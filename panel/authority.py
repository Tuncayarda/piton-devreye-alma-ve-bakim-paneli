#!/usr/bin/env python3
"""Who is holding admin mode open right now — and nobody, so it closes.

THERE ARE TWO WAYS IN NOW, and that is what this module exists for. The
service key was the only one, so the code that read the key could also decide
the mode was over: no stick, no admin (`panel.adminkey.watcher`). Add a
second source and that reasoning inverts into a bug — the USB watcher, which
knows nothing about a remote session, would take back within two seconds
every mode the remote session had just opened, and the two would fight over
the flag several times a minute.

So the decision moves here, and it becomes a decision about SOURCES rather
than about a stick. Each watcher reports only what it can see:

    report("key", ...)      the stick is in this machine, or it is not
    report("remote", ...)   a signed grant is unexpired, or it is not

and `settle()` answers the one question neither of them can answer alone: is
anything still holding the door? Only when nothing is does the mode end.

THIS MODULE NEVER GRANTS. It can turn admin mode off and never on. Entering
is earned in the place that can check the evidence — the volume re-read in
`admin_routes.post_mode`, the signature checked in `remote_routes` — and a
module that could do both would be a module where a reporting bug becomes an
escalation. Reporting `live=True` for a source that is not live keeps a mode
that was already granted; it cannot start one.

THE WRITING EXCEPTION IS UNCHANGED, and it was always the interesting case: a
half-written IP assignment or a firmware upload interrupted by a door closing
is worse than the door staying open a few minutes longer. So when the last
source goes while devices are being written to, the drop is deferred and the
badge says so.
"""
from __future__ import annotations

import threading

from . import editions

KEY = "key"
REMOTE = "remote"

_LOCK = threading.RLock()
_LIVE: dict[str, bool] = {KEY: False, REMOTE: False}
_PENDING = False
# `leave_admin` unwinds the session, and unwinding it ends the remote watch,
# and ending the watch reports a source going away — which is a call back
# into `settle()` from inside `settle()`. Guarded rather than untangled: the
# call chain is correct in both directions, and only its re-entry is not.
_SETTLING = False


def report(source: str, live: bool) -> None:
    """Record what one watcher can see. Decides nothing on its own."""
    with _LOCK:
        _LIVE[source] = bool(live)


def holding() -> tuple[str, ...]:
    """The sources holding admin mode open, for the API to describe."""
    with _LOCK:
        return tuple(name for name, live in _LIVE.items() if live)


def settle() -> bool:
    """End admin mode if nothing is holding it. True if the answer moved.

    The caller bumps its own `generation` on True, so a window polling for
    changes learns that the drop is now pending without either watcher
    having to know about the other's counter.
    """
    global _SETTLING
    if not editions.is_active():
        return False
    if editions.opens_as_admin():
        # This run holds the build secret and opened as admin without any
        # source at all, so no source going away takes anything with it.
        return False
    with _LOCK:
        if _SETTLING:
            return False
        live = any(_LIVE.values())
    if live or not editions.admin():
        return _set_pending(False)
    if _writing():
        return _set_pending(True)       # drop it when the queue clears
    with _LOCK:
        _SETTLING = True
    try:
        _leave_admin()
    finally:
        with _LOCK:
            _SETTLING = False
    return _set_pending(False)


def revoke_pending() -> bool:
    """Is admin mode waiting for a write to finish before it ends?"""
    with _LOCK:
        return _PENDING


def _set_pending(pending: bool) -> bool:
    global _PENDING
    with _LOCK:
        if _PENDING == pending:
            return False
        _PENDING = pending
        return True


def reset() -> None:
    """Forget every source. Tests, and service shutdown."""
    global _PENDING, _SETTLING
    with _LOCK:
        for name in _LIVE:
            _LIVE[name] = False
        _PENDING = False
        _SETTLING = False


def _leave_admin() -> None:
    # Imported here rather than at the top: lifecycle imports the packages
    # that import this one, and it is lifecycle that knows what has to be put
    # back — the project, the queue's device results, the configuration
    # targets, and the remote watch itself.
    from .api.lifecycle import leave_admin                 # noqa: PLC0415
    leave_admin()


def _writing() -> bool:
    from . import jobs                                     # noqa: PLC0415
    from .api.presenters import WRITING_JOB_KINDS          # noqa: PLC0415
    return any(job.kind in WRITING_JOB_KINDS
               and job.state in (jobs.QUEUED, jobs.RUNNING)
               for job in jobs.QUEUE.list())
