#!/usr/bin/env python3
"""KYLAND switch reads, through the switch panel's working client.

There is no second switch client here. `field_scripts/switch_api.py` is
imported at runtime and its verified calls are used:

    sw_get(ip, "stat/basicInfo", timeout, credentials=(user, password))

So URL, Basic Auth shape, port, timeout, headers and the "no JSON means you
must sign in" rule are identical in both panels.

`credentials` is always passed explicitly. As long as it is, switch_api never
consults its own in-module store; this panel's credentials live only in
`panel.credentials`.
"""
from __future__ import annotations

from .. import script_loader, settings
from ..errors import (AuthError, UnreachableError, VerificationError, classify)
from .. import i18n

# Fields looked for in a basicInfo reply. With none of them present the JSON
# is not switch data — a 200 alone does not count.
EXPECTED_FIELDS = ("deviceName", "sysName", "deviceType", "model",
                   "softVer", "softwareVersion", "macAddress", "mac")


def api():
    """The loaded switch_api module — shared by tests and other modules."""
    return script_loader.switch_api()


def _identity_body(data):
    """Extract the identity dict from a basicInfo reply."""
    if not isinstance(data, dict):
        raise VerificationError(i18n.t("error.switchIdentity"))
    body = data.get("basicInfo", data)
    if isinstance(body, list):
        body = body[0] if body and isinstance(body[0], dict) else {}
    if not isinstance(body, dict):
        raise VerificationError(i18n.t("error.switchIdentity"))
    return body


def validate(data) -> dict:
    """Confirm the reply really is a switch identity.

    HTTP 200 + JSON is not enough: the endpoint may have changed, another
    device may hold the address, or a proxy may be in the way. At least one
    expected field must be populated.
    """
    body = _identity_body(data)
    populated = {k: v for k, v in body.items()
                 if k in EXPECTED_FIELDS and str(v).strip()}
    if not populated:
        raise VerificationError(
            i18n.t("error.notASwitch"))
    return body


def uptime_seconds(body: dict):
    """The switch's uptime in seconds.

    KYLAND has no single `uptime` field; the value arrives split under
    `operateTime`:

        "operateTime": {"day": "0", "hour": "7", "minute": "30",
                        "second": "39"}
    """
    for name in ("upTime", "uptime", "systemUptime"):
        if str(body.get(name, "")).strip():
            return body[name]

    parts = body.get("operateTime")
    if not isinstance(parts, dict):
        return None
    multipliers = {"day": 86400, "hour": 3600, "minute": 60, "second": 1}
    total, found = 0, False
    for name, factor in multipliers.items():
        value = parts.get(name)
        if value in (None, ""):
            continue
        try:
            total += int(float(value)) * factor
        except (TypeError, ValueError):
            return None
        found = True
    return total if found else None


def read(ip: str, credentials: tuple[str, str] | None = None,
         timeout: float | None = None) -> dict:
    """Read the switch identity.

    Returns: {"name", "model", "version", "mac", "uptime", "raw"}
    Raises:  AuthError / UnreachableError / VerificationError
    """
    module = api()
    limit = timeout if timeout is not None else settings.PROBE_TIMEOUT
    try:
        data = module.sw_get(ip, "stat/basicInfo", timeout=limit,
                             credentials=credentials)
    except module.AuthError:
        # 401/403, WWW-Authenticate, or a login page instead of JSON.
        # The script's own wording is dropped on purpose: it is an
        # untranslatable English sentence written in a file this panel
        # only borrows (field_scripts/switch_api.py), and it says nothing
        # the message below does not, the address included — the UI shows
        # that beside it.
        raise AuthError(i18n.t("error.probeAuth"))
    except Exception as exc:                       # network / HTTP layer
        code = getattr(getattr(exc, "response", None), "status_code", None)
        if code in (401, 403):
            raise AuthError(i18n.t("error.probeAuth"))
        raise classify(exc)

    body = validate(data)
    return {
        "name": body.get("deviceName") or body.get("sysName") or "",
        "model": body.get("deviceType") or body.get("model") or "",
        "version": body.get("softVer") or body.get("softwareVersion") or "",
        "mac": body.get("macAddress") or body.get("mac") or "",
        "uptime": uptime_seconds(body),
        "raw": body,
    }


def ports(ip: str, credentials: tuple[str, str] | None = None,
          timeout: float | None = None) -> list[dict]:
    """Port list for the IP assignment screen's front panel.

    Same endpoints and merge order as the switch panel (portMode + poePort +
    poeStatus). All three are read so both apps colour the faceplate from the
    same data: portMode alone cannot tell "powering" from "linked".

    PoE endpoints do not exist on every model; when absent the fields stay
    empty rather than being invented.
    """
    module = api()
    limit = timeout if timeout is not None else settings.PROBE_TIMEOUT

    def fetch(endpoint: str):
        try:
            return module.sw_get(ip, endpoint, timeout=limit,
                                 credentials=credentials)
        except module.AuthError:                # see read() on the wording
            raise AuthError(i18n.t("error.probeAuth"))
        except Exception as exc:
            raise classify(exc)

    port_mode = fetch("stat/portMode")
    rows = port_mode.get("portMode", []) if isinstance(port_mode, dict) else []
    if not isinstance(rows, list):
        raise VerificationError(i18n.t("error.switchPortList"))

    def optional(endpoint: str, key: str) -> dict:
        """PoE endpoints may be missing by model; auth errors still surface."""
        try:
            data = fetch(endpoint)
        except AuthError:
            raise
        except Exception:
            return {}
        records = data.get(key, []) if isinstance(data, dict) else []
        return {int(p["pid"]): p for p in records
                if isinstance(p, dict) and str(p.get("pid", "")).isdigit()}

    poe = optional("stat/poePort", "poePort")
    power = optional("stat/poeStatus", "poeStatus")

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = int(row.get("pid", 0))
        poe_row = poe.get(pid, {})
        power_row = power.get(pid, {})
        watts = power_row.get("powerUsed")
        out.append({
            "pid": pid,
            "type": row.get("type", ""),
            "enabled": bool(row.get("adminStat")),
            "link": row.get("linkStat", ""),
            "poe": pid in poe,
            "poeMode": str(poe_row.get("poeMode", "")),
            "poeState": power_row.get("portStatus", ""),
            # The switch reports power as an integer ten times too large.
            "watts": (round(int(watts) / 10, 1)
                      if str(watts).isdigit() else None),
        })
    return out


def mac_table(ip: str, credentials: tuple[str, str] | None = None,
              timeout: float | None = None) -> dict[str, int]:
    """The switch's MAC learning table: {mac: port}.

    Endpoints and parsing come from the IP assignment script, which already
    reads this table to verify ports. A second parser would drift from it the
    moment KYLAND's reply shape changed. The HTTP path is this panel's own:
    credentials live in `panel.credentials`, never in the script's store.

    A switch that answers but knows none of the MAC endpoints yields an empty
    dict — not an error, just no table on that model. A switch that cannot be
    reached at all raises UnreachableError: "off" and "does not serve the
    table" call for different fixes (the switch versus the cable).
    """
    module = api()
    assign = script_loader.intercom_ip_assign()
    limit = timeout if timeout is not None else settings.PROBE_TIMEOUT
    endpoints = getattr(assign, "MAC_ENDPOINTS", ["stat/macQuery"])
    parse = getattr(assign, "_parse_mac_table", None)
    if parse is None:
        return {}

    last_error = None
    for endpoint in endpoints:
        try:
            data = module.sw_get(ip, endpoint, timeout=limit,
                                 credentials=credentials)
        except module.AuthError:                # see read() on the wording
            raise AuthError(i18n.t("error.switchAuth"))
        except Exception as exc:
            error = classify(exc)
            # No point trying the remaining endpoints on an unreachable
            # switch: three endpoints x timeout kept the user waiting half a
            # minute. A 404 is different — that endpoint is missing, the next
            # may exist.
            if isinstance(error, UnreachableError):
                raise error
            last_error = error
            continue
        last_error = None                 # the switch talked; endpoint's fault
        table = parse(data)
        if table:
            return {str(mac).lower(): int(port) for mac, port in table.items()}
    if last_error is not None:
        raise last_error
    return {}


__all__ = [
    "AuthError",
    "UnreachableError",
    "VerificationError",
    "api",
    "mac_table",
    "ports",
    "read",
    "validate",
]
