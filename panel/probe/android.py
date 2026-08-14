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

from .. import settings
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


def read(ip: str, timeout: int | None = None) -> dict:
    limit = timeout or settings.ADB_TIMEOUT
    target = f"{ip}:{settings.ADB_PORT}"

    def run(*args) -> str:
        result = subprocess.run(["adb", "-s", target, *args],
                                capture_output=True, text=True, timeout=limit)
        return result.stdout.strip()

    try:
        subprocess.run(["adb", "connect", target], capture_output=True,
                       text=True, timeout=limit)
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
        if not package["version"]:
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
            subprocess.run(["adb", "disconnect", target], capture_output=True,
                           text=True, timeout=limit)
        except Exception:
            pass
