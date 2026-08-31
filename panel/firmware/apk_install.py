#!/usr/bin/env python3
"""Compartment LCD — APK install over adb.

The device is Android, so `adb install -r` does the work.  The selected APK's
own manifest supplies its package name; the version check then comes from the
same parser as the probe layer (dumpsys package → probe.android.package_info).
That also permits a temporary test application without weakening the
post-install proof to adb's word "Success" alone.

Installing does not reboot the device; the app itself is reinstalled. So
there is no "wait for the device to come back" step as on the HTTP path —
verification happens directly.

The TRANSPORT is `panel.adb.client` and nothing else — this file's private
``subprocess`` wrapper was the panel's third copy of the adb rules, with its
own timeouts and its own idea of a connect. What stays here is only what is
install-specific: `install -r`, the downgrade retry with `-d`, the
translation of adb's failure markers, and the install's own long timeout.
"""
from __future__ import annotations

from .. import settings
from ..adb import client
from ..errors import NotApplicableError, UnreachableError, VerificationError
from ..inventory.device_map import Device
from ..probe.android import package_info
from .. import i18n
from .apk_metadata import ApkMetadataError, read_apk_metadata

# adb marker -> the catalogue key explaining it. Keys, not sentences: this
# table is built at import time, long before a language is chosen.
KNOWN_FAILURES = {
    "INSTALL_FAILED_INVALID_APK": "error.apkInvalid",
    "INSTALL_FAILED_VERSION_DOWNGRADE": "error.apkDowngrade",
    "INSTALL_FAILED_UPDATE_INCOMPATIBLE": "error.apkSignature",
    "INSTALL_FAILED_INSUFFICIENT_STORAGE": "error.apkNoSpace",
    "INSTALL_PARSE_FAILED": "error.apkParseFailed",
    "device unauthorized": "error.adbUnauthorized",
    "device offline": "error.adbOffline",
    "no devices/emulators found": "error.adbNoDevice",
}


def _installed_version(ip: str, package: str, timeout: int) -> str:
    result = client.shell_result(ip, "dumpsys", "package", package,
                                 timeout=timeout)
    return package_info(str(getattr(result, "stdout", "") or ""))["version"]


def _install(ip: str, path, timeout: int, *, downgrade: bool = False):
    """One `adb install -r` (optionally `-d`), output joined the adb way."""
    flags = ("-r", "-d") if downgrade else ("-r",)
    result = client.run("-s", client.target(ip), "install", *flags,
                        str(path), timeout=timeout)
    return result, client.output(result)


def _failure_message(output: str) -> str:
    """Reduce adb install output to one readable line."""
    for marker, key in KNOWN_FAILURES.items():
        if marker in output:
            return i18n.t("error.apkInstallFailedWhy", reason=i18n.t(key))
    first = next((line for line in output.splitlines() if line.strip()), "")
    if first:
        # adb's own words, untranslated: they are the device's answer, not
        # ours, and looking them up needs them verbatim.
        return i18n.t("error.apkInstallFailedWhy", reason=first[:160])
    return i18n.t("error.apkInstallFailed")


def install_apk(device: Device, path, verify_window: float) -> dict:
    # Do not assume every selected APK is the panel application's package.
    # Test/commissioning installs intentionally include ordinary Android apps.
    # Reading the identity from the selected payload before touching the device
    # lets the post-install check address the exact package that was chosen.
    try:
        metadata = read_apk_metadata(path)
    except ApkMetadataError as exc:
        raise VerificationError(i18n.t("error.apkInvalid")) from exc
    package = metadata["package"]
    # The version to confirm afterwards comes from the chosen APK's own
    # manifest. Nobody types one: a hand-entered "expected version" only ever
    # repeated what the file already states, and got it wrong.
    verify_version = str(metadata["version"] or "").strip()

    ip = device.ip
    timeout = settings.ADB_TIMEOUT
    install_timeout = max(int(verify_window), settings.ADB_INSTALL_TIMEOUT)

    try:
        # The lease keeps a concurrent scan's polite cleanup from dropping
        # this transport half way through the install — the tear that was
        # actually reported (see panel/adb/client.py, "the connection
        # lease").
        with client.lease(ip):
            if not client.connect(ip, attempts=2, timeout=timeout):
                raise UnreachableError(i18n.t("error.adbNoConnection"))
            # The app may not be installed at all; that is a first install,
            # not an error.
            previous = _installed_version(ip, package, timeout) or ""

            result, output = _install(ip, path, install_timeout)
            # The package manager refuses when the installed version is
            # newer. Downgrading is sometimes needed in the field, so it is
            # retried with -d (not sent every time: some devices disable
            # downgrades and reject the whole command).
            if "INSTALL_FAILED_VERSION_DOWNGRADE" in output:
                result, output = _install(ip, path, install_timeout,
                                          downgrade=True)

            succeeded = (getattr(result, "returncode", 1) == 0
                         and any(line.strip() == "Success"
                                 for line in output.splitlines()))
            if not succeeded:
                raise VerificationError(_failure_message(output))

            current = _installed_version(ip, package, timeout)
            if not current:
                raise VerificationError(
                    i18n.t("error.apkVerifyFailed",
                           package=package))
            if verify_version and current.strip() != verify_version:
                raise VerificationError(
                    i18n.t("error.versionMismatch", current=current,
                           expected=verify_version))
            return {"previous": previous, "current": current,
                    "changed": bool(previous) and previous != current,
                    "package": package}
    except client.AdbUnavailable as exc:
        # The shared transport says "adb is missing" in the probe's words;
        # this screen's operator is trying to INSTALL, so the sentence has
        # to say what cannot happen here.
        raise NotApplicableError(i18n.t("error.adbInstallMissing")) from exc
    finally:
        # After the lease is released: drops the serial for real when this
        # install was its only user, and is skipped by `client.disconnect`
        # when something else — another read — still leases it.
        client.disconnect(ip, timeout=timeout)
