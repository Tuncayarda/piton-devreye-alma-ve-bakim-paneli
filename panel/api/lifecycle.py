#!/usr/bin/env python3
"""Service start-up and shutdown, plus the optional admin password."""
from __future__ import annotations

import secrets
import threading

from .. import config_sync, credentials, firmware, jobs, telemetry

# Admin password: asked for when the application is started with one,
# otherwise the admin screen opens without one. Never written anywhere.
_ADMIN_PASSWORD: str | None = None

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
            _STARTED = True
        # `reset()` closes the queue. If the service is rebuilt in the same
        # process, make sure the job queue is open again.
        jobs.QUEUE.open()
        return _LOADED_DEFAULTS


def set_admin_password(password: str | None) -> None:
    global _ADMIN_PASSWORD
    _ADMIN_PASSWORD = password or None


def admin_password_required() -> bool:
    return bool(_ADMIN_PASSWORD)


def check_admin_password(password: str) -> bool:
    if not _ADMIN_PASSWORD:
        return True
    return secrets.compare_digest(str(password), _ADMIN_PASSWORD)


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
    clear_telemetry_cache()
    config_sync.forget_targets()
    firmware.clear_all()
    credentials.forget_all()
    with _START_LOCK:
        _STARTED = False
        _LOADED_DEFAULTS = 0
