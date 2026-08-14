#!/usr/bin/env python3
"""The dispatcher: which device type is read how.

`read_device()` is the only entry point. Callers (the scan job, light
refresh, credential checks) do not know which protocol is spoken; they hand
over a Device from the inventory.

Credentials are NOT looked up here, the caller supplies them. That way a
credential attempt and a normal read follow the same code path, so "it worked
in the form but not in the scan" cannot happen.
"""
from __future__ import annotations

from .. import settings
from ..inventory.catalog import READ_METHODS
from ..inventory.device_map import Device
from . import android, announcement, camera, mqtt_source, result, switch
from .. import i18n


def credential_group(device: Device) -> str | None:
    return READ_METHODS.get(device.read_method, {}).get("group")


def read_device(device: Device, credentials=None, telemetry=None,
                timeout: float | None = None,
                expected_ntp: str | None = None,
                pbx_ip: str | None = None) -> result.ProbeResult:
    """Read one device and return a coloured result. Never raises."""
    method = device.read_method
    try:
        if method == "kyland":
            return _read_switch(device, credentials, telemetry, timeout)
        if method == "isapi":
            return _read_camera(device, credentials, timeout, expected_ntp)
        if method == "http":
            return _read_announcement(device, credentials, timeout)
        if method == "adb":
            return _read_android(device, telemetry, pbx_ip)
        if method in ("mqtt", "app"):
            return _read_mqtt(device, telemetry, method)
        return result.not_applicable(
            method, i18n.t("error.noReadMethod"))
    except Exception as exc:
        return result.from_error(exc, method)


def _read_switch(device, credentials, telemetry, timeout):
    data = switch.read(device.ip, credentials, timeout)
    # When the switch does not report its own uptime, fall back to the
    # DeviceMap record.
    uptime = data["uptime"]
    if uptime in (None, ""):
        uptime = mqtt_source._map_uptime(device, telemetry)
    return result.success({
        "version": data["version"], "model": data["model"],
        "mac": data["mac"], "deviceName": data["name"],
        "uptime": result.uptime_text(uptime),
    }, "kyland")


def _read_camera(device, credentials, timeout, expected_ntp):
    data = camera.read(device.ip, credentials, timeout,
                       expected_ntp=expected_ntp)
    return result.success({
        "version": data["version"], "serial": data["serial"],
        "model": data["model"], "networkTime": data["networkTime"],
    }, "isapi")


def _read_announcement(device, credentials, timeout):
    data = announcement.read(device.ip, credentials, timeout)
    return result.success({
        "version": data["version"], "serial": data["serial"],
        "uptime": result.uptime_text(data["uptime"]),
        "sipPbx": data["sipPbx"], "sipExtension": data["sipExtension"],
        "sipOutbound": data["sipOutbound"],
        "speakerVolume": data["speakerVolume"],
        "micVolume": data["micVolume"],
        "speakerGain": data["speakerGain"],
        "micGain": data["micGain"],
    }, "http")


def _read_android(device, telemetry, pbx_ip):
    data = android.read(device.ip)
    registration = data["sipRegistration"]
    # The extension is written to the device log only at app start; after the
    # buffer wraps it is gone. The same number sits retained on the broker
    # under ALFA/SipPort, so it is taken from there without rebooting the
    # device, and the source is stated.
    extension, source = data["sipExtension"], i18n.t("probe.deviceLog")
    if not extension and telemetry is not None:
        extension = telemetry.sip_extension(device.ip)
        source = f"{settings.MQTT_SIP_PORT_PREFIX}/{device.ip}"
    # The PBX address is on that same log line; without it, the registrar is
    # the set's PISCU (there is no other one). Only written while the device
    # says "registered" — naming a PBX for an unregistered device would show
    # a connection that does not exist.
    pbx, pbx_source = data["sipPbx"], i18n.t("probe.deviceLog")
    if not pbx and pbx_ip and registration.startswith("register"):
        pbx, pbx_source = pbx_ip, i18n.t("probe.projectPiscu")
    return result.success({
        "version": data["version"], "serial": data["serial"],
        "timezone": data["timezone"],
        "uptime": result.uptime_text(data["uptime"]),
        "sipPbx": pbx, "sipExtension": extension,
        "sipPbxSource": pbx_source if pbx else "",
        "sipExtensionSource": source if extension else "",
        "sipRegistration": (f"{registration} ({data['sipCode']})"
                            if registration and data["sipCode"]
                            else registration),
        "package": data["package"], "versionCode": data["versionCode"],
        "targetSdk": data["targetSdk"],
        "updatedAt": data["updatedAt"],
    }, "adb", i18n.t("probe.adbRead", package=settings.ADB_PACKAGE,
                          version=data["version"]))


def _read_mqtt(device, telemetry, method):
    if telemetry is None or telemetry.error:
        reason = (telemetry.error if telemetry
                  else i18n.t("probe.noTelemetry"))
        return result.not_read(method, reason)
    data = (mqtt_source.from_app_status(device, telemetry) if method == "app"
            else mqtt_source.from_device_map(device, telemetry))
    return result.success({
        "version": data.get("version", ""), "serial": data.get("serial", ""),
        "uptime": result.uptime_text(data.get("uptime")),
        "note": data.get("note", ""),
    }, method)
