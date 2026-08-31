#!/usr/bin/env python3
"""The steps a camera and an NVR apply IDENTICALLY.

`camera.py` and `nvr.py` each own their device's ordering — which is the
procedure, and the reason this package exists — but the individual steps
they share used to be written twice, and had already started to drift (the
two copies of the time write disagreed about their timeout). What lives
here is only what is provably the same on both devices:

  · the time zone / NTP write pair, applied only where the device differs;
  · the storage format step, and its rule that a healthy disk is never
    touched — applying a setting must not wipe recordings;
  · the reboot request, whose dropped connection is the success case.
"""
from __future__ import annotations

from .. import i18n
from . import isapi, payloads

# One bound for the small writes both procedures make (time, NTP, reboot).
# 10 s is the recorder's field-proven ceiling and a superset of the camera's
# old default (PROBE_TIMEOUT, 5 s): the slower device sets the bound, and a
# camera that answers at all answers well inside either.
WRITE_TIMEOUT = 10.0


def differs(state: dict, targets: dict, name: str) -> bool:
    """Does the device hold something other than the target for `name`?

    A field absent from `targets` never differs: the run only writes what
    it was asked for. State keys are lower case (see `read_state`).
    """
    return (name in targets
            and str(state.get(name.lower(), "")) != str(targets[name]))


def apply_time_targets(ip: str, state: dict, targets: dict, credentials,
                       say) -> list[str]:
    """Write the time zone and the NTP server where they differ.

    Returns the field names actually written, for the run report.
    """
    written: list[str] = []
    if differs(state, targets, "timeZone"):
        isapi.write(ip, "System/time", credentials,
                    payloads.time_body(targets["timeZone"]),
                    timeout=WRITE_TIMEOUT)
        say(i18n.lazy("video.stepTimeZone", value=targets["timeZone"]),
            "written")
        written.append("timeZone")
    if differs(state, targets, "ntpServer"):
        isapi.write(ip, "System/time/ntpServers/1", credentials,
                    payloads.ntp_body(targets["ntpServer"]),
                    timeout=WRITE_TIMEOUT)
        say(i18n.lazy("video.stepNtp", value=targets["ntpServer"]), "written")
        written.append("ntpServer")
    return written


def format_storage(device, credentials, say) -> bool:
    """Format the SD card / disk only when it is unusable as it stands.

    Storage that is formatted and recording is left alone: applying a
    setting must never wipe footage (see isapi.needs_format).
    """
    summary, disks = isapi.storage_status(
        isapi.read(device.ip, "ContentMgmt/Storage/hdd", credentials))
    if not disks:
        say(i18n.lazy("video.stepNoStorage"), "info")
        return False
    formatted = False
    for hdd_id, status in disks:
        if not isapi.needs_format(status):
            continue
        isapi.write(device.ip, f"ContentMgmt/Storage/hdd/{hdd_id}/format",
                    credentials, "", timeout=15)
        say(i18n.lazy("video.stepStorageFormatted", id=hdd_id,
                      status=status or "?"), "written")
        formatted = True
    if not formatted:
        say(i18n.lazy("video.stepStorageOk", detail=summary), "info")
    return formatted


def reboot(device, credentials) -> None:
    """Ask for a reboot. A dropped connection means it started.

    Both devices sever the socket as they go down; that IS the reboot, so
    nothing here is an error. Whether to reboot at all is the caller's
    decision — a device already in agreement must never be restarted.
    """
    try:
        isapi.request("PUT", device.ip, "System/reboot", credentials,
                      timeout=WRITE_TIMEOUT)
    except Exception:
        pass
