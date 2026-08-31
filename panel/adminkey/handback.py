#!/usr/bin/env python3
"""Reading the stick from the operator's own session, when root may not.

macOS gates removable volumes behind a privacy permission, and that
permission belongs to A PERSON and to the application they launched. The
panel is neither by the time it looks: it restarts itself elevated, and the
elevated process is detached from whatever started it and is root. So
`/Volumes` lists the stick, every file on it answers EPERM, and the system
does not even ask — on that side of the password box there is nobody to ask.
A key in the slot then looks exactly like an empty slot, which is how an
afternoon went.

`panel.system.files` already had the answer, for the file picker, and it is
the same answer here: HAND THE WORK BACK DOWN to the person at the keyboard.
`launchctl asuser` puts the command in their GUI session, `sudo -H -u` drops
the root identity, and the read happens with their permissions — which are
the permissions the volume is actually asking for.

NOTHING IS GRANTED BY THIS. It reads what that user could read by opening
the file in Finder, on a volume they plugged in themselves; what decides
anything is still the digest check in `secret.py`, on the same bytes.

AND IT HAS TO GO FIRST, which is the part that cost the afternoon. The
obvious shape — try the direct read, hand back when it is refused — is the
one shape that does not work. Measured on macOS 26, four runs in a row:
whichever side asks first decides for the whole process tree. Ask through
the operator's session and every read keeps working, including after this
process has been refused for itself. Let this process be refused first and
the refusal is inherited by everything it starts: the same `ls` that
succeeded a minute earlier comes back "Operation not permitted". So
`keyfile.read` asks `applicable()` BEFORE it touches the volume, and the
direct read is what happens where there is nobody to hand the work to.
"""
from __future__ import annotations

import os
import platform
import subprocess

from ..system.files import as_console_user

# A command that is only being asked to read a few hundred kilobytes off a
# USB stick. Long enough for a slow one, short enough that the watcher's
# thread cannot be parked on it.
TIMEOUT = 15.0


def applicable() -> bool:
    """Is there another session to hand the read down to?

    Asked before anything is spawned: on Linux and Windows the refusal means
    something else, and running the same command again as the same user is
    just a process spent to be told the same thing.
    """
    return platform.system() == "Darwin" and os.geteuid() == 0


def names(folder) -> list[str] | None:
    """What is in this directory, or None if that could not be found out."""
    listed = _run(["/bin/ls", "-1", str(folder)])
    if listed is None:
        return None
    return [line for line in listed.decode("utf-8", "replace").splitlines()
            if line]


def read_bytes(path, limit: int) -> bytes | None:
    """The first `limit` bytes of this file, or None if it could not be read.

    Capped at the source rather than after the fact: what is on the other end
    is removable media somebody else wrote, and a process is a poor place to
    discover that it holds four gigabytes. One byte over the limit is
    returned as well, so the caller can tell "too big" from "exactly full".
    """
    return _run(["/usr/bin/head", "-c", str(int(limit) + 1), str(path)])


def _run(command: list[str]) -> bytes | None:
    if not applicable():
        return None
    try:
        done = subprocess.run(as_console_user(command), capture_output=True,
                              timeout=TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None
