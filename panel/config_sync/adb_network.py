#!/usr/bin/env python3
"""The one setting a Compartment LCD has on the device settings screen.

Every other device on that screen is configured over HTTP: the panel posts a
body to the endpoint the device's own web UI posts to, then reads the settings
back. An Android display has no such API. What it does have is ADB, which the
commissioning run already uses to move a display between train sets — and the
address is the one setting worth changing on a display from a settings screen
in the first place.

So this module is deliberately narrow. It reads what the display reports about
itself, and it writes ONE thing: the address on eth0. Everything else about
the display's network — the prefix it is using — is preserved rather than
decided here, exactly as the intercom write preserves the netmask it finds.

WHAT MAKES A WRITE SUCCESSFUL is the same rule as the run's: not the command's
reply, which the address change itself commonly cuts off, but a fresh ADB
connection to the NEW address answering with the SAME Android serial and
nothing but the new address on eth0.
"""
from __future__ import annotations

from ..errors import UnreachableError, VerificationError
from ..inventory.device_map import Device
from .. import ip_assign
from ..ip_assign import lcd_runner
from ..probe import android
from .. import i18n

# How many times to knock while the display comes back after the change. The
# run's own default is generous because it has just powered the port on; here
# the display was already up and only its address moved.
RECONNECT_ATTEMPTS = 6


def _split(cidr: str) -> tuple[str, int]:
    address, _, prefix = str(cidr).partition("/")
    try:
        return address, int(prefix)
    except ValueError:
        return address, ip_assign.effective_prefix()


def current_address(ip: str) -> tuple[str, int]:
    """The single global IPv4 address on eth0, and its prefix.

    More than one address is not resolved by guessing: a display holding both
    an old and a new address is exactly the state a half-finished run leaves
    behind, and picking one of them would hide it.
    """
    found = sorted(lcd_runner.addresses(ip))
    if not found:
        raise VerificationError(i18n.t("error.lcdNoAddress"))
    if len(found) > 1:
        raise VerificationError(
            i18n.t("error.lcdSeveralAddresses", addresses=", ".join(found)))
    return _split(found[0])


def _app_details(device: Device) -> dict:
    """What the panel application reports — never raises.

    Deliberately not allowed to fail the read. The probe layer treats an
    unreadable application version as a device fault, and rightly so: a
    display with no app installed is not a working display. But the one row
    this screen can WRITE is the address, and an address is perfectly
    readable and writable on a display whose app is missing — which is
    exactly the display someone is most likely to be repairing.
    """
    try:
        return android.read(device.ip)
    except Exception:
        return {}


def read(device: Device) -> dict:
    """What the settings screen shows for a display, as a flat dict.

    The keys are the ones the field table already searches for (see
    panel.probe.fields), so the display's answer lands in the same rows as
    every other device's.
    """
    if not lcd_runner.connect(device.ip, attempts=2):
        raise UnreachableError(i18n.t("error.adbNoConnection"))
    try:
        address, prefix = current_address(device.ip)
        serial = lcd_runner.serial_of(device.ip)
    finally:
        lcd_runner.disconnect(device.ip)
    data = _app_details(device)
    return {
        "ipaddress": address,
        "ipprefix": prefix,
        "serial": serial or data.get("serial", ""),
        "version": data.get("version", ""),
        # The display reports its registration under its own name; the field
        # table looks for the announcement equipment's. Translating it here
        # keeps one row definition for both.
        "sipstatus": data.get("sipRegistration", ""),
    }


def write_address(device: Device, target_ip: str) -> dict:
    """Move the display to `target_ip`, then prove it is the same display.

    The prefix is NOT changed: whatever eth0 is using stays. Changing the mask
    is a commissioning decision and belongs to the run that makes it (see the
    IP screen's mask field), not to a settings row that only says "address".
    """
    if not lcd_runner.connect(device.ip, attempts=2):
        raise UnreachableError(i18n.t("error.adbNoConnection"))
    try:
        before_serial = lcd_runner.serial_of(device.ip)
        _address, prefix = current_address(device.ip)
        if not before_serial:
            raise VerificationError(i18n.t("error.adbNoConnection"))
        lcd_runner.write_address(device.ip, target_ip, prefix)
    finally:
        lcd_runner.disconnect(device.ip)

    if not lcd_runner.connect(target_ip, attempts=RECONNECT_ATTEMPTS):
        raise VerificationError(
            i18n.t("error.lcdNotAtNewAddress", ip=target_ip))
    try:
        actual = lcd_runner.serial_of(target_ip)
        if actual != before_serial:
            raise VerificationError(
                i18n.t("error.lcdSerialChanged", expected=before_serial,
                       actual=actual or "?"))
        held = lcd_runner.addresses(target_ip)
        expected = f"{target_ip}/{prefix}"
        if held != {expected}:
            raise VerificationError(
                i18n.t("error.lcdWrongAddresses", expected=expected,
                       found=", ".join(sorted(held)) or "-"))
    finally:
        lcd_runner.disconnect(target_ip)
    return {"previous": device.ip, "current": target_ip, "prefix": prefix}


__all__ = ["current_address", "read", "write_address"]
