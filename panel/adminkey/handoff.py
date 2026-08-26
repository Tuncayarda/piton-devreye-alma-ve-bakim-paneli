#!/usr/bin/env python3
"""Getting the build secret past the system's password box.

THE ENVIRONMENT DOES NOT SURVIVE THE PROMPT. The panel restarts itself
elevated through the operating system's own dialog — osascript on macOS,
pkexec on Linux — and every one of those builds a fresh command line under a
fresh environment. A secret exported in the shell is therefore gone in the
process that actually opens: the panel comes up in field mode and the
variable the user set looks as though it were ignored.

Putting the value on that command line is not the answer. A command line is
public — `ps` shows it to every account on the machine — and the secret is
the one value that must never be there. So what travels is a PATH:

    the unprivileged process    writes the secret to a file only its own
                                user can read, and names the file in the
                                command line
    the elevated process        reads it, DELETES IT, and puts the value
                                back in its own environment

The file lives in the user's private temporary directory, is created 0600 by
`mkstemp`, and exists for the second or two between the password box and the
new process reading it.

NOT IN A PACKAGED BUILD, either end. A frozen build takes its key material
from the build stamp and nothing else (`secret.build_secret`), so there is
nothing to hand over and nothing to accept: a file arriving at a customer's
package changes nothing about what it will open.
"""
from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path

# Named in the command line the elevation builds (see
# panel.elevation.privileges.CARRIED). The PATH is public; the file is not.
FILE_VAR = "DAP_ADMIN_KEY_SECRET_FILE"
SECRET_VAR = "DAP_ADMIN_KEY_SECRET"


def stash() -> str:
    """Write the secret where the elevated process can pick it up.

    Returns the path, or "" when there is nothing to hand over — which is
    the normal case: no secret in the environment, a packaged build, or a
    platform where the handover cannot happen at all.

    WINDOWS IS THAT PLATFORM. `runas` takes no environment of ours, so the
    path would never reach the new process (see
    `panel.elevation.privileges.CARRIED`) and the file would sit in the
    temporary directory holding a secret nobody ever came for. Writing it
    would be all of the cost and none of the point; `app.py` tells the user
    to set the variable in an administrator shell instead.
    """
    from .. import settings                               # noqa: PLC0415
    value = os.environ.get(SECRET_VAR, "").strip()
    if settings.FROZEN or not value or platform.system() == "Windows":
        return ""
    try:
        handle, path = tempfile.mkstemp(prefix="dabp-key-", suffix=".txt")
    except OSError:
        return ""
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as target:
            target.write(value)
    except OSError:
        _remove(path)
        return ""
    return path


def claim() -> None:
    """Take the secret handed over by the process that elevated us.

    Called once at start-up, before anything asks what this build can do.
    The file is removed whether or not it could be read: it has done its
    job either way, and a secret left in a temporary directory is exactly
    what this is trying not to leave behind.
    """
    from .. import settings                               # noqa: PLC0415
    path = os.environ.pop(FILE_VAR, "").strip()
    if not path:
        return
    value = ""
    try:
        if not settings.FROZEN:
            value = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        value = ""
    _remove(path)
    if value:
        os.environ[SECRET_VAR] = value


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
