#!/usr/bin/env python3
"""Reading and writing a switch's ports and their PoE.

Three of KYLAND's habits are load-bearing here and none of them are obvious:

1. THE PORT TABLES ARE WRITTEN WHOLE. `stat/poePort` and `stat/portMode`
   take the entire table on every POST. Sending one port on its own does not
   change one port — it resets the other twenty-three to the form's defaults.
   Every write below therefore reads the current table first and rewrites it
   with one row changed.

2. A BOOLEAN IS PRESENT OR ABSENT, never "0". `adminStat_3=1` enables port 3;
   disabling it means leaving the field out of the form entirely.

3. POWER ARRIVES TEN TIMES TOO LARGE. `powerUsed: "123"` is 12.3 W.
"""
from __future__ import annotations

from .. import i18n
from ..errors import AuthError, DeviceError

# The modes a PoE port can be in, as CATALOGUE KEYS rather than words. The
# sibling application spelled the words out here — it had one language and no
# catalogue — and they travelled from this dictionary through /api/switch
# straight onto the screen, so a panel running in Turkish offered "Off" in its
# right-click menu. Neither language gate saw it: one reads static/js, the
# other looks for Turkish in English text.
POE_MODE = {"0": "switch.poeModeOff",
            "1": "switch.poeModePoe",
            "2": "switch.poeModePoePlus"}
POE_MODES = frozenset(POE_MODE)
PORT_CONFIG_FIELDS = {"enabled", "linkType", "autoNegotiation", "speed",
                      "fullDuplex", "flowControl", "maxFrameLength"}
BOOLEAN_PORT_CONFIG_FIELDS = {"enabled", "autoNegotiation", "fullDuplex",
                              "flowControl"}


def get_ports(client, ip: str, credentials=None) -> list[dict]:
    """Merge portMode, poePort and poeStatus into one row per port.

    All three are read because none of them is the whole answer: portMode
    knows whether a port is up, poePort knows what it is configured to
    deliver, and only poeStatus can tell "powering" from merely "linked".

    poeStatus does not exist on every model. When it is missing the live
    fields stay empty rather than being invented — but an AuthError still
    travels, because "you must sign in" is not the same as "this model has no
    such table".
    """
    port_modes = client.get(ip, "stat/portMode",
                            credentials=credentials).get("portMode", [])
    poe_ports = {
        int(port["pid"]): port
        for port in client.get(ip, "stat/poePort",
                               credentials=credentials).get("poePort", [])}
    try:
        live = {
            int(port["pid"]): port
            for port in client.get(
                ip, "stat/poeStatus",
                credentials=credentials).get("poeStatus", [])}
    except AuthError:
        raise
    except Exception:
        live = {}

    output = []
    for port in port_modes:
        pid = int(port["pid"])
        poe = poe_ports.get(pid, {})
        status = live.get(pid, {})
        power = status.get("powerUsed")
        output.append({
            "id": pid,
            "portType": port.get("type", ""),
            "enabled": bool(port.get("adminStat")),
            "linkState": port.get("linkStat", ""),
            "linkLabel": port.get("linktext", ""),
            "speed": str(port.get("speed", "")),
            "autoNegotiation": bool(port.get("autoNego")),
            "fullDuplex": bool(port.get("duplex")),
            "flowControl": bool(port.get("flowCtrl")),
            "maxFrameLength": str(port.get("maxLength", "")),
            "linkType": str(port.get("linkType", "")),
            "supportsPoe": pid in poe_ports,
            "poeMode": str(poe.get("poeMode", "")),
            "poePriority": str(poe.get("priority", "0")),
            "poeMaxPower": str(poe.get("maxPower", "154")),
            "poeState": status.get("portStatus", ""),
            # See habit 3 at the top of this file.
            "powerWatts": (round(int(power) / 10, 1)
                           if str(power).isdigit() else None),
        })
    return output


def _poe_form(ports: list, mode_overrides: dict) -> dict:
    """The whole PoE table, with the named ports' modes replaced."""
    form = {}
    for item in ports:
        pid = int(item["pid"])
        form[f"mode_{pid}"] = str(mode_overrides.get(pid, item["poeMode"]))
        form[f"priority_{pid}"] = str(item["priority"])
        form[f"maxPower_{pid}"] = str(item["maxPower"])
    return form


def _port_mode_form(ports: list, admin_overrides: dict) -> dict:
    """The whole portMode table, with the named ports' admin state replaced.

    Do not simplify this into "send the one port that changed" — see habit 1.
    """
    form = {}
    for port in ports:
        pid = int(port["pid"])
        admin = admin_overrides.get(pid, bool(port.get("adminStat")))
        if admin:
            form[f"adminStat_{pid}"] = "1"
        form[f"linkType_{pid}"] = str(port.get("linkType", "0"))
        if port.get("autoNego"):
            form[f"autoNego_{pid}"] = "1"
        form[f"speed_{pid}"] = str(port.get("speed", ""))
        if port.get("duplex"):
            form[f"duplex_{pid}"] = "1"
        if port.get("flowCtrl"):
            form[f"flowCtrl_{pid}"] = "1"
        form[f"maxLength_{pid}"] = str(port.get("maxLength", "1522"))
    return form


def set_poe(client, ip: str, port: int, mode: str, credentials=None) -> dict:
    """Set one port's PoE mode."""
    if mode not in POE_MODES:
        raise DeviceError(i18n.t("switch.errorUnsupportedPoeMode", mode=mode))
    with client.lock(ip):
        ports = client.get(ip, "stat/poePort",
                           credentials=credentials).get("poePort", [])
        if not any(int(item["pid"]) == port for item in ports):
            raise DeviceError(i18n.t("switch.errorPortNotInPoeTable",
                                     port=port))
        return client.post(ip, "stat/poePort", _poe_form(ports, {port: mode}),
                           credentials=credentials)


def set_port_enabled(client, ip: str, port: int, enabled: bool,
                     credentials=None) -> dict:
    """Bring one port up or down."""
    with client.lock(ip):
        ports = client.get(ip, "stat/portMode",
                           credentials=credentials).get("portMode", [])
        if not any(int(item["pid"]) == port for item in ports):
            raise DeviceError(i18n.t("switch.errorPortMissing", port=port))
        return client.post(ip, "stat/portMode",
                           _port_mode_form(ports, {port: enabled}),
                           credentials=credentials)


def set_port_config(client, ip: str, port: int, config: dict,
                    credentials=None) -> dict:
    """Write one port's speed, duplex, negotiation and frame length."""
    unknown = sorted(set(config) - PORT_CONFIG_FIELDS)
    if unknown:
        raise DeviceError(i18n.t("switch.errorUnknownPortFields",
                                 fields=", ".join(unknown)))
    invalid_booleans = sorted(
        field for field in BOOLEAN_PORT_CONFIG_FIELDS.intersection(config)
        if not isinstance(config[field], bool))
    if invalid_booleans:
        raise DeviceError(i18n.t("switch.errorPortFieldsNotBoolean",
                                 fields=", ".join(invalid_booleans)))
    with client.lock(ip):
        ports = client.get(ip, "stat/portMode",
                           credentials=credentials).get("portMode", [])
        if not any(int(item["pid"]) == port for item in ports):
            raise DeviceError(i18n.t("switch.errorPortMissing", port=port))
        form = {}
        for item in ports:
            pid = int(item["pid"])
            values = config if pid == port else {}
            if values.get("enabled", bool(item.get("adminStat"))):
                form[f"adminStat_{pid}"] = "1"
            form[f"linkType_{pid}"] = str(
                values.get("linkType", item.get("linkType", "0")))
            if values.get("autoNegotiation", bool(item.get("autoNego"))):
                form[f"autoNego_{pid}"] = "1"
            form[f"speed_{pid}"] = str(
                values.get("speed", item.get("speed", "")))
            if values.get("fullDuplex", bool(item.get("duplex"))):
                form[f"duplex_{pid}"] = "1"
            if values.get("flowControl", bool(item.get("flowCtrl"))):
                form[f"flowCtrl_{pid}"] = "1"
            form[f"maxLength_{pid}"] = str(
                values.get("maxFrameLength", item.get("maxLength", "1522")))
        return client.post(ip, "stat/portMode", form, credentials=credentials)


def apply_batch(client, ip: str, poe: dict, ports: dict,
                credentials=None) -> dict:
    """Apply several PoE and port changes as two writes rather than many.

    The operator ticks a row of ports and presses apply once; sending one
    request per port would rewrite the whole table once per port, and a
    failure halfway would leave the switch in a state nobody chose.
    """
    invalid_modes = sorted(port for port, mode in poe.items()
                           if mode not in POE_MODES)
    if invalid_modes:
        raise DeviceError(i18n.t(
            "switch.errorUnsupportedPoeModes",
            ports=", ".join(str(port) for port in invalid_modes)))
    result = {"retCode": ["success"], "poe": [], "ports": []}
    with client.lock(ip):
        if poe:
            current = client.get(ip, "stat/poePort",
                                 credentials=credentials).get("poePort", [])
            known = {int(item["pid"]) for item in current}
            missing = sorted(set(poe) - known)
            if missing:
                raise DeviceError(i18n.t(
                    "switch.errorPortsNotInPoeTable",
                    ports=", ".join(str(port) for port in missing)))
            client.post(ip, "stat/poePort", _poe_form(current, poe),
                        credentials=credentials)
            result["poe"] = sorted(poe)

        if ports:
            current = client.get(ip, "stat/portMode",
                                 credentials=credentials).get("portMode", [])
            known = {int(item["pid"]) for item in current}
            missing = sorted(set(ports) - known)
            if missing:
                raise DeviceError(i18n.t(
                    "switch.errorPortsMissing",
                    ports=", ".join(str(port) for port in missing)))
            client.post(ip, "stat/portMode",
                        _port_mode_form(current, ports),
                        credentials=credentials)
            result["ports"] = sorted(ports)
    return result
