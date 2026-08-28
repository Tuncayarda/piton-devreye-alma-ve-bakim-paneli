#!/usr/bin/env python3
"""Switch identity, sign-in, and the three operations that end a session.

`reboot`, `factory_reset` and (in `network`) an address change share an
awkward property: the switch carries out the request and then stops being able
to answer it. A dropped connection is the EXPECTED outcome, so it is reported
as success. Treating it as a failure told the operator the reset had not
happened while the switch was already resetting.
"""
from __future__ import annotations

import requests

from .. import credentials as credential_store
from .. import i18n
from ..errors import AuthError, UnreachableError
from .client import looks_like_switch

PREFIX_TO_MASK = {"8": "255.0.0.0", "16": "255.255.0.0",
                  "24": "255.255.255.0"}

# Every switch password this panel holds is filed under one group, so an
# account entered on this screen also unlocks the IP assignment screen's
# reads (see `panel.ip_assign.factory_reset`, which looks it up by this name).
GROUP = "switch"


def get_info(client, ip: str, credentials=None) -> dict:
    """Identity plus the management address the switch answers on.

    The management network is read separately and is allowed to fail: not
    every model serves `vlanIntfIp`, and a missing address is not a reason to
    refuse the identity that did arrive. An AuthError is different and travels.
    """
    info = client.identity(ip, timeout=4, credentials=credentials)
    if info is None:
        raise UnreachableError(i18n.t("switch.errorNotResponding", ip=ip))
    if info.get("locked"):
        raise AuthError(i18n.t("error.probeAuth"))
    try:
        network = client.get(ip, "stat/vlanIntfIp?intf=1",
                             credentials=credentials)
        network = (network.get("vlanIntfIp", network)
                   if isinstance(network, dict) else {})
    except AuthError:
        raise
    except Exception:
        network = {}
    info["network"] = {
        "method": network.get("method", "manual"),
        "address": network.get("addr", ip),
        "prefix": str(network.get("netmaskLen", "")),
        "subnetMask": PREFIX_TO_MASK.get(str(network.get("netmaskLen", "")),
                                         ""),
        "mtu": str(network.get("mtu", "1500")),
    }
    return info


def login(client, ip: str, username: str, password: str, *,
          device_id: str | None = None,
          share_with_group: bool = False) -> dict:
    """Check an account against the switch and remember it if it works.

    THE PASSWORD IS ONLY KEPT ONCE THE SWITCH HAS PROVED WHAT IT IS. An
    address can be taken over by another device between one scan and the next,
    and plenty of things answer HTTP with 200 and accept any Basic Auth header
    without reading it. Storing on "the request did not fail" would file the
    operator's switch password against whatever now holds that address; it is
    stored only after a reply that carries a model, a version or a MAC.

    Nothing is written to disk here — `panel.credentials` is memory only.
    """
    if not username:
        raise AuthError(i18n.t("switch.errorUsernameRequired"))
    info = client.identity(ip, timeout=6, credentials=(username, password))
    if info is None:
        raise UnreachableError(i18n.t("switch.errorNotResponding", ip=ip))
    if info.get("locked"):
        raise AuthError(i18n.t("switch.errorWrongCredentials"))
    if not looks_like_switch(info):
        raise UnreachableError(i18n.t("switch.errorNotASwitch", ip=ip))
    credential_store.remember(device_id or ip, ip, username, password,
                              group=GROUP, share_with_group=share_with_group)
    return info


def save_configuration(client, ip: str, credentials=None) -> dict:
    """Write the running configuration to flash.

    Nothing above survives a power cut without this, and the switch takes its
    time over it — hence the longer timeout.
    """
    return client.post(ip, "stat/configSave", {"postOperation": "configSave"},
                       timeout=15, credentials=credentials)


def reboot(client, ip: str, credentials=None) -> dict:
    with client.lock(ip):
        try:
            return client.post(ip, "stat/reboot", {"postOperation": "reboot"},
                               timeout=5, credentials=credentials)
        except (requests.RequestException, UnreachableError):
            # See the note at the top of this file.
            return {"retCode": ["success"],
                    "note": i18n.lazy("switch.noteRebooting")}


def factory_reset(client, ip: str, credentials=None) -> dict:
    with client.lock(ip):
        try:
            return client.post(ip, "stat/reset", {"postOperation": "reset"},
                               timeout=10, credentials=credentials)
        except (requests.RequestException, UnreachableError):
            return {"retCode": ["success"],
                    "note": i18n.lazy("switch.noteResetting")}
