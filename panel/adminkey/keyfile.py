#!/usr/bin/env python3
"""The file on the stick: how it is read, and how a key is written.

READING IS DEFENSIVE, ALWAYS. The stick comes from outside the machine and
whatever is on it was put there by someone else. Nothing here raises: a
malformed, truncated, enormous or entirely unrelated file is simply "not a
service key". This runs on the watcher's thread every couple of seconds, and
an exception there would take the watcher down and leave the panel believing
no key had ever been inserted.

Named `.json`, not `.key`: `.gitignore` ignores `*.key` and the repository
checks in CI warn on a tracked one, so a test fixture would silently vanish
or raise a false alarm.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import handback
from . import secret as key_secret

FILENAME = "dabp-admin-key.json"
FORMAT = "dabp-admin-key"
VERSION = 1
# The pack folder beside the key file (see `pack.py`).
PACK_DIR = "dabp-projects"
# A key file is a few hundred bytes. The cap is not about this file: it is
# about never reading an unbounded amount from removable media handed to us
# by someone else. Same reasoning, same size as `settings.BODY_LIMIT`.
MAX_BYTES = 64 * 1024


@dataclass(frozen=True)
class KeyFile:
    """What was found on a volume. `recognised` is the only thing that
    grants anything; `label` and `issued` are the operator's own notes and
    are never checked against anything.

    `proof` is K itself — the value the stick carries — and it is kept, on a
    RECOGNISED key only, because it is also the key that opens the sealed
    device lists in the package (see `vault.py`). It used to be dropped the
    moment it had been verified, which was right while verifying was all it
    was for. Nothing widens here: the bytes were already in this process,
    read from a volume the operator has physically inserted.
    """

    path: Path
    recognised: bool
    label: str = ""
    issued: str = ""
    reason: str = ""
    proof: bytes = b""


def path_on(volume: Path) -> Path:
    return Path(volume) / FILENAME


def read(volume) -> KeyFile | None:
    """The key file on this volume, or None if there is not one there.

    A KeyFile with `recognised` False means a file WAS found and rejected —
    worth telling the user about, because a stick that looks right and is not
    is otherwise indistinguishable from no stick at all.
    """
    path = path_on(volume)
    # THE ORDER HERE IS NOT A PREFERENCE, it is the whole difference between
    # a key that works and a key that is never seen. Where the operator's
    # session has to be borrowed at all (macOS, elevated — see `handback`),
    # it is borrowed FIRST, before this process has touched the volume.
    #
    # Measured on macOS 26, four runs in a row: whichever side asks first
    # decides for the whole process tree. Ask through the operator's session
    # and the reads keep working — even after this process is refused. Let
    # this process be refused first and the refusal is inherited: the same
    # `ls` that worked a minute earlier comes back "Operation not
    # permitted". Trying the direct read first and handing back on failure
    # is therefore the one arrangement that cannot work.
    if handback.applicable():
        found = _handed_back(volume, path)
        if found is _NO_KEY:
            return None
        if found is not None:
            return _from_bytes(path, found)

    try:
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_BYTES:
            return KeyFile(path, False, reason="oversize")
        raw = path.read_text(encoding="utf-8", errors="strict")
    except PermissionError:
        # NOT ALLOWED TO LOOK, which is not the same as nothing being there.
        # Swallowed, an inserted key looks exactly like an empty slot — the
        # panel sat there saying nothing at all, and that is the bug this
        # reason exists for.
        return KeyFile(path, False, reason="denied")
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return _parsed(path, raw)


def _from_bytes(path: Path, data: bytes) -> KeyFile | None:
    if len(data) > MAX_BYTES:
        return KeyFile(path, False, reason="oversize")
    try:
        return _parsed(path, data.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def _parsed(path: Path, raw: str) -> KeyFile | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return KeyFile(path, False, reason="malformed")
    if not isinstance(data, dict):
        return KeyFile(path, False, reason="malformed")
    if data.get("format") != FORMAT:
        return KeyFile(path, False, reason="malformed")
    # The version is checked BEFORE anything else is trusted: a later format
    # may mean something different by the same field names, and guessing at
    # it is how a checked value quietly becomes an unchecked one.
    if data.get("version") != VERSION:
        return KeyFile(path, False, reason="version")

    proof = data.get("proof")
    if not isinstance(proof, str):
        return KeyFile(path, False, reason="malformed")
    recognised = key_secret.verify(proof)
    return KeyFile(
        path,
        recognised,
        label=_text(data.get("label")),
        issued=_text(data.get("issued")),
        reason="" if recognised else "unrecognised",
        # Only from a key that passed. An unrecognised file's bytes are
        # somebody else's guess and must not be carried around as if they
        # were key material.
        proof=(key_secret.decode(proof) or b"") if recognised else b"",
    )


# "There is no key file on this volume", told apart from "there is one and
# it could not be read". Without the distinction every unrelated USB stick
# on a machine that refuses the panel would be reported as a key nobody was
# allowed to read.
_NO_KEY = object()


def _handed_back(volume, path):
    """The key file read from the operator's session: bytes, `_NO_KEY`, or
    None when even that could not be done.

    The read is tried before the listing, and that way round on purpose:
    this runs every couple of seconds for as long as the panel is open, and
    the case worth spending nothing on is the one where the key is where it
    should be. The listing is only needed to answer a question the read has
    already answered when it succeeds.
    """
    # One byte over the cap comes back too, so an oversize file is reported
    # as oversize rather than parsed.
    data = handback.read_bytes(path, MAX_BYTES)
    if data is not None:
        return data
    # Nothing came back. Was there a file at all? Without asking, every
    # unrelated stick in the building would be reported as a key nobody was
    # allowed to read.
    listing = handback.names(volume)
    if listing is not None and FILENAME not in listing:
        return _NO_KEY
    return None


def write(volume, label: str = "") -> Path:
    """Mint a service key onto this volume. Needs the build secret.

    Written through a temporary file and renamed into place: a stick pulled
    the moment after the button is pressed must hold either the whole key or
    nothing, never half of one. `fsync` before the rename because the rename
    is only atomic with respect to data that has actually reached the device.
    """
    if not key_secret.can_write():
        raise RuntimeError("this build carries no key secret")
    target = path_on(volume)
    body = {
        "format": FORMAT,
        "version": VERSION,
        "kdf": "pbkdf2-hmac-sha256",
        "iterations": key_secret.ITERATIONS,
        "proof": key_secret.mint(),
        "issued": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "label": _text(label)[:120],
        "pack": PACK_DIR,
    }
    temporary = target.with_name(target.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(body, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    # From source, remember what was written: a source tree has no stamp, so
    # without this the panel would not recognise the very stick it has just
    # made. No effect in a packaged build — see secret.remember.
    key_secret.remember(
        key_secret.digest(base64.b64decode(body["proof"])))
    return target


def _text(value) -> str:
    return str(value) if isinstance(value, (str, int)) else ""
