#!/usr/bin/env python3
"""Is the service key in the machine right now?

There is no socket between the panel and its window — the UI polls, the way
it already polls for jobs and device state (see `static/js/core/schedule.js`).
So this keeps an answer ready rather than pushing one: a daemon thread
watches the mounted volumes — several times a second for the cheap half of
the question, every couple of seconds for the whole of it (`_run`) — and
`/api/admin/key` hands back what it saw, or takes a look itself if that has
gone stale (`fresh`).

`generation` is what the UI actually watches. It counts OBSERVED CHANGES, not
polls, so the browser can ask twice a second and still know that nothing has
happened. It is also what stops the panel from asking "switch to admin mode?"
every two seconds after the user has said no: the declined generation is
remembered, and the question comes back only after the key has been taken out
and put in again.

LEAVING ADMIN MODE IS DECIDED HERE, because this is the only place that sees
the key go. Pulling the stick ends admin mode — that is what makes it a key
rather than a password typed once. The single exception is a job that is
WRITING to devices: an IP assignment or a firmware upload half-finished is a
worse outcome than a door left open for another few minutes, so the drop
waits for the queue to clear and the badge says so meanwhile.
"""
from __future__ import annotations

import threading
import time

from .. import editions
from . import keyfile, pack, secret, volumes

# How often the WHOLE question is asked: which volumes are mounted, and what
# is on them.
INTERVAL = 2.0
# How often the cheap half is asked — which volumes are mounted. A glob and a
# stat, and the only thing that changes when somebody pushes a stick in.
TICK = 0.35
# How long a change is chased before settling back to the slow beat. A volume
# that has just appeared may not be readable for a moment yet, so one look at
# it is not enough.
SETTLE = 2.0
# How old the last observation may be before a caller takes its own.
FRESH = 1.0


class KeyWatch:
    """One observation of the machine's removable volumes, kept fresh."""

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._present = False
        self._recognised = False
        self._label = ""
        self._reason = ""
        self._volume = None
        self._pack = 0
        self._revoke_pending = False
        self._generation = 0
        self._seen_at = 0.0

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        """Begin watching. Safe to call repeatedly."""
        if not secret.usable():
            # A build cut without key material cannot recognise a stick, so
            # there is nothing for a thread to do. `/api/edition` reports
            # this as "admin unavailable" rather than as "no key inserted".
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run,
                                            name="panel-adminkey", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
        self._stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=INTERVAL + 1.0)

    def _run(self) -> None:
        """The cheap half often, the whole question rarely.

        WHY IT USED TO BE ASYMMETRIC — a stick pulled out was noticed at
        once, a stick pushed in was not. That is what a two-second beat does
        to a volume that takes a second or two to mount: unmounting is
        instant and lands inside a tick, while mounting finishes just after
        one has gone by and waits for the next.

        So which volumes are mounted is asked five times as often. It is a
        glob and a stat, and it is the only thing that changes when a stick
        goes in. READING one costs a great deal more — on macOS it is a
        command run in the operator's own session (see `handback`) — so that
        is done when the answer can actually have moved: on a change, for a
        moment afterwards, and otherwise on the old slow beat.
        """
        mounted = None
        looked = 0.0
        settling = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                seen = tuple(str(volume) for volume in volumes.removable())
            except Exception:
                seen = mounted
            if seen != mounted:
                mounted = seen
                settling = now + SETTLE
            if now < settling or now - looked >= INTERVAL:
                try:
                    self.observe()
                except Exception:
                    # A watcher that dies leaves the panel believing no key
                    # was ever inserted, and nothing on screen would say why.
                    pass
                looked = time.monotonic()
            else:
                # Nothing has arrived and nothing has gone, so the answer
                # already in hand is current and `fresh` need not take
                # another. This is what keeps the window's polling free.
                self._still_current()
            self._stop.wait(TICK)

    def _still_current(self) -> None:
        with self._lock:
            self._seen_at = time.monotonic()

    # ── one look at the machine ──────────────────────────────────────────
    def observe(self) -> dict:
        """Scan the volumes once and record what was found.

        Called by the thread, and directly at start-up so the first answer is
        ready before the window asks for it.
        """
        found = None
        rejected = None
        for volume in volumes.removable():
            entry = keyfile.read(volume)
            if entry is None:
                continue
            if entry.recognised:
                found = (volume, entry)
                break
            rejected = rejected or (volume, entry)

        target = found or rejected
        if target is None:
            self._record(False, False, "", "", None, 0)
        else:
            volume, entry = target
            projects = pack.projects(volume) if entry.recognised else []
            for project in projects:
                editions.add_extra(project)
            self._record(True, entry.recognised, entry.label, entry.reason,
                         volume, len(projects))
        self._apply_mode()
        return self.snapshot()

    def _record(self, present, recognised, label, reason, volume,
                pack_count) -> None:
        with self._lock:
            self._seen_at = time.monotonic()
            changed = (present, recognised, label, reason, pack_count) != (
                self._present, self._recognised, self._label, self._reason,
                self._pack)
            self._present = present
            self._recognised = recognised
            self._label = label
            self._reason = reason
            self._volume = volume
            self._pack = pack_count
            if changed:
                self._generation += 1

    # ── the mode this observation implies ────────────────────────────────
    def _apply_mode(self) -> None:
        if not editions.is_active():
            return
        if editions.opens_as_admin():
            # This package opened as admin without a key, so a key
            # going away takes nothing with it.
            return
        with self._lock:
            recognised = self._recognised
        if recognised or not editions.admin():
            self._set_pending(False)
            return
        if _writing():
            self._set_pending(True)     # drop it when the queue clears
            return
        _leave_admin()
        self._set_pending(False)

    def _set_pending(self, pending: bool) -> None:
        with self._lock:
            if self._revoke_pending != pending:
                self._revoke_pending = pending
                self._generation += 1

    # ── what the API hands out ───────────────────────────────────────────
    def fresh(self, max_age: float = FRESH) -> dict:
        """The observation, taken again if the last one has gone stale.

        THE TWO POLLS USED TO ADD UP. The window asks every couple of
        seconds and this thread looked every couple of seconds, and the two
        are not in step: a stick pushed in just after a look was answered
        out of that look, and the news arrived up to TWICE the interval
        late. That is the "sometimes it takes ages to notice".

        So asking is what makes an observation. The answer is then at most
        one poll of the window's own behind, and the thread is left to do
        what only it can — notice a key being pulled while nobody is asking.
        """
        with self._lock:
            fresh_enough = (time.monotonic() - self._seen_at) < max_age
        return self.snapshot() if fresh_enough else self.observe()

    def snapshot(self) -> dict:
        """UI-safe. NO PROOF, NO DIGEST, AND NO PATH.

        The volume path is the panel's own business: naming it would tell a
        field screen which drive to go and look at, and there is no screen
        that needs to know.
        """
        with self._lock:
            return {
                "present": self._present,
                "recognised": self._recognised,
                "label": self._label,
                "reason": self._reason,
                "packAvailable": self._pack,
                "revokePending": self._revoke_pending,
                "generation": self._generation,
            }

    def volume(self):
        """The volume the recognised key is on, for the routes that write."""
        with self._lock:
            return self._volume if self._recognised else None

    def reset(self) -> None:
        """Forget everything observed. Tests only."""
        self.stop()
        with self._lock:
            self._present = False
            self._recognised = False
            self._label = ""
            self._reason = ""
            self._volume = None
            self._pack = 0
            self._revoke_pending = False
            self._generation = 0


def _leave_admin() -> None:
    # Imported here rather than at the top: lifecycle imports this package,
    # and it is lifecycle that knows what has to be put back — the project,
    # the queue's device results, the configuration targets.
    from ..api.lifecycle import leave_admin                 # noqa: PLC0415
    leave_admin()


def _writing() -> bool:
    from .. import jobs                                    # noqa: PLC0415
    from ..api.presenters import WRITING_JOB_KINDS         # noqa: PLC0415
    return any(job.kind in WRITING_JOB_KINDS
               and job.state in (jobs.QUEUED, jobs.RUNNING)
               for job in jobs.QUEUE.list())


WATCH = KeyWatch()


def wait_for_change(previous: int, timeout: float = 0.0) -> dict:
    """Block until the observation moves past `previous`. Tests only —
    the UI polls instead, and nothing in the panel waits on a stick."""
    deadline = time.monotonic() + timeout
    while True:
        state = WATCH.snapshot()
        if state["generation"] != previous or time.monotonic() >= deadline:
            return state
        time.sleep(0.05)
