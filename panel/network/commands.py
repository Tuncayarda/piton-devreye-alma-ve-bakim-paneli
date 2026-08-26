#!/usr/bin/env python3
"""The commands that add and remove a secondary address, per platform.

Pure functions. Building the command line and running it are kept apart for
the same reason as in `panel.elevation.privileges`: the real decision is in
the argument list, and it has to be checkable on every machine, not only on
the one it will run on.

WHAT IS NEVER USED, and why:

  · `netsh interface ipv4 set address` / `netsh ... set dns` — `set` REPLACES
    the adapter's configuration. Everything here only ever ADDS an address
    beside the ones already there and takes back exactly what it added.
  · `New-NetIPAddress` (PowerShell) and `networksetup` (macOS) — both write a
    PERSISTENT address. A process killed mid-run would leave the machine
    reconfigured for good, with nobody left to undo it.

`store=active` on Windows is the same guarantee the other two platforms give
for free: the address lives in the running stack only, never in the registry,
so a reboot clears whatever a crash left behind. `ip addr add` and
`ifconfig alias` are non-persistent by nature.
"""
from __future__ import annotations

import ipaddress
import platform

# Adding an address needs root/Administrator on all three. The application
# already runs elevated (see app.py); this is what the UI reports when it
# somehow does not.
SUPPORTED_SYSTEMS = ("Darwin", "Linux", "Windows")


def netmask(prefix: int) -> str:
    """24 -> '255.255.255.0'. ifconfig and netsh want the dotted form."""
    return str(ipaddress.IPv4Network(f"0.0.0.0/{int(prefix)}").netmask)


def supported(system: str | None = None) -> bool:
    return (system or platform.system()) in SUPPORTED_SYSTEMS


def add_command(handle: str, ip: str, prefix: int,
                system: str | None = None) -> list[str]:
    """Add `ip/prefix` to the interface `handle` addresses.

    `handle` is what THIS platform's tool accepts, not the pretty name: the
    device name on POSIX (`en0`, `enp3s0`), the interface index on Windows
    (see `panel.network.adapters` for why the name will not do there).

    On macOS an alias that lands in the SAME subnet as an address the
    interface already holds must be given /32, or it steals the subnet route
    and strands it on removal. `planning.required_networks` was once trusted
    to keep that case from arising; it cannot, because the interface may be
    given its own address after the alias is already on it. The caller decides
    the prefix against the live interface instead — see `aliases.alias_prefix`.
    """
    system = system or platform.system()
    ip, prefix = str(ip), int(prefix)
    if system == "Darwin":
        return ["ifconfig", handle, "alias", ip, "netmask", netmask(prefix)]
    if system == "Linux":
        return ["ip", "addr", "add", f"{ip}/{prefix}", "dev", handle]
    if system == "Windows":
        return ["netsh", "interface", "ipv4", "add", "address",
                f"name={handle}", f"address={ip}", f"mask={netmask(prefix)}",
                "store=active"]
    raise ValueError(f"unsupported system: {system}")


def remove_command(handle: str, ip: str, prefix: int,
                   system: str | None = None) -> list[str]:
    """Take back an address added by `add_command`.

    macOS and Windows identify the address on its own; Linux wants the prefix
    back, and `ip addr del` without one deletes whichever prefix it finds
    first — which could be the machine's real address.
    """
    system = system or platform.system()
    ip, prefix = str(ip), int(prefix)
    if system == "Darwin":
        return ["ifconfig", handle, "-alias", ip]
    if system == "Linux":
        return ["ip", "addr", "del", f"{ip}/{prefix}", "dev", handle]
    if system == "Windows":
        return ["netsh", "interface", "ipv4", "delete", "address",
                f"name={handle}", f"address={ip}", "store=active"]
    raise ValueError(f"unsupported system: {system}")
