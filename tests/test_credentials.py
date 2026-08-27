#!/usr/bin/env python3
"""The lock flow and credentials staying in memory only.

Covered requirements:
  4. A 401/403 device drops into the lock list.
  5. Correct credentials turn the device green and clear it from the list.
  6. Wrong credentials do not overwrite a working in-memory credential.
  7. The RAM credential store is cleared when the application closes.
  8. Earlier passwords are not found in a new application process.
 12. A late scan reply does not overwrite a fresh verification success.
 15. A camera/NVR 401 enters the same lock flow.
 16. A timeout and a wrong password produce different error classes.
"""
from __future__ import annotations

import subprocess
import sys
import unittest

from panel import api, credentials, jobs, settings, status
from panel.probe import reader
from panel.probe import result as probe_result

from .support import fakes
from .support.base import ServiceTest

PASSWORD = "secret-Password-42"


def _switch_topology():
    return fakes.device_map([], switch_ip="127.0.0.1", switch_name="Test_SW")


def _camera_topology():
    return fakes.device_map([{
        "Name": "Corridor_Cam_1", "IP": "127.0.0.1", "IsActive": True,
        "Type": "Camera", "SubType": "Corridor", "Port": "1",
        "Username": "admin", "Password": "devicemap-parolasi",
        "Status": {"NoError": False},
    }])


class LockFlow(ServiceTest):

    def test_4_a_device_answering_401_drops_into_the_lock_list(self):
        self.build_map(_switch_topology())
        with fakes.kyland(password=PASSWORD) as switch:
            self.switch_port(switch.port)
            base = self.start_service()

            code, started = self.call(base, "/api/scan", {"set": 1})
            self.assertEqual(code, 200)
            self.await_job(jobs.QUEUE.find(started["id"]))

            code, locked = self.call(base, "/api/locked?set=1")
            self.assertEqual(code, 200)
            names = [d["name"] for d in locked["devices"]]
            self.assertIn("Test_SW", names)
            self.assertEqual(locked["devices"][0]["credentialGroup"], "switch")
            self.assertFalse(locked["devices"][0]["hasCredentials"])

            code, state = self.call(base, "/api/state?set=1")
            self.assertEqual(state["counts"]["auth"], 1)
            self.assertEqual(state["lockedCount"], 1)

    def test_15_a_camera_401_enters_the_same_flow(self):
        self.build_map(_camera_topology())
        with fakes.camera(password=PASSWORD) as camera:
            settings.VIDEO_PORT = camera.port
            base = self.start_service()

            code, started = self.call(base, "/api/scan", {"set": 1})
            self.await_job(jobs.QUEUE.find(started["id"]))

            code, locked = self.call(base, "/api/locked?set=1")
            cameras = [d for d in locked["devices"] if d["type"] == "Camera"]
            self.assertEqual(len(cameras), 1)
            self.assertEqual(cameras[0]["credentialGroup"], "video")

            # Correct credentials turn it green
            device_id = cameras[0]["id"]
            code, body = self.call(base, "/api/credentials", {
                "set": 1, "deviceId": device_id,
                "username": "admin", "password": PASSWORD})
            self.assertEqual(code, 200)
            self.assertEqual(body["result"], "verified")
            self.assertEqual(
                body["device"]["result"]["fields"]["version"], "V5.7.3")

    def test_5_correct_credentials_turn_it_green_and_unlock_it(self):
        self.build_map(_switch_topology())
        with fakes.kyland(password=PASSWORD) as switch:
            self.switch_port(switch.port)
            base = self.start_service()
            code, started = self.call(base, "/api/scan", {"set": 1})
            self.await_job(jobs.QUEUE.find(started["id"]))

            code, locked = self.call(base, "/api/locked?set=1")
            device_id = locked["devices"][0]["id"]

            code, body = self.call(base, "/api/credentials", {
                "set": 1, "deviceId": device_id,
                "username": "admin", "password": PASSWORD})
            self.assertEqual(code, 200)
            self.assertEqual(body["result"], "verified")

            # The device must have been re-read and turned green
            self.assertEqual(body["device"]["result"]["state"], status.OK)
            self.assertEqual(
                body["device"]["result"]["fields"]["version"], "F6014")

            # The counters are current in the same reply
            self.assertEqual(body["state"]["counts"]["auth"], 0)
            self.assertEqual(body["state"]["counts"]["ok"], 1)
            self.assertEqual(body["state"]["lockedCount"], 0)

            # The lock list has emptied
            code, locked = self.call(base, "/api/locked?set=1")
            self.assertEqual(locked["devices"], [])

            # No second full scan needed: the light refresh can read it
            code, body = self.call(base, "/api/refresh", {"set": 1})
            self.assertEqual(code, 200)
            self.assertIn(device_id, body["refreshed"])

    def test_6_wrong_credentials_do_not_overwrite_a_working_one(self):
        inventory = self.build_map(_switch_topology())
        with fakes.kyland(password=PASSWORD) as switch:
            self.switch_port(switch.port)
            base = self.start_service()
            device = inventory.switches()[0]

            code, _ = self.call(base, "/api/credentials", {
                "set": 1, "deviceId": device.id,
                "username": "admin", "password": PASSWORD})
            self.assertEqual(code, 200)
            self.assertEqual(credentials.lookup(device.id, device.ip),
                             ("admin", PASSWORD))

            code, body = self.call(base, "/api/credentials", {
                "set": 1, "deviceId": device.id,
                "username": "admin", "password": "yanlis"})
            self.assertEqual(code, 401)
            self.assertEqual(body["error"],
                             "The username or password could not be "
                             "verified")

            # The working credential in RAM stays exactly as it was
            self.assertEqual(credentials.lookup(device.id, device.ip),
                             ("admin", PASSWORD))
            # And the device stays green — a wrong attempt does not flip it
            view = jobs.view_for(1)
            self.assertEqual(view.get(device.id).state, status.OK)

    def test_16_a_timeout_and_a_wrong_password_are_different_classes(self):
        inventory = self.build_map(_switch_topology())
        device = inventory.switches()[0]

        with fakes.kyland(password=PASSWORD) as switch:
            self.switch_port(switch.port)
            wrong = reader.read_device(device, credentials=("admin", "hatali"),
                                       timeout=3)
        self.assertEqual(wrong.state, status.AUTH)
        self.assertEqual(wrong.verification, status.AUTH_REQUIRED)

        with fakes.silent() as silent:
            self.switch_port(silent.port)
            unreachable = reader.read_device(
                device, credentials=("admin", PASSWORD), timeout=1.0)
        self.assertEqual(unreachable.state, status.FAILED)
        self.assertEqual(unreachable.verification, status.UNVERIFIED)
        self.assertNotEqual(wrong.detail, unreachable.detail)
        self.assertIn("timed out", unreachable.detail.lower())

    def test_12_a_late_scan_reply_does_not_overwrite_a_verification(self):
        """Generation check: a late old reply cannot undo a newer one."""
        view = jobs.DeviceStateView(1)

        old_generation = jobs.next_generation()
        new_generation = jobs.next_generation()

        newer = probe_result.success({"version": "F6014"}, "kyland")
        newer.generation = new_generation
        self.assertTrue(view.write("sw1", newer))

        # An auth result arriving late from the scan (an OLDER generation)
        older = probe_result.ProbeResult(
            state=status.AUTH, verification=status.AUTH_REQUIRED,
            detail="wants a password", read_method="kyland",
            generation=old_generation)
        self.assertFalse(view.write("sw1", older))
        self.assertEqual(view.get("sw1").state, status.OK)

        # A NEWER auth result is valid
        newest = probe_result.ProbeResult(
            state=status.AUTH, verification=status.AUTH_REQUIRED,
            read_method="kyland", generation=jobs.next_generation())
        self.assertTrue(view.write("sw1", newest))
        self.assertEqual(view.get("sw1").state, status.AUTH)

    def test_7_memory_is_cleared_on_shutdown(self):
        inventory = self.build_map(_switch_topology())
        device = inventory.switches()[0]
        credentials.remember(device.id, device.ip, "admin", PASSWORD,
                             group="switch", share_with_group=True)
        self.assertEqual(credentials.count(), 1)

        api.reset()

        self.assertEqual(credentials.count(), 0)
        self.assertIsNone(
            credentials.lookup(device.id, device.ip, group="switch"))
        self.assertEqual(credentials.summary(), {"device": {}, "group": {}})

    def test_8_earlier_passwords_are_absent_in_a_new_process(self):
        """A separate Python process is started; the store must be empty.

        This differs from "we cleared it in the same test": it shows that a
        genuinely new interpreter loads no credential from any persistent
        source.
        """
        inventory = self.build_map(_switch_topology())
        device = inventory.switches()[0]
        credentials.remember(device.id, device.ip, "admin", PASSWORD,
                             group="switch", share_with_group=True)

        script = (
            "import sys, json;"
            f"sys.path.insert(0, {str(settings.ROOT)!r});"
            "from panel import credentials;"
            "print(json.dumps({'count': credentials.count(),"
            " 'summary': credentials.summary(),"
            f" 'lookup': credentials.lookup({device.id!r}, {device.ip!r},"
            " group='switch')}))"
        )
        output = subprocess.run([sys.executable, "-c", script],
                                capture_output=True, text=True, timeout=60,
                                check=False)
        self.assertEqual(output.returncode, 0, output.stderr)
        data = __import__("json").loads(output.stdout.strip().splitlines()[-1])
        self.assertEqual(data["count"], 0)
        self.assertIsNone(data["lookup"])
        self.assertEqual(data["summary"], {"device": {}, "group": {}})
        # The password text must not appear in the new process's output
        self.assertNotIn(PASSWORD, output.stdout)

    def test_the_credential_read_path_matches_the_scan(self):
        """A credential attempt and a scan go through the same read code.

        Separate paths would create the "worked in the form, failed in the
        scan" situation; this test asserts against it directly.
        """
        inventory = self.build_map(_switch_topology())
        device = inventory.switches()[0]
        with fakes.kyland(password=PASSWORD) as switch:
            self.switch_port(switch.port)
            a = reader.read_device(device, credentials=("admin", PASSWORD))
            credentials.remember(device.id, device.ip, "admin", PASSWORD,
                                 group="switch")
            b = reader.read_device(
                device,
                credentials=credentials.lookup(device.id, device.ip,
                                               group="switch"))
        self.assertEqual(a.state, b.state)
        self.assertEqual(a.fields, b.fields)


if __name__ == "__main__":
    unittest.main()
