#!/usr/bin/env python3
"""Reading a device's current values, comparing them, and writing targets."""
from __future__ import annotations

import time
from dataclasses import replace

import requests

from .. import settings, video_config
from ..errors import (AuthError, NotApplicableError, VerificationError,
                      classify)
from ..inventory.device_map import Device, Inventory
from ..probe import announcement
from ..probe import fields as probe_fields
from . import adb_network
from .fields import (ADB_NETWORK, ENDPOINT_ORDER, FIELDS, ISAPI_CAMERA,
                     ISAPI_NVR, REBOOTING_ENDPOINTS, REQUIRED_FIELDS,
                     config_scope, endpoint_for, fields_for_scope,
                     writable_for_scope)
from .targets import device_targets, resolve_target, target_detail
from .. import i18n

# How long to wait after a device reboots. Coming back takes a few seconds in
# the field; when the window expires the read is attempted anyway so the real
# error reaches the user.
REBOOT_WAIT = float(settings.PROBE_TIMEOUT) * 6

# On decimal fields the device stores float32: write 2.4 and read back
# 2.4000000953674316. Exact equality made a written threshold look unwritten.
# The tolerance sits far below the step size (0.1).
DECIMAL_TOLERANCE = 1e-3

_REJECTION_WORDS = ("error", "fail", "invalid", "reject", "missing",
                    "not found")


def _read_flat(device: Device, credentials=None) -> dict:
    """Every readable field on the device, flattened.

    A Handset's mode fields live on `system/modes`, not the main endpoint;
    the probe layer merges the two so one dict appears here.

    The extra endpoint is requested ONLY for the type that needs it. Trying
    every known extra visibly stalled the screen: six requests for six absent
    endpoints, each taking seconds (a full timeout when the device is off).
    """
    extra = (("system/modes",) if (device.subtype or "") == "Handset" else ())
    data = announcement.read(device.ip, credentials, extra_endpoints=extra)
    return data.get("flat") or probe_fields.flatten(data.get("settings") or {})


def _current(flat: dict, name: str):
    field = FIELDS[name]
    return probe_fields.pick(flat, *field.candidates(),
                             exclude=field.exclude)


def _current_values(flat: dict, scope: str | None) -> dict:
    return {name: _current(flat, name)
            for name in fields_for_scope(scope)}


def _equal(current, target, kind: str | None = None) -> bool:
    """The device says 100, the user typed "100"; same value."""
    left, right = str(current).strip(), str(target).strip()
    if left == right:
        return True
    try:
        left_number = float(left.replace(",", "."))
        right_number = float(right.replace(",", "."))
    except ValueError:
        return False
    if kind == "decimal":
        return abs(left_number - right_number) <= DECIMAL_TOLERANCE
    return left_number == right_number


def _display(name: str, value):
    """How a value read from the device is shown.

    float32 noise is trimmed on decimals (2.4000000953674316 → 2.4); the
    rounding is display-only, comparison uses the raw value.
    """
    if value in (None, ""):
        return ""
    if FIELDS[name].kind != "decimal":
        return str(value)
    try:
        return f"{round(float(value), 3):g}"
    except (TypeError, ValueError):
        return str(value)


def _comparison(name: str, current, target) -> str:
    if target in (None, ""):
        return "no_target"
    if current in (None, ""):
        return "unread"
    return "match" if _equal(current, target, FIELDS[name].kind) else "differs"


def _rows(device: Device, inventory: Inventory, flat: dict,
          group: str | None = None) -> dict:
    """Screen rows from an already-performed read. The device is not visited
    twice — post-write verification and the screen share one read."""
    subtype = device.subtype or ""
    scope = config_scope(device)
    current = _current_values(flat, scope)
    own = device_targets(device.id, set_no=inventory.set_no)

    rows = []
    for name in fields_for_scope(scope):
        field = FIELDS[name]
        value = current.get(name)
        target, source, warning = (
            ("", "", "") if not field.write_name
            else target_detail(device, inventory, name, group))
        # A secret field's value leaves in no column; the comparison happens
        # on the server and the UI sees only the outcome and the source.
        rows.append({
            # The label is a message KEY in the table (it has to be, the
            # table is read on every request and the answer must be in the
            # language chosen at that moment). It is rendered here, the same
            # way `field_list` renders it for the group card — a row went out
            # reading "field.sipPbx" otherwise.
            "field": name, "label": i18n.t(field.label),
            "section": field.section,
            "current": "" if field.secret else _display(name, value),
            "hasCurrent": value not in (None, ""),
            "target": "" if field.secret else str(target or ""),
            "hasTarget": bool(target),
            "source": source,
            "override": "" if field.secret else str(own.get(name, "")),
            "hasOverride": bool(own.get(name)),
            "editable": bool(field.write_name),
            "secret": field.secret,
            "warning": warning,
            "comparison": _comparison(name, value, target),
        })
    return {"deviceId": device.id, "group": group or "", "subtype": subtype,
            "rows": rows}


def fetch(device: Device, inventory: Inventory, credentials=None,
          group: str | None = None) -> dict:
    """Read the device's current values and compare them to the targets.

    Two transports, one shape of answer. Announcement equipment answers over
    HTTP; a Compartment LCD has no settings API and answers over ADB, with
    exactly one writable row (see config_sync.adb_network).
    """
    if device.read_method == "adb":
        return _rows(device, inventory, adb_network.read(device), group)
    if device.read_method == "isapi":
        # Cameras and NVRs speak ISAPI and are configured as a procedure,
        # not field by field; the state comes back flattened the same way,
        # so the rows below are built from it unchanged.
        return _rows(device, inventory,
                     video_config.read_state(device, inventory, credentials),
                     group)
    if device.read_method != "http":
        raise NotApplicableError(
            i18n.t("error.configTypeUnsupported"))
    return _rows(device, inventory, _read_flat(device, credentials), group)


# ── writing ─────────────────────────────────────────────────────────────
def _payload_value(name: str, value: str):
    """Convert the target text to the JSON type the device expects."""
    field = FIELDS[name]
    text = str(value).strip()
    if field.kind == "decimal":
        return float(text.replace(",", "."))
    if field.kind in ("integer", "choice"):
        try:
            return int(float(text))
        except ValueError:
            return text
    return text


def _post(device: Device, endpoint: str, payload: dict,
          credentials=None) -> str:
    auth = tuple(credentials) if credentials else None
    try:
        response = requests.post(
            f"http://{device.ip}:{settings.ANNOUNCEMENT_PORT}/{endpoint}",
            json=payload, timeout=settings.PROBE_TIMEOUT, auth=auth,
            headers={"Content-Type": "application/json"})
    except Exception as exc:
        raise classify(exc)
    if response.status_code in (401, 403):
        raise AuthError(i18n.t("error.probeAuth"))
    # The body may be plain text ("Missing required fields"); it goes into the
    # error message, otherwise the user cannot tell which field was missing.
    text = (response.text or "").strip()[:120]
    if response.status_code >= 400:
        raise VerificationError(
            i18n.t("error.writeRefusedHttp", endpoint=endpoint,
                   code=response.status_code)
            + (i18n.t("error.writeRefusedSuffix", detail=text) if text else ""))
    if any(word in text.lower() for word in _REJECTION_WORDS):
        raise VerificationError(
            i18n.t("error.writeRefusedDetail", endpoint=endpoint,
                   detail=text))
    return text


def _wait_for_reboot(device: Device, credentials=None,
                     previous_uptime=None) -> bool:
    """Wait for the device to reboot and answer again.

    A value read right after the write may still come from the old process,
    so "it answered" is not enough — the uptime must have wound back. On
    timeout this returns False and verification is attempted anyway.
    """
    deadline = time.monotonic() + REBOOT_WAIT
    time.sleep(min(2.0, REBOOT_WAIT))
    while time.monotonic() < deadline:
        try:
            flat = _read_flat(device, credentials)
        except Exception:
            time.sleep(1.0)
            continue
        uptime = probe_fields.pick(flat, *probe_fields.UPTIME_KEYS)
        try:
            if previous_uptime is None or float(uptime) < float(previous_uptime):
                return True
        except (TypeError, ValueError):
            return True
        time.sleep(1.0)
    return False


def _apply_adb(device: Device, inventory: Inventory,
               group: str | None = None) -> dict:
    """Write a Compartment LCD's address, then read it back at the new one.

    Written deliberately apart from the HTTP path below rather than folded
    into it: there is no endpoint, no partial body and no reboot to wait out.
    What they do share is the rule that decides success — the value has to be
    read back from the device, never assumed from a reply.
    """
    flat = adb_network.read(device)
    target, _source = resolve_target(device, inventory, "ipAddress", group)
    target = str(target or "").strip()
    if not target:
        raise ValueError(i18n.t("error.noTargetValue"))
    if _equal(_current(flat, "ipAddress"), target):
        return {**_rows(device, inventory, flat, group),
                "writtenFields": [], "writtenEndpoints": [],
                "rebooted": False}
    adb_network.write_address(device, target)
    # The display is at the new address now, so the read-back has to go there
    # — `device` still carries the DeviceMap one.
    moved = replace(device, ip=target)
    return {**_rows(moved, inventory, adb_network.read(moved), group),
            "writtenFields": [i18n.t(FIELDS["ipAddress"].label)],
            "writtenEndpoints": [ADB_NETWORK], "rebooted": False}


def _apply_isapi(device: Device, inventory: Inventory, credentials=None,
                 group: str | None = None, report=None) -> dict:
    """Configure a camera or an NVR, then verify against the device.

    The procedure — which ISAPI calls, in what order, which of them reboot
    the device — belongs to panel.video_config. What stays here is the rule
    the whole screen runs on: a value counts as written only once it has
    been READ BACK. The state returned by the procedure is that read; on the
    NVR it deliberately happens before the reboot, because a device on its
    way down answers nothing.

    `report` is handed straight to the procedure, which narrates its steps
    into the job's row (see panel.api.tasks.config_task).
    """
    scope = config_scope(device)
    targets: dict[str, str] = {}
    for name in writable_for_scope(scope):
        value, _source = resolve_target(device, inventory, name, group)
        if str(value).strip():
            targets[name] = str(value).strip()
    if not targets:
        raise ValueError(i18n.t("error.noTargetValue"))

    result = video_config.apply(device, inventory, targets, credentials,
                                report)
    flat = result["state"]
    final = _current_values(flat, scope)
    unconfirmed = [i18n.t(FIELDS[name].label) for name in targets
                   if not _equal(final.get(name), targets[name],
                                 FIELDS[name].kind)]
    if unconfirmed:
        raise VerificationError(
            i18n.t("error.fieldsNotWritten", fields=", ".join(unconfirmed)))

    written = result["written"]
    marker = ISAPI_NVR if device.type == "NVR" else ISAPI_CAMERA
    return {**_rows(device, inventory, flat, group),
            "writtenFields": [i18n.t(FIELDS[name].label) for name in written],
            "writtenEndpoints": [marker] if written else [],
            "rebooted": bool(result["rebooted"])}


def apply_targets(device: Device, inventory: Inventory, credentials=None,
                  group: str | None = None, report=None) -> dict:
    """Write the target values and verify them by reading back.

    Only fields that DIFFER from the device are sent: the SIP endpoint reboots
    the device, so we do not black one out over a setting that already matches.

    HTTP 200 alone is not success: after the write the settings are read again
    and the value is confirmed to have changed. A device can ignore a field it
    does not know without erroring, so without verification "written" would
    cover a setting that never landed.

    `report(text, state)` is used by the video procedures, which have several
    steps worth naming; the announcement path writes fields and needs none.
    """
    if device.read_method == "adb":
        return _apply_adb(device, inventory, group)
    if device.read_method == "isapi":
        return _apply_isapi(device, inventory, credentials, group, report)
    if device.read_method != "http":
        raise NotApplicableError(
            i18n.t("error.writeTypeUnsupported"))

    scope = config_scope(device)
    flat = _read_flat(device, credentials)
    current = _current_values(flat, scope)
    previous_uptime = probe_fields.pick(flat, *probe_fields.UPTIME_KEYS)

    targets: dict[str, str] = {}
    for name in writable_for_scope(scope):
        value, _source = resolve_target(device, inventory, name, group)
        if str(value).strip():
            targets[name] = str(value).strip()
    if not targets:
        raise ValueError(i18n.t("error.noTargetValue"))

    # A field already correct on the device is not sent.
    changed = [name for name, value in targets.items()
               if not _equal(current.get(name), value, FIELDS[name].kind)]
    if not changed:
        return {**_rows(device, inventory, flat, group),
                "writtenFields": [], "writtenEndpoints": [],
                "rebooted": False}

    # Changed fields are spread across their endpoints; endpoints that reject
    # a partial body get their required fields filled from the target or the
    # device.
    buckets: dict[str, dict[str, str]] = {}
    for name in changed:
        endpoint = endpoint_for(name, scope)
        if endpoint:
            buckets.setdefault(endpoint, {})[name] = targets[name]

    written_endpoints = []
    for endpoint in ENDPOINT_ORDER:
        if endpoint not in buckets:
            continue
        body = dict(buckets[endpoint])
        for name in REQUIRED_FIELDS.get(endpoint, ()):
            if name in body or name not in writable_for_scope(scope):
                continue
            value = targets.get(name) or current.get(name)
            if value in (None, ""):
                raise VerificationError(
                    i18n.t("error.requiredFieldUnknown",
                           field=i18n.t(FIELDS[name].label),
                           endpoint=endpoint))
            body[name] = str(value)
        _post(device, endpoint,
              {FIELDS[name].write_name: _payload_value(name, value)
               for name, value in body.items()}, credentials)
        written_endpoints.append(endpoint)

    rebooted = any(endpoint in REBOOTING_ENDPOINTS
                   for endpoint in written_endpoints)
    if rebooted:
        _wait_for_reboot(device, credentials, previous_uptime)

    # Read again afterwards: only this shows which field actually stuck. One
    # read feeds both the verification and the screen rows; a second pass
    # would be expensive on a 12-intercom run.
    final_flat = _read_flat(device, credentials)
    result = _rows(device, inventory, final_flat, group)
    final = _current_values(final_flat, scope)
    # A secret field the device does not report back cannot be verified — but
    # that does not mean the write failed. On a device that masks the
    # password, "the device did not write this field" would flag a perfectly
    # good SIP setting as an error every time.
    unconfirmed = [i18n.t(FIELDS[name].label) for name in targets
                   if not (FIELDS[name].secret and final.get(name) in (None, ""))
                   and not _equal(final.get(name), targets[name],
                                  FIELDS[name].kind)]
    if unconfirmed:
        raise VerificationError(
            i18n.t("error.fieldsNotWritten",
                   fields=", ".join(unconfirmed)))
    return {**result,
            "writtenFields": [i18n.t(FIELDS[name].label) for name in changed],
            "writtenEndpoints": written_endpoints, "rebooted": rebooted}
