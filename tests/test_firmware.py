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
import struct
import tempfile
import time
from unittest import mock
import zipfile

from panel import firmware, jobs, settings
from panel.errors import NotApplicableError, VerificationError
from panel.firmware import apk_install
from panel.firmware.apk_metadata import ApkMetadataError, read_apk_metadata
from panel.system import files

from .support import fakes
from .support.base import PanelTest, ServiceTest


def image(name: str, content: bytes = b"BIN") -> str:
    path = Path(tempfile.mkdtemp(prefix="fw-test-")) / name
    path.write_bytes(content)
    return str(path)


def apk(name: str = "panel.apk", package: str = "com.piton.train_lcd_panel",
        version: str = "0.0.6", manifest: bytes | None = None) -> str:
    """Small valid APK-shaped fixture; PackageManager itself is faked."""
    path = Path(tempfile.mkdtemp(prefix="apk-test-")) / name
    xml = manifest or (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        f'package="{package}" android:versionName="{version}"/>').encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("AndroidManifest.xml", xml)
        archive.writestr("classes.dex", b"test")
    return str(path)


def binary_manifest(package: str, version: str) -> bytes:
    """Minimal real AXML manifest for the dependency-free metadata reader."""
    strings = ["manifest", "package", package, "versionName", version]
    encoded = []
    offsets = []
    cursor = 0
    for value in strings:
        raw = value.encode("utf-8")
        item = bytes((len(value), len(raw))) + raw + b"\0"
        offsets.append(cursor)
        encoded.append(item)
        cursor += len(item)
    payload = b"".join(encoded)
    payload += b"\0" * ((-len(payload)) % 4)
    strings_start = 28 + len(offsets) * 4
    pool_size = strings_start + len(payload)
    pool = (struct.pack("<HHIIIIII", 0x0001, 28, pool_size,
                        len(strings), 0, 0x100, strings_start, 0)
            + struct.pack(f"<{len(offsets)}I", *offsets) + payload)

    no_index = 0xFFFFFFFF
    attributes = b"".join((
        struct.pack("<IIIHBBI", no_index, 1, 2, 8, 0, 3, 2),
        struct.pack("<IIIHBBI", no_index, 3, 4, 8, 0, 3, 4),
    ))
    start_size = 36 + len(attributes)
    start = (struct.pack("<HHIII", 0x0102, 16, start_size, 1, no_index)
             + struct.pack("<IIHHHHHH", no_index, 0, 20, 20, 2, 0, 0, 0)
             + attributes)
    total = 8 + len(pool) + len(start)
    return struct.pack("<HHI", 0x0003, 8, total) + pool + start


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
        firmware.select_file([a.id], image("intercom-1.2.6.bin"))
        firmware.select_file([b.id], image("intercom-1.1.9.bin"))

        self.assertEqual(firmware.selection_for(a.id)["name"],
                         "intercom-1.2.6.bin")
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
        firmware.select_file([device.id], image("set1.bin"), set_no=1)

        self.assertTrue(firmware.has_selection(device.id, set_no=1))
        self.assertFalse(firmware.has_selection(device.id, set_no=2))
        self.assertEqual(
            firmware.selection_for(device.id, set_no=2)["selected"], False)
        self.assertEqual(firmware.selections(set_no=2), {})

        firmware.select_file([device.id], image("set2.bin"), set_no=2)
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

    def test_an_android_sized_apk_is_not_rejected_by_the_bin_limit(self):
        _, devices = self.build(1)
        target = Path(tempfile.mkdtemp(prefix="fw-size-")) / "game.apk"
        with target.open("wb") as handle:
            handle.seek(firmware.MAX_BIN_SIZE + 1024)
            handle.write(b"x")

        firmware.select_file([devices[0].id], str(target))

        self.assertTrue(firmware.has_selection(devices[0].id))
        self.assertGreater(firmware.selection_for(devices[0].id)["size"],
                           32 * 1024 * 1024)

    def test_the_small_bin_limit_and_the_apk_upper_bound_stay_separate(self):
        _, devices = self.build(1)
        folder = Path(tempfile.mkdtemp(prefix="fw-size-"))
        oversized_bin = folder / "too-large.bin"
        oversized_apk = folder / "too-large.apk"
        for target, limit in ((oversized_bin, firmware.MAX_BIN_SIZE),
                              (oversized_apk, firmware.MAX_APK_SIZE)):
            with target.open("wb") as handle:
                handle.seek(limit)
                handle.write(b"x")
            with self.assertRaises(ValueError):
                firmware.select_file([devices[0].id], str(target))

        self.assertFalse(firmware.has_selection(devices[0].id))

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


class FilePicker(PanelTest):

    def setUp(self):
        super().setUp()
        # No window in the suite; a test that registers one puts it back.
        self.addCleanup(files.use_window, None)

    def test_linux_uses_the_windows_own_dialog_when_there_is_a_window(self):
        """The Linux picker needed zenity or kdialog installed, or it refused.

        Neither is on a minimal image, and the operator could then not choose
        a firmware file or an APK at all. The window engine already has a
        dialog — this is that dialog.
        """
        opened = {}

        class FakeWindow:
            @staticmethod
            def create_file_dialog(dialog_type, **kwargs):
                opened["type"] = dialog_type
                opened["kwargs"] = kwargs
                return ("/home/operator/panel.apk",)

        files.use_window(FakeWindow())
        with mock.patch.object(files.platform, "system", return_value="Linux"):
            chosen = files.pick_file("Choose .apk", ("apk",))

        self.assertEqual(chosen, "/home/operator/panel.apk")
        self.assertFalse(opened["kwargs"]["allow_multiple"])
        # The extension reaches the dialog as a filter rather than being
        # dropped: a folder of firmware is not a list to scroll.
        self.assertIn("*.apk", " ".join(opened["kwargs"]["file_types"]))

    def test_cancelling_the_window_dialog_is_not_an_error(self):
        class FakeWindow:
            @staticmethod
            def create_file_dialog(*_args, **_kwargs):
                return None

        files.use_window(FakeWindow())
        with mock.patch.object(files.platform, "system", return_value="Linux"):
            self.assertIsNone(files.pick_file("Choose", ("apk",)))

    def test_a_window_dialog_that_fails_falls_back_to_the_command(self):
        """A window engine without a dialog must not lose the picker."""
        class FakeWindow:
            @staticmethod
            def create_file_dialog(*_args, **_kwargs):
                raise RuntimeError("no dialog on this backend")

        files.use_window(FakeWindow())
        with mock.patch.object(files.platform, "system", return_value="Linux"), \
                mock.patch.object(files.shutil, "which",
                                  side_effect=lambda name: "/usr/bin/zenity"
                                  if name == "zenity" else None), \
                mock.patch.object(files.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout="/tmp/a.apk\n", stderr="",
                                         returncode=0)
            self.assertEqual(files.pick_file("Choose", ("apk",)), "/tmp/a.apk")
        self.assertEqual(run.call_args[0][0][0], "zenity")

    def test_macos_and_windows_keep_their_own_dialogs(self):
        """The window dialog is a LINUX fix; the other two are already tuned.

        macOS needs the UTI workaround below and Windows a localised filter.
        Routing those through the window engine would trade a working dialog
        for an untested one.
        """
        class FakeWindow:
            @staticmethod
            def create_file_dialog(*_args, **_kwargs):
                raise AssertionError("the window dialog was used")

        files.use_window(FakeWindow())
        for system, head in (("Darwin", "osascript"), ("Windows", "powershell")):
            with mock.patch.object(files.platform, "system",
                                   return_value=system), \
                    mock.patch.object(files, "as_console_user",
                                      side_effect=lambda c: c), \
                    mock.patch.object(files.subprocess, "run") as run:
                run.return_value = mock.Mock(stdout="", stderr="",
                                             returncode=0)
                files.pick_file("Choose", ("apk",))
            self.assertEqual(run.call_args[0][0][0], head, system)

    def test_browser_mode_has_no_window_and_still_picks(self):
        """`--browser` registers no window; the command path must still run."""
        with mock.patch.object(files.platform, "system", return_value="Linux"), \
                mock.patch.object(files.shutil, "which",
                                  side_effect=lambda name: "/usr/bin/zenity"
                                  if name == "zenity" else None), \
                mock.patch.object(files.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout="/tmp/b.apk\n", stderr="",
                                         returncode=0)
            self.assertEqual(files.pick_file("Choose", ("apk",)), "/tmp/b.apk")

    def test_macos_does_not_treat_apk_as_an_installed_uti(self):
        with mock.patch.object(files.platform, "system", return_value="Darwin"):
            command = files._picker_command("Choose .apk", ("apk",))

        self.assertEqual(command[:2], ["osascript", "-e"])
        self.assertIn("choose file", command[-1])
        self.assertNotIn("of type", command[-1])

    def test_the_save_dialog_names_the_file_before_it_opens(self):
        """The mirror of the picker, for the ADB address list.

        Three platforms, three saving dialogs — `choose file name`,
        SaveFileDialog, `--save`. Each is handed the suggested name so the
        operator confirms rather than types, and each is opened by the same
        command path (and the same hand-back to the logged-in user) as the
        open dialog beside it.
        """
        for system, head in (("Darwin", "osascript"),
                             ("Windows", "powershell")):
            with mock.patch.object(files.platform, "system",
                                   return_value=system):
                command = files._save_command("Save", "adb-devices.json",
                                              ("json",))
            self.assertEqual(command[0], head, system)
            self.assertIn("adb-devices.json", command[-1], system)
        with mock.patch.object(files.platform, "system", return_value="Linux"), \
                mock.patch.object(files.shutil, "which",
                                  side_effect=lambda name: "/usr/bin/zenity"
                                  if name == "zenity" else None):
            command = files._save_command("Save", "adb-devices.json", ("json",))
        self.assertEqual(command[:3],
                         ["zenity", "--file-selection", "--save"])

    def test_a_saved_name_without_a_suffix_gets_one(self):
        """`choose file name` lets a bare word be typed. A list saved as
        "benches" is one the import filter will not even show next time."""
        with mock.patch.object(files.platform, "system",
                               return_value="Darwin"), \
                mock.patch.object(files, "as_console_user",
                                  side_effect=lambda c: c), \
                mock.patch.object(files.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout="/Users/op/benches\n",
                                         stderr="", returncode=0)
            chosen = files.pick_save_path("Save", "adb-devices.json",
                                          ("json",))
        self.assertEqual(chosen, "/Users/op/benches.json")

    def test_a_cancelled_save_dialog_returns_nothing(self):
        """Cancel is not a failure: the caller writes nothing and says
        nothing. macOS reports it as error -128 rather than an exit code."""
        with mock.patch.object(files.platform, "system",
                               return_value="Darwin"), \
                mock.patch.object(files, "as_console_user",
                                  side_effect=lambda c: c), \
                mock.patch.object(files.subprocess, "run") as run:
            run.return_value = mock.Mock(
                stdout="", stderr="execution error: User canceled. (-128)",
                returncode=1)
            self.assertIsNone(
                files.pick_save_path("Save", "adb-devices.json", ("json",)))

    def test_an_elevated_panel_opens_the_dialog_as_the_logged_in_user(self):
        """Root's dialog is empty: no home, no places, no protected folders.

        `create=True` on the geteuid patch: there is no such function on
        Windows, and the branch under test is reached by pretending to be
        macOS. In the product the platform check comes first and short
        circuits, so the missing function is never touched there.

        The panel runs elevated to configure interfaces, so the picker has to
        be handed back to the user at the window server or the operator sees a
        window with nothing to browse and no file to pick.
        """
        with mock.patch.object(files.platform, "system",
                               return_value="Darwin"), \
                mock.patch.object(files.os, "geteuid", return_value=0,
                                  create=True), \
                mock.patch.object(files, "_console_user",
                                  return_value=("tester", 501)):
            command = files.as_console_user(["osascript", "-e", "script"])

        self.assertEqual(
            command,
            ["launchctl", "asuser", "501", "sudo", "-H", "-u", "tester",
             "osascript", "-e", "script"])

    def test_an_unelevated_panel_opens_the_dialog_itself(self):
        with mock.patch.object(files.platform, "system",
                               return_value="Darwin"), \
                mock.patch.object(files.os, "geteuid", return_value=501,
                                  create=True):
            self.assertEqual(files.as_console_user(["osascript"]),
                             ["osascript"])

    def test_root_is_never_handed_back_to_root(self):
        """A login window (or a `sudo` shell owned by root) has no user."""
        with mock.patch.object(files.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout="root\n")
            with mock.patch.dict(files.os.environ, {"SUDO_USER": "root"}):
                self.assertIsNone(files._console_user())


class Install(PanelTest):

    def build(self):
        topology = fakes.device_map([{
            "Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "Intercom", "Port": "11",
            "Status": {"NoError": True}}])
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("Announcement")[0]

    def test_the_image_is_sent_and_the_version_read_back(self):
        _, device = self.build()
        firmware.select_file([device.id],
                             image("intercom-1.2.6.bin", b"IMAJ-VERISI"))
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
        firmware.select_file([device.id], image("intercom-1.2.6.bin"))
        with fakes.announcement(new_version="1.2.6") as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            firmware.install(device, verify_window=10.0)
            paths = [p for method, p in fake.history if method == "POST"]
        self.assertEqual(paths, ["/api/v1/system/firmware"])

    def test_it_fails_when_the_device_reports_no_version_at_all(self):
        """HTTP 200 is not enough: the device has to answer afterwards.

        There is no expected version any more (nobody types one), so what is
        verified is that the device came back and reported SOMETHING.
        """
        _, device = self.build()
        firmware.select_file([device.id], image("intercom-1.3.0.bin"))
        with fakes.announcement(new_version="") as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            with self.assertRaises(VerificationError):
                firmware.install(device, verify_window=4.0)

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
                 install_stderr="", install_returncode=0):
        self.install_output = install_output
        self.install_stderr = install_stderr
        self.install_returncode = install_returncode
        self.versions = list(versions or [DUMPSYS_OLD, DUMPSYS_NEW])
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        out, err, code = "", "", 0
        if "install" in args:
            out, err = self.install_output, self.install_stderr
            code = self.install_returncode
        elif "dumpsys" in args:
            out = self.versions.pop(0) if self.versions else DUMPSYS_NEW
        elif "connect" in args:
            out = "connected"

        class Result:
            stdout = out
            stderr = err
            returncode = code
        return Result()

    def command(self, name: str) -> list[str] | None:
        return next((c for c in self.calls if name in c), None)


class ApkMetadata(PanelTest):

    def test_a_binary_android_manifest_supplies_the_exact_identity(self):
        manifest = binary_manifest("com.imangi.templerun2", "1.112.0")
        path = apk("temple-run.apk", manifest=manifest)

        self.assertEqual(read_apk_metadata(path), {
            "package": "com.imangi.templerun2", "version": "1.112.0"})

    def test_a_zip_without_an_android_manifest_is_not_an_apk(self):
        path = Path(tempfile.mkdtemp(prefix="apk-test-")) / "fake.apk"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", "not an app")
        with self.assertRaises(ApkMetadataError):
            read_apk_metadata(path)


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
        path = apk("panel-0.0.6.apk")
        firmware.select_file([device.id], path)
        adb = self.patch(FakeAdbInstall())

        result = firmware.install(device)

        self.assertEqual((result["previous"], result["current"]),
                         ("0.0.5", "0.0.6"))
        self.assertTrue(result["changed"])
        install = adb.command("install")
        self.assertIsNotNone(install)
        self.assertIn("-r", install)
        self.assertEqual(install[-1], path)
        # The connection is opened and closed; no adb session is left hanging.
        self.assertIsNotNone(adb.command("connect"))
        self.assertIsNotNone(adb.command("disconnect"))
        # The version is verified from the same place the probe reads it.
        self.assertIsNotNone(adb.command("dumpsys"))

    def test_an_install_error_becomes_a_clear_message(self):
        _, device = self.build()
        firmware.select_file([device.id], apk("bozuk.apk"))
        self.patch(FakeAdbInstall(
            install_output="Failure [INSTALL_FAILED_INVALID_APK]"))
        with self.assertRaises(VerificationError) as caught:
            firmware.install(device)
        self.assertIn("not a valid APK", str(caught.exception))

    def test_success_text_with_a_failed_exit_status_is_not_accepted(self):
        _, device = self.build()
        firmware.select_file([device.id], apk("bozuk.apk"))
        self.patch(FakeAdbInstall(install_output="Success\n",
                                  install_returncode=1))
        with self.assertRaises(VerificationError):
            firmware.install(device)

    def test_a_downgrade_is_done_on_the_second_attempt(self):
        """Going back to an older build happens in the field: retried with -d."""
        _, device = self.build()
        firmware.select_file([device.id], apk("panel-0.0.4.apk",
                                              version="0.0.5"))

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

    def test_another_package_is_verified_by_its_own_apk_identity(self):
        """A temporary test app is not forced to use the panel package id."""
        _, device = self.build()
        path = apk("temple-run.apk", package="com.imangi.templerun2",
                   version="1.112.0")
        firmware.select_file([device.id], path)
        current = "    versionCode=7\n    versionName=1.112.0"
        adb = self.patch(FakeAdbInstall(versions=["", current]))

        result = firmware.install(device)

        self.assertEqual(result["package"], "com.imangi.templerun2")
        self.assertEqual(result["current"], "1.112.0")
        dumpsys = [call for call in adb.calls if "dumpsys" in call]
        self.assertEqual(len(dumpsys), 2)
        self.assertTrue(all(call[-1] == "com.imangi.templerun2"
                            for call in dumpsys))

    def test_success_is_rejected_when_the_selected_package_is_not_present(self):
        _, device = self.build()
        firmware.select_file([device.id], apk(
            "temple-run.apk", package="com.imangi.templerun2",
            version="1.112.0"))
        self.patch(FakeAdbInstall(versions=["", ""]))
        with self.assertRaises(VerificationError) as caught:
            firmware.install(device)
        self.assertIn("version could not be read", str(caught.exception))

    def test_a_version_other_than_the_apks_own_is_an_error(self):
        """The APK's manifest is the only expectation there is.

        Nobody types a version any more: what has to appear on the device
        afterwards is exactly what the chosen file declares.
        """
        _, device = self.build()
        firmware.select_file([device.id], apk("panel-0.0.9.apk",
                                              version="0.0.9"))
        self.patch(FakeAdbInstall())
        with self.assertRaises(VerificationError) as caught:
            firmware.install(device)
        self.assertIn("0.0.6", str(caught.exception))

    def test_a_missing_adb_is_a_not_applicable_error(self):
        _, device = self.build()
        firmware.select_file([device.id], apk("panel.apk"))

        def missing(*a, **k):
            raise FileNotFoundError("adb")

        self.patch(missing)
        with self.assertRaises(NotApplicableError):
            firmware.install(device)

    def test_a_file_named_apk_but_not_an_apk_never_reaches_adb(self):
        _, device = self.build()
        firmware.select_file([device.id], image("fake.apk"))
        adb = self.patch(FakeAdbInstall())

        with self.assertRaises(VerificationError) as caught:
            firmware.install(device)

        self.assertIn("not a valid APK", str(caught.exception))
        self.assertEqual(adb.calls, [])


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

    def build_lcd(self):
        topology = fakes.device_map([{
            "Name": "Compartment_Lcd_1", "IP": "10.n.1.40",
            "IsActive": True, "Type": "LCD", "SubType": "Compartment",
            "Port": "13", "Status": {},
        }])
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("LCD")[0]

    def test_the_group_list_and_selection_are_visible_from_the_endpoint(self):
        inventory = self.build()
        base = self.start_service()
        devices = inventory.by_type("Announcement")

        code, body = self.call(base, "/api/firmware?set=1&group=Intercom")
        self.assertEqual(code, 200)
        self.assertEqual(len(body["devices"]), 2)
        self.assertTrue(all(d["installable"] for d in body["devices"]))
        self.assertEqual(body["selectedCount"], 0)
        self.assertEqual(body["maxSize"], firmware.MAX_BIN_SIZE)
        # No version is invented before a scan.
        self.assertEqual(body["devices"][0]["currentVersion"], "")

        code, body = self.call(base, "/api/firmware/file", {
            "set": 1, "devices": [devices[0].id],
            "path": image("intercom-1.2.6.bin")})
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

    def test_the_suffix_is_enforced_after_picker_and_on_the_path_endpoint(self):
        inventory = self.build()
        device = inventory.by_type("Announcement")[0]
        wrong = image("not-an-image.apk")
        previous = files.pick_file
        files.pick_file = lambda *a, **k: wrong
        self.addCleanup(lambda: setattr(files, "pick_file", previous))
        base = self.start_service()

        for endpoint, body in (
                ("/api/firmware/pick",
                 {"set": 1, "devices": [device.id]}),
                ("/api/firmware/file",
                 {"set": 1, "devices": [device.id], "path": wrong})):
            code, reply = self.call(base, endpoint, body)
            self.assertEqual(code, 400)
            self.assertIn(".bin", reply["error"])
        self.assertFalse(firmware.has_selection(device.id))

    def test_the_picker_accepts_a_typical_large_android_apk(self):
        _inventory, device = self.build_lcd()
        path = Path(tempfile.mkdtemp(prefix="fw-size-")) / "temple-run.apk"
        with path.open("wb") as handle:
            handle.seek(131_259_749)
            handle.write(b"x")
        previous = files.pick_file
        files.pick_file = lambda *a, **k: str(path)
        self.addCleanup(lambda: setattr(files, "pick_file", previous))
        base = self.start_service()

        code, plan = self.call(
            base, "/api/firmware?set=1&group=Compartment%20LCD")
        self.assertEqual(code, 200)
        self.assertEqual(plan["maxSize"], firmware.MAX_APK_SIZE)
        code, reply = self.call(base, "/api/firmware/pick", {
            "set": 1, "devices": [device.id]})

        self.assertEqual(code, 200)
        self.assertEqual(reply["deviceCount"], 1)
        self.assertEqual(
            firmware.selection_for(device.id)["name"], "temple-run.apk")

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
                "path": image("intercom-1.2.6.bin")})
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
            "set": 1, "devices": [devices[0].id]})
        self.assertEqual(code, 200)
        self.assertEqual(body["selectedCount"], 1)
        self.assertEqual(call["extensions"], ("bin",))
        self.assertIn(devices[0].name, call["title"])
        record = firmware.selection_for(devices[0].id)
        self.assertEqual(record["name"], "intercom-1.2.6.bin")

    def test_cancelling_the_picker_does_not_break_the_selection(self):
        inventory = self.build()
        devices = inventory.by_type("Announcement")
        firmware.select_file([devices[0].id], image("onceki.bin"))

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

    def test_there_is_no_target_version_endpoint(self):
        """The expected-version field is gone from every screen.

        A selection carries a file and nothing else; what the install checks
        afterwards comes from the file itself.
        """
        inventory = self.build()
        devices = inventory.by_type("Announcement")
        firmware.select_file([devices[0].id], image("intercom-1.2.6.bin"))
        base = self.start_service()
        code, _ = self.call(base, "/api/firmware/version", {
            "set": 1, "devices": [devices[0].id], "version": "1.3.0"})
        self.assertEqual(code, 404)
        self.assertNotIn("version",
                         firmware.selection_for(devices[0].id))

    def test_installs_run_in_parallel(self):
        """Devices are independent of each other; waiting in turn is wasteful.

        On a twelve-intercom set a serial run added every wait end to end.
        """
        import threading

        self.build(count=6)
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
