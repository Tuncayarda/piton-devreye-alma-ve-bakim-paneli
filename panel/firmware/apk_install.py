#!/usr/bin/env python3
"""Compartment LCD — APK install over adb.

The device is Android, so `adb install -r` does the work. The version check
comes from the same place as the probe layer (dumpsys package →
probe.android.package_info), so "installed" and the version on screen come
from one source.

Installing does not reboot the device; the app itself is reinstalled. So
there is no "wait for the device to come back" step as on the HTTP path —
verification happens directly.
"""
from __future__ import annotations

import subprocess

from .. import settings
from ..errors import NotApplicableError, UnreachableError, VerificationError
from ..inventory.device_map import Device
from ..probe.android import package_info
from .. import i18n

KNOWN_FAILURES = {
    "INSTALL_FAILED_INVALID_APK": "The file is not a valid APK",
    "INSTALL_FAILED_VERSION_DOWNGRADE":
        "The version on the device is newer; a downgrade was refused",
    "INSTALL_FAILED_UPDATE_INCOMPATIBLE":
        "The APK was built with a different signature — uninstall the current app first",
    "INSTALL_FAILED_INSUFFICIENT_STORAGE": "The device is out of space",
    "INSTALL_PARSE_FAILED": "The APK could not be parsed",
    "device unauthorized": "The device has not authorised adb (the prompt on "
                           "its screen may need accepting)",
    "device offline": "The device is not connected to adb",
    "no devices/emulators found": "Could not connect to the device with adb "
                                  "(port 5555 may be closed)",
}


def _adb(*args: str, timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["adb", *args], capture_output=True, text=True,
                              timeout=timeout)
    except FileNotFoundError:
        raise NotApplicableError(
            i18n.t("error.adbInstallMissing"))
    except subprocess.TimeoutExpired:
        raise UnreachableError(i18n.t("error.adbCommandTimeout",
                                      command=args[0]))


def _installed_version(target: str, timeout: int) -> str:
    result = _adb("-s", target, "shell", "dumpsys", "package",
                  settings.ADB_PACKAGE, timeout=timeout)
    return package_info(result.stdout or "")["version"]


def _failure_message(output: str) -> str:
    """Reduce adb install output to one readable line."""
    for marker, message in KNOWN_FAILURES.items():
        if marker in output:
            return f"The APK could not be installed: {message}"
    first = next((line for line in output.splitlines() if line.strip()), "")
    return (f"The APK could not be installed: {first[:160]}" if first
            else "The APK could not be installed")


def install_apk(device: Device, path, expected: str,
                verify_window: float) -> dict:
    target = f"{device.ip}:{settings.ADB_PORT}"
    timeout = settings.ADB_TIMEOUT
    install_timeout = max(int(verify_window), settings.ADB_INSTALL_TIMEOUT)

    _adb("connect", target, timeout=timeout)
    try:
        # The app may not be installed at all; that is a first install, not an
        # error. Whether the device is reachable shows up in the install
        # output.
        previous = _installed_version(target, timeout) or ""

        result = _adb("-s", target, "install", "-r", str(path),
                      timeout=install_timeout)
        output = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
        # The package manager refuses when the installed version is newer.
        # Downgrading is sometimes needed in the field, so it is retried with
        # -d (not sent every time: some devices disable downgrades and reject
        # the whole command).
        if "INSTALL_FAILED_VERSION_DOWNGRADE" in output:
            result = _adb("-s", target, "install", "-r", "-d", str(path),
                          timeout=install_timeout)
            output = f"{result.stdout or ''}\n{result.stderr or ''}".strip()

        if "Success" not in output:
            raise VerificationError(_failure_message(output))

        current = _installed_version(target, timeout)
        if not current:
            raise VerificationError(
                i18n.t("error.apkVerifyFailed",
                       package=settings.ADB_PACKAGE))
        if expected and current.strip() != str(expected).strip():
            raise VerificationError(
                i18n.t("error.versionMismatch", current=current,
                   expected=expected))
        return {"previous": previous, "current": current,
                "changed": bool(previous) and previous != current}
    finally:
        _adb("disconnect", target, timeout=timeout)
