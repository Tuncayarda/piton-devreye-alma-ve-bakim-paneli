#!/usr/bin/env python3
"""Is the grant still good right now?

The service key's watcher looks at the machine; this one asks a question over
the network and has to hear an answer back. Otherwise the two are the same
shape deliberately: a daemon thread keeps an answer ready, the window polls
`/api/admin/remote` rather than being pushed to, and `generation` counts
OBSERVED CHANGES so that polling every second is a cheap way of learning that
nothing has happened (see panel.adminkey.watcher).

WHAT KEEPS THE DOOR OPEN IS A DEADLINE, NOT A CONNECTION. Every answer the
service signs carries a ttl of a few seconds, and admin mode lasts until that
runs out. The beat is faster than the ttl, so in normal running each answer
pushes the deadline out before the last one reaches it, and the mode simply
continues. Stop answering — the operator closes the link, the wireless drops,
the laptop is carried out of range — and nothing has to be detected at all:
the deadline arrives and the mode ends. There is no state to get wrong, no
timeout to tune twice, and no way for a lost connection to be missed.

MEASURED ON A MONOTONIC CLOCK, from the moment the answer arrived. Not from
the `issuedAt` in the payload, and not against the machine's wall clock:
those disagree in the field for entirely innocent reasons, and a customer
setting the clock back must not extend anything.

A DEFINITE NO IS NOT WAITED OUT. If the service says the code is unknown or
the session is closed, or if a signature does not check, the mode ends on the
spot rather than at the deadline — closing a link should be felt when it is
closed. Only silence is ridden out, because silence is what a wireless
network does between two access points.

AND IT DOES NOT COME BACK BY ITSELF. Once a session has ended, the beat stops
and the operator reconnects with the same code. An admin mode that returned
on its own when the network did would be a mode nobody watched being granted.

THE SESSION IS HANDED BACK when the panel is done with it, rather than left
to run out with nobody in it. That is a courtesy in the ordinary case and
matters in the QR case: a paired session is minted for one machine and one
machine only, so one left open is a machine slot and a line on the operator's
list that mean nothing. Nothing waits on it — see `_release`.
"""
from __future__ import annotations

import secrets
import threading

from .. import authority, clock, editions, settings
from . import client, protocol, session, verify

# HOW OFTEN THE QUESTION IS ASKED, and it is worked out rather than declared.
#
# What holds the door is the ttl on the last signed answer, so the beat has
# to sit comfortably inside it: a third of the ttl means two answers may be
# lost before the deadline arrives and the mode moves. Four seconds said
# exactly that in a second place — a third of the twelve the service asks
# for — and a second place is a place to get it wrong: a service that began
# issuing a longer grant would have gone on being asked three times as often
# as it needed, for ever, with nothing on this side saying why.
#
# The ceiling is thirty seconds. Past that a link that has gone is a link
# nobody asks about for half a minute, and the operator's screen would go on
# saying "admin mode" for longer than anybody believes a screen. The floor is
# four, so a service that asks for a very short grant cannot turn this into a
# busy loop against itself.
#
# Reaching the ceiling needs the SERVICE to issue a ttl of ninety seconds;
# with today's twelve this beats every four, exactly as it did before.
BEAT_MIN = 4.0
BEAT_MAX = 30.0


def beat_for(ttl: float) -> float:
    """How long to wait before asking again, given the grant in hand."""
    if not ttl or ttl <= 0:
        return BEAT_MIN
    return min(BEAT_MAX, max(BEAT_MIN, float(ttl) / 3.0))
# Long enough to be worth a fresh look rather than the answer in hand, when
# the window asks. The same idea as the key watcher's `FRESH`.
FRESH = 1.0

# Reasons that END the session rather than being ridden out. Everything the
# signature check can say is here too: an answer that does not verify is not
# a network problem, and waiting to see whether the next one verifies would
# be waiting for an attacker to get it right.
FATAL = frozenset({"unknownCode", "closed", "editionNotAllowed",
                   "notThisMachine", "installLimit", "untrusted", "nonce",
                   "install", "edition", "version", "malformed"})

# How long shutdown waits for the hand-back to leave the machine. Short on
# purpose: the application is closing, and a wireless network that has
# already gone must not hold the window open while a socket times out. If it
# does not get away the session simply expires, which is what it did before
# there was anything to send.
RELEASE_GRACE = 1.5


class RemoteWatch:
    """One remote service session, kept alive or allowed to lapse."""

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._giving_back: threading.Thread | None = None
        # ONE EVENT PER RUN, and the event IS the run's name. `disconnect`
        # joins the beat thread with a timeout and carries on regardless —
        # it has to, the thread may be sitting in a ten-second network read —
        # so a thread can survive its own disconnection. With a single
        # shared Event, `connect` then cleared the very flag that survivor
        # was watching, and two beats ran against one set of state. Now the
        # survivor holds an Event nobody clears: it finds it set and dies,
        # and every write it still had in flight is refused by the token
        # checks in `_round`/`_record` (see there). A fresh `connect` makes
        # a fresh Event, so the current run is always `self._stop` and a
        # thread whose captured event is not `self._stop` is history.
        self._stop = threading.Event()
        self._code = ""
        self._label = ""
        self._session = ""
        self._reason = ""
        self._expires = 0.0
        self._ttl = 0.0
        self._generation = 0
        self._seen_at = 0.0

    # ── starting and ending ──────────────────────────────────────────────
    def connect(self, code: str) -> str:
        """Take a code and hold the door with it. "" if it worked.

        THE FIRST ROUND IS SYNCHRONOUS, and the thread only starts if it
        succeeded. The operator has just typed eight characters and is
        waiting to be told whether they were the right ones; answering
        "started, we shall see" and reporting the failure through a poll
        two seconds later would be a worse screen for no gain.
        """
        if not verify.available():
            return "unavailable"
        normalised = protocol.normalise(code)
        if normalised is None:
            return "badCode"

        self.disconnect()
        with self._lock:
            run = self._stop = threading.Event()
            self._code = normalised
            self._reason = ""
        reason = self._round(run)
        if reason:
            with self._lock:
                if self._stop is run:
                    self._code = ""
            return reason

        with self._lock:
            if self._stop is not run or run.is_set():
                # Superseded while the first answer was on the wire: another
                # connect or disconnect owns the state now. Whatever door is
                # open is theirs to hold — starting a second beat here would
                # recreate exactly the two-threads-one-state race this token
                # exists to close.
                return ""
            self._thread = threading.Thread(target=self._run,
                                            name="panel-remotekey",
                                            daemon=True)
            self._thread.start()
        return ""

    def disconnect(self) -> None:
        """End the session. Reports the source gone; does NOT settle.

        Settling is left to the caller, and that is not tidiness: this is
        called from inside `lifecycle.leave_admin`, which is itself called
        from `authority.settle`. Ending the mode from here would be a second
        lap of the same wheel.
        """
        with self._lock:
            thread = self._thread
            self._thread = None
            stop = self._stop
        # Only the CURRENT run's event. A fresh connect swaps `_stop` for a
        # new Event, so a disconnect can never reach forward and stop a run
        # it never knew about.
        stop.set()
        if thread is not None and thread.is_alive() \
                and thread is not threading.current_thread():
            # The join may time out — the thread can be deep in a network
            # read. That is tolerated rather than waited out: the survivor's
            # event is set, so it exits at its next look, and until then the
            # token checks keep its late answer from touching the state.
            thread.join(timeout=client.READ_TIMEOUT + 1.0)
        with self._lock:
            code, self._code = self._code, ""
            self._label = ""
            self._session = ""
            self._expires = 0.0
            self._ttl = 0.0
            self._generation += 1
        self._release(code)
        authority.report(authority.REMOTE, False)

    def _release(self, code: str) -> None:
        """Give the session back to the service. Nothing waits for it.

        ON ITS OWN THREAD, because this is called from the button that
        leaves admin mode and from shutdown, and neither may be held up by a
        machine whose network has gone. The service takes the same request
        twice without complaint, so a reply lost on the way back costs
        nothing (see `panel.remotekey.client.release`).
        """
        if not code:
            return
        install = session.install_id()

        def hand_back() -> None:
            try:
                client.release(code=code, install_id=install)
            except client.ServiceError:
                pass

        giving_back = threading.Thread(target=hand_back,
                                       name="panel-remotekey-release",
                                       daemon=True)
        with self._lock:
            self._giving_back = giving_back
        giving_back.start()

    def _run(self) -> None:
        with self._lock:
            if self._thread is not threading.current_thread():
                return          # superseded before the first beat
            # Taken under the same lock that still names this thread as the
            # current one, so it is THIS run's event and no other's.
            run = self._stop
        while not run.is_set():
            # Read each time round: the service may hand out a different ttl
            # from one answer to the next, and the wait follows it.
            with self._lock:
                ttl = self._ttl
            run.wait(beat_for(ttl))
            if run.is_set():
                return
            reason = self._round(run)
            with self._lock:
                if self._stop is not run:
                    # A disconnect outlived its join and a new session began
                    # while this round was on the wire. The state is the new
                    # run's; ending anything from here would end THEIRS.
                    return
                over = reason in FATAL or not self.live()
                if over:
                    # The session is over, either because it was refused or
                    # because the last good answer has run out. Either way
                    # there is nothing left to ask about.
                    self._thread = None
                    run.set()
            if over:
                self._lapse(reason, run)
                return

    # ── one round ────────────────────────────────────────────────────────
    def _round(self, run: threading.Event | None = None) -> str:
        """Ask once. "" if a fresh grant is now in hand, else the reason.

        `run` is the asking run's stop token. Everything the answer would
        write is guarded on it: the question travels the network with no
        lock held, and by the time the answer lands a disconnect — or a
        whole new session — may own the state. A grant applied then would
        extend a door the operator watched close. `None` means "the current
        state, whoever holds it" and is for callers that are not a run at
        all (`fresh`).
        """
        with self._lock:
            if run is not None and (self._stop is not run or run.is_set()):
                return "closed"
            code = self._code
        if not code:
            return "closed"

        nonce = secrets.token_bytes(32)
        install = session.install_id()
        edition = editions.active().id
        try:
            payload, signature = client.ask(
                code=code, nonce=nonce, install_id=install, edition=edition,
                app_version=settings.APP_VERSION)
        except client.ServiceError as exc:
            self._record(exc.reason, run)
            return exc.reason

        grant, reason = protocol.check(payload, signature, nonce=nonce,
                                       install_id=install, edition=edition)
        if grant is None:
            self._record(reason, run)
            return reason

        with self._lock:
            if run is not None and (self._stop is not run or run.is_set()):
                # Stopped or superseded while the answer was on the wire —
                # the disconnect happened, whatever this answer says.
                # Nothing is written and nothing is settled: the "" only
                # tells the asking loop the service did not refuse, and
                # that loop's own token check is what retires it.
                return ""
            self._seen_at = clock.monotonic()
            self._ttl = grant.ttl
            self._expires = self._seen_at + grant.ttl
            changed = (self._label, self._session, self._reason) != (
                grant.label, grant.session, "")
            self._label = grant.label
            self._session = grant.session
            self._reason = ""
            if changed:
                self._generation += 1
        self._settle()
        return ""

    def _record(self, reason: str, run: threading.Event | None = None) -> None:
        """Note why a round failed. Does not itself end anything — whether
        it has is a question about the deadline, asked by the caller."""
        with self._lock:
            if run is not None and (self._stop is not run or run.is_set()):
                return          # a stopped run's news is nobody's news
            self._seen_at = clock.monotonic()
            if self._reason != reason:
                self._reason = reason
                self._generation += 1
        self._settle()

    def _lapse(self, reason: str,
               run: threading.Event | None = None,
               seen_expires: float | None = None) -> None:
        with self._lock:
            if run is not None and self._stop is not run:
                return          # a newer session's state is not ours to end
            if seen_expires is not None and self._expires != seen_expires:
                # `fresh()` read the deadline OUTSIDE this lock and hands it
                # back here. A connect landing in that gap holds a LIVE
                # grant under a new deadline, and the stale reading must not
                # end it — the same rule the run token enforces for the
                # beats. A caller ending the session for its own reason (the
                # service said so) passes nothing and is not second-guessed.
                return
            self._expires = 0.0
            self._ttl = 0.0
            self._code = ""
            if reason and self._reason != reason:
                self._reason = reason
            self._generation += 1
        self._settle()

    def _settle(self) -> None:
        authority.report(authority.REMOTE, self.live())
        if authority.settle():
            with self._lock:
                self._generation += 1

    # ── what the API hands out ───────────────────────────────────────────
    def live(self) -> bool:
        """Is a signed grant still inside its ttl?"""
        with self._lock:
            return self._expires > clock.monotonic()

    def snapshot(self) -> dict:
        """UI-safe. NO CODE, NO NONCE, NO SIGNATURE.

        The code is masked rather than returned: the panel may be on a
        screen in a rack room, and a session code left on it is a session
        code somebody else can use until it is closed.
        """
        with self._lock:
            remaining = max(0.0, self._expires - clock.monotonic())
            return {
                "available": verify.available(),
                "active": remaining > 0,
                "label": self._label,
                "codeMasked": protocol.mask(self._code),
                "expiresIn": round(remaining, 1),
                "reason": self._reason,
                "revokePending": authority.revoke_pending(),
                "generation": self._generation,
            }

    def fresh(self, max_age: float = FRESH) -> dict:
        """The state, settled again if the deadline may have passed unnoticed.

        The thread beats at a third of the ttl; a grant can therefore run
        out between two beats — and the longer the ttl, the longer that gap
        is — and the window would be told "still active" for the remainder.
        Asking is what makes the observation, exactly as it is for the
        service key, and it is why the window's own second-by-second poll is
        NOT slowed down with the beat: the two answer different questions.
        """
        with self._lock:
            expires = self._expires
        if expires and expires <= clock.monotonic():
            self._lapse("expired", seen_expires=expires)
        return self.snapshot()

    def reset(self) -> None:
        """Forget the session entirely. Tests, and service shutdown."""
        self.disconnect()
        with self._lock:
            giving_back = self._giving_back
            self._giving_back = None
            self._reason = ""
            self._generation = 0
            self._seen_at = 0.0
        if giving_back is not None and giving_back.is_alive() \
                and giving_back is not threading.current_thread():
            giving_back.join(timeout=RELEASE_GRACE)


WATCH = RemoteWatch()
