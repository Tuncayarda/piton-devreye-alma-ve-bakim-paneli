#!/usr/bin/env python3
"""Compartment LCD — Android over adb (getprop + dumpsys + logcat).

Reaching adb is not enough for the device to count as "up": the panel app's
version must be readable too. A device shown green with no data would fill
the checklist with empty columns and call it verified — in the field that
means reporting an app that was never installed as installed.
"""
from __future__ import annotations

import re
import subprocess

from .. import editions, settings
from ..adb.binary import adb_path
from ..errors import (NotApplicableError, UnreachableError, VerificationError)
from .. import i18n


def package_info(raw: str) -> dict:
    """Device identity from `dumpsys package <pkg>` output.

        versionCode=1 minSdk=21 targetSdk=35
        versionName=0.0.5
        firstInstallTime=2026-07-07 13:13:40

    No `versionName` means the package is not installed; the caller treats
    that as an error.
    """
    def find(pattern: str) -> str:
        match = re.search(pattern, raw)
        return match.group(1).strip() if match else ""

    return {
        "version": find(r"versionName=(\S+)"),
        "versionCode": find(r"versionCode=(\d+)"),
        "minSdk": find(r"minSdk=(\d+)"),
        "targetSdk": find(r"targetSdk=(\d+)"),
        "installedAt": find(r"firstInstallTime=(.+)"),
        "updatedAt": find(r"lastUpdateTime=(.+)"),
    }


def sip_log(raw: str) -> dict:
    """SIP registration from the AnnounceSip log.

        SIP engine started: sip:6001@10.1.1.1:5060 (UDP)
        Registration state=registered code=200

    The log is a ring buffer, so the NEWEST line wins. No registration line
    at all leaves the fields empty — that alone is not an error, the buffer
    may simply have wrapped.
    """
    data = {"sipExtension": "", "sipPbx": "", "sipPort": "",
            "sipTransport": "", "sipRegistration": "", "sipCode": ""}

    endpoints = re.findall(
        r"sip:(\d+)@([\d.]+)(?::(\d+))?(?:\s*\((\w+)\))?", raw)
    if endpoints:
        extension, pbx, port, transport = endpoints[-1]
        data.update(sipExtension=extension, sipPbx=pbx, sipPort=port,
                    sipTransport=transport)

    registrations = re.findall(
        r"Registration state=(\S+)(?:\s+code=(\d+))?", raw)
    if registrations:
        state, code = registrations[-1]
        data.update(sipRegistration=state, sipCode=code)
    return data


def app_required() -> bool:
    """Must the named panel application be on the display for a green read?

    THE PROJECT DECIDES. A train's Compartment LCD is there to run that
    application and its absence is the fault being commissioned for; a
    demonstration stand carries borrowed hardware running whatever each unit
    happens to have, and demanding one named application turns the whole
    board red and hides the units that genuinely cannot be reached (see
    `panel.editions.catalogue.Project.stand`).

    `ADB_REQUIRE_PACKAGE` overrides it in either direction, for a bench that
    is neither. Unset — which is the normal case — nobody has to remember a
    flag: setting the stand up is the whole of it.
    """
    override = str(settings.ADB_REQUIRE_PACKAGE or "").strip()
    if override in ("0", "1"):
        return override == "1"
    try:
        return not editions.on_a_stand()
    except Exception:
        # No edition active yet (a probe from a test or a script). The
        # stricter answer is the safe one.
        return True


def read(ip: str, timeout: int | None = None) -> dict:
    limit = timeout or settings.ADB_TIMEOUT
    target = f"{ip}:{settings.ADB_PORT}"

    def run(*args) -> str:
        result = subprocess.run([adb_path(), "-s", target, *args],
                                capture_output=True, text=True, timeout=limit,
                                check=False)
        return result.stdout.strip()

    try:
        subprocess.run([adb_path(), "connect", target], capture_output=True,
                       text=True, timeout=limit, check=False)
    except FileNotFoundError:
        raise NotApplicableError(
            i18n.t("error.adbMissing"))
    except subprocess.TimeoutExpired:
        raise UnreachableError(i18n.t("error.adbConnectTimeout"))

    try:
        serial = run("shell", "getprop", "ro.serialno")
        if not serial:
            # A failed adb connect leaves stdout empty; that is a device
            # access problem, not an "unexpected error".
            raise UnreachableError(
                i18n.t("error.adbNoConnection"))
        timezone = run("shell", "getprop", "persist.sys.timezone")
        uptime_raw = run("shell", "cat", "/proc/uptime")

        package = package_info(run("shell", "dumpsys", "package",
                                   settings.ADB_PACKAGE))
        if not package["version"] and app_required():
            # On a train this is the fault being looked for: the display is
            # there to run this application. On a stand it is not — see
            # `app_required` below. Either way the display had to ANSWER to
            # get this far; what is in question is only what is on it.
            raise VerificationError(
                i18n.t("error.adbVersionUnreadable",
                       package=settings.ADB_PACKAGE))

        sip = sip_log(run("logcat", "-d", "-s",
                          f"{settings.ADB_LOG_TAG}:I", "*:S"))

        return {
            "serial": serial,
            "timezone": timezone,
            "uptime": uptime_raw.split()[0] if uptime_raw else None,
            "package": settings.ADB_PACKAGE,
            **package,
            **sip,
        }
    except subprocess.TimeoutExpired:
        raise UnreachableError(i18n.t("error.adbTimeout"))
    finally:
        try:
            # `adb_path()`, not the bare name: this module resolves it for
            # every other call and a disconnect that quietly does nothing
            # leaves the transport attached for the next read to trip over.
            subprocess.run([adb_path(), "disconnect", target],
                           capture_output=True, text=True, timeout=limit,
                           check=False)
        except Exception:
            pass
