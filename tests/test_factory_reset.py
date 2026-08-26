#!/usr/bin/env python3
"""Gathering devices on the factory address (panel.ip_assign.reset_to_factory).

Two field situations used to lock this flow; the tests pin both down:

  · The device is NOT at its DeviceMap address. After the operation has run
    once, most devices are already on the factory address and nobody answers
    the old ones. That is not a failure.
  · TWO devices share an address (arp-scan's "DUP: 2"). In a single pass a
    write to that address reaches only one of them; the second becomes visible
    only once the address frees up. Hence the flow runs pass by pass.

The network is imitated by a fake module standing in for the script
(field_scripts/intercom_ip_assign.py): the contract is whatever the real
functions offer — probe_all reports the answering addresses, write_ip moves a
device, host_mac says which device is currently at an address.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from panel import api, credentials, jobs
from panel.api.routes import ip_routes
from panel.ip_assign import audit, factory_reset, runner
from panel.probe import switch as switch_probe

from .support import fakes
from .support.base import PanelTest


def _topology(count: int = 3) -> dict:
    """Intercoms on ports 11..(10+count); IPs 10.1.1.10, .11, ...

    Extensions are ordered by port as in the field (2001, 2002, …): because
    the device reports its own extension, the row match comes from there.
    """
    return fakes.device_map([{
        "Name": f"Intercom_{i}", "IP": f"10.1.1.{9 + i}", "IsActive": True,
        "Type": "Announcement", "SubType": "Intercom", "Port": str(10 + i),
        "PBXExtension": f"200{i}" if i < 10 else f"20{i}",
        "Status": {"NoError": True},
    } for i in range(1, count + 1)], switch_ip="10.1.1.101")


def _template_topology(count: int = 3) -> dict:
    """The same layout with addresses resolved from the requested set."""
    return fakes.device_map([{
        "Name": f"Intercom_{i}", "IP": f"10.n.1.{9 + i}",
        "IsActive": True, "Type": "Announcement", "SubType": "Intercom",
        "Port": str(10 + i), "PBXExtension": f"200{i}",
        "Status": {"NoError": True},
    } for i in range(1, count + 1)], switch_ip="10.n.1.101")


class FakeNetwork:
    """A small world standing in for the script's network functions.

    `layout`: {ip: [mac, ...]} — several devices can share one address, which
    is exactly the field collision. A request to the address reaches the FIRST
    device in the list; once it moves, the one behind it becomes visible.
    """

    def __init__(self, layout: dict[str, list[str]], deaf: set | None = None,
                 hidden: dict[str, int] | None = None):
        self.layout = {ip: list(m) for ip, m in layout.items()}
        # Devices that take the write request and stay put (write ignored).
        self.deaf = set(deaf or ())
        # {address: how many probes it stays invisible for} — the stale ARP
        # entry: a device is there, but the OS asks a MAC that has moved so
        # no answer arrives.
        self.hidden = dict(hidden or {})
        self.writes: list[tuple[str, str]] = []
        # Call order: did "probe" come first, or "arp" (see
        # test_it_probes_first_then_flushes_arp).
        self.trace: list[str] = []

    # ---- the script's contract ----
    def read_settings(self, ip, config):
        if self.hidden.get(ip, 0) > 0:
            return None
        queue = self.layout.get(ip)
        if queue:
            # Like a real device: it reports its own extension too. In the
            # fake network a device's identity and extension are one string.
            return {"netmask": "255.255.0.0", "gateway": "10.1.1.101",
                    "ip": ip, "pbxExtension": queue[0]}
        return None

    def probe_all(self, candidates, config):
        self.trace.append("probe")
        found = {ip: s for ip, s in
                 ((ip, self.read_settings(ip, config)) for ip in candidates)
                 if s is not None}
        # Each probe brings a hidden address one step closer to visibility.
        for ip, remaining in list(self.hidden.items()):
            self.hidden[ip] = max(0, remaining - 1)
        return found

    def write_ip(self, ip, settings, new_ip, config):
        self.writes.append((ip, new_ip))
        queue = self.layout.get(ip) or []
        if not queue:
            raise RuntimeError("no device on that address")
        mac = queue[0]
        if mac in self.deaf:
            return
        queue.pop(0)
        self.layout.setdefault(new_ip, []).append(mac)

    def arp_forget(self, addresses, config=None):
        self.trace.append("arp")
        return True

    def host_mac(self, ip):
        queue = self.layout.get(ip) or []
        return queue[0] if queue else None

    def module(self):
        return SimpleNamespace(
            read_settings=self.read_settings, probe_all=self.probe_all,
            write_ip=self.write_ip, arp_forget=self.arp_forget,
            host_mac=self.host_mac)


class FactoryReset(PanelTest):

    def build(self, layout, deaf=None, count=3, arp=True, hidden=None):
        """Sets up the fake network.

        `arp`: whether the ARP cache can be flushed. With the privilege, an
        address that does not answer really is empty; without it the flow
        waits and retries (see EMPTY_PASS_TOLERANCE).
        """
        inventory = self.build_map(_topology(count))
        network = FakeNetwork(layout, deaf, hidden)
        self.network = network
        patches = (
            mock.patch.object(factory_reset.script_loader,
                              "intercom_ip_assign", network.module),
            mock.patch.object(factory_reset, "can_flush_arp", lambda: arp),
            # Waiting is meaningless in a test: the fake network answers
            # instantly and no ARP entry ever goes stale.
            mock.patch.object(factory_reset, "RESET_WAIT", 0.0),
            mock.patch.object(factory_reset, "PASS_INTERVAL_UNPRIVILEGED", 0.0),
            mock.patch.object(factory_reset, "PASS_INTERVAL_PRIVILEGED", 0.0),
            mock.patch.object(factory_reset, "PROBE_INTERVAL", 0.0),
            mock.patch.object(audit, "script_loader",
                              SimpleNamespace(
                                  intercom_ip_assign=network.module)),
            mock.patch.object(audit, "PASS_INTERVAL", 0.0),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return inventory

    def run_reset(self, inventory, ports=(11, 12, 13), cancelled=None):
        job = jobs.Job("ipfactory", "Reset to the factory IP", 1)
        summary = factory_reset.reset_to_factory(
            inventory, inventory.switches()[0].id, list(ports), ["Intercom"],
            job, options={"factoryIp": "10.1.1.12"}, cancelled=cancelled)
        return job, summary

    @staticmethod
    def rows(job):
        return {row["deviceId"]: row for row in job.rows()}

    # ── the ordinary flow ─────────────────────────────────────────────
    def test_devices_are_gathered_from_their_own_addresses(self):
        inventory = self.build({"10.1.1.10": ["a"], "10.1.1.11": ["b"],
                                "10.1.1.12": ["c"]})
        job, summary = self.run_reset(inventory)

        self.assertEqual(self.network.layout["10.1.1.12"], ["c", "a", "b"])
        self.assertEqual(summary["written"], 2)
        self.assertEqual(summary["failed"], 0)
        rows = self.rows(job)
        self.assertEqual(rows["p11"]["state"], "done")
        self.assertEqual(rows["p12"]["state"], "done")
        # Port 13's DeviceMap address is already the factory address: nothing
        # to write, but the row must not be missing either.
        self.assertEqual(rows["p13"]["state"], "done")
        self.assertEqual(job.progress(), 1.0)

    def test_the_percentage_advances_before_the_job_ends(self):
        """In the old flow the bar stayed at 0% from start to finish."""
        inventory = self.build({"10.1.1.10": ["a"], "10.1.1.11": ["b"]})
        ratios = []
        real = jobs.Job.set_progress

        def watch(self_, ratio):
            ratios.append(ratio)
            real(self_, ratio)

        with mock.patch.object(jobs.Job, "set_progress", watch):
            job, _ = self.run_reset(inventory)
        between = [r for r in ratios if 0.0 < r < 1.0]
        self.assertTrue(between, "no intermediate ratio was written while running")
        self.assertEqual(job.progress(), 1.0)
        self.assertEqual(job.phase, "")

    # ── two devices on one address ────────────────────────────────────
    def test_both_devices_on_one_address_are_gathered(self):
        """The field bug: two devices stayed on 10.1.1.14 and stayed there.

        One pass is not enough; the second device appears once the address
        frees up.
        """
        inventory = self.build({"10.1.1.10": ["a", "b"]})
        job, summary = self.run_reset(inventory)

        self.assertEqual(self.network.layout.get("10.1.1.10"), [])
        self.assertEqual(self.network.layout["10.1.1.12"], ["a", "b"])
        self.assertEqual(summary["written"], 2)
        self.assertEqual(summary["failed"], 0)

    def test_empty_retries_do_not_count_as_passes(self):
        """A pass in the phase text is a pass WHERE A DEVICE WAS FOUND.

        Counting deviceless retries as passes showed "pass 8" to the user on a
        two-device collision and made the job look long; it had in fact
        finished on the second pass.
        """
        inventory = self.build({"10.1.1.10": ["a", "b"]})
        phases = []
        real = jobs.Job.set_phase

        def watch(self_, text):
            phases.append(text)
            real(self_, text)

        with mock.patch.object(jobs.Job, "set_phase", watch):
            self.run_reset(inventory, ports=(11,))

        self.assertTrue(any("pass 2" in p for p in phases))
        self.assertFalse([p for p in phases if "3. tur" in p],
                         "a repeat that found no device must not count as a pass")
        self.assertTrue(any("looking again" in p for p in phases))

    def test_the_second_device_lands_on_its_own_row_via_mac(self):
        """With switch credentials the found device goes to its port's row."""
        inventory = self.build({"10.1.1.10": ["a", "b"]})
        switch = inventory.switches()[0]
        credentials.remember(switch.id, switch.ip, "admin", "p",
                             group="switch")
        with mock.patch.object(switch_probe, "mac_table",
                               lambda *a, **k: {"a": 11, "b": 12}):
            job, summary = self.run_reset(inventory)

        rows = self.rows(job)
        self.assertEqual(rows["p11"]["state"], "done")
        # The second device was found at 10.1.1.10 but its MAC points at 12.
        self.assertEqual(rows["p12"]["state"], "done")
        self.assertIn("10.1.1.10", rows["p12"]["note"])
        self.assertEqual(summary["written"], 2)

    def test_a_device_lands_on_its_own_row_via_its_extension(self):
        """The field case: the device at 10.1.1.13 belonged to port 22.

        Because the device reports its own extension, the right row is found
        without switch credentials or ARP.
        """
        inventory = self.build({"10.1.1.10": ["2004"]}, count=4)
        job, summary = self.run_reset(inventory, ports=(11, 12, 13, 14))

        rows = self.rows(job)
        # 10.1.1.10 is port 11's address in DeviceMap, but the device there
        # belongs to port 14 (extension 2004).
        self.assertEqual(rows["p14"]["state"], "done")
        self.assertIn("extension 2004", rows["p14"]["note"])
        self.assertEqual(rows["p11"]["state"], "skipped")
        self.assertEqual(summary["written"], 1)

    def test_a_device_outside_the_selected_ports_is_untouched(self):
        """If the MAC points at another port, that device is not our business."""
        inventory = self.build({"10.1.1.10": ["x"]})
        switch = inventory.switches()[0]
        credentials.remember(switch.id, switch.ip, "admin", "p",
                             group="switch")
        with mock.patch.object(switch_probe, "mac_table",
                               lambda *a, **k: {"x": 20}):
            _job, summary = self.run_reset(inventory, ports=(11,))

        self.assertEqual(self.network.writes, [])
        self.assertEqual(summary["written"], 0)

    # ── addresses that do not answer ──────────────────────────────────
    def test_no_answer_at_its_address_is_not_a_failure(self):
        """On a second run the devices are already on the factory address."""
        inventory = self.build({"10.1.1.12": ["a", "b", "c"]})
        job, summary = self.run_reset(inventory)

        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["written"], 0)
        self.assertTrue(summary["factoryAnswers"])
        rows = self.rows(job)
        self.assertEqual(rows["p11"]["state"], "skipped")
        self.assertIn("may already be on", rows["p11"]["note"])
        # There IS an answer on the factory address: the job is not painted red.
        from panel.api.tasks.ip_task import _factory_reset_error
        self.assertIsNone(_factory_reset_error(summary))

    def test_the_job_fails_when_nothing_answers_anywhere(self):
        inventory = self.build({})
        _job, summary = self.run_reset(inventory)

        self.assertFalse(summary["factoryAnswers"])
        from panel.api.tasks.ip_task import _factory_reset_error
        self.assertIn("No device was found",
                      _factory_reset_error(summary))

    # ── while the ARP cache cannot be flushed ─────────────────────────
    def test_a_device_invisible_on_the_first_probe_is_still_found(self):
        """One probe is not enough to say "nobody is here".

        Measured in the field: a resolved address answers in 0.01 s, while an
        address whose ARP entry was just deleted can stay silent for the whole
        probe timeout. Because the run deletes the entry every pass this
        happens EVEN WITH the privilege — and the old flow counted every
        device as "no answer" right here and finished having done nothing.
        """
        # With the privilege fewer retries (the flush really works), without
        # it more: in both, the first probe is not the last word.
        for arp, hidden in ((True, 2), (False, 4)):
            with self.subTest(arp=arp):
                inventory = self.build({"10.1.1.10": ["a"]}, arp=arp,
                                       hidden={"10.1.1.10": hidden})
                _job, summary = self.run_reset(inventory, ports=(11,))

                self.assertEqual(summary["written"], 1)
                self.assertEqual(self.network.layout["10.1.1.12"], ["a"])

    def test_it_probes_first_then_flushes_arp(self):
        """The ARP flush does NOT happen BEFORE the probe.

        Deleting the entry forces the address to be resolved again, and
        resolution can take longer than the probe timeout. Deleting every
        candidate's entry at the start of a pass was what made all the field
        devices go "no answer" at once. The entry is flushed only when no
        answer came.
        """
        inventory = self.build({"10.1.1.10": ["a"]})
        self.run_reset(inventory, ports=(11,))

        self.assertEqual(self.network.trace[0], "probe",
                         "the first thing must be a probe, not an ARP flush")

    def test_an_invisible_device_is_not_waited_for_forever(self):
        """Retrying has an end too: the job does not get stuck."""
        inventory = self.build({"10.1.1.10": ["a"]},
                               hidden={"10.1.1.10": 99})
        _job, summary = self.run_reset(inventory, ports=(11,))

        self.assertEqual(summary["written"], 0)
        self.assertEqual(summary["skipped"], 1)

    def test_the_summary_warns_when_arp_cannot_be_flushed(self):
        """Unprivileged, "no answer" is not certain — and is not stated so."""
        inventory = self.build({"10.1.1.12": ["a"]}, arp=False)
        _job, summary = self.run_reset(inventory, ports=(11,))

        self.assertFalse(summary["arpFlush"])
        from panel.api.tasks.ip_task import _factory_reset_error
        self.assertIn("administrator/sudo", _factory_reset_error(summary))

    def test_a_row_fails_when_the_write_is_ignored(self):
        """A device that takes the request and stays put is a failure."""
        inventory = self.build({"10.1.1.10": ["a"]}, deaf={"a"})
        job, summary = self.run_reset(inventory, ports=(11,))

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(self.rows(job)["p11"]["state"], "failed")
        from panel.api.tasks.ip_task import _factory_reset_error
        self.assertIn("could not be reset", _factory_reset_error(summary))

    # ── stopping ──────────────────────────────────────────────────────
    def test_a_stopped_job_does_not_fill_the_percentage(self):
        inventory = self.build({"10.1.1.10": ["a"], "10.1.1.11": ["b"]})
        job, summary = self.run_reset(inventory, cancelled=lambda: True)

        self.assertTrue(summary["stopped"])
        self.assertEqual(self.network.writes, [])
        self.assertLess(job.progress(), 1.0)
        self.assertEqual(self.rows(job)["p11"]["state"], "skipped")


class FactoryResetApi(PanelTest):
    """The route chooses the source inventory; the engine must not guess it."""

    def setUp(self):
        super().setUp()
        self.build_map(_template_topology())

    @staticmethod
    def request(set_no):
        return {
            "set": set_no,
            "switch": "sw1",
            "groups": ["Intercom"],
            "ports": "11-12",
            "factoryIp": "10.1.1.12",
        }

    def test_an_external_set_resolves_the_inventory_and_owns_the_job(self):
        """Set 14 means the devices currently live on the 10.14.1.x plan."""
        queued = {}

        def submit(job, body):
            queued.update(job=job, body=body)
            return job, True

        task_body = object()
        with (mock.patch.object(ip_routes, "factory_reset_task",
                                return_value=task_body) as make_task,
              mock.patch.object(ip_routes.jobs.QUEUE, "submit",
                                side_effect=submit)):
            response = api.call("POST", "/api/ip/factory-reset",
                                body=self.request("14"))

        self.assertEqual(response.status, 200)
        inventory, switch_id, ports, groups, options = make_task.call_args.args
        self.assertEqual(inventory.set_no, 14)
        self.assertEqual(inventory.find("sw1").ip, "10.14.1.101")
        self.assertEqual(
            [device.ip for device in inventory.devices
             if device.id in ("sw1.d1", "sw1.d2")],
            ["10.14.1.10", "10.14.1.11"])
        self.assertEqual((switch_id, ports, groups),
                         ("sw1", [11, 12], ["Intercom"]))
        self.assertEqual(options["factoryIp"], "10.1.1.12")
        self.assertIs(queued["body"], task_body)
        self.assertEqual(queued["job"].set_no, 14)
        self.assertEqual(queued["job"].key, "ipfactory:14:sw1")
        self.assertEqual(response.body["setNo"], 14)

    def test_ip_write_routes_reject_an_invalid_set_instead_of_using_set_one(self):
        bad_values = (None, "", 0, 255, "abc", 14.5, True, False)
        for path in ("/api/ip/run", "/api/ip/factory-reset"):
            for bad in bad_values:
                with self.subTest(path=path, value=bad):
                    with mock.patch.object(ip_routes.jobs.QUEUE,
                                           "submit") as submit:
                        response = api.call("POST", path,
                                            body=self.request(bad))
                    self.assertEqual(response.status, 400)
                    self.assertIn("Invalid set number", response.body["error"])
                    submit.assert_not_called()


class PersistenceOption(unittest.TestCase):
    """The removed persistence option cannot be revived by an old client."""

    def _argv(self, persistence: bool) -> list[str]:
        captured = {}

        def execute(_module, argv, _emit, _cancelled=None):
            captured["argv"] = argv
            return 0

        with (mock.patch.object(runner.script_loader, "intercom_ip_assign",
                                lambda: SimpleNamespace(main=lambda: 0)),
              mock.patch.object(runner, "_execute", execute)):
            inventory = SimpleNamespace(set_no=1, source="DeviceMap.json")
            switch = SimpleNamespace(ip="10.1.1.101")
            runner._run_intercom(inventory, switch, [11], ("admin", "p"),
                                 lambda _line: None,
                                 {"persistenceCheck": persistence})
        return captured["argv"]

    def test_always_disabled_by_default(self):
        self.assertIn("--no-persist-check", self._argv(False))

    def test_legacy_true_value_is_ignored(self):
        self.assertIn("--no-persist-check", self._argv(True))


class IdentityAudit(FactoryReset):
    """After the run: is the RIGHT device at the target address?

    The script picks a device by guessing at uptime and does not check who it
    is; in the field three devices gathered on one target address and one
    device had been written to another port's address. Because the device
    reports its own extension, this can be checked for certain after the run.
    """

    def audit(self, inventory, ports=(11, 12, 13), **kwargs):
        return audit.audit_identities(
            inventory, inventory.switches()[0].id, list(ports), ["Intercom"],
            options={"factoryIp": "10.1.1.12"}, **kwargs)

    @staticmethod
    def row(result, port):
        return next(r for r in result["rows"] if r["port"] == port)

    def test_the_right_device_at_the_right_address(self):
        inventory = self.build({"10.1.1.10": ["2001"], "10.1.1.11": ["2002"]},
                               count=3)
        result = self.audit(inventory, passes=1)

        self.assertEqual(self.row(result, 11)["state"], "correct")
        self.assertEqual(self.row(result, 12)["state"], "correct")
        self.assertEqual(result["counts"]["correct"], 2)

    def test_a_write_to_the_wrong_device_is_caught(self):
        """The case the run calls "completed" but got mixed up."""
        # Port 13's device sits at port 11's address.
        inventory = self.build({"10.1.1.10": ["2003"]}, count=3)
        result = self.audit(inventory, passes=1)

        row = self.row(result, 11)
        self.assertEqual(row["state"], "wrong")
        self.assertEqual(row["expectedExtension"], "2001")
        self.assertEqual(row["found"][0]["name"], "Intercom_3")
        self.assertEqual(result["counts"]["wrong"], 1)

        from panel.api.tasks.ip_task import _identity_error
        self.assertIn("DIFFERENT device", _identity_error(result["counts"]))

    def test_two_devices_on_one_address_is_a_conflict(self):
        inventory = self.build({"10.1.1.10": ["2001", "2002"]}, count=3)
        network = self.network

        def rotate(*_a, **_k):
            queue = network.layout.get("10.1.1.10") or []
            if len(queue) > 1:
                queue.append(queue.pop(0))
            return True

        with mock.patch.object(network, "arp_forget", rotate):
            result = self.audit(inventory, passes=2)

        self.assertEqual(self.row(result, 11)["state"], "conflict")

    def test_a_silent_address_does_not_count_as_wrong(self):
        """Silence is its own state: the run already reports it."""
        inventory = self.build({}, count=3)
        result = self.audit(inventory, passes=1)

        self.assertEqual(result["counts"]["silent"], 3)
        self.assertEqual(result["counts"]["wrong"], 0)

    def test_the_identity_check_writes_nothing(self):
        inventory = self.build({"10.1.1.10": ["2003"]}, count=3)
        self.audit(inventory, passes=2)

        self.assertEqual(self.network.writes, [])


class AddressMap(FactoryReset):
    """The diagnostic screen's data: which device is at which address.

    In the field this was answered by hand with `arp-scan` and only at MAC
    level; thanks to the device's own extension the panel can say "the device
    at this address actually belongs to this port".
    """

    def map(self, inventory, **kwargs):
        return audit.address_map(
            inventory, inventory.switches()[0].id, ["Intercom"],
            options={"factoryIp": "10.1.1.12"}, **kwargs)

    @staticmethod
    def row(result, ip):
        return next(r for r in result["rows"] if r["ip"] == ip)

    def test_a_device_at_its_own_address_is_expected(self):
        inventory = self.build({"10.1.1.10": ["2001"]}, count=3)
        result = self.map(inventory, passes=1)

        row = self.row(result, "10.1.1.10")
        self.assertEqual(row["state"], "expected")
        self.assertEqual(row["found"][0]["port"], 11)
        self.assertEqual(self.row(result, "10.1.1.11")["state"], "empty")

    def test_a_device_at_another_device_address_is_flagged(self):
        """The field table: port 22's device sat at 10.1.1.13."""
        inventory = self.build({"10.1.1.10": ["2003"]}, count=3)
        result = self.map(inventory, passes=1)

        row = self.row(result, "10.1.1.10")
        self.assertEqual(row["state"], "foreign")
        self.assertEqual(row["expectedPort"], 11)       # the address is 11's
        self.assertEqual(row["found"][0]["port"], 13)   # the device there is 13's

    def test_two_devices_on_one_address_show_as_a_conflict(self):
        """One probe does not reveal a collision; it is looked at pass by pass."""
        inventory = self.build({"10.1.1.10": ["2001", "2002"]}, count=3)
        # In the fake network a request reaches the first in the list; the
        # second appears only when the order changes (in reality, when the ARP
        # entry turns over).
        network = self.network

        def rotate(*_a, **_k):
            queue = network.layout.get("10.1.1.10") or []
            if len(queue) > 1:
                queue.append(queue.pop(0))
            return True

        with mock.patch.object(network, "arp_forget", rotate):
            result = self.map(inventory, passes=2)

        row = self.row(result, "10.1.1.10")
        self.assertEqual(row["state"], "conflict")
        self.assertEqual([f["extension"] for f in row["found"]],
                         ["2001", "2002"])
        self.assertEqual(result["counts"]["conflict"], 1)

    def test_the_factory_address_is_always_in_the_list(self):
        """The address the devices gather on is the map's first question."""
        inventory = self.build({"10.1.1.12": ["2002"]}, count=3)
        result = self.map(inventory, passes=1)

        row = self.row(result, "10.1.1.12")
        self.assertTrue(row["isFactory"])
        # Who stands on the factory address is not "wrong".
        self.assertEqual(row["state"], "expected")
        self.assertEqual(row["found"][0]["name"], "Intercom_2")

    def test_the_map_writes_nothing(self):
        inventory = self.build({"10.1.1.10": ["2001"], "10.1.1.12": ["2003"]},
                               count=3)
        self.map(inventory, passes=2)

        self.assertEqual(self.network.writes, [])


if __name__ == "__main__":
    unittest.main()
