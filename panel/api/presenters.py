#!/usr/bin/env python3
"""Shared lookups and the DTOs handed to the UI."""
from __future__ import annotations

import threading
import time

from .. import credentials as credential_store
from .. import jobs, status
from ..inventory import catalog
from ..inventory import device_map as inventory_module
from ..probe import reader, result as probe_result
from ..telemetry import TelemetrySnapshot
from .. import i18n

# Job kinds that WRITE to devices — kept apart from the reading kinds (scan,
# light refresh), because while they run whatever a device reports is
# temporary.
WRITING_JOB_KINDS = ("ip", "ipfactory", "config", "firmware")


def inventory_for(set_no) -> inventory_module.Inventory:
    return inventory_module.load(inventory_module.valid_set(set_no))


def inventory_for_write(set_no) -> inventory_module.Inventory:
    """Resolve a write target only after strict set-number validation."""
    return inventory_module.load(inventory_module.required_set(set_no))


def find_device(inventory: inventory_module.Inventory, device_id):
    """Look a device up ONLY in the inventory.

    No field the client sends other than the id (ip, type) takes part in
    choosing the target.
    """
    if not isinstance(device_id, str) or len(device_id) > 64:
        raise ValueError(i18n.t("error.invalidDeviceId"))
    device = inventory.find(device_id)
    if device is None:
        raise LookupError(i18n.t("error.deviceNotInSet"))
    return device


def credentials_for(device):
    """The in-memory credential for a device, if any."""
    return credential_store.lookup(device.id, device.ip,
                                   group=reader.credential_group(device))


def collect_telemetry(inventory) -> TelemetrySnapshot:
    return TelemetrySnapshot(inventory.piscu_ip()).collect(
        expected_set=inventory.set_no)


# Telemetry cache, per set.
#
# `TelemetrySnapshot.collect()` opens three MQTT connections and waits for
# retained messages; measured at ~9 seconds in the field. Because the light
# refresh re-collected it every round, the round ITSELF took nine seconds
# while the devices answered in milliseconds — which made the UI's
# few-second refresh pointless.
#
# The values sit retained on the broker and the minute-long discovery round
# already collects them; for light rounds that picture is fresh enough. The
# TTL is longer than the discovery interval, so on a normally running panel a
# light round always finds the cache warm and never touches MQTT.
TELEMETRY_TTL = 90.0
_telemetry_cache: dict[int, tuple[float, TelemetrySnapshot]] = {}
_telemetry_lock = threading.Lock()


def store_telemetry(set_no: int, snapshot: TelemetrySnapshot) -> None:
    # A failed snapshot is stored too: if MQTT really is unreachable, there is
    # no point in the light round spending nine seconds finding the same error
    # every time. Telemetry-backed devices are not green, so they are not
    # light-round targets anyway.
    with _telemetry_lock:
        _telemetry_cache[int(set_no)] = (time.monotonic(), snapshot)


def cached_telemetry(set_no: int) -> TelemetrySnapshot | None:
    with _telemetry_lock:
        entry = _telemetry_cache.get(int(set_no))
    if entry is None or time.monotonic() - entry[0] > TELEMETRY_TTL:
        return None
    return entry[1]


def clear_telemetry_cache() -> None:
    with _telemetry_lock:
        _telemetry_cache.clear()


def reported_version(result) -> str:
    """The version read from the device; empty when unread (never invented)."""
    return str((result.fields.get("version") if result else "") or "")


def device_dto(device, result) -> dict:
    data = device.dto()
    data["result"] = (result.dto() if result is not None
                      else probe_result.not_read(device.read_method).dto())
    data["credentialGroup"] = reader.credential_group(device) or ""
    data["hasCredentials"] = credentials_for(device) is not None
    return data


def state_body(inventory) -> dict:
    # The device list always shows the last known state; step-by-step scan
    # progress lives in the job queue. Showing both made the list unreadable
    # while a scan ran.
    view = jobs.view_for(inventory.set_no)
    results = view.all()
    devices = [device_dto(device, results.get(device.id))
               for device in inventory.devices]
    locked = [device for device in devices
              if device["result"]["verification"] == status.AUTH_REQUIRED]
    return {
        "setNo": inventory.set_no,
        "devices": devices,
        "counts": view.counts(),
        "lockedCount": len(locked),
        "lastScan": view.last_scan,
        "scanRunning": bool(jobs.QUEUE.active(f"scan:{inventory.set_no}")),
    }


def target_devices(inventory, body, op: str = ""):
    """Resolve the group/device list the client selected.

    The UI only offers supported options; the same limit applies to direct API
    calls. Mixed lists are not partially processed.
    """
    ids = body.get("devices")
    if isinstance(ids, list) and ids:
        if len(ids) > 256:
            raise ValueError(i18n.t("error.tooManyDevices"))
        devices = [find_device(inventory, str(value)) for value in ids]
        if op and any(not catalog.device_supports(device, op)
                      for device in devices):
            if op == "fw":
                raise ValueError(
                    i18n.t("error.firmwareNotDefined"))
            raise ValueError(
                i18n.t("error.someDevicesUnsupported"))
        return devices
    group = catalog.find_group(str(body.get("group", "")))
    if group is None:
        raise ValueError(i18n.t("error.noTargetGroup"))
    if op and not catalog.group_supports(group, op):
        if op == "fw":
            raise ValueError(
                i18n.t("error.firmwareNotDefined"))
        raise ValueError(i18n.t("error.typeUnsupported"))
    return [device for device in inventory.devices
            if catalog.group_matches(group, device)]


def config_field_context(inventory, device, group: str) -> dict:
    """Field definitions, group targets and DeviceMap values for the screen.

    Must work even when the device cannot be read: group values get prepared
    in the field while devices are unreachable. Fields vary by device type — a
    Handset's mode fields do not exist on an Amplifier, and the UIC thresholds
    only on a UIC. A secret field's (the SIP password) value is not sent; only
    whether one was entered.

    `projectShared` are the DeviceMap values identical across the group, which
    the screen pre-fills. `projectVarying` lists the fields that differ per
    device — those boxes stay empty.
    """
    from .. import config_sync
    from ..config_sync.targets import group_project_summary

    definition = catalog.find_group(group)
    members = [candidate for candidate in inventory.devices
               if definition and catalog.group_matches(definition, candidate)]
    shared, varying = group_project_summary(inventory, members or [device])
    return {
        "fields": config_sync.field_list(
            config_sync.config_scope(device)),
        "groupTargets": config_sync.group_target_display(
            group, set_no=inventory.set_no),
        "groupSecrets": config_sync.group_secret_fields(
            group, set_no=inventory.set_no),
        "projectShared": shared,
        "projectVarying": varying,
        "savedDefaults": config_sync.saved_defaults_summary(inventory.set_no),
    }


def piscu_body(inventory) -> dict:
    """The PISCU & PBX screen — only data that was actually read."""
    view = jobs.view_for(inventory.set_no)
    results = view.all()

    clients = []
    for device in inventory.by_type("PISCU") + inventory.by_type("HMI"):
        result = results.get(device.id)
        clients.append({
            "name": device.name, "ip": device.ip,
            "state": result.state if result else status.UNKNOWN,
            "version": (result.fields.get("version", "") if result else ""),
            "detail": result.detail if result else i18n.t("probe.notReadYet"),
        })

    extensions = []
    for device in [d for d in inventory.devices if d.pbx_extension]:
        result = results.get(device.id)
        extensions.append({
            "extension": device.pbx_extension, "name": device.name,
            "ip": device.ip,
            "state": result.state if result else status.UNKNOWN,
            "reportedExtension": (result.fields.get("sipExtension", "")
                                  if result else ""),
            "pbx": (result.fields.get("sipPbx", "") if result else ""),
        })

    return {
        "brokerIp": inventory.piscu_ip(),
        "clients": clients,
        "extensions": extensions,
        "note": i18n.t("sip.note"),
    }
