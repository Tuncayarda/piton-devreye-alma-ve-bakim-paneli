#!/usr/bin/env python3
"""The Yatakli sleeper train.

Every announcement kind Piton makes except the gooseneck, the corridor and
landing cameras with their recorder, and the compartment displays — the one
project whose displays are commissioned port by port.
"""
from ._rules import (ANDROID_DISPLAY, ANNOUNCEMENT_HTTP, CONTROL_APP,
                     SWITCH_KYLAND, VIDEO_ISAPI)

KEY = "yatakli"

RULES = (
    SWITCH_KYLAND,        # two KYLAND switches
    ANNOUNCEMENT_HTTP,    # Intercom, Handset, Amplifier, UIC
    VIDEO_ISAPI,          # the corridor and landing cameras, and the NVR
    CONTROL_APP,          # the PISCU and the HMI
    ANDROID_DISPLAY,      # the Compartment LCDs
)
# Not listed, and asked nothing on purpose: the Landing LCD is a passive
# screen the PISCU drives, and so are the LED strips, the access point and
# the ICU. They are in DeviceMap and that is all the panel knows of them.
