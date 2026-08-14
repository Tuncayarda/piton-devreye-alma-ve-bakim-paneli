#!/usr/bin/env python3
"""Writing configuration to devices."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ... import config_sync, jobs, settings
from ...errors import AuthError, user_message
from ..presenters import credentials_for
from ... import i18n


def config_task(inventory, devices, group: str = ""):
    """Configuration writes — devices are processed IN PARALLEL.

    Serial writes stacked the waits end to end: every device has a read, a
    write and a verification read, and a device that gets SIP written also
    reboots. On a twelve-intercom set that alone meant minutes — most of it
    network waiting, not panel work.

    The width matches firmware (`settings.CONFIG_WORKERS`) and is narrower
    than scanning: a write can reboot a device, and blacking out everything
    behind one switch at once also strains the person standing next to it.
    """
    def body(job: jobs.Job):
        for device in devices:
            job.add_device_row(device)

        def one(device):
            if job.cancel.is_set():
                job.update_row(device.id, "skipped", i18n.lazy("row.cancelled"))
                return
            job.update_row(device.id, "running", i18n.lazy("job.applying"))
            try:
                result = config_sync.apply_targets(
                    device, inventory, credentials_for(device), group)
                written = result.get("writtenFields") or []
                # A device already in agreement gets no request; the row must
                # say so, otherwise a row reading "written" hides the fact
                # that no request was made at all.
                job.update_row(device.id, "done", i18n.lazy(
                    "config.writtenRestarted" if result.get("rebooted")
                    else "config.written", fields=", ".join(written))
                    if written else i18n.lazy("config.alreadyMatches"))
            except AuthError as exc:
                job.update_row(device.id, "auth", user_message(exc))
            except Exception as exc:
                job.update_row(device.id, "failed", user_message(exc))

        if not devices:
            return
        pool = ThreadPoolExecutor(
            max_workers=min(settings.CONFIG_WORKERS, len(devices)))
        try:
            list(pool.map(one, devices))
        finally:
            pool.shutdown(wait=True)

    return body
