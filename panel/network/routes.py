#!/usr/bin/env python3
"""Routes left pointing at an address the machine no longer has.

The failure this module reports, seen on a field machine:

    Destination     Gateway    RT_IFA       Flags   Netif
    10.1.1/24       link#19    10.1.1.225   UCS     en6

`RT_IFA` is the route's SOURCE address. 10.1.1.225 was an alias the panel had
added and then taken back; the interface still held its own 10.1.1.223, so the
subnet route survived the removal — still bound to the address that was gone.
From that moment the kernel could not pick a source for anything in the /24
and every connect() failed at once with EADDRNOTAVAIL, "Can't assign requested
address". A full scan reported all forty-two devices unreachable in a few
milliseconds, without a single packet leaving the machine.

`aliases.alias_prefix` stops the panel from creating that state. This is the
other half: SEEING it. The state outlives the process that caused it, it can
be reached by other means (any tool that removes an address), and from the
inside it is indistinguishable from dead hardware — which is what made it cost
an afternoon. One line in the queue is worth that.

Reads only. Repairing a route means privileged surgery on the machine's
routing table and is deliberately not done here; the note says what to do.
"""
from __future__ import annotations

import ipaddress
import platform

from ..system import interfaces

# BSD `netstat` alone prints the RT_IFA column, so this check is macOS-only.
# On Linux and Windows an address removal takes its routes with it.
SUPPORTED_SYSTEMS = ("Darwin",)


def supported(system: str | None = None) -> bool:
    return (system or platform.system()) in SUPPORTED_SYSTEMS


def _network_of(destination: str):
    """'10.1.1/24' -> 10.1.1.0/24. netstat abbreviates trailing zero octets."""
    text = str(destination or "").strip()
    if "/" not in text:
        return None
    address, _, prefix = text.partition("/")
    parts = address.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    address = ".".join(parts + ["0"] * (4 - len(parts)))
    try:
        return ipaddress.ip_network(f"{address}/{prefix}", strict=False)
    except ValueError:
        return None


def sources(table: str) -> list[dict]:
    """(network, source address, interface) for every unicast network route.

    Column positions come from the header, not from counting backwards: the
    Expire field is empty on most rows, so the last word is sometimes the
    interface and sometimes an expiry.

    Host routes are left out. The kernel clones them from the network route
    and they go when it goes, so listing them would turn one fault into two
    hundred rows saying the same thing. Multicast is left out for the same
    reason — it is stranded as a consequence, never as the cause.
    """
    found: list[dict] = []
    source_at = interface_at = -1
    for line in (table or "").splitlines():
        fields = line.split()
        if not fields:
            continue
        if "RT_IFA" in fields and "Netif" in fields:
            source_at = fields.index("RT_IFA")
            interface_at = fields.index("Netif")
            continue
        if source_at < 0 or len(fields) <= interface_at:
            continue
        network = _network_of(fields[0])
        if (network is None or network.prefixlen >= 32
                or network.is_multicast):
            continue
        try:
            source = str(ipaddress.ip_address(fields[source_at]))
        except ValueError:
            continue
        found.append({"network": str(network), "source": source,
                      "interface": fields[interface_at]})
    return found


def stranded(table: str, live) -> list[dict]:
    """The routes whose source address is not on this machine any more."""
    held = {str(address) for address in live}
    seen: set[tuple[str, str]] = set()
    out = []
    for entry in sources(table):
        key = (entry["network"], entry["source"])
        if entry["source"] in held or key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _table() -> str:
    code, output = interfaces.run_command(["netstat", "-rnl", "-f", "inet"],
                                          timeout=10.0)
    return output if code == 0 else ""


def broken_networks(system: str | None = None) -> list[dict]:
    """Networks this computer cannot send into, and the address to blame."""
    if not supported(system):
        return []
    from . import adapters as adapter_module

    live = [address
            for adapter in adapter_module.list_adapters()
            for address, _prefix in adapter.addresses]
    return stranded(_table(), live)
