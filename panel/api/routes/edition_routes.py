#!/usr/bin/env python3
"""What this package is, what it may show, and which project is open.

`/api/version` answers before the panel is ready and never changes during a
session; this is the other half — everything that DOES change. Entering or
leaving admin mode and switching project both alter which screens exist, so
the UI re-reads this body after either and redraws from it.

The `views` list here and the one `panel.api.guard` enforces are the same
list (`panel.editions.views()`). Hiding a screen and refusing its data can
therefore never disagree — which matters, because hiding alone is worth
nothing: the whole API is exposed to the page over the desktop bridge, and
anything the UI can ask for it can ask for without being shown a button.
"""
from __future__ import annotations

from ... import editions, i18n, jobs
from ..presenters import WRITING_JOB_KINDS
from ..response import respond


def project_dto(project, current: str) -> dict:
    return {
        "key": project.key,
        "label": project.label,
        # Delivered or not. The VIP entry exists in the table before its
        # DeviceMap does, and the menu has to say why it cannot be opened
        # rather than fail on the click.
        "available": editions.available(project),
        "current": project.key == current,
        # "usb" projects arrive on the service key and disappear with it.
        "origin": "usb" if editions.is_extra(project) else "edition",
    }


def edition_body() -> dict:
    edition = editions.active()
    current = editions.current_project()
    return {
        "id": edition.id,
        "productName": edition.product_name,
        "mode": editions.mode(),
        # This run opened as admin without a key — it holds the build secret
        # — so there is nothing to return to and the UI offers no way out.
        # Never true of a shipped package: none of them carries the secret.
        "adminByDefault": editions.opens_as_admin(),
        "views": list(editions.views()),
        # Whether the service key can raise THIS package at all. False only
        # when no key material was built in (see panel.adminkey.secret), so
        # the UI can say "unavailable" instead of silently never asking.
        "adminAvailable": editions.opens_as_admin() or _key_material(),
        # Minting a key needs the secret itself rather than a digest of it,
        # which no shipped package carries.
        "canWriteKey": _can_write_key(),
        "projects": [project_dto(project, current.key)
                     for project in editions.projects()],
    }


def _key_material() -> bool:
    from ... import adminkey                              # noqa: PLC0415
    return adminkey.usable()


def _can_write_key() -> bool:
    from ... import adminkey                              # noqa: PLC0415
    return adminkey.can_write()


def get_edition(_query=None):
    return respond(200, edition_body())


def post_project_select(body):
    """Open another project's device list without restarting.

    Refused while a job is WRITING to devices: an IP run, a configuration
    write or a firmware upload is addressed at the devices of the project
    that was open when it was queued, and swapping the map underneath it
    would point the rest of the run at different hardware.
    """
    key = body.get("key")
    if not isinstance(key, str) or not key.strip():
        return respond(400, {"error": i18n.t("error.projectNotAvailable",
                                             project=key)})
    project = editions.find_project(key)
    if project is None:
        return respond(404, {"error": i18n.t("error.projectNotAvailable",
                                             project=key)})
    if editions.is_extra(project) and not editions.admin():
        return respond(403, {"error": i18n.t("error.adminModeRequired")})
    if not editions.available(project):
        return respond(409, {"error": i18n.t("error.projectNotDelivered",
                                             project=project.label)})

    blocking = next((job for job in jobs.QUEUE.list()
                     if job.kind in WRITING_JOB_KINDS
                     and job.state in (jobs.QUEUED, jobs.RUNNING)), None)
    if blocking is not None:
        return respond(409, {"error": i18n.t("error.projectSwitchBlocked",
                                             title=blocking.title)})

    # A running SCAN is not a reason to refuse — it only reads, and the UI
    # cancels it exactly as it does when the train set changes.
    for job in jobs.QUEUE.list():
        if job.kind == "scan":
            jobs.QUEUE.cancel(job.id)

    from ..lifecycle import switch_project                # noqa: PLC0415
    switch_project(project.key)
    return respond(200, edition_body())


GET = {
    "/api/edition": get_edition,
}

POST = {
    "/api/project/select": post_project_select,
}
