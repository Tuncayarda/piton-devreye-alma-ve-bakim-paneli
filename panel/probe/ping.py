#!/usr/bin/env python3
"""One ICMP echo, asked of the operating system.

The probe's second opinion, not a reader: when a device's own protocol gave
nothing, one ping tells apart the two afternoons that used to share one red
row — a device that is OFF and a device that is up but silent (see
`panel.status`). Nothing here parses ping's output; the locale-dependent text
is exactly why only the exit code is read.

The OS command rather than a raw ICMP socket on purpose: a raw socket needs
root on POSIX, and the panel does not always have it (`--browser` mode, the
tests), while `ping` is setuid/capable everywhere it exists.
"""
from __future__ import annotations

import platform
import subprocess

from ..system.spawn import NO_CONSOLE

# One echo, and how long it may take. Short because this runs after a read
# that already spent its own timeout, inside the same sweep worker.
TIMEOUT = 1.0


def _command(ip: str, timeout: float) -> list[str]:
    system = platform.system()
    if system == "Windows":
        # -w is per-reply, in milliseconds.
        return ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
    if system == "Darwin":
        # -W is the reply wait in MILLISECONDS on macOS, unlike Linux.
        return ["ping", "-c", "1", "-W", str(int(timeout * 1000)), ip]
    return ["ping", "-c", "1", "-W", str(max(1, round(timeout))), ip]


def reachable(ip: str, timeout: float = TIMEOUT) -> bool:
    """Did one echo come back? False on ANY failure, including no `ping`.

    False is the honest default for every problem here: the caller uses True
    to soften a red row into "needs inspection", and a softening that can be
    produced by a broken ping command would hide dead devices.
    """
    if not ip:
        return False
    try:
        done = subprocess.run(_command(str(ip), timeout),
                              capture_output=True,
                              timeout=timeout + 3, check=False,
                              **NO_CONSOLE)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
