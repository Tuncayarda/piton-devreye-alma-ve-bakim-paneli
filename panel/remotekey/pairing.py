#!/usr/bin/env python3
"""The square on the screen: a session asked for instead of dictated.

The code path is somebody reading eight characters down a telephone. This is
the same permission asked for in the other direction: the panel draws a QR,
the engineer points a phone at it, approves with the operator token they
already carry, and the panel — which has been asking all along — is handed
the code and starts the ordinary grant loop with it.

WHAT IS DRAWN IS NOT A CREDENTIAL. The square holds a pairing id and nothing
else, and the pairing id is public the instant it is on screen: anybody in
the room can photograph it. It buys them the approval page and no further,
because approving needs an operator token, and because the code that comes
out is bound to THIS installation and refused on any other machine.

THE POLL KEY IS THE CREDENTIAL, and it never leaves this process: not into
the square, not over the API to the window, not into the settings file, not
into a log. It is the only thing that can read the issued code back, so a
photograph of the screen cannot collect the answer to the question the screen
is asking.

NO LOCAL DEADLINE. `expires` comes back and is kept for nothing but the
record: it is the service's wall clock, and the panel's may be a month out
for entirely innocent reasons (see `panel.remotekey.protocol`). The service
answers `expired` when it is expired, and that answer is the deadline.
"""
from __future__ import annotations

import base64
import math
import re
import threading

from . import client, verify

# What the service issues: twelve characters of Crockford's base32.
ID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{12}$")
# HOW MANY SQUARES ACROSS, read off the drawing itself. The service draws one
# unit per module and puts the whole thing — quiet zone included — in the
# viewBox, so this number is what the window needs to size the picture at a
# WHOLE NUMBER OF PIXELS PER MODULE. Scaled by a fraction instead, every
# module edge lands mid-pixel and is antialiased into a grey smear, and a
# camera looking for hard black and white has to work for it.
VIEW_BOX = re.compile(r'viewBox="0 0 (\d{2,3}) (\d{2,3})"')
# Every dark module, as the service draws them: one unit square each. The
# smallest coordinate among them is exactly how wide the white margin is,
# which is the one number the window cannot work out for itself and must not
# guess — it decides how much of that margin can be trimmed on screen without
# trimming the code with it.
MODULE = re.compile(r"M(\d{1,3}) (\d{1,3})h1v1h-1z")
# A QR code is 21 modules across at version 1 and 177 at version 40, and the
# quiet zone adds eight. Anything outside that is not a QR code.
MIN_MODULES = 21
MAX_MODULES = 200
MAX_KEY = 128
# The drawn square, as SVG. A version 10 code at eight pixels a module is a
# few tens of kilobytes; anything past this is not a QR code.
MAX_IMAGE = 96 * 1024
# Markup that has no business in a drawn square. It could not run anyway —
# the window shows this inside an `<img>`, where SVG is static by
# specification and script never executes — but a QR code that arrives
# carrying a script is a service that has been tampered with, and the honest
# thing to do about it is refuse rather than display it safely.
FORBIDDEN = ("<script", "<foreignobject", "javascript:", "<iframe", "<use")

# How often the window asks, when the service does not say. Clamped, because
# a number from the network decides how hard this machine works.
DEFAULT_POLL = 2.0
MIN_POLL = 1.0
MAX_POLL = 30.0

# The states the service can report, and nothing else is taken. `pending` is
# the only one that leaves the square on screen.
STATES = frozenset({"pending", "approved", "denied", "cancelled",
                    "expired", "closed"})


class Pairing:
    """One pending request for a session. At most one at a time."""

    def __init__(self):
        self._lock = threading.RLock()
        self._pair_id = ""
        self._poll_key = ""
        self._url = ""
        self._image = ""
        self._modules = 0
        self._quiet = 0
        self._expires = 0
        self._poll_after = DEFAULT_POLL
        self._state = "idle"

    # ── asking ───────────────────────────────────────────────────────────
    def start(self, *, install_id: str, edition: str, app_version: str,
              hint: str) -> str:
        """Ask for a square. "" if there is one to draw, else the reason.

        Any square already asked for is given up first. The window opens
        this dialog as often as somebody presses the button, and a request
        nobody will answer should not stay on an engineer's phone.
        """
        if not verify.available():
            return "unavailable"
        self.cancel()

        try:
            answer = client.pair(install_id=install_id, edition=edition,
                                 app_version=app_version, hint=hint)
        except client.ServiceError as exc:
            return exc.reason

        pair_id = answer.get("pairId")
        poll_key = answer.get("pollKey")
        url = answer.get("url")
        image, modules, quiet = self._picture(answer.get("qr"))
        if (not isinstance(pair_id, str) or not ID_PATTERN.match(pair_id)
                or not isinstance(poll_key, str) or not poll_key
                or len(poll_key) > MAX_KEY or not image
                or not self._ours(url, pair_id)):
            return "service"

        with self._lock:
            self._pair_id = pair_id
            self._poll_key = poll_key
            self._url = url
            self._image = image
            self._modules = modules
            self._quiet = quiet
            self._expires = int(answer.get("expires") or 0)
            self._poll_after = _beat(answer.get("pollAfter"))
            self._state = "pending"
        return ""

    @staticmethod
    def _ours(url, pair_id: str) -> bool:
        """Is that the address of the service this build was told to use?

        THE SQUARE SENDS A PHONE SOMEWHERE, and what it sends it to is the
        page that will ask an engineer for the operator token — the one
        secret in this arrangement that opens sessions on ANY machine. So
        the address is not taken on the service's word: it is compared with
        the address the panel was compiled with, character for character.
        The worker builds it from the origin the panel connected to, so
        anything else means the answer did not come from where the request
        went.
        """
        expected = f"{verify.service_url().rstrip('/')}/p/{pair_id}"
        return isinstance(url, str) and url == expected

    @staticmethod
    def _picture(qr) -> tuple[str, int, int]:
        """`(picture, modules across, quiet zone)`, or zeroes for anything else.

        Handed to the window already encoded so that nothing anywhere puts
        markup that came off a socket into the page as markup, and measured
        beside it: the module count so the window can size it to whole
        pixels, the quiet zone so it knows what is margin and what is code.
        """
        if not isinstance(qr, str) or len(qr) > MAX_IMAGE:
            return "", 0, 0
        text = qr.strip()
        if not text.startswith("<svg") or not text.endswith("</svg>"):
            return "", 0, 0
        lowered = text.lower()
        if any(word in lowered for word in FORBIDDEN):
            return "", 0, 0
        box = VIEW_BOX.search(text)
        if box is None or box.group(1) != box.group(2):
            return "", 0, 0                 # not square, or not measurable
        modules = int(box.group(1))
        if not MIN_MODULES <= modules <= MAX_MODULES:
            return "", 0, 0
        marks = MODULE.findall(text)
        if not marks:
            return "", 0, 0                 # nothing drawn: not a code
        quiet = min(min(int(x), int(y)) for x, y in marks)
        # The margin cannot be most of the picture, and a code with none at
        # all is one the service drew wrongly.
        if not 0 < quiet < modules // 4:
            return "", 0, 0
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}", modules, quiet

    # ── waiting ──────────────────────────────────────────────────────────
    def poll(self) -> tuple[str, str]:
        """Ask once. `(state, code)`, and the code only when approved.

        THE CODE IS RETURNED RATHER THAN KEPT. The caller hands it straight
        to the watcher, which checks a signature against it; holding a copy
        here would be a session code sitting in memory behind a screen that
        has already moved on. If the caller cannot use it — the machine is
        offline for the moment — the next poll asks for it again, because
        the service answers `approved` for as long as the record lives.
        """
        with self._lock:
            pair_id, poll_key = self._pair_id, self._poll_key
        if not pair_id:
            # Nothing here to ask about: the request was settled or given up
            # while the window still had a square on screen. That is the same
            # fact the service reports when it has lost the pairing, and the
            # window should read the same sentence and draw another.
            return "pairLost", ""

        try:
            answer = client.poll(pair_id=pair_id, poll_key=poll_key)
        except client.ServiceError as exc:
            if exc.reason == "pairLost":
                self.forget("expired")
            return exc.reason, ""

        state = answer.get("state")
        if state not in STATES:
            return "service", ""
        with self._lock:
            self._state = state
        if state != "approved":
            # Denied, expired, cancelled, closed: there is nothing left to
            # ask about, and the poll key goes with the request it opened.
            if state != "pending":
                self.forget(state)
            return state, ""

        code = answer.get("code")
        if not isinstance(code, str) or not code:
            return "service", ""
        return "approved", code

    # ── giving up ────────────────────────────────────────────────────────
    def cancel(self) -> None:
        """The window closed the dialog. Best effort, and never raises.

        The service does not need this — a pending request expires on its
        own — but an abandoned square left hanging on somebody's phone is a
        decision somebody may still make about a machine that has stopped
        listening.
        """
        with self._lock:
            pair_id, poll_key = self._pair_id, self._poll_key
        if pair_id:
            try:
                client.cancel(pair_id=pair_id, poll_key=poll_key)
            except client.ServiceError:
                pass
        self.forget("cancelled")

    def forget(self, state: str = "idle") -> None:
        """Drop the request and the key. The state is kept to report."""
        with self._lock:
            self._pair_id = ""
            self._poll_key = ""
            self._url = ""
            self._image = ""
            self._modules = 0
            self._quiet = 0
            self._expires = 0
            self._state = state

    def reset(self) -> None:
        """Forget it entirely. Tests, and service shutdown."""
        self.forget("idle")

    # ── what the API hands out ───────────────────────────────────────────
    def snapshot(self) -> dict:
        """UI-safe. NO POLL KEY, and no code — see the module note.

        The pairing id and the address are here because they are on the
        screen already: the square holds both, and an engineer whose camera
        will not read it types the address instead.
        """
        with self._lock:
            return {
                "state": self._state,
                "pairId": self._pair_id,
                "url": self._url,
                "image": self._image,
                "modules": self._modules,
                "quiet": self._quiet,
                "pollAfter": self._poll_after,
            }


PAIR = Pairing()


def _beat(value) -> float:
    """How long the window waits between polls, whatever the service said."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_POLL
    if not math.isfinite(seconds):
        return DEFAULT_POLL
    return min(max(seconds, MIN_POLL), MAX_POLL)
