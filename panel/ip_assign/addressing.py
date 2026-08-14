#!/usr/bin/env python3
"""Candidate addresses, the factory address, and ARP permission."""
from __future__ import annotations

import ipaddress
import time

from .. import script_loader, settings
from ..inventory.device_map import Inventory
from .. import i18n

# Upper bound on the candidate address list. The field netmask can be /16
# (255.255.0.0), which would mean 65k addresses scanned end to end for every
# port — the run would never finish. On a wide netmask the way to narrow the
# search is an explicit address range, not network + mask (see
# `range_candidates`).
SEARCH_LIMIT = 512


# Permission to flush the ARP cache is what lets a run finish in one pass
# (see intercom_ip_assign.arp_forget). The app is launched elevated, so the
# expected answer is yes; it is still measured rather than assumed. The query
# spawns a subprocess, so it is not repeated on every plan request.
_ARP_PERMISSION = {"checked_at": 0.0, "value": False}


def can_flush_arp(ttl: float = 10.0) -> bool:
    now = time.time()
    if now - _ARP_PERMISSION["checked_at"] > ttl:
        try:
            value = bool(script_loader.intercom_ip_assign().can_flush_arp())
        except Exception:
            value = False
        _ARP_PERMISSION.update(checked_at=now, value=value)
    return _ARP_PERMISSION["value"]


def is_ipv4(value) -> bool:
    try:
        return ipaddress.ip_address(str(value).strip()).version == 4
    except ValueError:
        return False


def factory_ip(inventory: Inventory | None = None) -> str:
    """The address unconfigured devices are expected on.

    Fixed (10.1.1.12) — NOT resolved per train set. A device leaves the
    factory without knowing which set it joins, so they all arrive the same.
    `inventory` stays only to keep call sites unchanged.
    """
    return settings.FACTORY_IP


def range_candidates(first: str, last: str,
                     limit: int = SEARCH_LIMIT) -> list[str]:
    """'10.1.1.10' + '10.1.1.60' → every address in between.

    The answer to network + mask being useless: with a /8 project mask that
    network is 16 million addresses, while the devices sit in a known narrow
    range. The user writes that range directly.
    """
    first, last = str(first or "").strip(), str(last or "").strip()
    if not (first and last):
        raise ValueError(
            i18n.t("error.searchRangeBothEnds"))
    try:
        start = ipaddress.IPv4Address(first)
        end = ipaddress.IPv4Address(last)
    except ValueError as exc:
        raise ValueError(
            i18n.t("error.searchRangeUnparsed", detail=exc)) from exc
    if int(end) < int(start):
        raise ValueError(i18n.t("error.searchRangeBackwards"))
    count = int(end) - int(start) + 1
    if count > limit:
        raise ValueError(
            i18n.t("error.searchRangeTooWide", count=count, limit=limit))
    return [str(ipaddress.IPv4Address(value))
            for value in range(int(start), int(end) + 1)]


def search_candidates(network: str, netmask: str, limit: int = SEARCH_LIMIT,
                      first: str = "", last: str = "") -> list[str]:
    """'10.1.1.0' + '255.255.255.0' → ['10.1.1.1', …, '10.1.1.254'].

    Addresses to scan for devices that are not on the factory address. A
    prefix length ("24") works in place of a mask.

    When first/last are given, that range replaces network + mask (see
    `range_candidates`) — on wide-netmask setups it is the only way to narrow
    the search.
    """
    network = str(network or "").strip()
    netmask = str(netmask or "").strip()
    if str(first or "").strip() or str(last or "").strip():
        return range_candidates(first, last, limit)
    if not network:
        return []
    try:
        net = ipaddress.ip_network(f"{network}/{netmask or '32'}",
                                   strict=False)
    except ValueError as exc:
        raise ValueError(
            i18n.t("error.searchNetworkUnparsed", detail=exc)) from exc
    if net.version != 4:
        raise ValueError(i18n.t("error.searchNetworkNotIpv4"))
    addresses = [str(host) for host in net.hosts()] or [str(net.network_address)]
    if len(addresses) > limit:
        raise ValueError(
            i18n.t("error.searchNetworkTooWide", count=len(addresses),
                   limit=limit))
    return addresses
