#!/usr/bin/env python3
"""The full scan job."""
from __future__ import annotations

from ... import jobs
from ...probe import reader
from ...telemetry import TelemetrySnapshot
from ..presenters import collect_telemetry, credentials_for, store_telemetry
from .network_prepare import prepare_network
from ... import i18n


def scan_task(inventory):
    def body(job: jobs.Job):
        # A scan of a set whose network the computer is not on finds nothing
        # at all, and the empty result looks like dead hardware. Telemetry is
        # the first thing read and it goes to the PISCU's own address, so this
        # comes before it.
        prepare_network(job, inventory, None)
        # Collecting telemetry takes seconds during which no device row moves.
        # The queue shows what is being waited on; otherwise the scan looks
        # frozen.
        job.add_row("telemetry", i18n.lazy("job.telemetryRow"),
                    state="running",
                    note=i18n.lazy("job.readingPiscu",
                               broker=inventory.piscu_ip() or "PISCU"),
                    ip=inventory.piscu_ip() or "")
        try:
            snapshot = collect_telemetry(inventory)
        except Exception:
            snapshot = TelemetrySnapshot(inventory.piscu_ip())
            snapshot.error = i18n.t("job.telemetryFailed")
        # Light refresh rounds reuse this snapshot; they never collect it.
        store_telemetry(inventory.set_no, snapshot)
        job.add_row(
            "telemetry", i18n.lazy("job.telemetryRow"),
            state="failed" if snapshot.error else "done",
            note=snapshot.error or i18n.lazy("job.telemetryRecords",
                                             count=len(snapshot.records)),
            ip=inventory.piscu_ip() or "")

        piscu_ip = inventory.piscu_ip()

        def read(device):
            return reader.read_device(device,
                                      credentials=credentials_for(device),
                                      telemetry=snapshot,
                                      expected_ntp=piscu_ip,
                                      pbx_ip=piscu_ip)

        jobs.sweep_devices(job, inventory.devices, read)

    return body
