#!/usr/bin/env python3
"""Who may touch the devices right now — one claim for the whole process.

Three workers reach the same hardware and none of them used to ask the
others: the queue's single worker (every job, scans included), the ADB
screen's runner (outside the queue on purpose) and the light refresh
(request thread, no job). Each pair had, at best, a check-then-act glance at
the other's state — the refresh looked at `RUNNER.busy()` but the runner
never looked back, so a scan starting mid-install tore the install's adb
transport out from under it; the documented worst collision in the tree.

So the question gets ONE answer. The queue worker takes the claim for the
whole of every job body — a scan is a reader, but a reader that tires
devices and shares the adb server, so it queues like everything else. The
runner and the refresh try without waiting and turn a refusal into their
own 409/RunnerBusy: a request thread must answer now, not block behind a
firmware run.

NOT A GUARANTEE OF EXCLUSIVITY ON THE WIRE — the field script and direct
route handlers still talk to devices without it (the switch screen's
one-shot writes, credential checks). It is the gate for the three LONG,
sweeping workers, which are the ones that interleave for minutes at a time.
"""
from __future__ import annotations

import threading

_LOCK = threading.Lock()
_OWNER = ""
_HELD = threading.Lock()


def acquire(owner: str, cancelled=None, poll: float = 0.25) -> bool:
    """Claim the devices. Blocks; `cancelled()` True abandons the wait.

    Returns True once the claim is held. False only when `cancelled` ended
    the wait — the caller was told to stop wanting it.
    """
    while not _HELD.acquire(timeout=poll):
        if cancelled is not None and cancelled():
            return False
    with _LOCK:
        global _OWNER
        _OWNER = str(owner)
    return True


def try_acquire(owner: str) -> bool:
    """Claim the devices only if nobody holds them. Never blocks."""
    if not _HELD.acquire(blocking=False):
        return False
    with _LOCK:
        global _OWNER
        _OWNER = str(owner)
    return True


def release(owner: str) -> None:
    """Give the claim back. Only the holder's release counts."""
    global _OWNER
    with _LOCK:
        if _OWNER != str(owner):
            return
        _OWNER = ""
    try:
        _HELD.release()
    except RuntimeError:
        pass


def holder() -> str:
    """Who holds the claim, or empty — for the message a refusal carries."""
    with _LOCK:
        return _OWNER


def reset() -> None:
    """Drop any claim. Shutdown and tests: the workers it belonged to are
    being stopped by the same reset, and a claim that outlived them would
    refuse every worker of the next service for no one's benefit."""
    global _OWNER
    with _LOCK:
        _OWNER = ""
    try:
        _HELD.release()
    except RuntimeError:
        pass
