#!/usr/bin/env python3
"""The checklist preview and its Excel export."""
from __future__ import annotations

from ... import checklist, jobs
from ..presenters import inventory_for
from ..response import respond
from ..tasks import checklist_export_task
from .helpers import single
from ... import i18n


def get_checklist(query):
    inventory = inventory_for(single(query, "set", 1))
    view = jobs.view_for(inventory.set_no)
    return respond(200, {
        **checklist.build_preview(inventory, view.all()),
        "setNo": inventory.set_no,
        "counts": view.counts(),
        "lastScan": view.last_scan,
    })


def post_export(body):
    inventory = inventory_for(body.get("set"))
    job = jobs.Job("checklist", i18n.lazy("job.checklist",
                                          set=inventory.set_no),
                   inventory.set_no, key=f"checklist:{inventory.set_no}")
    job, is_new = jobs.QUEUE.submit(job, checklist_export_task(inventory))
    return respond(200 if is_new else 202,
                   {**job.dto(rows=False), "new": is_new})


GET = {
    "/api/checklist": get_checklist,
}

POST = {
    "/api/checklist/export": post_export,
}
