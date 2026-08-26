#!/usr/bin/env python3
"""Version, project metadata, device list and the job queue."""
from __future__ import annotations

from ... import i18n, jobs, settings, status
from ...inventory import catalog
from ...probe import reader
from ...system import files
from ..presenters import (credentials_for, device_dto, find_device,
                          inventory_for, state_body)
from ..response import respond
from ..tasks import scan_task
from .helpers import single


def get_version(query):
    """Version and product name — and nothing that changes during a session.

    This is the liveness probe `app.http_ready()` polls before it opens a
    browser, so it must answer before the panel state is ready. Anything that
    has to be re-read after a mode or project change belongs on
    `/api/edition` instead.
    """
    return respond(200, {
        "version": settings.APP_VERSION, "name": i18n.t("app.name"),
    })


def get_language(_query=None):
    """The catalogue the UI renders itself with."""
    return respond(200, i18n.payload())


def post_language(body):
    """Switch language. The whole catalogue comes back with the answer.

    The UI redraws from what it gets here, so there is no window where half
    the screen is in the old language.
    """
    wanted = body.get("language")
    if wanted not in i18n.LANGUAGES:
        return respond(400, {"error": i18n.t("error.unknownLanguage")})
    i18n.use(wanted)
    return respond(200, i18n.payload())


def get_project(query):
    inventory = inventory_for(single(query, "set", 1))
    return respond(200, {
        "project": inventory.project,
        "setNo": inventory.set_no,
        # The set number is typed in; the UI gets the accepted range rather
        # than a ready-made list.
        "setMin": settings.SET_MIN,
        "setMax": settings.SET_MAX,
        "file": inventory.source.name,
        "total": len(inventory.devices),
        "switchCount": len(inventory.switches()),
        # The screen never sees a message key: categories and groups are
        # rendered here, where the language is known. `name` on a group stays
        # untouched — it is the identifier the UI sends back.
        "categories": [{**entry, "name": i18n.t(entry["nameKey"]),
                        "types": i18n.t(entry["types"])}
                       for entry in catalog.CATEGORIES],
        "groups": [{**entry, "label": i18n.t(entry.get("labelKey")
                                             or entry["name"])}
                   for entry in catalog.GROUPS],
        "readMethods": catalog.READ_METHODS,
        "piscuIp": inventory.piscu_ip(),
    })


def get_state(query):
    return respond(200, state_body(inventory_for(single(query, "set", 1))))


def get_locked(query):
    inventory = inventory_for(single(query, "set", 1))
    view = jobs.view_for(inventory.set_no)
    listed = []
    for device in inventory.devices:
        result = view.get(device.id)
        if result is None or result.verification != status.AUTH_REQUIRED:
            continue
        listed.append({
            **device.dto(),
            "credentialGroup": reader.credential_group(device) or "",
            "detail": result.detail,
            "readMethodCode": catalog.READ_METHODS.get(
                device.read_method, {}).get("code", ""),
            "hasCredentials": credentials_for(device) is not None,
        })
    return respond(200, {"setNo": inventory.set_no, "devices": listed})


def get_jobs(query):
    return respond(200, {"jobs": [job.dto(rows=False)
                                  for job in jobs.QUEUE.list()]})


def get_job(query):
    job = jobs.QUEUE.find(str(single(query, "id", "")))
    if job is None:
        return respond(404, {"error": i18n.t("error.jobNotFound")})
    return respond(200, job.dto())


def get_device(query):
    inventory = inventory_for(single(query, "set", 1))
    device = find_device(inventory, single(query, "id"))
    result = jobs.view_for(inventory.set_no).get(device.id)
    return respond(200, {
        **device_dto(device, result),
        "readMethodInfo": catalog.READ_METHODS.get(device.read_method, {}),
        "piscuIp": inventory.piscu_ip(),
    })


def post_scan(body):
    inventory = inventory_for(body.get("set"))
    # `auto`: the UI's minute-long discovery round. It does the same work;
    # it is only flagged so it does not pile up in the queue history and can
    # be told apart from a manually started scan.
    auto = body.get("auto") is True
    kind = i18n.t("job.scanAutomatic" if auto else "job.scanFull")
    job = jobs.Job("scan", i18n.lazy("job.scanTitle", kind=kind,
                                     set=inventory.set_no),
                   inventory.set_no, key=f"scan:{inventory.set_no}", auto=auto)
    for device in inventory.devices:
        job.add_device_row(device)
    job, is_new = jobs.QUEUE.submit(job, scan_task(inventory))
    return respond(200 if is_new else 202,
                   {**job.dto(rows=False), "new": is_new})


def post_job_cancel(body):
    job_id = body.get("id")
    if not isinstance(job_id, str):
        return respond(400, {"error": i18n.t("error.jobIdRequired")})
    cancelled = jobs.QUEUE.cancel(job_id)
    return respond(200 if cancelled else 404, {"cancelled": cancelled})


def post_job_remove(body):
    job_id = body.get("id")
    if not isinstance(job_id, str):
        return respond(400, {"error": i18n.t("error.jobIdRequired")})
    removed = jobs.QUEUE.remove(job_id)
    return respond(200 if removed else 409,
                   {"removed": removed,
                    "error": None if removed
                    else i18n.t("error.runningJobNotDeletable")})


def post_job_file(body):
    # The client does not send the path to open: the panel opens the path it
    # wrote into the job record itself. Otherwise this endpoint would mean
    # "open any file on this machine".
    job_id, row_key = body.get("id"), body.get("row")
    if not isinstance(job_id, str) or not isinstance(row_key, str):
        return respond(400, {"error": i18n.t("error.jobAndRowRequired")})
    job = jobs.QUEUE.find(job_id)
    target = job.file_path(row_key) if job else ""
    if not target:
        return respond(404, {"error": i18n.t("error.rowHasNoFile")})
    try:
        files.open_path(target, reveal=bool(body.get("reveal")))
    except FileNotFoundError:
        return respond(404, {
            "error": i18n.t("error.fileMovedOrDeleted")})
    except RuntimeError as exc:
        return respond(500, {"error": str(exc)})
    return respond(200, {"opened": True})


GET = {
    "/api/version": get_version,
    "/api/language": get_language,
    "/api/project": get_project,
    "/api/devices": get_state,
    "/api/state": get_state,
    "/api/locked": get_locked,
    "/api/jobs": get_jobs,
    "/api/job": get_job,
    "/api/device": get_device,
}

POST = {
    "/api/language": post_language,
    "/api/scan": post_scan,
    "/api/job/cancel": post_job_cancel,
    "/api/job/remove": post_job_remove,
    "/api/job/file": post_job_file,
}
