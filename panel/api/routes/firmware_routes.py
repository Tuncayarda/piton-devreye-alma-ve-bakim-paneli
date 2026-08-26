#!/usr/bin/env python3
"""Firmware: which file for which device, and installing it."""
from __future__ import annotations

from pathlib import Path

from ... import firmware, jobs, settings
from ...inventory import catalog
from ...system import files
from ..presenters import (find_device, inventory_for, reported_version,
                          target_devices)
from ..response import respond
from .helpers import single
from ... import i18n

_NO_TARGET = "error.firmwareNotDefined"


def get_firmware(query):
    # An image is chosen per device; the screen learns which file sits on
    # which device here. Without a group, only the selected ones come back
    # (the install button counts those).
    inventory = inventory_for(single(query, "set", 1))
    group = catalog.find_group(str(single(query, "group", "") or ""))
    if group and not catalog.group_supports(group, "fw"):
        return respond(400, {
            "error": i18n.t("error.firmwareTypeUnsupported")})
    devices = [device for device in inventory.devices
               if group is None or catalog.group_matches(group, device)]
    view = jobs.view_for(inventory.set_no)
    extensions = {firmware.file_extension(device) for device in devices
                  if firmware.file_extension(device)}
    return respond(200, {
        "setNo": inventory.set_no,
        "group": group["name"] if group else "",
        "maxSize": max((firmware.max_size_for(extension)
                        for extension in extensions),
                       default=firmware.MAX_SIZE),
        "devices": [{
            "deviceId": device.id,
            "name": device.name,
            "ip": device.ip,
            # Devices with no install path show as "not applicable"; the ones
            # that have it show which file is expected (announcement .bin,
            # Compartment LCD .apk).
            "installable": firmware.is_supported(device),
            "extension": firmware.file_extension(device),
            "currentVersion": reported_version(view.get(device.id)),
            "file": firmware.selection_for(device.id,
                                           set_no=inventory.set_no),
        } for device in devices],
        "selectedCount": len(firmware.selections(set_no=inventory.set_no)),
        "concurrency": settings.FIRMWARE_WORKERS,
    })


def _installable(inventory, body):
    devices = target_devices(inventory, body, "fw")
    targets = [device for device in devices if firmware.is_supported(device)]
    if not targets:
        raise ValueError(i18n.t(_NO_TARGET))
    return targets


def _target_extension(targets) -> str:
    extensions = {firmware.file_extension(device) for device in targets}
    if len(extensions) != 1:
        raise ValueError(i18n.t("error.mixedFileTypes"))
    return next(iter(extensions))


def _require_extension(path: str, extension: str) -> None:
    # OS filters are presentation only.  In particular macOS may classify an
    # APK as dynamic ``public.data`` and grey it out when AppleScript filters
    # by the literal "apk" type.  Always enforce the exact suffix here, after
    # the user has chosen a path, and on the headless endpoint too.
    if Path(str(path)).suffix.lower() != f".{extension.lower()}":
        raise ValueError(i18n.t("error.fileExtensionMismatch",
                                extension=extension.lower()))


def post_pick(body):
    # Opens the OS file picker and assigns the choice to the target
    # device(s). The path does not come from the client: the browser does not
    # reveal the real path and the user should not have to type it. The
    # request blocks until the user closes the window.
    inventory = inventory_for(body.get("set"))
    targets = _installable(inventory, body)
    # The filter follows what the device expects: an image (.bin) for
    # announcement equipment, an app package (.apk) for the Compartment LCD.
    # A mixed selection cannot be served by one file.
    extension = _target_extension(targets)
    title = (f".{extension} file for {targets[0].name}"
             if len(targets) == 1
             else f".{extension} file for {len(targets)} devices")
    try:
        chosen = files.pick_file(title, (extension,))
    except RuntimeError as exc:
        return respond(500, {"error": str(exc)})
    if not chosen:
        return respond(200, {"cancelled": True})
    _require_extension(chosen, extension)
    selection = firmware.select_file(
        [device.id for device in targets], chosen, set_no=inventory.set_no)
    return respond(200, {"files": selection, "deviceCount": len(targets),
                         "selectedCount": len(firmware.selections(
                             set_no=inventory.set_no))})


def post_file(body):
    # Assign by path directly. The UI does not use this (there the file comes
    # from the OS picker, see /api/firmware/pick); this is the endpoint for
    # headless runs and tests. Target: one device (devices: [id]) or a group.
    inventory = inventory_for(body.get("set"))
    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        return respond(400, {"error": i18n.t("error.filePathRequired")})
    # No image is assigned to a device with no install endpoint: silently
    # skipping one in a "apply to group" selection led to "why was it not
    # installed?" — showing it as never selected is the right answer.
    targets = _installable(inventory, body)
    extension = _target_extension(targets)
    _require_extension(path, extension)
    selection = firmware.select_file(
        [device.id for device in targets], path, set_no=inventory.set_no)
    return respond(200, {"files": selection, "deviceCount": len(targets),
                         "selectedCount": len(firmware.selections(
                             set_no=inventory.set_no))})


def post_remove(body):
    inventory = inventory_for(body.get("set"))
    if body.get("all") is True:
        # "All" is not project-wide but every selection in the open set.
        # Other sets' preparation is untouched.
        firmware.clear_all(inventory.set_no)
        return respond(200, {"removed": "all", "selectedCount": 0})
    devices = target_devices(inventory, body, "fw")
    removed = firmware.clear_selection([device.id for device in devices],
                                       set_no=inventory.set_no)
    return respond(200, {
        "removed": removed,
        "files": firmware.selections([device.id for device in devices],
                                     set_no=inventory.set_no),
        "selectedCount": len(firmware.selections(set_no=inventory.set_no))})


def post_install(body):
    inventory = inventory_for(body.get("set"))
    devices = target_devices(inventory, body, "fw")
    # Only devices with an image selected enter the queue: queueing one
    # without a file means a run that fills the row with an error and does
    # nothing.
    targets = [device for device in devices
               if firmware.is_supported(device)
               and firmware.has_selection(device.id, set_no=inventory.set_no)]
    if not targets:
        return respond(400, {
            "error": i18n.t("error.noFileChosen")})
    job = jobs.Job("firmware", i18n.lazy("job.firmware", count=len(targets)),
                   inventory.set_no, key=f"firmware:{inventory.set_no}")
    from ..tasks import firmware_task
    job, is_new = jobs.QUEUE.submit(job, firmware_task(inventory, targets))
    return respond(200 if is_new else 202,
                   {**job.dto(rows=False), "new": is_new})


GET = {
    "/api/firmware": get_firmware,
}

POST = {
    "/api/firmware/pick": post_pick,
    "/api/firmware/file": post_file,
    "/api/firmware/remove": post_remove,
    "/api/firmware/install": post_install,
}
