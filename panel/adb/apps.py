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

from .. import clock, firmware, i18n, settings
from ..errors import UnreachableError, VerificationError
from . import client

# `cmd package resolve-activity --brief` ends with the component, one per
# line, the last line being the resolved one.
_COMPONENT = re.compile(r"^[A-Za-z][\w.]*/[\w.$]+$")
# The fallback: the MAIN/LAUNCHER filter block inside `dumpsys package`.
_DUMPSYS_COMPONENT = re.compile(r"([A-Za-z][\w.]*)/([\w.$]+)")
# `am start` and `pm uninstall` both announce failure in their output.
_FAILURE = re.compile(r"^\s*(Error|Failure|Exception)\b", re.MULTILINE)
# How often a rebooting display is knocked on. Two seconds: the whole wait
# is a minute or more, and a tighter beat only spends ADB connections.
REBOOT_POLL = 2.0

# Actions the screen offers. Named here rather than in the route so the
# server and the runner cannot disagree about what exists.
OPERATIONS = ("connect", "restart_server", "start", "stop", "restart",
              "uninstall", "install", "reboot", "autostart_install",
              "autostart_remove")

# The ones that address the DEVICE rather than an application on it.
#
# This distinction is not decoration. A run carries (device, bundle) pairs,
# and a display with two selected bundles on it produces two of them — which
# for `stop` is exactly right and for `reboot` would send the machine the
# reboot command twice. So the runner collapses these to one row per address
# (see `panel.adb.runner._pairs`), and the bundle column stays empty because
# no bundle was involved in what happened.
DEVICE_OPERATIONS = ("connect", "install", "reboot", "restart_server")

# The one operation that reaches no device at all. It runs once, whatever is
# selected, and its row carries no address because none was involved.
HOST_OPERATIONS = ("restart_server",)

# Operations that must NOT be disconnected afterwards. Everything else here
# borrows a transport and gives it back (see `panel.adb.runner`); `connect`
# exists precisely to leave one behind, so that `adb devices` lists the
# display afterwards and another tool on this machine can reach it.
KEEP_CONNECTED = ("connect",)


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
def connect(ip: str) -> dict:
    """Attach one display and LEAVE IT ATTACHED.

    Every other operation on this screen connects, does its work and hands the
    transport back, because a serial left behind is a serial the next
    operation might reach by accident. This one is the deliberate exception:
    the operator wants their whole bench in `adb devices`, so that Android
    Studio, `adb logcat` or scrcpy on the same machine can see it too.

    Being connected and being LISTED are checked separately on purpose. The
    first is this panel's own handshake; the second is what the operator will
    actually look at in a terminal, and a display that passes the first and
    fails the second is exactly the case worth a warning rather than silence.
    """
    if not client.connect(ip, attempts=2):
        raise UnreachableError(i18n.t("error.adbNoConnection"))
    serial = client.target(ip)
    if serial not in client.listed():
        raise VerificationError(i18n.t("error.adbNotListed", serial=serial))
    return {"action": "connect", "serial": serial}


def restart_server(_ip: str = "") -> dict:
    """Stop and start the local ADB server.

    THE ADDRESS IS IGNORED. This is the one action on the screen that reaches
    no device: what is wrong is the daemon on this computer, and every display
    reporting "cannot be reached" at once is its signature rather than a bench
    full of dead hardware.
    """
    answer = client.restart_server()
    if not answer.get("ok"):
        raise UnreachableError(i18n.t("error.adbServerRestartFailed",
                                      detail=answer.get("detail", "")[:120]))
    return answer


def stop(ip: str, package: str) -> dict:
    """Force-stop the application. Stopping one that is not running is fine."""
    name = clean_package(package)
    _require(ip)
    result = client.shell_result(ip, "am", "force-stop", name)
    detail = _failed(client.output(result))
    if detail:
        raise VerificationError(detail)
    return {"package": name, "action": "stop"}


# What `monkey` prints when the package it was given has nothing to launch.
# It exits 0 either way, so the text is the only signal.
_MONKEY_NOTHING = "No activities found to run"


def _start_with_monkey(ip: str, name: str) -> dict:
    """Launch by package name, letting the device pick the activity.

    THE FALLBACK THAT MAKES "RESTART" WORK ON REAL DISPLAYS. `am start -n`
    needs a component, and resolving one needs the package to declare a
    MAIN/LAUNCHER activity that this build will admit to. Several of the
    bundles actually running on these panels do not: the launcher is disabled
    on a locked-down image, or the entry point is an alias `resolve-activity`
    will not return. Those packages start perfectly well — just not that way.

    `monkey` is Android's own tool for exactly this: given a package and the
    LAUNCHER category it starts whatever the launcher would have started,
    without anyone having to name it.
    """
    result = client.shell_result(
        ip, "monkey", "-p", name, "-c", "android.intent.category.LAUNCHER", "1")
    text = client.output(result)
    if _MONKEY_NOTHING in text or getattr(result, "returncode", 0) != 0:
        raise VerificationError(i18n.t("error.adbNoLauncherActivity",
                                       package=name))
    return {"package": name, "action": "start", "activity": ""}


def start(ip: str, package: str, activity: str = "") -> dict:
    """Launch the application.

    Two ways, in order: the named component if one can be resolved, and
    otherwise `monkey` (see above). The second is not a lesser path — for a
    package whose launcher activity cannot be resolved it is the only one,
    and before it existed "restart" simply reported that the bundle declared
    nothing to launch.
    """
    name = clean_package(package)
    _require(ip)
    component = str(activity or "").strip()
    if not component:
        try:
            component = launcher_activity(ip, name)
        except VerificationError:
            return _start_with_monkey(ip, name)
    result = client.shell_result(ip, "am", "start", "-n", component)
    text = client.output(result)
    detail = _failed(text)
    if detail or getattr(result, "returncode", 0) != 0:
        # The component resolved but the device would not start it. Worth one
        # more go through monkey: a stale or aliased component name is the
        # usual reason, and monkey does not use one.
        try:
            return _start_with_monkey(ip, name)
        except VerificationError:
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


def reboot(ip: str) -> dict:
    """Restart the display itself, and wait for it to come back.

    WAITING IS THE POINT, and it is why this does not simply fire the
    command and return. `adb reboot` answers the moment the device accepts
    it, which is several seconds before anything actually happens and a full
    minute before the display is usable. Reported as done at that instant,
    the table would go green on twelve displays that are all still dark —
    and the one that never comes back would look exactly like the eleven
    that did. So the run holds the row open until the address answers again,
    which is the thing the operator would otherwise walk over and check.

    Both waits go through `panel.clock`, so the test suite does not spend
    two real minutes per device proving this.
    """
    _require(ip)
    result = client.run("-s", client.target(ip), "reboot")
    text = client.output(result)
    detail = _failed(text)
    if detail or getattr(result, "returncode", 0) != 0:
        raise VerificationError(detail or i18n.t("error.adbRebootFailed"))
    # The transport to the old session is finished either way; leaving it in
    # the ADB server means the "is it back?" test can be answered by a stale
    # entry rather than by the device.
    client.disconnect(ip)

    started = clock.monotonic()
    if not _wait_until(ip, up=False, limit=settings.ADB_REBOOT_DOWN_WAIT):
        # It answered the whole time. Either the command was ignored or this
        # is not a device that reboots — saying "done" would be a guess.
        raise VerificationError(i18n.t("error.adbRebootNotTaken"))
    if not _wait_until(ip, up=True, limit=settings.ADB_REBOOT_WAIT):
        raise VerificationError(
            i18n.t("error.adbRebootNoReturn",
                   seconds=int(settings.ADB_REBOOT_WAIT)))
    return {"action": "reboot",
            "seconds": round(clock.monotonic() - started, 1)}


def _wait_until(ip: str, *, up: bool, limit: float) -> bool:
    """Poll until the address is reachable (or is not). True if it happened."""
    deadline = clock.monotonic() + max(0.0, float(limit))
    while True:
        try:
            # One attempt per look: `connect` retries internally, and a
            # retry loop inside a poll loop makes the real wait unknowable.
            reachable = client.connect(ip, attempts=1)
        except Exception:
            reachable = False
        finally:
            client.disconnect(ip)
        if reachable == up:
            return True
        if clock.monotonic() >= deadline:
            return False
        clock.sleep(REBOOT_POLL)


class _AddressOnly:
    """The smallest thing `install_apk` accepts: something with an `ip`."""

    __slots__ = ("id", "ip", "name", "read_method")

    def __init__(self, ip: str):
        self.ip = str(ip)
        self.id = self.ip
        self.name = self.ip
        self.read_method = "adb"
