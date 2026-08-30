#!/usr/bin/env python3
"""Socket-free desktop start-up and pywebview bridge regressions."""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from .support.base import ROOT  # noqa: F401  (sys.path + temp data dir)

import app
from panel import i18n, settings
from panel.desktop import (BRIDGE_MARKER, CAPABILITY_SLOT, PanelBridge,
                           editmenu, load_html)


class DesktopHtml(unittest.TestCase):
    def test_single_file_html_is_read_with_the_bridge_marker(self):
        text = load_html("A" * 43)
        self.assertIn(BRIDGE_MARKER, text)
        self.assertNotIn(CAPABILITY_SLOT, text)
        self.assertIn("A" * 43, text)

    def test_an_artefact_requesting_an_external_script_is_rejected(self):
        source = (settings.STATIC_DIR / "desktop.html").read_text(
            encoding="utf-8")
        broken = source.replace(
            "</body>", '<script src="https://example.com/a.js"></script></body>')
        # Written to a real file and handed to load_html rather than
        # patching Path.read_text: that patch caught EVERY read in the
        # process for as long as it was open — including the first, lazy
        # read of the message catalogue, which then came back empty and
        # failed this test with an unrelated error.
        with tempfile.TemporaryDirectory() as directory:
            artefact = Path(directory) / "desktop.html"
            artefact.write_text(broken, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "invalid"):
                load_html("A" * 43, path=artefact)


class Bridge(unittest.TestCase):
    def test_get_query_and_post_body_are_split_for_the_service(self):
        calls = []

        def call(method, path, query=None, body=None):
            calls.append((method, path, query, body))
            return {"ok": True, "status": 200, "body": {"done": True}}

        bridge = PanelBridge(call, capability="A" * 43)
        self.assertTrue(
            bridge.invoke("A" * 43, "GET", "/api/project?set=2", {})["ok"])
        self.assertTrue(bridge.invoke(
            "A" * 43, "POST", "/api/scan", {"set": 2})["ok"])
        self.assertEqual(calls, [
            ("GET", "/api/project", {"set": ["2"]}, {}),
            ("POST", "/api/scan", {}, {"set": 2}),
        ])

    def test_arbitrary_url_method_and_oversized_body_are_rejected(self):
        call = mock.Mock()
        bridge = PanelBridge(call, capability="A" * 43)
        for method, path, body, code in (
                ("GET", "https://example.com/api/version", {}, 400),
                ("DELETE", "/api/jobs", {}, 405),
                ("POST", "/api/scan",
                 {"x": "a" * (settings.BODY_LIMIT + 1)}, 400)):
            envelope = bridge.invoke("A" * 43, method, path, body)
            self.assertFalse(envelope["ok"])
            self.assertEqual(envelope["status"], code)
        call.assert_not_called()

    def test_invoke_is_the_only_public_callable(self):
        bridge = PanelBridge(lambda *a, **k: {}, capability="A" * 43)
        public = sorted(name for name in dir(bridge)
                        if not name.startswith("_")
                        and callable(getattr(bridge, name)))
        self.assertEqual(public, ["invoke"])

    def test_shutdown_rejects_a_new_call(self):
        bridge = PanelBridge(lambda *a, **k: {
            "ok": True, "status": 200, "body": {}}, capability="A" * 43)
        self.assertTrue(bridge._close())
        self.assertEqual(
            bridge.invoke("A" * 43, "GET", "/api/version", {})["status"], 503)

    def test_shutdown_waits_for_an_in_flight_call(self):
        started = threading.Event()
        finish = threading.Event()

        def call(*args, **kwargs):
            started.set()
            finish.wait(2)
            return {"ok": True, "status": 200, "body": {}}

        bridge = PanelBridge(call, capability="A" * 43)
        request = threading.Thread(
            target=bridge.invoke,
            args=("A" * 43, "GET", "/api/version", {}),
        )
        request.start()
        self.assertTrue(started.wait(1))

        closed = threading.Event()

        def close():
            bridge._close()
            closed.set()

        shutdown = threading.Thread(target=close)
        shutdown.start()
        time.sleep(0.02)
        self.assertFalse(closed.is_set())
        finish.set()
        shutdown.join(1)
        request.join(1)
        self.assertTrue(closed.is_set())

    def test_a_wrong_capability_key_never_reaches_the_service(self):
        call = mock.Mock()
        bridge = PanelBridge(call, capability="A" * 43)
        envelope = bridge.invoke("B" * 43, "GET", "/api/version", {})
        self.assertEqual(envelope["status"], 403)
        call.assert_not_called()

    def test_missing_and_extra_arguments_return_an_envelope(self):
        call = mock.Mock()
        bridge = PanelBridge(call, capability="A" * 43)
        self.assertEqual(bridge.invoke()["status"], 403)
        self.assertEqual(bridge.invoke("A" * 43)["status"], 400)
        self.assertEqual(
            bridge.invoke("A" * 43, "GET", "/api/version", {}, "extra")[
                "status"],
            400,
        )
        call.assert_not_called()


class DesktopStartup(unittest.TestCase):
    def test_port_zero_is_rejected_without_browser_mode(self):
        with (mock.patch.object(sys, "argv", ["app.py", "--port", "0"]),
              mock.patch("app.write") as write):
            self.assertEqual(app.main(), 2)
        write.assert_called_with(
            "[ERROR] --port can only be used together with --browser.")

    def test_without_elevation_the_application_never_opens(self):
        """The panel writes to the network and to devices; there is no
        unprivileged mode.

        Refusing the system's password box sets up no service at all — the
        window that follows only says why.
        """
        with (mock.patch.object(sys, "argv",
                                ["app.py", "--edition", "gdm"]),
              mock.patch("app.is_elevated", return_value=False),
              mock.patch("app.set_macos_identity") as identity,
              mock.patch("panel.elevation.flow.elevate",
                         return_value=(False, "denied")),
              mock.patch("panel.elevation.flow.show_failure") as shown,
              mock.patch("panel.api.start") as start,
              mock.patch("app.write") as write):
            self.assertEqual(app.main(), 1)
        shown.assert_called_once()
        # The elevation window is the application's window too: it must not
        # look like a SECOND app under the interpreter's name in the Dock.
        identity.assert_called_once()
        start.assert_not_called()
        self.assertIn("must run elevated", " ".join(
            str(c.args[0]) for c in write.call_args_list))

    def test_an_unprivileged_start_goes_straight_to_the_system_box(self):
        """No dialog of ours comes first; the system prompt is the question.

        The starting process EXITS with 0: two copies of the same panel must
        not write to the same switch and the same DeviceMap.
        """
        with (mock.patch.object(sys, "argv", ["app.py"]),
              mock.patch("app.is_elevated", return_value=False),
              mock.patch("panel.elevation.flow.hide_dock_icon"),
              mock.patch("panel.elevation.flow.show_failure") as shown,
              mock.patch("panel.elevation.flow.elevate",
                         return_value=(True, "")) as elevate,
              mock.patch("panel.api.start") as start,
              mock.patch("app.write")):
            self.assertEqual(app.main(), 0)
        elevate.assert_called_once()
        shown.assert_not_called()
        start.assert_not_called()

    def test_the_window_title_follows_the_language(self):
        """The title bar belongs to the operating system, not the WebView.

        A language switch hands the UI a whole new catalogue and the screen
        is redrawn from it — but that redraw stops at the edge of the web
        view. The title has to be told separately, or it keeps announcing the
        app in a language the user just left.
        """
        titles = []
        fake = types.ModuleType("webview")
        fake.settings = {}
        fake.opened_with = None

        def create_window(title, **_kwargs):
            fake.opened_with = title
            return types.SimpleNamespace(expose=lambda *_f: None,
                                         set_title=titles.append)

        fake.create_window = create_window
        fake.start = lambda **_kwargs: None

        html = f"<!doctype html><head>{BRIDGE_MARKER}</head>"
        try:
            i18n.use("en", persist=False)
            with (mock.patch.dict(sys.modules, {"webview": fake}),
                  mock.patch.object(sys, "argv", ["app.py"]),
                  mock.patch("app.is_elevated", return_value=True),
                  mock.patch("app.platform.system", return_value="Linux"),
                  mock.patch("app.set_macos_identity"),
                  mock.patch("panel.desktop.load_html", return_value=html),
                  mock.patch("panel.api.start"),
                  mock.patch("panel.api.reset"),
                  mock.patch("app.write")):
                self.assertEqual(app.main(), 0)

            self.assertEqual(fake.opened_with,
                             i18n.t("app.name", _language="en"))
            i18n.use("tr", persist=False)
            self.assertEqual(titles[-1], i18n.t("app.name", _language="tr"))
            self.assertNotEqual(titles[-1], fake.opened_with,
                                "the two languages must not read the same")
        finally:
            # The follower registered above holds this fake window; it must
            # not still be firing in the next test.
            i18n.reset()
            i18n.use("en", persist=False)

    def test_default_mode_opens_no_http_server(self):
        fake = types.ModuleType("webview")
        fake.settings = {}
        fake.window = None
        fake.startup = None
        fake.exposed_functions = []

        def create_window(*args, **kwargs):
            fake.window = (args, kwargs)
            fake.window_object = types.SimpleNamespace(
                expose=lambda *f: fake.exposed_functions.extend(f))
            return fake.window_object

        def start(**kwargs):
            fake.startup = kwargs

        fake.create_window = create_window
        fake.start = start

        html = f"<!doctype html><head>{BRIDGE_MARKER}</head>"
        with (mock.patch.dict(sys.modules, {"webview": fake}),
              mock.patch.object(sys, "argv", ["app.py"]),
              mock.patch("app.is_elevated", return_value=True),
              mock.patch("app.platform.system", return_value="Windows"),
              mock.patch("app.set_macos_identity"),
              mock.patch("panel.desktop.load_html", return_value=html),
              mock.patch("panel.api.start"),
              mock.patch("panel.api.reset"),
              mock.patch("panel.api.http_adapter.serve") as server):
            self.assertEqual(app.main(), 0)

        server.assert_not_called()
        self.assertIsNotNone(fake.window)
        _, options = fake.window
        self.assertNotIn("url", options)
        self.assertNotIn("js_api", options)
        self.assertEqual(options["html"], html)
        self.assertEqual(
            [f.__name__ for f in fake.exposed_functions], ["invoke"])
        self.assertIsInstance(fake.exposed_functions[0].__self__, PanelBridge)
        # `func` installs the Edit menu: macOS has no Cmd-C or Cmd-V without
        # a menu bar to hang them on, and pywebview builds no Edit menu of
        # its own (see panel.desktop.editmenu). Checked by CALLING it rather
        # than by identity, because it now has to carry the window through —
        # Paste writes into the page, and a closure that forgot the window
        # would still be a callable of the right name.
        self.assertEqual(set(fake.startup),
                         {"func", "gui", "http_server"})
        self.assertEqual(fake.startup["gui"], "edgechromium")
        self.assertFalse(fake.startup["http_server"])
        with mock.patch.object(editmenu, "install") as install:
            fake.startup["func"]()
        install.assert_called_once()
        self.assertIs(install.call_args[0][0], fake.window_object)
        self.assertFalse(fake.settings["ALLOW_FILE_URLS"])
        self.assertFalse(fake.settings["ALLOW_DOWNLOADS"])


if __name__ == "__main__":
    unittest.main()
