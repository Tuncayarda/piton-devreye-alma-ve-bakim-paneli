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

# The prefix length written together with a newly assigned address. Every
# address in the project plan is a /24 and that stays the default, but it is
# NOT a constant of the system: a Compartment LCD is sometimes commissioned on
# a /8 so it can be reached from the whole 10.0.0.0 range while the rest of
# the train is still being addressed. So the run takes it as an option.
#
# The bounds are the range in which "assign this address to a device on a
# switch port" still means something: below /8 the mask stops describing a
# network anybody routes here, and above /30 there is no host address left
# beside the device's own.
DEFAULT_TARGET_PREFIX = 24
MIN_TARGET_PREFIX = 8
MAX_TARGET_PREFIX = 30


def effective_prefix(requested=None) -> int:
    """The mask a run writes: the operator's, then the project's, then /24.

    ONE ANSWER, in one place. The plan the screen draws, the run that writes
    and the address the device-settings screen sends all have to agree; three
    of them working it out separately is how a screen comes to promise a /24
    and a run to write a /16.

    See `panel.editions.catalogue.Project.prefix` for why a project states
    one at all.
    """
    from ..editions import runtime as editions              # noqa: PLC0415
    return (int(requested or 0) or editions.prefix()
            or DEFAULT_TARGET_PREFIX)


def netmask_for(prefix: int) -> str:
    """24 -> '255.255.255.0'. The dotted form the HTTP devices want."""
    return str(ipaddress.IPv4Network(("0.0.0.0", int(prefix))).netmask)


def parse_prefix(value, default: int = DEFAULT_TARGET_PREFIX) -> int:
    """'24', '/24' and '255.255.255.0' all mean 24; empty means `default`.

    Both spellings appear in the field: the switch pages and the device web
    UIs write a dotted mask, while everyone says "slash eight" out loud. A
    mask with holes in it (255.0.255.0) is rejected rather than rounded to
    something plausible.
    """
    text = str(value or "").strip().lstrip("/")
    if not text:
        return int(default)
    if text.isdigit():
        prefix = int(text)
    else:
        try:
            prefix = ipaddress.IPv4Network(f"0.0.0.0/{text}").prefixlen
        except ValueError as exc:
            raise ValueError(i18n.t("error.targetMaskInvalid")) from exc
    if not MIN_TARGET_PREFIX <= prefix <= MAX_TARGET_PREFIX:
        raise ValueError(i18n.t("error.targetMaskOutOfRange",
                                low=MIN_TARGET_PREFIX,
                                high=MAX_TARGET_PREFIX))
    return prefix


def parse_set(value, default: int = 0) -> int:
    """The set a device is CURRENTLY on, for a transfer. 0 = not given.

    Deliberately strict: silently reading a mistyped set number as 1 would
    send the run looking on the factory network while the devices sit in set
    3, and report every port as "device not found".
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return int(default)
    try:
        number = int(text)
    except ValueError as exc:
        raise ValueError(i18n.t("error.sourceSetInvalid")) from exc
    if not 1 <= number <= 254:
        raise ValueError(i18n.t("error.sourceSetInvalid"))
    return number


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
    # COUNT BEFORE BUILDING, the way `range_candidates` above does. Asking
    # `net.hosts()` first means a /8 typed by mistake materialises 16.7
    # million strings — eighteen seconds and a gigabyte — only to be thrown
    # away by the very next line. The count is the same either way:
    # `hosts()` drops the network and broadcast addresses below /31, and
    # yields the single address at /31 and /32 (which is why the list below
    # falls back to the network address rather than staying empty).
    usable = net.num_addresses - (2 if net.prefixlen < 31 else 0)
    if usable > limit:
        raise ValueError(
            i18n.t("error.searchNetworkTooWide", count=usable, limit=limit))
    return [str(host) for host in net.hosts()] or [str(net.network_address)]
