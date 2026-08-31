#!/usr/bin/env python3
"""Compartment LCD — Android over adb (getprop + dumpsys + logcat).

Reaching adb is not enough for the device to count as "up": the panel app's
version must be readable too. A device shown green with no data would fill
the checklist with empty columns and call it verified — in the field that
means reporting an app that was never installed as installed.

The TRANSPORT is `panel.adb.client` and nothing else. This file used to run
its own ``subprocess`` with its own connect proof, and the ADB screen ran the
client's; the two proofs disagreed, so the same display at the same moment
could be red on the scan and green on the ADB screen. What lives here now is
only what this probe knows: which fields to extract and how to parse them.
"""
from __future__ import annotations

import re

from .. import editions, settings
from ..adb import client
from ..errors import UnreachableError, VerificationError
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


def read(ip: str, timeout: float | None = None) -> dict:
    # Applied to EACH adb invocation below, not to the read as a whole —
    # callers passing a budget (the light refresh's few seconds) get it as
    # the ceiling on any single hang, which is the failure the budget is
    # there to bound.
    limit = timeout or settings.ADB_TIMEOUT

    def shell(*args: str) -> str:
        # stdout, exit code ignored — the shape this probe has always read:
        # a command that failed leaves its field empty rather than aborting
        # the whole read, and the checks below decide what an empty field
        # means.
        result = client.shell_result(ip, *args, timeout=limit)
        return str(getattr(result, "stdout", "") or "").strip()

    try:
        # The lease keeps this read from tearing a transport out from under
        # a concurrent APK install on the same display — and the other way
        # round (see panel/adb/client.py, "the connection lease").
        with client.lease(ip):
            # THE CONNECT PROOF IS THE CLIENT'S: disconnect-first, then
            # `adb connect`, then `get-state` must answer ``device``. This
            # file used to fire one bare `adb connect` and infer
            # reachability from `getprop ro.serialno` coming back non-empty
            # — a proof no other screen shared, which is how one display got
            # two verdicts at once (scan red, ADB screen green), and one
            # that `adb connect`'s cheerful answer to a mere TCP handshake
            # could fool. One attempt, not the client's default twelve: the
            # scan revisits on its own beat, and its budget is per command,
            # not per campaign.
            if not client.connect(ip, attempts=1, timeout=limit):
                raise UnreachableError(i18n.t("error.adbNoConnection"))

            serial = shell("getprop", "ro.serialno")
            if not serial:
                # No longer the connect proof (the client's is, above), but
                # still a failed read: a transport that answers ``device``
                # and yields no serial gives this probe nothing to report,
                # and an empty row shown green is the original complaint.
                raise UnreachableError(i18n.t("error.adbNoConnection"))
            timezone = shell("getprop", "persist.sys.timezone")
            uptime_raw = shell("cat", "/proc/uptime")

            package = package_info(shell("dumpsys", "package",
                                         settings.ADB_PACKAGE))
            if not package["version"] and app_required():
                # On a train this is the fault being looked for: the display
                # is there to run this application. On a stand it is not —
                # see `app_required` above. Either way the display had to
                # ANSWER to get this far; what is in question is only what
                # is on it.
                raise VerificationError(
                    i18n.t("error.adbVersionUnreadable",
                           package=settings.ADB_PACKAGE))

            # logcat is a device command, not a shell command, so it goes
            # through `client.run` with the same explicit serial.
            logcat = client.run("-s", client.target(ip), "logcat", "-d",
                                "-s", f"{settings.ADB_LOG_TAG}:I", "*:S",
                                timeout=limit)
            sip = sip_log(str(getattr(logcat, "stdout", "") or "").strip())

            return {
                "serial": serial,
                "timezone": timezone,
                "uptime": uptime_raw.split()[0] if uptime_raw else None,
                "package": settings.ADB_PACKAGE,
                **package,
                **sip,
            }
    finally:
        # AFTER the lease is released, so it really drops the serial when
        # this read was the transport's only user — and is skipped by
        # `client.disconnect` itself when an install still holds a lease.
        # A transport left attached is what the next read trips over.
        client.disconnect(ip, timeout=limit)
