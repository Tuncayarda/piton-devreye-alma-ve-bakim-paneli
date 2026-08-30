#!/usr/bin/env python3
"""The VIP train.

The Yatakli's equipment without the displays: there is no LCD of any kind on
this train, so the Android rule is deliberately absent rather than listed and
unused. If one is ever fitted, `tests/test_data.py` will say so — it fails on
a device kind that falls through to "passive" without being named as passive.
"""
from ._rules import (ANNOUNCEMENT_HTTP, CONTROL_APP, SWITCH_KYLAND,
                     VIDEO_ISAPI)

KEY = "vip"

RULES = (
    SWITCH_KYLAND,        # one KYLAND switch
    ANNOUNCEMENT_HTTP,    # Intercom, Handset, Amplifier, UIC
    VIDEO_ISAPI,          # the corridor and landing cameras, and the NVR
    CONTROL_APP,          # the PISCU and the HMI
)
