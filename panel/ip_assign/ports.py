#!/usr/bin/env python3
"""Port lists, and finding the ports a run must never touch."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from .. import settings
from ..errors import AuthError, UnreachableError
from ..inventory.device_map import Inventory
from ..probe import switch as switch_probe
from ..system import interfaces
from .. import i18n


# Why a switch's MAC table could not be read. The codes are the contract —
# they travel to the UI and are worded there too (static/js/views/ip) — so a
# rewording here must not change them.
SWITCH_STATE_LABEL = {
    "auth": "ip.switchStateAuth",
    "unreachable": "ip.switchStateUnreachable",
    "unreadable": "ip.switchStateUnreadable",
    "empty": "ip.switchStateEmpty",
    "read": "ip.switchStateRead",
}


def switch_state_label(state: str) -> str:
    """The reading of a `tried[].state` code, in the current language."""
    key = SWITCH_STATE_LABEL.get(str(state or ""))
    return i18n.t(key) if key else str(state or "")


def port_key(port: int) -> str:
    return f"p{int(port)}"


def parse_ports(text: str, allowed: set[int] | None = None) -> list[int]:
    """'11-14, 21 22' -> [11,12,13,14,21,22]. Raises ValueError if invalid."""
    out: list[int] = []
    normalised = str(text or "").replace(";", ",").replace(" ", ",")
    for chunk in normalised.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            low, _, high = chunk.partition("-")
            try:
                first, last = int(low), int(high)
            except ValueError:
                raise ValueError(i18n.t("error.invalidPortRange", chunk=chunk))
            if last < first:
                raise ValueError(i18n.t("error.invalidPortRange", chunk=chunk))
            out.extend(range(first, last + 1))
        else:
            try:
                out.append(int(chunk))
            except ValueError:
                raise ValueError(i18n.t("error.invalidPort", chunk=chunk))
    if allowed is not None:
        outside = sorted(set(out) - allowed)
        if outside:
            raise ValueError(
                i18n.t("error.portNotOnSwitch",
                       ports=", ".join(str(port) for port in outside)))
    return sorted(set(out))


def format_ports(ports) -> str:
    """[11,12,13,21] -> '11-13, 21'"""
    values = sorted({int(port) for port in ports})
    if not values:
        return ""
    chunks, start, previous = [], values[0], values[0]
    for index in range(1, len(values) + 1):
        current = values[index] if index < len(values) else None
        if current == previous + 1:
            previous = current
            continue
        chunks.append(str(start) if start == previous
                      else f"{start}-{previous}")
        start = previous = current
    return ", ".join(chunks)


def assert_not_protected(ports, protected: dict[int, str] | None) -> None:
    """Raise if a port that must stay out of the run is in the target list.

    Called twice: when the request arrives (so the user sees it immediately)
    and inside the run itself (in case a path that skips the first check is
    ever added).
    """
    targets = set(ports)
    for port in sorted(protected or {}):
        if port in targets:
            raise ValueError(
                i18n.t("error.protectedPortSelected", port=port,
                       reason=protected[port]))


def allowed_ports(inventory: Inventory, switch_id: str) -> list[int]:
    """Ports of devices attached to this switch in DeviceMap."""
    ports = {int(device.port) for device in inventory.devices
             if device.switch_id == switch_id and device.port
             and str(device.port).isdigit()}
    return sorted(ports)


def _switch_tables(inventory: Inventory, credentials_for=None):
    """Each switch's MAC learning table plus its own MAC.

    Read in parallel: a switch that is down fails on its own timeout without
    holding up the others. Returns ([(switch, table, own_mac, problem)], tried)
    """
    switches = inventory.switches()
    if not switches:
        return [], []

    # Kept short: this search runs while the user is looking at the screen and
    # waits out the timeout of any switch that is down.
    timeout = min(settings.PROBE_TIMEOUT, 2.5)

    def read(switch):
        credentials = credentials_for(switch) if credentials_for else None
        try:
            table = switch_probe.mac_table(switch.ip, credentials,
                                           timeout=timeout)
        except AuthError:
            return switch, {}, "", "auth"
        except UnreachableError:
            return switch, {}, "", "unreachable"      # stable code, not text
        except Exception:
            return switch, {}, "", "unreadable"
        # The switch's OWN MAC: finding it in a neighbour's table reveals the
        # port linking the two switches.
        try:
            own = interfaces.normalize_mac(
                switch_probe.read(switch.ip, credentials,
                                  timeout=timeout).get("mac", ""))
        except Exception:
            own = ""
        return switch, table, own, ""

    pool = ThreadPoolExecutor(max_workers=min(8, len(switches)))
    try:
        results = list(pool.map(read, switches))
    finally:
        pool.shutdown(wait=True)

    # `state` is a CODE, not a sentence: it is written on screen in two
    # places and both have to be able to say it in the user's language.
    tried = [{"switchId": switch.id, "name": switch.name, "ip": switch.ip,
              "state": problem or ("empty" if not table else "read")}
             for switch, table, _own, problem in results]
    return results, tried


def _macs_on_port(table: dict, port: int) -> int:
    return sum(1 for value in table.values() if value == port)


def protected_ports(inventory: Inventory, credentials_for=None) -> dict:
    """EVERY port the run must not touch — none of them is asked for.

    Two physical facts, both of which used to be typed in by hand:

      · The computer is on one port of one switch.
      · The switches are linked to each other by one port each.

    Both fall out of the switches' MAC learning tables, so there was no need
    to ask. A wrong answer did double damage: a port that needed protecting
    was not protected, and a port that did not was dropped from the run.

    The rule is one and the same for every switch: **whichever port of a
    switch learned the computer's MAC is the path towards the computer.** On
    the switch the computer is plugged into that is its own port; on the
    others it is the uplink used to reach that switch. Cutting either cuts the
    run's own path, so both are protected.

    Which switch carries the computer DIRECTLY follows from how many MACs were
    learned on the port: an access port has one device, an uplink has
    everything behind the switch. Order would be the wrong signal — the
    neighbouring switch sees the computer's MAC on its uplink too.

    On top of that the neighbour's OWN MAC is searched for, which finds
    switch-to-switch links that are not on the computer's path.

    Returns:
      {"time", "computer": {...}, "ports": [...], "tried": [...], "note": ""}
    Each entry in `ports`:
      {"switchId", "switchName", "port", "kind", "reason"}
      `kind`: "computer" | "link"
    Nothing that cannot be found is guessed.
    """
    empty_computer = {"switchId": "", "switchName": "", "port": None,
                      "mac": "", "interface": "", "localIp": "",
                      "source": "none", "note": ""}
    result = {"time": time.time(), "computer": dict(empty_computer),
              "ports": [], "tried": [], "note": ""}

    if not inventory.switches():
        return {**result, "note": i18n.t("ip.noSwitchInProject")}
    # The interface dump is read once; running a command per switch is
    # pointless.
    local_interfaces = interfaces.list_interfaces()
    if not local_interfaces:
        return {**result,
                "note": "Could not read the computer's network interfaces"}

    results, tried = _switch_tables(inventory, credentials_for)
    result["tried"] = tried
    readable = [(switch, table, own)
                for switch, table, own, problem in results
                if table and not problem]
    if not readable:
        reasons = ", ".join(
            i18n.t("ip.switchStateLine", switch=entry["name"],
                   state=switch_state_label(entry["state"]))
            for entry in tried)
        return {**result,
                "note": i18n.t("ip.noMacTableRead", reasons=reasons)}

    # ── which switch, which port learned the computer's MAC? ──
    findings = []
    for switch, table, _own in readable:
        local = interfaces.interface_toward(switch.ip, local_interfaces)
        # The routed interface first, then the rest.
        ordered = ([local["mac"]] if local["mac"] else []) + [
            mac for mac in local["candidates"] if mac != local["mac"]]
        mac = next((candidate for candidate in ordered if candidate in table),
                   "")
        if not mac:
            continue
        port = int(table[mac])
        findings.append({"switch": switch, "port": port, "mac": mac,
                         "interface": local["name"],
                         "localIp": local["localIp"],
                         "neighbours": _macs_on_port(table, port)})

    ports: dict[tuple[str, int], dict] = {}

    def add(switch, port, kind, reason):
        key = (switch.id, int(port))
        # "computer" is the more informative label; if a port arrives for both
        # reasons, that one stays.
        if key in ports and ports[key]["kind"] == "computer":
            return
        ports[key] = {"switchId": switch.id, "switchName": switch.name,
                      "port": int(port), "kind": kind, "reason": reason}

    if findings:
        # Fewest learned MACs = the port the computer is directly attached to.
        direct = min(findings, key=lambda entry: entry["neighbours"])
        result["computer"] = {
            "switchId": direct["switch"].id,
            "switchName": direct["switch"].name,
            "port": direct["port"], "mac": direct["mac"],
            "interface": direct["interface"], "localIp": direct["localIp"],
            "source": "mac", "note": "",
        }
        for entry in findings:
            if entry is direct:
                add(entry["switch"], entry["port"], "computer",
                    "the computer is on this port")
            else:
                add(entry["switch"], entry["port"], "link",
                    f"link towards {direct['switch'].name}")
    else:
        result["computer"] = {
            **empty_computer,
            "note": "The computer's MAC is in none of the switches read — "
                    "is its cable plugged in?"}

    # ── which port links the switches to each other? ──
    # Wherever a neighbour's own MAC sits in our table, that port is the link
    # to that neighbour. Links off the computer's path are only found this way.
    own_macs = {switch.id: own for switch, _table, own in readable if own}
    for switch, table, _own in readable:
        for neighbour_id, neighbour_mac in own_macs.items():
            if neighbour_id == switch.id or neighbour_mac not in table:
                continue
            neighbour = inventory.find(neighbour_id)
            add(switch, table[neighbour_mac], "link",
                f"link to {neighbour.name if neighbour else neighbour_id}")

    result["ports"] = sorted(ports.values(),
                             key=lambda entry: (entry["switchName"],
                                                entry["port"]))
    return result


def computer_port(inventory: Inventory, credentials_for=None) -> dict:
    """Just where the computer is — a shortcut through `protected_ports`."""
    return protected_ports(inventory, credentials_for)["computer"]
