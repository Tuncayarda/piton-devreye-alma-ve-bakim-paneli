#!/usr/bin/env python3
"""The exhibition rack.

One switch and the twelve devices shown beside it. Not a train: the hardware
is borrowed and the addresses are literal rather than templated (see the
`stand` flag in `panel/editions/catalogue.py`). Cameras without a recorder —
they record to their own cards here.
"""
from ._rules import (ANDROID_DISPLAY, ANNOUNCEMENT_HTTP, CONTROL_APP,
                     SWITCH_KYLAND, VIDEO_ISAPI)

KEY = "fuar"

RULES = (
    SWITCH_KYLAND,        # one KYLAND switch
    ANNOUNCEMENT_HTTP,    # Intercom, Handset, Amplifier, Swanneck
    VIDEO_ISAPI,          # the two cameras
    CONTROL_APP,          # the PISCU and the HMI
    ANDROID_DISPLAY,      # the Twin display
)
