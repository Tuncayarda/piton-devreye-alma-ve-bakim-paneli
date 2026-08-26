#!/usr/bin/env python3
"""Project device lists carried on the service key.

A customer's package holds one customer's DeviceMap and no other — that is
the whole point of building it separately. Admin mode still has to be able to
open another project on a machine in the field, so the maps travel with the
engineer instead: a `dabp-projects/` folder beside the key file on the same
stick.

The pack inherits the stick's authority and nothing else. It is read only
after the key file has been recognised, so a folder of that name on any other
volume is just a folder.

Every map is COPIED into a session directory as it is discovered, and the
copy is what the panel opens. Pulling the stick then cannot break a run that
is already under way — an IP assignment reads the inventory repeatedly over
several minutes, and an engineer who has finished at one cabinet has no
reason to expect the stick to still be needed.
"""
from __future__ import annotations

import shutil
import tempfile
from fnmatch import fnmatch
from pathlib import Path

from ..editions import Project
from . import handback
from .keyfile import PACK_DIR

# Bounds on what is read from removable media handed to us by someone else.
MAX_FILES = 32
MAX_BYTES = 4 * 1024 * 1024

_SESSION: Path | None = None


def session_dir() -> Path:
    global _SESSION
    if _SESSION is None or not _SESSION.is_dir():
        _SESSION = Path(tempfile.mkdtemp(prefix="dabp-projects-"))
    return _SESSION


def clear_session() -> None:
    """Remove the copies. Called from `panel.api.lifecycle.reset`."""
    global _SESSION
    if _SESSION is not None:
        shutil.rmtree(_SESSION, ignore_errors=True)
    _SESSION = None


def projects(volume) -> list[Project]:
    """The maps on this volume, copied and ready to open.

    Never raises: this runs on the watcher's thread, and a stick with an
    unreadable folder on it must leave the panel working.
    """
    folder = Path(volume) / PACK_DIR
    found: list[Project] = []
    # Through the operator's session first where that is needed at all, and
    # for the same reason as the key file itself: on macOS the first side to
    # ask decides for the whole process tree, so this process must not be
    # the one that asks and is refused (see `keyfile.read` and `handback`).
    if handback.applicable():
        found = _handed_back(folder)
        if found:
            return found
    try:
        if not folder.is_dir():
            return found
        entries = sorted(folder.glob("DeviceMap*.json"))[:MAX_FILES]
    except OSError:
        return found

    for entry in entries:
        try:
            if not entry.is_file() or entry.stat().st_size > MAX_BYTES:
                continue
            target = session_dir() / entry.name
            # Copied afresh every round: a stick swapped for another one
            # carrying a newer map of the same name must not be shadowed by
            # the copy made from the first.
            shutil.copyfile(entry, target)
        except OSError:
            continue
        found.append(_project_for(target))
    return found


def _handed_back(folder: Path) -> list[Project]:
    """The same maps, read through the session that is allowed to read them.

    The bounds are the ones above and for the same reason — this is still
    removable media somebody else wrote — they are simply enforced on this
    side of the handback rather than by `stat`.
    """
    listed = handback.names(folder)
    if not listed:
        return []
    found: list[Project] = []
    for name in sorted(n for n in listed
                       if fnmatch(n, "DeviceMap*.json"))[:MAX_FILES]:
        data = handback.read_bytes(folder / name, MAX_BYTES)
        if data is None or len(data) > MAX_BYTES:
            continue
        target = session_dir() / name
        try:
            target.write_bytes(data)
        except OSError:
            continue
        found.append(_project_for(target))
    return found


def _project_for(path: Path) -> Project:
    """Name it the way a built-in project is named.

    The label has to match what `Inventory.project` derives from the same
    file name, because that derived string is what the video configuration
    branches on (`panel/video_config/nvr.py`). Deriving both from the stem is
    what keeps them the same string.
    """
    label = path.stem.replace("DeviceMap", "").strip("_- ") or "YATAKLI"
    return Project(key=label.lower(), label=label, map_name=path.name,
                   source_path=(path.name,), path=str(path))
