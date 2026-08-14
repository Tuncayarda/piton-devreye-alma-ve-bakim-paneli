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

    def write(self, device_id: str,
              result: probe_result.ProbeResult) -> bool:
        """Store a result. Returns False (and stores nothing) if a newer one
        is already there — a late scan reply must not undo a fresh success."""
        with self._lock:
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


_VIEWS: dict[int, DeviceStateView] = {}
_VIEWS_LOCK = threading.Lock()


def view_for(set_no: int) -> DeviceStateView:
    with _VIEWS_LOCK:
        return _VIEWS.setdefault(int(set_no), DeviceStateView(int(set_no)))
