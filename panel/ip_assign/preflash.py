#!/usr/bin/env python3
"""Flashing an intercom before its address is written.

The field problem: intercoms shipped to the trains long ago are on firmware
old enough that they report their version and their identity wrongly. They
have to be flashed before anything else is done to them, and the only moment
that is possible is inside the assignment run — the run has just powered a
single PoE port, so exactly one device is reachable and it is still on the
factory address. A minute later it has an address of its own and is one of a
dozen indistinguishable devices.

So this is not a second firmware screen. It is a step the run performs at the
one instant it can, on whatever answers, through the same upload endpoint the
firmware screen uses (`panel.firmware.post_image`).

WHEN IT FLASHES. Always, on every port the option is switched on for. There
is no "expected version" to compare against: the devices this step exists for
are precisely the ones that report their version wrongly or not at all, so a
comparison could only ever be answered with "I cannot tell", and that answer
was never allowed to mean "it is up to date". The version IS still read before
and after, but only to say so in the run log.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .. import firmware, i18n
from ..errors import user_message
from ..probe import announcement

# How long to wait for a device to come back after the image is sent. The
# device reboots into the new firmware; until it answers again nothing else
# can be done with it, and the run's own port loop is blocked meanwhile.
REBOOT_WINDOW = 120.0
# How often to knock while waiting. The device refuses connections until its
# HTTP server is up, so these are cheap.
POLL_INTERVAL = 3.0
# The read that decides "old or not". Short: a device that does not answer
# this quickly counts as unreadable, which means it gets flashed anyway.
VERSION_TIMEOUT = 4.0


def read_version(ip: str, credentials=None) -> str:
    """The device's reported version, or "" when it will not say.

    Never raises. Every failure — unreachable, no auth, nonsense body — is the
    same answer here: unknown, therefore flash it.
    """
    try:
        return str(announcement.read(
            ip, credentials, timeout=VERSION_TIMEOUT,
            extra_endpoints=()).get("version", "") or "").strip()
    except Exception:                                  # noqa: BLE001
        return ""


def wait_back(ip: str, credentials=None, window: float = REBOOT_WINDOW,
              cancelled=None) -> str:
    """Wait for the device to answer again. Returns its version, "" if never.

    The address does not change: a firmware upload does not move the device,
    and the factory address is where it was already.
    """
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        if cancelled is not None and cancelled():
            return ""
        time.sleep(POLL_INTERVAL)
        version = read_version(ip, credentials)
        if version:
            return version
        # It may be up but not yet reporting a version — that still counts as
        # back, and the caller decides what an empty version means.
        try:
            announcement.read(ip, credentials, timeout=VERSION_TIMEOUT,
                              extra_endpoints=())
            return ""
        except Exception:                              # noqa: BLE001
            continue
    return ""


# ───────────────────────────────────────────────── the chosen image ────────
# One image for the whole run, held in memory only.
#
# ONE, not one per device: at the moment this step happens the device is on
# the factory address and has not said which of the twelve intercoms it is —
# that is the very fault being repaired. Choosing per device would presume the
# answer to the question the step exists to work around.
#
# THE PATH NEVER GOES TO THE BROWSER. The user picks the file in the operating
# system's own dialog and the panel keeps the path; the screen only ever sees
# the file's name and size. Same rule as the job log files (see
# general_routes.post_job_file) — a path from the client is a path the client
# chose.
_CHOSEN: dict = {}
_CHOSEN_LOCK = threading.Lock()


def choose_file(path: str) -> dict:
    """Remember the image for the run. Raises ValueError if unusable."""
    target, size = firmware.validate_file(path)
    with _CHOSEN_LOCK:
        _CHOSEN.clear()
        _CHOSEN.update(path=target, size=size)
    return chosen()


def chosen() -> dict:
    """What the screen is allowed to know: the name and the size."""
    with _CHOSEN_LOCK:
        if not _CHOSEN:
            return {"name": "", "size": 0}
        return {"name": Path(_CHOSEN["path"]).name, "size": _CHOSEN["size"]}


def forget_file() -> None:
    with _CHOSEN_LOCK:
        _CHOSEN.clear()


def options_from(body: dict) -> dict:
    """The run's flashing options.

    Only the switch comes from the request; the file is whatever the user
    picked in the OS dialog (see `_CHOSEN`).
    """
    with _CHOSEN_LOCK:
        path = str(_CHOSEN.get("path") or "")
    return {"preflash": bool(body.get("preflash")), "preflashPath": path}


def validate(options: dict) -> None:
    """Raise ValueError if the run cannot be started with these options.

    Checked when the button is pressed rather than when the first port is
    reached: learning that the file was moved eight ports into a run means
    learning it at the worst possible moment.
    """
    if not options.get("preflash"):
        return
    path = str(options.get("preflashPath") or "").strip()
    if not path:
        raise ValueError(i18n.t("error.preflashNoFile"))
    # Same size and existence rules as the firmware screen.
    firmware.validate_file(path)


def callback(options: dict, emit, credentials=None, cancelled=None):
    """Build the run's BEFORE_WRITE hook, or None when the option is off.

    The returned callable matches the contract documented on
    `intercom_ip_assign.BEFORE_WRITE`: it returns (ok, note) and never raises,
    because a callback that raises out of the field script's port loop would
    take the whole run down with it — and the ports would be left closed.
    """
    if not options.get("preflash"):
        return None
    path = Path(str(options.get("preflashPath") or "").strip())

    def before_write(port: int, ip: str, _settings, _config):
        try:
            current = read_version(ip, credentials)
            emit(i18n.t("preflash.starting", ip=ip, name=path.name,
                        current=current or i18n.t("preflash.unknownVersion")))
            firmware.post_image(ip, path, credentials)
            back = wait_back(ip, credentials, cancelled=cancelled)
            if cancelled is not None and cancelled():
                return False, i18n.t("preflash.cancelled")
            if not back:
                # It may be up without reporting a version; the run's own next
                # step will find out. What we cannot do is claim a version.
                return True, i18n.t("preflash.doneNoVersion")
            return True, i18n.t("preflash.done", version=back)
        except Exception as exc:                       # noqa: BLE001
            return False, i18n.t("preflash.failed",
                                 detail=user_message(exc))

    return before_write
