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

from .. import settings, status
from ..errors import UnreachableError, classify
from ..inventory.catalog import READ_METHODS
from ..inventory.device_map import Device
from . import android, announcement, camera, mqtt_source, ping, result, switch
from .. import i18n


def credential_group(device: Device) -> str | None:
    return READ_METHODS.get(device.read_method, {}).get("group")


# The methods that reach a device DIRECTLY — the only ones worth a second,
# richer visit after a broker answer (below).
DIRECT_METHODS = ("kyland", "http", "isapi", "adb")


def read_device(device: Device, credentials=None, telemetry=None,
                timeout: float | None = None,
                expected_ntp: str | None = None,
                pbx_ip: str | None = None,
                project_span: str = "",
                method: str | None = None) -> result.ProbeResult:
    """Read one device and return a coloured result. Never raises.

    THE BROKER ANSWERS FIRST, THE DEVICE TOPS IT UP. On a broker-probed
    device (GDM: `probe_method` "mqtt" while `read_method` names the real
    protocol) the DeviceMap record decides who is up and carries the base
    fields — version, serial, uptime — and a device the record calls alive
    is then read once over its own protocol for the fields the broker does
    not publish: an Intercom's volumes and SIP numbers, a display's time
    zone, a camera's time check. The same shape as the field script this
    panel grew out of (`field_scripts/device_verify.py`): the map is the
    backbone, the protocol reads only top up, and a top-up that fails does
    not un-say what the broker said.

    AND THE BROKER IS NEVER A PRECONDITION. Where there is no record to
    read — no broker on the stand, a collection that failed, a device the
    published map does not list — the device is simply asked directly, the
    read every project had before the broker-first arrangement. A record
    that testifies "down", on the other hand, stands (softened only by the
    ping below): the PISCU watches the device continuously and outranks a
    fresh handshake.

    `method` overrides the dispatch entirely — the checklist export's door
    to a direct re-read — and an override also skips the top-up: whoever
    names a method wants exactly that one answer.
    """
    # The PROBE method, not the read method, decides how status is asked
    # for — "mqtt" on every direct rule, fleet-wide — while `read_method`
    # keeps carrying what it always carried: which protocol configuration
    # and firmware travel over (see inventory/profiles).
    # `getattr` because the ADB screen's stand-in devices predate the field.
    chosen = (method or getattr(device, "probe_method", "")
              or device.read_method)
    hybrid = (method is None and chosen != device.read_method
              and device.read_method in DIRECT_METHODS)
    if hybrid and not _broker_can_answer(device, telemetry):
        chosen, hybrid = device.read_method, False
    try:
        outcome = _dispatch(chosen, device, credentials, telemetry, timeout,
                            expected_ntp, pbx_ip, project_span)
    except Exception as exc:
        return _second_opinion(device, result.from_error(exc, chosen))
    if hybrid and outcome.state == status.OK:
        return _topped_up(device, outcome, credentials, telemetry, timeout,
                          expected_ntp, pbx_ip, project_span)
    return outcome


def _broker_can_answer(device: Device, telemetry) -> bool:
    """Is there a broker record for this device at all?

    False sends the read to the device itself. Absence of a record is NOT
    evidence of absence of the device — a stand has no PISCU, a bench has
    no broker, and a map that does not list a camera says nothing about
    the camera — so nothing here is allowed to colour a row; it only picks
    which road the read takes.
    """
    return bool(telemetry is not None
                and not getattr(telemetry, "error", None)
                and telemetry.record(device.ip))


def _dispatch(method, device, credentials, telemetry, timeout,
              expected_ntp, pbx_ip, project_span) -> result.ProbeResult:
    """One read over one named method. Raises what the readers raise."""
    if method == "kyland":
        return _read_switch(device, credentials, telemetry, timeout)
    if method == "isapi":
        return _read_camera(device, credentials, timeout, expected_ntp,
                            project_span)
    if method == "http":
        return _read_announcement(device, credentials, timeout)
    if method == "adb":
        return _read_android(device, telemetry, pbx_ip, timeout)
    if method in ("mqtt", "app"):
        return _read_mqtt(device, telemetry, method)
    return result.not_applicable(
        method, i18n.t("error.noReadMethod"))


def _topped_up(device: Device, base: result.ProbeResult, credentials,
               telemetry, timeout, expected_ntp, pbx_ip,
               project_span) -> result.ProbeResult:
    """The device's own answer, laid over the broker record.

    The outcomes, in the order they are checked:

    * The device answered — the rich result wins, carrying forward any base
      field its protocol does not produce (ISAPI has no uptime; the record
      does). Green, with everything filled.
    * The device wants a password — AMBER, with the base fields kept. The
      credential store is memory-only, so this is the only road to the
      extra fields ever being readable: a row that stayed green would never
      ask, and nobody would ever be told why the volumes are empty.
    * The device COULD NOT BE READ AT ALL — timeout, refused, no route —
      while the broker calls it alive: "needs inspection". A device whose
      own protocol is gone is an errand even when the PISCU can still see
      it, and a green row would hide that errand behind the record.
    * Anything else — a reply that merely failed verification, a host
      without adb — the broker's word stands: named in the detail, no cell
      emptied, nothing turned red.
    """
    try:
        rich = _dispatch(device.read_method, device, credentials, telemetry,
                         timeout, expected_ntp, pbx_ip, project_span)
    except Exception as exc:
        return _extras_verdict(base, device.read_method, exc)
    if rich.state == status.OK:
        fields = dict(base.fields)
        fields.update({key: value for key, value in rich.fields.items()
                       if value not in (None, "")})
        rich.fields = fields
        return rich
    # The readers raise their failures; what RETURNS non-OK is the pair of
    # grey shapes (not applicable / not read), and grey on top of a live
    # record is only a note.
    base.detail = i18n.t("probe.extrasUnread",
                         reason=rich.detail or rich.read_method)
    return base


def _extras_verdict(base: result.ProbeResult, method: str,
                    exc: BaseException) -> result.ProbeResult:
    """What a raised top-up means for the row — see `_topped_up`."""
    rich = result.from_error(exc, method)
    if result.needs_auth(rich):
        rich.fields = dict(base.fields)
        return rich
    if isinstance(classify(exc), UnreachableError):
        base.state = status.REVIEW
        base.verification = status.UNVERIFIED
        base.detail = i18n.t("probe.aliveButUnreadable",
                             reason=rich.detail or method)
        return base
    base.detail = i18n.t("probe.extrasUnread",
                         reason=rich.detail or method)
    return base


def _second_opinion(device: Device, outcome: result.ProbeResult):
    """A failed read is followed by one ping before it is called red.

    Only FAILED is refined. Amber already means "alive, wants a password"
    and grey means "not asked", so neither needs the echo; and a read that
    threw without the device being at fault (no telemetry) never gets here —
    it went grey in `_read_mqtt`.

    The original error stays in the detail: "needs inspection" without the
    reason is an errand with no starting point.
    """
    if outcome.state != status.FAILED or not device.ip:
        return outcome
    if not ping.reachable(device.ip):
        return outcome
    outcome.state = status.REVIEW
    outcome.detail = i18n.t("probe.aliveButSilent", reason=outcome.detail)
    return outcome


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


def _read_camera(device, credentials, timeout, expected_ntp,
                 project_span=""):
    # An NVR and a camera answer the same protocol but are not checked for
    # the same things: a recorder has a disk and a buzzer, a camera has a
    # card, an IR lamp and a third stream.
    data = camera.read(device.ip, credentials, timeout,
                       expected_ntp=expected_ntp,
                       is_nvr=device.type == "NVR",
                       project_span=project_span)
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


def _read_android(device, telemetry, pbx_ip, timeout=None):
    # The caller's budget reaches adb as-is. `android.read` applies it to
    # EACH adb invocation rather than to the read as a whole — that is its
    # documented shape, and it is the right one here too: what the light
    # refresh's short budget exists to bound is a display that stops
    # answering, and that shows up as one command hanging, not as many
    # quick ones adding up. Dropping it (as this branch used to) meant the
    # 3-second refresh waited out the full default on a dead display.
    data = android.read(device.ip, timeout=timeout)
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
    }, "adb", _adb_detail(data))


def _adb_detail(data: dict) -> str:
    """What the row says it read.

    With `settings.ADB_REQUIRE_PACKAGE` off the display may carry no named
    application at all, and "com.piton.train_lcd_panel  read" with an empty
    version would be a sentence claiming something that did not happen. What
    WAS read is said instead — the display answered, and by its serial.
    """
    if data["version"]:
        return i18n.t("probe.adbRead", package=settings.ADB_PACKAGE,
                      version=data["version"])
    return i18n.t("probe.adbReadNoApp", serial=data["serial"] or "?")


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
