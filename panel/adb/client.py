#!/usr/bin/env python3
"""Running one ADB command against one explicitly named device.

THIS FILE IS THE ONLY PLACE THE PANEL EXECUTES ``adb``. It started inside the
Compartment LCD commissioning run (`panel.ip_assign.lcd_runner`), because that
is where the rules were learned, and it was copied from there each time
another screen needed a device command. Three copies meant three answers to
"what happens when adb is missing" and three different timeouts; this is the
one answer. The last two private copies — the probe's
(`panel.probe.android`) and the APK install's
(`panel.firmware.apk_install`) — ran their own ``subprocess`` with their
own connect proofs, so the same display at the same moment could be red on
the scan and green on the ADB screen. Both run on this file now, and a test
scans their sources to keep it that way (tests/test_adb.py::OneTransport).

The rules the run paid for, and which every caller now inherits:

* **Every command names its device.** ``-s <ip>:5555``, always. Changing a
  display's address leaves both the old and the new TCP serial in the ADB
  server, so a command without ``-s`` reaches whichever of them the server
  feels like — and ``adb devices`` is never consulted for the same reason.
* **Connecting is not believing.** `connect_once` also asks the serial for
  its state, because ``adb connect`` reports success against an address that
  answers a TCP handshake and nothing more.
* **Every wait is bounded** (`settings.ADB_TIMEOUT`), and a wait that runs
  out is `AdbTimeout` rather than a hang.

`AdbUnavailable` and `AdbTimeout` USED TO BE PLAIN RuntimeErrors, which is
how "adb is not installed on this computer" reached the screen as "an
unexpected device problem". They are `DeviceError`s now — the classification
the rest of the panel already uses to decide what the operator should go and
do (`panel.errors`): a missing executable is nothing to do with the device
(N/A), and a timed-out command is a device that did not answer.
"""
from __future__ import annotations

import shlex
import subprocess
import threading
from contextlib import contextmanager

from .. import clock, settings
from ..errors import NotApplicableError, UnreachableError, VerificationError
from .. import i18n
from ..system.spawn import NO_CONSOLE
from .binary import adb_path

# How many times a reconnect is attempted, and how long between attempts.
# Sized for the commissioning run: the display has just had its PoE port
# switched back on and is still coming up.
CONNECT_ATTEMPTS = 12
CONNECT_RETRY_INTERVAL = 2.0


class AdbUnavailable(NotApplicableError):
    """The host cannot execute ADB at all."""

    title = i18n.lazy("error.adbMissing")


class AdbTimeout(UnreachableError):
    """One ADB command exceeded its bounded wait."""

    title = i18n.lazy("error.adbTimeout")


def run(*args: str, timeout: float | None = None):
    """Run ADB without ever relying on its implicit current device.

    `NO_CONSOLE` because this is the panel's hottest spawn point: a run over
    thirty displays is hundreds of adb calls, and on the console-less Windows
    build every one of them opened its own terminal window over the screen
    (`panel.system.spawn` tells the story).
    """
    try:
        return subprocess.run(
            [adb_path(), *args], capture_output=True, text=True,
            timeout=(settings.ADB_TIMEOUT if timeout is None else timeout),
            check=False, **NO_CONSOLE)
    except FileNotFoundError as exc:
        raise AdbUnavailable(i18n.t("error.adbMissing")) from exc
    except subprocess.TimeoutExpired as exc:
        # The verb, not the routing flag: every command opens with
        # `-s <serial>`, and naming that produced "adb -s timed out" for
        # every timeout in the panel.
        verb = "adb"
        if args:
            verb = (args[2] if args[0] == "-s" and len(args) > 2
                    else args[0])
        raise AdbTimeout(i18n.t("error.adbCommandTimeout",
                                command=verb)) from exc


def target(ip: str) -> str:
    return f"{ip}:{settings.ADB_PORT}"


# ── the connection lease ─────────────────────────────────────────────────
# The transport to one serial is GLOBAL to this process's ADB server, and two
# subsystems really do use the same one at the same time: the light refresh
# reads a Compartment LCD while the firmware screen installs an APK on it.
# Each side politely disconnects when it is done — which is exactly the tear
# that was reported from the bench: the scan's cleanup pulled the transport
# out from under an install that was half way through.
#
# A lease is a per-serial reference count. Whoever needs the transport to
# SURVIVE for a span takes one (`with client.lease(ip):`), and `disconnect`
# below declines to drop a serial while any lease on it is active. Nothing
# else changes: a caller that never leases — the ADB screen's runner, the
# commissioning run — keeps its explicit connect/disconnect behaviour to the
# letter, because with no lease held the count is zero and `disconnect` does
# what it always did.
#
# Deadlock-free by construction: the one lock guards only the dict of counts
# and is never held across a subprocess call (or any other lock).
_lease_lock = threading.Lock()
_leases: dict[str, int] = {}


@contextmanager
def lease(ip: str):
    """Keep the transport to `ip` alive for the length of the block.

    Reentrant across threads and within one: every entry counts, every exit
    uncounts, and only the count matters. The holder's own `disconnect`
    calls are skipped too — so a caller that wants the serial really dropped
    afterwards disconnects AFTER its `with` block, where the drop happens
    unless somebody else still holds a lease.
    """
    serial = target(ip)
    with _lease_lock:
        _leases[serial] = _leases.get(serial, 0) + 1
    try:
        yield
    finally:
        with _lease_lock:
            remaining = _leases.get(serial, 1) - 1
            if remaining > 0:
                _leases[serial] = remaining
            else:
                _leases.pop(serial, None)


def leased(ip: str) -> bool:
    """Is any lease on this serial active right now?"""
    with _lease_lock:
        return _leases.get(target(ip), 0) > 0


def disconnect(ip: str, *, timeout: float | None = None,
               force: bool = False) -> None:
    if not ip:
        return
    # An active lease means the transport is in use somewhere in this
    # process — a scan tidying up after itself must not cut off the APK
    # install sharing the same serial. Skipped, not deferred: the last
    # lease-holder's own cleanup disconnect runs after its lease is
    # released and really drops the serial then.
    #
    # `force` is the commissioning run's word: the LCD flow REQUIRES the
    # old transport gone before the address changes — its safety proof
    # depends on it — and it must not be vetoed by a background read that
    # happened to lease the same serial a moment earlier.
    if leased(ip) and not force:
        return
    try:
        run("disconnect", target(ip), timeout=timeout)
    except Exception:
        # Cleanup must neither hide the caller's result nor prevent a PoE
        # restore.
        pass


def connect_once(ip: str, *, timeout: float | None = None) -> bool:
    """Connect and prove that this exact TCP serial is in ``device`` state."""
    serial = target(ip)
    command_timeout = (min(settings.ADB_TIMEOUT, 5) if timeout is None
                       else timeout)
    # Disconnect-first keeps a stale row from answering for the device. Under
    # an active lease it is skipped (see `disconnect`), and that is the right
    # trade: a leased serial is a transport this process is USING, which is
    # better evidence of life than a fresh handshake — and `get-state` below
    # still has to answer ``device`` on it either way.
    disconnect(ip, timeout=command_timeout)
    try:
        connected = run("connect", serial, timeout=command_timeout)
    except AdbTimeout as exc:
        # Named for what hung: "adb connect timed out" sends the operator to
        # the device's network, where the generic per-command wording sends
        # them to the adb server. The probe used to make this distinction in
        # its own wrapper; it lives with the command now.
        raise AdbTimeout(i18n.t("error.adbConnectTimeout")) from exc
    if getattr(connected, "returncode", 0) != 0:
        return False
    state = run("-s", serial, "get-state", timeout=command_timeout)
    return (getattr(state, "returncode", 0) == 0
            and str(getattr(state, "stdout", "") or "").strip() == "device")


def connect(ip: str, cancelled=None, attempts: int = CONNECT_ATTEMPTS,
            *, timeout: float | None = None) -> bool:
    """Bounded reconnect; stale ``adb devices`` rows are never consulted.

    `timeout` bounds each single adb command inside an attempt, not the
    whole call — the shape the probe's read budget has always had ("the
    ceiling on any single hang"). Left `None`, `connect_once` keeps its own
    short per-command bound.
    """
    for attempt in range(max(1, int(attempts))):
        if cancelled is not None and cancelled():
            return False
        try:
            if connect_once(ip, timeout=timeout):
                return True
        except AdbUnavailable:
            raise
        except Exception:
            pass
        if attempt + 1 < attempts and CONNECT_RETRY_INTERVAL:
            clock.sleep(CONNECT_RETRY_INTERVAL)
    return False


def listed(timeout: float | None = None) -> set[str]:
    """The serials `adb devices` reports as ready, right now.

    THE ONE PLACE THIS IS ASKED, and only for the screen that shows it. Every
    operation still proves its own transport with `connect_once` rather than
    trusting a row here — the note at the top of this file says why: an
    `adb devices` row survives the display being unplugged, so believing one
    means sending a command into a socket that is not there.

    What the list IS good for is answering "which of my addresses is actually
    attached", which is a question about the ADB server rather than about any
    one device.
    """
    result = run("devices", timeout=timeout)
    ready = set()
    for line in str(getattr(result, "stdout", "") or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            ready.add(parts[0])
    return ready


# ── the ADB server itself ───────────────────────────────────────────────
# Everything above talks to a DEVICE. These two talk to the daemon on this
# computer that all of it goes through, and it is a thing that gets stuck: a
# display that changed address, a laptop that slept with transports open, a
# second `adb` from Android Studio claiming the port. The symptom is always
# the same and always misleading — every device on the bench "cannot be
# reached", so the operator goes looking at cables.
#
# `kill-server` + `start-server` is the fix, and it is safe in the sense that
# matters here: it drops every transport, which is exactly what is wanted, and
# no device is touched. WHAT IT IS NOT SAFE FOR is running while commands are
# in flight — see `panel.adb.runner`, which only ever does this between
# rounds, never inside one.


def server_ok(timeout: float | None = None) -> bool:
    """Is the local ADB server answering at all?

    `adb devices` is the cheapest question that reaches it. An empty list is
    a fine answer — "no displays attached" is not "the server is wedged".
    """
    try:
        result = run("devices", timeout=timeout if timeout is not None else 5)
    except AdbUnavailable:
        raise
    except Exception:
        return False
    return getattr(result, "returncode", 1) == 0


def restart_server(timeout: float | None = None) -> dict:
    """Stop the local ADB server and start it again.

    Both halves, and the second one explicitly: `kill-server` alone leaves the
    next command to start the daemon implicitly, which it does — while the
    caller is timing it. Starting it here means the cost is paid once, now,
    by the operator who asked for it.
    """
    limit = timeout if timeout is not None else 15
    killed = run("kill-server", timeout=limit)
    started = run("start-server", timeout=limit)
    return {"action": "restart_server",
            "ok": getattr(started, "returncode", 1) == 0,
            "detail": output(started) or output(killed)}


def shell_result(ip: str, *command: str, timeout: float | None = None):
    """The raw result of a shell command on one named transport.

    For callers that have to read the exit code AND the output. ``am start``
    is the reason this is public: it exits 0 while printing an Error line
    when the activity does not exist, so a caller that trusts either half
    alone reports a launch that never happened.
    """
    return run("-s", target(ip), "shell", *command, timeout=timeout)


def shell(ip: str, *command: str, timeout: float | None = None) -> str:
    """Run a shell command on one explicitly named Android transport."""
    result = shell_result(ip, *command, timeout=timeout)
    if getattr(result, "returncode", 0) != 0:
        detail = (str(getattr(result, "stderr", "") or "").strip()
                  or str(getattr(result, "stdout", "") or "").strip())
        raise RuntimeError(detail[:160] or "adb shell failed")
    return str(getattr(result, "stdout", "") or "").strip()


def restart_as_root(ip: str, *, timeout: float | None = None) -> bool:
    """Ask adbd to restart as root. True once it really is root.

    On a userdebug image this is what makes /system writable at all — the
    unprivileged `su` route cannot do it on a device whose /system sits on a
    verity-backed device-mapper volume, because the kernel there accepts the
    file's metadata and silently drops its contents.

    adbd DIES AND COMES BACK, so the transport has to be rebuilt afterwards;
    `connect` is what proves it is really up rather than the command's own
    cheerful answer.
    """
    result = run("-s", target(ip), "root",
                 timeout=timeout if timeout is not None else 30)
    answer = output(result).lower()
    if "cannot run as root" in answer or "not permitted" in answer:
        return False                      # a user build: nothing to retry
    disconnect(ip)
    if not connect(ip, attempts=6):
        return False
    return "uid=0" in output(shell_result(ip, "id"))


def overlay_remount(ip: str, *, timeout: float | None = None) -> bool:
    """Make /system writable, by overlay if the image needs one.

    `adb remount` is the only thing that arranges this correctly on Android
    10 and later: it mounts an overlayfs whose upper layer lives on
    /mnt/scratch, so a write lands somewhere that is actually written.
    Remounting the read-only volume by hand looks like it worked and is not
    the same thing at all.
    """
    result = run("-s", target(ip), "remount",
                 timeout=timeout if timeout is not None else 60)
    answer = output(result).lower()
    return ("remount succeeded" in answer or "overlayfs" in answer
            or "now reboot" in answer)


def output(result) -> str:
    """stdout and stderr of one command, joined — adb uses both."""
    return f"{getattr(result, 'stdout', '') or ''}\n" \
           f"{getattr(result, 'stderr', '') or ''}".strip()


# ── running a SCRIPT, as opposed to a command ────────────────────────────
# `adb shell a b c` DOES NOT QUOTE ITS ARGUMENTS. It joins them with spaces
# and hands the result to the device's shell, so
#
#     shell(ip, "sh", "-c", "mount -o rw,remount /; cp a b")
#
# arrives on the device as
#
#     sh -c mount -o rw,remount /; cp a b
#
# — `sh -c mount` runs, and everything after the first `;` runs SEPARATELY,
# as whatever user adbd happens to be. Measured on a live display, not
# guessed: the first half of a root transaction succeeded and the rest ran
# unprivileged and failed, which looked exactly like "the write did not
# work" with no indication why.
#
# So anything with a space, a semicolon or a redirection in it goes through
# here, where it is quoted into ONE argument before adb joins them.
#
# `shell()` above is left alone and is still right for the many callers that
# pass a plain word list (`getprop ro.serialno`, `pm list packages`).
def script(ip: str, text: str, *, timeout: float | None = None):
    """Run a whole shell script on the device, as the adbd user."""
    return shell_result(ip, "sh", "-c", shlex.quote(text), timeout=timeout)


class NoRootShell(VerificationError):
    """This device offers no `su` that actually yields root."""

    title = i18n.lazy("error.adbNoRootShell")


# HOW A ROOT SHELL IS ASKED FOR, in the order the forms are tried.
#
# There is no single answer, which is the whole reason this is a list. The
# Compartment LCDs carry a Magisk-style `su` that takes `-c`. The Android
# displays built on AOSP carry TOYBOX `su`, whose usage is
# `su [WHO [COMMAND...]]` — it reads `-c` as a user name and answers
# "invalid uid/gid '-c'". A panel that only knows one of the two reports a
# perfectly rootable device as unwritable.
#
# `su 0 sh -c` is first because it is understood by both.
SU_FORMS = (
    ("su", "0", "sh", "-c"),
    ("su", "-c"),
    ("su", "root", "sh", "-c"),
)


def root_form(ip: str, *, timeout: float | None = None) -> tuple[str, ...]:
    """Which `su` form this device accepts — PROVED, not assumed.

    Every candidate is asked to run `id`, and only a reply containing
    `uid=0` counts. A form that is merely accepted proves nothing: toybox
    `su -c` exits non-zero with a usage error, and a caller reading only the
    exit code of the transaction that follows would take the failure for a
    device that has no root.
    """
    for form in SU_FORMS:
        try:
            proved = output(shell_result(ip, *form, "id", timeout=timeout))
        except AdbUnavailable:
            raise
        except Exception:
            continue
        if "uid=0" in proved:
            return form
    raise NoRootShell(i18n.t("error.adbNoRootShell"))


def root_script(ip: str, text: str, *, form: tuple[str, ...] | None = None,
                timeout: float | None = None):
    """Run a whole shell script as root. See `script` for the quoting."""
    chosen = form or root_form(ip, timeout=timeout)
    return shell_result(ip, *chosen, shlex.quote(text), timeout=timeout)
