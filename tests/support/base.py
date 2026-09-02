#!/usr/bin/env python3
"""Shared setup for the tests.

THE ENVIRONMENT IS NOT PINNED HERE. The temp data directories, the
network-write ban, the edition and the build secret are all set in
tests/__init__.py, and the split is deliberate: this module is imported by
choice, while the package module provably runs before any test module does.
A test module that imported ``panel`` before importing this one bypassed
everything set here for the flags the panel reads at import time
(PANEL_NETWORK_WRITES), which is how the suite once wrote real IP aliases
onto a developer's network interface. What stays here is everything that
needs ``panel`` importable and imported: the language pin, the edition
activation, and the test base classes.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

# Defined by the package module along with the environment (see above);
# re-exported because half the suite reads checkout files relative to it.
from .. import ROOT

from panel import i18n

# Assertions in this suite are written against the English wording, so the
# language is pinned rather than read from the machine: on a Turkish desktop
# the same tests would otherwise compare English text against Turkish output.
i18n.use("en", persist=False)

from panel import (config_sync, credentials, editions,  # noqa: E402
                   firmware, jobs, settings)
from panel import adminkey, authority, remotekey  # noqa: E402

# Activated once, before any test touches a DeviceMap: `activate()` is what
# points `settings.DEVICE_MAP` at a project and gives the settings directory
# its per-edition sub-folder.
editions.activate(os.environ["DAP_EDITION"])
from panel.editions import catalogue  # noqa: E402
from panel.inventory import device_map  # noqa: E402

# The Yatakli map, where this checkout keeps it. Several tests read the
# DELIVERED map rather than a topology they built themselves — the real
# device kinds are the point — and they ask the edition table where it is
# instead of each spelling out a path, so a project folder that moves moves
# in one place.
YATAKLI_MAP = ROOT.joinpath(*catalogue.YATAKLI.source_path)
from panel import switch  # noqa: E402

from . import clock as fake_clock  # noqa: E402
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
        # Device waits pass instantly (see panel/clock.py). Every wait in
        # this suite is a fake device that is never actually rebooting, so
        # the seconds were pure cost. A test whose subject IS the timing
        # calls `self.clock.uninstall()` to get the real one back.
        self.clock = fake_clock.install(self)
        # No test pings a real network. The probe follows a failed read with
        # one echo (panel/probe/ping.py), and on a developer's network a
        # test-fixture address may genuinely answer — every "unreachable"
        # assertion in the suite would then flap with the office topology.
        # Tests about the softening itself patch this back on.
        self._ping = mock.patch("panel.probe.ping.reachable",
                                return_value=False)
        self._ping.start()
        self.addCleanup(self._ping.stop)
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
        jobs.view.clear_all()
        adminkey.WATCH.reset()
        # And the other way in, and the arbiter that weighs the two: a
        # remote session left live by one test would hold admin mode open
        # through the next one's `settle()` and quietly hide a drop that
        # should have happened.
        remotekey.WATCH.reset()
        authority.reset()
        # The mode a test starts in is the one this RUN implies, not the one
        # the previous test happened to leave behind. `editions.activate`
        # re-reads the build secret to decide it, and a test that hides the
        # secret (`as_shipped`) and re-activates in its own tearDown — which
        # runs BEFORE the environment patch is undone — left the whole process
        # in field mode from there on. That was invisible while every field
        # screen was reachable in field mode; the ADB and switch screens are
        # not (panel/editions/catalogue.py), so it stopped being invisible.
        if editions.is_active():
            editions.set_admin(editions.opens_as_admin())

    def tearDown(self):
        settings.DEVICE_MAP = self._old_device_map
        settings.KYLAND_PORT = self._old_kyland
        settings.VIDEO_PORT = self._old_video
        settings.ANNOUNCEMENT_PORT = self._old_announcement
        switch.CLIENT.port = self._old_kyland
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
            # A tenth of a second per look is a long time to hold every
            # tearDown in the suite; the queue finishes far quicker than that.
            time.sleep(0.01)
        for job in jobs.QUEUE.list():
            jobs.QUEUE.remove(job.id)

    # ---- helpers ----
    def switch_port(self, port: int) -> None:
        """Point the panel at the fake switch's port.

        Both halves are needed: the setting is what a client built from here
        on reads, and `CLIENT` is the one already built — it took its port at
        construction, before any test could move the setting.
        """
        settings.KYLAND_PORT = port
        switch.CLIENT.port = port

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
        # Poll fast so `shutdown` returns promptly — same reason as the fake
        # devices in support/fakes.py: the default half-second beat made
        # every service test pay half a second to put the server away.
        t = threading.Thread(target=srv.serve_forever,
                             kwargs={"poll_interval": 0.01}, daemon=True)
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
