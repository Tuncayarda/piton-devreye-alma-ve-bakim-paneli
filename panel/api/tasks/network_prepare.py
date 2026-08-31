#!/usr/bin/env python3
"""Making the computer's network ready, reported onto a job's rows.

Shared by every job that talks to devices: the assignment run, the factory
reset and the full scan all fail the same way when the computer has no route
to the address they are looking for.
"""
from __future__ import annotations

from ... import i18n, jobs, network


def prepare_network(job: jobs.Job, inventory, options=None) -> dict:
    """Give the computer an address on every network this job has to reach.

    A device leaves the factory on 10.1.1.12 whatever set it joins, so on a
    computer sitting at 10.17.1.222/24 every probe of that address failed
    before a packet left the machine — the run reported "device not found" on
    all twelve ports and the address had to be added by hand in system
    settings (see `panel.network`).

    It is done without asking, but never silently: each address added becomes
    a queue row, so a change to the computer's network is on screen. The
    addresses are taken back when the application closes.

    A failure here is a WARNING row, never the job's error. The computer may
    still reach the devices by a route this cannot see, and if it cannot, the
    operation's own message says far more than a guess made here.
    """
    result = network.ensure(inventory, options)
    _report(job, result)
    return result


def prepare_expression(job: jobs.Job, target) -> dict:
    """The same preparation for a job that has a NETWORK, not a DeviceMap.

    The switch-discovery sweep is the one caller: its target is whatever the
    operator typed into the CIDR box. It used to carry its own copy of the
    row emission below — which had already drifted, dropping the
    stranded-route warning that exists precisely because a stranded network
    fails every probe with the same wording as dead hardware.
    """
    result = network.ensure_network(target)
    _report(job, result)
    return result


def _report(job: jobs.Job, result: dict) -> None:
    for record in result["added"]:
        job.add_row(f"net:{record['ip']}",
                    f"{record['ip']}/{record['prefix']}", state="done",
                    note=i18n.lazy("job.networkAddressAdded",
                                   adapter=record["adapter"]),
                    ip=record["ip"])
    if result.get("needsAdapter"):
        # Its own row, and its own wording: the panel did not fail here, it
        # declined to guess which adapter reaches the switch. The Network
        # screen is where that gets answered.
        job.add_row("net:adapter", i18n.lazy("job.networkNoAdapter"),
                    state="warning", note=i18n.lazy("job.networkPickAdapter"))
    # Read back, not prepared: a network whose route still names an address
    # this computer no longer holds. Every device in it then fails instantly,
    # with the same wording as a dead device — so it is said out loud here,
    # before the rows that look like broken hardware start arriving.
    for broken in network.broken_networks():
        job.add_row(f"net:stranded:{broken['network']}", broken["network"],
                    state="warning",
                    note=i18n.lazy("job.networkRouteStranded",
                                   address=broken["source"],
                                   adapter=broken["interface"]))
    for failure in result["failed"]:
        job.add_row(f"net:{failure['network'] or 'adapter'}",
                    failure["network"] or i18n.lazy("job.networkNoAdapter"),
                    state="warning",
                    note=i18n.lazy("job.networkAddressFailed",
                                   detail=failure["error"]))
