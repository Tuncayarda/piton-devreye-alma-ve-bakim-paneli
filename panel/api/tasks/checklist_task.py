#!/usr/bin/env python3
"""Producing the checklist workbook."""
from __future__ import annotations

from ... import checklist, jobs


def checklist_export_task(inventory):
    def body(job: jobs.Job):
        results = jobs.view_for(inventory.set_no).all()
        path = checklist.export(inventory, results)
        job.add_row("workbook", path.name, state="done", note=str(path),
                    path=str(path))

    return body
