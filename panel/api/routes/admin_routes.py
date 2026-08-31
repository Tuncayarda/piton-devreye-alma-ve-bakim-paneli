#!/usr/bin/env python3
"""The service key: what is in the machine, and getting in with it.

`/api/admin/key` is deliberately OPEN — a field package has to be able to
ask whether a key is present in order to offer the question at all, and the
answer carries nothing a key could be built from. Everything that CHANGES
something is closed: entering admin mode re-verifies the file on the spot,
and listing or writing volumes is admin-only on top of that
(`panel.api.guard`).

THE CLIENT'S WORD IS NEVER TAKEN FOR IT. `POST /api/admin/mode {enter:true}`
does not consult the watcher's last observation; it goes and looks at the
volumes again. The watcher exists so the UI can poll cheaply, not so a
request can be granted on the strength of something observed two seconds
ago.
"""
from __future__ import annotations

from ... import adminkey, editions, i18n
from ..lifecycle import leave_admin
from ..response import respond
from .edition_routes import edition_body


def get_key(_query=None):
    # `fresh` rather than `snapshot`: asking is what makes the observation,
    # so a key pushed in is noticed one UI poll later rather than one UI
    # poll plus one watcher poll later (see panel.adminkey.watcher.fresh).
    return respond(200, {**adminkey.WATCH.fresh(),
                         "usable": adminkey.usable(),
                         # The OTHER way in, answered on the same poll
                         # because it can change while the panel is open in
                         # exactly the same way: the build secret may be
                         # dropped into the checkout as a file and taken
                         # away again (panel.adminkey.secret.SECRET_FILE).
                         # The window offers the way back into admin mode on
                         # this and on `recognised`, and refusing it is the
                         # same decision on the same two facts.
                         "withoutKey": editions.opens_as_admin()})


def get_key_volumes(_query=None):
    """The volumes a key could be written to. The `admin` build's screen."""
    listed = []
    for volume in adminkey.removable():
        existing = adminkey.read(volume)
        listed.append({
            "path": str(volume),
            "name": volume.name or str(volume),
            # So the screen can say "replace" rather than "write" and the
            # engineer is not surprised by an overwrite.
            "hasKey": existing is not None,
        })
    return respond(200, {"volumes": listed, "canWrite": adminkey.can_write()})


def post_key_write(body):
    """Mint a service key onto a volume. Only a build holding the secret.

    Guarded twice on purpose: the guard has already refused this path
    outside admin mode, and the build still has to hold the secret rather
    than a digest of it. The two are different failures — a customer package
    RAISED to admin mode by a stick reaches this path, and must not be able
    to make more sticks.
    """
    if not adminkey.can_write():
        return respond(403, {"error": i18n.t("error.adminKeyWriteNotAllowed")})
    wanted = body.get("volume")
    if not isinstance(wanted, str) or not wanted.strip():
        return respond(400, {"error": i18n.t("error.adminKeyVolumeRequired")})
    label = body.get("label")
    label = label if isinstance(label, str) else ""

    # The volume comes from OUR list, never from the body as a path: an
    # arbitrary path here would be a "write a file anywhere on this machine"
    # endpoint, in a process that runs elevated.
    target = next((volume for volume in adminkey.removable()
                   if str(volume) == wanted), None)
    if target is None:
        return respond(404, {"error": i18n.t("error.adminKeyVolumeGone")})

    try:
        adminkey.write(target, label)
    except (OSError, RuntimeError) as exc:
        return respond(500, {"error": i18n.t("error.adminKeyWriteFailed",
                                             reason=str(exc))})
    adminkey.WATCH.observe(wait=True)
    return respond(200, {"written": str(target),
                         "key": adminkey.WATCH.snapshot()})


def get_key_drives(_query=None):
    """The removable drives that could be erased into a service key.

    Whole drives, not mounted volumes: what is listed here is about to be
    wiped, so it is named by the model and the size an engineer can check
    against the thing in their hand.
    """
    listed = [{"id": drive.id, "name": drive.name, "size": drive.size,
               "bus": drive.bus} for drive in adminkey.media.drives()]
    return respond(200, {"drives": listed, "canWrite": adminkey.can_write()})


def post_key_prepare(body):
    """ERASE a drive, format it FAT32, and write the key onto it.

    The one operation in the panel that destroys data outside its own files.
    Guarded exactly like writing a key — the secret has to be in the build —
    and `media.prepare` refuses on its own anything the operating system
    does not call removable, whatever id arrives here.
    """
    if not adminkey.can_write():
        return respond(403, {"error": i18n.t("error.adminKeyWriteNotAllowed")})
    wanted = body.get("drive")
    if not isinstance(wanted, str) or not wanted.strip():
        return respond(400, {"error": i18n.t("error.adminKeyVolumeRequired")})
    label = body.get("label")
    label = label if isinstance(label, str) else ""

    drive = adminkey.media.find(wanted)
    if drive is None:
        return respond(404, {"error": i18n.t("error.adminKeyVolumeGone")})

    try:
        mounted = adminkey.media.prepare(drive.id)
        adminkey.write(mounted, label)
    except adminkey.media.MediaError as exc:
        return respond(500, {"error": _media_message(exc)})
    except OSError as exc:
        return respond(500, {"error": i18n.t("error.adminKeyWriteFailed",
                                             reason=str(exc))})
    adminkey.WATCH.observe(wait=True)
    return respond(200, {"written": str(mounted), "drive": drive.name,
                         "key": adminkey.WATCH.snapshot()})


def _media_message(exc) -> str:
    """Turn a disk tool's failure into something to act on.

    A missing tool is the one an operator can actually fix (Linux ships
    without `mkfs.vfat` more often than not), so it is named rather than
    folded into a general failure.
    """
    reason = str(exc)
    if reason == "not-removable":
        return i18n.t("error.adminKeyDriveNotRemovable")
    if reason.startswith("missing tool: "):
        return i18n.t("error.adminKeyToolMissing",
                      tool=reason.split(": ", 1)[1])
    return i18n.t("error.adminKeyPrepareFailed", reason=reason)


def post_mode(body):
    """Enter or leave admin mode, either way round and as often as asked.

    Leaving needs nothing — giving something up never does — and it is
    allowed even to a run that opened as admin on the build secret: the
    field view is a real place to go, and the way to see what the customer
    sees. Entering is the one that has to be earned, by the build secret or
    by a stick, and the stick is READ AGAIN here rather than trusted from
    the last poll.
    """
    enter = body.get("enter") is True

    if not enter:
        leave_admin()
        return respond(200, edition_body())

    if editions.opens_as_admin():
        editions.set_admin(True)
        return respond(200, edition_body())
    if not adminkey.usable():
        return respond(409, {"error": i18n.t("error.adminKeyUnavailable")})

    state = adminkey.WATCH.observe(wait=True)
    if not state.get("recognised"):
        # A key that could not be READ is not a key that was refused: the
        # operating system gates removable volumes and the panel runs
        # elevated. Naming it separately is the difference between "your
        # stick is wrong" and something the user can actually fix.
        message = ("error.adminKeyDenied" if state.get("reason") == "denied"
                   else "error.adminKeyInvalid" if state.get("present")
                   else "error.adminKeyNotFound")
        return respond(403, {"error": i18n.t(message)})
    editions.set_admin(True)
    return respond(200, edition_body())


GET = {
    "/api/admin/key": get_key,
    "/api/admin/key/volumes": get_key_volumes,
    "/api/admin/key/drives": get_key_drives,
}

POST = {
    "/api/admin/mode": post_mode,
    "/api/admin/key/write": post_key_write,
    "/api/admin/key/prepare": post_key_prepare,
}
