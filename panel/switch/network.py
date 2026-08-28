#!/usr/bin/env python3
"""The switch's own management address.

Changing this is the one write that guarantees the reply never arrives: the
switch moves to the new address and the socket carrying the request dies with
the old one. That is success, not failure — see `panel.switch.device`.
"""
from __future__ import annotations

import ipaddress

import requests

from .. import i18n
from ..errors import UnreachableError
from .device import PREFIX_TO_MASK

MIN_MTU, MAX_MTU = 576, 9216


def validate_network(address: str, prefix, mtu) -> tuple[str, str, str]:
    """Check an address the operator typed before the switch moves to it.

    A switch that boots onto 127.0.0.1 or a multicast address is a switch that
    has to be recovered with a console cable, so these are refused here rather
    than discovered afterwards.
    """
    try:
        parsed_address = ipaddress.IPv4Address(str(address).strip())
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise ValueError(i18n.t("switch.errorInvalidAddress",
                                address=address)) from exc
    if (parsed_address.is_loopback or parsed_address.is_multicast
            or parsed_address.is_unspecified):
        raise ValueError(i18n.t("switch.errorUnusableAddress",
                                address=str(parsed_address)))
    parsed_prefix = str(prefix).strip()
    if parsed_prefix not in PREFIX_TO_MASK:
        raise ValueError(i18n.t(
            "switch.errorUnsupportedPrefix", prefix=parsed_prefix,
            allowed=", ".join("/" + item for item in PREFIX_TO_MASK)))
    try:
        parsed_mtu = int(str(mtu).strip())
    except ValueError as exc:
        raise ValueError(i18n.t("switch.errorInvalidMtu", mtu=mtu)) from exc
    if not MIN_MTU <= parsed_mtu <= MAX_MTU:
        raise ValueError(i18n.t("switch.errorMtuOutOfRange",
                                minimum=MIN_MTU, maximum=MAX_MTU,
                                mtu=parsed_mtu))
    return str(parsed_address), parsed_prefix, str(parsed_mtu)


def set_network(client, ip: str, address: str, prefix, mtu="1500",
                credentials=None) -> dict:
    """Move the switch to another management address."""
    address, prefix, mtu = validate_network(address, prefix, mtu)
    with client.lock(ip):
        form = {"method": "manual", "addr": address, "netmaskLen": prefix,
                "mtu": mtu}
        try:
            return client.post(ip, "stat/vlanIntfIp?intf=1", form, timeout=5,
                               credentials=credentials)
        except (requests.RequestException, UnreachableError):
            return {"retCode": ["success"],
                    "note": i18n.lazy("switch.noteAddressChanged")}
