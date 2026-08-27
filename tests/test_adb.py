#!/usr/bin/env python3
"""The ADB screen: a device list of its own, and work on several at once.

Nothing here touches a real device — `FakeAdb` stands in for the executable,
the way `tests/test_lcd_ip.py` does for the commissioning run. What the fake
can prove is exactly what tends to go wrong in this code and cannot be seen by
reading it: which commands are sent, IN WHICH ORDER, and what is left behind
when one of them fails half way.

The one thing it cannot prove is that an init service written to `/system`
actually starts the application when the display is powered back on. That is
verified by hand, on hardware.
"""
from __future__ import annotations

import json
import re
import shlex
import threading
import time
from contextlib import contextmanager
from unittest import mock

from panel import settings
from panel.adb import apps, autostart, binary, packages, pool
from panel.adb import client as adb_client
from panel.adb.runner import RUNNER
from panel.errors import DeviceError

from .support.base import PanelTest


class Result:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeAdb:
    """An ADB server holding a few Android devices with a file system.

    Only the commands this screen actually sends are answered. Anything else
    comes back as a failure rather than as an empty success — a command
    nobody wrote a case for should show up as a broken test, not as a silent
    pass.
    """

    LAUNCHER = "com.example.gebze/.MainActivity"

    def __init__(self, devices=None, *, system_writable=True,
                 push_to_system=True, start_fails=False,
                 uninstall_fails=False, refuse=(), magisk_su=False):
        # ip -> {"packages": [...], "files": {path: text},
        #        "modes": {path: mode}}
        self.live = {ip: {"packages": list(record.get("packages", [])),
                          "files": dict(record.get("files", {})),
                          "modes": {}}
                     for ip, record in (devices or {}).items()}
        self.connected: set[str] = set()
        self.calls: list[list[str]] = []
        self.timeline: list[str] = []
        # Which of the three write routes this device allows.
        self.system_writable = system_writable
        self.push_to_system = push_to_system
        self.start_fails = start_fails
        self.uninstall_fails = uninstall_fails
        # Paths the device ACCEPTS AND THEN DOES NOT KEEP: the command
        # reports success and the file is not there afterwards. That is the
        # failure the read-back exists to catch.
        self.refuse = set(refuse)
        # Does this image carry a Magisk-style `su` that takes `-c`? The
        # Compartment LCDs do; the AOSP displays do not. Off by default so
        # the harder of the two is what the suite exercises.
        self.magisk_su = magisk_su
        self.staged: dict[str, str] = {}

    # ── plumbing ────────────────────────────────────────────────────────
    @staticmethod
    def ip_of(target: str) -> str:
        return target.rsplit(":", 1)[0]

    def __call__(self, args, **_kwargs):
        args = list(args)
        self.calls.append(args)
        verb = args[1]
        if verb == "disconnect":
            self.connected.discard(self.ip_of(args[2]))
            return Result("disconnected\n")
        if verb == "connect":
            ip = self.ip_of(args[2])
            if ip in self.live:
                self.connected.add(ip)
                return Result(f"connected to {args[2]}\n")
            return Result(f"failed to connect to {args[2]}\n", returncode=1)

        assert verb == "-s", args
        ip = self.ip_of(args[2])
        if ip not in self.connected or ip not in self.live:
            return Result("", "device offline\n", 1)
        action = args[3]
        if action == "get-state":
            return Result("device\n")
        if action == "push":
            return self._push(ip, args[4], args[5])
        if action == "uninstall":
            return self._uninstall(ip, args[4])
        if action == "shell":
            return self._shell(ip, args[4:])
        return Result("", f"unexpected command {action}\n", 1)

    # ── the device ──────────────────────────────────────────────────────
    def _push(self, ip, local, remote):
        from pathlib import Path as _Path

        text = _Path(local).read_text(encoding="utf-8")
        if remote.startswith("/system/") and not self.push_to_system:
            return Result("", "adb: error: failed to copy: Read-only file "
                              "system\n", 1)
        self.timeline.append(f"push:{remote}")
        if remote not in self.refuse:
            self.live[ip]["files"][remote] = text
            # A pushed file is not marked runnable; `_write_file` chmods it
            # afterwards, which this fake grants unconditionally.
            self.live[ip]["modes"][remote] = "0755"
        return Result("1 file pushed\n")

    def _uninstall(self, ip, package):
        if self.uninstall_fails:
            return Result("Failure [DELETE_FAILED_INTERNAL_ERROR]\n")
        self.timeline.append(f"uninstall:{package}")
        record = self.live[ip]
        record["packages"] = [name for name in record["packages"]
                              if name != package]
        return Result("Success\n")

    def _shell(self, ip, command):
        record = self.live[ip]
        joined = " ".join(command)
        # A SCRIPT, not a word list. `adb shell` hands its arguments to the
        # device's shell unquoted, so anything with a space in it arrives
        # here already quoted by the caller (see client.script) — and is
        # taken apart again the same way the device's shell would.
        if command[:2] == ["sh", "-c"]:
            return self._script(record, _unquote(command[2]), root=False)
        if command[0] == "su":
            return self._su(record, command)
        if command[:3] == ["pm", "list", "packages"]:
            return Result("".join(f"package:{name}\n"
                                  for name in record["packages"]))
        if command[:2] == ["am", "force-stop"]:
            self.timeline.append(f"stop:{command[2]}")
            return Result("")
        if command[:3] == ["am", "start", "-n"]:
            if self.start_fails:
                return Result("Starting: Intent\n"
                              "Error: Activity class does not exist.\n")
            self.timeline.append(f"start:{command[3]}")
            return Result(
                f"Starting: Intent {{ cmp={command[3]} }}\n")
        if command[:4] == ["cmd", "package", "resolve-activity", "--brief"]:
            if command[4] in record["packages"]:
                return Result(f"priority=0\n{self.LAUNCHER}\n")
            return Result("No activity found\n")
        if command[:2] == ["dumpsys", "package"]:
            return Result(_DUMPSYS if command[2] in record["packages"] else "")
        if command[0] == "chmod":
            return Result("")
        return Result("", f"unexpected shell {joined}\n", 1)

    # ── the `su` this image carries ──────────────────────────────────────
    def _su(self, record, command):
        """Toybox `su`, which is what the field displays actually have.

        Its usage is `su [WHO [COMMAND...]]`, so it reads `-c` as a USER
        NAME and answers "invalid uid/gid". Modelled rather than smoothed
        over: a panel that only knows the Magisk `su -c` form reports a
        perfectly rootable display as unwritable, which is the bug this
        fake now makes impossible to reintroduce unnoticed.
        """
        if len(command) >= 2 and command[1] == "-c":
            if self.magisk_su:
                return self._script(record, _unquote(command[2]), root=True)
            return Result("", "su: invalid uid/gid '-c'\n", 1)
        if command[1:4] in (["0", "sh", "-c"], ["root", "sh", "-c"]):
            return self._script(record, _unquote(command[4]), root=True)
        return Result("", "usage: su [WHO [COMMAND...]]\n", 1)

    # ── the device's shell ───────────────────────────────────────────────
    def _script(self, record, text, *, root):
        parts = shlex.split(text)
        if text == "id":
            return Result("uid=0(root) gid=0(root)\n" if root
                          else "uid=2000(shell) gid=2000(shell)\n")
        if parts[:2] in (["[", "-e"], ["[", "-x"]):
            path = parts[2]
            # `[ -e p ] && echo YES || echo NO` — the branches are whatever
            # the caller chose to print, read off the script rather than
            # written down twice.
            said = [parts[i + 1] for i, word in enumerate(parts)
                    if word == "echo"]
            held = (path in record["files"] if parts[1] == "-e"
                    else record["modes"].get(path) == "0755")
            if held:
                return Result(f"{said[0]}\n")
            return Result(f"{said[1]}\n" if len(said) > 1 else "\n")
        if parts[:2] == ["rm", "-f"]:
            self._unlink(record, parts[2], root=root)
            return Result("")
        if "mount -o rw,remount" in text:
            return self._transaction(record, text, root=root)
        return Result("", f"unexpected script {text}\n", 1)

    def _unlink(self, record, path, *, root):
        if path.startswith("/system/") and not (root and self.system_writable):
            return
        record["files"].pop(path, None)
        record["modes"].pop(path, None)

    def _transaction(self, record, text, *, root):
        r"""The remount-and-copy, run statement by statement.

        Taken apart the way a shell would rather than with one regex over
        the whole string: `rm -f /system/x; sync` matched by `rm -f (\S+)`
        captures `/system/x;`, semicolon included, and the removal then
        silently does nothing. That is a fake that passes while the product
        is broken, which is worse than no fake at all.
        """
        self.timeline.append("su")
        if not root:
            return Result("", "mount: Operation not permitted\n", 1)
        for statement in re.split(r"[;\n]|&&|\|\|", text):
            parts = shlex.split(statement.strip(" ()"))
            if not parts:
                continue
            if parts[0] == "cp" and len(parts) >= 3:
                self._copy(record, parts[1], parts[2])
            elif parts[0] == "chmod" and len(parts) >= 3:
                if parts[2] in record["files"]:
                    record["modes"][parts[2]] = parts[1]
            elif parts[0] == "rm":
                self._unlink(record, parts[-1], root=True)
        return Result("")

    def _copy(self, record, source, target):
        if target.startswith("/system/") and not self.system_writable:
            return
        if target in self.refuse:
            return
        if source not in record["files"]:
            return
        record["files"][target] = record["files"][source]
        record["modes"][target] = record["modes"].get(source, "0644")
        self.timeline.append(f"copy:{target}")


def _unquote(token: str) -> str:
    """What the device's shell would make of one quoted argument."""
    parts = shlex.split(token)
    return parts[0] if parts else ""


_DUMPSYS = """
  Activity Resolver Table:
    Non-Data Actions:
      android.intent.action.MAIN:
        com.example.gebze/.MainActivity filter 8f2
          Action: "android.intent.action.MAIN"
          Category: "android.intent.category.LAUNCHER"

    versionCode=3 minSdk=21 targetSdk=35
    versionName=1.2.0
"""


class AdbTest(PanelTest):
    """Every test starts with an empty device list and an idle runner."""

    def setUp(self):
        super().setUp()
        pool.clear()
        RUNNER.reset()
        self.addCleanup(RUNNER.reset)
        self.addCleanup(pool.clear)

    def with_adb(self, adb: FakeAdb) -> FakeAdb:
        patch = mock.patch.object(adb_client.subprocess, "run",
                                  side_effect=adb)
        patch.start()
        self.addCleanup(patch.stop)
        return adb

    @staticmethod
    def one_device(**overrides):
        return {"10.1.1.40": {"packages": ["com.example.gebze",
                                           "com.android.settings"],
                              **overrides}}

    @contextmanager
    def held_open(self, ip="10.1.1.40", package="com.example.gebze"):
        """Keep one operation running for the length of the block.

        The fake device answers instantly, so a run started and then asked
        about has usually finished before the question — which is a test
        that passes for the wrong reason. This holds the worker on its one
        device until the block is done with it.
        """
        arrived, release = threading.Event(), threading.Event()

        def wait_there(*_args, **_kwargs):
            arrived.set()
            release.wait(10.0)
            return {"package": package, "action": "stop"}

        with mock.patch.object(apps, "stop", side_effect=wait_there):
            RUNNER.start("stop", [ip], {"package": package})
            self.assertTrue(arrived.wait(10.0), "the operation never started")
            try:
                yield
            finally:
                release.set()
                deadline = time.time() + 15.0
                while RUNNER.busy() and time.time() < deadline:
                    time.sleep(0.01)

    def run_and_wait(self, operation, ips, params=None, timeout=15.0):
        RUNNER.start(operation, ips, params or {})
        deadline = time.time() + timeout
        while RUNNER.busy() and time.time() < deadline:
            time.sleep(0.01)
        self.assertFalse(RUNNER.busy(), "the runner never finished")
        return RUNNER.state()


# ────────────────────────────────────────────────── which adb is run ──
class Binary(AdbTest):

    def test_an_explicit_override_wins(self):
        with mock.patch.dict("os.environ",
                             {binary.ENV_OVERRIDE: "/opt/tools/adb"}):
            self.assertEqual(binary.adb_path(), "/opt/tools/adb")

    def test_a_bundled_copy_is_preferred_over_the_path(self):
        """A shipped package must not depend on the machine having adb.

        That is the whole reason the executable is carried inside the
        bundle: the laptops these are installed on have no Android tools,
        and "the adb command was not found" on a healthy display is the
        failure this removes.
        """
        folder = settings.ROOT / binary.BUNDLE_DIR
        with mock.patch.object(binary, "bundled",
                               return_value=folder / "adb"):
            self.assertEqual(binary.adb_path(), str(folder / "adb"))

    def test_nothing_found_still_returns_a_command(self):
        """Not an exception. A missing executable is reported by the call
        that needed it, as `AdbUnavailable` — which is a DeviceError and
        reaches the screen as a sentence rather than as a crash."""
        with mock.patch.object(binary, "bundled", return_value=None), \
                mock.patch.object(binary.shutil, "which", return_value=None):
            self.assertEqual(binary.adb_path(), "adb")

    def test_a_missing_executable_is_a_readable_device_error(self):
        with mock.patch.object(adb_client.subprocess, "run",
                               side_effect=FileNotFoundError()):
            with self.assertRaises(DeviceError) as caught:
                adb_client.run("devices")
        self.assertIn("adb", str(caught.exception).lower())


# ───────────────────────────────────────────────────── the device list ──
class Pool(AdbTest):

    def test_an_address_is_added_read_back_and_removed(self):
        self.assertEqual(pool.add("10.1.1.40", "bench 1"),
                         [{"ip": "10.1.1.40", "label": "bench 1"}])
        pool.add("10.1.1.41")
        self.assertEqual(pool.addresses(), ["10.1.1.40", "10.1.1.41"])
        self.assertEqual(pool.remove("10.1.1.40"),
                         [{"ip": "10.1.1.41", "label": ""}])

    def test_adding_the_same_address_twice_corrects_the_label(self):
        """Not an error: re-adding is how a label typo is fixed."""
        pool.add("10.1.1.40", "bench 1")
        devices = pool.add("10.1.1.40", "bench 2")
        self.assertEqual(devices, [{"ip": "10.1.1.40", "label": "bench 2"}])

    def test_an_address_with_a_port_is_refused(self):
        """The port is a panel-wide setting. One typed into the address box
        would reach a device the rest of the panel cannot."""
        for bad in ("10.1.1.40:5555", "10.1.1.0/24", "not-an-ip", ""):
            with self.assertRaises(pool.PoolError, msg=bad):
                pool.add(bad)

    def test_a_corrupt_file_leaves_the_screen_working(self):
        """THE OPPOSITE OF THE DEVICEMAP RULE, on purpose.

        A broken DeviceMap stops the panel, because opening it half-read
        would write an address to whatever device sits in that slot. This
        list is a preference somebody typed in; locking them out of a bench
        tool over a file they can retype in thirty seconds is the worse
        outcome.
        """
        path = settings.adb_devices_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(pool.load(), [])
        self.assertEqual(pool.add("10.1.1.40"),
                         [{"ip": "10.1.1.40", "label": ""}])

    def test_a_file_from_another_format_is_ignored_not_guessed_at(self):
        settings.adb_devices_file().parent.mkdir(parents=True, exist_ok=True)
        settings.adb_devices_file().write_text(
            json.dumps({"format": 99, "devices": [{"ip": "10.1.1.40"}]}),
            encoding="utf-8")
        self.assertEqual(pool.load(), [])

    def test_one_bad_row_does_not_take_the_good_ones_with_it(self):
        settings.adb_devices_file().parent.mkdir(parents=True, exist_ok=True)
        settings.adb_devices_file().write_text(json.dumps({
            "format": pool.FORMAT,
            "devices": [{"ip": "10.1.1.40"}, {"ip": "nonsense"},
                        "10.1.1.41", 7, {"ip": "10.1.1.40"}],
        }), encoding="utf-8")
        self.assertEqual(pool.addresses(), ["10.1.1.40", "10.1.1.41"])

    def test_the_file_is_never_left_half_written(self):
        """tmp + replace. A write that dies half way used to leave a file
        that reads as an EMPTY list, and the address book was gone with no
        error anywhere."""
        pool.add("10.1.1.40")
        real = type(settings.adb_devices_file()).replace

        def die(self, target):
            raise OSError("disk full")

        with mock.patch.object(type(settings.adb_devices_file()), "replace",
                               die):
            with self.assertRaises(OSError):
                pool.add("10.1.1.41")
        self.assertIs(type(settings.adb_devices_file()).replace, real)
        # The list is exactly what it was before the failed write.
        self.assertEqual(pool.addresses(), ["10.1.1.40"])

    def test_an_import_reports_what_it_skipped(self):
        """BOTH NUMBERS, ALWAYS. Three good addresses and nine typos import
        three, and an operator told only "3 imported" spends the afternoon
        looking for the other nine on the bench."""
        path = settings.data_dir() / "sent-to-me.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"devices": [
            {"ip": "10.1.1.40", "label": "a"}, {"ip": "10.1.1.41"},
            {"ip": "oops"}, {"label": "no address"},
        ]}), encoding="utf-8")

        entries, skipped = pool.read_import(path)
        self.assertEqual(skipped, 2)
        devices, added = pool.merge(entries)
        self.assertEqual(added, 2)
        self.assertEqual([entry["ip"] for entry in devices],
                         ["10.1.1.40", "10.1.1.41"])

    def test_a_bare_array_of_addresses_is_accepted(self):
        """The common case: a column pasted out of a spreadsheet."""
        path = settings.data_dir() / "plain.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(["10.1.1.40", "10.1.1.41"]),
                        encoding="utf-8")
        entries, skipped = pool.read_import(path)
        self.assertEqual((len(entries), skipped), (2, 0))

    def test_importing_adds_and_never_replaces(self):
        """Somebody importing a colleague's list has their own four devices
        on the bench in front of them."""
        pool.add("10.1.1.40", "mine")
        path = settings.data_dir() / "theirs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(["10.1.1.41", "10.1.1.40"]),
                        encoding="utf-8")
        entries, _ = pool.read_import(path)
        devices, added = pool.merge(entries)
        self.assertEqual(added, 1)
        self.assertEqual(devices[0], {"ip": "10.1.1.40", "label": "mine"})


# ─────────────────────────────────────────────── finding the application ──
class Packages(AdbTest):

    def test_a_keyword_finds_the_bundle_on_every_device(self):
        adb = self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze", "com.other"]},
            "10.1.1.41": {"packages": ["com.example.gebze"]},
        }))
        found = packages.search(["10.1.1.40", "10.1.1.41"], "gebze")
        self.assertEqual(len(found["packages"]), 1)
        self.assertEqual(found["packages"][0]["present"],
                         ["10.1.1.40", "10.1.1.41"])
        self.assertEqual(found["packages"][0]["missing"], [])
        self.assertFalse(adb.connected)

    def test_a_device_without_the_package_is_named_not_hidden(self):
        """The obvious presentation — one list of names — makes the display
        that has not had the application installed invisible, and the
        operator learns about it by watching one row fail."""
        self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze"]},
            "10.1.1.41": {"packages": ["com.android.settings"]},
        }))
        found = packages.search(["10.1.1.40", "10.1.1.41"], "gebze")
        self.assertEqual(found["packages"][0]["missing"], ["10.1.1.41"])

    def test_an_unreachable_device_is_a_third_thing(self):
        """"Not installed here" and "did not answer" have different fixes,
        so an address that never replied is NOT listed as missing the
        package."""
        self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze"]},
        }))
        found = packages.search(["10.1.1.40", "10.1.1.99"], "gebze")
        self.assertEqual(found["packages"][0]["missing"], [])
        self.assertEqual([row["ip"] for row in found["failed"]],
                         ["10.1.1.99"])

    def test_several_words_are_searched_at_once(self):
        """A bench rarely holds one kind of display. Four devices running
        three customers' applications is the ordinary case, and searching
        them one word at a time is three searches for one intention."""
        self.with_adb(FakeAdb({
            "10.1.1.45": {"packages": ["com.piton.gebze", "com.android.x"]},
            "10.1.1.46": {"packages": ["com.piton.darica"]},
        }))
        found = packages.search(["10.1.1.45", "10.1.1.46"], "gebze, darica")
        self.assertEqual([entry["name"] for entry in found["packages"]],
                         ["com.piton.darica", "com.piton.gebze"])
        self.assertEqual(found["keywords"], ["gebze", "darica"])

    def test_the_words_are_split_on_commas_and_semicolons(self):
        """A list pasted out of a spreadsheet arrives with whichever
        separator that spreadsheet used, and with its own spacing."""
        self.assertEqual(packages.keywords(" gebze , darica ;; lrm , gebze "),
                         ["gebze", "darica", "lrm"])

    def test_one_short_word_spoils_the_whole_list(self):
        """Otherwise it quietly pulls the entire system in beside the three
        packages that were actually wanted."""
        self.with_adb(FakeAdb(self.one_device()))
        with self.assertRaises(ValueError):
            packages.search(["10.1.1.40"], "gebze, a")

    def test_a_keyword_of_one_character_is_refused(self):
        self.with_adb(FakeAdb(self.one_device()))
        with self.assertRaises(ValueError):
            packages.search(["10.1.1.40"], "g")

    def test_the_filtering_happens_here_not_on_the_device(self):
        """A locked-down image is not guaranteed to have the shell utilities
        a pipeline would need, so the whole list comes back and is searched
        in Python."""
        adb = self.with_adb(FakeAdb(self.one_device()))
        packages.search(["10.1.1.40"], "gebze")
        listing = next(call for call in adb.calls if "pm" in call)
        self.assertEqual(listing[-3:], ["pm", "list", "packages"])


# ───────────────────────────────────────────────────────── operations ──
class Apps(AdbTest):

    def test_the_activity_is_resolved_from_the_device(self):
        """Nobody types a component. It is whatever the manifest declares as
        MAIN/LAUNCHER and differs between builds of the same application."""
        adb = self.with_adb(FakeAdb(self.one_device()))
        result = apps.start("10.1.1.40", "com.example.gebze")
        self.assertEqual(result["activity"], FakeAdb.LAUNCHER)
        self.assertIn(f"start:{FakeAdb.LAUNCHER}", adb.timeline)

    def test_dumpsys_answers_when_cmd_package_is_missing(self):
        """`cmd package` arrived in Android 7 and some of these locked-down
        images have it removed."""
        adb = self.with_adb(FakeAdb(self.one_device()))
        original = adb._shell

        def without_cmd(ip, command):
            if command[0] == "cmd":
                return Result("", "cmd: not found\n", 127)
            return original(ip, command)

        adb._shell = without_cmd
        # `launcher_activity` is called here directly, so the transport it
        # normally inherits from `start` has to be opened by hand.
        self.assertTrue(adb_client.connect("10.1.1.40", attempts=1))
        self.assertEqual(
            apps.launcher_activity("10.1.1.40", "com.example.gebze"),
            FakeAdb.LAUNCHER)

    def test_am_start_exiting_zero_is_not_believed(self):
        """It prints `Error: Activity class ... does not exist` and exits 0.
        A caller that trusts the exit code reports a launch that never
        happened."""
        self.with_adb(FakeAdb(self.one_device(), start_fails=True))
        with self.assertRaises(DeviceError):
            apps.start("10.1.1.40", "com.example.gebze")

    def test_a_failing_uninstall_is_not_read_as_success(self):
        self.with_adb(FakeAdb(self.one_device(), uninstall_fails=True))
        with self.assertRaises(DeviceError):
            apps.uninstall("10.1.1.40", "com.example.gebze")

    def test_a_restart_is_not_stopped_by_an_app_that_was_not_running(self):
        """Force-stopping something that is not running is normal, and is
        exactly how a restart is used after a crash."""
        adb = self.with_adb(FakeAdb(self.one_device()))
        result = apps.restart("10.1.1.40", "com.example.gebze")
        self.assertEqual(result["action"], "restart")
        self.assertLess(adb.timeline.index("stop:com.example.gebze"),
                        adb.timeline.index(f"start:{FakeAdb.LAUNCHER}"))

    def test_a_package_name_from_outside_is_checked(self):
        for bad in ("", "not a package", "com.example; rm -rf /"):
            with self.assertRaises(ValueError, msg=bad):
                apps.clean_package(bad)


# ───────────────────────────────────────────── running a whole script ──
class Scripts(AdbTest):
    """`adb shell` does not quote its arguments, and that is not a detail.

    Measured on a live display: `shell(ip, "sh", "-c", "a; b")` arrives as
    `sh -c a; b`, so `sh -c a` runs and `b` runs SEPARATELY as whatever user
    adbd happens to be. Half a root transaction succeeding and the other
    half running unprivileged is what "the autostart did not install" looked
    like, with nothing on screen to say so.
    """

    def test_a_script_reaches_the_device_as_one_argument(self):
        adb = self.with_adb(FakeAdb(self.one_device()))
        adb_client.connect("10.1.1.40", attempts=1)
        adb_client.script("10.1.1.40", "echo one; echo two")
        sent = adb.calls[-1]
        self.assertEqual(sent[3:5], ["shell", "sh"])
        # One argument, quotes included — not three words the device's shell
        # would take apart.
        self.assertEqual(len(sent), 7)
        self.assertIn(";", sent[-1])

    def test_a_toybox_su_still_yields_root(self):
        """`su [WHO [COMMAND...]]` reads `-c` as a user name and answers
        "invalid uid/gid". A panel that knows only the Magisk form reports a
        perfectly rootable display as unwritable."""
        self.with_adb(FakeAdb(self.one_device()))
        adb_client.connect("10.1.1.40", attempts=1)
        self.assertEqual(adb_client.root_form("10.1.1.40"),
                         ("su", "0", "sh", "-c"))

    def test_a_magisk_su_is_still_accepted(self):
        """The Compartment LCDs carry that one. Both have to work."""
        adb = self.with_adb(FakeAdb(self.one_device(), magisk_su=True))
        adb_client.connect("10.1.1.40", attempts=1)
        form = adb_client.root_form("10.1.1.40")
        self.assertIn(form, adb_client.SU_FORMS)
        self.assertIn("uid=0", adb_client.output(
            adb_client.root_script("10.1.1.40", "id", form=form)))
        self.assertTrue(adb.calls)

    def test_root_is_proved_and_not_assumed(self):
        """A form that merely exits without a message proves nothing: only
        `id` answering uid=0 does."""
        self.with_adb(FakeAdb({"10.1.1.40": {"packages": []}}))
        adb_client.connect("10.1.1.40", attempts=1)
        with mock.patch.object(adb_client, "SU_FORMS", (("su", "-c"),)):
            with self.assertRaises(adb_client.NoRootShell):
                adb_client.root_form("10.1.1.40")


# ────────────────────────────────────────────────────────── autostart ──
class Autostart(AdbTest):

    def paths(self, package="com.example.gebze"):
        return autostart.files(package)

    def test_the_script_is_written_before_the_service(self):
        """A device carrying the .rc without the .sh runs a service that
        fails on every boot and writes a failure into the log for ever — the
        one arrangement worse than not installing it at all."""
        adb = self.with_adb(FakeAdb(self.one_device(files={})))
        autostart.install("10.1.1.40", "com.example.gebze")
        script, service = self.paths()
        pushes = [entry for entry in adb.timeline
                  if entry.startswith(("push:", "copy:"))]
        self.assertLess(pushes.index(f"push:{script}"),
                        pushes.index(f"push:{service}"))

    def test_both_files_end_up_on_the_device(self):
        adb = self.with_adb(FakeAdb(self.one_device(files={})))
        result = autostart.install("10.1.1.40", "com.example.gebze")
        script, service = self.paths()
        files = adb.live["10.1.1.40"]["files"]
        self.assertIn(script, files)
        self.assertIn(service, files)
        self.assertEqual(result["route"], "push")
        # The service names the script and the property that triggers it;
        # without either, init runs nothing and says nothing.
        self.assertIn(script, files[service])
        self.assertIn("sys.boot_completed", files[service])
        self.assertIn(FakeAdb.LAUNCHER, files[script])

    def test_a_device_that_refuses_a_direct_push_is_written_through_su(self):
        """The second route: stage in /data/local/tmp, remount, copy. Same
        `su` the address write already relies on."""
        adb = self.with_adb(FakeAdb(self.one_device(files={}),
                                    push_to_system=False))
        result = autostart.install("10.1.1.40", "com.example.gebze")
        self.assertEqual(result["route"], "su")
        self.assertIn("su", adb.timeline)
        for path in self.paths():
            self.assertIn(path, adb.live["10.1.1.40"]["files"])

    def test_presence_is_decided_by_a_token_the_device_prints(self):
        """It used to be decided by looking for the path in `ls -lZ` output.

        Toybox `ls` reports a MISSING file as `ls: /system/bin/x: Invalid
        argument` — a line that contains the path. So every missing file
        read as present, the write "succeeded", and the failure surfaced two
        steps later against the wrong file name.
        """
        adb = self.with_adb(FakeAdb(self.one_device(files={})))
        adb_client.connect("10.1.1.40", attempts=1)
        script, _service = self.paths()
        self.assertFalse(autostart._present("10.1.1.40", script))
        self.assertFalse(
            any(call[4] == "ls" for call in adb.calls if len(call) > 4))

    def test_a_device_whose_system_cannot_be_written_gets_nothing(self):
        """NOT HALF OF IT. Leaving one of the two files behind is the
        failure this module exists to avoid."""
        adb = self.with_adb(FakeAdb(self.one_device(files={}),
                                    push_to_system=False,
                                    system_writable=False))
        with self.assertRaises(DeviceError):
            autostart.install("10.1.1.40", "com.example.gebze")
        for path in self.paths():
            self.assertNotIn(path, adb.live["10.1.1.40"]["files"])

    def test_a_failed_verification_takes_the_script_back_off(self):
        """The service write reports success and the file is not there.

        Every command in this transaction can lie: `adb push` prints "1 file
        pushed" and `su -c cp` says nothing at all, on a device whose
        /system quietly discarded the write. The script must not be left
        behind on its own when that happens.
        """
        script, service = self.paths()
        adb = self.with_adb(FakeAdb(self.one_device(files={}),
                                    refuse=(service,)))
        with self.assertRaises(DeviceError):
            autostart.install("10.1.1.40", "com.example.gebze")
        self.assertNotIn(script, adb.live["10.1.1.40"]["files"])
        self.assertNotIn(service, adb.live["10.1.1.40"]["files"])

    def test_each_package_gets_its_own_pair_of_files(self):
        """The hand-written version used one fixed name and could hold
        exactly one application; removing it took the other with it."""
        first = autostart.files("com.example.gebze")
        second = autostart.files("com.example.other")
        self.assertEqual(len(set(first) | set(second)), 4)

    def test_removing_takes_the_service_off_first(self):
        """The reverse of the install order, for the same reason: the
        service is the file that makes a boot fail."""
        adb = self.with_adb(FakeAdb(self.one_device(files={})))
        autostart.install("10.1.1.40", "com.example.gebze")
        autostart.remove("10.1.1.40", "com.example.gebze")
        self.assertEqual(adb.live["10.1.1.40"]["files"], {})

    def test_a_half_removed_autostart_is_reported_as_partial(self):
        """`partial` is not a hedge: it is what an interrupted removal
        leaves, and calling it "absent" hides a device that fails a service
        on every boot."""
        adb = self.with_adb(FakeAdb(self.one_device(files={})))
        autostart.install("10.1.1.40", "com.example.gebze")
        script, _service = self.paths()
        del adb.live["10.1.1.40"]["files"][script]
        state = autostart.state("10.1.1.40", "com.example.gebze")
        self.assertEqual(state["state"], "partial")


# ──────────────────────────────────────────────────────────── the run ──
class Runner(AdbTest):

    def test_every_row_exists_before_the_first_device_is_touched(self):
        """Built as results arrive, the operator watches a table grow from
        nothing and cannot tell a device that has not started from one that
        was never included."""
        self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze"]},
            "10.1.1.41": {"packages": ["com.example.gebze"]},
        }))
        started = RUNNER.start("stop", ["10.1.1.40", "10.1.1.41"],
                               {"package": "com.example.gebze"})
        self.assertEqual([row["ip"] for row in started["rows"]],
                         ["10.1.1.40", "10.1.1.41"])
        while RUNNER.busy():
            time.sleep(0.01)

    def test_one_device_failing_does_not_end_the_run(self):
        """Twelve displays on a bench, one with a cable out — the other
        eleven are still the work."""
        self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze"]},
            "10.1.1.42": {"packages": ["com.example.gebze"]},
        }))
        state = self.run_and_wait(
            "start", ["10.1.1.40", "10.1.1.99", "10.1.1.42"],
            {"package": "com.example.gebze"})
        by_ip = {row["ip"]: row for row in state["rows"]}
        self.assertEqual(by_ip["10.1.1.40"]["state"], "done")
        self.assertEqual(by_ip["10.1.1.42"]["state"], "done")
        self.assertEqual(by_ip["10.1.1.99"]["state"], "failed")
        self.assertTrue(by_ip["10.1.1.99"]["detail"])

    def test_each_device_gets_its_own_bundle(self):
        """The point of the whole screen. Four displays running different
        customers' applications, one run: a different package name per
        device and one table of results."""
        adb = self.with_adb(FakeAdb({
            "10.1.1.45": {"packages": ["com.piton.gebze"]},
            "10.1.1.46": {"packages": ["com.piton.darica"]},
        }))
        state = self.run_and_wait("stop", [
            {"ip": "10.1.1.45", "package": "com.piton.gebze"},
            {"ip": "10.1.1.46", "package": "com.piton.darica"},
        ])
        self.assertEqual([row["state"] for row in state["rows"]],
                         ["done", "done"])
        self.assertEqual([row["package"] for row in state["rows"]],
                         ["com.piton.gebze", "com.piton.darica"])
        self.assertEqual(sorted(entry for entry in adb.timeline
                                if entry.startswith("stop:")),
                         ["stop:com.piton.darica", "stop:com.piton.gebze"])

    def test_a_device_without_the_bundle_is_never_contacted(self):
        """NO POINTLESS COMMANDS. The screen builds its targets out of what
        the search FOUND, so a display that does not carry the package
        produces no pair — and nothing connects to it to be told there is no
        such package. Proved by the address never appearing in a call."""
        adb = self.with_adb(FakeAdb({
            "10.1.1.45": {"packages": ["com.piton.gebze"]},
            "10.1.1.46": {"packages": []},
        }))
        state = self.run_and_wait(
            "stop", [{"ip": "10.1.1.45", "package": "com.piton.gebze"}])
        self.assertEqual([row["ip"] for row in state["rows"]], ["10.1.1.45"])
        self.assertFalse([call for call in adb.calls
                          if any("10.1.1.46" in part for part in call)])

    def test_one_device_can_carry_two_selected_bundles(self):
        """Two rows for one address, and they must not collapse into one:
        both are real work with their own result."""
        self.with_adb(FakeAdb({
            "10.1.1.45": {"packages": ["com.piton.gebze", "com.piton.darica"]},
        }))
        state = self.run_and_wait("stop", [
            {"ip": "10.1.1.45", "package": "com.piton.gebze"},
            {"ip": "10.1.1.45", "package": "com.piton.darica"},
        ])
        self.assertEqual(len(state["rows"]), 2)
        self.assertEqual({row["package"] for row in state["rows"]},
                         {"com.piton.gebze", "com.piton.darica"})

    def test_the_same_pair_twice_is_one_row(self):
        self.with_adb(FakeAdb(self.one_device()))
        started = RUNNER.start("stop", [
            {"ip": "10.1.1.40", "package": "com.example.gebze"},
            {"ip": "10.1.1.40", "package": "com.example.gebze"},
        ], {})
        self.assertEqual(len(started["rows"]), 1)
        while RUNNER.busy():
            time.sleep(0.01)

    def test_a_bare_address_still_takes_its_package_from_the_run(self):
        """The shape installing an APK needs: the package is inside the
        file, not chosen on screen."""
        self.with_adb(FakeAdb(self.one_device()))
        state = self.run_and_wait("stop", ["10.1.1.40"],
                                  {"package": "com.example.gebze"})
        self.assertEqual(state["rows"][0]["package"], "com.example.gebze")

    def test_a_second_operation_is_refused_while_one_is_running(self):
        """Two at once would be two threads reaching the same display — the
        collision the rest of the panel takes such care to avoid."""
        from panel.adb.runner import RunnerBusy

        self.with_adb(FakeAdb(self.one_device()))
        with self.held_open():
            with self.assertRaises(RunnerBusy):
                RUNNER.start("start", ["10.1.1.40"],
                             {"package": "com.example.gebze"})

    def test_cancelling_skips_the_remaining_devices_whole(self):
        """Checked BEFORE a device, never during one. An APK install cut in
        half leaves a display with no working application, which is worse
        than the wait the operator was trying to stop."""
        adb = self.with_adb(FakeAdb({
            f"10.1.1.4{n}": {"packages": ["com.example.gebze"]}
            for n in range(6)
        }))
        with mock.patch.object(settings, "ADB_WORKERS", 1):
            RUNNER.start("stop", [f"10.1.1.4{n}" for n in range(6)],
                         {"package": "com.example.gebze"})
            RUNNER.cancel()
            while RUNNER.busy():
                time.sleep(0.01)
        state = RUNNER.state()
        states = [row["state"] for row in state["rows"]]
        self.assertIn("cancelled", states)
        # Nothing was left half done: every row is one of the finished
        # states, never `running`.
        self.assertEqual(
            set(states) - {"done", "cancelled", "failed"}, set())
        stops = [entry for entry in adb.timeline if entry.startswith("stop:")]
        self.assertLess(len(stops), 6)

    def test_the_generation_counts_changes_not_polls(self):
        """The screen asks once a second; without this it would redraw the
        whole table every second for an hour-long install."""
        self.with_adb(FakeAdb(self.one_device()))
        self.run_and_wait("stop", ["10.1.1.40"],
                          {"package": "com.example.gebze"})
        settled = RUNNER.state()["generation"]
        for _ in range(5):
            self.assertEqual(RUNNER.state()["generation"], settled)

    def test_an_unknown_operation_is_refused_before_anything_starts(self):
        with self.assertRaises(ValueError):
            RUNNER.start("format_the_disk", ["10.1.1.40"], {})
        self.assertFalse(RUNNER.busy())

    def test_a_run_with_no_device_is_refused(self):
        with self.assertRaises(ValueError):
            RUNNER.start("stop", [], {"package": "com.example.gebze"})


# ──────────────────────────────────────────────────── the refresh lock ──
class RefreshLock(AdbTest):
    """The gap this screen would otherwise open.

    The light refresh reads a Compartment LCD over the same global ADB
    server, and it is held back only by the JOB QUEUE. This screen is not in
    the queue on purpose, so without its own check a two-second round would
    walk straight into an install.
    """

    def test_a_light_refresh_is_refused_while_the_screen_is_working(self):
        from panel.api import service

        self.with_adb(FakeAdb(self.one_device()))
        with self.held_open():
            response = service.call("POST", "/api/refresh", body={"set": 1})
        self.assertEqual(response.status, 409)
        self.assertTrue(response.body["waiting"])
        # And it is allowed again the moment the operation ends — a lock
        # that is not released reads as a panel that stopped refreshing.
        self.assertEqual(
            service.call("POST", "/api/refresh", body={"set": 1}).status, 200)
