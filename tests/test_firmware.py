#!/usr/bin/env python3
"""Software installation — two device families.

The shared concern here: it must be clear which file went to which device.
The file is chosen PER DEVICE — an intercom can be a different hardware
revision and not take the same .bin as the rest of the group. Keeping a single
"selected file" hid that, and the wrong image went out silently.

Announcement equipment takes an image over HTTP, the Compartment LCD an APK
over adb. On both, "request accepted" alone is not success: the device is read
again and the version must really have changed.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import time

from panel import firmware, jobs, settings
from panel.errors import NotApplicableError, VerificationError
from panel.firmware import apk_install
from panel.system import files

from .support import fakes
from .support.base import PanelTest, ServiceTest


def image(name: str, content: bytes = b"BIN") -> str:
    path = Path(tempfile.mkdtemp(prefix="fw-test-")) / name
    path.write_bytes(content)
    return str(path)


class FileSelection(PanelTest):

    def build(self, count=2):
        devices = [{
            "Name": f"Intercom_{i}", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "Intercom", "Port": str(10 + i),
            "Status": {"NoError": True},
        } for i in range(1, count + 1)]
        inventory = self.build_map(fakes.device_map(devices))
        return inventory, inventory.by_type("Announcement")

    def test_each_device_keeps_its_own_image(self):
        _, devices = self.build()
        a, b = devices[0], devices[1]
        firmware.select_file([a.id], image("intercom-1.2.6.bin"), "1.2.6")
        firmware.select_file([b.id], image("intercom-1.1.9.bin"), "1.1.9")

        self.assertEqual(firmware.selection_for(a.id)["name"],
                         "intercom-1.2.6.bin")
        self.assertEqual(firmware.selection_for(a.id)["version"], "1.2.6")
        self.assertEqual(firmware.selection_for(b.id)["name"],
                         "intercom-1.1.9.bin")
        self.assertEqual(len(firmware.selections()), 2)

    def test_a_selection_can_be_removed(self):
        _, devices = self.build()
        a, b = devices[0], devices[1]
        firmware.select_file([a.id, b.id], image("ortak.bin"))
        self.assertEqual(firmware.clear_selection([a.id]), 1)
        self.assertFalse(firmware.has_selection(a.id))
        self.assertTrue(firmware.has_selection(b.id))
        firmware.clear_all()
        self.assertEqual(firmware.selections(), {})

    def test_the_same_device_id_does_not_leak_between_sets(self):
        _, devices = self.build(1)
        device = devices[0]
        firmware.select_file([device.id], image("set1.bin"), "1.0", set_no=1)

        self.assertTrue(firmware.has_selection(device.id, set_no=1))
        self.assertFalse(firmware.has_selection(device.id, set_no=2))
        self.assertEqual(
            firmware.selection_for(device.id, set_no=2)["selected"], False)
        self.assertEqual(firmware.selections(set_no=2), {})

        firmware.select_file([device.id], image("set2.bin"), "2.0", set_no=2)
        self.assertEqual(firmware.selection_for(device.id, set_no=1)["name"],
                         "set1.bin")
        self.assertEqual(firmware.selection_for(device.id, set_no=2)["name"],
                         "set2.bin")

        firmware.clear_all(1)
        self.assertFalse(firmware.has_selection(device.id, set_no=1))
        self.assertTrue(firmware.has_selection(device.id, set_no=2))

    def test_an_invalid_file_is_not_selected(self):
        _, devices = self.build(1)
        device = devices[0]
        empty = Path(tempfile.mkdtemp(prefix="fw-test-")) / "empty.bin"
        empty.write_bytes(b"")
        for path, expected in (("/no/such/file.bin", "not found"),
                               (str(empty), "is empty")):
            with self.assertRaises(ValueError, msg=path) as caught:
                firmware.select_file([device.id], path)
            self.assertIn(expected, str(caught.exception))
        # None of them may reach the selection.
        self.assertFalse(firmware.has_selection(device.id))

    def test_no_install_on_a_device_without_a_file(self):
        _, devices = self.build(1)
        with self.assertRaises(ValueError) as caught:
            firmware.install(devices[0])
        self.assertIn("No file was selected", str(caught.exception))

    def test_a_device_without_an_install_endpoint_is_rejected(self):
        """Installing exists only on devices with their own HTTP endpoint."""
        topology = fakes.device_map([{
            "Name": "Camera_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Camera", "SubType": "", "Port": "11", "Status": {}}])
        inventory = self.build_map(topology)
        device = inventory.by_type("Camera")[0]
        firmware.select_file([device.id], image("x.bin"))
        with self.assertRaises(NotApplicableError):
            firmware.install(device)


class Install(PanelTest):

    def build(self):
        topology = fakes.device_map([{
            "Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "Intercom", "Port": "11",
            "Status": {"NoError": True}}])
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("Announcement")[0]

    def test_the_image_is_sent_and_the_version_verified(self):
        _, device = self.build()
        firmware.select_file([device.id],
                             image("intercom-1.2.6.bin", b"IMAJ-VERISI"),
                             "1.2.6")
        with fakes.announcement(new_version="1.2.6") as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            result = firmware.install(device, verify_window=10.0)
            sent = list(fake.uploaded)

        self.assertEqual(result["current"], "1.2.6")
        self.assertEqual(result["previous"], "1.2.5")
        self.assertTrue(result["changed"])
        # The body that reached the device really is the selected file.
        self.assertEqual(len(sent), 1)
        self.assertIn(b"IMAJ-VERISI", sent[0])
        self.assertIn(b"intercom-1.2.6.bin", sent[0])
        # The request has the same shape as the device's own UI sends: field
        # name "firmware", part type application/macbinary.
        self.assertIn(b'name="firmware"', sent[0])
        self.assertIn(b"application/macbinary", sent[0])

    def test_the_install_goes_to_the_devices_own_endpoint(self):
        """The endpoint is /api/v1/system/firmware — not "update".

        An install sent to the wrong address failed with HTTP 404.
        """
        _, device = self.build()
        firmware.select_file([device.id], image("intercom-1.2.6.bin"), "")
        with fakes.announcement(new_version="1.2.6") as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            firmware.install(device, verify_window=10.0)
            paths = [p for method, p in fake.history if method == "POST"]
        self.assertEqual(paths, ["/api/v1/system/firmware"])

    def test_it_fails_when_the_expected_version_does_not_arrive(self):
        """HTTP 200 is not enough: a different reported version is an error."""
        _, device = self.build()
        firmware.select_file([device.id], image("intercom-1.3.0.bin"), "1.3.0")
        with fakes.announcement(new_version="1.2.6") as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            with self.assertRaises(VerificationError) as caught:
                firmware.install(device, verify_window=10.0)
        self.assertIn("1.2.6", str(caught.exception))

    def test_a_file_deleted_after_selection_is_caught(self):
        _, device = self.build()
        path = image("gecici.bin")
        firmware.select_file([device.id], path)
        Path(path).unlink()
        with self.assertRaises(ValueError) as caught:
            firmware.install(device)
        self.assertIn("no longer exists", str(caught.exception))


DUMPSYS_OLD = "    versionCode=1 minSdk=21 targetSdk=35\n    versionName=0.0.5"
DUMPSYS_NEW = "    versionCode=2 minSdk=21 targetSdk=35\n    versionName=0.0.6"


class FakeAdbInstall:
    """Stands in for subprocess.run; imitates the adb install flow.

    `install_output` sets the device's answer, `versions` the versions dumpsys
    returns in succession.
    """

    def __init__(self, install_output="Success\n", versions=None,
                 install_stderr=""):
        self.install_output = install_output
        self.install_stderr = install_stderr
        self.versions = list(versions or [DUMPSYS_OLD, DUMPSYS_NEW])
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        out, err = "", ""
        if "install" in args:
            out, err = self.install_output, self.install_stderr
        elif "dumpsys" in args:
            out = self.versions.pop(0) if self.versions else DUMPSYS_NEW
        elif "connect" in args:
            out = "connected"

        class Result:
            stdout = out
            stderr = err
            returncode = 0
        return Result()

    def command(self, name: str) -> list[str] | None:
        return next((c for c in self.calls if name in c), None)


class ApkInstall(PanelTest):
    """Compartment LCD — an APK, not an image; adb, not HTTP."""

    def build(self):
        topology = fakes.device_map([{
            "Name": "Compartment_Lcd_1", "IP": "10.n.1.40", "IsActive": True,
            "Type": "LCD", "SubType": "Compartment", "Port": "13",
            "Status": {}}])
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("LCD")[0]

    def patch(self, fake_adb):
        previous = apk_install.subprocess.run
        apk_install.subprocess.run = fake_adb
        self.addCleanup(
            lambda: setattr(apk_install.subprocess, "run", previous))
        return fake_adb

    def test_an_lcd_expects_an_apk(self):
        _, device = self.build()
        self.assertTrue(firmware.is_supported(device))
        self.assertEqual(firmware.file_extension(device), "apk")

    def test_the_apk_is_installed_with_adb_and_verified(self):
        _, device = self.build()
        apk = image("panel-0.0.6.apk")
        firmware.select_file([device.id], apk, "0.0.6")
        adb = self.patch(FakeAdbInstall())

        result = firmware.install(device)

        self.assertEqual((result["previous"], result["current"]),
                         ("0.0.5", "0.0.6"))
        self.assertTrue(result["changed"])
        install = adb.command("install")
        self.assertIsNotNone(install)
        self.assertIn("-r", install)
        self.assertEqual(install[-1], apk)
        # The connection is opened and closed; no adb session is left hanging.
        self.assertIsNotNone(adb.command("connect"))
        self.assertIsNotNone(adb.command("disconnect"))
        # The version is verified from the same place the probe reads it.
        self.assertIsNotNone(adb.command("dumpsys"))

    def test_an_install_error_becomes_a_clear_message(self):
        _, device = self.build()
        firmware.select_file([device.id], image("bozuk.apk"))
        self.patch(FakeAdbInstall(
            install_output="Failure [INSTALL_FAILED_INVALID_APK]"))
        with self.assertRaises(VerificationError) as caught:
            firmware.install(device)
        self.assertIn("not a valid APK", str(caught.exception))

    def test_a_downgrade_is_done_on_the_second_attempt(self):
        """Going back to an older build happens in the field: retried with -d."""
        _, device = self.build()
        firmware.select_file([device.id], image("panel-0.0.4.apk"))

        class Downgrade(FakeAdbInstall):
            def __init__(self):
                super().__init__(versions=[DUMPSYS_NEW, DUMPSYS_OLD])
                self.attempt = 0

            def __call__(self, args, **kwargs):
                if "install" in args:
                    self.attempt += 1
                    self.install_output = (
                        "Failure [INSTALL_FAILED_VERSION_DOWNGRADE]"
                        if self.attempt == 1 else "Success")
                return super().__call__(args, **kwargs)

        adb = self.patch(Downgrade())
        result = firmware.install(device)
        self.assertEqual(result["current"], "0.0.5")
        installs = [c for c in adb.calls if "install" in c]
        self.assertEqual(len(installs), 2)
        self.assertNotIn("-d", installs[0])
        self.assertIn("-d", installs[1])

    def test_another_packages_apk_is_caught(self):
        """The install succeeded but the expected package is nowhere."""
        _, device = self.build()
        firmware.select_file([device.id], image("baska.apk"))
        self.patch(FakeAdbInstall(versions=[DUMPSYS_OLD, ""]))
        with self.assertRaises(VerificationError) as caught:
            firmware.install(device)
        self.assertIn("version could not be read", str(caught.exception))

    def test_a_mismatched_target_version_is_an_error(self):
        _, device = self.build()
        firmware.select_file([device.id], image("panel-0.0.9.apk"), "0.0.9")
        self.patch(FakeAdbInstall())
        with self.assertRaises(VerificationError) as caught:
            firmware.install(device)
        self.assertIn("0.0.6", str(caught.exception))

    def test_a_missing_adb_is_a_not_applicable_error(self):
        _, device = self.build()
        firmware.select_file([device.id], image("panel.apk"))

        def missing(*a, **k):
            raise FileNotFoundError("adb")

        self.patch(missing)
        with self.assertRaises(NotApplicableError):
            firmware.install(device)


class FirmwareEndpoints(ServiceTest):

    def build(self, count=2):
        devices = [{
            "Name": f"Intercom_{i}", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "Intercom", "Port": str(10 + i),
            "Status": {"NoError": True},
        } for i in range(1, count + 1)]
        # A camera in the same set: "apply to group" must not include it.
        devices.append({
            "Name": "Camera_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Camera", "SubType": "", "Port": "20", "Status": {}})
        return self.build_map(fakes.device_map(devices))

    def test_the_group_list_and_selection_are_visible_from_the_endpoint(self):
        inventory = self.build()
        base = self.start_service()
        devices = inventory.by_type("Announcement")

        code, body = self.call(base, "/api/firmware?set=1&group=Intercom")
        self.assertEqual(code, 200)
        self.assertEqual(len(body["devices"]), 2)
        self.assertTrue(all(d["installable"] for d in body["devices"]))
        self.assertEqual(body["selectedCount"], 0)
        # No version is invented before a scan.
        self.assertEqual(body["devices"][0]["currentVersion"], "")

        code, body = self.call(base, "/api/firmware/file", {
            "set": 1, "devices": [devices[0].id],
            "path": image("intercom-1.2.6.bin"), "version": "1.2.6"})
        self.assertEqual(code, 200)
        self.assertEqual(body["selectedCount"], 1)

        code, body = self.call(base, "/api/firmware?set=1&group=Intercom")
        selected = {d["deviceId"]: d["file"] for d in body["devices"]}
        self.assertTrue(selected[devices[0].id]["selected"])
        self.assertEqual(selected[devices[0].id]["name"],
                         "intercom-1.2.6.bin")
        self.assertFalse(selected[devices[1].id]["selected"])

    def test_the_api_set_parameter_separates_the_selection(self):
        inventory = self.build()
        base = self.start_service()
        device = inventory.by_type("Announcement")[0]

        code, body = self.call(base, "/api/firmware/file", {
            "set": 1, "devices": [device.id], "path": image("set1.bin")})
        self.assertEqual(code, 200)
        self.assertEqual(body["selectedCount"], 1)

        # Even with the same DeviceMap id, Set 2 shows no selection and no
        # install queue starts.
        code, set2 = self.call(base, "/api/firmware?set=2&group=Intercom")
        self.assertEqual(code, 200)
        self.assertEqual(set2["selectedCount"], 0)
        self.assertFalse(next(d for d in set2["devices"]
                              if d["deviceId"] == device.id)["file"]["selected"])
        code, _error = self.call(base, "/api/firmware/install", {
            "set": 2, "devices": [device.id]})
        self.assertEqual(code, 400)

        self.call(base, "/api/firmware/file", {
            "set": 2, "devices": [device.id], "path": image("set2.bin")})
        _c1, set1 = self.call(base, "/api/firmware?set=1&group=Intercom")
        _c2, set2 = self.call(base, "/api/firmware?set=2&group=Intercom")
        file1 = next(d for d in set1["devices"]
                     if d["deviceId"] == device.id)["file"]
        file2 = next(d for d in set2["devices"]
                     if d["deviceId"] == device.id)["file"]
        self.assertEqual((file1["name"], file2["name"]),
                         ("set1.bin", "set2.bin"))

        # "all" clears only the open set's selections.
        self.call(base, "/api/firmware/remove", {"set": 1, "all": True})
        self.assertFalse(firmware.has_selection(device.id, set_no=1))
        self.assertTrue(firmware.has_selection(device.id, set_no=2))

    def test_applying_to_a_group_covers_only_that_group(self):
        inventory = self.build()
        base = self.start_service()
        code, body = self.call(base, "/api/firmware/file", {
            "set": 1, "group": "Intercom", "path": image("ortak.bin")})
        self.assertEqual(code, 200)
        self.assertEqual(body["deviceCount"], 2)
        # The camera is in the same set but not the Intercom group.
        camera = inventory.by_type("Camera")[0]
        self.assertFalse(firmware.has_selection(camera.id))

    def test_no_file_is_assigned_to_a_group_without_an_endpoint(self):
        self.build()
        base = self.start_service()
        code, body = self.call(base, "/api/firmware/file", {
            "set": 1, "group": "Camera", "path": image("shared.bin")})
        self.assertEqual(code, 400)
        self.assertIn("is not defined for the selected devices", body["error"])

    def test_an_invalid_path_returns_400(self):
        self.build()
        base = self.start_service()
        code, body = self.call(base, "/api/firmware/file", {
            "set": 1, "group": "Intercom", "path": "/yok/olmayan.bin"})
        self.assertEqual(code, 400)
        self.assertIn("not found", body["error"])

    def test_no_install_starts_without_a_selection(self):
        self.build()
        base = self.start_service()
        code, body = self.call(base, "/api/firmware/install",
                               {"set": 1, "group": "Intercom"})
        self.assertEqual(code, 400)
        self.assertIn("No device has a file selected", body["error"])
        self.assertEqual(jobs.QUEUE.list(), [])

    def test_only_a_device_with_a_file_enters_the_queue(self):
        inventory = self.build()
        devices = inventory.by_type("Announcement")
        with fakes.announcement(new_version="1.2.6") as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            base = self.start_service()
            self.call(base, "/api/firmware/file", {
                "set": 1, "devices": [devices[0].id],
                "path": image("intercom-1.2.6.bin"), "version": "1.2.6"})
            code, body = self.call(base, "/api/firmware/install",
                                   {"set": 1, "group": "Intercom"})
            self.assertEqual(code, 200)
            job = self.await_job(jobs.QUEUE.find(body["id"]), 40.0)

        rows = job.dto()["rows"]
        self.assertEqual(len(rows), 1,
                         "a device without a file must not enter the queue")
        self.assertEqual(rows[0]["state"], "done")
        self.assertIn("intercom-1.2.6.bin", rows[0]["note"])

    def test_the_file_is_assigned_from_the_picker(self):
        """The image path does not come from the client; it comes from the OS
        picker."""
        inventory = self.build()
        devices = inventory.by_type("Announcement")
        chosen = image("intercom-1.2.6.bin")
        call = {}

        def fake_pick(title="", extensions=()):
            call.update(title=title, extensions=extensions)
            return chosen

        previous = files.pick_file
        files.pick_file = fake_pick
        self.addCleanup(lambda: setattr(files, "pick_file", previous))

        base = self.start_service()
        code, body = self.call(base, "/api/firmware/pick", {
            "set": 1, "devices": [devices[0].id], "version": "1.2.6"})
        self.assertEqual(code, 200)
        self.assertEqual(body["selectedCount"], 1)
        self.assertEqual(call["extensions"], ("bin",))
        self.assertIn(devices[0].name, call["title"])
        record = firmware.selection_for(devices[0].id)
        self.assertEqual((record["name"], record["version"]),
                         ("intercom-1.2.6.bin", "1.2.6"))

    def test_cancelling_the_picker_does_not_break_the_selection(self):
        inventory = self.build()
        devices = inventory.by_type("Announcement")
        firmware.select_file([devices[0].id], image("onceki.bin"), "1.0.0")

        previous = files.pick_file
        files.pick_file = lambda *a, **k: None      # the user cancelled
        self.addCleanup(lambda: setattr(files, "pick_file", previous))

        base = self.start_service()
        code, body = self.call(base, "/api/firmware/pick",
                               {"set": 1, "devices": [devices[0].id]})
        self.assertEqual(code, 200)
        self.assertTrue(body["cancelled"])
        self.assertEqual(firmware.selection_for(devices[0].id)["name"],
                         "onceki.bin")

    def test_an_unopenable_picker_returns_an_error(self):
        self.build()
        previous = files.pick_file

        def explode(*a, **k):
            raise RuntimeError("No file picker found")

        files.pick_file = explode
        self.addCleanup(lambda: setattr(files, "pick_file", previous))

        base = self.start_service()
        code, body = self.call(base, "/api/firmware/pick",
                               {"set": 1, "group": "Intercom"})
        self.assertEqual(code, 500)
        self.assertIn("picker", body["error"])

    def test_the_target_version_changes_without_touching_the_file(self):
        inventory = self.build()
        devices = inventory.by_type("Announcement")
        firmware.select_file([devices[0].id], image("intercom-1.2.6.bin"),
                             "1.2.6")
        base = self.start_service()
        code, _ = self.call(base, "/api/firmware/version", {
            "set": 1, "devices": [devices[0].id], "version": "1.3.0"})
        self.assertEqual(code, 200)
        record = firmware.selection_for(devices[0].id)
        self.assertEqual((record["name"], record["version"]),
                         ("intercom-1.2.6.bin", "1.3.0"))

    def test_installs_run_in_parallel(self):
        """Devices are independent of each other; waiting in turn is wasteful.

        On a twelve-intercom set a serial run added every wait end to end.
        """
        import threading

        inventory = self.build(count=6)
        base = self.start_service()
        self.call(base, "/api/firmware/file", {
            "set": 1, "group": "Intercom", "path": image("ortak.bin")})

        lock = threading.Lock()
        state = {"current": 0, "peak": 0}
        previous = firmware.install

        def slow_install(device, credentials=None, **kwargs):
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            time.sleep(0.25)
            with lock:
                state["current"] -= 1
            return {"previous": "1.2.5", "current": "1.2.6", "changed": True}

        firmware.install = slow_install
        self.addCleanup(lambda: setattr(firmware, "install", previous))

        code, body = self.call(base, "/api/firmware/install",
                               {"set": 1, "group": "Intercom"})
        self.assertEqual(code, 200)
        job = self.await_job(jobs.QUEUE.find(body["id"]), 30.0)

        self.assertEqual(state["peak"], settings.FIRMWARE_WORKERS,
                         "as many devices as the pool width must install at once")
        rows = job.dto()["rows"]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r["state"] == "done" for r in rows), rows)
        # But not all at once: installing blacks the device out and the person
        # in the field must be able to see what went down.
        self.assertLess(state["peak"], 6)

    def test_the_selection_remove_endpoint(self):
        inventory = self.build()
        devices = inventory.by_type("Announcement")
        base = self.start_service()
        self.call(base, "/api/firmware/file", {
            "set": 1, "group": "Intercom", "path": image("ortak.bin")})
        code, body = self.call(base, "/api/firmware/remove",
                               {"set": 1, "devices": [devices[0].id]})
        self.assertEqual(code, 200)
        self.assertEqual(body["selectedCount"], 1)
        code, body = self.call(base, "/api/firmware/remove", {"all": True})
        self.assertEqual(body["selectedCount"], 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
