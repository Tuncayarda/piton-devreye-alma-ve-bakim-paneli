#!/usr/bin/env python3
"""Device categories, operation groups and the read-method map.

Single source of truth for the sidebar and the target-group pickers; the UI
keeps no list of its own and takes these from the API.
"""
from __future__ import annotations

from . import profiles

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
    # The router sits here with the switch and the access point because that
    # is what it is, and because the sidebar is the only place its two units
    # would otherwise appear — `category_for` drops anything it does not
    # recognise into "control", which is where Gaziray's routers were being
    # listed, next to the PISCU.
    {"id": "network", "nameKey": "category.network", "code": "NET",
     "types": "Switch · AP · Router", "matches": ["Switch", "AP", "Router"]},
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
    """Which reader handles this device type, on ANY project.

    The shared rules, asked without a project — which is the right question
    for the two callers that have no project to ask about: the checklist
    template generator (`tools/make_checklist_template.py`) builds one
    workbook per DeviceMap from the vocabulary, and
    `tests/test_data.py:ReadMethodsMatchTheFieldScript` joins this table to
    `field_scripts/device_verify.py:COLLECTORS`, which has no project
    dimension either.

    A DEVICE IS NOT READ THROUGH THIS. `panel/inventory/profiles` answers
    for the project the device came from, and `Device.read_method` is filled
    in from there when the map is loaded. The two agree today for every
    device in every shipped map (`tests/test_data.py`), and the whole reason
    the profiles exist is that they are allowed to stop agreeing: a customer
    whose Intercom answers somewhere else says so in their own file, and no
    other project moves.

    `mqtt` is the fallback: described by DeviceMap, asked nothing directly.
    """
    return profiles.SHARED.read_method(device_type, subtype)


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
    # The gooseneck microphone. Same Piton announcement firmware as the
    # Intercom — same endpoints, same field set — so it is configured and
    # updated the same way. Not addressed by the panel: like the Handset it
    # is set up by hand and then only configured.
    {"name": "Swanneck", "type": "Announcement", "subtype": "Swanneck",
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
    # The twin display, on the exhibition rack. Android like the Compartment
    # LCD: its address is written over ADB and its application arrives as an
    # APK. NO `ip` — the port-by-port commissioning run behind that operation
    # is written for the Compartment LCD alone (panel/ip_assign/lcd_runner.py
    # filters on the SubType, and the IP screen has its own bench mode for
    # it). On a map with literal addresses it would have nothing to do
    # anyway: source and target set resolve to the same address.
    {"name": "Twin LCD", "type": "LCD", "subtype": "Twin",
     "ops": "cfg fw check"},
    # GDM's two screens: the passenger information display and the line
    # diagram. The same Android hardware as the Compartment LCD, so the same
    # three operations reach them — `cfg` and `fw` both branch on the
    # device's READ METHOD rather than on the group (see
    # `panel/config_sync/apply.py` and `panel/firmware/__init__.py`), and
    # that method is `adb` for all four displays.
    #
    # NO `ip`, for the same reason the Twin LCD has none: the port-by-port
    # commissioning run behind that operation is written for the Compartment
    # LCD alone (`panel/ip_assign/lcd_runner.py` filters on the SubType, and
    # `runner.RUNNERS` has one entry). Their addresses are written on the
    # device settings screen instead, one at a time.
    #
    # No labelKey, like the LCDs above: "LINE" and "PIS" are the SubType
    # values in DeviceMap and appear in every device name it publishes
    # (Line_LCD_1_Mc1, Pis_LCD_1_Mc1). Translating the group heading while
    # the rows under it keep the DeviceMap spelling makes them read as two
    # different things.
    {"name": "LINE LCD", "type": "LCD", "subtype": "LINE",
     "ops": "cfg fw check"},
    {"name": "PIS LCD", "type": "LCD", "subtype": "PIS",
     "ops": "cfg fw check"},
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
    """Does the device fall into any group that declares this operation?

    Searches the whole vocabulary rather than the project's groups, and that
    is right rather than an oversight: the device was looked up in the open
    project's own inventory, so every group it matches is one the project
    has by construction. Narrowing this would ask the same question twice.
    """
    return any(group_supports(g, op) and group_matches(g, device)
               for g in GROUPS)


# ── what THIS project has ───────────────────────────────────────────────
# GROUPS above is the whole vocabulary: everything the panel knows how to do
# to anything, across every project. It is not a list any one operator should
# be offered. The target pickers were being handed it whole, so a Yatakli
# train listed the exhibition rack's Twin LCD and GDM's two screens, and the
# IP screen offered a Compartment LCD commissioning run on a project with no
# Compartment LCD in it.
#
# DERIVED FROM THE MAP, not declared on the project. The cost of that is real
# and worth writing down: this cannot tell "no Handset on this train" from
# "no Handset FITTED YET", so a device kind nobody has installed is missing
# from the picker until the first one appears in DeviceMap. The opposite
# choice has the opposite cost — a list to maintain by hand, which is how
# GROUPS came to describe five projects at once in the first place.
#
# `panel/editions/catalogue.py` argues for DECLARING where the two claims
# genuinely differ (`fixed_addressing`), and `Inventory.span` argues for
# COMPUTING where they do not. This is the second kind: "the picker offers
# what the operator can actually point at" has one answer, and the map is it.


def groups_for(inventory) -> list[dict]:
    """The groups the open project actually has devices for.

    Matched with `group_matches` rather than against a second table of type
    names — one matcher, so a group cannot be offered by one rule and refused
    by another.
    """
    return [group for group in GROUPS
            if any(group_matches(group, device)
                   for device in inventory.devices)]


def group_in(inventory, name: str) -> dict | None:
    """`find_group`, but only for a group the open project has.

    The API's half of the same rule. A picker that no longer offers a group
    is not a guarantee: the client may be holding a list from the project
    that was open a moment ago, and this is the write path.
    """
    group = find_group(name)
    if group is None:
        return None
    return group if any(group_matches(group, device)
                        for device in inventory.devices) else None
