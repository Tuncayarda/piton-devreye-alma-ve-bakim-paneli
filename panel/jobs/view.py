#!/usr/bin/env python3
"""The current device state for one train set."""
from __future__ import annotations

import itertools
import threading

from ..probe import result as probe_result

# Read generation — one counter that only grows, for the whole process.
_GENERATION = itertools.count(1)


def next_generation() -> int:
    return next(_GENERATION)


class DeviceStateView:
    """The latest known result per device in one train set."""

    def __init__(self, set_no: int):
        self.set_no = set_no
        self._results: dict[str, probe_result.ProbeResult] = {}
        self._lock = threading.Lock()
        self.last_scan: float | None = None
        self._epoch = 0

    @property
    def epoch(self) -> int:
        """Which LIFE of this view a writer is writing into.

        Bumped by `clear()`. A sweep captures it once at start and hands it
        back with every write: the view object survives a project switch on
        purpose (see `clear_all`), so without this a scan cancelled FOR the
        switch could still land the OLD project's results in the NEW
        project's view — same ids, different hardware, green rows.
        """
        with self._lock:
            return self._epoch

    def write(self, device_id: str, result: probe_result.ProbeResult,
              epoch: int | None = None) -> bool:
        """Store a result. Returns False (and stores nothing) if a newer one
        is already there — a late scan reply must not undo a fresh success —
        or if the writer's `epoch` predates a `clear()`: those results
        belong to a device list that is no longer open."""
        with self._lock:
            if epoch is not None and epoch != self._epoch:
                return False
            existing = self._results.get(device_id)
            if existing is not None and existing.generation > result.generation:
                return False
            self._results[device_id] = result
            return True

    def get(self, device_id: str) -> probe_result.ProbeResult | None:
        with self._lock:
            return self._results.get(device_id)

    def all(self) -> dict[str, probe_result.ProbeResult]:
        with self._lock:
            return dict(self._results)

    def counts(self) -> dict:
        return probe_result.tally(self.all().values())

    def awaiting_credentials(self) -> list[str]:
        return [device_id for device_id, result in self.all().items()
                if probe_result.needs_auth(result)]

    def clear(self) -> None:
        with self._lock:
            self._results.clear()
            # The stamp goes with the results it was stamped for. Kept, it
            # would date an EMPTY view — and `lastScan` is what the checklist
            # banner trusts to say "verified recently", so an old timestamp
            # over no data reads as a fresh verification of nothing.
            self.last_scan = None
            # And writers born before this clear are cut off — see `epoch`.
            self._epoch += 1


_VIEWS: dict[int, DeviceStateView] = {}
_VIEWS_LOCK = threading.Lock()


def view_for(set_no: int) -> DeviceStateView:
    with _VIEWS_LOCK:
        return _VIEWS.setdefault(int(set_no), DeviceStateView(int(set_no)))


def clear_all() -> None:
    """Empty every set's view, in place. The view OBJECTS survive.

    For when the device ids stop meaning what they meant: switching to
    another project's DeviceMap (see `panel.api.lifecycle.switch_project`),
    and between tests. Ids are positional — "sw1.d3" is the third device on
    the first switch — so a result kept across the switch would be shown
    against different hardware, in green, with a timestamp that looks fresh.

    IN PLACE is the load-bearing part. A sweep captures its view once at
    start (`sweep.sweep_devices` calls `view_for` and holds the reference);
    rebuilding the registry here left that sweep writing into an orphan
    nothing would ever read again, so a scan racing a project switch
    finished green with every result silently gone. Emptying each view and
    keeping it registered means a captured reference IS the live object.
    """
    with _VIEWS_LOCK:
        views = list(_VIEWS.values())
    for view in views:
        view.clear()
