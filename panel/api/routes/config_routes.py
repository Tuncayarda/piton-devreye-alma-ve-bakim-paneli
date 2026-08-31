#!/usr/bin/env python3
"""Device configuration: reading, targets and applying."""
from __future__ import annotations

from ... import config_sync, jobs
from ...errors import AuthError, DeviceError, user_message
from ...inventory import catalog
from ..presenters import (config_field_context, credentials_for, find_device,
                          inventory_for, inventory_for_write, target_devices)
from ..response import respond
from ..tasks import config_task
from .helpers import single, submit
from ... import i18n


def _error_body(device, group: str, exc: DeviceError) -> dict:
    """A 200 whose DEVICE could not be read — deliberately not a 502.

    The screen still needs the field list and the targets to stay usable
    while the device is dark (targets get prepared in the field against
    unreachable hardware), so the request SUCCEEDS and carries the device's
    failure as data. Named `deviceError`, never `error`: everywhere else in
    the API `error` means "this request failed", and the bridge envelope
    computes `ok` from the status — a third meaning under the same name is
    how a client-side helper mistakes a dark device for a good read.
    """
    return {"deviceId": device.id, "group": group, "rows": [],
            "subtype": device.subtype or "",
            "reading": False,
            "deviceError": user_message(exc),
            "needsCredentials": isinstance(exc, AuthError)}


def get_fields(query):
    # A fast endpoint that never touches the device: field list, targets and
    # DeviceMap values. When the group changes the screen waits for this, not
    # for the device read — reading can take seconds, and in that time the
    # card was still showing the old group's fields.
    inventory = inventory_for(single(query, "set", 1))
    device = find_device(inventory, single(query, "id"))
    group = single(query, "group", "")
    return respond(200, {
        "deviceId": device.id, "group": group,
        "subtype": device.subtype or "",
        "rows": [], "reading": True,
        **config_field_context(inventory, device, group)})


def get_config(query):
    inventory = inventory_for(single(query, "set", 1))
    device = find_device(inventory, single(query, "id"))
    group = single(query, "group", "")
    try:
        return respond(200, {
            **config_sync.fetch(device, inventory, credentials_for(device),
                                group),
            **config_field_context(inventory, device, group),
        })
    except DeviceError as exc:
        return respond(200, {
            **_error_body(device, group, exc),
            **config_field_context(inventory, device, group)})


def post_target(body):
    inventory = inventory_for_write(body.get("set"))
    device = find_device(inventory, body.get("deviceId"))
    group = str(body.get("group") or "")
    field = str(body.get("field", ""))
    value = str(body.get("value", ""))
    # "scope": group = the same value for the whole group, device = this
    # device only (overriding the group's). The value is validated here
    # against the device type's field definition: a bad value sitting in
    # memory until the write would surface in the queue instead.
    # Which fields exist on this device: its SubType, or its Type for video
    # equipment (see config_sync.fields.config_scope). Not to be confused
    # with the request's own "scope" below, which says group or device.
    field_scope = config_sync.config_scope(device)
    definition = catalog.group_in(inventory, group) if group else None
    if not catalog.device_supports(device, "cfg"):
        return respond(400, {
            "error": i18n.t("error.configUnsupported")})
    if group and (not catalog.group_supports(definition, "cfg")
                  or not catalog.group_matches(definition, device)):
        return respond(400, {"error": i18n.t("error.pickDeviceType")})
    if str(body.get("scope") or "device") == "group":
        if not definition:
            return respond(400, {"error": i18n.t("error.deviceTypeRequired")})
        config_sync.set_group_target(group, field, value,
                                     definition.get("subtype") or field_scope,
                                     set_no=inventory.set_no)
    else:
        config_sync.set_target(device.id, field, value, field_scope,
                               set_no=inventory.set_no)
    try:
        body_out = config_sync.fetch(device, inventory,
                                     credentials_for(device), group)
    except DeviceError as exc:
        body_out = _error_body(device, group, exc)
    return respond(200, {**body_out,
                         **config_field_context(inventory, device, group)})


def post_reset(body):
    # Saved defaults are removed; the DeviceMap project values stay and the
    # screen falls back to them.
    inventory = inventory_for_write(body.get("set"))
    device = find_device(inventory, body.get("deviceId"))
    group = str(body.get("group") or "")
    config_sync.clear_saved_defaults(inventory.set_no)
    try:
        body_out = config_sync.fetch(device, inventory,
                                     credentials_for(device), group)
    except DeviceError as exc:
        body_out = _error_body(device, group, exc)
    return respond(200, {**body_out,
                         **config_field_context(inventory, device, group)})


def post_apply(body):
    inventory = inventory_for_write(body.get("set"))
    devices = target_devices(inventory, body, "cfg")
    group = str(body.get("group") or "")
    # The queue will not take a second job with the same key. Applying to one
    # device carries its own key: the settings dialog opens device by device,
    # and a pending group job must not silently swallow a single-device apply.
    scope = devices[0].id if len(devices) == 1 else "group"
    title = (i18n.lazy("job.configOne", device=devices[0].name)
             if len(devices) == 1
             else i18n.lazy("job.configMany", count=len(devices)))
    job = jobs.Job("config", title, inventory.set_no,
                   key=f"config:{inventory.set_no}:{scope}")
    return submit(job, config_task(inventory, devices,
                                                     group))


GET = {
    "/api/config": get_config,
    "/api/config/fields": get_fields,
}

POST = {
    "/api/config/target": post_target,
    "/api/config/reset": post_reset,
    "/api/config/apply": post_apply,
}
