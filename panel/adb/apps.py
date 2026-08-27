#!/usr/bin/env python3
"""Starting, stopping, installing and removing one application on one device.

Each function here does its work on ONE address and either returns a short
record or raises. Doing several devices at once is `runner`'s job, and
keeping that split is what lets a device fail without taking the run with it.

TWO THINGS IN THIS FILE ARE NOT OBVIOUS AND BOTH COST TIME TO LEARN.

**The activity is resolved, never typed.** `am start` needs
``<package>/<activity>``, and the activity is not derivable from the package
name — it is whatever the manifest declares as MAIN/LAUNCHER, and it differs
between builds of the same application. Asking the operator for it means
asking for something they would have to read out of a manifest they do not
have. So the device is asked (`launcher_activity`), the same way a launcher
asks.

**`am start` lies.** It exits 0 while printing ``Error: Activity class …
does not exist`` — so a caller that trusts the exit code reports a launch
that never happened, and a caller that trusts the output alone reports a
failure whenever the device prints a warning. Both halves are checked
(`_started`), and the same care applies to `pm uninstall`, which prints
``Failure [DELETE_FAILED_INTERNAL_ERROR]`` and exits 0.
"""
from __future__ import annotations

import re

from .. import firmware, i18n, settings
from ..errors import UnreachableError, VerificationError
from . import client

# `cmd package resolve-activity --brief` ends with the component, one per
# line, the last line being the resolved one.
_COMPONENT = re.compile(r"^[A-Za-z][\w.]*/[\w.$]+$")
# The fallback: the MAIN/LAUNCHER filter block inside `dumpsys package`.
_DUMPSYS_COMPONENT = re.compile(r"([A-Za-z][\w.]*)/([\w.$]+)")
# `am start` and `pm uninstall` both announce failure in their output.
_FAILURE = re.compile(r"^\s*(Error|Failure|Exception)\b", re.MULTILINE)

# Actions the screen offers. Named here rather than in the route so the
# server and the runner cannot disagree about what exists.
OPERATIONS = ("start", "stop", "restart", "uninstall", "install",
              "autostart_install", "autostart_remove")


def _require(ip: str) -> None:
    if not client.connect(ip, attempts=2):
        raise UnreachableError(i18n.t("error.adbNoConnection"))


def _failed(text: str) -> str:
    """The first line that announces a failure, or "" if none does."""
    match = _FAILURE.search(text or "")
    if not match:
        return ""
    line = (text or "")[match.start():].splitlines()[0]
    return line.strip()[:160]


def launcher_activity(ip: str, package: str) -> str:
    """The component ``<package>/<activity>`` this device would launch.

    Two ways of asking, because the first one is not on every build:
    `cmd package` arrived in Android 7 and some of the locked-down images
    these displays run have it removed. The fallback reads the same fact out
    of `dumpsys package`, which every build has.
    """
    name = clean_package(package)
    brief = client.shell_result(
        ip, "cmd", "package", "resolve-activity", "--brief", name)
    for line in reversed(client.output(brief).splitlines()):
        candidate = line.strip()
        if _COMPONENT.match(candidate) and candidate.startswith(f"{name}/"):
            return candidate

    dumped = client.output(client.shell_result(
        ip, "dumpsys", "package", name))
    for block in _launcher_blocks(dumped):
        match = _DUMPSYS_COMPONENT.search(block)
        if match and match.group(1) == name:
            return f"{name}/{match.group(2)}"
    raise VerificationError(
        i18n.t("error.adbNoLauncherActivity", package=name))


def _launcher_blocks(dumped: str):
    """The sections of `dumpsys package` output that declare a launcher.

    `dumpsys` prints the resolver table as blocks separated by blank lines;
    the component sits on the block's own header line and the intent filter
    below it. Only blocks naming both MAIN and LAUNCHER are launchers — an
    activity with MAIN alone is not something a launcher would start.
    """
    for block in re.split(r"\n\s*\n", dumped or ""):
        if "android.intent.action.MAIN" in block and \
                "android.intent.category.LAUNCHER" in block:
            yield block


def clean_package(package) -> str:
    name = str(package or "").strip()
    if not name or not re.fullmatch(r"[A-Za-z][\w.]*", name):
        raise ValueError(i18n.t("error.adbPackageInvalid"))
    return name


# ── the operations ──────────────────────────────────────────────────────
def stop(ip: str, package: str) -> dict:
    """Force-stop the application. Stopping one that is not running is fine."""
    name = clean_package(package)
    _require(ip)
    result = client.shell_result(ip, "am", "force-stop", name)
    detail = _failed(client.output(result))
    if detail:
        raise VerificationError(detail)
    return {"package": name, "action": "stop"}


def start(ip: str, package: str, activity: str = "") -> dict:
    """Launch the application's own launcher activity."""
    name = clean_package(package)
    _require(ip)
    component = str(activity or "").strip() or launcher_activity(ip, name)
    result = client.shell_result(ip, "am", "start", "-n", component)
    text = client.output(result)
    detail = _failed(text)
    if detail or getattr(result, "returncode", 0) != 0:
        raise VerificationError(detail or i18n.t("error.adbStartFailed",
                                                 package=name))
    return {"package": name, "action": "start", "activity": component}


def restart(ip: str, package: str, activity: str = "") -> dict:
    """Stop then start. One button, because that is what is actually wanted.

    The stop is not allowed to fail the restart: force-stopping an
    application that is not running is normal and is how a restart is used
    after a crash.
    """
    name = clean_package(package)
    _require(ip)
    try:
        stop(ip, name)
    except VerificationError:
        pass
    started = start(ip, name, activity)
    return {**started, "action": "restart"}


def uninstall(ip: str, package: str) -> dict:
    """Remove the application from the device."""
    name = clean_package(package)
    _require(ip)
    result = client.run("-s", client.target(ip), "uninstall", name)
    text = client.output(result)
    detail = _failed(text)
    if detail or getattr(result, "returncode", 0) != 0:
        raise VerificationError(detail or i18n.t("error.adbUninstallFailed",
                                                 package=name))
    return {"package": name, "action": "uninstall"}


def install(ip: str, path) -> dict:
    """Install an APK, reusing the install the firmware screen already has.

    NOT REIMPLEMENTED HERE, and the reason is worth the import: that
    function knows the four failures `adb install` reports as success, the
    downgrade retry, and how to prove afterwards that the version on the
    device is the version in the file. A second copy of that would be a
    second, worse copy.

    It takes a `Device` for its address alone, so a stand-in carrying just
    the address is what it gets — this screen has no DeviceMap and never
    will (see `panel.adb.pool`).
    """
    if not path:
        raise ValueError(i18n.t("error.adbNoApkChosen"))
    _require(ip)
    try:
        result = firmware.install_apk(_AddressOnly(ip), path,
                                      settings.ADB_INSTALL_TIMEOUT)
    finally:
        client.disconnect(ip)
    return {**result, "action": "install"}


class _AddressOnly:
    """The smallest thing `install_apk` accepts: something with an `ip`."""

    __slots__ = ("id", "ip", "name", "read_method")

    def __init__(self, ip: str):
        self.ip = str(ip)
        self.id = self.ip
        self.name = self.ip
        self.read_method = "adb"
