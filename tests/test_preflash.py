#!/usr/bin/env python3
"""Flashing an intercom before its address is written.

The field problem: intercoms shipped to the trains long ago run firmware old
enough that they report their version and identity WRONGLY, so nothing can be
decided from what they say about themselves. They have to be flashed first,
and the only moment that is possible is inside the assignment run — the run
has just powered one PoE port, so exactly one device is reachable and it is
still on the factory address.

Two rules carry the whole feature and both are pinned here:

  · The option flashes every selected port. Nothing is decided from what the
    device says about its version — that is the very thing these devices get
    wrong — so there is no "expected version" to compare against and no way
    for a port to be skipped as "already up to date".
  · A device that could not be flashed must NOT get its address. Writing it
    anyway would move the device on and hide the reason it was selected.

NOTHING HERE TOUCHES A DEVICE. The upload and the version read are faked; a
test that really posted an image would need a device on the other end.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from .support import fakes
from .support.base import ROOT, PanelTest  # noqa: F401  (sys.path + temp data)

from panel import ip_assign, script_loader
from panel.ip_assign import preflash


# ─────────────────────────────────────────────────── the run's callback ────
class Callback(PanelTest):
    """`BEFORE_WRITE` — what it decides and what it never does."""

    def setUp(self):
        super().setUp()
        preflash.forget_file()
        self.addCleanup(preflash.forget_file)
        self.lines: list[str] = []
        self.uploads: list[tuple] = []

    def _hook(self, **options):
        return preflash.callback(
            {"preflash": True, "preflashPath": "image.bin", **options},
            self.lines.append)

    def _run(self, hook, reported, after=None):
        """Drive the hook with a device that reports `reported`."""
        answers = iter([reported] if after is None else [reported, after])

        def read_version(_ip, _credentials=None):
            try:
                return next(answers)
            except StopIteration:
                return after or reported

        with mock.patch.object(preflash, "read_version", read_version), \
                mock.patch.object(preflash, "wait_back",
                                  lambda *a, **k: after or ""), \
                mock.patch.object(preflash.firmware, "post_image",
                                  lambda *a, **k: self.uploads.append(a)):
            return hook(11, "10.1.1.12", {}, None)

    def test_the_option_off_installs_no_hook(self):
        self.assertIsNone(preflash.callback({"preflash": False}, print))

    def test_a_device_reporting_a_version_is_flashed_all_the_same(self):
        """No comparison is made: the chosen file always goes on.

        These devices report their version wrongly, so "it already says
        1.4.2" is not evidence of anything.
        """
        ok, _note = self._run(self._hook(), "1.4.2", after="1.4.2")
        self.assertTrue(ok)
        self.assertEqual(len(self.uploads), 1)

    def test_an_older_device_is_flashed(self):
        ok, _note = self._run(self._hook(), "1.3.0", after="1.4.2")
        self.assertTrue(ok)
        self.assertEqual(len(self.uploads), 1)

    def test_a_device_that_will_not_say_is_flashed(self):
        """The reported case: version unreadable, so flash it anyway."""
        ok, _note = self._run(self._hook(), "", after="1.4.2")
        self.assertTrue(ok)
        self.assertEqual(len(self.uploads), 1)

    def test_a_device_that_reports_nothing_afterwards_still_passes(self):
        """Up but silent about its version is not a failure.

        Claiming a version it never gave would be worse than saying so; the
        run's own next step finds out whether the device is really there.
        """
        ok, note = self._run(self._hook(), "", after="")
        self.assertTrue(ok)
        self.assertTrue(note)

    def test_an_upload_that_raises_fails_the_port_and_does_not_escape(self):
        """A callback that raises would take the run down with the ports shut.

        It is called from inside the field script's port loop; an exception
        there escapes `do_port` and the PoE ports are left closed — devices
        dark in the field.
        """
        def explode(*_args, **_kwargs):
            raise OSError("connection reset")

        with mock.patch.object(preflash, "read_version",
                               lambda *a, **k: "1.0.0"), \
                mock.patch.object(preflash.firmware, "post_image", explode):
            ok, note = self._hook()(11, "10.1.1.12", {}, None)
        self.assertFalse(ok)
        # The reason is carried out as text, classified the way every other
        # device error on this screen is (see panel.errors.user_message).
        self.assertTrue(note)
        self.assertNotIn("OSError", note)


# ──────────────────────────────────────────── the hook inside the script ───
class ScriptHook(unittest.TestCase):
    """The extension point in field_scripts/intercom_ip_assign.py."""

    def setUp(self):
        self.module = script_loader.intercom_ip_assign()
        self.addCleanup(setattr, self.module, "BEFORE_WRITE", None)

    def test_the_script_is_unchanged_when_nobody_installs_a_hook(self):
        """Run standalone it must behave exactly as it always did."""
        self.assertIsNone(self.module.BEFORE_WRITE)

    def test_a_failed_flash_stops_the_ip_from_being_written(self):
        """Read off the source, because reaching it needs a live switch.

        The check that matters is that the `not ok` branch returns BEFORE
        write_ip is called — if the order were the other way round, a device
        that could not be flashed would be moved to its address anyway and the
        reason would be buried.
        """
        import inspect

        body = inspect.getsource(self.module.do_port) if hasattr(
            self.module, "do_port") else inspect.getsource(self.module.main)
        hook = body.index("BEFORE_WRITE")
        refusal = body.index("the firmware step did not complete")
        write = body.index("write_ip(")
        self.assertLess(hook, write)
        self.assertLess(refusal, write)


# ────────────────────────────────────────────────────────── the request ────
class RunRequest(PanelTest):
    """What the IP screen sends, and what the server refuses."""

    def setUp(self):
        super().setUp()
        preflash.forget_file()
        self.addCleanup(preflash.forget_file)
        self.build_map(fakes.device_map(
            [{"Name": "Intercom 1", "Type": "Announcement",
              "SubType": "Intercom", "IP": "10.1.1.10", "Port": 11,
              "IsActive": True}]))

    def test_the_option_without_a_file_is_refused(self):
        from panel import api

        response = api.call("POST", "/api/ip/run",
                            body={"set": 1, "ports": "11", "group": "Intercom",
                                  "preflash": True})
        self.assertEqual(response.status, 400)
        self.assertIn("file", response.body["error"].lower())

    def test_the_option_off_needs_no_file(self):
        options = ip_assign.preflash_options({"preflash": False})
        ip_assign.validate_preflash(options)          # must not raise

    def test_the_path_never_reaches_the_client(self):
        """The screen learns the file's name and size. Not where it is.

        The user picks it in the operating system's own dialog; a path the
        client can read is a path the client can send back.
        """
        with mock.patch.object(preflash.firmware, "validate_file",
                               lambda path: (__import__("pathlib").Path(
                                   "/private/images/intercom-1.4.2.bin"), 2048)):
            shown = preflash.choose_file("ignored")
        self.assertEqual(shown, {"name": "intercom-1.4.2.bin", "size": 2048})
        self.assertNotIn("/private/images", str(shown))
        # The run still gets the real path. Compared through `Path` rather
        # than as a literal: what is stored is what the OS dialog handed
        # back, and Windows spells the same path with backslashes.
        self.assertEqual(ip_assign.preflash_options({"preflash": True})
                         ["preflashPath"],
                         str(Path("/private/images/intercom-1.4.2.bin")))

    def test_no_version_is_taken_from_the_request(self):
        """There is no expected-version input any more, on any screen."""
        options = ip_assign.preflash_options(
            {"preflash": True, "preflashVersion": "1.4.2"})
        self.assertNotIn("preflashVersion", options)


if __name__ == "__main__":
    unittest.main()
