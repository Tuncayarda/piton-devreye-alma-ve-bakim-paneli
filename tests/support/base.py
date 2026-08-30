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
# And the digests a service key written from source is remembered by: those
# live in the CHECKOUT (panel.adminkey.secret), so without this a test that
# writes a key would leave a file in the working tree and teach the developer's
# own panel to accept a key made up by the suite.
os.environ["DAP_ADMIN_KEY_STORE"] = tempfile.mkdtemp(
    prefix="panel-adminkey-")

# THE SUITE MUST NOT RECONFIGURE THIS COMPUTER. Scans and IP runs are
# exercised end to end against fake devices, and those jobs prepare the
# network before they start (see panel.api.tasks.network_prepare) — which ran
# `ifconfig alias` for real and left four addresses on a developer's live
# interface. Set before `panel` is imported, because the flag is read once at
# import. tests/test_network.py turns it back on around a faked subprocess.
os.environ["PANEL_NETWORK_WRITES"] = "0"

# Which package is under test. Every edition is a customer's now, so the
# suite runs as one of them; `setdefault`, so a run can be pointed at another
# on purpose (see tests/test_editions.py).
os.environ.setdefault("DAP_EDITION", "vip-yatakli")

# ...AND IT RUNS IN ADMIN MODE, which is what the secret below is for. The
# suite exercises every screen, and the admin screens exist only in admin
# mode; without the secret it would test the field half of the product and
# never the other. The secret is the bootstrap standing in for the first USB
# key, which cannot exist before it is written (see
# panel.editions.opens_as_admin). tests/test_adminkey.py takes it away again
# where the absence is the thing under test.
os.environ.setdefault("DAP_ADMIN_KEY_SECRET",
                      "a-build-secret-for-the-tests")

from panel import i18n  # noqa: E402

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
