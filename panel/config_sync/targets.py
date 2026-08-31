#!/usr/bin/env python3
"""Where a field's target value comes from, and storing user-entered ones.

Precedence: device-specific > group > the project value in DeviceMap.
"""
from __future__ import annotations

from ..editions import runtime as editions
from ..inventory.device_map import Device, Inventory
from ..video_config import defaults as video_defaults
from .fields import FIELDS, config_scope, writable_for_scope
from .store import DEVICE_TARGETS, GROUP_TARGETS, LOCK
from .validation import scope_key, validate


def set_target(device_id: str, name: str, value: str,
               scope: str | None = None, *, set_no: int = 1) -> None:
    cleaned = validate(name, value, scope)
    key = scope_key(set_no, device_id)
    with LOCK:
        if cleaned:
            DEVICE_TARGETS.setdefault(key, {})[name] = cleaned
        else:                                   # empty = drop the override
            DEVICE_TARGETS.get(key, {}).pop(name, None)
    from . import storage
    storage.save()


def device_targets(device_id: str, *, set_no: int = 1) -> dict:
    key = scope_key(set_no, device_id)
    with LOCK:
        return dict(DEVICE_TARGETS.get(key, {}))


def set_group_target(group: str, name: str, value: str,
                     scope: str | None = None, *, set_no: int = 1) -> None:
    cleaned = validate(name, value, scope)
    key = scope_key(set_no, group)
    with LOCK:
        if cleaned:
            GROUP_TARGETS.setdefault(key, {})[name] = cleaned
        else:
            GROUP_TARGETS.get(key, {}).pop(name, None)
    from . import storage
    storage.save()


def group_targets(group: str, *, set_no: int = 1) -> dict:
    """Targets entered for a group. Secret fields come back with their value —
    the UI-facing view is masked by `group_target_display`."""
    if not str(group or "").strip():
        return {}
    key = scope_key(set_no, group)
    with LOCK:
        return dict(GROUP_TARGETS.get(key, {}))


def group_target_display(group: str, *, set_no: int = 1) -> dict:
    """UI-safe form: secret fields report "entered", not their value."""
    raw = group_targets(group, set_no=set_no)
    return {name: ("" if FIELDS[name].secret else value)
            for name, value in raw.items()}


def group_secret_fields(group: str, *, set_no: int = 1) -> list[str]:
    return [name for name in group_targets(group, set_no=set_no)
            if FIELDS[name].secret]


def forget_targets(set_no: int | None = None) -> None:
    """Empty the in-memory targets — the saved file is untouched."""
    with LOCK:
        if set_no is None:
            DEVICE_TARGETS.clear()
            GROUP_TARGETS.clear()
            return
        number, _ = scope_key(set_no, "_")
        for store in (DEVICE_TARGETS, GROUP_TARGETS):
            for key in [k for k in store if k[0] == number]:
                store.pop(key, None)


def _project_target(device: Device, inventory: Inventory, name: str,
                    group: str | None = None) -> tuple[str, str]:
    """The DeviceMap value and, if any, why it cannot be used.

    The DeviceMap key is the device's own field name: `SpeakerVolume`,
    `PBXExtension`, `Target1`, `TcHigh`… (case-insensitive). Introducing a new
    setting to the project therefore needs no table here —
    Inventory.project_settings() merges the type/subtype/device levels.

    An invalid value is not treated as a target: writing bad project data to a
    device would make a wrong setting permanent under the excuse "DeviceMap
    says so". The reason is returned to the caller and shown on screen.
    """
    field = FIELDS[name]
    if not field.write_name:
        return "", ""
    if name == "ipAddress":
        # DeviceMap stores the TEMPLATE ("10.n.1.40"); the address the device
        # should hold is that template resolved for the open set, which is
        # what the inventory already did. Reading `extra["IP"]` here would
        # offer the template itself as a target.
        return (str(device.ip or ""), "")
    if field.secret:
        # Secret fields are absent from `extra` (DeviceMap passwords are
        # stripped); the value comes only from the device's own record.
        raw = device.pbx_password if name == "sipPassword" else None
        if name == "sipPassword" and str(raw or "").strip() == "":
            # Field rule: the SIP password equals the extension. Devices with
            # no PBXPassword in DeviceMap (Amplifier, UIC) had none, and since
            # the SIP endpoint requires one, even the extension could not be
            # written.
            #
            # The number itself comes from the target too, so changing the
            # extension on screen changes the password with it.
            raw, _source = resolve_target(device, inventory, "sipExtension",
                                          group)
    else:
        raw = inventory.project_settings(device).get(field.write_name.lower())
    if raw in (None, "") and name == "sipPbx":
        # With no PBX address in DeviceMap it is the project's registrar —
        # the PISCU on most trains, and a machine of its own on Gaziray and
        # GDM (see `panel.editions.catalogue.Project.broker`).
        raw = editions.pbx_ip(inventory) or ""
    if raw in (None, "") and device.read_method == "isapi":
        # Video equipment is configured to project settings that DeviceMap
        # does not carry today (IR mode, third stream, the camera's audio).
        # They are defaults, so they answer last: anything in DeviceMap, and
        # anything entered on screen, still wins.
        raw = video_defaults.for_field(device, inventory, name)
    if raw in (None, ""):
        return "", ""
    try:
        return validate(name, raw, config_scope(device)), ""
    except ValueError as exc:
        return "", f"DeviceMap: {exc}"


def target_detail(device: Device, inventory: Inventory, name: str,
                  group: str | None = None) -> tuple[str, str, str]:
    """The effective target, its source, and any warning about project data.

    Order: device-specific > group > the DeviceMap project value.
    """
    own = device_targets(device.id, set_no=inventory.set_no).get(name)
    project, warning = _project_target(device, inventory, name, group)
    if own:
        return own, "device", warning
    shared = (group_targets(group, set_no=inventory.set_no).get(name)
              if group else None)
    if shared:
        return shared, "group", warning
    return (project, "project", warning) if project else ("", "", warning)


def resolve_target(device: Device, inventory: Inventory, name: str,
                   group: str | None = None) -> tuple[str, str]:
    """The field's effective target value and where it came from."""
    value, source, _warning = target_detail(device, inventory, name, group)
    return value, source


def group_project_summary(inventory: Inventory,
                          devices: list[Device]) -> tuple[dict, list]:
    """DeviceMap values across a group: the shared ones and the varying ones.

    Needed to pre-fill the group value boxes: a setting identical on every
    device (a type's volume) goes into the box. A setting that varies per
    device (the extension) does NOT — showing one value there works until the
    user edits a character, at which point the whole group gets that number.
    """
    seen: dict[str, set] = {}
    for device in devices:
        if device.read_method not in ("http", "adb", "isapi"):
            continue
        for name in writable_for_scope(config_scope(device)):
            if FIELDS[name].secret:
                continue
            value, _warning = _project_target(device, inventory, name)
            seen.setdefault(name, set()).add(value)
    shared = {name: next(iter(values)) for name, values in seen.items()
              if len(values) == 1 and next(iter(values))}
    varying = sorted(name for name, values in seen.items() if len(values) > 1)
    return shared, varying
