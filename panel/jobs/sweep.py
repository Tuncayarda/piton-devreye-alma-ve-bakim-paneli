#!/usr/bin/env python3
"""Reading a list of devices in parallel while updating job rows."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from .. import settings, status
from .job import (Job, ROW_AUTH, ROW_DONE, ROW_FAILED, ROW_SKIPPED, RUNNING)
from .view import next_generation, view_for
from .. import i18n

_ROW_STATE = {
    status.OK: ROW_DONE,
    status.AUTH: ROW_AUTH,
    status.FAILED: ROW_FAILED,
    status.UNKNOWN: ROW_SKIPPED,
}


def sweep_devices(job: Job, devices, read, workers: int | None = None) -> None:
    """Read the devices in parallel, updating job rows live.

    `read(device) -> ProbeResult` — it does not know which protocol is used;
    the probe layer decides.

    Cancellation is checked BEFORE each device: the remaining ones are never
    touched, while the single in-flight request may run to its own timeout.
    """
    pool = ThreadPoolExecutor(max_workers=workers or settings.SCAN_WORKERS)
    view = view_for(job.set_no)
    # Captured with the view: the object survives a project switch, but the
    # results this sweep is about to produce belong to the device list open
    # NOW. A clear() in between bumps the epoch and the writes below become
    # no-ops instead of the old project's rows in the new project's view.
    epoch = view.epoch

    def one(device):
        if job.cancel.is_set():
            job.update_row(device.id, ROW_SKIPPED, i18n.lazy("row.cancelled"))
            return
        job.update_row(device.id, RUNNING, i18n.lazy("row.reading"))
        generation = next_generation()
        result = read(device)
        result.generation = generation
        stored = view.write(device.id, result, epoch=epoch)
        note = result.detail
        if not stored:
            note = i18n.lazy("row.newerResult", note=note)
        job.update_row(device.id, _ROW_STATE[result.state], note)

    try:
        list(pool.map(one, devices))
    finally:
        pool.shutdown(wait=True)
    # Only a sweep that RAN dates the view. A cancelled one skipped its
    # remaining devices, and `lastScan` is what the checklist staleness
    # banner trusts — stamping here would make data the scan never touched
    # look freshly verified.
    if not job.cancel.is_set():
        view.last_scan = time.time()
