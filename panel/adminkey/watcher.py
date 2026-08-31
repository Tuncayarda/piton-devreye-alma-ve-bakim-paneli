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

PULLING THE STICK ENDS ADMIN MODE — that is what makes it a key rather than
a password typed once — but this module no longer decides that on its own.
It sees the key go and says so; `panel.authority` weighs that against the
other way in (a remote service session) and ends the mode only when nothing
at all is holding it. Deciding here would mean deciding without knowing about
the other source, and taking back a mode granted two seconds earlier.
"""
from __future__ import annotations

import threading
import time

from .. import authority, editions
from . import keyfile, pack, sealed, secret, volumes

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
        # `observe` only — and deliberately NOT the RLock above. The scan
        # must run without holding `_lock` (it spawns subprocesses, and the
        # window's poll must not block behind them), and it must never run
        # twice at once: the beat thread, `fresh()` callers and the admin
        # routes all call `observe`, and on macOS each copy is a launchctl
        # run PER VOLUME in the operator's session. A plain Lock taken with
        # `acquire(blocking=False)` gives exactly the wanted shape — one
        # scanner, and every latecomer handed the answer already in hand.
        self._observing = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._present = False
        self._recognised = False
        self._label = ""
        self._reason = ""
        self._volume = None
        self._pack = 0
        self._proof = b""
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
                # REMOVABLE ONLY, and not `searched()`. This is the cheap
                # "has something appeared" test, and the application's own
                # folder never appears or disappears — including it would
                # add a constant to a comparison and detect nothing. A key
                # left in that folder is still found by `observe()` below,
                # on the beat and on the next question the window asks.
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
    def observe(self, wait: bool = False) -> dict:
        """Scan the volumes once and record what was found.

        Called by the thread, and directly at start-up so the first answer is
        ready before the window asks for it.

        ONE SCAN AT A TIME, and two kinds of caller. The beat and `fresh()`
        do not queue up behind a scan already running — a second look at the
        same volumes could only say the same thing — and are handed the
        current answer instead; what they miss is younger than FRESH, which
        is exactly the staleness `fresh()` already accepts. A caller about
        to GRANT something on the answer cannot accept that: losing the
        race there returned the snapshot from BEFORE the concurrent scan,
        and a stick pulled in that instant could still open admin mode on
        its ghost. Those callers pass `wait=True` and block for the scan —
        they are a few user-initiated requests per session, not a poll
        (panel/api/routes/admin_routes.py).
        """
        if wait:
            with self._observing:
                return self._observe()
        if not self._observing.acquire(blocking=False):
            return self.snapshot()
        try:
            return self._observe()
        finally:
            self._observing.release()

    def _observe(self) -> dict:
        found = None
        rejected = None
        for volume in volumes.searched():
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
                         volume, len(projects), entry.proof)
            # The stick carries the key that opens the device lists sealed
            # into this package (see `vault.py`). Opened IN ADMIN MODE ONLY:
            # the menu offers extras only there (`editions.projects`), so
            # unsealing on mere sight of the key bought nothing — and cost
            # the one thing the sealing exists for, because it left another
            # customer's list decrypted in the temp directory of a machine
            # whose operator never entered admin mode at all. Entering the
            # mode unseals too (`editions.set_admin` → `unlock_sealed`), so
            # this call only keeps an already-admin session current when the
            # stick arrives after the fact.
            if entry.recognised and editions.admin():
                sealed.unlock(entry.proof)
        self._apply_mode()
        return self.snapshot()

    def _record(self, present, recognised, label, reason, volume,
                pack_count, proof: bytes = b"") -> None:
        with self._lock:
            self._seen_at = time.monotonic()
            changed = (present, recognised, label, reason, pack_count) != (
                self._present, self._recognised, self._label, self._reason,
                self._pack)
            self._proof = bytes(proof or b"")
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
        """Report what was seen, and let the arbiter decide what it means.

        The generation is bumped when the ARBITER's answer moves, not when
        this observation does — `_record` has already counted the latter.
        What changes here is "the mode is about to end", which the window
        shows in the badge and which a source this module cannot see may
        equally have caused.
        """
        with self._lock:
            recognised = self._recognised
        authority.report(authority.KEY, recognised)
        if authority.settle():
            with self._lock:
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
                # The arbiter's, not this watcher's: the write that is
                # holding the door may have been holding it for a remote
                # session (see panel.authority).
                "revokePending": authority.revoke_pending(),
                "generation": self._generation,
            }

    def volume(self):
        """The volume the recognised key is on, for the routes that write."""
        with self._lock:
            return self._volume if self._recognised else None

    def content_key(self) -> bytes:
        """K from the key in the machine, or empty. Recognised keys only.

        The one caller is the sealed-project store. Kept behind a method
        rather than exposed as an attribute so that "there is no key in the
        machine" and "the key in the machine is not ours" are the same empty
        answer here as they are everywhere else.
        """
        with self._lock:
            return self._proof if self._recognised else b""

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
            self._proof = b""
            self._generation = 0


WATCH = KeyWatch()
