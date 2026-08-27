#!/usr/bin/env python3
"""The one place the panel waits for a device.

Every wait that exists because a piece of hardware needs time — a reboot, a
PoE port settling, an address coming back — goes through here, so a test can
let that time pass without spending it.

WHY A MODULE OF OUR OWN, and not `time.sleep` patched in place: `time` is a
single shared module object. `mock.patch("panel.somewhere.time.sleep")` and
`mock.patch.object(module.time, "sleep")` write to the SAME attribute on the
SAME object, for the whole process — the job queue's own threads included.
A "per-module" patch of `time` is an illusion, and a suite that relies on
one is patching far more than it means to. `panel.system.interfaces` reached
the same conclusion about `subprocess` and exposed `run_command` instead;
this is that pattern, for waiting.

`monotonic` LIVES HERE TOO, and that is not decoration. Almost every wait
below is the sleeping half of a deadline loop. Make `sleep` free but leave
`monotonic` reading the real clock and the loop stops sleeping and starts
SPINNING — the same fifteen seconds, now at full CPU. The two have to move
together or not at all, which is why a test swaps both (see
tests/support/clock.py).

WHAT DOES NOT BELONG HERE. Waits that are threads meeting each other rather
than a device taking its time:

    panel/jobs/                     the queue's own dispatch
    panel/adminkey/watcher.py       the USB poll beat; its tests measure the
                                    real cadence deliberately
    panel/elevation/privileges.py   waiting on an OS elevation prompt; tests
                                    replace those functions whole
    panel/telemetry/client.py       a threading.Event collection window
    panel/api/http_adapter.py       the browser-mode CLI's main loop

A virtual clock would not speed those up, it would only hide their timing.

Timestamps are also not waits: a record's `time.time()` and a cache's TTL
stay on `time`, because they answer "when", not "how long shall I hold".

`field_scripts/` is outside this too. Those three scripts are imported
rather than rewritten (see panel.script_loader), and their waits already
take their duration from an injectable config object (`cfg.poll_interval`,
`cfg.settle`, `cfg.post_write_wait`).
"""
from __future__ import annotations

import time as _time


def sleep(seconds: float) -> None:
    """Wait `seconds`. A negative or zero duration returns at once."""
    _time.sleep(max(0.0, seconds))


def monotonic() -> float:
    """Now, on a clock that only moves forward. Deadlines are built on this."""
    return _time.monotonic()
