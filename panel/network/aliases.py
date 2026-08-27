#!/usr/bin/env python3
"""Adding secondary addresses, and always taking them back.

The panel changes the operating system's network configuration here. Three
rules hold the whole module together:

  1. ONLY ADD. An existing address is never modified, never removed, never
     replaced. What goes away is exactly what this application put there.
  2. WRITE THE RECORD FIRST. The record file is updated BEFORE the command
     runs, so a process killed between the two still leaves a trace to clean
     up. A record for an address that was never added is harmless — removing
     an address that is not there fails and is ignored. The reverse is not
     harmless: an address nobody knows about, on a field laptop.
  3. NEVER CLAIM MORE THAN HAPPENED. An address counts as added only when the
     command succeeded AND the address is then visible on the adapter.

The addresses last for the session: they are taken back when the application
closes (`panel.api.lifecycle.reset`), because a scan, a configuration write
and a firmware upload after the run all need the same reachability the run
needed. A crash skips that, which is what `sweep_stale` is for — and on
Windows `store=active` means a reboot clears them regardless.
"""
from __future__ import annotations

import ipaddress
import json
import os
import platform
import threading
import time

from .. import settings
from ..elevation.privileges import process_alive
from ..system import interfaces
from . import adapters as adapter_module
from . import commands

# Adding and removing touch the same record file from the job queue, the API
# and shutdown.
_LOCK = threading.RLock()

# A hard off switch for the one thing in this package that changes the
# machine: adding an address.
#
# It exists because the test suite reconfigured a developer's computer. Full
# scans and IP runs are exercised end to end with fake devices, and once those
# jobs began preparing the network, `ifconfig alias` ran for real — four
# addresses were left on a laptop's live interface by `unittest discover`.
# Faking `subprocess` inside the network tests was not enough: every OTHER
# test that starts a job goes through here too.
#
# So the switch is off for the whole suite (see tests/support/base.py) and on
# everywhere else. Tests that do exercise this path turn it back on and fake
# the command.
WRITES_ALLOWED = os.environ.get("PANEL_NETWORK_WRITES", "1") != "0"


def record_file():
    """Where the addresses this application added are written down.

    Next to the panel's other state (see `settings.data_dir`). It holds no
    credentials — an interface name, an address and the owning pid.
    """
    return settings.data_dir() / "network_aliases.json"


def _read_records() -> list[dict]:
    try:
        raw = json.loads(record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = raw.get("aliases") if isinstance(raw, dict) else raw
    return [entry for entry in (entries or []) if isinstance(entry, dict)]


def _write_records(entries: list[dict]) -> None:
    path = record_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"aliases": entries}, indent=2),
                        encoding="utf-8")
    except OSError:
        # Losing the record does not justify losing the address that is
        # already on the adapter; the session teardown still holds it in
        # memory.
        pass


def _same(entry: dict, ip: str, handle: str = "") -> bool:
    return (entry.get("ip") == ip
            and (not handle or entry.get("handle") == handle))


def _remember(entry: dict) -> None:
    with _LOCK:
        entries = [item for item in _read_records()
                   if not _same(item, entry["ip"], entry["handle"])]
        entries.append(entry)
        _write_records(entries)


def _forget(ip: str, handle: str = "") -> None:
    with _LOCK:
        _write_records([item for item in _read_records()
                        if not _same(item, ip, handle)])


def active() -> list[dict]:
    """The addresses this process added and has not taken back."""
    pid = os.getpid()
    return [entry for entry in _read_records() if entry.get("pid") == pid]


def _visible(handle: str, ip: str) -> bool:
    """Is the address really on the adapter now?

    Asked after every add: `ifconfig` and `netsh` can return 0 and still not
    have applied the address (a duplicate, a driver that refuses it). Reporting
    it as added would send the run off to look for devices it cannot reach and
    hide the reason.
    """
    for adapter in adapter_module.list_adapters():
        if adapter.handle != handle and adapter.name != handle:
            continue
        if any(address == ip for address, _prefix in adapter.addresses):
            return True
    return False


def _adapter_addresses(handle: str) -> list[tuple[str, int]]:
    """What the interface holds right now, by either of its names."""
    for adapter in adapter_module.list_adapters():
        if adapter.handle == handle or adapter.name == handle:
            return list(adapter.addresses)
    return []


def _network_is_served(handle: str, ip: str, prefix: int) -> bool:
    """Does an address the interface already holds carry this network's route?

    Not "is some address inside it": a sibling host alias sits inside the
    network without carrying anything. The question is whether the route
    exists, which is whether another address's OWN network covers ours — so a
    /32 never counts, and a /16 covering our /24 does.
    """
    network = ipaddress.ip_network(f"{ip}/{int(prefix)}", strict=False)
    for address, held_prefix in _adapter_addresses(handle):
        if address == str(ip):
            continue                       # our own address, re-added
        try:
            held = ipaddress.ip_network(f"{address}/{int(held_prefix)}",
                                        strict=False)
        except ValueError:
            continue
        if held.prefixlen < 32 and (network == held
                                    or network.subnet_of(held)):
            return True
    return False


def alias_prefix(handle: str, ip: str, prefix: int,
                 system: str | None = None) -> int:
    """The prefix the alias is really given.

    macOS binds a subnet's route to the address that claimed it, and keeps
    that binding when the address goes away. An alias added with the full /24
    NEXT TO an address already in that /24 takes the route over, and
    `ifconfig -alias` then removes the address but leaves the route pointing
    at it. The interface still holds a live address; every route in the subnet
    still names the dead one; and every connect() into it fails instantly with
    EADDRNOTAVAIL, "Can't assign requested address".

    This happened on a field machine. After a session ended, `netstat -rnl`
    showed the whole /24 with RT_IFA on the alias the panel had taken back,
    and a full scan failed on every device in milliseconds — not a timeout, no
    packet ever left. `commands.add_command` already names the rule; it was
    left to `planning.required_networks` to guarantee the case never arose,
    and it cannot: the interface may be given its address (a cable plugged in,
    a manual configuration applied) AFTER the alias was added.

    So the prefix is decided here, against the interface as it is at the
    moment of the write. A host alias never claims the subnet route and so can
    never strand it; the full prefix is used only when the route does not
    exist yet and we are the ones creating it.
    """
    if (system or platform.system()) != "Darwin":
        return int(prefix)
    return 32 if _network_is_served(handle, ip, prefix) else int(prefix)


def add(handle: str, ip: str, prefix: int, adapter_name: str = "",
        system: str | None = None) -> dict:
    """Add one address. Returns the record; raises RuntimeError on failure."""
    system = system or platform.system()
    if not WRITES_ALLOWED:
        raise RuntimeError("network writes are switched off")
    if not commands.supported(system):
        raise RuntimeError(f"unsupported system: {system}")
    # The prefix that goes on the wire is not always the network's own; see
    # `alias_prefix`. The record keeps what was really assigned, because that
    # is what the removal and the queue row have to be about.
    assigned = alias_prefix(handle, ip, prefix, system)
    entry = {"ip": str(ip), "prefix": assigned, "handle": str(handle),
             "adapter": adapter_name or str(handle), "system": system,
             "pid": os.getpid(), "addedAt": time.time()}
    # Rule 2: the record goes down before the command runs.
    _remember(entry)
    code, output = interfaces.run_command(
        commands.add_command(handle, ip, assigned, system), timeout=10.0)
    if code != 0 or not _visible(handle, str(ip)):
        _forget(str(ip), str(handle))
        detail = " ".join((output or "").split())[:160]
        raise RuntimeError(detail or f"{ip}/{assigned} could not be added")
    return entry


def remove(entry: dict, system: str | None = None) -> bool:
    """Take one address back. Returns whether the address is now gone.

    A failure is not raised: the caller is usually shutdown, and stopping
    there would strand the remaining addresses too.

    THE RECORD IS KEPT WHEN THE ADDRESS IS STILL THERE. Dropping it either way
    was worse than useless — the address stayed on the adapter with nothing
    left pointing at it, so the next start-up sweep had nothing to retry and
    the only remaining cleanup was by hand. It happened for real: an
    unprivileged process cannot take back what an elevated one added, and the
    panel is normally the elevated one.

    An address that is not on the adapter counts as gone even when the command
    complained — removing something that was never there is not a failure.
    """
    system = system or entry.get("system") or platform.system()
    handle, ip = str(entry.get("handle", "")), str(entry.get("ip", ""))
    ok = False
    if commands.supported(system):
        code, _output = interfaces.run_command(
            commands.remove_command(handle, ip,
                                    int(entry.get("prefix") or 24), system),
            timeout=10.0)
        ok = code == 0
    if ok or not _visible(handle, ip):
        _forget(ip, handle)
        return True
    return False


def release(ip: str) -> bool:
    """Take back one address of this session, by address."""
    for entry in active():
        if entry.get("ip") == str(ip):
            return remove(entry)
    return False


def release_all() -> int:
    """Take back every address this process added. Returns how many."""
    with _LOCK:
        entries = active()
    removed = 0
    for entry in entries:
        try:
            if remove(entry):
                removed += 1
        except Exception:
            continue
    return removed


def sweep_stale() -> int:
    """Remove records left by a process that is gone. Called once at start-up.

    A crash (or a kill) skips the session teardown and leaves an address on
    the adapter with nothing left to remove it. The pid in the record answers
    whether that happened: another live pid means a second copy of the panel
    is running and its addresses are its own business.
    """
    pid = os.getpid()
    stale = [entry for entry in _read_records()
             if entry.get("pid") != pid
             and not process_alive(int(entry.get("pid") or 0))]
    removed = 0
    for entry in stale:
        try:
            if remove(entry):
                removed += 1
        except Exception:
            continue
    # What was really taken back, not what was attempted: a record that could
    # not be removed stays for the next start-up to try again.
    return removed
