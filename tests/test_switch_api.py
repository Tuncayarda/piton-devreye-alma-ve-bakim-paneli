#!/usr/bin/env python3
"""The switch screen's endpoints, over real HTTP.

`tests/test_switch_ports.py` covers what the service layer does to the device.
This file covers the layer above it: that each path exists, that a bad request
is a 400 rather than a 500, that a switch wanting a password produces a 401
the screen can act on, and — the one worth writing down — that no reply ever
carries the password back out.
"""
from __future__ import annotations

import unittest

from panel import credentials, i18n, jobs, switch
from panel.api.routes import switch_routes

from .support import fakes
from .support.base import ServiceTest

PASSWORD = "s3cret-switch-pw"


class SwitchEndpoints(ServiceTest):

    def setUp(self):
        super().setUp()
        self.base = self.start_service()
        switch_routes.reset()
        self.addCleanup(switch_routes.reset)

    def sign_in(self, fake):
        self.switch_port(fake.port)
        status, body = self.call(self.base, "/api/switch/login",
                                 {"ip": "127.0.0.1", "username": "admin",
                                  "password": PASSWORD})
        self.assertEqual(status, 200, body)
        return body

    # ---- the screen ----

    def test_the_screen_body_comes_back_in_one_request(self):
        status, body = self.call(self.base, "/api/switch")
        self.assertEqual(status, 200)
        self.assertEqual(body["discovered"], [])
        self.assertFalse(body["scanning"])
        self.assertEqual(body["defaultCidr"], "10.1.1.0-255/24")
        # Keys, not words. The words are the screen's to look up — see
        # `test_the_poe_modes_are_catalogue_keys_not_english` below.
        self.assertEqual([mode["value"] for mode in body["poeModes"]],
                         ["0", "1", "2"])
        self.assertEqual([mode["labelKey"] for mode in body["poeModes"]],
                         ["switch.poeModeOff", "switch.poeModePoe",
                          "switch.poeModePoePlus"])

    def test_the_poe_modes_are_catalogue_keys_not_english(self):
        """Every word this body carries must change with the language.

        The sibling application had one language, so it spelled its PoE modes
        out in Python — `{"0": "Off", ...}` — and this endpoint handed those
        three English words to the screen. A panel running in Turkish offered
        "Off" in its right-click menu, and neither language gate saw it: one
        reads static/js, the other looks for Turkish in English text.
        """
        status, body = self.call(self.base, "/api/switch")
        self.assertEqual(status, 200)
        modes = body["poeModes"]
        self.assertTrue(modes)
        turkish = i18n.payload("tr")["messages"]
        english = i18n.payload("en")["messages"]
        for mode in modes:
            # A key, not a word: the browser looks it up, so it cannot be
            # stuck in whatever language the server was written in.
            self.assertNotIn("label", mode, mode)
            key = mode["labelKey"]
            missing = [name for name, catalogue in (("tr", turkish),
                                                    ("en", english))
                       if key not in catalogue]
            self.assertEqual(missing, [], f"{key!r} is not a catalogue key")
        # And the two catalogues really do disagree, or the check above would
        # pass on a key whose translation was never written.
        self.assertNotEqual([turkish[m["labelKey"]] for m in modes],
                            [english[m["labelKey"]] for m in modes])

    # ---- authentication ----

    def test_a_switch_that_wants_a_password_answers_401_with_a_flag(self):
        """The screen opens its sign-in dialog off `auth`, not off the text."""
        with fakes.kyland(password=PASSWORD) as fake:
            self.switch_port(fake.port)
            status, body = self.call(self.base, "/api/switch/info?ip=127.0.0.1")
        self.assertEqual(status, 401)
        self.assertTrue(body["auth"])

    def test_signing_in_unlocks_the_reads(self):
        with fakes.kyland(password=PASSWORD) as fake:
            info = self.sign_in(fake)
            self.assertEqual(info["model"], "SICOM3028GPT")

            status, body = self.call(self.base, "/api/switch/info?ip=127.0.0.1")
            self.assertEqual(status, 200, body)
            self.assertEqual(body["network"]["address"], "10.1.1.2")
            self.assertEqual(body["network"]["subnetMask"], "255.255.255.0")

            status, body = self.call(self.base,
                                     "/api/switch/ports?ip=127.0.0.1")
            self.assertEqual(status, 200, body)
            self.assertEqual(len(body["ports"]), 24)

    def test_a_wrong_password_is_401_and_is_not_remembered(self):
        with fakes.kyland(password=PASSWORD) as fake:
            self.switch_port(fake.port)
            status, _ = self.call(self.base, "/api/switch/login",
                                  {"ip": "127.0.0.1", "username": "admin",
                                   "password": "wrong"})
        self.assertEqual(status, 401)
        self.assertIsNone(credentials.lookup("127.0.0.1", "127.0.0.1"))

    def test_signing_in_here_also_unlocks_the_ip_assignment_screen(self):
        """The point of the merge, asserted.

        The IP assignment screen looks its switch account up in the "switch"
        group (`panel.ip_assign.factory_reset`). Signing in on this screen with
        "apply to all" must therefore be enough for that one too.
        """
        with fakes.kyland(password=PASSWORD) as fake:
            self.switch_port(fake.port)
            status, _ = self.call(self.base, "/api/switch/login",
                                  {"ip": "127.0.0.1", "username": "admin",
                                   "password": PASSWORD,
                                   "applyToGroup": True})
        self.assertEqual(status, 200)
        self.assertEqual(
            credentials.lookup("sw2", "10.1.1.7", group="switch"),
            ("admin", PASSWORD))

    def test_signing_in_clears_the_locked_mark_on_the_list(self):
        """THE BADGE USED TO STAY UNTIL THE NEXT SWEEP.

        The stored scan result is what the screen draws, and nothing wrote
        back to it: a switch that had just been signed into carried on saying
        "sign in required" with an empty name, and the only way to correct it
        was to sweep the network again — the expensive way to learn something
        the login reply had already said.
        """
        with fakes.kyland(password=PASSWORD) as fake:
            self.switch_port(fake.port)
            status, body = self.call(self.base, "/api/switch/discover",
                                     {"cidr": "127.0.0.1"})
            self.assertEqual(status, 200, body)
            self.await_job(jobs.QUEUE.find(body["id"]))

            before = self.call(self.base, "/api/switch")[1]["discovered"][0]
            self.assertTrue(before["locked"])
            self.assertEqual(before["model"], "")

            self.sign_in(fake)

            after = self.call(self.base, "/api/switch")[1]["discovered"]
            self.assertEqual(len(after), 1, "the switch was duplicated")
            self.assertFalse(after[0]["locked"])
            self.assertEqual(after[0]["model"], "SICOM3028GPT")
            self.assertEqual(after[0]["name"], "Yatakli_Test_SW")

    def test_signing_into_an_address_no_sweep_found_lists_it(self):
        """A hand-typed address belongs on the list for the same reason."""
        with fakes.kyland(password=PASSWORD) as fake:
            self.assertEqual(self.call(self.base, "/api/switch")[1]
                             ["discovered"], [])
            self.sign_in(fake)
            found = self.call(self.base, "/api/switch")[1]["discovered"]
        self.assertEqual([entry["ip"] for entry in found], ["127.0.0.1"])
        self.assertFalse(found[0]["locked"])

    def test_logging_out_forgets_the_account(self):
        with fakes.kyland(password=PASSWORD) as fake:
            self.sign_in(fake)
            status, _ = self.call(self.base, "/api/switch/logout",
                                  {"ip": "127.0.0.1"})
        self.assertEqual(status, 200)
        self.assertIsNone(credentials.lookup("127.0.0.1", "127.0.0.1"))

    # ---- writes ----

    def test_poe_port_batch_and_network_writes_reach_the_switch(self):
        with fakes.kyland(password=PASSWORD) as fake:
            self.sign_in(fake)
            for path, body in (
                    ("/api/switch/poe",
                     {"ip": "127.0.0.1", "port": 4, "mode": "2"}),
                    ("/api/switch/port",
                     {"ip": "127.0.0.1", "port": 4, "enabled": False}),
                    ("/api/switch/port",
                     {"ip": "127.0.0.1", "port": 4,
                      "config": {"speed": "100"}}),
                    ("/api/switch/batch",
                     {"ip": "127.0.0.1", "poe": {"5": "0"},
                      "ports": {"6": True}}),
                    ("/api/switch/network",
                     {"ip": "127.0.0.1", "address": "10.1.1.9",
                      "prefix": "24", "mtu": "1500"}),
                    ("/api/switch/config-save", {"ip": "127.0.0.1"}),
                    ("/api/switch/reboot", {"ip": "127.0.0.1"}),
            ):
                status, reply = self.call(self.base, path, body)
                self.assertEqual(status, 200, (path, reply))

    def test_a_malformed_request_is_400_not_500(self):
        with fakes.kyland(password=PASSWORD) as fake:
            self.sign_in(fake)
            for path, body in (
                    ("/api/switch/poe", {"ip": "127.0.0.1", "mode": "1"}),
                    ("/api/switch/poe",
                     {"ip": "127.0.0.1", "port": "x", "mode": "1"}),
                    ("/api/switch/poe",
                     {"ip": "127.0.0.1", "port": -1, "mode": "1"}),
                    ("/api/switch/port",
                     {"ip": "127.0.0.1", "port": 1, "enabled": "yes"}),
                    ("/api/switch/batch",
                     {"ip": "127.0.0.1", "poe": {}, "ports": {}}),
                    ("/api/switch/batch",
                     {"ip": "127.0.0.1", "ports": {"a": True}}),
                    ("/api/switch/network",
                     {"ip": "127.0.0.1", "address": "127.0.0.1",
                      "prefix": "24"}),
                    ("/api/switch/network",
                     {"ip": "127.0.0.1", "address": "10.1.1.9",
                      "prefix": "25"}),
                    ("/api/switch/reboot", {}),
                    ("/api/switch/discover", {"cidr": "10.0.0.0/8"}),
            ):
                status, reply = self.call(self.base, path, body)
                self.assertEqual(status, 400, (path, status, reply))

    def test_a_missing_ip_query_is_400(self):
        for path in ("/api/switch/info", "/api/switch/ports"):
            status, _ = self.call(self.base, path)
            self.assertEqual(status, 400, path)

    def test_a_factory_reset_needs_the_address_typed_back(self):
        with fakes.kyland(password=PASSWORD) as fake:
            self.sign_in(fake)
            status, _ = self.call(self.base, "/api/switch/factory-reset",
                                  {"ip": "127.0.0.1", "confirm": "127.0.0.2"})
            self.assertEqual(status, 400)
            status, _ = self.call(self.base, "/api/switch/factory-reset",
                                  {"ip": "127.0.0.1", "confirm": ""})
            self.assertEqual(status, 400)
            self.assertEqual([path for path, _ in fake.posts], [])

            status, body = self.call(self.base, "/api/switch/factory-reset",
                                     {"ip": "127.0.0.1",
                                      "confirm": "127.0.0.1"})
            self.assertEqual(status, 200, body)
            self.assertIn("stat/reset", [path for path, _ in fake.posts])

    # ---- discovery ----

    def test_discovery_runs_as_a_job_and_its_result_is_kept(self):
        with fakes.kyland(password=PASSWORD) as fake:
            self.switch_port(fake.port)
            status, body = self.call(self.base, "/api/switch/discover",
                                     {"cidr": "127.0.0.1"})
            self.assertEqual(status, 200, body)
            self.assertEqual(body["kind"], "switchscan")
            self.await_job(jobs.QUEUE.find(body["id"]))

            status, screen = self.call(self.base, "/api/switch")
            self.assertEqual(status, 200)
            self.assertFalse(screen["scanning"])
            self.assertEqual(len(screen["discovered"]), 1)
            # Not signed in yet, so the switch is found but locked.
            self.assertTrue(screen["discovered"][0]["locked"])

            # Reopening the screen shows the last result rather than rescanning.
            before = fake.request_count
            self.call(self.base, "/api/switch")
            self.assertEqual(fake.request_count, before)

    def test_cancelling_a_scan_that_is_not_running_is_not_an_error(self):
        status, body = self.call(self.base, "/api/switch/discover/cancel", {})
        self.assertEqual(status, 200)
        self.assertIn("stopped", body)

    # ---- the rule that outranks the rest ----

    def test_no_reply_ever_carries_the_password(self):
        with fakes.kyland(password=PASSWORD) as fake:
            replies = [self.sign_in(fake)]
            for path in ("/api/switch", "/api/switch/info?ip=127.0.0.1",
                         "/api/switch/ports?ip=127.0.0.1"):
                replies.append(self.call(self.base, path)[1])
            for path, body in (
                    ("/api/switch/poe",
                     {"ip": "127.0.0.1", "port": 1, "mode": "1"}),
                    ("/api/switch/config-save", {"ip": "127.0.0.1"})):
                replies.append(self.call(self.base, path, body)[1])
            # And a failed sign-in, where the password was in the request.
            replies.append(self.call(self.base, "/api/switch/login",
                                     {"ip": "127.0.0.1", "username": "admin",
                                      "password": PASSWORD + "x"})[1])
        for reply in replies:
            self.assertNotIn(PASSWORD, repr(reply))

    def test_a_password_is_never_written_into_a_job_row(self):
        with fakes.kyland(password=PASSWORD) as fake:
            self.sign_in(fake)
            status, body = self.call(self.base, "/api/switch/discover",
                                     {"cidr": "127.0.0.1"})
            self.assertEqual(status, 200)
            job = jobs.QUEUE.find(body["id"])
            self.await_job(job)
            self.assertNotIn(PASSWORD, repr(job.dto()))


class RouteRegistration(unittest.TestCase):

    def test_every_switch_handler_is_reachable(self):
        """Both lists in `panel.api.routes.__init__`, or the paths 404."""
        from panel.api.routes import GET_ROUTES, POST_ROUTES

        for path in switch_routes.GET:
            self.assertIn(path, GET_ROUTES, path)
        for path in switch_routes.POST:
            self.assertIn(path, POST_ROUTES, path)

    def test_the_client_holds_no_credential_store(self):
        """Contract: passwords live in `panel.credentials` and nowhere else."""
        self.assertFalse(hasattr(switch.CLIENT, "credentials"))


if __name__ == "__main__":
    unittest.main()
