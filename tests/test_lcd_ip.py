#!/usr/bin/env python3
"""Compartment LCD commissioning: port isolation, ADB identity and /24."""
from __future__ import annotations

import json
import re
import subprocess
from contextlib import ExitStack
from unittest import mock

from panel import credentials
from panel.errors import AuthError
from panel.inventory import catalog, device_map
from panel.ip_assign import lcd_runner, runner
from panel.ip_assign.plan import build_plan

from .support import fakes
from .support.base import PanelTest


class Result:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeAdb:
    """An ADB server whose TCP serial changes when eth0 changes address."""

    def __init__(self, devices, *, apply_write=True, changed_serial="",
                 extra_after_write=(), write_timeout=False):
        # ip -> {serial, cidr, port}
        self.live = {ip: dict(record) for ip, record in devices.items()}
        self.connected: set[str] = set()
        self.calls: list[list[str]] = []
        self.timeline: list[str] = []
        self.apply_write = apply_write
        self.changed_serial = changed_serial
        self.extra_after_write = set(extra_after_write)
        self.write_timeout = write_timeout

    @staticmethod
    def ip_of(target: str) -> str:
        return target.rsplit(":", 1)[0]

    def __call__(self, args, **_kwargs):
        args = list(args)
        self.calls.append(args)
        if args[1] == "disconnect":
            self.connected.discard(self.ip_of(args[2]))
            self.timeline.append(f"disconnect:{self.ip_of(args[2])}")
            return Result("disconnected\n")
        if args[1] == "connect":
            ip = self.ip_of(args[2])
            if ip in self.live:
                self.connected.add(ip)
                return Result(f"connected to {args[2]}\n")
            return Result(f"failed to connect to {args[2]}\n", returncode=1)

        assert args[1] == "-s", args
        ip = self.ip_of(args[2])
        if args[3] == "get-state":
            return (Result("device\n") if ip in self.connected and ip in self.live
                    else Result("", "offline\n", 1))
        assert args[3] == "shell", args
        if ip not in self.connected or ip not in self.live:
            return Result("", "device offline\n", 1)
        if args[4:6] == ["getprop", "ro.serialno"]:
            return Result(self.live[ip]["serial"] + "\n")
        if args[4:8] == ["ip", "-o", "-4", "addr"]:
            cidrs = self.live[ip].get("cidrs") or {self.live[ip]["cidr"]}
            return Result("".join(
                f"2: eth0    inet {cidr} scope global eth0\n"
                for cidr in sorted(cidrs)))
        if len(args) >= 7 and args[4:6] == ["su", "-c"]:
            script = args[6]
            match = re.search(r"ip addr add ([0-9.]+)/(\d+)", script)
            assert match, script
            new_ip, prefix = match.group(1), match.group(2)
            self.timeline.append(f"write:{ip}->{new_ip}/{prefix}")
            old = self.live.pop(ip)
            self.connected.discard(ip)
            if self.apply_write:
                self.live[new_ip] = {
                    **old,
                    "serial": self.changed_serial or old["serial"],
                    "cidr": f"{new_ip}/{prefix}",
                    "cidrs": {f"{new_ip}/{prefix}", *self.extra_after_write},
                }
            # Losing the command response is allowed; reconnect is authoritative.
            if self.write_timeout:
                raise subprocess.TimeoutExpired(args, 1)
            return Result()
        return Result("", "unexpected command\n", 1)


class FakeSwitch:
    def __init__(self, adb: FakeAdb, ports=(13, 14)):
        self.adb = adb
        self.ports = tuple(ports)
        self.poe_calls: list[set[int]] = []
        self._MAC_CACHE = {}

    def poe_read(self, _cfg):
        return [{"pid": port, "poeMode": "1", "priority": "0",
                 "maxPower": "154"} for port in self.ports]

    def poe_apply(self, _cfg, _state, enabled, _managed):
        self.poe_calls.append(set(enabled))

    @staticmethod
    def wait_for_link(_cfg, _port, _timeout):
        return True, 0.0

    @staticmethod
    def arp_forget(_ips, _cfg=None):
        return True

    def verify_port(self, ip, expected_port, _cfg):
        record = self.adb.live.get(ip)
        if record is None:
            return None, "no MAC in ARP"
        actual = record["port"]
        return actual == expected_port, f"MAC fake -> port {actual}"


def events(lines):
    return [json.loads(line[5:]) for line in lines if line.startswith("@EVT ")]


class CompartmentLcdPlan(PanelTest):
    def inventory(self, set_no=7, count=2, second_switch=False):
        devices = [{
            "Name": f"Compartment_Lcd_{index + 1}",
            "IP": f"10.n.1.{40 + index}", "IsActive": True,
            "Type": "LCD", "SubType": "Compartment",
            "Port": str(13 + index), "Status": {},
        } for index in range(count)]
        second = ({
            "Name": "Bench_SW_2", "IP": "10.n.1.102",
            "IsActive": True, "Manufacturer": "KYLAND",
            "Status": {"NoError": True}, "Devices": [],
        } if second_switch else None)
        self.build_map(fakes.device_map(
            devices, switch_ip="10.n.1.101", second_switch=second))
        return device_map.load(set_no, self.map_path, cache=False)

    def test_the_catalogue_and_plan_publish_per_device_sources(self):
        inventory = self.inventory(7)
        group = catalog.find_group("Compartment LCD")
        self.assertTrue(catalog.group_supports(group, "ip"))

        plan = build_plan(inventory, "Compartment LCD", [13, 14], "sw1")
        self.assertEqual(plan["withoutRunner"], [])
        self.assertEqual(plan["targetPrefix"], 24)
        self.assertTrue(plan["physicalPortMode"])
        self.assertEqual(
            [(row["sourceIp"], row["factoryIp"], row["targetIp"],
              row["targetPrefix"]) for row in plan["candidateRows"]],
            [("10.1.1.40", "10.1.1.40", "10.7.1.40", 24),
             ("10.1.1.41", "10.1.1.41", "10.7.1.41", 24)])
        self.assertTrue(all(row["identityMode"] == "discover"
                            and row["deviceId"] is None
                            for row in plan["rows"]))

    def test_switch_two_plan_uses_switch_one_as_the_immutable_device_map(self):
        inventory = self.inventory(7, second_switch=True)

        plan = build_plan(
            inventory, "Compartment LCD", [13, 14], "sw2")

        self.assertEqual(plan["switchId"], "sw2")
        self.assertEqual(plan["switchIp"], "10.7.1.102")
        self.assertEqual(plan["deviceSwitchId"], "sw1")
        self.assertTrue(plan["switchOverride"])
        self.assertEqual([row["deviceId"] for row in plan["candidateRows"]],
                         ["sw1.d1", "sw1.d2"])


class CompartmentLcdRun(CompartmentLcdPlan):
    def setUp(self):
        super().setUp()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # The four settle/retry intervals used to be zeroed here. They are
        # durations, and durations cost nothing now (tests/support/clock.py),
        # so the run exercises the real ones.

    def run_manual(self, inventory, adb, port=8, options=None,
                   cancelled=None, ports=(8,)):
        switch_api = FakeSwitch(adb, ports=ports)
        lines = []
        self.stack.enter_context(mock.patch.object(
            lcd_runner.script_loader, "intercom_ip_assign",
            return_value=switch_api))
        self.stack.enter_context(mock.patch.object(
            lcd_runner.subprocess, "run", side_effect=adb))
        code = lcd_runner.run_manual(
            inventory, inventory.switches()[0], port, ("admin", "pw"),
            lines.append, options or {}, cancelled=cancelled)
        return code, switch_api, lines

    def run_lcd(self, inventory, adb, ports=(13,), options=None,
                cancelled=None, install=None, switch_index=0):
        switch_api = FakeSwitch(adb, ports=ports)
        lines = []
        self.stack.enter_context(mock.patch.object(
            lcd_runner.script_loader, "intercom_ip_assign",
            return_value=switch_api))
        self.stack.enter_context(mock.patch.object(
            lcd_runner.subprocess, "run", side_effect=adb))
        if install is not None:
            self.stack.enter_context(mock.patch.object(
                lcd_runner.firmware, "has_selection", return_value=True))
            self.stack.enter_context(mock.patch.object(
                lcd_runner.firmware, "install", side_effect=install))
        code = lcd_runner.run(
            inventory, inventory.switches()[switch_index], list(ports),
            ("admin", "pw"),
            lines.append, options or {}, cancelled=cancelled)
        return code, switch_api, lines

    def test_generic_runner_uses_switch_two_credentials_and_the_lcd_map_from_one(self):
        inventory = self.inventory(7, count=1, second_switch=True)
        physical = inventory.switches()[1]
        credentials.remember(physical.id, physical.ip, "bench", "pw",
                             group="switch")
        called = {}

        def capture(_inventory, switch, ports, account, _emit, options,
                    _cancelled):
            called.update(switch=switch, ports=ports, account=account,
                          options=options)
            return 0

        with mock.patch.dict(runner.RUNNERS,
                             {"Compartment LCD": capture}):
            code = runner.run(
                inventory, "sw2", [13], lambda _line: None,
                groups=["Compartment LCD"])

        self.assertEqual(code, 0)
        self.assertEqual(called["switch"].id, "sw2")
        self.assertEqual(called["account"], ("bench", "pw"))
        self.assertEqual(called["ports"], [13])
        self.assertEqual(called["options"]["_deviceSwitchId"], "sw1")

    def test_switch_one_credentials_do_not_authorize_a_switch_two_run(self):
        inventory = self.inventory(7, count=1, second_switch=True)
        source = inventory.switches()[0]
        credentials.remember(source.id, source.ip, "source", "pw",
                             group="switch")

        with self.assertRaises(AuthError):
            runner.run(inventory, "sw2", [13], lambda _line: None,
                       groups=["Compartment LCD"])

    def test_switch_two_override_still_rejects_a_device_on_the_wrong_port(self):
        inventory = self.inventory(7, count=1, second_switch=True)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 14},
        })

        code, _switch, lines = self.run_lcd(
            inventory, adb, options={"_deviceSwitchId": "sw1"},
            switch_index=1)

        self.assertEqual(code, 1)
        self.assertFalse(any("su" in call for call in adb.calls))
        failed = [event for event in events(lines)
                  if event["event"] == "port_failed"]
        self.assertIn("port 14", failed[0]["reason"])

    def test_arbitrary_physical_port_discovers_the_canonical_lcd_identity(self):
        inventory = self.inventory(7, count=2)
        adb = FakeAdb({
            # DeviceMap stores this display on port 14.  A test cable moves it
            # to port 8; its own immutable .41 identity must still win.
            "10.1.1.41": {"serial": "LCD-41", "cidr": "10.1.1.41/16",
                            "port": 8},
        })

        code, _switch, lines = self.run_lcd(inventory, adb, ports=(8,))

        self.assertEqual(code, 0)
        self.assertEqual(set(adb.live), {"10.7.1.41"})
        self.assertTrue(any("su" in call for call in adb.calls))
        self.assertFalse(any("10.7.1.40" in " ".join(call)
                             and "su" in call for call in adb.calls))
        identified = [event for event in events(lines)
                      if event["event"] == "port_identified"]
        self.assertEqual(
            [(row["port"], row["name"], row["target"])
             for row in identified],
            [(8, "Compartment_Lcd_2", "10.7.1.41")])
        found = [event for event in events(lines)
                 if event["event"] == "port_step"
                 and event.get("step") == "device_found"]
        self.assertIn("Compartment_Lcd_2", found[0]["detail"])

    def test_missing_device_discovery_has_a_bounded_number_of_adb_calls(self):
        inventory = self.inventory(7, count=11)
        adb = FakeAdb({})

        code, _switch, _lines = self.run_lcd(inventory, adb, ports=(8,))

        self.assertEqual(code, 1)
        # 22 unique source/target addresses, two sweeps, and at most
        # disconnect+connect+get-state per address.
        self.assertLessEqual(len(adb.calls), 22 * 2 * 3)
        self.assertFalse(adb.connected)
        self.assertFalse(any("kill-server" in call for call in adb.calls))

    def test_wrong_port_reachable_transports_are_cleaned_after_discovery(self):
        inventory = self.inventory(7, count=2)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 9},
            "10.1.1.41": {"serial": "LCD-41", "cidr": "10.1.1.41/16",
                            "port": 8},
        })

        code, _switch, _lines = self.run_lcd(inventory, adb, ports=(8,))

        self.assertEqual(code, 0)
        self.assertFalse(adb.connected)
        self.assertIn("disconnect:10.1.1.40", adb.timeline)

    def test_source_devices_move_port_by_port_and_completed_ports_stay_on(self):
        inventory = self.inventory(7)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
            "10.1.1.41": {"serial": "LCD-41", "cidr": "10.1.1.41/16",
                            "port": 14},
        })

        code, switch_api, lines = self.run_lcd(
            inventory, adb, ports=(13, 14))

        self.assertEqual(code, 0)
        self.assertEqual(set(adb.live), {"10.7.1.40", "10.7.1.41"})
        self.assertEqual(adb.live["10.7.1.40"]["cidr"], "10.7.1.40/24")
        # close all -> open 13 -> keep 13 while opening 14 -> final all open
        self.assertEqual(switch_api.poe_calls,
                         [set(), {13}, {13, 14}, {13, 14}])
        summaries = [e for e in events(lines) if e["event"] == "summary_row"]
        self.assertEqual([e["status"] for e in summaries], ["ok", "ok"])

        scoped = [call for call in adb.calls
                  if "shell" in call or "get-state" in call or "install" in call]
        self.assertTrue(scoped)
        self.assertTrue(all(call[1] == "-s" and call[2].endswith(":5555")
                            for call in scoped))
        flattened = " ".join(" ".join(call) for call in adb.calls)
        self.assertNotIn("kill-server", flattened)
        self.assertNotIn("adb devices", flattened)
        self.assertFalse(adb.connected)  # both old/new transports cleaned up

    def test_an_apk_is_installed_at_the_source_before_the_ip_transaction(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
        })

        def install(device, **_kwargs):
            self.assertEqual(device.ip, "10.1.1.40")
            adb.timeline.append("apk:10.1.1.40")
            # The real installer disconnects in its finally block.
            adb.connected.discard("10.1.1.40")
            return {"previous": "1", "current": "2", "changed": True}

        code, _switch, _lines = self.run_lcd(
            inventory, adb, options={"installApk": True}, install=install)

        self.assertEqual(code, 0)
        self.assertLess(adb.timeline.index("apk:10.1.1.40"),
                        adb.timeline.index("write:10.1.1.40->10.7.1.40/24"))

    def test_an_apk_failure_never_reaches_the_root_ip_command(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
        })

        def fail_install(*_args, **_kwargs):
            raise RuntimeError("APK verification failed")

        code, switch_api, lines = self.run_lcd(
            inventory, adb, options={"installApk": True},
            install=fail_install)

        self.assertEqual(code, 1)
        self.assertFalse(any(" su " in f" {' '.join(call)} "
                             for call in adb.calls))
        self.assertIn("10.1.1.40", adb.live)
        self.assertEqual(switch_api.poe_calls[-1], {13})
        failed = [e for e in events(lines) if e["event"] == "port_failed"]
        self.assertIn("APK verification failed", failed[0]["reason"])

    def test_a_stale_old_serial_is_disconnected_before_new_reconnect(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
        })
        # This is what remains from an earlier failed attempt in `adb devices`.
        adb.connected.add("10.7.1.40")

        code, _switch, _lines = self.run_lcd(inventory, adb)

        self.assertEqual(code, 0)
        write_at = adb.timeline.index("write:10.1.1.40->10.7.1.40/24")
        after = adb.timeline[write_at + 1:]
        self.assertIn("disconnect:10.1.1.40", after)
        self.assertIn("disconnect:10.7.1.40", after)
        self.assertEqual(adb.live["10.7.1.40"]["serial"], "LCD-40")

    def test_reconnect_failure_is_not_reported_as_a_success(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
        }, apply_write=False)

        code, switch_api, lines = self.run_lcd(inventory, adb)

        self.assertEqual(code, 1)
        self.assertEqual(switch_api.poe_calls[-1], {13})
        failed = [e for e in events(lines) if e["event"] == "port_failed"]
        self.assertIn("did not reconnect", failed[0]["reason"])
        summary = [e for e in events(lines) if e["event"] == "summary_row"]
        self.assertEqual(summary[0]["status"], "missing")

    def test_a_dropped_ip_command_reply_can_only_succeed_after_reconnect(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
        }, write_timeout=True)

        code, _switch, lines = self.run_lcd(inventory, adb)

        self.assertEqual(code, 0)
        self.assertEqual(adb.live["10.7.1.40"]["cidr"], "10.7.1.40/24")
        summary = [e for e in events(lines) if e["event"] == "summary_row"]
        self.assertEqual(summary[0]["status"], "ok")

    def test_set_one_is_still_rewritten_from_16_to_24(self):
        inventory = self.inventory(1, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
        })

        code, _switch, _lines = self.run_lcd(inventory, adb)

        self.assertEqual(code, 0)
        self.assertEqual(adb.live["10.1.1.40"]["cidr"], "10.1.1.40/24")
        writes = [call for call in adb.calls if "su" in call]
        self.assertEqual(len(writes), 1)
        self.assertIn("10.1.1.40/24", writes[0][-1])

    def test_set_one_already_on_the_exact_24_is_idempotent(self):
        inventory = self.inventory(1, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/24",
                            "port": 13},
        })

        code, _switch, lines = self.run_lcd(inventory, adb)

        self.assertEqual(code, 0)
        self.assertFalse(any("su" in call for call in adb.calls))
        written = [e for e in events(lines) if e["event"] == "port_written"]
        self.assertEqual(written[0]["reason"], "already_correct")

    def test_final_verification_rejects_a_leftover_old_prefix(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
        }, extra_after_write={"10.1.1.40/16"})

        code, _switch, lines = self.run_lcd(inventory, adb)

        self.assertEqual(code, 1)
        self.assertEqual(adb.live["10.7.1.40"]["cidrs"],
                         {"10.7.1.40/24", "10.1.1.40/16"})
        failed = [e for e in events(lines) if e["event"] == "port_failed"]
        self.assertIn("must contain only 10.7.1.40/24", failed[0]["reason"])

    def test_an_asked_for_mask_is_written_and_verified(self):
        """The mask is an option, not a constant of the system.

        A display is sometimes commissioned on a /8 so it stays reachable
        from the whole 10.0.0.0 range while the rest of the train is still
        being addressed.
        """
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/24",
                          "port": 13},
        })

        code, _switch, _lines = self.run_lcd(
            inventory, adb, options={"targetPrefix": 8})

        self.assertEqual(code, 0)
        self.assertEqual(adb.live["10.7.1.40"]["cidr"], "10.7.1.40/8")
        writes = [call for call in adb.calls if "su" in call]
        self.assertIn("10.7.1.40/8", writes[0][-1])

    def test_a_factory_reset_moves_the_display_back_to_its_set_one_address(self):
        """Not one shared address: every display keeps its own host octet."""
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.7.1.40": {"serial": "LCD-40", "cidr": "10.7.1.40/24",
                          "port": 13},
        })

        code, _switch, lines = self.run_lcd(
            inventory, adb, options={"sourceSet": 7, "targetSet": 1})

        self.assertEqual(code, 0)
        self.assertIn("10.1.1.40", adb.live)
        self.assertEqual(adb.live["10.1.1.40"]["cidr"], "10.1.1.40/24")
        self.assertIn("write:10.7.1.40->10.1.1.40/24", adb.timeline)
        identified = [e for e in events(lines)
                      if e["event"] == "port_identified"]
        self.assertEqual(identified[0]["target"], "10.1.1.40")

    def test_a_set_transfer_reads_one_set_and_writes_another(self):
        """Set 3 -> set 5: neither end is the factory or the open set."""
        inventory = self.inventory(5, count=1)
        adb = FakeAdb({
            "10.3.1.40": {"serial": "LCD-40", "cidr": "10.3.1.40/24",
                          "port": 13},
        })

        code, _switch, _lines = self.run_lcd(
            inventory, adb, options={"sourceSet": 3})

        self.assertEqual(code, 0)
        self.assertEqual(adb.live["10.5.1.40"]["cidr"], "10.5.1.40/24")
        self.assertIn("write:10.3.1.40->10.5.1.40/24", adb.timeline)

    def test_the_bench_flow_writes_the_typed_address_on_a_proved_port(self):
        """No DeviceMap row decides anything; the MAC still has to."""
        inventory = self.inventory(7, count=2)
        adb = FakeAdb({
            "10.1.1.41": {"serial": "LCD-41", "cidr": "10.1.1.41/24",
                          "port": 8},
        })

        code, switch_api, lines = self.run_manual(
            inventory, adb, port=8,
            options={"targetIp": "10.9.1.44", "targetPrefix": 8})

        self.assertEqual(code, 0)
        self.assertEqual(adb.live["10.9.1.44"]["cidr"], "10.9.1.44/8")
        self.assertIn("write:10.1.1.41->10.9.1.44/8", adb.timeline)
        # Only the selected port is powered, and it is reopened afterwards.
        self.assertEqual(switch_api.poe_calls, [set(), {8}, {8}])
        summary = [e for e in events(lines) if e["event"] == "summary_row"]
        self.assertEqual(summary[0]["status"], "ok")

    def test_the_bench_flow_never_writes_to_a_display_on_another_port(self):
        inventory = self.inventory(7, count=2)
        adb = FakeAdb({
            "10.1.1.41": {"serial": "LCD-41", "cidr": "10.1.1.41/24",
                          "port": 14},
        })

        code, _switch, lines = self.run_manual(
            inventory, adb, port=8, options={"targetIp": "10.9.1.44"})

        self.assertEqual(code, 1)
        self.assertFalse(any("su" in call for call in adb.calls))
        failed = [e for e in events(lines) if e["event"] == "port_failed"]
        self.assertIn("port 14", failed[0]["reason"])

    def test_the_bench_flow_refuses_an_address_that_is_not_ipv4(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({})
        with self.assertRaises(ValueError):
            self.run_manual(inventory, adb, port=8,
                            options={"targetIp": "10.9.1"})

    def test_the_bench_candidates_cover_set_one_the_open_set_and_the_target(self):
        inventory = self.inventory(7, count=2)
        found = lcd_runner.manual_candidates(inventory, "sw1", "10.9.1.44")
        self.assertEqual(found[0], "10.9.1.44")
        for address in ("10.1.1.40", "10.1.1.41", "10.7.1.40", "10.7.1.41"):
            self.assertIn(address, found)
        self.assertEqual(len(found), len(set(found)))

    def test_cancellation_still_reopens_every_managed_port(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
        })

        code, switch_api, _lines = self.run_lcd(
            inventory, adb, cancelled=lambda: True)

        self.assertEqual(code, 130)
        self.assertEqual(switch_api.poe_calls, [set(), {13}])
        self.assertFalse(any("su" in call for call in adb.calls))

    def test_a_different_serial_at_the_target_fails_identity_verification(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 13},
        }, changed_serial="SOMEONE-ELSE")

        code, _switch, lines = self.run_lcd(inventory, adb)

        self.assertEqual(code, 1)
        failed = [e for e in events(lines) if e["event"] == "port_failed"]
        self.assertIn("serial changed", failed[0]["reason"])

    def test_a_device_learned_on_another_switch_port_is_never_written(self):
        inventory = self.inventory(7, count=1)
        adb = FakeAdb({
            "10.1.1.40": {"serial": "LCD-40", "cidr": "10.1.1.40/16",
                            "port": 14},
        })

        code, _switch, lines = self.run_lcd(inventory, adb)

        self.assertEqual(code, 1)
        self.assertFalse(any("su" in call for call in adb.calls))
        failed = [e for e in events(lines) if e["event"] == "port_failed"]
        self.assertIn("port 14", failed[0]["reason"])


if __name__ == "__main__":
    import unittest
    unittest.main()
