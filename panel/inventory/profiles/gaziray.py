#!/usr/bin/env python3
"""Gaziray.

Four cars on four networks, two PISCUs, and the twin display. The routers are
in DeviceMap and asked nothing — they are the only project with them.
"""
from ._rules import (ANDROID_DISPLAY, ANNOUNCEMENT_HTTP, CONTROL_APP,
                     SWITCH_KYLAND, VIDEO_ISAPI)

KEY = "gaziray"

RULES = (
    SWITCH_KYLAND,        # eight KYLAND switches
    ANNOUNCEMENT_HTTP,    # Intercom, Amplifier, Swanneck, UIC
    VIDEO_ISAPI,          # the cameras and the NVR
    CONTROL_APP,          # the Master and Slave PISCUs, and the HMI
    ANDROID_DISPLAY,      # the Twin display
)
