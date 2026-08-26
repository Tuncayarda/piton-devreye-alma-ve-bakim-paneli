#!/usr/bin/env python3
"""Installing software on devices."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ... import firmware, jobs, settings
from ...errors import AuthError, user_message
from ..presenters import credentials_for
from .network_prepare import prepare_network
from ... import i18n


def firmware_task(inventory, devices):
    """Installs run in parallel.

    The devices are independent: each takes its own file and waits out its own
    reboot. Doing that serially stacked the waits on a 12-intercom set. How
    many run at once is `settings.FIRMWARE_WORKERS` (default 4).
    """
    def body(job: jobs.Job):
        # The same reason as the scan and the assignment run: a write cannot
        # reach a device the computer has no route to. On a fresh start the
        # panel has only prepared set 1's networks, and an operator who
        # changes set and comes straight here — or who has paused the
        # automatic rounds — would otherwise meet "device unreachable" on
        # every row.
        prepare_network(job, inventory)
        for device in devices:
            job.add_device_row(device)

        def one(device):
            # Cancellation is checked BEFORE each device: the queued ones are
            # never touched, while an install already under way runs to its
            # own timeout — a firmware write cut in half leaves a device
            # unusable.
            if job.cancel.is_set():
                job.update_row(device.id, "skipped", i18n.lazy("row.cancelled"))
                return
            # Which file went out is on the row: a file can be chosen per
            # device, so "installed" alone is not enough.
            file_name = firmware.selection_for(
                device.id, set_no=inventory.set_no)["name"]
            job.update_row(device.id, "running",
                           i18n.lazy("job.installing", file=file_name))
            try:
                result = firmware.install(device, credentials_for(device),
                                          set_no=inventory.set_no)
                job.update_row(device.id, "done",
                               i18n.lazy("job.installed", file=file_name,
                                         version=result["current"]))
            except AuthError as exc:
                job.update_row(device.id, "auth", user_message(exc))
            except Exception as exc:
                job.update_row(device.id, "failed", user_message(exc))

        pool = ThreadPoolExecutor(
            max_workers=max(1, min(settings.FIRMWARE_WORKERS, len(devices))))
        try:
            list(pool.map(one, devices))
        finally:
            pool.shutdown(wait=True)

    return body
