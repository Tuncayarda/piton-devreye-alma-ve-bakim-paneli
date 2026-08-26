#!/usr/bin/env python3
"""The NVR's channel list, derived from DeviceMap.

The field script carries a hard-coded table per project (YATAKLI_CH,
GDM_CH …): channel number, name, camera address. DeviceMap already holds all
three on the camera's own record —

    {"Type": "Camera", "Name": "Corridor_Cam_1", "CameraID": "1",
     "CameraName": "Corridor 1", "IP": "10.n.1.24", "Port": "1"}

— so the table is read from the inventory instead. A camera added to the
project therefore reaches the NVR without a code change, and the channel
numbers cannot disagree with the ones the rest of the panel shows.
"""
from __future__ import annotations

from ..inventory.device_map import Device, Inventory

# Camera positions that have no microphone fitted. The rule is the field
# script's: audio is enabled on every camera except these.
NO_AUDIO_PREFIXES = ("Rear", "Panto")


def display_name(camera: Device) -> str:
    """What the channel is called on the NVR and in the camera's own OSD.

    DeviceMap's `CameraName` ("Corridor 1") is the spoken name; `Name`
    ("Corridor_Cam_1") is the identifier used everywhere else in the panel
    and is the fallback.
    """
    return str(camera.extra.get("CameraName") or camera.name or "").strip()


def channel_id(camera: Device) -> int | None:
    """DeviceMap's `CameraID` — the NVR input channel this camera occupies."""
    raw = str(camera.extra.get("CameraID") or "").strip()
    return int(raw) if raw.isdigit() else None


def audio_default(camera: Device) -> str:
    """The project's audio setting for this camera, as the field's value.

    Not stored anywhere: a Rear or Panto camera has no microphone, so
    enabling audio on it produces a stream with a dead track.
    """
    return "0" if display_name(camera).startswith(NO_AUDIO_PREFIXES) else "1"


def for_nvr(inventory: Inventory) -> list[tuple[int, str, Device]]:
    """(channel id, name, camera) for every camera in the set, in order.

    Cameras without a CameraID are skipped: there is no channel to put them
    on, and guessing one would overwrite a channel that belongs to another
    camera.
    """
    found = []
    for camera in inventory.by_type("Camera"):
        number = channel_id(camera)
        if number is None or not camera.active:
            continue
        found.append((number, display_name(camera), camera))
    return sorted(found, key=lambda row: row[0])
