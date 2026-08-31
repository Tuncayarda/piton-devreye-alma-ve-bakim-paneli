#!/usr/bin/env python3
"""In-memory stores for user-entered target values.

Two levels: a value written for a whole group (entered once when the same
setting goes to every announcement device) and a value for one device (when
that device differs). The device-specific value wins.

DeviceMap device and group ids repeat across sets, so the store key is always
``(setNo, deviceId/group)``. Otherwise a maintenance value prepared on Set 1
would silently move to Set 2 when that set was opened.
"""
from __future__ import annotations

import threading

DEVICE_TARGETS: dict[tuple[int, str], dict] = {}
GROUP_TARGETS: dict[tuple[int, str], dict] = {}

LOCK = threading.Lock()
