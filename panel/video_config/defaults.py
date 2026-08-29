#!/usr/bin/env python3
"""The project's settings for video equipment, where DeviceMap says nothing.

Every value here is the one the field scripts have been applying on trains.
They are DEFAULTS, not constants: DeviceMap wins over them (a `Config`
block, or the camera's own record), and a value entered on the screen wins
over both — the ordinary target precedence in panel.config_sync.targets.

Keeping them out of the field table means a project that differs changes
data, not code.
"""
from __future__ import annotations

from .. import settings
from ..editions import runtime as editions
from . import channels, payloads

# The IR illuminator is switched off: the cameras sit behind glass, where the
# lamp reflects straight back into the lens.
IR_MODE = "close"
# The third stream feeds the wall; it is enabled on every camera.
THIRD_STREAM = "1"
# The NVR's buzzer is silenced — it sits in an equipment cabinet on a train.
BUZZER = "0"


def for_field(device, inventory, name: str) -> str:
    """The project default for one field, or "" when there is none."""
    if name == "ntpServer":
        # The project's clock source — the PISCU on most trains, and a
        # machine of its own on Gaziray and GDM. Same rule as the SIP
        # registrar (see `panel.editions.catalogue.Project.broker`).
        return editions.ntp_ip(inventory) or ""
    if name == "timeZone":
        return settings.EXPECTED_TIMEZONE
    if name == "channelName":
        return channels.display_name(device)
    if name == "audioEnabled":
        return channels.audio_default(device)
    if name == "irLight":
        return IR_MODE
    if name == "thirdStream":
        return THIRD_STREAM
    if name == "stream3Resolution":
        return payloads.DEFAULT_STREAM3
    if name == "buzzer":
        return BUZZER
    return ""
