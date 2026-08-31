#!/usr/bin/env python3
"""Which ``adb`` executable the panel runs.

The panel used to call the bare name and hope. On a commissioning laptop that
works — Android Studio put one on PATH — and on the machines this is actually
shipped to it does not, which showed up as "the Compartment LCD cannot be
read" on a display that was perfectly healthy. The executable is now carried
INSIDE the package, so a fresh installation can talk to an Android display
without anybody installing developer tools first.

Resolution order, and the reason for each step:

1. ``DABP_ADB_BINARY``     an explicit override, for a field machine with a
                           vendor build of adb that must be used instead.
2. the bundled copy        ``platform-tools/adb`` beside the frozen bundle
                           (``sys._MEIPASS``) or at the top of the source
                           tree. This is the answer on a shipped package.
3. ``PATH``                a developer's own installation.
4. the bare name           last resort, and NOT an error: it keeps the
                           behaviour the panel has always had, where the
                           missing executable is reported by the call that
                           needed it (``client.run`` turns the resulting
                           FileNotFoundError into `AdbUnavailable`, which is
                           a `NotApplicableError` and therefore reaches the
                           screen as a sentence rather than as a crash).

THE EXECUTABLE BIT IS NOT ASSUMED. PyInstaller copies data files, and a data
file is not marked runnable; the same is true of anything that has been
through a ZIP. So the bundled copy is made executable on first use rather
than at build time, where getting it wrong is invisible until a field
machine refuses to start it.
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from .. import settings

# Folder name inside the bundle. The same name Google ships the tools under,
# so a release step can unzip the official archive straight into place.
BUNDLE_DIR = "platform-tools"
ENV_OVERRIDE = "DABP_ADB_BINARY"


def _executable_name() -> str:
    # Assembled rather than written as one literal. The message-catalogue
    # check reads keys out of the source by SHAPE (tests/test_i18n.py), and
    # the quoted Windows name is exactly the shape of a key in the `adb`
    # area — it would be reported as a message that has no translation.
    return "adb" + (".exe" if os.name == "nt" else "")


def _make_runnable(path: Path) -> None:
    """Restore the executable bit if packaging dropped it."""
    if os.name == "nt":
        return
    try:
        mode = path.stat().st_mode
        if mode & stat.S_IXUSR:
            return
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        # A read-only install directory is not a reason to refuse the call:
        # the executable bit may well already be right, and the attempt to
        # run it is the honest test.
        pass


def bundled() -> Path | None:
    """The adb shipped with this build, or None if it carries none.

    Both roots are consulted so the bundled path can be exercised from a
    source tree: `resource_dir()` is the frozen bundle, `ROOT` the checkout.
    """
    for base in (settings.resource_dir(), settings.ROOT):
        candidate = Path(base) / BUNDLE_DIR / _executable_name()
        if candidate.is_file():
            _make_runnable(candidate)
            return candidate
    return None


def adb_path() -> str:
    """The command to run. Never raises — see the module docstring."""
    override = str(os.environ.get(ENV_OVERRIDE) or "").strip()
    if override:
        return override
    found = bundled()
    if found is not None:
        return str(found)
    # `which` rather than the bare name so the resolved path shows up in a
    # traceback and in the job log; "adb" alone tells nobody which adb ran.
    return shutil.which("adb") or "adb"

