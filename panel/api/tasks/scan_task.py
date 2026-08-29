#!/usr/bin/env python3
"""The full scan job."""
from __future__ import annotations

from ... import jobs
from ...editions import runtime as editions
from ...probe import reader
from ...telemetry import TelemetrySnapshot
from ..presenters import collect_telemetry, credentials_for, store_telemetry
from .network_prepare import prepare_network
from ... import i18n


def scan_task(inventory):
    def body(job: jobs.Job):
        # The broker, the clock source and the PBX, which are roles rather
        # than devices: on most projects all three are the single PISCU, and
        # on Gaziray and GDM none of them is (see
        # `panel.editions.catalogue.Project.broker`).
        broker = editions.broker_ip(inventory)
        expected_ntp = editions.ntp_ip(inventory)
        pbx = editions.pbx_ip(inventory)
        # How far this project reaches, from the DeviceMap. A camera whose
        # own mask does not cover it cannot see the rest of the train.
        span = str(inventory.span(broker) or "")

        # A scan of a set whose network the computer is not on finds nothing
        # at all, and the empty result looks like dead hardware. Telemetry is
        # the first thing read and it goes to the broker's address, so this
        # comes before it.
        prepare_network(job, inventory, None)
        # Collecting telemetry takes seconds during which no device row moves.
        # The queue shows what is being waited on; otherwise the scan looks
        # frozen.
        job.add_row("telemetry", i18n.lazy("job.telemetryRow"),
                    state="running",
                    note=i18n.lazy("job.readingPiscu",
                               broker=broker or "PISCU"),
                    ip=broker or "")
        try:
            snapshot = collect_telemetry(inventory)
        except Exception:
            snapshot = TelemetrySnapshot(broker)
            snapshot.error = i18n.t("job.telemetryFailed")
        # Light refresh rounds reuse this snapshot; they never collect it.
        store_telemetry(inventory.set_no, snapshot)
        job.add_row(
            "telemetry", i18n.lazy("job.telemetryRow"),
            state="failed" if snapshot.error else "done",
            note=snapshot.error or i18n.lazy("job.telemetryRecords",
                                             count=len(snapshot.records)),
            ip=broker or "")

        def read(device):
            return reader.read_device(device,
                                      credentials=credentials_for(device),
                                      telemetry=snapshot,
                                      expected_ntp=expected_ntp,
                                      pbx_ip=pbx,
                                      project_span=span)

        jobs.sweep_devices(job, inventory.devices, read)

    return body
