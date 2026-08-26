#!/usr/bin/env python3
"""Writing configuration to devices."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ... import config_sync, jobs, settings
from ...errors import AuthError, user_message
from ..presenters import credentials_for
from .network_prepare import prepare_network
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
        # The same reason as the scan and the assignment run: a write cannot
        # reach a device the computer has no route to. On a fresh start the
        # panel has only prepared set 1's networks, and an operator who
        # changes set and comes straight here — or who has paused the
        # automatic rounds — would otherwise meet "device unreachable" on
        # every row.
        prepare_network(job, inventory)
        # The NVR takes its input channels from the cameras, so it goes
        # last: a channel written before its camera has its stream profile
        # would carry the old one until the next run.
        ordered = sorted(devices, key=lambda device: device.type == "NVR")
        for device in ordered:
            job.add_device_row(device)

        def one(device):
            if job.cancel.is_set():
                job.update_row(device.id, "skipped", i18n.lazy("row.cancelled"))
                return
            job.update_row(device.id, "running", i18n.lazy("job.applying"))
            try:
                # Video equipment is configured by a PROCEDURE, not by a
                # field write: channels, a disk, a buzzer, a restart. One
                # note per device could only say the last of those, so the
                # steps go under the row — the same accordion the IP run
                # uses — and "what did it actually change" has an answer.
                result = config_sync.apply_targets(
                    device, inventory, credentials_for(device), group,
                    report=lambda text, state="done": job.add_step(
                        device.id, text, state))
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

        if not ordered:
            return
        # Cameras run in parallel; the NVR waits for them. Splitting the run
        # in two is what keeps the ordering above meaningful — inside one
        # pool the NVR would start alongside the last cameras.
        cameras = [device for device in ordered if device.type != "NVR"]
        recorders = [device for device in ordered if device.type == "NVR"]
        for batch in (cameras, recorders):
            if not batch:
                continue
            pool = ThreadPoolExecutor(
                max_workers=min(settings.CONFIG_WORKERS, len(batch)))
            try:
                list(pool.map(one, batch))
            finally:
                pool.shutdown(wait=True)

    return body
