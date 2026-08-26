#!/usr/bin/env python3
"""Service start-up and shutdown."""
from __future__ import annotations

import threading

from .. import (adminkey, config_sync, credentials, editions, firmware,
                jobs, network, telemetry)
from ..inventory import device_map

# Starting the application service does not depend on the HTTP server. The
# desktop bridge uses the same path; even with several adapters set up, the
# saved defaults load exactly once.
_START_LOCK = threading.Lock()
_STARTED = False
_LOADED_DEFAULTS = 0


def start() -> int:
    """Make the panel state ready. Safe to call repeatedly."""
    global _STARTED, _LOADED_DEFAULTS
    with _START_LOCK:
        if not _STARTED:
            _LOADED_DEFAULTS = config_sync.load_saved_defaults()
            # A previous run that was killed could not take its addresses off
            # the adapter. They belong to nobody now, so they go — before this
            # session adds any of its own (see panel.network.aliases).
            try:
                network.sweep_stale()
            except Exception:
                pass
            # The factory address is needed before the first scan or IP run,
            # not as a side effect of whichever operation happens to start
            # first.  Set 1 is the application's initial inventory; ``ensure``
            # also honours a saved adapter and otherwise declines to guess
            # between unrelated interfaces.  Startup remains best-effort:
            # a missing DeviceMap, unsupported OS or adapter read failure must
            # not keep the panel window from opening.
            prepare_network()
            # Watching for the service key starts with the panel, not with
            # the screen that asks about it: the question at launch has to be
            # ready before the first paint (see panel.adminkey.watcher).
            try:
                adminkey.WATCH.observe()
                adminkey.WATCH.start()
            except Exception:
                pass
            _STARTED = True
        # `reset()` closes the queue. If the service is rebuilt in the same
        # process, make sure the job queue is open again.
        jobs.QUEUE.open()
        return _LOADED_DEFAULTS


def prepare_network() -> None:
    """Give the computer an address on the devices' network.

    Split out of `start()` so a project switch can run it again: `start()`
    itself is behind `_STARTED` and runs once per process, while another
    project means different subnets and therefore a different address.
    """
    try:
        network.ensure(device_map.load(1))
    except Exception:
        pass


def leave_admin() -> None:
    """Give up admin mode, and give up what it was showing.

    THE PROJECT HAS TO GO BACK TOO. Admin mode may have opened a device list
    delivered on the service key — another customer's, in the general case.
    Dropping the mode alone left that list on screen: the menu said the
    package's own project was open while every device on it belonged to
    somebody else. That is the exact leak the whole arrangement exists to
    prevent, so it is undone here rather than left to whoever calls next.

    The fall back is forced even when this package's OWN DeviceMap has not
    been delivered yet: an empty screen that says so is the right answer, and
    strictly better than another customer's inventory.
    """
    stranded = editions.current_is_extra()
    editions.set_admin(False)
    adminkey.pack.clear_session()
    if stranded:
        switch_project(editions.active().default_project, allow_missing=True)


def switch_project(key: str, *, allow_missing: bool = False):
    """Open another project's device list in the running application.

    EVERYTHING KEYED BY DEVICE ID HAS TO GO. Device ids are positional —
    "sw1.d3" is the third device on the first switch — so the same id names
    a different device in another project. A configuration target, a probe
    result or a chosen firmware image carried across would be shown against,
    and eventually written to, hardware it was never meant for.

    Device credentials are the one exception and stay: they are keyed by
    "id@ip" rather than by id alone, and the group account is usually the
    same customer's. Making the engineer retype every switch password to
    look at the other train is an annoyance with nothing behind it.

    Refused while anything is WRITING to devices — the caller checks that
    (`panel.api.routes.edition_routes`), because only it can answer with a
    409 that says which job is in the way.
    """
    from .presenters import clear_telemetry_cache

    project = editions.use_project(key, allow_missing=allow_missing)
    device_map.clear_cache()
    jobs.view.clear_all()
    clear_telemetry_cache()
    config_sync.forget_targets()
    firmware.clear_all()
    prepare_network()
    return project


def reset() -> None:
    """Application shutdown: queue, listener and in-memory credentials."""
    global _STARTED, _LOADED_DEFAULTS
    from .presenters import clear_telemetry_cache

    try:
        jobs.QUEUE.close()
    except Exception:
        pass
    try:
        telemetry.MONITOR.stop()
    except Exception:
        pass
    try:
        adminkey.WATCH.stop()
    except Exception:
        pass
    # The computer's network goes back as it was found. This is the ONLY
    # reliable moment: `app.py` calls reset() in main()'s finally, before the
    # interpreter is ended outright, and an address left behind would outlive
    # the application that needed it.
    try:
        network.release_all()
    except Exception:
        pass
    clear_telemetry_cache()
    config_sync.forget_targets()
    firmware.clear_all()
    credentials.forget_all()
    # The copies of the project maps that came off the service key go with
    # the session that made them.
    adminkey.pack.clear_session()
    with _START_LOCK:
        _STARTED = False
        _LOADED_DEFAULTS = 0
