#!/usr/bin/env python3
"""How a kind of device is talked to — the shared rules, each with a name.

A RULE answers two questions about one family of equipment: which reader
reaches it, and what decides its configuration field set. They are two
answers to one fact, which is why they live on the same object: the video
gear is read over ISAPI *and* its fields are decided by the device Type,
and neither of those is true of announcement equipment.

THESE ARE NAMES, NOT A TABLE. Nothing here is applied to anything; a project
picks the rules it uses (see the modules beside this one), and a project
whose equipment does not behave like the others writes a rule of its own
rather than bending one of these. That is the whole point of the split: a
customer's Intercom can stop answering like everybody else's without a
single line changing for the other four trains.

The field set a rule points at is defined in `panel/config_sync/fields.py`,
keyed by the scope this returns.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """One family of equipment, and how the panel deals with it.

    `subtypes` of None means "every SubType of these types" — the Camera
    SubTypes are project vocabulary (Corridor, Panto, Cabin…) and say nothing
    about the interface, so listing them would be listing the customer's
    words rather than a fact about the hardware.

    `scope_by` names what decides the field set. "subtype" for announcement
    equipment, where the SubType IS the interface; "type" for video, where it
    is not.
    """

    name: str
    types: tuple[str, ...]
    subtypes: tuple[str, ...] | None
    read: str
    scope_by: str = "subtype"

    def covers(self, device_type: str, subtype: str | None) -> bool:
        return (device_type in self.types
                and (self.subtypes is None or (subtype or "") in self.subtypes))

    def scope(self, device_type: str, subtype: str | None) -> str:
        return device_type if self.scope_by == "type" else (subtype or "")


# The managed switch. One reader, no SubTypes — a switch is a switch.
SWITCH_KYLAND = Rule("switch/kyland", ("Switch",), None, "kyland")

# Piton's announcement controllers. Every one of them answers the same HTTP
# surface; what differs between them is WHICH fields that surface carries,
# which is why the scope is the SubType.
ANNOUNCEMENT_HTTP = Rule(
    "announcement/http", ("Announcement",),
    ("Amplifier", "Handset", "Intercom", "Swanneck", "UIC"), "http")

# Hikvision cameras and recorders, over ISAPI. Scoped by TYPE: a camera's
# SubType is where the customer wrote what the camera is pointed at.
VIDEO_ISAPI = Rule("video/isapi", ("Camera", "NVR"), None, "isapi",
                   scope_by="type")

# The control units. Read from what they publish over MQTT rather than asked
# directly — there is no settings surface on either.
CONTROL_APP = Rule("control/app", ("PISCU", "HMI"), None, "app")

# The Android displays. All of them are reached over ADB and none has a
# settings API: the address is written with `panel/config_sync/adb_network.py`
# and the application arrives as an APK.
#
# The SubTypes are listed because on these they are NOT project vocabulary —
# each one is a different screen in a different place, and a display kind
# nobody has declared should fall through to "described by DeviceMap, asked
# nothing" rather than have adb tried on it.
ANDROID_DISPLAY = Rule(
    "display/adb", ("LCD",), ("Compartment", "Twin", "LINE", "PIS"), "adb")

# The reader for everything no rule claims: described by DeviceMap, asked
# nothing directly. Not a rule a project lists — it is what is left.
PASSIVE = "mqtt"
