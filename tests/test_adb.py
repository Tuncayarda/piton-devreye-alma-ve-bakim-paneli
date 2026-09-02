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

import builtins
import importlib.util
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from unittest import mock

from panel import settings
from panel.adb import apps, autostart, binary, packages, pool
from panel.adb import client as adb_client
from panel.adb import runner as runner_module
from panel.adb.runner import RUNNER
from panel.errors import DeviceError, VerificationError
from panel.system import files

# The one fake ADB (tests/support/adb.py). It grew up in this file and moved
# out when the probe and the APK install joined the shared transport: three
# suites faking the same `subprocess.run` seam three ways would be the test
# suite repeating the exact bug the consolidation removed.
from .support.adb import FakeAdb, Result
from .support.base import PanelTest


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


# ─────────────────────────────────────────── the ADB server itself ────
class Server(AdbTest):
    """The daemon on THIS computer, as opposed to any display.

    It gets stuck — a display that changed address, a laptop that slept with
    transports open, a second `adb` claiming the port — and the symptom is
    always misleading: every device on the bench "cannot be reached", so the
    operator goes looking at cables.
    """

    def test_a_wedged_server_is_restarted_and_the_run_succeeds(self):
        """The panel tries it ITSELF, once, and only on that signature.

        Every row failing to connect is the daemon; a run where three of four
        worked is three healthy transports a restart would drop for nothing.
        """
        adb = self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze"]},
            "10.1.1.41": {"packages": ["com.example.gebze"]},
        }, wedged=True))

        state = self.run_and_wait("stop", ["10.1.1.40", "10.1.1.41"],
                                  {"package": "com.example.gebze"})

        self.assertEqual(adb.server_restarts, 1, "the server was not restarted")
        self.assertEqual([row["state"] for row in state["rows"]],
                         ["done", "done"])

    def test_one_dead_display_does_not_restart_the_server(self):
        """Three working transports are not thrown away for the fourth."""
        adb = self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze"]},
        }))
        state = self.run_and_wait("stop", ["10.1.1.40", "10.1.1.99"],
                                  {"package": "com.example.gebze"})
        self.assertEqual(adb.server_restarts, 0)
        self.assertEqual(sorted(row["state"] for row in state["rows"]),
                         ["done", "failed"])

    def test_the_operator_can_reset_it_with_nothing_selected(self):
        """Which is exactly when it is reached for: nothing works yet."""
        adb = self.with_adb(FakeAdb({}, wedged=True))
        state = self.run_and_wait("restart_server", [])
        self.assertEqual(len(state["rows"]), 1)
        self.assertEqual(state["rows"][0]["state"], "done")
        # No address, because none was involved.
        self.assertEqual(state["rows"][0]["ip"], "")
        self.assertEqual(adb.server_restarts, 1)
        self.assertTrue(adb_client.server_ok())

    def test_a_restart_that_does_not_come_back_is_a_failure(self):
        self.with_adb(FakeAdb({}))
        with mock.patch.object(adb_client, "restart_server",
                               return_value={"ok": False, "detail": "busy"}):
            state = self.run_and_wait("restart_server", [])
        self.assertEqual(state["rows"][0]["state"], "failed")


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

    def test_no_console_window_opens_on_windows(self):
        """The panel's hottest spawn point, on the console-less build.

        A run over thirty displays is hundreds of adb calls, and each one
        opened its own terminal window over the panel — and the reboot's
        come-back polling kept them coming after the run looked finished.
        The flag is patched in the way `tests/test_switch.py` proves it for
        `interfaces.run_command`: this suite runs on every platform, and off
        Windows the real constant is empty.
        """
        with mock.patch.object(adb_client, "NO_CONSOLE",
                               {"creationflags": 0x08000000}), \
                mock.patch.object(adb_client.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            adb_client.run("devices")
        self.assertEqual(run.call_args.kwargs.get("creationflags"),
                         0x08000000)


# ───────────────────────────────────────────────────── the device list ──
    def test_every_adb_call_in_the_tree_goes_through_the_resolver(self):
        """A bare "adb" defeats the bundled copy, silently.

        `panel/adb/binary.py` exists so a fresh installation can talk to an
        Android display without Android Studio on it. A call site that writes
        the bare name instead reaches PATH or nothing at all — and the ones
        that did were in a `finally` behind `except Exception: pass`, so the
        failure was invisible: the transport simply stayed attached.

        Matched at the CALL, not on the word: "adb" is a legitimate string
        elsewhere (a read method, a view id, an edition's view list).
        """
        call = re.compile(r"""subprocess\.run\(\s*\[\s*["']adb["']""")
        offenders = []
        roots = (settings.ROOT / "panel", settings.ROOT / "field_scripts")
        for path in sorted(p for root in roots for p in root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for match in call.finditer(text):
                line = text[:match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(settings.ROOT)}:{line}")
        self.assertEqual(offenders, [],
                         "these call adb by its bare name instead of "
                         f"adb_path(): {offenders}")

    def test_a_release_build_cannot_be_made_without_the_adb_tools(self):
        """The spec REFUSES rather than warns, and CI has no opt-out.

        Every package CI produced shipped without adb: the workflow never
        downloaded the tools and the spec only printed a note. A display in
        the field then reports itself unreadable while being perfectly
        healthy — which is the failure `panel/adb/binary.py` was written to
        prevent in the first place.
        """
        spec = (settings.ROOT / "dabp.spec").read_text(encoding="utf-8")
        self.assertIn("DAP_ALLOW_NO_ADB", spec,
                      "the deliberate-opt-out escape hatch is gone")
        guard = spec.split("ADB_BINARY.is_file()")[1][:2000]
        self.assertIn("raise SystemExit", guard,
                      "a missing adb must stop the build, not print a note")

        workflow = (settings.ROOT / ".github" / "workflows"
                    / "build-app.yml").read_text(encoding="utf-8")
        # Pinned and verified now, not "-latest-": the archive is copied
        # into every package, so the shipped adb must not change on
        # Google's schedule (tests/test_edition_packaging.py pins the
        # digests themselves).
        self.assertIn("platform-tools_${PT_VERSION}-${ARCHIVE}.zip", workflow,
                      "CI does not fetch the adb tools")
        # ...and it must not hand itself the opt-out. Matched as a YAML
        # assignment, so the name may still be explained in a comment.
        self.assertNotIn("DAP_ALLOW_NO_ADB:", workflow,
                         "CI sets the escape hatch it exists to not need")
        # The case tokens as they are written, so a renamed one fails here
        # rather than matching some unrelated mention of the word.
        for archive in ("ARCHIVE=win", "ARCHIVE=linux", "ARCHIVE=darwin"):
            self.assertIn(archive, workflow, f"no {archive} case in CI")

    def test_the_packaged_self_test_fails_without_a_bundled_adb(self):
        """The second net, on the artifact rather than on the build.

        `--self-test` runs against the packaged application in CI, so a
        package that lost the tools between the spec and the artifact is
        still caught.
        """
        source = (settings.ROOT / "app.py").read_text(encoding="utf-8")
        block = source.split("ADB executable")[1][:400]
        self.assertIn("settings.FROZEN", source.split("ADB executable")[0][-800:],
                      "the check must be a failure only in a package")
        self.assertIn("in the package", block)

    def test_the_field_script_prefers_the_panels_adb_but_runs_without_it(self):
        """`device_verify.py` runs two ways and needs the right answer in both.

        Inside the panel it must use the bundled copy; run on its own from a
        terminal there is no panel to ask and the bare name is correct.
        """
        spec = importlib.util.spec_from_file_location(
            "dv_probe", settings.ROOT / "field_scripts" / "device_verify.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with mock.patch.dict(os.environ,
                             {binary.ENV_OVERRIDE: "/opt/tools/adb"}):
            self.assertEqual(module._adb_binary(), "/opt/tools/adb")

        # No panel to import from: the script still answers, with the bare
        # name, which is what a terminal run wants.
        def refuse(name, *args, **kwargs):
            if name.startswith("panel"):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        real_import = builtins.__import__
        with mock.patch.dict(os.environ, {binary.ENV_OVERRIDE: ""}), \
                mock.patch.object(builtins, "__import__", refuse):
            self.assertEqual(module._adb_binary(), "adb")

class Pool(AdbTest):

    def test_an_address_is_added_read_back_and_removed(self):
        self.assertEqual(pool.add("10.1.1.40", "bench 1"),
                         [{"ip": "10.1.1.40", "label": "bench 1"}])
        pool.add("10.1.1.41")
        self.assertEqual(pool.addresses(), ["10.1.1.40", "10.1.1.41"])
        self.assertEqual(pool.remove("10.1.1.40"),
                         [{"ip": "10.1.1.41", "label": ""}])

    def test_clearing_takes_the_whole_list_out_at_once(self):
        """A bench that has moved on to another train throws the list away.

        Read back through `load()` rather than trusting what `clear()`
        returned: an empty list is also what an unreadable file looks like
        (see `_read`), and the two must not be told apart by luck.
        """
        pool.add_many("10.1.1.40-43", "cabin")
        self.assertEqual(len(pool.load()), 4)
        self.assertEqual(pool.clear(), [])
        self.assertEqual(pool.load(), [])

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
        devices = pool.adopt(entries)
        self.assertEqual([entry["ip"] for entry in devices],
                         ["10.1.1.40", "10.1.1.41"])

    def test_a_file_saved_by_windows_notepad_still_imports(self):
        """Notepad writes JSON with a UTF-8 BOM. One invisible byte must not
        turn a colleague's list into "this is not JSON" (it did, on the
        machine the list was most likely written on)."""
        path = settings.data_dir() / "notepad.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xef\xbb\xbf"
                         + json.dumps(["10.1.1.40"]).encode("utf-8"))
        entries, skipped = pool.read_import(path)
        self.assertEqual((len(entries), skipped), (1, 0))

    def test_a_bare_array_of_addresses_is_accepted(self):
        """The common case: a column pasted out of a spreadsheet."""
        path = settings.data_dir() / "plain.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(["10.1.1.40", "10.1.1.41"]),
                        encoding="utf-8")
        entries, skipped = pool.read_import(path)
        self.assertEqual((len(entries), skipped), (2, 0))

    def test_importing_replaces_the_list_rather_than_adding_to_it(self):
        """The file IS the bench a moment from now.

        It used to add, and the addresses left over from the last train then
        had to be picked out of the table a row at a time — the chore the
        button exists to save. The screen asks first when the list has
        anything in it (views/adb/pool.js importList).
        """
        pool.add("10.1.1.40", "mine")
        pool.add("10.1.1.99", "last train")
        path = settings.data_dir() / "theirs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(["10.1.1.41", "10.1.1.40"]),
                        encoding="utf-8")
        entries, _ = pool.read_import(path)
        devices = pool.adopt(entries)
        # The file's order and the file's labels, and nothing of what was
        # there before: ".40" comes back with an empty label, not "mine".
        self.assertEqual(devices, [{"ip": "10.1.1.41", "label": ""},
                                   {"ip": "10.1.1.40", "label": ""}])
        self.assertEqual(pool.load(), devices)

    def test_an_import_of_nothing_still_empties_the_list(self):
        """A file with no readable row is still the list the operator chose.

        The alternative — leaving the old list when the new one is empty —
        is a screen that says "0 addresses" over four addresses it kept.
        """
        pool.add("10.1.1.40", "mine")
        path = settings.data_dir() / "empty.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"devices": []}), encoding="utf-8")
        entries, skipped = pool.read_import(path)
        self.assertEqual((entries, skipped), ([], 0))
        self.assertEqual(pool.adopt(entries), [])


    def test_one_box_takes_a_list_and_a_range(self):
        """Twelve consecutive displays is twelve rounds of type-tab-Enter.

        BOTH ENDS ARE INCLUDED: "45-47" is three displays to the person
        holding them, and a range that quietly dropped .47 would be found by
        the operator rather than by anyone reading the code.
        """
        self.assertEqual(pool.parse_addresses("10.1.1.45"), ["10.1.1.45"])
        self.assertEqual(pool.parse_addresses("10.1.1.45-47"),
                         ["10.1.1.45", "10.1.1.46", "10.1.1.47"])
        # The long form means the same thing.
        self.assertEqual(pool.parse_addresses("10.1.1.45-10.1.1.47"),
                         pool.parse_addresses("10.1.1.45-47"))
        # Commas, semicolons and plain spaces all separate, and a repeat is
        # collapsed rather than refused.
        self.assertEqual(
            pool.parse_addresses("10.1.1.40, 10.1.1.41;10.1.1.44-45 10.1.1.40"),
            ["10.1.1.40", "10.1.1.41", "10.1.1.44", "10.1.1.45"])
        # A range of one is a range.
        self.assertEqual(pool.parse_addresses("10.1.1.45-45"), ["10.1.1.45"])

    def test_a_bad_piece_fails_the_whole_box(self):
        """Unlike the file import, and the two differ on purpose.

        A file is somebody else's and arrives with whatever is in it. This is
        what the operator just typed: a silently dropped piece is an address
        they believe they added and will go looking for later.
        """
        for bad in ("10.1.1.47-45", "10.1.1.1-10.9.1.1", "10.1.1.45-",
                    "10.1.1.40, oops"):
            with self.subTest(bad):
                with self.assertRaises(pool.PoolError):
                    pool.parse_addresses(bad)
        # And nothing was added on the way to the failure.
        self.assertEqual(pool.addresses(), [])

    def test_a_range_is_added_under_one_label(self):
        devices, added = pool.add_many("10.1.1.45-47", "cabin 3")
        self.assertEqual(added, 3)
        self.assertEqual(devices, [{"ip": "10.1.1.45", "label": "cabin 3"},
                                   {"ip": "10.1.1.46", "label": "cabin 3"},
                                   {"ip": "10.1.1.47", "label": "cabin 3"}])
        # Adding an overlapping range adds only what is new; the count is
        # what the screen reports, so it must not count the ones already in.
        _, added = pool.add_many("10.1.1.46-48")
        self.assertEqual(added, 1)
        self.assertEqual(pool.addresses(), ["10.1.1.45", "10.1.1.46",
                                            "10.1.1.47", "10.1.1.48"])

    def test_what_is_exported_can_be_imported_again(self):
        """The round trip is the point of the format number.

        An exported list is what gets attached to an e-mail and read back on
        another bench. If the two ends drifted, the file would be refused by
        the very screen that wrote it — and `_read` refuses silently, which is
        the worst way to find out.
        """
        pool.add("10.1.1.40", "bench 2")
        pool.add("10.1.1.41")

        path = pool.write_export(settings.data_dir() / "carried-away.json")
        self.assertTrue(path.is_file())
        body = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(body["format"], pool.FORMAT)

        pool.clear()
        entries, skipped = pool.read_import(path)
        self.assertEqual(skipped, 0)
        self.assertEqual(pool.adopt(entries),
                         [{"ip": "10.1.1.40", "label": "bench 2"},
                          {"ip": "10.1.1.41", "label": ""}])

    def test_exporting_an_empty_list_writes_an_empty_list(self):
        """Not an error. The button is disabled on an empty list, but the
        endpoint is reachable without it and must not produce a broken file."""
        path = pool.write_export(settings.data_dir() / "nothing.json")
        body = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(body, {"format": pool.FORMAT, "devices": []})

    def test_the_export_goes_to_documents_by_default(self):
        """Where this panel puts everything meant to be carried away.

        Still the answer when nobody named a folder — a scripted run, a test.
        The screen itself always names one now (below)."""
        self.assertEqual(pool.write_export.__module__, "panel.adb.pool")
        with mock.patch.object(settings, "OUTPUT_DIR",
                               settings.data_dir() / "documents"):
            path = pool.write_export()
        self.assertEqual(path.name, pool.EXPORT_NAME)
        self.assertEqual(path.parent.name, "documents")

    def test_the_export_is_written_where_the_dialog_said(self):
        """The operator picks the folder; the file is not posted a path.

        The list is carried away on a stick or attached to an e-mail, and the
        person doing that has a folder in mind. The path still comes from the
        OS dialog and never from the request — that is what stops this being
        a "write a file anywhere on this machine" endpoint.
        """
        from panel.api import service

        pool.add("10.1.1.40", "bench 2")
        target = settings.data_dir() / "somewhere else" / "bench.json"
        with mock.patch.object(files, "pick_save_path",
                               return_value=str(target)) as dialog:
            response = service.call("POST", "/api/adb/export", body={})
        self.assertTrue(dialog.called)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["file"], "bench.json")
        self.assertEqual(response.body["count"], 1)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         {"format": pool.FORMAT,
                          "devices": [{"ip": "10.1.1.40",
                                       "label": "bench 2"}]})

    def test_a_cancelled_save_dialog_writes_nothing(self):
        """Not an error, and not a toast either: the operator closed the
        window they opened. Same shape as the import picker."""
        from panel.api import service

        with mock.patch.object(files, "pick_save_path", return_value=None):
            response = service.call("POST", "/api/adb/export", body={})
        self.assertEqual(response.status, 200)
        self.assertTrue(response.body["cancelled"])
        self.assertIsNone(response.body.get("file"))


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
        happened.

        There are two routes to starting an application now (`am start -n`
        and, when that will not do, `monkey` — see
        `AttachingTheWholeBench` above). The invariant this test protects is
        unchanged and is the one that matters: when the application did NOT
        start, nothing reports that it did. Both routes therefore fail here.
        """
        self.with_adb(FakeAdb(self.one_device(), start_fails=True,
                              monkey_fails={"com.example.gebze"}))
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

    def test_a_restart_proves_the_transport_once(self):
        """One `_require`, not three. `restart` calling the public `stop`
        and `start` re-proved the same transport per step — three connect
        rounds, ~nine adb processes — and the answer cannot change between
        a stop and the start half a second later."""
        adb = self.with_adb(FakeAdb(self.one_device()))
        apps.restart("10.1.1.40", "com.example.gebze")
        self.assertEqual(
            sum(1 for call in adb.calls if call[1] == "connect"), 1)

    def test_a_package_name_from_outside_is_checked(self):
        for bad in ("", "not a package", "com.example; rm -rf /"):
            with self.assertRaises(ValueError, msg=bad):
                apps.clean_package(bad)


# ───────────────────────────────────────────── running a whole script ──
# ──────────────────────────────────────────── restarting the machine ──
class Reboot(AdbTest):
    """The device, not the application on it."""

    def test_a_reboot_waits_for_the_display_to_answer_again(self):
        """`adb reboot` answers the moment the device accepts it, seconds
        before anything happens and a minute before the display is usable.
        Reported as done at that instant, twelve rows go green on twelve
        displays that are all still dark."""
        adb = self.with_adb(FakeAdb(self.one_device()))

        result = apps.reboot("10.1.1.40")

        self.assertEqual(adb.timeline.count("reboot:10.1.1.40"), 1)
        self.assertEqual(result["action"], "reboot")
        # It knocked, was refused three times, and then got an answer — so
        # the run really did hold the row open across the downtime.
        self.assertGreater(result["seconds"], 0)
        self.assertGreater(self.clock.waited, 0)

    def test_a_device_that_never_goes_down_did_not_take_the_command(self):
        """A display that answers throughout either ignored the reboot or is
        not a device that reboots; either way "done" would be a guess."""
        self.with_adb(FakeAdb(self.one_device(), reboot_downtime=0))

        with self.assertRaises(VerificationError) as caught:
            apps.reboot("10.1.1.40")
        self.assertIn("never went down", str(caught.exception))

    def test_a_display_that_does_not_come_back_is_reported_as_such(self):
        """The one failure the operator most needs naming: eleven displays
        came back and this one did not."""
        self.with_adb(FakeAdb(self.one_device(), reboot_downtime=10_000))

        with self.assertRaises(VerificationError) as caught:
            apps.reboot("10.1.1.40")
        message = str(caught.exception)
        self.assertIn("did not answer again", message)
        # And it says the reboot itself was accepted, so nobody goes looking
        # for a command that was never sent.
        self.assertIn("restarted", message)

    def test_a_refused_reboot_never_starts_the_wait(self):
        adb = self.with_adb(FakeAdb(self.one_device(), reboot_refused=True))

        with self.assertRaises(VerificationError):
            apps.reboot("10.1.1.40")
        self.assertEqual(self.clock.waited, 0.0)
        self.assertNotIn("reboot:10.1.1.40", adb.timeline)

    def test_two_selected_bundles_reboot_the_machine_once(self):
        """The run carries (device, bundle) pairs, and a display holding two
        of the selected bundles produces two of them. For `stop` that is
        exactly right; here it would send the machine the reboot command
        twice, the second time while it is already on its way down."""
        adb = self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze",
                                       "com.example.darica"]},
        }))

        state = self.run_and_wait("reboot", [
            {"ip": "10.1.1.40", "package": "com.example.gebze"},
            {"ip": "10.1.1.40", "package": "com.example.darica"},
        ])

        self.assertEqual(len(state["rows"]), 1)
        self.assertEqual(state["rows"][0]["state"], "done")
        # The bundle column is empty because no bundle was involved in what
        # happened to the machine.
        self.assertEqual(state["rows"][0]["package"], "")
        self.assertEqual(adb.timeline.count("reboot:10.1.1.40"), 1)

    def test_a_reboot_row_says_how_long_the_display_took(self):
        """The number an operator compares displays by when one is sick."""
        self.with_adb(FakeAdb({"10.1.1.40": {"packages": []}}))

        state = self.run_and_wait("reboot", ["10.1.1.40"])

        self.assertEqual(state["rows"][0]["state"], "done")
        self.assertRegex(state["rows"][0]["detail"], r"\d")




class AutostartDiagnosis(AdbTest):
    """Both files sitting where they were written is NOT evidence.

    That was the whole of the old check, and it reported "installed" on a
    display where nothing ran at boot — which is the state that actually
    gets reported from the field. Three different faults produce it and each
    needs a different fix, so the check has to name which.
    """

    def installed(self, **overrides):
        """A display carrying both files, written before the last boot."""
        script, service = autostart.files("com.example.gebze")
        adb = self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze"],
                          "files": {script: "#!/system/bin/sh\n",
                                    service: "service x\n"}},
        }))
        # Written at 1000, booted at 6400 (now 10000 - uptime 3600).
        adb.mtimes = {script: 1000, service: 1000}
        for key, value in overrides.items():
            setattr(adb, key, value)
        return adb

    def test_a_service_init_never_parsed_is_not_reported_as_installed(self):
        """THE FAULT THAT WAS BEING HIDDEN. The files survived a reboot and
        `init.svc.<name>` does not exist, so the .rc was never accepted."""
        self.installed()          # no init.svc property at all

        found = autostart.state("10.1.1.40", "com.example.gebze")

        self.assertEqual(found["state"], "installed")   # the files ARE there
        self.assertEqual(found["verdict"], "notParsed")  # and it still fails

    def test_the_verdict_does_not_lean_on_the_device_clock(self):
        """These displays have no battery-backed clock: they boot in 2024,
        pick the real date up from the network a minute later, and
        now-minus-uptime is nonsense in between. `init.svc.<name>` existing
        is proof init parsed the .rc, which only happens at boot — so it
        beats the arithmetic, which otherwise reported a display that had
        rebooted and run as "not rebooted yet"."""
        name = autostart.service_name("com.example.gebze")
        adb = self.installed(props={f"init.svc.{name}": "stopped"},
                             logcat=[f"{name}: started x/.Main"])
        script, service = autostart.files("com.example.gebze")
        adb.mtimes = {script: 9_999_999, service: 9_999_999}   # "the future"

        found = autostart.state("10.1.1.40", "com.example.gebze")

        self.assertEqual(found["verdict"], "ranOk")

    def test_a_fresh_install_is_not_blamed_on_init(self):
        """Right after installing there has been no boot for any of this to
        have happened at; saying "init refused it" would be a lie the
        operator would act on."""
        adb = self.installed()
        script, service = autostart.files("com.example.gebze")
        adb.mtimes = {script: 9000, service: 9000}      # newer than boot

        found = autostart.state("10.1.1.40", "com.example.gebze")

        self.assertEqual(found["verdict"], "pendingReboot")

    def test_a_running_service_is_reported_as_running(self):
        name = autostart.service_name("com.example.gebze")
        self.installed(props={f"init.svc.{name}": "running"})

        found = autostart.state("10.1.1.40", "com.example.gebze")

        self.assertEqual(found["verdict"], "running")

    def test_a_launch_that_failed_blames_the_activity_not_the_autostart(self):
        """`init.svc` is stopped and the script's own log says it gave up:
        the autostart worked, the activity is the problem. Told apart because
        the two need opposite fixes."""
        name = autostart.service_name("com.example.gebze")
        self.installed(props={f"init.svc.{name}": "stopped"},
                       logcat=[(f"{name}: gave up starting "
                                "com.example.gebze/.MainActivity")])

        found = autostart.state("10.1.1.40", "com.example.gebze")

        self.assertEqual(found["verdict"], "gaveUp")
        self.assertTrue(found["log"], "the device's own words are the fix")

    def test_a_successful_boot_launch_is_reported_as_such(self):
        name = autostart.service_name("com.example.gebze")
        self.installed(props={f"init.svc.{name}": "stopped"},
                       logcat=[f"{name}: started com.example.gebze/.Main"],
                       app_running={"com.example.gebze"})

        found = autostart.state("10.1.1.40", "com.example.gebze")

        self.assertEqual(found["verdict"], "ranOk")
        self.assertTrue(found["appRunning"])

    def test_the_init_service_name_fits_a_property_name(self):
        """Init turns it into `init.svc.<name>`, and on Android 7 and earlier
        a property name had to fit in 32 characters. The package-derived name
        was 36 and init rejected the whole definition — both files present,
        nothing running, which is exactly the report."""
        for package in ("com.example.gebze_osb",
                        "com.a.very.long.vendor.application.name.indeed"):
            name = autostart.service_name(package)
            self.assertLessEqual(len(f"init.svc.{name}"), 32, package)

    def test_two_bundles_get_two_different_service_names(self):
        """They are removed independently; one name would take both."""
        self.assertNotEqual(autostart.service_name("com.example.gebze"),
                            autostart.service_name("com.example.darica"))




class BootScript(AdbTest):
    """What the generated script has to do, learned on the hardware.

    Both of these were found on a display that reported a successful
    autostart and showed nothing, and each on its own is enough to produce
    that.
    """

    def script(self, package="com.example.gebze"):
        return autostart.script_text(package, FakeAdb.LAUNCHER)

    def test_the_service_can_read_other_processes(self):
        """/proc on these displays is mounted `hidepid=2,gid=3009`: a process
        outside group readproc cannot see any other process AT ALL. The
        script checks whether the application it launched is really running,
        and without the group that check answers "no" however well the
        launch went — thirty retries against a healthy app, then a log line
        saying it gave up. An adb shell has readproc, which is exactly why
        the same command worked by hand and not at boot."""
        self.assertIn("readproc", autostart.SERVICE_GROUPS)
        self.assertIn(f"group {autostart.SERVICE_GROUPS}",
                      autostart.service_text("com.example.gebze"))

    def test_the_launch_is_proved_by_the_process_not_the_exit_code(self):
        """`am start` reports success for a launch that never lands — the
        same trap this panel refuses everywhere else."""
        text = self.script()
        self.assertIn('pidof "$PACKAGE"', text)
        # And the package is there to be asked about, not just the component.
        self.assertIn('PACKAGE="com.example.gebze"', text)

    def test_it_waits_past_boot_completed_before_the_first_launch(self):
        """`sys.boot_completed=1` is not the end of starting up: the launcher
        is still coming to the foreground behind it, and an activity started
        into that gap is replaced by the home screen a moment later. That is
        a launch which reports success and leaves nothing on the display."""
        text = self.script()
        after_boot = text.split("sys.boot_completed")[-1]
        self.assertIn(f"sleep {autostart.BOOT_SETTLE}", after_boot)
        self.assertGreater(autostart.BOOT_SETTLE, 0)

    def test_a_launch_is_given_time_before_it_is_judged(self):
        """Asked the instant after `am start`, the process is not up yet and
        every attempt reads as a failure."""
        self.assertGreater(autostart.LAUNCH_SETTLE, 0)
        text = self.script()
        between = text.split("am start")[-1].split("pidof")[0]
        self.assertIn(f"sleep {autostart.LAUNCH_SETTLE}", between)


class VerityDisplay(AdbTest):
    """The display that reported "installed" and started nothing.

    Its /system sits on a verity-backed device-mapper volume. Remounting it
    read-write appears to work, `cp` exits 0, and the file arrives with the
    right owner, the right mode and the right SELinux label — and zero
    bytes. An empty .rc declares no service, so init has nothing to parse
    and the operator has been told it is set up.
    """

    def verity(self, **overrides):
        """A display that keeps a /system write only through an overlay."""
        return self.with_adb(FakeAdb(
            self.one_device(files={}), drops_content=True,
            push_to_system=False, **overrides))

    def test_an_empty_file_is_never_accepted_as_written(self):
        """The check used to be "is the path there?", and the path IS there.
        Only the size tells the two apart."""
        self.verity(adb_root_allowed=False, overlay_allowed=False)

        with self.assertRaises(DeviceError) as caught:
            autostart.install("10.1.1.40", "com.example.gebze")
        self.assertIn("cannot be written", str(caught.exception))

    def test_nothing_is_left_behind_when_no_route_works(self):
        """A display carrying a service whose script is missing runs a
        failing service on every boot — worse than not installing at all.
        The empty files this device DID create must go too."""
        adb = self.verity(adb_root_allowed=False, overlay_allowed=False)

        with self.assertRaises(DeviceError):
            autostart.install("10.1.1.40", "com.example.gebze")
        left = [path for path in adb.live["10.1.1.40"]["files"]
                if path.startswith("/system/")]
        self.assertEqual(left, [], f"left behind on the device: {left}")

    def test_the_overlay_route_is_what_actually_writes(self):
        """`adb root` then `adb remount` mounts an overlayfs whose upper
        layer is really written. Remounting the read-only volume by hand
        looks identical and is not the same thing."""
        adb = self.verity()

        result = autostart.install("10.1.1.40", "com.example.gebze")

        self.assertEqual(result["route"], "overlay")
        self.assertTrue(adb.overlay, "no overlay was ever mounted")
        script, service = autostart.files("com.example.gebze")
        for path in (script, service):
            self.assertTrue(adb.live["10.1.1.40"]["files"][path].strip(),
                            f"{path} landed empty")

    def test_the_service_file_really_declares_the_service(self):
        """What init has to find. The empty file passed every check the
        panel used to make, and declares nothing at all."""
        adb = self.verity()

        autostart.install("10.1.1.40", "com.example.gebze")

        _script, service = autostart.files("com.example.gebze")
        written = adb.live["10.1.1.40"]["files"][service]
        self.assertIn(f"service {autostart.service_name('com.example.gebze')}",
                      written)
        self.assertIn("on property:sys.boot_completed=1", written)


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
        """The LAST route: stage in /data/local/tmp, remount, copy. Same
        `su` the address write already relies on.

        The overlay is taken away as well, because it comes first now and
        would otherwise answer this device — the point here is the image
        that has a working `su` and no `adb remount` at all.
        """
        adb = self.with_adb(FakeAdb(self.one_device(files={}),
                                    push_to_system=False,
                                    adb_root_allowed=False,
                                    overlay_allowed=False))
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
        failure this module exists to avoid.

        Every route is shut: no root adbd, no overlay, no writable /system.
        Anything less and one of the three would answer, which is the point
        of having three.
        """
        adb = self.with_adb(FakeAdb(self.one_device(files={}),
                                    push_to_system=False,
                                    system_writable=False,
                                    adb_root_allowed=False,
                                    overlay_allowed=False))
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

    def test_a_finished_row_writes_one_line_in_the_log(self):
        """The screen's history, and where the row DETAIL now lives.

        The run table lost its detail column — it was the widest thing on the
        screen and empty in every row that had not run yet. The detail is not
        dropped: each finished row writes a line here, and that is what the
        log under the status card shows.
        """
        self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze"]},
            "10.1.1.42": {"packages": ["com.example.gebze"]},
        }))
        state = self.run_and_wait(
            "start", ["10.1.1.40", "10.1.1.99", "10.1.1.42"],
            {"package": "com.example.gebze"})
        log = state["log"]
        self.assertEqual(len(log), 3)
        self.assertEqual({entry["operation"] for entry in log}, {"start"})
        by_ip = {entry["ip"]: entry for entry in log}
        self.assertEqual(by_ip["10.1.1.40"]["state"], "done")
        self.assertEqual(by_ip["10.1.1.99"]["state"], "failed")
        # The two things a line is for: when, and what actually happened.
        self.assertTrue(all(entry["at"] for entry in log))
        self.assertTrue(by_ip["10.1.1.99"]["detail"])

    def test_the_log_survives_the_next_run(self):
        """A run replaces the table and ADDS to the log. The question asked
        on a bench is never about the current run — it is "did 42 ever come
        back?", two runs ago."""
        self.with_adb(FakeAdb({
            "10.1.1.40": {"packages": ["com.example.gebze"]},
            "10.1.1.42": {"packages": ["com.example.gebze"]},
        }))
        self.run_and_wait("stop", ["10.1.1.40"],
                          {"package": "com.example.gebze"})
        state = self.run_and_wait("start", ["10.1.1.42"],
                                  {"package": "com.example.gebze"})
        self.assertEqual([row["ip"] for row in state["rows"]], ["10.1.1.42"])
        self.assertEqual([(entry["operation"], entry["ip"])
                          for entry in state["log"]],
                         [("stop", "10.1.1.40"), ("start", "10.1.1.42")])

    def test_the_log_does_not_grow_without_end(self):
        """It is polled once a second while a run is on; a log that kept an
        afternoon of lines would be sent sixty times a minute."""
        self.assertEqual(RUNNER.state()["log"], [])
        self.assertEqual(runner_module.LOG_LIMIT,
                         RUNNER._log.maxlen)

    def test_a_pending_row_writes_nothing(self):
        """Only a row that has FINISHED is a line. A run in flight would
        otherwise write one line per device per state change."""
        self.with_adb(FakeAdb(self.one_device()))
        with self.held_open():
            self.assertEqual(RUNNER.state()["log"], [])

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


# ──────────────────────────────────── attaching the bench, and restarting ──
class LaunchingWithoutALauncherActivity(AdbTest):
    """`am start -n` needs a component. Not every bundle can supply one.

    The displays on the bench run locked-down images, and some of the bundles
    on them declare no MAIN/LAUNCHER activity that `resolve-activity` will
    return — a disabled launcher, or an alias it does not report. Those
    applications start perfectly well; they just cannot be started that way,
    and "restart" reported that the bundle declared nothing to launch.
    """

    def test_a_package_with_no_launcher_activity_still_starts(self):
        adb = FakeAdb(self.one_device(), no_launcher={"com.example.gebze"})
        self.with_adb(adb)
        result = apps.start("10.1.1.40", "com.example.gebze")
        self.assertEqual(result["action"], "start")
        # Started through monkey, so no component was ever named.
        self.assertEqual(result["activity"], "")
        self.assertIn("monkey:com.example.gebze", adb.timeline)

    def test_restart_reaches_the_same_fallback(self):
        adb = FakeAdb(self.one_device(), no_launcher={"com.example.gebze"})
        self.with_adb(adb)
        result = apps.restart("10.1.1.40", "com.example.gebze")
        self.assertEqual(result["action"], "restart")
        self.assertIn("monkey:com.example.gebze", adb.timeline)

    def test_a_component_that_will_not_start_falls_back_too(self):
        """`am start` exits 0 while printing an Error line.

        A component that resolves and then will not launch is a stale or
        aliased name, which is exactly what monkey does not use.
        """
        adb = FakeAdb(self.one_device(), start_fails=True)
        self.with_adb(adb)
        result = apps.start("10.1.1.40", "com.example.gebze")
        self.assertIn("monkey:com.example.gebze", adb.timeline)
        self.assertEqual(result["action"], "start")

    def test_a_bundle_nothing_can_start_is_still_an_error(self):
        """The fallback must not turn a real failure into a success."""
        adb = FakeAdb(self.one_device(), no_launcher={"com.example.gebze"},
                      monkey_fails={"com.example.gebze"})
        self.with_adb(adb)
        with self.assertRaises(VerificationError):
            apps.start("10.1.1.40", "com.example.gebze")


class AttachingTheWholeBench(AdbTest):
    """`connect` puts every address in `adb devices` and says what did not.

    Every other operation borrows a transport and hands it back. This one is
    the deliberate exception — the operator wants the bench reachable from
    this machine, by scrcpy or `adb logcat` as much as by this panel.
    """

    def test_connecting_leaves_the_transport_attached(self):
        adb = FakeAdb(self.one_device())
        self.with_adb(adb)
        result = apps.connect("10.1.1.40")
        self.assertEqual(result["action"], "connect")
        self.assertEqual(result["serial"], f"10.1.1.40:{settings.ADB_PORT}")
        self.assertIn("10.1.1.40", adb.connected)

    def test_a_device_that_will_not_answer_is_an_error_not_a_silence(self):
        adb = FakeAdb({})            # nothing is live
        self.with_adb(adb)
        with self.assertRaises(DeviceError):
            apps.connect("10.1.1.40")

    def test_connected_but_not_listed_is_reported(self):
        """THE CASE THE WARNING EXISTS FOR.

        A display can complete this panel's own handshake and still not appear
        in `adb devices` — which is the list the operator is about to look at
        in a terminal. Passing the first check and failing the second is not
        success.
        """
        adb = FakeAdb(self.one_device(), unlisted={"10.1.1.40"})
        self.with_adb(adb)
        with self.assertRaises(VerificationError) as caught:
            apps.connect("10.1.1.40")
        self.assertIn("10.1.1.40", str(caught.exception))

    def test_the_runner_does_not_disconnect_after_connecting(self):
        """Otherwise the operation would undo itself on the way out."""
        adb = FakeAdb({"10.1.1.40": {"packages": {}},
                       "10.1.1.41": {"packages": {}}})
        self.with_adb(adb)
        state = RUNNER.start("connect", [{"ip": "10.1.1.40"},
                                         {"ip": "10.1.1.41"}], {})
        self.assertTrue(state["running"])
        while RUNNER.busy():
            time.sleep(0.01)
        self.assertEqual(adb.connected, {"10.1.1.40", "10.1.1.41"})

    def test_one_unreachable_address_does_not_stop_the_others(self):
        adb = FakeAdb({"10.1.1.40": {"packages": {}},
                       "10.1.1.42": {"packages": {}}})
        self.with_adb(adb)
        RUNNER.start("connect", [{"ip": "10.1.1.40"}, {"ip": "10.1.1.41"},
                                 {"ip": "10.1.1.42"}], {})
        while RUNNER.busy():
            time.sleep(0.01)
        rows = RUNNER.state()["rows"]
        by_ip = {row["ip"]: row for row in rows}
        self.assertEqual(by_ip["10.1.1.40"]["state"], "done")
        self.assertEqual(by_ip["10.1.1.42"]["state"], "done")
        # The one that is not there is a failed row — the warning.
        self.assertEqual(by_ip["10.1.1.41"]["state"], "failed")
        self.assertTrue(by_ip["10.1.1.41"]["detail"])

    def test_connect_is_one_row_per_address_not_per_bundle(self):
        """It addresses the DEVICE, so two bundles must not mean two rows."""
        self.assertIn("connect", apps.DEVICE_OPERATIONS)
        self.assertIn("connect", apps.OPERATIONS)


# ─────────────────────────────────────── the one transport, pinned ────
class OneTransport(AdbTest):
    """`panel.adb.client` claims to be the only place adb is executed.

    The claim was false once already: the probe and the APK install each
    grew a private `subprocess` wrapper with its own connect proof, and the
    same display at the same moment was red on the scan and green on the
    ADB screen. The wrappers are gone; this scan is what keeps a fourth
    copy from growing back quietly.
    """

    # The two files that carried private copies of the transport.
    FORMER_COPIES = (("panel", "probe", "android.py"),
                     ("panel", "firmware", "apk_install.py"))

    def test_the_former_private_wrappers_stay_deleted(self):
        """No `subprocess` outside comments — import, call or alias."""
        pattern = re.compile(r"\bsubprocess\s*\.|"
                             r"^\s*import\s+subprocess|"
                             r"^\s*from\s+subprocess\b")
        offenders = []
        for parts in self.FORMER_COPIES:
            path = settings.ROOT.joinpath(*parts)
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):
                # Outside comments. The docstrings naming the old wrappers
                # mention the word without the dot or the import form, so
                # they do not match; running code cannot avoid both.
                if pattern.search(line.split("#")[0]):
                    offenders.append(f"{'/'.join(parts)}:{number}")
        self.assertEqual(offenders, [],
                         "these run their own subprocess instead of "
                         f"panel.adb.client: {offenders}")

    def test_both_former_copies_import_the_shared_client(self):
        """The positive half: the transport they use is the client."""
        for parts in self.FORMER_COPIES:
            text = settings.ROOT.joinpath(*parts).read_text(encoding="utf-8")
            self.assertIn("from ..adb import client", text,
                          f"{'/'.join(parts)} does not use panel.adb.client")


# ───────────────────────────────────── the connection lease ───────────
class Lease(AdbTest):
    """Two subsystems, one serial: neither may tear the other down.

    The tear this removes was reported from the bench: the light refresh
    read a Compartment LCD, politely disconnected afterwards — and pulled
    the transport out from under the APK install that was half way through
    on the same display. A lease is a per-serial reference count that
    `client.disconnect` respects; with none held, nothing changes at all,
    which is what keeps the runner's and the commissioning run's explicit
    disconnects exactly as they were.
    """

    def test_disconnect_is_skipped_while_a_lease_is_active(self):
        adb = self.with_adb(FakeAdb(self.one_device()))
        self.assertTrue(adb_client.connect("10.1.1.40", attempts=1))
        with adb_client.lease("10.1.1.40"):
            adb_client.disconnect("10.1.1.40")
            self.assertIn("10.1.1.40", adb.connected,
                          "the leased transport was dropped")
        # The lease is gone, so the ordinary rule is back.
        adb_client.disconnect("10.1.1.40")
        self.assertNotIn("10.1.1.40", adb.connected)

    def test_leases_are_counted_not_boolean(self):
        """Two holders, two releases: the transport survives the first."""
        adb = self.with_adb(FakeAdb(self.one_device()))
        self.assertTrue(adb_client.connect("10.1.1.40", attempts=1))
        with adb_client.lease("10.1.1.40"):
            with adb_client.lease("10.1.1.40"):
                pass                      # the first holder finished
            adb_client.disconnect("10.1.1.40")
            self.assertIn("10.1.1.40", adb.connected,
                          "one release must not void the other holder")
        adb_client.disconnect("10.1.1.40")
        self.assertNotIn("10.1.1.40", adb.connected)

    def test_a_scan_read_does_not_drop_a_leased_install_transport(self):
        """The documented tear, end to end.

        An install holds its lease on the display; the probe reads the same
        display through the same client, finishes, tidies up after itself —
        and the install's transport is still there.
        """
        from panel.probe import android

        adb = self.with_adb(FakeAdb(
            {"10.1.1.40": {"packages": [settings.ADB_PACKAGE]}}))
        adb.props["ro.serialno"] = "rk3568r0001"
        with adb_client.lease("10.1.1.40"):        # the install's span
            self.assertTrue(adb_client.connect("10.1.1.40", attempts=1))
            data = android.read("10.1.1.40")
            self.assertEqual(data["serial"], "rk3568r0001")
            self.assertIn("10.1.1.40", adb.connected,
                          "the read disconnected a transport in use")
        adb_client.disconnect("10.1.1.40")
        self.assertNotIn("10.1.1.40", adb.connected)

    def test_a_lone_read_still_hands_the_transport_back(self):
        """The lease must not turn every read into `connect`'s exception:
        with nobody else holding the serial, a read that leaves it attached
        is a serial the next operation reaches by accident."""
        from panel.probe import android

        adb = self.with_adb(FakeAdb(
            {"10.1.1.40": {"packages": [settings.ADB_PACKAGE]}}))
        adb.props["ro.serialno"] = "rk3568r0001"
        android.read("10.1.1.40")
        self.assertNotIn("10.1.1.40", adb.connected)
        # And the connect proof really was the client's: the serial was
        # asked for its state, not inferred from a property read.
        self.assertTrue(any("get-state" in call for call in adb.calls))


# ─────────────────────────── the probe's adb branch ───────────────────
class ProbeTimeout(PanelTest):
    """The caller's read budget must reach the adb commands."""

    def test_the_callers_timeout_reaches_android_read(self):
        """`read_device`'s `timeout` was dropped on the adb branch alone —
        every other protocol passed it through — so the light refresh's
        3-second budget never bounded an unresponsive display: the refresh
        sat out the full default while the working devices' data went
        stale behind it. `android.read` applies the budget per adb
        invocation (its documented shape), so it is forwarded as-is."""
        from types import SimpleNamespace

        from panel import status
        from panel.probe import reader

        seen = {}

        def fake_read(ip, timeout=None):
            seen["ip"], seen["timeout"] = ip, timeout
            return {"serial": "SER123", "timezone": "Europe/Istanbul",
                    "uptime": "120", "version": "1.0.5", "versionCode": "7",
                    "targetSdk": "35", "updatedAt": "2026-07-07",
                    "package": settings.ADB_PACKAGE, "sipExtension": "6001",
                    "sipPbx": "10.1.1.1", "sipRegistration": "registered",
                    "sipCode": "200"}

        device = SimpleNamespace(read_method="adb", ip="10.1.1.40")
        with mock.patch.object(reader.android, "read", fake_read):
            result = reader.read_device(device, timeout=3.0)

        self.assertEqual(seen["ip"], "10.1.1.40")
        self.assertEqual(seen["timeout"], 3.0)
        self.assertEqual(result.state, status.OK)

        # Without a budget the default must survive: `android.read` falls
        # back to settings.ADB_TIMEOUT only when it is handed None.
        with mock.patch.object(reader.android, "read", fake_read):
            reader.read_device(device)
        self.assertIsNone(seen["timeout"])
