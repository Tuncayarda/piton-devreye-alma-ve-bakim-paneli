#!/usr/bin/env python3
"""The run plan and the switch front-panel drawing — no network access."""
from __future__ import annotations

import time

from .. import settings
from ..errors import AuthError
from ..inventory.catalog import find_group, group_matches
from ..inventory.device_map import Inventory
from ..probe import switch as switch_probe
from .addressing import factory_ip
from .ports import format_ports


def resolve_groups(names) -> list[dict]:
    """Turn names that support IP assignment into group definitions.

    This module's working engine is defined for Intercom only. The limit in
    the UI is not enough on its own; a direct API call must not push another
    device type through the Intercom write routine either.
    """
    out, seen = [], set()
    for name in names or []:
        group = find_group(str(name).strip())
        supported = group and "ip" in str(group.get("ops", "")).split()
        if supported and group["name"] not in seen:
            seen.add(group["name"])
            out.append(group)
    return out


def devices_by_port(inventory: Inventory, groups: list[dict],
                    switch_id: str | None = None) -> dict[int, tuple]:
    """Port -> (device, group name). Several groups merge into one map.

    A device can belong to two groups at once (Intercom and All); the port
    key stays unique so rows do not repeat, and the first matching group name
    wins.
    """
    by_port: dict[int, tuple] = {}
    for group in groups:
        for device in inventory.devices:
            if not group_matches(group, device):
                continue
            if switch_id and device.switch_id != switch_id:
                continue
            if not (device.port and str(device.port).isdigit()):
                continue
            by_port.setdefault(int(device.port), (device, group["name"]))
    return by_port


def build_plan(inventory: Inventory, group_names, ports: list[int],
               switch_id: str | None = None) -> dict:
    """The run plan — from DeviceMap only, without touching the network.

    Each row: which port, which device, which group, the factory candidate and
    the IP to write.

    `group_names` is a list (a single name is accepted too): several device
    groups can join one run. Each group has its own assignment script, so the
    run proceeds group by group (see runner.RUNNERS).

    Port numbers are per switch: both switches have a port 11. With
    `switch_id` the plan is built only from that switch's devices; otherwise
    the same port number could point at a device on another switch.
    """
    from .runner import RUNNERS

    if isinstance(group_names, str):
        group_names = [group_names]
    groups = resolve_groups(group_names)
    by_port = devices_by_port(inventory, groups, switch_id)

    rows = []
    for port in ports:
        device, group_name = by_port.get(port, (None, ""))
        rows.append({
            "port": port,
            "deviceId": device.id if device else None,
            "name": device.name if device else "—",
            "type": device.dto()["typeLabel"] if device else "",
            "group": group_name,
            "factoryIp": factory_ip(inventory),
            "targetIp": device.ip if device else "—",
            "actionable": device is not None,
        })
    first = next(iter(by_port.values()), None)
    resolved_switch = switch_id or (
        first[0].switch_id if first
        else (inventory.switches()[0].id if inventory.switches() else None))
    switch = inventory.find(resolved_switch) if resolved_switch else None
    return {
        "switch": switch.name if switch else "",
        "switchIp": switch.ip if switch else "",
        "switchId": resolved_switch,
        "rows": rows,
        "targetCount": sum(1 for row in rows if row["actionable"]),
        "portText": format_ports(ports) or "No port selected",
        "groups": [group["name"] for group in groups],
        # Groups with no script: the UI can say so before starting a run.
        "withoutRunner": [group["name"] for group in groups
                          if group["name"] not in RUNNERS],
    }


def front_panel(inventory: Inventory, switch_id: str,
                credentials=None) -> dict:
    """The switch's port list, for drawing the front panel.

    When the switch cannot be read (no credentials / unreachable) the ports
    are drawn from DeviceMap with empty state — no invented link status.
    """
    switch = inventory.find(switch_id)
    if switch is None:
        return {"ports": [], "source": "none", "note": "Switch not found"}
    defined = {int(device.port): device.name for device in inventory.devices
               if device.switch_id == switch_id and device.port
               and str(device.port).isdigit()}
    try:
        live = {port["pid"]: port
                for port in switch_probe.ports(switch.ip, credentials)}
        source, note = "switch", ""
    except AuthError:
        live, source = {}, "devicemap"
        note = "The switch wants a username/password — port state unreadable"
    except Exception:
        live, source = {}, "devicemap"
        note = "The switch is unreachable — port state unreadable"

    # The panel draws the device's whole face: showing only the ports present
    # in DeviceMap turned the map into a sparse list of numbers with no sense
    # of where anything was. An unexpected port number (from DeviceMap or the
    # switch) is added to the list too.
    poe_count = settings.SWITCH_POE_PORTS
    uplink_count = settings.SWITCH_UPLINK_PORTS
    numbers = sorted(set(range(1, poe_count + uplink_count + 1))
                     | set(defined) | set(live))
    return {
        "switchId": switch.id,
        "switchName": switch.name,
        "switchIp": switch.ip,
        # The run connects to the switch with a username/password. Without one
        # it fails at the first step; the UI can say so up front.
        "hasCredentials": bool(credentials),
        "poeCount": poe_count,
        "uplinkCount": uplink_count,
        "source": source,
        "note": note,
        # When the data was read: the front panel refreshes live, so "how many
        # seconds ago" is computed in the UI from this stamp.
        "readAt": time.time() if source == "switch" else None,
        "ports": [{
            "number": number,
            # PoE or uplink in the physical layout (the panel's right column).
            "poe": number <= poe_count,
            "device": defined.get(number, ""),
            "defined": number in defined,
            "enabled": (live[number]["enabled"] if number in live else None),
            "link": live[number]["link"] if number in live else "",
            # With a live read the power state comes too: it is the only thing
            # separating "powering" from "merely linked".
            "hasPoe": live[number].get("poe") if number in live else None,
            "poeMode": live[number].get("poeMode", "") if number in live else "",
            "watts": live[number].get("watts") if number in live else None,
        } for number in numbers],
    }
