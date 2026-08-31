#!/usr/bin/env python3
"""Devices the panel reads through PISCU's MQTT broker.

PISCU, HMI, ICU, AP, LED and the Landing LCD are never contacted directly;
their state comes from RETAINED broker messages. Reading a retained message
is NOT proof the device exists — it stays in the broker after the device is
gone. An unplugged HMI was shown green "verified" while the note it displayed
literally said "disconnected".

Two independent signals exist and both are checked:

  ALFA/AppStatus/…  Status: "connected" | "disconnected"
      A dead device's last will stays retained as "disconnected", and that
      payload carries no DeviceIP, HWID or Version at all.

  ALFA/DeviceMap    Status.NoError
      PISCU watches every device; a down device reports NoError=false and
      Uptime=-1. That is a LIVE signal, not a tombstone.

`Has Network Failure` is deliberately unused: a healthy PISCU reports true on
its own record, so it does not mean "device missing".
"""
from __future__ import annotations

from .. import settings
from ..errors import UnreachableError, VerificationError
from ..inventory.device_map import Device
from .. import i18n

CONNECTED = "connected"


def _live_state(device: Device, telemetry) -> dict:
    return ((telemetry.record(device.ip) if telemetry else None) or {}
            ).get("Status") or {}


def _reported_faulty(device: Device, telemetry) -> bool:
    """Does the live DeviceMap explicitly report this device down?

    No record returns False — absence is not proof of failure; the caller
    judges that case in its own context.
    """
    state = _live_state(device, telemetry)
    return bool(state) and state.get("NoError") is not True


def _map_uptime(device: Device, telemetry):
    """Uptime from the device's DeviceMap record (None when absent).

    For a device that is off, PISCU remembers the last known value and sends
    Uptime -1; -1 is not an uptime and is not written.
    """
    record = telemetry.record(device.ip) if telemetry else None
    state = (record or {}).get("Status") or {}
    value = state.get("Uptime")
    try:
        return value if float(value) >= 0 else None
    except (TypeError, ValueError):
        return None


def from_device_map(device: Device, telemetry) -> dict:
    """Common fields from the MQTT DeviceMap record."""
    record = telemetry.record(device.ip) if telemetry else None
    if not record:
        raise VerificationError(i18n.t("error.piscuNoStatus"))
    state = record.get("Status") or {}
    if state.get("NoError") is not True:
        # This used to be "not applicable" (grey). Wrong: grey means "this
        # check does not exist on this device", but the check DID run and the
        # device reported a FAULT. Showing a dead device as N/A read as fine.
        raise UnreachableError(
            i18n.t("error.piscuDeviceDown"))
    return {
        "version": state.get("Version") or "",
        "serial": record.get("SerialNumber") or "",
        "uptime": state.get("Uptime"),
        "note": i18n.t("probe.mqttLiveNote"),
    }


def from_app_status(device: Device, telemetry) -> dict:
    """PISCU / HMI — the ALFA/AppStatus message.

    The AppStatus payload has NO uptime (ClientId, DeviceIP, HWID, Status,
    Version). Uptime lives on the same device's DeviceMap record; without
    merging the two, these devices' uptime column stayed empty.
    """
    keyword = "PISCU" if device.type == "PISCU" else "MCP"
    record = (telemetry.app_record(device.ip, keyword) if telemetry else None)
    if not record:
        raise VerificationError(
            i18n.t("error.noAppStatus", keyword=keyword,
                   prefix=settings.MQTT_APP_STATUS_PREFIX))

    # The message EXISTING does not mean the device is up (see CONNECTED).
    state = str(record.get("Status") or "").strip().lower()
    if state and state != CONNECTED:
        raise UnreachableError(
            i18n.t("error.brokerDisconnected",
                   prefix=settings.MQTT_APP_STATUS_PREFIX) + " "
            + i18n.t("error.brokerLastStatus",
                     status=record.get("Status")))
    # Second signal: even for an old payload with no Status at all, a device
    # PISCU reports as faulty does not go green.
    if _reported_faulty(device, telemetry):
        raise UnreachableError(
            i18n.t("error.piscuDeviceDown"))

    uptime = record.get("Uptime")
    if uptime in (None, "", -1):
        uptime = _map_uptime(device, telemetry)
    return {
        "version": record.get("Version") or "",
        "serial": record.get("HWID") or "",
        "uptime": uptime,
        "note": record.get("Status") or "",
    }
