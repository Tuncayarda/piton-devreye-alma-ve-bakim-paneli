#!/usr/bin/env python3
"""The run plan and the switch front-panel drawing — no network access."""
from __future__ import annotations

import time

from .. import i18n, settings
from ..errors import AuthError
from ..inventory.catalog import find_group, group_in, group_matches
from ..inventory.device_map import Inventory, resolve_template
from ..probe import switch as switch_probe
from .addressing import effective_prefix, factory_ip, netmask_for
from .ports import format_ports

_COMPARTMENT_LCD = "Compartment LCD"


def resolve_groups(names, inventory: Inventory | None = None) -> list[dict]:
    """Turn names that support IP assignment into group definitions.

    The limit in the UI is not enough on its own; a direct API call must not
    push a device type without a commissioning flow through a write routine.

    WITH AN INVENTORY the name also has to be a group THIS project has. The
    write paths all pass one — a run that cuts switch ports and rewrites
    addresses is the last place to accept a device type from another
    customer's train. Without one the answer is about the vocabulary only,
    which is what `groups_without_runner` asks (see runner.py).
    """
    out, seen = [], set()
    for name in names or []:
        group = (group_in(inventory, str(name).strip()) if inventory is not None
                 else find_group(str(name).strip()))
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


def device_switch_for(inventory: Inventory, groups,
                      execution_switch_id: str | None) -> str | None:
    """Return the DeviceMap switch whose port map supplies the run rows.

    ``execution_switch_id`` is always the physical switch whose PoE and MAC
    table will be used.  Normally it is also where DeviceMap says the devices
    live.  Compartment LCD commissioning deliberately permits a bench/field
    override, though: the LCD definitions may all be under ``sw1`` while the
    operator has plugged that same port layout into ``sw2``.

    The override is intentionally narrow and deterministic:

    * it applies only to an LCD-only run;
    * a map already defined on the selected switch always wins;
    * otherwise exactly one DeviceMap switch must contain LCD definitions.

    With zero or several possible source switches we keep the selected switch
    as the source too.  That yields no invented/ambiguous rows, and the API's
    allowed-port validation rejects a write before it is queued.
    """
    requested = [groups] if isinstance(groups, str) else (groups or [])
    selected = (requested if requested and isinstance(requested[0], dict)
                else resolve_groups(requested, inventory))
    names = [group["name"] for group in selected]
    if names != [_COMPARTMENT_LCD] or not execution_switch_id:
        return execution_switch_id

    matching = [device for device in inventory.devices
                if group_matches(selected[0], device)
                and device.port and str(device.port).isdigit()]
    if any(device.switch_id == execution_switch_id for device in matching):
        return execution_switch_id
    sources = list(dict.fromkeys(device.switch_id for device in matching))
    return sources[0] if len(sources) == 1 else execution_switch_id


def build_plan(inventory: Inventory, group_names, ports: list[int],
               switch_id: str | None = None,
               device_switch_id: str | None = None, *,
               target_prefix: int = 0,
               source_set: int = 0, target_set: int = 0) -> dict:
    """The run plan — from DeviceMap only, without touching the network.

    Each row: which port, which device, which group, the factory candidate and
    the IP to write.

    `group_names` is a list (a single name is accepted too): several device
    groups can join one run. Each group has its own assignment script, so the
    run proceeds group by group (see runner.RUNNERS).

    Port numbers are per switch: both switches have a port 11.  ``switch_id``
    is the physical execution switch.  Normally its own DeviceMap rows supply
    the plan; the explicit LCD-only override can instead use the single
    canonical LCD layout returned by :func:`device_switch_for`.

    `source_set` is where the devices ARE at the moment, when that is not
    where the run would normally look. Zero means the usual starting point:
    the shared factory address for an Intercom, the set-1 form of each
    display's own template for a Compartment LCD. Giving a number instead
    turns the run into a set transfer — set 3's addresses become the sources
    and the open set stays the destination.

    `target_set` is the other end of the same idea: zero means the open set,
    a number means the addresses are written for that set instead. A factory
    reset is exactly `target_set=1`.

    `target_prefix` is the mask written with the new address; 0 means "the
    project's, or the system default" (see `addressing.effective_prefix`).
    """
    from .runner import RUNNERS

    # Resolved once, at the top: every row below and the summary at the
    # bottom quote this number, and the run itself resolves it the same way.
    target_prefix = effective_prefix(target_prefix)
    if isinstance(group_names, str):
        group_names = [group_names]
    groups = resolve_groups(group_names, inventory)
    resolved_device_switch = (device_switch_id
                              or device_switch_for(inventory, groups,
                                                   switch_id))
    by_port = devices_by_port(inventory, groups, resolved_device_switch)
    lcd_physical_mode = [group["name"] for group in groups] == [
        _COMPARTMENT_LCD]

    def device_row(port, device, group_name, *, actionable=True):
        # Intercoms share one factory address.  Compartment LCDs instead
        # arrive in a factory train layout: the set-1 form of each device's
        # own DeviceMap template (10.1.1.40, .41, ...).
        #
        # A transfer overrides both: the device is not at any starting point,
        # it is on the set it is being moved out of.
        if not device:
            source_ip = ""
        elif source_set:
            source_ip = resolve_template(device.ip_template, source_set)
        elif group_name == _COMPARTMENT_LCD:
            source_ip = resolve_template(device.ip_template, 1)
        else:
            source_ip = factory_ip(inventory)
        return {
            "port": port,
            "deviceId": device.id if device else None,
            "deviceSwitchId": device.switch_id if device else None,
            "name": (device.name if device else
                     _COMPARTMENT_LCD if lcd_physical_mode else "—"),
            "type": device.dto()["typeLabel"] if device else "",
            "group": group_name,
            "sourceIp": source_ip,
            "factoryIp": source_ip,
            "targetIp": ("" if not device else
                         resolve_template(device.ip_template, target_set)
                         if target_set else device.ip),
            "targetPrefix": int(target_prefix),
            "actionable": actionable,
            # In physical-port mode the actual DeviceMap identity is learned
            # only after this port is isolated and MAC->port is proven.
            "identityMode": ("discover" if lcd_physical_mode and not device
                             else "mapped"),
        }

    # These are the only identities and addresses the LCD runner is allowed
    # to discover.  They remain separate from the physical test ports: a
    # display may be plugged into port 8 even though DeviceMap stores its
    # normal train position as port 13.  No candidate comes from the client.
    candidate_rows = ([
        device_row(port, device, group_name)
        for port, (device, group_name) in sorted(by_port.items())
    ] if lcd_physical_mode else [])

    rows = []
    for port in ports:
        if lcd_physical_mode:
            # A physical port deliberately carries no pre-selected identity.
            # The Android address plus the switch MAC table resolve it during
            # the run.  This prevents a moved cable from writing port 8's
            # first candidate address to whichever display happens to answer.
            rows.append(device_row(port, None, _COMPARTMENT_LCD))
        else:
            device, group_name = by_port.get(port, (None, ""))
            rows.append(device_row(port, device, group_name,
                                   actionable=device is not None))
    first = next(iter(by_port.values()), None)
    resolved_switch = switch_id or (
        first[0].switch_id if first
        else (inventory.switches()[0].id if inventory.switches() else None))
    switch = inventory.find(resolved_switch) if resolved_switch else None
    return {
        "switch": switch.name if switch else "",
        "switchIp": switch.ip if switch else "",
        "switchId": resolved_switch,
        "deviceSwitchId": resolved_device_switch,
        "switchOverride": bool(resolved_switch and resolved_device_switch
                               and resolved_switch != resolved_device_switch),
        "physicalPortMode": lcd_physical_mode,
        "candidateRows": candidate_rows,
        "rows": rows,
        "targetCount": sum(1 for row in rows if row["actionable"]),
        "portText": format_ports(ports) or i18n.t("ip.noPortSelected"),
        "groups": [group["name"] for group in groups],
        "targetPrefix": int(target_prefix),
        "targetNetmask": netmask_for(target_prefix),
        # Zero means "the usual starting point"; a number means the run is a
        # transfer out of that set, or into it.
        "sourceSet": int(source_set),
        "targetSet": int(target_set) or int(inventory.set_no),
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
        return {"ports": [], "source": "none",
                "note": i18n.t("ip.switchNotFound")}
    defined = {int(device.port): device.name for device in inventory.devices
               if device.switch_id == switch_id and device.port
               and str(device.port).isdigit()}
    try:
        live = {port["pid"]: port
                for port in switch_probe.ports(switch.ip, credentials)}
        source, note = "switch", ""
    except AuthError:
        live, source = {}, "devicemap"
        note = i18n.t("ip.switchWantsCredentials")
    except Exception:
        live, source = {}, "devicemap"
        note = i18n.t("ip.switchUnreachable")

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
