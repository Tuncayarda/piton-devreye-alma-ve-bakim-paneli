#!/usr/bin/env python3
"""This installation's name for itself.

A random identifier, made once and kept, so that a grant can be tied to the
computer that asked for it: the service signs the id back, the panel checks
it is its own, and a grant intended for one machine is refused on another.

WHAT IT IS NOT. It is not a secret, it identifies nothing about the customer,
and possessing it grants nothing — a grant also needs the code, and a
signature the panel will only take from the service. It is a random number
in a file, and it is the ONLY thing this feature leaves on the customer's
disk. That was the requirement the service key could not meet: the file it
needs is the thing that opens the door, so a copy left behind is a permanent
way in. A copy of this file left behind is a random number.

Rewritten rather than raised on if it goes missing or unreadable, the way the
ADB list is (see `panel.adb.pool`): the worst a fresh id costs is that the
service counts one more activation.
"""
from __future__ import annotations

import json
import threading
import uuid

from .. import settings

FORMAT = 1
_LOCK = threading.Lock()
_CACHED = ""


def install_id() -> str:
    """The identifier, read from disk the first time and kept in memory."""
    global _CACHED
    with _LOCK:
        if _CACHED:
            return _CACHED
        _CACHED = _read() or _create()
        return _CACHED


def forget() -> None:
    """Drop the cached value. Tests, and a project switch that moves the
    data directory out from under it."""
    global _CACHED
    with _LOCK:
        _CACHED = ""


def _read() -> str:
    path = settings.remote_session_file()
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    if not isinstance(body, dict) or body.get("format") != FORMAT:
        return ""
    value = body.get("installId")
    return value if isinstance(value, str) and value else ""


def _create() -> str:
    value = str(uuid.uuid4())
    path = settings.remote_session_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"format": FORMAT, "installId": value}, indent=2),
            encoding="utf-8")
        temporary.replace(path)         # never leave a half-written file
    except OSError:
        # An unwritable data directory means a new id every run. The feature
        # still works; the service simply sees each run as a new machine.
        pass
    return value
