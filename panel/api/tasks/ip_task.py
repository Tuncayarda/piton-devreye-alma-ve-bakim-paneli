#!/usr/bin/env python3
"""The IP assignment run and the factory-reset helper."""
from __future__ import annotations

from ... import credentials as credential_store
from ... import ip_assign, jobs
from ...errors import AuthError
from ...system import files
from .network_prepare import prepare_network
from ... import i18n


def _short_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:160]


def _identity_rows(job, audit: dict) -> None:
    """Write the identity check's outcome onto the port rows.

    Only problem ports are touched: a correct one already reads "done", and
    marking every port a second time drowned the rows in noise.
    """
    for row in audit["rows"]:
        key = ip_assign.port_key(row["port"])
        who = ", ".join(
            i18n.t("ip.withExtension",
                   name=found["name"] or i18n.t("ip.unknownDevice"),
                   extension=found["extension"])
            if found["extension"]
            else (found["name"] or i18n.t("ip.unknownDevice"))
            for found in row["found"]) or i18n.t("ip.noAnswer")
        if row["state"] in ("wrong", "conflict"):
            job.update_row(key, "failed", i18n.lazy(
                "ip.identityWrong" if row["state"] == "wrong"
                else "ip.identityConflict", ip=row["targetIp"], who=who))
            job.add_step(key, i18n.lazy("ip.identityCheck", who=who), "failed")
        elif row["state"] == "correct":
            job.add_step(key, i18n.lazy("ip.identityOk",
                                        extension=row["expectedExtension"]),
                         "done")


def _identity_error(counts: dict) -> str:
    """Summary of ports written to the wrong device — the worst outcome.

    Different from "port could not be completed", and worse: the run believes
    it finished while the devices are mixed up.
    """
    parts = []
    if counts["wrong"]:
        parts.append(i18n.t("ip.wrongDeviceCount", count=counts["wrong"]))
    if counts["conflict"]:
        parts.append(i18n.t("ip.conflictCount", count=counts["conflict"]))
    return i18n.t("ip.identityError", parts=i18n.t("ip.and").join(parts))


def _run_summary_error(counts: dict, code: int) -> str:
    """What the run failed to finish — in one sentence, with port counts.

    A partly successful run is common: ten of twelve ports complete, two do
    not. That is what the user needs to see, not the script's exit code. The
    reasons are on the port rows and in the log file.
    """
    incomplete = counts.get("failed", 0) + counts.get("skipped", 0)
    ok, total = counts.get("ok", 0), counts.get("total", 0)
    if not incomplete:
        return i18n.t("ip.exitCode", code=code)
    where = i18n.t("ip.whereReasons")
    if ok:
        return i18n.t("ip.partlyDone", ok=ok, total=total,
                      incomplete=incomplete, where=where)
    return i18n.t("ip.noneDone", incomplete=incomplete, where=where)


def ip_assign_task(inventory, switch_id, ports, protected, groups, options):
    """The IP assignment run — progress is reported PER PORT.

    Every output line of the script used to enter the queue as a "step": two
    hundred unreadable lines, and since those rows do not count towards the
    counters, 0% from start to finish. Now there is one row per port, the
    run's real unit of work (see ip_assign.RunProgress), and the raw output
    goes to a log file that opens from a single queue row.
    """
    def body(job: jobs.Job):
        # If the script cannot reopen the ports, devices stay dark in the
        # field. That is not a warning to lose among queue rows; it becomes
        # the job's error so the user sees they must open them by hand.
        left_closed = {"value": False}
        # Before anything else: the run cannot find a device it has no route
        # to, and the factory address is on another network by design.
        prepare_network(job, inventory, options)
        # The rows say where each port is going, so they have to be built
        # with the same two sets and mask the run will actually use.
        plan = ip_assign.build_plan(
            inventory, groups, ports, switch_id,
            target_prefix=ip_assign.effective_prefix(
                options.get("targetPrefix")),
            source_set=int(options.get("sourceSet") or 0),
            target_set=int(options.get("targetSet") or 0))
        log_file = files.log_path(f"ip-assign-set{inventory.set_no}")
        log = log_file.open("w", encoding="utf-8")

        progress = ip_assign.RunProgress(
            job, plan["rows"],
            log=lambda line: (log.write(line + "\n"), log.flush()))

        def emit(text: str):
            # The script says so itself with an event; matching its prose
            # would break the moment that sentence is reworded.
            event = ip_assign.parse_event(text.strip())
            if event and event.get("event") == "ports_left_closed":
                left_closed["value"] = True
            progress.line(text)

        try:
            # The cancel flag reaches the script: when the user stops the run
            # the script goes through its own Ctrl-C path and reopens the PoE
            # ports.
            code = ip_assign.run(inventory, switch_id, ports, emit,
                                 protected=protected, groups=groups,
                                 options=options,
                                 cancelled=job.cancel.is_set)
        finally:
            progress.finish()
            log.close()
            # The raw output is not lost, just moved out of the way: it stays
            # as an openable file rather than a wall of rows.
            job.add_row("log", log_file.name, state="done",
                        note=i18n.lazy("job.rawOutput"), path=str(log_file))

        # The run is over; but "port completed" only means "the target
        # address answered". Whether the answer came from the RIGHT device is
        # checked separately: the script picks a device by guessing at uptime,
        # so writing to the wrong one is possible and has happened in the
        # field (see ip_assign.audit_identities).
        audit = None
        # The identity audit reads an Intercom's HTTP settings and compares
        # its SIP extension. A Compartment LCD is identified inside its ADB
        # runner by serial + switch port; sending it through this HTTP audit
        # would turn a successful Android run into a false warning.
        intercom_groups = [name for name in groups if name == "Intercom"]
        intercom_ports = []
        if intercom_groups:
            intercom_plan = ip_assign.build_plan(
                inventory, intercom_groups, ports, switch_id)
            intercom_ports = [row["port"] for row in intercom_plan["rows"]
                              if row.get("actionable")]
        if not job.cancel.is_set() and intercom_ports:
            try:
                audit = ip_assign.audit_identities(
                    inventory, switch_id, intercom_ports,
                    intercom_groups, options)
            except Exception as exc:
                job.add_row("identity", i18n.lazy("job.identityUnverified"),
                            state="warning", note=_short_error(exc))
            else:
                _identity_rows(job, audit)

        switch = inventory.find(switch_id)
        if left_closed["value"]:
            job.error = i18n.lazy("ip.portsLeftClosed",
                                  switch=switch.ip if switch else "")
        elif audit and (audit["counts"]["wrong"] or audit["counts"]["conflict"]):
            job.error = _identity_error(audit["counts"])
        elif code and code != 130:      # 130 = the user stopped it
            # "The script exited with code 1" told the user nothing: the same
            # sentence appeared whether the run finished most ports or none.
            # The exit code only ever means "something is missing"; WHAT is
            # missing lives on the rows, and its summary goes here.
            job.error = _run_summary_error(job.counts(), code)

    return body


def lcd_manual_task(inventory, switch_id, port, protected, options):
    """Write one typed address to the display on one switch port.

    The bench flow (see ip_assign.lcd_runner.run_manual). It reports through
    the same per-port queue rows as the ordinary run — one row — so the steps
    the operator reads while a port is worked on are identical.
    """
    def body(job: jobs.Job):
        prepare_network(job, inventory, options)
        switch = inventory.find(switch_id)
        if switch is None or switch.type != "Switch":
            raise ValueError(i18n.t("error.switchNotFound"))
        ip_assign.assert_not_protected([port], protected)
        account = credential_store.lookup(switch.id, switch.ip,
                                          group="switch")
        if not account:
            raise AuthError(i18n.t("error.noSwitchCredentials",
                                   switch=switch.name))

        target_ip = str(options.get("targetIp") or "")
        rows = [{"port": port, "name": i18n.t("ip.lcdManualRowName"),
                 "targetIp": target_ip, "actionable": True}]
        log_file = files.log_path(f"lcd-assign-set{inventory.set_no}")
        log = log_file.open("w", encoding="utf-8")
        progress = ip_assign.RunProgress(
            job, rows, log=lambda line: (log.write(line + "\n"), log.flush()))
        left_closed = {"value": False}

        def emit(text: str):
            event = ip_assign.parse_event(text.strip())
            if event and event.get("event") == "ports_left_closed":
                left_closed["value"] = True
            progress.line(text)

        try:
            code = ip_assign.run_lcd_manual(
                inventory, switch, port, account, emit, options,
                cancelled=job.cancel.is_set)
        finally:
            progress.finish()
            log.close()
            job.add_row("log", log_file.name, state="done",
                        note=i18n.lazy("job.rawOutput"), path=str(log_file))

        if left_closed["value"]:
            job.error = i18n.lazy("ip.portsLeftClosed", switch=switch.ip)
        elif code and code != 130:
            job.error = _run_summary_error(job.counts(), code)

    return body


def factory_reset_task(inventory, switch_id, ports, groups, options):
    """Test flow: put the selected devices back on the factory address.

    Rows, steps and percentage are written by the operation itself (see
    ip_assign.FactoryResetProgress); only the summary is turned into an error
    here.
    """
    def body(job: jobs.Job):
        # Same reason as the assignment run: this operation moves devices ONTO
        # the factory address and then confirms them there, so the computer
        # needs to be able to reach it.
        prepare_network(job, inventory, options)
        summary = ip_assign.reset_to_factory(
            inventory, switch_id, ports, groups, job,
            options=options, cancelled=job.cancel.is_set)
        job.error = _factory_reset_error(summary)

    return body


def _factory_reset_error(summary: dict) -> str | None:
    """Is there anything in the factory-reset summary that fails the job?

    "No answer on its address" is NOT a failure on its own: run the operation
    again and most devices are already on the factory address with nobody
    answering the old ones. The failure is a device STAYING on its old
    address, which the final check catches separately.
    """
    if summary.get("stopped"):
        return None
    if summary.get("failed"):
        return i18n.t("ip.factoryResetFailed", count=summary["failed"],
                      factory=summary["factoryIp"])
    if (not summary.get("written") and summary.get("skipped")
            and summary.get("factoryAnswers") is False):
        # Nothing answers on the old addresses or the factory one: the devices
        # are somewhere the computer cannot see. That really is a failure.
        return (i18n.t("ip.nothingFound", factory=summary["factoryIp"])
                + ("" if summary.get("arpFlush")
                   else i18n.t("ip.nothingFoundArp")))
    if summary.get("skipped") and not summary.get("arpFlush"):
        # With ARP unflushable, an address that does not answer does not mean
        # "nobody is there": devices sharing an address appear in turn. The
        # result may be incomplete and only permission can settle it.
        return i18n.t("ip.skippedNoArp", count=summary["skipped"])
    return None
