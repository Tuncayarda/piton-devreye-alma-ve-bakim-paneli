#!/usr/bin/env python3
"""The grant: what is asked, and every reason an answer is refused.

A CHALLENGE, NOT A DOWNLOAD, and that is the whole design. Fetching a fixed
something from a URL and believing it would last exactly as long as it took
one customer to save the something and serve it from their own machine — at
which point the panel would be back to a permanent admin file on a customer's
computer, which is the arrangement this exists to replace.

So the panel speaks first. It sends a NONCE it has just invented, the service
signs that nonce, and the panel checks the signature against a key it was
built with. A recording of yesterday's answer carries yesterday's nonce; a
server run by somebody else cannot produce a signature at all. Neither replay
nor a substituted host gets anywhere, and no secret has to sit on the
customer's disk for any of it.

WHAT IS NOT CHECKED, AND WHY. `issuedAt` is carried for the operator's
listing and is NOT validated. A wall clock set wrongly is ordinary in the
field — a machine that has been off for a month, a BIOS battery, a
time zone typed in by hand — and refusing a valid grant over it would be an
outage with no attack behind it. Nothing is gained by checking it: replay is
already answered by the nonce, and how long a grant lasts is measured with
`clock.monotonic()` from the moment it arrived, which no clock setting can
move (see `panel.remotekey.watcher`).
"""
from __future__ import annotations

import hmac
import json
from dataclasses import dataclass

from . import verify

VERSION = 1

# What the signature is over. The prefix is DOMAIN SEPARATION: the service
# signs nothing else today, but a key that only ever signs bytes beginning
# "dabp-remote-grant-v1" cannot be talked into signing something from
# elsewhere that happens to be handed to it.
PREFIX = b"dabp-remote-grant-v1\x00"

# The longest a single grant may hold the door, whatever the service says.
# The service asks for twelve seconds today. This is not a second opinion
# about the right number; it is a ceiling, so that a mistake there — a unit
# confused, a field left as a default — cannot leave a customer package in
# admin mode for an afternoon.
#
# NINETY, BECAUSE THE BEAT IS A THIRD OF IT. The panel asks again every
# ttl/3 (see panel.remotekey.watcher), so the ceiling is also the ceiling on
# how rarely it may ask: at thirty it could never ask less often than every
# ten seconds however long a grant the service issued. The price is that a
# service which goes wrong holds the door for up to ninety seconds after the
# link has gone rather than thirty. Ninety seconds is still nobody's
# afternoon, and it is the deadline that ends the mode either way.
MAX_TTL = 90.0

# Crockford's base32: the digits and the letters, less I, L, O and U. The
# first three because they are read back as 1, 1 and 0 over a telephone, and
# U because it turns short codes into words nobody wants to dictate.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8
# Typed in by somebody reading a screen out loud, so what they meant is
# accepted: the letters that were left out of the alphabet are the ones that
# get typed anyway.
CONFUSIONS = {"I": "1", "L": "1", "O": "0", "U": "V"}
SEPARATORS = " -_.\t "


@dataclass(frozen=True)
class Grant:
    """A signed permission to be in admin mode, for the next few seconds."""

    label: str
    ttl: float
    session: str


def normalise(text) -> str | None:
    """The code as the service knows it, or None if that is not a code.

    Separators go, case does not matter, and the four letters the alphabet
    leaves out are read as what the person meant. Anything still outside the
    alphabet afterwards is a REFUSAL rather than something to drop: quietly
    discarding a stray character turns a mistyped code into a differently
    mistyped code, and the operator is left rereading a correct screen.
    """
    if not isinstance(text, str):
        return None
    cleaned = "".join(character for character in text.strip().upper()
                      if character not in SEPARATORS)
    cleaned = "".join(CONFUSIONS.get(character, character)
                      for character in cleaned)
    if len(cleaned) != CODE_LENGTH:
        return None
    if any(character not in ALPHABET for character in cleaned):
        return None
    return cleaned


def find(text) -> str | None:
    """The first code in `text`, or None. For what somebody pasted.

    A code copied out of a message rarely arrives alone: a word in front of
    it, a trailing newline, a colon. The whole string is tried
    first, then each word in it, and `normalise` decides in both cases, so
    what counts as a code is still answered in exactly one place.
    """
    if not isinstance(text, str):
        return None
    direct = normalise(text)
    if direct is not None:
        return direct
    for word in text.split():
        found = normalise(word)
        if found is not None:
            return found
    return None


def display(code: str) -> str:
    """`K7M29QX4` as `K7M2-9QX4`, which is how it is read out."""
    half = CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}" if len(code) == CODE_LENGTH else code


def mask(code: str) -> str:
    """Enough of the code to recognise the session by, on a screen that may
    be looked at by somebody who was not given it."""
    return f"{code[:2]}…{code[-2:]}" if len(code) == CODE_LENGTH else ""


def check(payload_text, signature_text, *, nonce: bytes, install_id: str,
          edition: str) -> tuple[Grant | None, str]:
    """Read one answer from the service. `(grant, "")`, or `(None, reason)`.

    THE SIGNATURE IS CHECKED FIRST, over the bytes as they arrived, and the
    JSON is only parsed afterwards. Verifying a re-serialised payload would
    mean the panel decides what was signed, and any disagreement between two
    JSON writers about spacing or key order becomes a security question. This
    way there is nothing to disagree about.
    """
    payload = verify.decode(payload_text)
    signature = verify.decode(signature_text)
    if payload is None or signature is None:
        return None, "malformed"
    if not verify.verify(PREFIX + payload, signature):
        return None, "untrusted"

    try:
        body = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, "malformed"
    if not isinstance(body, dict):
        return None, "malformed"
    if body.get("v") != VERSION:
        return None, "version"

    # The nonce. Everything else on this list guards against a mistake; this
    # one guards against a recording, and it is the reason the exchange is
    # worth making at all.
    answered = verify.decode(body.get("nonce"))
    if answered is None or not hmac.compare_digest(answered, nonce):
        return None, "nonce"
    if body.get("installId") != install_id:
        return None, "install"

    granted = body.get("edition")
    if granted != "*" and granted != edition:
        return None, "edition"

    ttl = body.get("ttl")
    if not isinstance(ttl, (int, float)) or isinstance(ttl, bool) or ttl <= 0:
        return None, "malformed"

    label = body.get("label")
    session = body.get("session")
    return Grant(label=label if isinstance(label, str) else "",
                 ttl=min(float(ttl), MAX_TTL),
                 session=session if isinstance(session, str) else ""), ""
