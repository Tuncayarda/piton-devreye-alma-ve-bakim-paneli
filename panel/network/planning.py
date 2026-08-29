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
    # The /24 the address that made this necessary lives in. Only interesting
    # when `network` is WIDER than that — see `choose_host`, which puts the
    # panel's own address here rather than at the base of the wide network.
    anchor: ipaddress.IPv4Network | None = None

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
                      known: list | None = None,
                      broker: str = "") -> list[Requirement]:
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
        # The /24 this address is actually in, kept beside the (possibly
        # wider) network so the panel's own address can be placed next to the
        # devices rather than at the base of the range (see `choose_host`).
        wanted.append(Requirement(network, reason, str(address),
                                  anchor=network_of(address, 24)))

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

    # The broker, which is a ROLE and not a device, so nothing above finds
    # it. On most projects it is the PISCU and already inside a device
    # network, and this line changes nothing; on Gaziray it sits on a network
    # of its own (10.n.0.1, while the cars are 10.n.1-4.x) and asking for it
    # is the difference between the panel reaching MQTT and not. Stated
    # rather than left to a wide enough prefix covering it by accident.
    want(broker or "", "net.reasonBroker")

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
                limit: int = HOST_OCTET_LIMIT,
                anchor: ipaddress.IPv4Network | None = None) -> str:
    """The address the panel gives itself inside `network`.

    Starts at `octet` (225 by default) and walks up. Rejected: anything in
    `taken` (DeviceMap addresses, the factory address, addresses the computer
    already holds) and the network and broadcast addresses.

    `anchor` IS WHERE THE DEVICES ARE, and it matters as soon as a project
    widens its network. GDM's 125 devices sit in 192.168.201.0/24 but the
    project runs a /16, and counting from the base of that /16 gives the
    panel 192.168.0.225 — an address a camera on a /24 cannot answer, because
    replying to it means leaving its own subnet through a gateway it has no
    reason to have. Counted from the anchor instead, the panel takes
    192.168.201.225 and keeps the /16: it reaches the whole range, and every
    device can still reply to it directly.

    Without an anchor, or with one the network does not contain, this is the
    plain walk it always was — which is what a project stating no prefix
    gets, since there the anchor and the network are the same /24.

    KNOWN LIMIT: this checks what is WRITTEN DOWN, not what is on the wire.
    A third-party host squatting on the chosen address cannot be detected
    before the address is assigned — probing an address needs a route to it,
    and having the route is what is being set up. A collision therefore shows
    up as the run failing to reach devices, not as an error here.
    """
    # The band to count from; the MASK still comes from `network`.
    start = network
    if anchor is not None and anchor.subnet_of(network):
        start = anchor

    def is_host(address) -> bool:
        # `hosts()` is not materialised: on a wide prefix that is 65 000
        # strings built to answer one question.
        return (address in start
                and address != start.network_address
                and address != start.broadcast_address
                and address != network.network_address
                and address != network.broadcast_address)

    for value in range(int(octet), int(limit) + 1):
        candidate = start.network_address + value
        if is_host(candidate) and str(candidate) not in taken:
            return str(candidate)
    # The preferred band is full; fall back to any free host address rather
    # than giving up on the run. Still inside the anchor when there is one:
    # an address the devices cannot answer is not a useful fallback.
    for host in start.hosts():
        if str(host) not in taken:
            return str(host)
    raise ValueError(i18n.t("error.networkNoFreeAddress",
                            network=str(network)))
