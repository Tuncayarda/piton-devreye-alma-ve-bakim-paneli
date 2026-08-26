#!/usr/bin/env python3
"""API security and password-leak checks.

Covered requirements:
  9. No password is written to `.env`, JSON or any other file.
 10. API replies and queue rows contain no password.
 17. No connection is made to a client-supplied IP outside DeviceMap.
"""
from __future__ import annotations

import json
import secrets
import unittest

from panel import credentials, jobs, settings

from .support import fakes
from .support.base import ServiceTest

# The password is generated randomly per run. Hard-coded, the "search the tree
# for this text" test would trip over the test's own source file — and a real
# leak would be indistinguishable from the test constant.
PASSWORD = "gecici-" + secrets.token_hex(12)


def _topology():
    return fakes.device_map([{
        "Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
        "Type": "Announcement", "SubType": "Intercom", "Port": "11",
        "PBXExtension": "2001", "PBXPassword": "2001",
        "Status": {"NoError": True},
    }], switch_ip="127.0.0.1")


class Security(ServiceTest):

    # ── 10 ────────────────────────────────────────────────────────────
    def test_10_no_password_in_api_replies(self):
        inventory = self.build_map(_topology())
        with fakes.kyland(password=PASSWORD) as switch, \
                fakes.announcement() as device:
            self.switch_port(switch.port)
            settings.ANNOUNCEMENT_PORT = device.port
            base = self.start_service()

            code, started = self.call(base, "/api/scan", {"set": 1})
            self.await_job(jobs.QUEUE.find(started["id"]))

            switch_id = inventory.switches()[0].id
            code, _ = self.call(base, "/api/credentials", {
                "set": 1, "deviceId": switch_id,
                "username": "admin", "password": PASSWORD})
            self.assertEqual(code, 200)

            paths = [
                "/api/version", "/api/project?set=1", "/api/state?set=1",
                "/api/devices?set=1", "/api/locked?set=1", "/api/jobs",
                f"/api/job?id={started['id']}",
                f"/api/device?set=1&id={switch_id}",
                "/api/ip/plan?set=1&group=Intercom", "/api/firmware",
                "/api/checklist?set=1",
                "/api/piscu?set=1", "/api/mqtt",
            ]
            for path in paths:
                code, body = self.call(base, path)
                text = json.dumps(body, ensure_ascii=False)
                self.assertNotIn(PASSWORD, text, f"{path} leaked the password")
                self.assertNotIn("secret-devicemap-password", text,
                                 f"{path} leaked the DeviceMap password")
                self.assertNotIn("Authorization", text)
                self.assertNotIn("Basic ", text)
                for key in ("password", "Password", "pbxPassword"):
                    self.assertNotIn(f'"{key}"', text, path)

    def test_10b_no_password_in_queue_rows(self):
        inventory = self.build_map(_topology())
        with fakes.kyland(password=PASSWORD) as switch, \
                fakes.announcement() as device:
            self.switch_port(switch.port)
            settings.ANNOUNCEMENT_PORT = device.port
            base = self.start_service()
            switch_id = inventory.switches()[0].id
            self.call(base, "/api/credentials", {
                "set": 1, "deviceId": switch_id,
                "username": "admin", "password": PASSWORD})
            code, started = self.call(base, "/api/scan", {"set": 1})
            self.await_job(jobs.QUEUE.find(started["id"]))

            code, full = self.call(base, f"/api/job?id={started['id']}")
            text = json.dumps(full, ensure_ascii=False)
            self.assertNotIn(PASSWORD, text)
            self.assertNotIn("Traceback", text)
            for row in full["rows"]:
                # "file" is only a flag: whether the row points at an openable
                # file. The path ("path") never reaches the UI — the server
                # opens the file by reading it from the job record.
                #
                # "steps" feeds the accordion under the row; the text in it
                # must be showable to the user too, because it comes from the
                # same place — the script's output.
                self.assertEqual(
                    set(row) - {"deviceId", "name", "ip", "readMethod",
                                "state", "note", "file", "steps"},
                    set(), "unexpected field on a queue row")
                self.assertNotIn("path", row)
                for step in row.get("steps", []):
                    self.assertEqual(set(step), {"text", "state", "at"})
                    self.assertNotIn(PASSWORD, step["text"])

    def test_10c_the_credential_summary_masks_the_username(self):
        credentials.remember("d1", "127.0.0.1", "administrator", PASSWORD)
        summary = credentials.summary()
        text = json.dumps(summary)
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn("administrator", text)
        self.assertEqual(credentials.mask("admin"), "a***n")

    # ── 9 ─────────────────────────────────────────────────────────────
    def test_9_no_password_is_written_to_any_file(self):
        """After a full flow, the project tree is searched for the password."""
        inventory = self.build_map(_topology())
        with fakes.kyland(password=PASSWORD) as switch, \
                fakes.announcement() as device:
            self.switch_port(switch.port)
            settings.ANNOUNCEMENT_PORT = device.port
            base = self.start_service()
            switch_id = inventory.switches()[0].id
            self.call(base, "/api/credentials", {
                "set": 1, "deviceId": switch_id, "username": "admin",
                "password": PASSWORD, "applyToGroup": True})
            code, started = self.call(base, "/api/scan", {"set": 1})
            self.await_job(jobs.QUEUE.find(started["id"]))
            self.call(base, "/api/config/target", {
                "set": 1, "deviceId": inventory.devices[1].id,
                "field": "sipExtension", "value": "2001"})

        # No file in the project tree may contain the password
        skip = {".venv", ".git", "__pycache__", "node_modules"}
        inspected = 0
        for path in settings.ROOT.rglob("*"):
            if not path.is_file() or any(p in skip for p in path.parts):
                continue
            if path.suffix in (".png", ".xlsx", ".svg", ".ico"):
                continue
            inspected += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            self.assertNotIn(PASSWORD, text, f"{path} contains the password")
        self.assertGreater(inspected, 10)

        # No new file may appear in the temporary DeviceMap directory either
        neighbours = list(self.map_path.parent.iterdir())
        self.assertEqual([p.name for p in neighbours], ["DeviceMap.json"])

        # A .env file must never be created
        self.assertFalse((settings.ROOT / ".env").exists())

    def test_9b_the_credential_module_writes_no_file(self):
        """panel/credentials.py must not touch persistent storage at all."""
        source = (settings.ROOT / "panel" / "credentials.py").read_text(
            encoding="utf-8")
        for banned in ("open(", "write_text", "json.dump", "pickle",
                       "sqlite3", "keyring", "os.environ["):
            self.assertNotIn(banned, source,
                             f"credentials.py must not use '{banned}'")

    # ── 17 ────────────────────────────────────────────────────────────
    def test_17_a_client_supplied_ip_is_not_used(self):
        """Putting ip/host in the body must not change the target."""
        inventory = self.build_map(_topology())
        with fakes.kyland(password=PASSWORD) as switch:
            self.switch_port(switch.port)
            base = self.start_service()
            switch_id = inventory.switches()[0].id

            code, body = self.call(base, "/api/credentials", {
                "set": 1, "deviceId": switch_id,
                "ip": "10.255.255.1",          # must be ignored
                "type": "Camera",              # must be ignored
                "username": "admin", "password": PASSWORD})
            self.assertEqual(code, 200)
            # The target came from DeviceMap: the fake switch saw the request
            self.assertGreater(switch.request_count, 0)
            self.assertEqual(body["device"]["ip"], "127.0.0.1")

    def test_17b_an_unknown_device_id_is_rejected(self):
        self.build_map(_topology())
        base = self.start_service()
        for body in ({"set": 1, "deviceId": "yok-boyle-bir-id",
                      "username": "a", "password": "b"},
                     {"set": 1, "deviceId": "../../etc/passwd",
                      "username": "a", "password": "b"}):
            code, reply = self.call(base, "/api/credentials", body)
            self.assertEqual(code, 404, body)
            self.assertIn("not in this train set's list", reply["error"])

    def test_17c_an_invalid_set_number_is_not_accepted(self):
        self.build_map(_topology())
        base = self.start_service()
        for bad in (0, -3, 999, "abc", None, 1e9):
            code, body = self.call(base, f"/api/state?set={bad}")
            self.assertEqual(code, 200)
            self.assertTrue(settings.SET_MIN <= body["setNo"]
                            <= settings.SET_MAX)

    # ── general API hardening ─────────────────────────────────────────
    def test_static_files_cannot_escape_the_directory(self):
        self.build_map(_topology())
        base = self.start_service()
        for path in ("/css/../../app.py",
                     "/js/../../DeviceMap.json",
                     "/css/%2e%2e%2f%2e%2e%2fapp.py",
                     "/js/....//....//app.py"):
            code, _ = self.call(base, path)
            self.assertIn(code, (400, 404), path)

    def test_the_ip_endpoints_reject_a_group_without_an_ip_runner(self):
        """Even past the UI boundary, unsupported device types stay read-only."""
        inventory = self.build_map(_topology())
        base = self.start_service()

        code, body = self.call(base, "/api/ip/plan?set=1&group=Camera")
        self.assertEqual(code, 400)
        self.assertIn("Intercom devices only", body["error"])

        code, body = self.call(base, "/api/ip/factory-reset", {
            "set": 1,
            "switch": inventory.switches()[0].id,
            "groups": ["Camera"],
            "ports": "11",
            "factoryIp": "10.1.1.12",
        })
        self.assertEqual(code, 400)
        self.assertIn("Intercom devices only", body["error"])

    def test_the_body_size_is_limited(self):
        self.build_map(_topology())
        base = self.start_service()
        code, body = self.call(base, "/api/credentials", {
            "set": 1, "deviceId": "sw1",
            "username": "a" * 200, "password": "b"})
        self.assertEqual(code, 400)

        import urllib.error
        import urllib.request
        oversized = (b'{"set":1,"deviceId":"'
                     + b"a" * (settings.BODY_LIMIT + 10) + b'"}')
        request = urllib.request.Request(base + "/api/credentials",
                                         data=oversized, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10):
                self.fail("an oversized body was accepted")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_cors_is_not_opened(self):
        import urllib.request
        self.build_map(_topology())
        base = self.start_service()
        with urllib.request.urlopen(base + "/api/version", timeout=10) as r:
            self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))

    def test_the_server_binds_to_localhost_only(self):
        from panel.api import http_adapter
        with self.assertRaises(ValueError):
            http_adapter.serve("0.0.0.0", 0)


if __name__ == "__main__":
    unittest.main()
