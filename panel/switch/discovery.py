#!/usr/bin/env python3
"""Which addresses a discovery scan will try, and the cheap TCP knock.

Split from the client because it answers a question that needs no network at
all: "10.1.1" and "10.1.1.0/24" and "10.1.1.5" are three ways of saying where
to look, and turning them into a list of addresses is arithmetic. The client
does the talking.

The ceiling is deliberate. A /16 is 65534 addresses; at the probe timeout
below that is a scan nobody waits for, so it is refused with a sentence that
says how many rather than started and silently abandoned.
"""
from __future__ import annotations

import ipaddress
import re
import socket

from .. import i18n

DEFAULT_DISCOVERY_CIDR = "10.1.1.0-255/24"
# The prefix a range is read against when it carries none.
DEFAULT_PREFIX = 24
TCP_PROBE_TIMEOUT = 1.2
MAX_DISCOVERY_ADDRESSES = 1024
# Below this many addresses a TCP sweep that finds nothing is not proof that
# nothing is there — a switch may refuse the knock and still serve HTTP. Above
# it, asking every address over HTTP costs more than the answer is worth.
HTTP_FALLBACK_LIMIT = 256


# `10.1.1.20-40` — the last octet given as a range. The screen sends this
# shape because that is how the operator says it: the switches are on .100 to
# .110, not on a whole /24, and sweeping the other 244 addresses is time paid
# for nothing.
_RANGE = re.compile(r"^(\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d{1,3})-(\d{1,3})$")


def _range_addresses(body: str) -> list[str] | None:
    """The addresses of `A.B.C.x-y`, or None when that is not the shape."""
    match = _RANGE.match(body)
    if not match:
        return None
    head, first, last = match.group(1), int(match.group(2)), int(match.group(3))
    if first > last:
        first, last = last, first
    try:
        # Each end parsed as a real address, so 10.1.1.300-400 is refused
        # here rather than producing addresses that cannot exist.
        ipaddress.IPv4Address(f"{head}.{first}")
        ipaddress.IPv4Address(f"{head}.{last}")
    except ipaddress.AddressValueError as exc:
        raise ValueError(i18n.t("switch.errorInvalidAddress",
                                address=body)) from exc
    count = last - first + 1
    if count > MAX_DISCOVERY_ADDRESSES:
        raise ValueError(i18n.t("switch.errorNetworkTooLarge", network=body,
                                count=count,
                                maximum=MAX_DISCOVERY_ADDRESSES))
    return [f"{head}.{octet}" for octet in range(first, last + 1)]


def target_network(expression: str):
    """The network `expression` sits in, for the address the panel may add.

    Answers a different question from `resolve_addresses`: not "which
    addresses do I knock on" but "which network does the computer need to be
    on to reach them at all". A sweep of 10.1.1.0-255 from a machine sitting
    on 10.17.1.222 finds nothing, and not because the switches are absent —
    nothing ever left the network card (see `panel.network`).

    Returns None when the expression names no network this can work out.
    """
    raw = (expression or "").strip()
    if not raw:
        return None
    body, _, prefix_text = raw.partition("/")
    try:
        prefix = int(prefix_text) if prefix_text else DEFAULT_PREFIX
    except ValueError:
        return None
    match = _RANGE.match(body)
    head = f"{match.group(1)}.{match.group(2)}" if match else body.rstrip(".")
    if head.count(".") == 2:
        head = f"{head}.0"
    try:
        return ipaddress.IPv4Network(f"{head}/{prefix}", strict=False)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError,
            ValueError):
        return None


def resolve_addresses(expression: str) -> tuple[list[str], bool]:
    """Turn an address, a range, a network or a three-octet prefix into hosts.

    Returns the addresses and whether the expression named exactly one, which
    the caller uses to pick a longer timeout: one address is worth waiting on.
    """
    raw = (expression or "").strip()
    if not raw:
        raise ValueError(i18n.t("switch.errorAddressRequired"))

    # A range carries its own bounds, so the prefix beside it says only which
    # network the addresses belong to — it does not widen the sweep.
    body, _, _prefix = raw.partition("/")
    ranged = _range_addresses(body.strip())
    if ranged is not None:
        return ranged, len(ranged) == 1

    if "/" not in raw:
        body = raw.rstrip(".")
        parts = body.split(".")
        if len(parts) == 4 and not raw.endswith("."):
            try:
                single = ipaddress.IPv4Address(body)
            except ipaddress.AddressValueError as exc:
                raise ValueError(i18n.t("switch.errorInvalidAddress",
                                        address=raw)) from exc
            return [str(single)], True
        if len(parts) == 3:
            raw = f"{body}.0/24"
        else:
            raise ValueError(i18n.t("switch.errorUnrecognizedAddress",
                                    address=expression))

    try:
        network = ipaddress.IPv4Network(raw, strict=False)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError,
            ValueError) as exc:
        raise ValueError(i18n.t("switch.errorInvalidNetwork",
                                network=expression)) from exc

    # THE SIZE IS CHECKED BEFORE THE LIST IS BUILT. `hosts()` is a generator,
    # but expanding it first and measuring afterwards meant a typed-in /8 sat
    # there building 16.7 million strings — sixteen seconds and hundreds of
    # megabytes — only to be refused. `num_addresses` is arithmetic.
    if network.num_addresses > MAX_DISCOVERY_ADDRESSES + 2:
        raise ValueError(i18n.t("switch.errorNetworkTooLarge",
                                network=str(network),
                                count=network.num_addresses,
                                maximum=MAX_DISCOVERY_ADDRESSES))
    addresses = [str(address) for address in network.hosts()]
    if not addresses:
        # A /32 has no hosts; the address itself is what was meant.
        addresses = [str(network.network_address)]
    if len(addresses) > MAX_DISCOVERY_ADDRESSES:
        raise ValueError(i18n.t("switch.errorNetworkTooLarge",
                                network=str(network), count=len(addresses),
                                maximum=MAX_DISCOVERY_ADDRESSES))
    return addresses, len(addresses) == 1


def tcp_open(ip: str, port: int, timeout: float = 0.4) -> bool:
    """Is anything listening? No request is sent and no reply is read."""
    try:
        with socket.create_connection((ip, port), timeout):
            return True
    except OSError:
        return False
