#!/usr/bin/env python3
"""Which API paths this edition, in this mode, is allowed to answer.

HIDING A SCREEN IS NOT KEEPING IT. The whole API is reachable from the page
over the desktop bridge, and the sidebar only decides what is drawn: a screen
left out of the menu can still be opened by asking for its data. The project
definition — the device list, the addresses, the SIP numbering — is exactly
what an edition exists to keep to itself, so the refusal has to be here, on
the side that holds the data.

The table is an ALLOWLIST OF RESTRICTIONS, not of paths: a path absent from
it is unrestricted, because most of the API is the field work every edition
does. Only the handful of paths that belong to a hideable screen appear, and
each names the view it belongs to — the same view id the sidebar filters on
and `panel.editions.views()` produces, so what is drawn and what is answered
are decided by one list rather than two.
"""
from __future__ import annotations

from .. import editions, i18n
from .response import respond

# Path prefix -> the view it belongs to, named exactly as the sidebar and
# `static/index.html` name it.
#
# The "Project & device list" screen (view id `admin`) has no path of its
# own: it is drawn from `/api/project`, which every screen needs. What it
# adds beyond the field screens is the "forget every credential" button,
# handled separately below.
#
# MATCHED BY PREFIX, not by listing every path. The table used to name each
# endpoint, which held while a restricted screen had two of them; the ADB and
# switch screens have eleven and fourteen. A list that long is a list with a
# gap in it, and the gap is silent — a new endpoint on a guarded screen would
# be open until somebody remembered this file. A prefix guards the screen's
# next endpoint on the day it is written.
#
# A prefix matches the path exactly or the path plus a slash, so `/api/switch`
# never claims `/api/switchboard`.
RESTRICTED: dict[str, str] = {
    "/api/piscu": "piscu",
    "/api/mqtt": "mqtt",
    "/api/adb": "adb",
    "/api/switch": "switch",
}


def restricted_view(path: str) -> str | None:
    """The view `path` belongs to, if it belongs to a restricted one."""
    for prefix, view in RESTRICTED.items():
        if path == prefix or path.startswith(prefix + "/"):
            return view
    return None


# The subtree only admin mode may reach at all, whatever the edition's view
# list says: the service key's own endpoints. MATCHED BY PREFIX, for the
# reason the RESTRICTED table above already wrote down — a per-path list
# develops silent gaps, and this file spent thirty lines arguing that while
# keeping one. The single deliberately-open path is the exception list:
# reading the key STATE is field work (the UI has to know whether to offer
# the question); changing anything under it is not.
ADMIN_ONLY_PREFIX = "/api/admin/key"
ADMIN_OPEN = ("/api/admin/key",)


def refusal(path: str, body=None):
    """The response that refuses this call, or None to let it through."""
    if not editions.is_active():
        return None                      # nothing to enforce against yet
    under_key = (path == ADMIN_ONLY_PREFIX
                 or path.startswith(ADMIN_ONLY_PREFIX + "/"))
    if under_key and path not in ADMIN_OPEN and not editions.admin():
        return _denied()
    view = restricted_view(path)
    if view is not None and view not in editions.views():
        return _denied()
    # "Forget every credential in memory" is an admin action wearing a field
    # path: the single-device form of it is how a technician clears a
    # password they mistyped, and that must keep working.
    if (path == "/api/credentials/forget" and isinstance(body, dict)
            and body.get("all") is True and not editions.admin()):
        return _denied()
    # A project that came off the service key opens in admin mode only. This
    # used to live in the route handler — an admin decision outside the one
    # module whose whole job is holding them, and the exact "second
    # project-opening path would be open until somebody remembered" gap the
    # prefix table exists to close. Asked of the EXTRA REGISTRY directly:
    # `find_project` hides extras outside admin mode, so a lookup through it
    # answered None in exactly the mode this refusal exists for.
    if (path == "/api/project/select" and isinstance(body, dict)
            and editions.is_extra_key(str(body.get("key") or ""))
            and not editions.admin()):
        return _denied()
    return None


def _denied():
    # 403 rather than 404: the path exists, and pretending otherwise would
    # make a genuine typo indistinguishable from a refusal in the log.
    return respond(403, {"error": i18n.t("error.adminModeRequired")})
