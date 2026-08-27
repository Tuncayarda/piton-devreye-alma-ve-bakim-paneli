#!/usr/bin/env python3
"""Device categories, operation groups and the read-method map.

Single source of truth for the sidebar and the target-group pickers; the UI
keeps no list of its own and takes these from the API.
"""
from __future__ import annotations
from .. import i18n

# ── sidebar categories ──────────────────────────────────────────────────
CATEGORIES = [
    {"id": "all", "nameKey": "category.all", "code": "ALL",
     "types": "category.allTypes", "matches": None},
    {"id": "announcement", "nameKey": "category.announcement", "code": "ANN",
     "types": "Announcement", "matches": ["Announcement"]},
    {"id": "video", "nameKey": "category.video", "code": "VIDEO",
     "types": "Camera · NVR", "matches": ["Camera", "NVR"]},
    {"id": "display", "nameKey": "category.display", "code": "DISPLAY",
     "types": "LCD · LED", "matches": ["LCD", "LED"]},
    {"id": "network", "nameKey": "category.network", "code": "NET",
     "types": "Switch · AP", "matches": ["Switch", "AP"]},
    {"id": "control", "nameKey": "category.control", "code": "CONTROL",
     "types": "PISCU · HMI · ICU", "matches": ["PISCU", "HMI", "ICU"]},
]


def category_for(device_type: str) -> str:
    for category in CATEGORIES:
        if category["matches"] and device_type in category["matches"]:
            return category["id"]
    return "control"


# ── read methods ────────────────────────────────────────────────────────
# `group`: the set that may share one credential. If the user picks "apply
# this account to the group" it is stored under that name (see
# panel.credentials).
READ_METHODS = {
    "kyland": {"code": "KYLAND", "path": "/stat/basicInfo", "group": "switch",
               "needsAuth": True, "period": 10},
    "isapi": {"code": "ISAPI", "path": "/ISAPI/System/deviceInfo",
              "group": "video", "needsAuth": True, "period": 10},
    "http": {"code": "HTTP", "path": "/api/v1/system/settings",
             "group": "announcement", "needsAuth": False, "period": 3},
    "app": {"code": "MQTT", "path": "ALFA/AppStatus/#", "group": None,
            "needsAuth": False, "period": 1},
    "mqtt": {"code": "MQTT", "path": "ALFA/DeviceMap (retained)", "group": None,
             "needsAuth": False, "period": 1},
    "adb": {"code": "ADB", "path": "adb getprop · dumpsys · logcat (5555)",
            "group": None, "needsAuth": False, "period": 0},
}


def read_method_for(device_type: str, subtype: str | None) -> str:
    """Which reader handles this device type.

    This is the panel's own map: how a device is READ and WRITTEN while the
    panel is open. The COLLECTORS table in field_scripts/device_verify.py
    answers a narrower question — which extra query the checklist export
    makes — and the two are deliberately not the same table.

    Where they overlap they must agree, and one device is deliberately in
    this map and not in that one (Announcement/UIC: the panel writes its
    settings over HTTP, but the checklist gets every UIC field it reports
    from DeviceMap). That is pinned by
    tests/test_data.py:ReadMethodsMatchTheFieldScript — a claim in a
    docstring could not be checked, and was already untrue when it said the
    two mirrored each other.

    `mqtt` is the fallback: described by DeviceMap, asked nothing directly.
    """
    if device_type == "Switch":
        return "kyland"
    if device_type in ("Camera", "NVR"):
        return "isapi"
    if device_type == "Announcement" and (subtype or "") in (
            "Amplifier", "Handset", "Intercom", "UIC"):
        return "http"
    if device_type in ("PISCU", "HMI"):
        return "app"
    if device_type == "LCD" and (subtype or "") == "Compartment":
        return "adb"
    return "mqtt"


# ── groups that operations can target ───────────────────────────────────
# ops: ip = IP assignment, cfg = configuration, fw = firmware, check = checklist
#
# `name` is the CONTRACT: it travels in API calls, is stored in the saved
# configuration defaults and keys the RUNNERS table. `labelKey` is the only
# thing shown on screen. Most groups are product names that read the same in
# every language, so their key resolves back to the same word.
GROUPS = [
    {"name": "Intercom", "type": "Announcement", "subtype": "Intercom",
     "ops": "ip cfg fw check"},
    {"name": "Handset", "type": "Announcement", "subtype": "Handset",
     "ops": "cfg fw check"},
    {"name": "Amplifier", "type": "Announcement", "subtype": "Amplifier",
     "ops": "cfg fw check"},
    {"name": "UIC", "type": "Announcement", "subtype": "UIC",
     "ops": "cfg fw check"},
    # The Compartment LCD is commissioned and receives its APK over adb.
    # No labelKey on either LCD: "Compartment" and "Landing" are the SubType
    # values in DeviceMap and appear in every device name it publishes
    # (Compartment_Lcd_3). Translating the group heading while the rows under
    # it keep the DeviceMap spelling makes them read as two different things.
    {"name": "Compartment LCD", "type": "LCD", "subtype": "Compartment",
     "ops": "ip cfg fw check"},
    {"name": "Landing LCD", "type": "LCD",
     "subtype": "Landing", "ops": "check"},
    {"name": "LED", "type": "LED", "subtype": "Front", "ops": "check"},
    {"name": "ICU", "type": "ICU", "subtype": "", "ops": "check"},
    # Video equipment is configured, not addressed: the camera and NVR
    # addresses are set by hand in the field and the panel never writes one.
    # What it writes is the configuration — time, streams, the NVR's input
    # channels (see panel.video_config).
    {"name": "Camera", "labelKey": "group.camera", "type": "Camera",
     "subtype": "", "ops": "cfg check"},
    {"name": "NVR", "type": "NVR", "subtype": "", "ops": "cfg check"},
    {"name": "AP", "type": "AP", "subtype": "", "ops": "check"},
    {"name": "PISCU", "type": "PISCU", "subtype": "", "ops": "check"},
    {"name": "HMI", "type": "HMI", "subtype": "", "ops": "check"},
    {"name": "All", "labelKey": "group.all", "type": "*", "subtype": "",
     "ops": "check"},
]


def find_group(name: str) -> dict | None:
    return next((g for g in GROUPS if g["name"] == name), None)


def group_matches(group: dict, device) -> bool:
    if group["type"] == "*":
        return device.type != "Switch"
    if device.type != group["type"]:
        return False
    return (not group["subtype"]) or (device.subtype or "") == group["subtype"]


def group_supports(group: dict | None, op: str) -> bool:
    """Is this operation declared in the group's metadata?"""
    return bool(group) and op in str(group.get("ops", "")).split()


def device_supports(device, op: str) -> bool:
    """Does the device fall into any group that declares this operation?"""
    return any(group_supports(g, op) and group_matches(g, device)
               for g in GROUPS)
