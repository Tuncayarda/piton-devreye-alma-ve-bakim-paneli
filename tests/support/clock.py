#!/usr/bin/env python3
"""A clock the suite can run forward without waiting for it.

Stands in for `panel.clock` (see that module for why the panel owns a clock
at all). `sleep` does not sleep — it moves `monotonic` forward by exactly
the amount asked for, so a deadline loop reaches its deadline in the number
of iterations it really would, having spent no time at all.

BOTH halves must be installed together. Swap `sleep` alone and every
`while clock.monotonic() < deadline` loop stops sleeping and starts
spinning: the same wait, now burning a core. `install()` is the only
supported way in, and it takes both.
"""
from __future__ import annotations

from unittest import mock

from panel import clock


class FakeClock:
    """Time passes when something asks to wait, and at no other moment."""

    def __init__(self, start: float = 0.0):
        self.now = float(start)
        self.slept: list[float] = []
        self._patcher = None

    def uninstall(self) -> None:
        """Hand the real clock back. Safe to call twice."""
        if self._patcher is not None:
            self._patcher.stop()
            self._patcher = None

    def sleep(self, seconds: float) -> None:
        seconds = max(0.0, float(seconds))
        self.slept.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now

    @property
    def waited(self) -> float:
        """Total time the code under test believes it waited."""
        return sum(self.slept)


def install(test, start: float = 0.0) -> FakeClock:
    """Put a FakeClock behind `panel.clock` for the rest of `test`.

    Returns it, so a test that cares can assert on how long the code thought
    it was waiting — which is the interesting half, and the half that was
    invisible while the suite waited for real.
    """
    fake = FakeClock(start)
    fake._patcher = mock.patch.multiple(clock, sleep=fake.sleep,
                                        monotonic=fake.monotonic)
    fake._patcher.start()
    test.addCleanup(fake.uninstall)
    return fake
