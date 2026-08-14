#!/usr/bin/env python3
"""Shared setup for the tests."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The panel's persistent data (configuration defaults) is written to a temp
# directory in tests: they neither read nor damage the user's real settings.
import os  # noqa: E402
os.environ["PANEL_DATA_DIR"] = tempfile.mkdtemp(prefix="panel-data-")

from panel import i18n  # noqa: E402

# Assertions in this suite are written against the English wording, so the
# language is pinned rather than read from the machine: on a Turkish desktop
# the same tests would otherwise compare English text against Turkish output.
i18n.use("en", persist=False)

from panel import (config_sync, credentials, firmware,  # noqa: E402
                   jobs, settings)
from panel.inventory import device_map  # noqa: E402
from panel.probe import switch as switch_probe  # noqa: E402

from . import fakes  # noqa: E402,F401  (re-exported for the tests)


class PanelTest(unittest.TestCase):
    """Every test starts with a clean DeviceMap, memory and view."""

    def build_map(self, topology: dict) -> device_map.Inventory:
        path = Path(tempfile.mkdtemp(prefix="panel-test-")) / "DeviceMap.json"
        path.write_text(json.dumps(topology, ensure_ascii=False),
                        encoding="utf-8")
        self.map_path = path
        settings.DEVICE_MAP = path
        device_map.clear_cache()
        return device_map.load(1, path)

    def setUp(self):
        # Belt and braces: a test elsewhere may have switched language.
        i18n.use("en", persist=False)
        self._old_device_map = settings.DEVICE_MAP
        self._old_kyland = settings.KYLAND_PORT
        self._old_video = settings.VIDEO_PORT
        self._old_announcement = settings.ANNOUNCEMENT_PORT
        # A previous test may have shut the queue down; if it stays closed
        # this test's jobs never start.
        jobs.QUEUE.open()
        self.drain_queue()
        credentials.forget_all()
        # The saved defaults file is removed too: one test's value must not
        # leak into the next.
        config_sync.clear_saved_defaults()
        firmware.clear_all()
        for view in list(jobs.view._VIEWS.values()):
            view.clear()
        jobs.view._VIEWS.clear()

    def tearDown(self):
        settings.DEVICE_MAP = self._old_device_map
        settings.KYLAND_PORT = self._old_kyland
        settings.VIDEO_PORT = self._old_video
        settings.ANNOUNCEMENT_PORT = self._old_announcement
        try:
            switch_probe.api().SWITCH_PORT = self._old_kyland
        except Exception:
            pass
        device_map.clear_cache()
        credentials.forget_all()
        self.drain_queue()

    @staticmethod
    def drain_queue(timeout: float = 30.0) -> None:
        """Really empties the queue.

        Cancelling and removing is not enough: a running job cannot be
        removed, so it stayed in the queue and the next test's job with the
        same key was rejected as "already there". Here we WAIT for jobs to
        finish.
        """
        for job in jobs.QUEUE.list():
            jobs.QUEUE.cancel(job.id)
        deadline = time.time() + timeout
        while time.time() < deadline:
            pending = [job for job in jobs.QUEUE.list()
                       if job.state in (jobs.QUEUED, jobs.RUNNING)]
            if not pending:
                break
            time.sleep(0.1)
        for job in jobs.QUEUE.list():
            jobs.QUEUE.remove(job.id)

    # ---- helpers ----
    def switch_port(self, port: int) -> None:
        """Apply the fake switch's port to the panel and the sibling backend."""
        settings.KYLAND_PORT = port
        switch_probe.api().SWITCH_PORT = port

    def await_job(self, job: jobs.Job, timeout: float = 30.0) -> jobs.Job:
        done = threading.Event()

        def watch():
            for _ in range(int(timeout / 0.05)):
                if job.state in (jobs.DONE, jobs.CANCELLED, jobs.FAILED):
                    break
                done.wait(0.05)
            done.set()

        t = threading.Thread(target=watch, daemon=True)
        t.start()
        t.join(timeout + 1)
        return job


class ServiceTest(PanelTest):
    """Tests that bring up the real HTTP service."""

    def start_service(self):
        from panel.api import http_adapter

        srv = http_adapter.serve("127.0.0.1", 0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{port}"

    @staticmethod
    def call(base: str, path: str, body=None, method=None):
        """A minimal HTTP client — returns (status code, body)."""
        import urllib.error
        import urllib.request

        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            base + path, data=data,
            method=method or ("POST" if data is not None else "GET"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"{}")
            except ValueError:
                return e.code, {"raw": raw.decode("utf-8", "replace")}
