#!/usr/bin/env python3
"""The key material, and the one-way step between its two halves.

The problem this solves: a customer's package must be able to RECOGNISE the
service key without being able to MAKE one. If both builds carried the same
value, anyone with a customer package could read it out and write their own
stick — and the whole point of the stick is that the customer cannot.

So there are two values and a one-way function between them:

    S   the build secret, held by the organisation and by the `admin`
        package alone. Never ships to a customer.
    K   = pbkdf2_hmac(sha256, S, SALT, ITERATIONS)      — what is WRITTEN
        onto the stick.
    D   = sha256(K)                                     — what a CUSTOMER
        package is built with, and all it is built with.

A customer package holds D. Verifying a stick is `sha256(K') == D`, which is
fast — the watcher does it every couple of seconds. Going the other way is
not: from D there is no route back to K, so a package cannot mint a stick,
and from K there is no route back to S, so a captured stick does not yield
the secret that every edition and every version share.

The slow KDF earns its keep on that second step only. It is why S survives a
lost stick.

WHAT THIS DOES NOT CLAIM. The stick is a physical key, and a copy of it is
the key: every stick is byte-identical, and there is no per-stick
revocation. Withdrawing one means rotating S and cutting new builds —
which is why the digest is a LIST rather than a single value, so the old and
the new secret can both be honoured while the field is updated. Nor is any
of this proof against someone editing the package itself; it is the line
between a customer using their own product and a customer wandering into
another customer's. That is the line that was asked for.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from pathlib import Path

# Fixed, and part of the format: it is versioned by name rather than stored
# per key, so a stick carries no tunable a forger could turn down.
SALT = b"dabp-admin-key-v1"
ITERATIONS = 600_000
PROOF_BYTES = 32


def derive(secret: bytes) -> bytes:
    """S -> K. The slow half; called when a stick is written, never on read."""
    return hashlib.pbkdf2_hmac("sha256", secret, SALT, ITERATIONS,
                               dklen=PROOF_BYTES)


def digest(proof: bytes) -> str:
    """K -> D. The fast half; called on every poll."""
    return hashlib.sha256(proof).hexdigest()


# S -> D, remembered. `derive` is 600 000 rounds of PBKDF2 — a quarter of a
# second — and `accepted_digests` runs it on the path of EVERY read of the
# stick, which is every couple of seconds for as long as the panel is open.
# Working it out afresh each time turned a background check into a busy
# loop. A process sees one secret, or a handful under test.
_DERIVED: dict[bytes, str] = {}


def _digest_of(secret: bytes) -> str:
    known = _DERIVED.get(secret)
    if known is None:
        if len(_DERIVED) > 8:
            _DERIVED.clear()
        known = _DERIVED[secret] = digest(derive(secret))
    return known


def _stamped(name: str, default=None):
    from .. import settings                               # noqa: PLC0415
    if not settings.FROZEN:
        return default
    try:
        from ..editions import _stamp                     # noqa: PLC0415
    except ImportError:
        return default
    return getattr(_stamp, name, default)


# S, kept in the checkout as a file — the licence-file shape of the same
# development convenience the environment variable is.
#
# WHY A FILE AS WELL. An environment variable is copied into a process when
# it STARTS. Exporting one in a shell while the panel is open reaches
# nothing: the running process has its own copy and no way to hear about a
# later export. So switching admin mode on meant restarting, through the
# password box, every time. A file is asked about at the moment the question
# is asked — drop it in and the panel can be raised, delete it and the mode
# goes the way it goes when the stick is pulled (`watcher._apply_mode`).
#
# It also survives the privilege prompt for free, which the variable needs a
# whole handover to do (see `handoff`): the elevated process is started in
# this same directory and simply reads the same file.
#
# SOURCE RUNS ONLY, exactly like the digests below. A FROZEN BUILD NEVER
# READS IT: what a package can do is decided at build time, and no file on a
# customer's disk may add to it — least of all this one, which would
# otherwise be "mint service keys for every other customer" in a text file.
SECRET_FILE = ".adminkey-secret"
# One line of text. The cap is not about this file; it is about never
# reading an unbounded amount because of a name someone put in a folder.
SECRET_MAX_BYTES = 8 * 1024


def _secret_file() -> Path:
    return _dev_dir() / SECRET_FILE


def build_secret() -> bytes | None:
    """S, when this run holds it. Never a shipped package.

    Three places, in order: the build stamp (frozen builds, and nothing is
    stamped with the secret any more — see `dabp.spec`), the environment,
    and a file in the checkout. The last two are source-run conveniences so
    the flow can be exercised without cutting a package; a frozen build
    reads the stamp and only the stamp.
    """
    stamped = _stamped("ADMIN_KEY_SECRET")
    if stamped:
        return _decode(stamped)
    from .. import settings                               # noqa: PLC0415
    if settings.FROZEN:
        return None
    raw = os.environ.get("DAP_ADMIN_KEY_SECRET", "")
    if raw:
        return raw.encode("utf-8")
    return _file_secret()


def _file_secret() -> bytes | None:
    """Whatever `.adminkey-secret` holds right now, or None.

    Read on every ask rather than cached, because the whole point is that it
    can appear and disappear while the panel is open. Never raises: a
    directory of that name, a file being written as it is read, or one full
    of binary is simply "no secret here".
    """
    path = _secret_file()
    try:
        if path.stat().st_size > SECRET_MAX_BYTES:
            return None
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return value.encode("utf-8") if value else None


# Digests a service key written ON THIS COMPUTER was made with. SOURCE RUNS
# ONLY, and it exists because of a trap that cost real time:
#
# A packaged build knows which key to accept because the digest is stamped
# into it. A source tree has no stamp, so a source run recognises NOTHING —
# plug the stick in and the panel sits there as if the slot were empty. The
# answer used to be "export the secret every time", which is a poor answer
# twice over: it has to be remembered, and it does not survive the privilege
# prompt (see app.py).
#
# So writing a key from source records what it wrote. Afterwards every
# source run of every edition FROM THIS CHECKOUT recognises that stick,
# whoever the run belongs to — which matters, because the panel restarts
# itself as root and root is not the person who wrote the key.
#
# It grants nothing on its own — a digest cannot mint a key, and anyone who
# can write this file can edit the source tree it belongs to. A FROZEN BUILD
# NEVER READS IT: what a package accepts is decided at build time and
# nothing on disk may add to it.
REMEMBERED = ".adminkey-dev.json"
# Where that file goes, for the tests and for nothing else. A frozen build
# never reads any of this, and a source run already takes digests from
# DAP_ADMIN_KEY_DIGESTS, so this adds no way in that was not there.
STORE = "DAP_ADMIN_KEY_STORE"


def _remembered_file() -> Path:
    return _dev_dir() / REMEMBERED


def _dev_dir() -> Path:
    """Where the development files live — the digests, and the secret.

    IN THE CHECKOUT, not in the settings directory, AND THE ELEVATION IS
    WHY. The settings directory hangs off HOME, and the panel restarts
    itself as another user: pkexec hands the process root's own HOME and
    Windows runas another profile entirely, while `tools/key_digest.py
    --remember` is typed by the person at the keyboard, in their own HOME.
    Whether the two meet is then a property of the elevation tool — macOS's
    osascript happens to pass HOME through, polkit does not — and a key that
    is recognised on one operating system and silently ignored on the next
    is not something to leave to chance.

    The checkout is the one place every one of those processes agrees on:
    the elevated run is started from it (see
    `panel.elevation.privileges.elevation_plan`) and it is the tree these
    files belong to anyway. They grant nothing that editing this tree would
    not already grant.
    """
    from .. import settings                               # noqa: PLC0415
    override = os.environ.get(STORE)
    return Path(override).expanduser() if override else settings.ROOT


def remembered_digests() -> tuple[str, ...]:
    from .. import settings                               # noqa: PLC0415
    if settings.FROZEN:
        return ()
    try:
        data = json.loads(_remembered_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    if not isinstance(data, dict):
        return ()
    return tuple(str(value).strip().lower()
                 for value in data.get("digests") or []
                 if _is_digest(value))


def remember(value: str) -> None:
    """Record a digest so later source runs recognise the same stick."""
    from .. import settings                               # noqa: PLC0415
    if settings.FROZEN or not _is_digest(value):
        return
    kept = list(dict.fromkeys([*remembered_digests(), value.strip().lower()]))
    path = _remembered_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"digests": kept}, indent=2),
                             encoding="utf-8")
        temporary.replace(path)     # never leave a half-written file
    except OSError:
        pass                        # a read-only tree must not break a write


def _is_digest(value) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}",
                             str(value or "").strip().lower()))


def accepted_digests() -> tuple[str, ...]:
    """Every D this package recognises.

    Usually one. Two during a rotation, and more on a developer's machine
    where keys have been written from source.
    """
    stamped = _stamped("ADMIN_KEY_DIGESTS") or ()
    values = [str(value).strip().lower() for value in stamped if value]
    if not values:
        from .. import settings                           # noqa: PLC0415
        if not settings.FROZEN:
            values = [part.strip().lower() for part
                      in os.environ.get("DAP_ADMIN_KEY_DIGESTS", "").split(",")
                      if part.strip()]
            values.extend(remembered_digests())
    # A run that holds the secret rather than a digest list — a source run
    # writing keys — can work its own digest out.
    secret = build_secret()
    if secret is not None:
        values.append(_digest_of(secret))
    return tuple(dict.fromkeys(values))


def usable() -> bool:
    """Can this package recognise a service key at all?

    False in a build cut without key material — a fork, or a local build with
    DAP_ALLOW_NO_ADMIN_KEY. The panel still runs; it says the key cannot be
    used rather than looking as though the stick were not recognised.
    """
    return bool(accepted_digests())


def can_write() -> bool:
    """Can this package MINT a service key? Only with S in hand."""
    return build_secret() is not None


def mint() -> str:
    """K for this build's secret, base64, ready to be written onto a stick."""
    secret = build_secret()
    if secret is None:
        raise RuntimeError("this build carries no key secret")
    return base64.b64encode(derive(secret)).decode("ascii")


def verify(proof_text: str) -> bool:
    """Is this the value from a genuine service key?

    Compared with `compare_digest` rather than `==`: both sides are hex of
    the same length here, so the timing channel is narrow, but a constant
    time comparison of a secret-derived value costs nothing and does not
    have to be reasoned about again later.
    """
    proof = _decode(proof_text)
    if proof is None or len(proof) != PROOF_BYTES:
        return False
    seen = digest(proof)
    return any(hmac.compare_digest(seen, known)
               for known in accepted_digests())


def decode(value) -> bytes | None:
    """Base64 in, bytes out, None for anything that is not. Public because
    `keyfile` decodes the same proof it hands here to be verified."""
    return _decode(value)


def content_key() -> bytes | None:
    """K, when this run can work it out on its own. Not from a stick.

    THIS IS THE SEALING KEY (see `vault.py`), and there are only two ways to
    hold it without one being inserted:

      * a run that holds S can derive it — a source run with the secret
        exported or dropped in `.adminkey-secret`, which is where keys are
        written and where the sealing at build time is done;
      * nothing else. A shipped package holds D and D alone.

    The stick's own copy comes from `keyfile.KeyFile.proof` and is carried by
    the watcher; this function deliberately does not reach for it, so that
    "what this build can open by itself" stays a separate question from "what
    is plugged in right now".
    """
    secret = build_secret()
    if secret is None:
        return None
    return _derived_key(secret)


# `derive` is 600 000 rounds of PBKDF2. The sealed maps are opened on the
# path of entering admin mode, not once per file, but a source run switching
# projects would still pay it repeatedly. Same cache shape as `_DERIVED`.
_KEYS: dict[bytes, bytes] = {}


def _derived_key(secret: bytes) -> bytes:
    known = _KEYS.get(secret)
    if known is None:
        if len(_KEYS) > 8:
            _KEYS.clear()
        known = _KEYS[secret] = derive(secret)
    return known


def _decode(value) -> bytes | None:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    try:
        return base64.b64decode(str(value), validate=True)
    except (binascii.Error, ValueError, TypeError):
        return None
