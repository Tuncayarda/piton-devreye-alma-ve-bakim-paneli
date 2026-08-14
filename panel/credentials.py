#!/usr/bin/env python3
"""In-memory device credential store.

The rule in one sentence: usernames and passwords live ONLY in the running
process's memory. Deliberately absent here: writing to a file (json / .env /
sqlite / keychain / plist), writing to the environment, disk caches, temp
files, log lines.

`forget_all()` runs on shutdown; once the process dies nothing is left. Every
device that wants a password asks again on the next launch.

Groups exist because one account often covers every switch or every camera.
The default is still per device; sharing happens only when the user asks
(see `remember`).
"""
from __future__ import annotations

import threading

# device key -> (username, password)
_BY_DEVICE: dict[str, tuple[str, str]] = {}
# group name -> (username, password), only when the user opts in
_BY_GROUP: dict[str, tuple[str, str]] = {}
_LOCK = threading.RLock()


def device_key(device_id: str, ip: str) -> str:
    """Name alone or IP alone is not enough: two switches can share a name,
    and one IP points at a different device once the set changes."""
    return f"{device_id}@{ip}"


def remember(device_id: str, ip: str, username: str, password: str,
             group: str | None = None, share_with_group: bool = False) -> None:
    """Store a verified credential.

    Only call this after data really came back from the device — a filled-in
    form proves nothing.
    """
    with _LOCK:
        _BY_DEVICE[device_key(device_id, ip)] = (username, password)
        if share_with_group and group:
            _BY_GROUP[group] = (username, password)


def lookup(device_id: str, ip: str, group: str | None = None):
    """The device's own credential first, then the shared group one."""
    with _LOCK:
        found = _BY_DEVICE.get(device_key(device_id, ip))
        if found:
            return found
        return _BY_GROUP.get(group) if group else None


def has(device_id: str, ip: str, group: str | None = None) -> bool:
    return lookup(device_id, ip, group) is not None


def forget(device_id: str, ip: str) -> None:
    with _LOCK:
        _BY_DEVICE.pop(device_key(device_id, ip), None)


def forget_all() -> None:
    """Called while the application shuts down."""
    with _LOCK:
        _BY_DEVICE.clear()
        _BY_GROUP.clear()


def summary() -> dict:
    """UI-safe summary — CONTAINS NO PASSWORDS.

    Only "is there a credential in memory for this device" plus a masked
    username.
    """
    with _LOCK:
        return {
            "device": {k: mask(v[0]) for k, v in _BY_DEVICE.items()},
            "group": {g: mask(v[0]) for g, v in _BY_GROUP.items()},
        }


def count() -> int:
    with _LOCK:
        return len(_BY_DEVICE)


def mask(username: str) -> str:
    """Shorten a username for logs and summaries: admin -> a***n."""
    name = str(username or "")
    if len(name) <= 2:
        return "*" * len(name)
    return f"{name[0]}{'*' * (len(name) - 2)}{name[-1]}"
