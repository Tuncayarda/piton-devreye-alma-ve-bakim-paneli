#!/usr/bin/env python3
"""Small shared helpers for route handlers."""
from __future__ import annotations

from ... import jobs
from ..response import ApiResponse, respond


def submit(job: jobs.Job, task) -> ApiResponse:
    """Queue a job and answer the way every job endpoint answers.

    200 = a new job; 202 = the same work was already queued or running and
    THAT job is returned (the queue de-duplicates on `job.key`, so a double
    click never starts a second scan — see jobs.queue.submit). Nine
    endpoints used to spell these three lines out separately, which left
    the 202 convention discoverable only by reading all nine.
    """
    job, is_new = jobs.QUEUE.submit(job, task)
    return respond(200 if is_new else 202,
                   {**job.dto(rows=False), "new": is_new})


def single(query: dict, name: str, default=None):
    """One value out of a parsed query string."""
    value = query.get(name, default)
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return value


def name_list(raw) -> list[str]:
    """Accept a group name as a string or a list, return a list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part for part in raw.split(",") if part.strip()]
    return [str(part) for part in raw if str(part).strip()]


def first_switch_id(inventory, requested=None) -> str:
    if requested:
        return str(requested)
    switches = inventory.switches()
    return switches[0].id if switches else ""
