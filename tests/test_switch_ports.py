#!/usr/bin/env python3
"""Port, PoE, network and discovery behaviour of `panel.switch`.

What is worth testing here is not "does a write happen" — it is the three
KYLAND habits the service layer exists to absorb, because each of them fails
SILENTLY and destructively when it is got wrong:

  · a write sends the WHOLE table, so writing one port must not disturb the
    other twenty-three;
  · power arrives ten times too large;
  · a boolean is present or absent, never "0".

Plus the guards: a scan that would run for an hour, an address the switch
could not be recovered from, and a factory reset confirmed against the wrong
switch.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import unittest

import requests

from panel import switch
from panel.errors import AuthError, DeviceError, UnreachableError
from panel.probe import switch as switch_probe
from panel.switch import device, network, ports

from .support import fakes
from .support.base import PanelTest

ACCOUNT = ("admin", "123")


def kyland_without_poe_tables(username="admin", password="123"):
    """A KYLAND model that serves portMode and NO PoE table at all.

    `fakes.kyland` can only drop `stat/poeStatus`; this switch answers 404 on
    `stat/poePort` too — the model the two port merges used to disagree
    about, before they became one (panel.switch.ports.get_ports): the IP
    screen's front panel rendered it, the switch screen failed the whole
    list.
    """
    expected = "Basic " + base64.b64encode(
        f"{username}:{password}".encode()).decode()

    def send(self):
        self.fake.request_count += 1
        if self.headers.get("Authorization") != expected:
            return self.write(401, b'{"error":"auth"}', "application/json",
                              {"WWW-Authenticate": 'Basic realm="switch"'})
        path = self.path.split("?")[0]
        if path == "/stat/basicInfo":
            return self.write(200, json.dumps(fakes.BASIC_INFO).encode(),
                              "application/json")
        if path == "/stat/portMode":
            return self.write(200, json.dumps(fakes.PORT_MODE).encode(),
                              "application/json")
        return self.write(404, b'{"error":"missing"}', "application/json")

    return fakes._Server(fakes._base_handler("NoPoeTableHandler", send))


class PortReads(PanelTest):

    def test_the_three_tables_are_merged_into_one_row_per_port(self):
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            rows = ports.get_ports(switch.CLIENT, "127.0.0.1", ACCOUNT)

        self.assertEqual(len(rows), 24)
        first = rows[0]
        # portMode
        self.assertEqual(first["id"], 1)
        self.assertEqual(first["linkState"], "up")
        self.assertTrue(first["enabled"])
        # poePort
        self.assertTrue(first["supportsPoe"])
        self.assertEqual(first["poeMode"], "1")
        self.assertEqual(first["poePriority"], "0")
        # poeStatus
        self.assertEqual(first["poeState"], "on")

    def test_power_is_divided_by_ten(self):
        """The switch reports 123 for 12.3 W. Reporting 123 W is not close."""
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            rows = ports.get_ports(switch.CLIENT, "127.0.0.1", ACCOUNT)
        self.assertEqual(rows[0]["powerWatts"], 12.3)
        # "0" is a reading of zero, not a missing reading.
        self.assertEqual(rows[3]["powerWatts"], 0.0)

    def test_a_model_without_poestatus_still_lists_its_ports(self):
        """`stat/poeStatus` does not exist on every model.

        The ports must still come back — with the live fields empty rather
        than invented.
        """
        with fakes.kyland(password="123", poe_status=False) as fake:
            self.switch_port(fake.port)
            rows = ports.get_ports(switch.CLIENT, "127.0.0.1", ACCOUNT)
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows[0]["poeState"], "")
        self.assertIsNone(rows[0]["powerWatts"])
        # The configured side is unaffected: that came from poePort.
        self.assertEqual(rows[0]["poeMode"], "1")

    def test_uplink_ports_are_listed_but_marked_as_having_no_poe(self):
        """The real SICOM3028GPT is 24 PoE + 4 uplink.

        An uplink is in portMode and NOT in poePort. It must still be listed —
        the faceplate draws the switch's real face, and a panel missing its
        uplink column stops matching the hardware — but with `supportsPoe`
        false, which is what the front panel draws the eight-pin connector
        from.
        """
        with fakes.kyland(password="123", uplinks=4) as fake:
            self.switch_port(fake.port)
            rows = ports.get_ports(switch.CLIENT, "127.0.0.1", ACCOUNT)

        self.assertEqual(len(rows), 28)
        poe = [row for row in rows if row["supportsPoe"]]
        uplink = [row for row in rows if not row["supportsPoe"]]
        self.assertEqual(len(poe), 24)
        self.assertEqual([row["id"] for row in uplink], [25, 26, 27, 28])
        # No PoE fields are invented for a port that has no PoE.
        for row in uplink:
            self.assertEqual(row["poeMode"], "")
            self.assertEqual(row["poeState"], "")
            self.assertIsNone(row["powerWatts"])

    def test_an_uplink_cannot_be_given_a_poe_mode(self):
        with fakes.kyland(password="123", uplinks=4) as fake:
            self.switch_port(fake.port)
            with self.assertRaises(DeviceError):
                ports.set_poe(switch.CLIENT, "127.0.0.1", 25, "1", ACCOUNT)
            self.assertEqual(fake.posts, [])

    def test_an_uplink_can_still_be_turned_off(self):
        """It has no PoE, but it is a port: portMode covers all 28."""
        with fakes.kyland(password="123", uplinks=4) as fake:
            self.switch_port(fake.port)
            ports.set_port_enabled(switch.CLIENT, "127.0.0.1", 26, False,
                                   ACCOUNT)
            form = next(body for path, body in reversed(fake.posts)
                        if path == "stat/portMode")
        self.assertNotIn("adminStat_26", form)
        # The whole 28-row table went out, uplinks included.
        for pid in (1, 24, 25, 27, 28):
            self.assertEqual(form[f"adminStat_{pid}"], "1", pid)

    def test_a_model_without_a_poe_table_lists_ports_on_both_screens(self):
        """The Kyland merge exists ONCE now, so its tolerance does too.

        Two copies of this merge used to fail differently on a model with no
        `stat/poePort`: the front panel tolerated it while the switch screen
        raised and lost the whole list. The front panel's answer is the right
        one — a switch without PoE tables still has ports to draw, to bring
        up and down, and to assign devices to — and after the consolidation
        both consumers must give it.
        """
        with kyland_without_poe_tables(password="123") as fake:
            self.switch_port(fake.port)
            rows = ports.get_ports(switch.CLIENT, "127.0.0.1", ACCOUNT)
            front = switch_probe.ports("127.0.0.1", ACCOUNT)

        self.assertEqual(len(rows), 24)
        self.assertEqual(len(front), 24)
        # No PoE fields are invented on either screen.
        self.assertFalse(any(row["supportsPoe"] for row in rows))
        self.assertFalse(any(row["poe"] for row in front))
        self.assertEqual(rows[0]["poeMode"], "")
        self.assertEqual(rows[0]["poeState"], "")
        self.assertIsNone(rows[0]["powerWatts"])
        # The non-PoE half of the table is intact on both.
        self.assertEqual([row["id"] for row in rows],
                         [row["pid"] for row in front])
        self.assertEqual(rows[0]["linkState"], "up")
        self.assertEqual(front[0]["link"], "up")

    def test_the_front_panel_is_a_projection_of_the_switch_screens_rows(self):
        """`probe.switch.ports` renames fields; it must not re-merge them.

        Row for row, the front panel's dict is the switch screen's row under
        the IP screen's key names — the pin that keeps the second merge from
        growing back.
        """
        with fakes.kyland(password="123", uplinks=4) as fake:
            self.switch_port(fake.port)
            rows = ports.get_ports(switch.CLIENT, "127.0.0.1", ACCOUNT)
            front = switch_probe.ports("127.0.0.1", ACCOUNT)

        self.assertEqual(front, [{
            "pid": row["id"],
            "type": row["portType"],
            "enabled": row["enabled"],
            "link": row["linkState"],
            "poe": row["supportsPoe"],
            "poeMode": row["poeMode"],
            "poeState": row["poeState"],
            "watts": row["powerWatts"],
        } for row in rows])

    def test_a_locked_switch_with_no_poe_table_still_asks_to_sign_in(self):
        """Tolerance for a missing table must not swallow "sign in first"."""
        with kyland_without_poe_tables(password="123") as fake:
            self.switch_port(fake.port)
            with self.assertRaises(AuthError):
                ports.get_ports(switch.CLIENT, "127.0.0.1", ("admin", "no"))
            with self.assertRaises(AuthError):
                switch_probe.ports("127.0.0.1", ("admin", "no"))

    def test_a_locked_switch_is_not_reported_as_a_model_without_poe(self):
        """"Sign in" and "this model has no such table" are different.

        `get_ports` swallows a failing poeStatus on purpose; if it swallowed
        an auth error too, a switch that simply needed a password would look
        like a switch with no PoE at all.
        """
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            with self.assertRaises(AuthError):
                ports.get_ports(switch.CLIENT, "127.0.0.1", ("admin", "no"))


class PortWrites(PanelTest):

    @staticmethod
    def _form(fake, endpoint):
        """The last form posted to one endpoint."""
        for path, form in reversed(fake.posts):
            if path == endpoint:
                return form
        raise AssertionError(f"nothing was posted to {endpoint}")

    def test_setting_one_ports_poe_rewrites_the_whole_table(self):
        """THE ONE THAT MATTERS. A partial form resets 23 ports."""
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            ports.set_poe(switch.CLIENT, "127.0.0.1", 7, "2", ACCOUNT)
            form = self._form(fake, "stat/poePort")

        for pid in range(1, 25):
            self.assertIn(f"mode_{pid}", form, pid)
            self.assertIn(f"priority_{pid}", form, pid)
            self.assertIn(f"maxPower_{pid}", form, pid)
        # Only the target moved; the rest kept what was read.
        self.assertEqual(form["mode_7"], "2")
        for pid in (1, 6, 8, 24):
            self.assertEqual(form[f"mode_{pid}"], "1", pid)

    def test_disabling_a_port_omits_its_flag_and_keeps_the_others(self):
        """A boolean is present or absent — "0" would read as enabled."""
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            ports.set_port_enabled(switch.CLIENT, "127.0.0.1", 5, False,
                                   ACCOUNT)
            form = self._form(fake, "stat/portMode")

        self.assertNotIn("adminStat_5", form)
        for pid in (1, 4, 6, 24):
            self.assertEqual(form[f"adminStat_{pid}"], "1", pid)
        # The rest of each row survives the rewrite.
        self.assertEqual(form["maxLength_5"], "1522")
        self.assertEqual(form["speed_5"], "1000")

    def test_an_unsupported_poe_mode_is_refused_before_the_write(self):
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            with self.assertRaises(DeviceError):
                ports.set_poe(switch.CLIENT, "127.0.0.1", 1, "9", ACCOUNT)
            self.assertEqual(fake.posts, [])

    def test_a_port_the_switch_does_not_have_is_refused(self):
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            with self.assertRaises(DeviceError):
                ports.set_port_enabled(switch.CLIENT, "127.0.0.1", 99, True,
                                       ACCOUNT)
            with self.assertRaises(DeviceError):
                ports.set_poe(switch.CLIENT, "127.0.0.1", 99, "1", ACCOUNT)
            self.assertEqual(fake.posts, [])

    def test_port_configuration_refuses_unknown_and_non_boolean_fields(self):
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            with self.assertRaises(DeviceError):
                ports.set_port_config(switch.CLIENT, "127.0.0.1", 1,
                                      {"vlan": "7"}, ACCOUNT)
            with self.assertRaises(DeviceError):
                ports.set_port_config(switch.CLIENT, "127.0.0.1", 1,
                                      {"enabled": "yes"}, ACCOUNT)
            self.assertEqual(fake.posts, [])

    def test_port_configuration_writes_the_named_fields(self):
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            ports.set_port_config(
                switch.CLIENT, "127.0.0.1", 3,
                {"speed": "100", "fullDuplex": False,
                 "maxFrameLength": "9000"}, ACCOUNT)
            form = self._form(fake, "stat/portMode")

        self.assertEqual(form["speed_3"], "100")
        self.assertEqual(form["maxLength_3"], "9000")
        self.assertNotIn("duplex_3", form)
        # Its neighbours keep theirs.
        self.assertEqual(form["speed_4"], "1000")
        self.assertEqual(form["duplex_4"], "1")


class BatchWrites(PanelTest):

    def test_a_batch_is_two_writes_not_one_per_port(self):
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            result = ports.apply_batch(
                switch.CLIENT, "127.0.0.1", {2: "0", 3: "2"},
                {5: False, 6: True}, ACCOUNT)
            written = [path for path, _ in fake.posts]

        self.assertEqual(result["poe"], [2, 3])
        self.assertEqual(result["ports"], [5, 6])
        self.assertEqual(written.count("stat/poePort"), 1)
        self.assertEqual(written.count("stat/portMode"), 1)

    def test_a_batch_naming_a_missing_port_writes_nothing(self):
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            with self.assertRaises(DeviceError):
                ports.apply_batch(switch.CLIENT, "127.0.0.1", {}, {99: True},
                                  ACCOUNT)
            self.assertEqual(fake.posts, [])

    def test_a_batch_with_an_invalid_mode_writes_nothing(self):
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            with self.assertRaises(DeviceError):
                ports.apply_batch(switch.CLIENT, "127.0.0.1", {1: "9"}, {},
                                  ACCOUNT)
            self.assertEqual(fake.posts, [])


class ManagementNetwork(unittest.TestCase):

    def test_an_address_the_switch_could_not_be_recovered_from_is_refused(self):
        for address in ("127.0.0.1", "224.0.0.1", "0.0.0.0"):
            with self.assertRaises(ValueError, msg=address):
                network.validate_network(address, "24", "1500")

    def test_only_the_three_prefixes_the_switch_accepts_are_allowed(self):
        for prefix in ("8", "16", "24"):
            self.assertEqual(
                network.validate_network("10.1.1.2", prefix, "1500")[1],
                prefix)
        for prefix in ("25", "0", "32", "abc"):
            with self.assertRaises(ValueError, msg=prefix):
                network.validate_network("10.1.1.2", prefix, "1500")

    def test_the_mtu_has_to_be_in_range(self):
        self.assertEqual(
            network.validate_network("10.1.1.2", "24", "9216")[2], "9216")
        for mtu in ("575", "9217", "", "big"):
            with self.assertRaises(ValueError, msg=mtu):
                network.validate_network("10.1.1.2", "24", mtu)

    def test_a_lost_connection_after_the_address_change_is_success(self):
        """The switch moves and the socket dies. That IS the write landing.

        Both shapes the drop can arrive in are checked: the panel's own
        UnreachableError, which is what the client raises today, and requests'
        raw exception, which is what it would raise if the client ever stopped
        wrapping. Catching only one of them would report a completed address
        change as a failure.
        """
        def dropping(failure):
            class Dropping:
                def lock(self, _ip):
                    return threading.Lock()

                def post(self, *_args, **_kwargs):
                    raise failure

            return Dropping()

        for failure in (UnreachableError("gone"),
                        requests.ConnectionError("closed")):
            result = network.set_network(dropping(failure), "10.1.1.2",
                                         "10.1.1.9", "24")
            self.assertEqual(result["retCode"], ["success"],
                             type(failure).__name__)


class Discovery(PanelTest):

    def test_an_address_a_prefix_and_a_network_all_resolve(self):
        single, is_single = switch.resolve_addresses("10.1.1.5")
        self.assertEqual(single, ["10.1.1.5"])
        self.assertTrue(is_single)

        prefix, is_single = switch.resolve_addresses("10.1.1")
        self.assertEqual(len(prefix), 254)
        self.assertFalse(is_single)
        self.assertEqual(prefix[0], "10.1.1.1")

        network_form, _ = switch.resolve_addresses("10.1.1.0/24")
        self.assertEqual(network_form, prefix)

    def test_an_address_range_sweeps_only_that_range(self):
        """The shape the screen sends now: bounds, plus a mask beside them.

        The switches sit on .100 to .110; sweeping the other 244 addresses of
        the /24 is a minute paid for nothing. The mask says which network the
        addresses belong to, not how many to try.
        """
        addresses, single = switch.resolve_addresses("10.1.1.100-110/24")
        self.assertEqual(len(addresses), 11)
        self.assertEqual(addresses[0], "10.1.1.100")
        self.assertEqual(addresses[-1], "10.1.1.110")
        self.assertFalse(single)

        # A wide mask does not widen the sweep.
        wide, _ = switch.resolve_addresses("10.1.1.100-110/16")
        self.assertEqual(wide, addresses)

    def test_a_range_given_backwards_still_works(self):
        """Typed the other way round is a typo, not a refusal."""
        self.assertEqual(switch.resolve_addresses("10.1.1.110-100")[0],
                         switch.resolve_addresses("10.1.1.100-110")[0])

    def test_a_range_of_impossible_addresses_is_refused(self):
        with self.assertRaises(ValueError):
            switch.resolve_addresses("10.1.1.300-400")

    def test_an_oversized_range_is_refused(self):
        with self.assertRaises(ValueError):
            switch.resolve_addresses("10.1.0-0.0")   # not a range at all
        # 0-255 is 256, which is allowed; the ceiling is on the count.
        self.assertEqual(len(switch.resolve_addresses("10.1.1.0-255")[0]), 256)

    def test_the_network_to_join_is_derived_from_the_expression(self):
        """What `resolve_addresses` does NOT answer: which network to be on.

        A sweep from a machine on another subnet finds nothing and looks
        exactly like "there are no switches here".
        """
        for expression, expected in (
                ("10.1.1.0-255/24", "10.1.1.0/24"),
                ("10.1.1.100-110/24", "10.1.1.0/24"),
                ("10.1.1.5", "10.1.1.0/24"),
                ("10.1.1", "10.1.1.0/24"),
                ("10.1.1.0/24", "10.1.1.0/24"),
                ("192.168.8.0-255/16", "192.168.0.0/16")):
            self.assertEqual(str(switch.target_network(expression)), expected,
                             expression)
        self.assertIsNone(switch.target_network("nonsense"))
        self.assertIsNone(switch.target_network(""))

    def test_a_network_nobody_would_wait_for_is_refused(self):
        with self.assertRaises(ValueError):
            switch.resolve_addresses("10.1.0.0/16")
        with self.assertRaises(ValueError):
            switch.resolve_addresses("")
        with self.assertRaises(ValueError):
            switch.resolve_addresses("not.an.address.at.all")

    def test_an_oversized_network_is_refused_without_being_expanded(self):
        """It is refused by arithmetic, not by building the list first.

        A /8 expanded before the check took sixteen seconds and hundreds of
        megabytes to produce a 400 — long enough that the operator who
        mistyped it assumed the panel had hung.
        """
        started = time.monotonic()
        with self.assertRaises(ValueError):
            switch.resolve_addresses("10.0.0.0/8")
        self.assertLess(time.monotonic() - started, 1.0)

    def test_the_largest_allowed_network_still_resolves(self):
        addresses, single = switch.resolve_addresses("10.1.0.0/22")
        self.assertEqual(len(addresses), 1022)
        self.assertFalse(single)

    def test_a_single_address_scan_finds_the_fake_switch(self):
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            result = switch.CLIENT.discover("127.0.0.1",
                                            credentials=("admin", "123"))
        self.assertFalse(result["cancelled"])
        self.assertEqual(len(result["switches"]), 1)
        self.assertEqual(result["switches"][0]["model"], "SICOM3028GPT")

    def test_a_cancelled_scan_stops_and_says_so(self):
        cancel = threading.Event()
        cancel.set()
        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            before = fake.request_count
            result = switch.CLIENT.discover("10.1.1.0/24", cancel_event=cancel)
            self.assertEqual(fake.request_count, before)
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["switches"], [])
        self.assertEqual(result["queried"], 0)

    def test_only_one_scan_runs_at_a_time(self):
        self.assertTrue(switch.CLIENT.start_scan())
        try:
            self.assertFalse(switch.CLIENT.start_scan())
        finally:
            switch.CLIENT.finish_scan()
        self.assertTrue(switch.CLIENT.start_scan())
        switch.CLIENT.finish_scan()


class Login(PanelTest):

    def test_a_working_account_is_kept_in_memory_under_the_switch_group(self):
        from panel import credentials

        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            device.login(switch.CLIENT, "127.0.0.1", "admin", "123")
        self.assertEqual(credentials.lookup("127.0.0.1", "127.0.0.1"),
                         ("admin", "123"))

    def test_a_wrong_account_is_not_kept(self):
        from panel import credentials

        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            with self.assertRaises(AuthError):
                device.login(switch.CLIENT, "127.0.0.1", "admin", "wrong")
        self.assertIsNone(credentials.lookup("127.0.0.1", "127.0.0.1"))

    def test_a_device_that_takes_the_password_but_is_not_a_switch_keeps_none(self):
        """The reason `looks_like_switch` is checked before storing.

        An address can change hands between one scan and the next, and plenty
        of things answer 200 without reading the Authorization header at all.
        """
        from panel import credentials

        with fakes.empty_json_switch() as fake:
            self.switch_port(fake.port)
            with self.assertRaises(UnreachableError):
                device.login(switch.CLIENT, "127.0.0.1", "admin", "123")
        self.assertIsNone(credentials.lookup("127.0.0.1", "127.0.0.1"))

    def test_the_group_account_is_shared_only_when_asked(self):
        from panel import credentials

        with fakes.kyland(password="123") as fake:
            self.switch_port(fake.port)
            device.login(switch.CLIENT, "127.0.0.1", "admin", "123")
            # Another switch, no account of its own, no sharing asked for.
            self.assertIsNone(
                credentials.lookup("10.9.9.9", "10.9.9.9", group="switch"))
            device.login(switch.CLIENT, "127.0.0.1", "admin", "123",
                         share_with_group=True)
            self.assertEqual(
                credentials.lookup("10.9.9.9", "10.9.9.9", group="switch"),
                ("admin", "123"))


if __name__ == "__main__":
    unittest.main()
