#!/usr/bin/env python3
"""ADB: the transport every screen shares, and the device pool of its own.

Two different things live here and they are deliberately kept apart.

**The transport** (`binary`, `client`) is the panel's only way of running
``adb``. It was written for the Compartment LCD commissioning run and grew
three uncoordinated copies — one per screen that needed a device command —
each with its own idea of what a timeout or a missing executable means, and
worse, its own connect proof: the probe inferred reachability from a getprop
answer while the ADB screen demanded ``get-state`` say ``device``, so one
display could be red on the scan and green on the ADB screen at the same
moment. There is one transport now — `panel.probe.android` and
`panel.firmware.apk_install` run on it too, pinned by a source scan in
tests/test_adb.py — and every caller gets the same bounded wait, the same
``-s <ip>:5555`` scoping, the same connect proof and the same two error
classes. Callers sharing one display at one moment take a `client.lease` so
neither tears down the transport under the other.

**The ADB screen** (`pool`, `packages`, `apps`, `autostart`, `runner`) is a
tool in its own right and knows nothing about DeviceMap. Its devices are a
list of addresses the user keeps (`pool`); its work is starting, stopping,
installing and removing applications on several of them at once (`runner`).
Nothing here reads the project, and nothing here enters the job queue — see
`runner` for why that is not an oversight.

Only `binary` and `client` are re-exported. The screen's modules are imported
by path (``from panel.adb import runner``) so that importing the transport —
which `panel.probe.android` and `panel.firmware.apk_install` both do — never
drags the whole screen in behind it.
"""

from . import binary, client
from .binary import adb_path
from .client import AdbTimeout, AdbUnavailable

__all__ = ["AdbTimeout", "AdbUnavailable", "adb_path", "binary", "client"]
