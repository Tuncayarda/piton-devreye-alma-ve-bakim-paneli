#!/usr/bin/env python3
"""Read-only diagnostics: who is on which address, and did the run land right.

"Which device is on which address?" is the most common field question, and
until now it could only be answered with external tools like arp-scan — and
then only at MAC level. But the device announces its own extension (see
`extension_of`) and DeviceMap knows which port that extension belongs to.
Together they produce a sentence like "the device sitting on 10.1.1.13 is
actually port 22's device".

A conflict (two devices on one address) is invisible to a single probe: an
address answers with one device at a time. Several passes are made with an ARP
flush in between so the order changes; DIFFERENT extensions seen on one
address mean more than one device is there.
"""
from __future__ import annotations

import time

from .. import clock, script_loader
from ..inventory.device_map import Inventory
from .addressing import factory_ip, is_ipv4, search_candidates
from .plan import devices_by_port, resolve_groups
from .runner import script_config
from .. import i18n

MAP_PASSES = 3
PASS_INTERVAL = 1.0


def extension_of(device_settings: dict | None) -> str:
    """The extension (SIP number) the device reports for itself.

    An Intercom returns `pbxExtension` in its /api/v1/system/settings reply,
    and that number is unique per device — DeviceMap holds the same field
    (`PBXExtension`). So "who is on this address" can be answered from the
    device itself, with no ARP, no switch credentials and no MAC table. It is
    also what tells two devices on one address apart.
    """
    for key in ("pbxExtension", "pbxextension", "PBXExtension"):
        value = str((device_settings or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def _require_switch(inventory: Inventory, switch_id: str, groups):
    switch = inventory.find(switch_id)
    if switch is None:
        raise ValueError(i18n.t("error.switchNotFound"))
    selected = resolve_groups(groups)
    if not selected:
        raise ValueError(
            i18n.t("error.intercomOnly"))
    return switch, selected


def address_map(inventory: Inventory, switch_id: str, groups,
                options: dict | None = None,
                passes: int = MAP_PASSES) -> dict:
    """Who answers on the candidate addresses — read-only, nothing is written.

    Returns: {"factoryIp", "time", "arpFlush", "rows": [...], "counts"}
    Each row is one ADDRESS:
      {"ip", "isFactory", "expectedPort", "expectedName",
       "found": [{"extension", "port", "name"}], "state"}
    `state`: empty | expected | foreign | conflict | unknown
    """
    from .addressing import can_flush_arp

    module = script_loader.intercom_ip_assign()
    switch, selected = _require_switch(inventory, switch_id, groups)

    options = options or {}
    factory = (str(options.get("factoryIp") or "").strip()
               or factory_ip(inventory))
    by_port = devices_by_port(inventory, selected, switch.id)
    config = script_config(factory, switch.ip)

    address_owner, extension_owner = {}, {}
    for port, (device, _group) in sorted(by_port.items()):
        ip = str(device.ip or "").strip()
        if is_ipv4(ip):
            address_owner.setdefault(ip, (port, device.name))
        if getattr(device, "pbx_extension", None):
            extension_owner[device.pbx_extension] = (port, device.name)

    extra = search_candidates(options.get("searchNetwork"),
                              options.get("searchNetmask"),
                              first=options.get("searchFirst") or "",
                              last=options.get("searchLast") or "")
    candidates = list(dict.fromkeys([factory] + list(address_owner) + extra))

    # Probe pass by pass, accumulating the extensions SEEN on each address.
    seen: dict[str, dict[str, dict]] = {ip: {} for ip in candidates}
    for index in range(max(1, passes)):
        if index:
            module.arp_forget(candidates)
            clock.sleep(PASS_INTERVAL)
        for ip, device_settings in module.probe_all(candidates, config).items():
            extension = extension_of(device_settings)
            port, name = extension_owner.get(extension, (None, ""))
            seen.setdefault(ip, {})[extension or f"?{len(seen[ip])}"] = {
                "extension": extension, "port": port, "name": name}

    rows = []
    for ip in candidates:
        found = sorted(seen.get(ip, {}).values(),
                       key=lambda entry: (entry["port"] is None,
                                          entry["port"] or 0))
        expected_port, expected_name = address_owner.get(ip, (None, ""))
        if not found:
            state = "empty"
        elif len(found) > 1:
            state = "conflict"
        elif ip == factory:
            state = "expected"        # factory address: who it is is moot
        elif found[0]["port"] is None:
            state = "unknown"         # extension not in DeviceMap
        elif found[0]["port"] == expected_port:
            state = "expected"
        else:
            state = "foreign"
        rows.append({
            "ip": ip, "isFactory": ip == factory,
            "expectedPort": expected_port, "expectedName": expected_name,
            "found": found, "state": state,
        })

    counts = {"total": len(rows),
              "devices": sum(len(row["found"]) for row in rows)}
    for state in ("empty", "expected", "foreign", "conflict", "unknown"):
        counts[state] = sum(1 for row in rows if row["state"] == state)
    return {"factoryIp": factory, "time": time.time(),
            "arpFlush": can_flush_arp(), "switchName": switch.name,
            "rows": rows, "counts": counts}


def audit_identities(inventory: Inventory, switch_id: str, ports: list[int],
                     groups, options: dict | None = None,
                     passes: int = 2) -> dict:
    """After a run: is the RIGHT device on each port's target address?

    The run picks a device by guessing at uptime (see `find_device` in the
    script) and never checks WHO it found — which is how the wrong device can
    be written when two share an address. The field result was exactly that:
    three devices ended up on one target address and one device had been
    written to another port's address.

    The script is not modified; the check happens AFTER the run, here: the
    device reports its own extension and DeviceMap knows which port that
    extension belongs to. If the two disagree, the run wrote to the wrong
    device.

    Returns: {"rows": [{"port", "name", "targetIp", "expectedExtension",
              "found": [...], "state"}], "counts"}
    `state`: correct | wrong | conflict | silent | unknown
    """
    module = script_loader.intercom_ip_assign()
    switch, selected = _require_switch(inventory, switch_id, groups)

    options = options or {}
    factory = (str(options.get("factoryIp") or "").strip()
               or factory_ip(inventory))
    config = script_config(factory, switch.ip)
    by_port = devices_by_port(inventory, selected, switch.id)
    targets = [(port, by_port[port][0]) for port in sorted(ports)
               if port in by_port]
    extension_owner = {
        device.pbx_extension: (port, device.name)
        for port, (device, _group) in by_port.items()
        if getattr(device, "pbx_extension", None)}

    addresses = [device.ip for _port, device in targets
                 if is_ipv4(str(device.ip or ""))]
    seen: dict[str, dict[str, dict]] = {}
    for index in range(max(1, passes)):
        if index:
            # A second device on the same address only appears once the entry
            # turns over (see address_map).
            module.arp_forget(addresses)
            clock.sleep(PASS_INTERVAL)
        for ip, device_settings in module.probe_all(addresses, config).items():
            extension = extension_of(device_settings)
            port, name = extension_owner.get(extension, (None, ""))
            seen.setdefault(ip, {})[extension or "?"] = {
                "extension": extension, "port": port, "name": name}

    rows = []
    for port, device in targets:
        found = list(seen.get(str(device.ip or ""), {}).values())
        expected = getattr(device, "pbx_extension", None) or ""
        if not found:
            state = "silent"
        elif len(found) > 1:
            state = "conflict"
        elif not expected or not found[0]["extension"]:
            state = "unknown"
        elif found[0]["extension"] == expected:
            state = "correct"
        else:
            state = "wrong"
        rows.append({
            "port": port, "name": device.name, "targetIp": device.ip,
            "expectedExtension": expected, "found": found, "state": state,
        })

    counts = {"total": len(rows)}
    for state in ("correct", "wrong", "conflict", "silent", "unknown"):
        counts[state] = sum(1 for row in rows if row["state"] == state)
    return {"rows": rows, "counts": counts}
