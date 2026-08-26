#!/usr/bin/env python3
"""Which networks the computer has to be in, and on which address.

This is the module that answers the failure this feature exists for. In the
field:

    computer            10.17.1.222/24
    switches            10.17.1.100, 10.17.1.101
    intercoms (factory) 10.1.1.12

The switches are read without trouble — they are inside the computer's own
/24. The devices are not: an unconfigured intercom answers on 10.1.1.12, and
the computer has no address anywhere near it, so every probe fails before a
packet leaves the machine. The run reported "device not found" on every port
and the address had to be added by hand in system settings.

`required_networks` is that diagnosis as code: collect every network the run
will actually talk to, drop the ones the computer is already in, and what is
left has to be added.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .. import i18n, settings
from ..inventory.device_map import Inventory
from . import adapters as adapter_module

# The default last octet of the address the panel gives itself. High enough to
# sit above the device addresses in DeviceMap (which run from .1 to roughly
# .60) and above the switches (.100, .101), so the obvious choice does not
# collide with the project's own plan.
DEFAULT_HOST_OCTET = 225
# How far to walk up when that octet is taken. Small on purpose: past this the
# answer is "something is wrong with the assumption", not "try harder".
HOST_OCTET_LIMIT = 240
# The prefix of the address the panel adds. /24 rather than the /16 the
# devices themselves use: our own alias only has to reach the devices' /24,
# and the narrower it is the less of the routing table it claims.
DEFAULT_PREFIX = 24


@dataclass
class Requirement:
    """One network the run needs, and why."""

    network: ipaddress.IPv4Network
    reason: str          # a message key, rendered where the language is known
    target: str = ""     # the address that made it necessary

    def dto(self) -> dict:
        return {"network": str(self.network),
                "reason": i18n.t(self.reason),
                "reasonKey": self.reason,
                "target": self.target}


def network_of(address: str, prefix: int = DEFAULT_PREFIX):
    """'10.1.1.12' -> 10.1.1.0/24. None when the address is not IPv4."""
    try:
        return ipaddress.ip_network(f"{str(address).strip()}/{int(prefix)}",
                                    strict=False)
    except ValueError:
        return None


def required_networks(inventory: Inventory, factory_ip: str = "",
                      extra=(), prefix: int = DEFAULT_PREFIX,
                      known: list | None = None) -> list[Requirement]:
    """The networks a run needs but the computer is not in.

    `known` is the computer's current networks (see
    `adapters.local_networks`); passing it avoids a second OS call and lets
    the tests state the starting position directly.

    A network is dropped when an address the computer already has falls inside
    it — that is what "the computer can reach it" means. The comparison is by
    membership, not equality: a machine sitting on 10.1.0.0/16 already reaches
    10.1.1.0/24 and needs nothing added.
    """
    known = list(adapter_module.local_networks(adapter_module.list_adapters())
                 if known is None else known)

    wanted: list[Requirement] = []

    def want(address: str, reason: str):
        network = network_of(address, prefix)
        if network is None:
            return
        if any(network.subnet_of(existing) or network == existing
               for existing in known if existing.version == 4):
            return
        if any(entry.network == network for entry in wanted):
            return
        wanted.append(Requirement(network, reason, str(address)))

    # The factory address. This is the one that broke in the field: devices
    # leave the factory on 10.1.1.12 whatever set they end up in, so it is
    # almost never inside the project's own network.
    want(str(factory_ip or "").strip() or settings.FACTORY_IP,
         "net.reasonFactory")

    # The set's own network — switches and configured devices. Needed when the
    # computer is on a foreign network altogether (DHCP in the depot office,
    # say), which is the other half of the same problem.
    for switch in inventory.switches():
        want(switch.ip, "net.reasonSwitch")
    for device in inventory.devices:
        if device.type != "Switch" and device.ip:
            want(device.ip, "net.reasonDevices")

    # Anything the caller is going to scan on top: the search range on the IP
    # screen can point anywhere.
    for address in extra:
        want(str(address or "").strip(), "net.reasonSearch")

    return wanted


def occupied(inventory: Inventory, factory_ip: str = "") -> set[str]:
    """Addresses the panel must not take for itself.

    Everything DeviceMap plans for this set, plus the factory address. Taking
    one of these would put the computer on the address it is about to look
    for — the device would then be invisible and the cause invisible with it.
    """
    taken = {device.ip for device in inventory.devices if device.ip}
    taken.add(str(factory_ip or "").strip() or settings.FACTORY_IP)
    return {address for address in taken if address}


def choose_host(network: ipaddress.IPv4Network, taken: set[str],
                octet: int = DEFAULT_HOST_OCTET,
                limit: int = HOST_OCTET_LIMIT) -> str:
    """The address the panel gives itself inside `network`.

    Starts at `octet` (225 by default) and walks up. Rejected: anything in
    `taken` (DeviceMap addresses, the factory address, addresses the computer
    already holds) and the network and broadcast addresses.

    KNOWN LIMIT: this checks what is WRITTEN DOWN, not what is on the wire.
    A third-party host squatting on the chosen address cannot be detected
    before the address is assigned — probing an address needs a route to it,
    and having the route is what is being set up. A collision therefore shows
    up as the run failing to reach devices, not as an error here.
    """
    def is_host(address) -> bool:
        # `hosts()` is not materialised: on a wide prefix that is 65 000
        # strings built to answer one question.
        return (address in network
                and address != network.network_address
                and address != network.broadcast_address)

    for value in range(int(octet), int(limit) + 1):
        candidate = network.network_address + value
        if is_host(candidate) and str(candidate) not in taken:
            return str(candidate)
    # The preferred band is full; fall back to any free host address rather
    # than giving up on the run.
    for host in network.hosts():
        if str(host) not in taken:
            return str(host)
    raise ValueError(i18n.t("error.networkNoFreeAddress",
                            network=str(network)))
