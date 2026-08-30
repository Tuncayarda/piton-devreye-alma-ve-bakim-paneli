#!/usr/bin/env python3
"""GDM.

Four cars, two PISCUs, and two Android screens of its own — the passenger
information display and the line diagram. Same hardware as the Yatakli's
compartment display and read the same way, which is why they share the rule.

The induction loop is announcement equipment by Type but is not one of the
controllers that answers over HTTP, so it falls through to passive: the panel
knows it from DeviceMap and asks it nothing.
"""
from ._rules import (ANDROID_DISPLAY, ANNOUNCEMENT_HTTP, CONTROL_APP,
                     SWITCH_KYLAND, VIDEO_ISAPI)

KEY = "gdm"

RULES = (
    SWITCH_KYLAND,        # eight KYLAND switches
    ANNOUNCEMENT_HTTP,    # Intercom, Amplifier, Swanneck
    VIDEO_ISAPI,          # the cameras and the NVR
    CONTROL_APP,          # the Master and Slave PISCUs, and the HMI
    ANDROID_DISPLAY,      # the LINE and PIS screens
)
