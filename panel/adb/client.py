#!/usr/bin/env python3
"""Running one ADB command against one explicitly named device.

THIS FILE IS THE ONLY PLACE THE PANEL EXECUTES ``adb``. It started inside the
Compartment LCD commissioning run (`panel.ip_assign.lcd_runner`), because that
is where the rules were learned, and it was copied from there each time
another screen needed a device command. Three copies meant three answers to
"what happens when adb is missing" and three different timeouts; this is the
one answer.

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

from .. import clock, settings
from ..errors import NotApplicableError, UnreachableError, VerificationError
from .. import i18n
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
    """Run ADB without ever relying on its implicit current device."""
    try:
        return subprocess.run(
            [adb_path(), *args], capture_output=True, text=True,
            timeout=(settings.ADB_TIMEOUT if timeout is None else timeout),
            check=False)
    except FileNotFoundError as exc:
        raise AdbUnavailable(i18n.t("error.adbMissing")) from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbTimeout(i18n.t("error.adbCommandTimeout",
                                command=args[0] if args else "adb")) from exc


def target(ip: str) -> str:
    return f"{ip}:{settings.ADB_PORT}"


def disconnect(ip: str, *, timeout: float | None = None) -> None:
    if not ip:
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
    disconnect(ip, timeout=command_timeout)
    connected = run("connect", serial, timeout=command_timeout)
    if getattr(connected, "returncode", 0) != 0:
        return False
    state = run("-s", serial, "get-state", timeout=command_timeout)
    return (getattr(state, "returncode", 0) == 0
            and str(getattr(state, "stdout", "") or "").strip() == "device")


def connect(ip: str, cancelled=None, attempts: int = CONNECT_ATTEMPTS) -> bool:
    """Bounded reconnect; stale ``adb devices`` rows are never consulted."""
    for attempt in range(max(1, int(attempts))):
        if cancelled is not None and cancelled():
            return False
        try:
            if connect_once(ip):
                return True
        except AdbUnavailable:
            raise
        except Exception:
            pass
        if attempt + 1 < attempts and CONNECT_RETRY_INTERVAL:
            clock.sleep(CONNECT_RETRY_INTERVAL)
    return False


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
