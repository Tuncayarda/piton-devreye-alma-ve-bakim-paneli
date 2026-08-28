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


# Paths only admin mode may reach at all, whatever the edition's view list
# says. The service key's own endpoints: reading the key state is open (the
# field UI has to know whether to offer the question), but changing anything
# is not.
ADMIN_ONLY = (
    "/api/admin/key/volumes",
    "/api/admin/key/write",
    "/api/admin/key/drives",
    "/api/admin/key/prepare",
)


def refusal(path: str, body=None):
    """The response that refuses this call, or None to let it through."""
    if not editions.is_active():
        return None                      # nothing to enforce against yet
    if path in ADMIN_ONLY and not editions.admin():
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
    return None


def _denied():
    # 403 rather than 404: the path exists, and pretending otherwise would
    # make a genuine typo indistinguishable from a refusal in the log.
    return respond(403, {"error": i18n.t("error.adminModeRequired")})
