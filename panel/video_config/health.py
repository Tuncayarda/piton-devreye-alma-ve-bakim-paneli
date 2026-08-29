#!/usr/bin/env python3
"""The extra checks the verification pass makes on a camera or an NVR.

Time zone, NTP and subnet mask are checked in `panel.probe.camera`, next to
the identity read. What is here is everything the field's CCTV verification
script looks at BEYOND those — the state that decides whether the equipment
will actually record:

  NVR     the disk, and whether the buzzer is still armed
  camera  the SD card, the IR illuminator, the third stream

Each check answers with a short phrase for the verification column, or None
when there is nothing to report. A check that CANNOT be read says so rather
than passing quietly: "the buzzer could not be read" and "the buzzer is off"
are not the same answer, and the second one written in place of the first is
how a train leaves with a beeping cabinet.
"""
from __future__ import annotations

from .. import i18n
from ..errors import AuthError
from . import isapi

# The two triggers that can beep on an NVR. Only used when the trigger list
# comes back without notification methods — some firmware answers the list
# with ids alone, and then the only way to know is to ask them by name.
BEEPING_TRIGGERS = ("diskerror", "diskfull")


def _text(response) -> str:
    return (response.text or "") if response is not None else ""


def buzzer_on(ip: str, credentials, timeout: float | None = None):
    """True while a trigger still sounds the buzzer; None if unreadable."""
    try:
        listing = isapi.request("GET", ip, "Event/triggers", credentials,
                                timeout=timeout)
        if listing.status_code != 200:
            return None
        body = _text(listing)
        if "<notificationMethod>" in body:
            return "<notificationMethod>beep<" in body
        for name in BEEPING_TRIGGERS:
            one = isapi.request("GET", ip, f"Event/triggers/{name}",
                                credentials, timeout=timeout)
            if (one.status_code == 200
                    and "<notificationMethod>beep<" in _text(one)):
                return True
        return False
    except AuthError:
        raise
    except Exception:
        return None


def _storage_problem(ip: str, credentials, label: str, timeout):
    try:
        root = isapi.read(ip, "ContentMgmt/Storage/hdd", credentials,
                          timeout=timeout)
    except AuthError:
        raise
    except Exception:
        # Only a broken conversation is "unreadable". The device answered
        # its identity a moment ago, so a refused storage endpoint means it
        # has no storage — most cameras in a set have no card fitted, and
        # "SD unreadable" on every one of them is a finding nobody can act
        # on.
        return i18n.t("video.checkStorageUnreadable", label=label)
    _summary, disks = isapi.storage_status(root)
    if not disks:
        return i18n.t("video.checkStorageMissing", label=label)
    bad = [status or "?" for _id, status in disks if isapi.needs_format(status)]
    if bad:
        return i18n.t("video.checkStorageError", label=label,
                      detail="/".join(bad))
    return None


def _sub_value(ip: str, credentials, path: str, parent: str, tag: str,
               timeout):
    """(readable, value) for one tag under one element.

    Absent is not a fault: a camera model without an IR lamp has no
    IrLightSwitch, and reporting "IR could not be read" on it would put a
    permanent finding on a healthy device.
    """
    try:
        root = isapi.read(ip, path, credentials, timeout=timeout)
    except AuthError:
        raise
    except Exception:
        return False, None
    if root is None:
        return False, None
    for element in isapi.blocks(root, parent):
        return True, isapi.child_text(element, tag).lower()
    return True, None


def _buzzer_problem(ip: str, credentials, timeout):
    state = buzzer_on(ip, credentials, timeout)
    if state is None:
        return i18n.t("video.checkBuzzerUnreadable")
    return i18n.t("video.checkBuzzerOn") if state else None


def _ir_problem(ip: str, credentials, timeout):
    readable, mode = _sub_value(ip, credentials, "System/Hardware",
                                "IrLightSwitch", "mode", timeout)
    if not readable:
        return i18n.t("video.checkIrUnreadable")
    if mode is None or mode == "close":
        return None
    return i18n.t("video.checkIrOn")


def _third_stream_problem(ip: str, credentials, timeout):
    readable, enabled = _sub_value(ip, credentials,
                                   "System/Software/channels/1",
                                   "ThirdStream", "enabled", timeout)
    if not readable:
        return i18n.t("video.checkThirdStreamUnreadable")
    if enabled is None or enabled == "true":
        return None
    return i18n.t("video.checkThirdStreamOff")


def problems(ip: str, credentials, *, is_nvr: bool,
             storage: bool = True,
             timeout: float | None = None) -> list[str]:
    """Everything worth reporting about this device, in reading order.

    `storage` is the PROJECT's answer to "is there anything in these devices
    to ask about" (see `panel.editions.catalogue.Project.storage`). On the
    trains whose cameras record to the NVR there is no card in them by
    design, and asking anyway filled the checklist with "no SD card" for
    every camera on the train — a fault nobody could fix, on hardware that
    was working exactly as specified.

    The BUZZER is not behind that flag. An NVR left with its buzzer armed is
    a fault on any project, and it has nothing to do with what is in the
    slot.
    """
    found = []
    if storage:
        found.append(_storage_problem(ip, credentials,
                                      i18n.t("video.hdd") if is_nvr
                                      else i18n.t("video.sdCard"), timeout))
    if is_nvr:
        found.append(_buzzer_problem(ip, credentials, timeout))
    else:
        found.append(_ir_problem(ip, credentials, timeout))
        found.append(_third_stream_problem(ip, credentials, timeout))
    return [problem for problem in found if problem]
