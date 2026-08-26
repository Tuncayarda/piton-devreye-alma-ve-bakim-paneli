#!/usr/bin/env python3
"""Where a USB stick shows up, on each of the three operating systems.

The stick has to be recognised wherever it is plugged in, and the three
platforms disagree about what "plugged in" even looks like. The per-OS
branching follows the shape already used in `panel/elevation/privileges.py`.

Scope is deliberately narrowed to removable media rather than "any path that
holds the file". The key is meant to be a physical thing somebody carries; a
copy of the file on the system drive would make it a password again.
"""
from __future__ import annotations

import ctypes
import os
import platform
from pathlib import Path

# Windows GetDriveTypeW
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3


def removable(system: str | None = None) -> list[Path]:
    """Every mounted volume that could be somebody's USB stick."""
    system = system or platform.system()
    if system == "Windows":
        return _windows()
    if system == "Darwin":
        return _macos()
    return _linux()


# ── Windows ──────────────────────────────────────────────────────────────
def _windows() -> list[Path]:
    """The drive letters, minus the system drive.

    DRIVE_FIXED is accepted alongside DRIVE_REMOVABLE on purpose: plenty of
    USB3 sticks and every USB SSD enumerate as fixed, and refusing them would
    mean a key that works on one engineer's stick and not another's. The
    system drive is still excluded — that is the case this narrowing is for.
    """
    found: list[Path] = []
    try:
        kernel32 = ctypes.windll.kernel32                  # type: ignore[attr-defined]
        mask = int(kernel32.GetLogicalDrives())
    except (AttributeError, OSError, ValueError):
        return found
    system_drive = str(os.environ.get("SystemDrive", "C:")).rstrip("\\").upper()
    for index in range(26):
        if not mask & (1 << index):
            continue
        letter = f"{chr(ord('A') + index)}:"
        if letter.upper() == system_drive:
            continue
        try:
            kind = int(kernel32.GetDriveTypeW(ctypes.c_wchar_p(letter + "\\")))
        except (AttributeError, OSError, ValueError):
            continue
        if kind in (DRIVE_REMOVABLE, DRIVE_FIXED):
            found.append(Path(letter + "\\"))
    return found


# ── macOS ────────────────────────────────────────────────────────────────
def _macos() -> list[Path]:
    """Everything under /Volumes except the boot volume.

    The boot volume appears there too, as "Macintosh HD" — but the name is
    the user's to change and on modern macOS it is a firmlink to `/`. So it
    is identified by device number rather than by name; string-matching it
    would let a renamed boot volume through.
    """
    return _under(Path("/Volumes").glob("*"))


# ── Linux ────────────────────────────────────────────────────────────────
def _linux() -> list[Path]:
    """The automount points, under whichever user's name they were made.

    THE FIELD TRAP IS THE USER NAME. The panel runs elevated through pkexec,
    so `$USER` inside this process is root — while the desktop mounted the
    stick under the name of the person who plugged it in. Looking under
    "/media/$USER" alone finds nothing, every time, on the machine where it
    matters. The original user is recovered from what the elevation left
    behind, and the wildcard forms are searched as well.
    """
    candidates = []
    names = [name for name in (_original_user(),) if name]
    for base in ("/media", "/run/media"):
        for name in names:
            candidates.extend(Path(base).glob(f"{name}/*"))
        candidates.extend(Path(base).glob("*/*"))
        candidates.extend(Path(base).glob("*"))
    candidates.extend(Path("/mnt").glob("*"))
    return _under(candidates)


def _original_user() -> str:
    """Who was at the keyboard before the elevation, if we can tell."""
    for name in ("PKEXEC_UID", "SUDO_UID"):
        raw = os.environ.get(name)
        if raw and raw.isdigit():
            try:
                import pwd                                 # noqa: PLC0415
                return pwd.getpwuid(int(raw)).pw_name
            except (ImportError, KeyError, ValueError):
                continue
    return str(os.environ.get("SUDO_USER") or "")


# ── shared ───────────────────────────────────────────────────────────────
def _under(candidates) -> list[Path]:
    """Keep the directories that are really separate mounts, in order.

    A mount point on the same device as `/` is a plain folder somebody made,
    not a volume — `/mnt/backup` on the system disk, or a `/media` entry left
    behind after an unmount.
    """
    try:
        root_device = os.stat("/").st_dev
    except OSError:
        root_device = None
    found: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            if not candidate.is_dir():
                continue
            resolved = candidate.resolve()
            key = str(resolved)
            if key in seen:
                continue
            info = os.stat(resolved)
            if root_device is not None and info.st_dev == root_device:
                continue
        except OSError:
            continue
        seen.add(key)
        found.append(candidate)
    return found
