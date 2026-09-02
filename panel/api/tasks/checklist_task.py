#!/usr/bin/env python3
"""Producing the checklist workbook.

THE EXPORT READS RICHER THAN THE SCAN, where the two differ. On GDM the
scan listens to ALFA/DeviceMap (see `inventory/profiles/gdm.py`), which
carries version, serial and uptime — and none of the protocol-specific
columns the workbook has: an Intercom's volumes and SIP numbers, a display's
time zone, a camera's time check. Those lived in the direct readers the
scan no longer runs. So the export, and only the export, re-reads such
devices over their own protocol and lays the answers over the broker
record; the screen keeps showing the broker's picture throughout.

The fallback is the record, not an empty row: a device that answers the
broker but not its own protocol still goes into the workbook with what the
broker knows, exactly as it did before the re-read existed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ... import checklist, jobs, settings, status
from ...probe import reader
from ..presenters import (cached_telemetry, collect_telemetry,
                          credentials_for, probe_context, store_telemetry)
from ... import i18n


def _needs_rich_read(device) -> bool:
    """Does the workbook know more questions than this device's scan asked?

    True only where the probe was redirected away from the device itself
    (GDM's broker listening) AND the read method is a direct protocol the
    reader can still speak. Everything else was already read as richly as
    it can be.
    """
    probe = getattr(device, "probe_method", "")
    return bool(probe and probe != device.read_method
                and device.read_method in ("kyland", "http", "isapi", "adb"))


def _merged(stored, fresh):
    """The workbook's row: the richer read, on top of the broker record.

    A fresh OK wins, carrying forward any stored field it did not produce
    itself — ISAPI has no uptime, the broker record does, and the row
    should hold both. A fresh failure changes nothing: the stored result
    (when there is one) is what the operator already trusts on screen.
    """
    if fresh.state != status.OK:
        return stored or fresh
    if stored is not None:
        fields = dict(stored.fields)
        fields.update({key: value for key, value in fresh.fields.items()
                       if value not in (None, "")})
        fresh.fields = fields
    return fresh


def _enrich(job: jobs.Job, inventory, results: dict) -> None:
    """Re-read the broker-probed devices for the workbook, in place."""
    devices = [device for device in inventory.devices
               if device.active and _needs_rich_read(device)]
    if not devices:
        return
    # The ADB reads complete their SIP extension from telemetry, the same
    # way the scan's do. The cache normally holds the last scan's snapshot;
    # collected once here when it does not — and only when a display is
    # among the re-reads, because it is the one reader that asks for it.
    snapshot = cached_telemetry(inventory.set_no)
    if snapshot is None and any(d.read_method == "adb" for d in devices):
        try:
            snapshot = collect_telemetry(inventory)
            store_telemetry(inventory.set_no, snapshot)
        except Exception:
            snapshot = None
    context = probe_context(inventory)

    def one(device):
        if job.cancel.is_set():
            job.update_row(device.id, "skipped", i18n.lazy("row.cancelled"))
            return
        job.update_row(device.id, "running",
                       i18n.lazy("row.readingForWorkbook"))
        fresh = reader.read_device(device,
                                   credentials=credentials_for(device),
                                   telemetry=snapshot,
                                   method=device.read_method, **context)
        stored = results.get(device.id)
        results[device.id] = _merged(stored, fresh)
        if fresh.state == status.OK:
            job.update_row(device.id, "done", fresh.detail)
        elif stored is not None:
            # The workbook falls back to the broker record; the row says so
            # rather than going red over a book that will still be filled.
            job.update_row(device.id, "done",
                           i18n.lazy("row.workbookFromBroker"))
        else:
            job.update_row(device.id, "failed", fresh.detail)

    for device in devices:
        job.add_row(device.id, device.name, state="queued",
                    ip=device.ip, counted=True)
    pool = ThreadPoolExecutor(max_workers=settings.SCAN_WORKERS)
    try:
        list(pool.map(one, devices))
    finally:
        pool.shutdown(wait=True)


def checklist_export_task(inventory):
    def body(job: jobs.Job):
        results = dict(jobs.view_for(inventory.set_no).all())
        _enrich(job, inventory, results)
        path = checklist.export(inventory, results)
        job.add_row("workbook", path.name, state="done", note=str(path),
                    path=str(path))

    return body
