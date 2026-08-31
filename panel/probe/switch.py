#!/usr/bin/env python3
"""KYLAND switch reads for the device screens.

There is no second switch client here. `panel.switch` is this panel's one
client and this module calls it:

    switch.CLIENT.get(ip, "stat/basicInfo", timeout=..., credentials=(u, p))

So URL, Basic Auth shape, port, timeout, headers and the "no JSON means you
must sign in" rule are the same here as on the switch screen. What this module
adds on top is the shape the device screens want: an identity validated
against a list of expected fields, a port list keyed the way the front panel
draws it, and the MAC table.

`credentials` is always passed explicitly. The client holds none — this
panel's credentials live only in `panel.credentials`.
"""
from __future__ import annotations

from .. import script_loader, settings, switch
from ..errors import (AuthError, UnreachableError, VerificationError, classify)
from .. import i18n

# Fields looked for in a basicInfo reply. With none of them present the JSON
# is not switch data — a 200 alone does not count.
EXPECTED_FIELDS = ("deviceName", "sysName", "deviceType", "model",
                   "softVer", "softwareVersion", "macAddress", "mac")


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
    limit = timeout if timeout is not None else settings.PROBE_TIMEOUT
    try:
        data = switch.CLIENT.get(ip, "stat/basicInfo", timeout=limit,
                                 credentials=credentials)
    except AuthError:
        # 401/403, WWW-Authenticate, or a login page instead of JSON. Raised
        # again rather than let through so the wording is this module's own
        # and the same on every read below.
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

    The merge itself is `panel.switch.ports.get_ports` — the SAME rows the
    switch screen shows, including its tolerance for a model missing a PoE
    table, so the two screens cannot disagree about what a switch's face
    looks like. This module only projects them into the key names the IP
    screen's front panel has always drawn from.
    """
    limit = timeout if timeout is not None else settings.PROBE_TIMEOUT
    try:
        rows = switch.ports.get_ports(switch.CLIENT, ip, credentials,
                                      timeout=limit)
    except AuthError:                           # see read() on the wording
        raise AuthError(i18n.t("error.probeAuth"))
    except Exception as exc:
        raise classify(exc)

    return [{
        "pid": row["id"],
        "type": row["portType"],
        "enabled": row["enabled"],
        "link": row["linkState"],
        "poe": row["supportsPoe"],
        "poeMode": row["poeMode"],
        "poeState": row["poeState"],
        "watts": row["powerWatts"],
    } for row in rows]


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
    assign = script_loader.intercom_ip_assign()
    limit = timeout if timeout is not None else settings.PROBE_TIMEOUT
    # Direct attribute reads, no getattr fallback: the loader has already
    # verified both names (script_loader.CONTRACTS). The old fallback meant
    # a rename in the script did not fail — it silently returned {} and
    # switched MAC→port verification off for the whole run.
    endpoints = assign.MAC_ENDPOINTS
    parse = assign.parse_mac_table

    last_error = None
    for endpoint in endpoints:
        try:
            data = switch.CLIENT.get(ip, endpoint, timeout=limit,
                                     credentials=credentials)
        except AuthError:                       # see read() on the wording
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
    "mac_table",
    "ports",
    "read",
    "validate",
]
