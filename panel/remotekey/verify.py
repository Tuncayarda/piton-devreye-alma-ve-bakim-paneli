#!/usr/bin/env python3
"""Whose signature this package accepts, and where it asks for one.

THE TRUST ANCHOR IS A PUBLIC KEY, IN THE SOURCE, IN PLAIN SIGHT. That is the
whole difference between this and the service key: `panel.adminkey.secret`
stamps a DIGEST into the build because the value behind it must never ship,
and the stamping drags a build secret, a CI variable and a self-test through
`dabp.spec` with it. A public key is public. It goes in the file, it is read
in a review, it is identical in a source run and in a shipped package, and
the packaging touches none of it.

A TUPLE, NOT A VALUE, for the same reason `accepted_digests()` is a list: the
day the signing key has to be replaced, the new one is added, a release goes
out, and the old one is removed in the release after that. Rotation with an
overlap, rather than a flag day on which every installed package stops
working at once.

The private half lives on the grant service and nowhere else — a separate
private repository, deployed to Cloudflare, holding it as a secret. Nothing
in this repository can sign anything, which is the point: a customer package
that could mint its own grant would be a package that grants itself admin.
"""
from __future__ import annotations

import base64
import os

from .. import settings
from . import ed25519

# The service the panel asks. FIXED AND BUILT IN, so the operator reads eight
# characters down the telephone instead of a URL — and so a customer cannot
# be talked into pointing the panel somewhere else. Pointing it elsewhere
# would gain nothing anyway (the signature is what is checked, not the host),
# but a control that changes nothing is worse than no control.
SERVICE_URL = "https://dabp-key.piton-dabp.workers.dev"

# Ed25519 public keys, base64url, 32 bytes each. EMPTY UNTIL THE SERVICE IS
# DEPLOYED: with no key the feature reports itself unavailable and the UI
# never offers it, which is the correct behaviour for a build that cannot
# check anything.
TRUSTED_KEYS: tuple[str, ...] = (
    "YiTKI1DYCjAQeRWEDFPqcgQMm_AfLfPnZIm6q_40Iuk",              # v1, 2026-08-29
)

# Source runs only, and the reason is development against a Worker of one's
# own. A frozen package takes the service and the keys it was built with;
# nothing in the environment may add to what a shipped build accepts.
KEYS_ENV = "DAP_REMOTE_PUBLIC_KEYS"
URL_ENV = "DAP_REMOTE_SERVICE_URL"


def service_url() -> str:
    if not settings.FROZEN:
        override = os.environ.get(URL_ENV, "").strip()
        if override:
            return override
    return SERVICE_URL


def accepted_keys() -> tuple[bytes, ...]:
    """Every public key this run will accept a grant from, decoded.

    A key that does not decode to 32 bytes is DROPPED rather than raised on:
    a typo in the tuple must not stop the panel opening, and the failure it
    causes — "no remote session available" — is the same one an empty tuple
    causes and is reported the same way.
    """
    listed = list(TRUSTED_KEYS)
    if not settings.FROZEN:
        listed.extend(part.strip()
                      for part in os.environ.get(KEYS_ENV, "").split(",")
                      if part.strip())
    keys = []
    for text in listed:
        decoded = decode(text)
        if decoded is not None and len(decoded) == 32 and decoded not in keys:
            keys.append(decoded)
    return tuple(keys)


def available() -> bool:
    """Can this build check a grant at all?

    False for a package cut before the service existed. `/api/edition`
    reports it so the window can leave the offer out entirely rather than
    show a door that opens on nothing.
    """
    return bool(accepted_keys())


def verify(message: bytes, signature: bytes) -> bool:
    """True if any accepted key signed `message`."""
    return any(ed25519.verify(key, message, signature)
               for key in accepted_keys())


def decode(text: str) -> bytes | None:
    """base64url in, bytes out, None for anything that is not that.

    Padding is added rather than required: the service is JavaScript, and
    JavaScript's base64url conventionally omits it.
    """
    if not isinstance(text, str) or not text:
        return None
    padded = text.strip() + "=" * (-len(text.strip()) % 4)
    # Translated by hand and decoded with the standard alphabet, because
    # `urlsafe_b64decode` takes no `validate` and STRICT IS THE POINT: the
    # default silently DROPS characters outside the alphabet, which turns
    # "this is not base64 at all" into a short byte string and then into
    # "the signature did not verify" — the wrong thing to tell somebody
    # whose service is answering with an error page.
    standard = padded.replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(standard, validate=True)
    except (ValueError, TypeError):
        return None


def encode(raw: bytes) -> str:
    """bytes out as base64url without padding, the way the service reads it."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
