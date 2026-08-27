#!/usr/bin/env python3
"""Turning the script's output into queue progress.

The script prints line by line and every one of those lines used to become a
queue "step": a two-hundred-line pile, a percentage stuck at 0 (step rows do
not count towards the counters) and no way to see which phase was running.

THE SCRIPT'S FLOW WAS NOT REWRITTEN. It is field-proven, so its behaviour is
left alone; only its *reporting* changed. It now prints one machine-readable
event per meaningful transition (see `field_scripts/intercom_ip_assign.py`,
`emit_event`), and that event stream — not the prose around it — is the
contract between the two files.

The prose used to be the contract, which made a reworded sentence enough to
break the panel's progress bar silently. Nothing here matches free text any
more: every state change, phase and percentage comes from an event.

Prose lines are not lost. They go to the run log, and the indented detail
lines under a running port also become that port's step history — text the
user reads, never something the code branches on.

The run's real unit of work is a PORT, so each target port is one row and the
percentage is phase-weighted (see PHASES).
"""
from __future__ import annotations

import json
from .. import i18n

# The event line marker, mirroring EVENT_PREFIX in the field script.
EVENT_PREFIX = "@EVT "

# Written but not yet confirmed in the final pass. Deliberately not "done":
# the device reset, and whether it answers on its new address is settled in
# the verification pass. It does not count as a success.
WRITTEN = "written"


# ── phases ──
# The whole run and each phase's share of the bar. The shares come from field
# measurements, not duration guesses: on a twelve-port run the port pass takes
# minutes and the final verification about fifteen seconds. They must total
# 1.00.
#
# Phases are counted explicitly because the percentage used to be only
# "finished ports / total ports", and since ports close in the summary table
# at the end rather than along the way, the bar sat at 0% and hit 100% in the
# last second.
PHASES = (
    ("prepare", "phase.prepare", 0.05),
    ("baseline", "phase.baseline", 0.07),
    ("assign", "phase.assign", 0.70),
    ("restore", "phase.restore", 0.04),
    ("verify", "phase.verify", 0.14),
)


def phase_table(phases):
    """Derive the bar arithmetic from a phase list.

    Returns: (order, labels, shares, starts). A phase's "start" is where it
    begins on the bar — the sum of the shares before it.
    """
    order = [name for name, _label, _share in phases]
    labels = {name: key for name, key, _share in phases}
    shares = {name: share for name, _label, share in phases}
    starts, total = {}, 0.0
    for name, _label, share in phases:
        starts[name] = total
        total += share
    return order, labels, shares, starts


_ORDER, _LABEL, _SHARE, _START = phase_table(PHASES)

# Steps inside one port: the event's step code, how much of the port is done
# at that point, and what the user is told. The port pass is 70% of the bar; a
# single port can take a minute, so the bar must move within a port too.
PORT_STEPS = (
    ("poe_on", 0.10, "step.poeOn"),
    ("searching", 0.35, "step.searching"),
    ("device_found", 0.60, "step.deviceFound"),
    # Only when the run was started with "flash before assigning". It sits
    # between finding the device and writing its address because that is the
    # only moment the device is alone on the wire (see ip_assign.preflash).
    ("firmware", 0.70, "step.firmware"),
    ("writing_ip", 0.80, "step.writingIp"),
    ("verifying", 0.92, "step.verifying"),
)

_STEP_FRACTION = {code: fraction for code, fraction, _label in PORT_STEPS}
_STEP_LABEL = {code: label for code, _fraction, label in PORT_STEPS}

_STARTING_LABEL = "step.starting"


def parse_event(line: str) -> dict | None:
    """Return the event carried by a line, or None if it carries none.

    A malformed event is treated as prose rather than raising: a run must not
    die because one line of its own output was garbled.
    """
    if not line.startswith(EVENT_PREFIX):
        return None
    try:
        event = json.loads(line[len(EVENT_PREFIX):])
    except ValueError:
        return None
    return event if isinstance(event, dict) and event.get("event") else None


class RunProgress:
    """Translates the script's event stream into job queue progress.

    It produces three things:

      · A ROW per target port (queued → running → written → done/failed).
      · Under that row, the port's own STEP history: "Opening the PoE port",
        "device found: 10.1.1.12", "writing the IP". The UI shows these in a
        collapsed accordion.
      · The job's PHASE and percentage (see PHASES).

    Lines that are neither an event nor a detail line under the running port
    are swallowed, so only meaningful things reach the queue. With `log` set,
    the prose goes there too.
    """

    def __init__(self, job, plan_rows, log=None):
        from .ports import port_key

        self._job = job
        self._log = log
        self._port_key = port_key
        self._current: int | None = None
        self._failures = 0
        self._ports = []
        self._states: dict[int, str] = {}
        self._fraction = 0.0     # progress within the running port
        self._step_label = _STARTING_LABEL
        self._phase = "prepare"
        self._summary_seen = 0   # rows read from the summary table
        self._pass = 1
        for row in plan_rows:
            if not row.get("actionable"):
                continue
            port = int(row["port"])
            self._ports.append(port)
            self._states[port] = "queued"
            job.add_row(port_key(port),
                        i18n.lazy("ip.portRow", port=port, name=row["name"]),
                        state="queued",
                        note=i18n.lazy("ip.targetNote", ip=row["targetIp"]),
                        counted=True)
        self._enter_phase("prepare")

    @property
    def failure_count(self) -> int:
        return self._failures

    # ---- phase and percentage ----
    def _enter_phase(self, name: str) -> None:
        """Advance the phase. Never goes back: pass 2 does not restart it."""
        if name not in _ORDER:
            return
        if (_ORDER.index(name) >= _ORDER.index(self._phase)
                and name != self._phase):
            self._phase = name
            self._fraction = 0.0
        self._publish()

    def _closed_ports(self) -> int:
        """Ports closed as far as the port pass is concerned.

        A failed port does not count as closed: it will be retried next pass.
        The number never decreases, so the bar never goes back.
        """
        return sum(1 for port in self._ports
                   if self._states.get(port) in (WRITTEN, "done"))

    def _inner_ratio(self) -> float:
        if self._phase == "assign":
            if not self._ports:
                return 1.0
            return (self._closed_ports() + self._fraction) / len(self._ports)
        if self._phase == "verify":
            if not self._ports:
                return 1.0
            return self._summary_seen / len(self._ports)
        return 0.0

    def _phase_text(self) -> str:
        total = len(self._ports)
        if self._phase == "assign":
            prefix = (i18n.t("phase.passPrefix", **{"pass": self._pass})
                      if self._pass > 1 else "")
            if self._current is None:
                return i18n.t("phase.assignCount", prefix=prefix,
                              done=self._closed_ports(), total=total)
            return i18n.t("phase.assignPort", prefix=prefix,
                          port=self._current,
                          step=i18n.t(self._step_label),
                          done=self._closed_ports(), total=total)
        if self._phase == "verify" and self._summary_seen:
            return i18n.t("phase.withCount", label=i18n.t(_LABEL[self._phase]),
                          done=self._summary_seen, total=total)
        return i18n.t(_LABEL[self._phase])

    def _publish(self) -> None:
        ratio = _START[self._phase] + _SHARE[self._phase] * min(
            1.0, max(0.0, self._inner_ratio()))
        self._job.set_progress(ratio)
        self._job.set_phase(self._phase_text())

    # ---- rows ----
    def _write(self, port: int, state: str, note: str = "",
               step: str = "") -> None:
        if port not in self._ports:
            return
        self._states[port] = state
        self._job.update_row(self._port_key(port), state, note)
        if step:
            self._job.add_step(self._port_key(port), step, state)

    def _step(self, port: int, text: str, state: str = "info") -> None:
        if port in self._ports:
            self._job.add_step(self._port_key(port), text, state)

    # ---- input ----
    def line(self, text: str) -> None:
        raw = text.rstrip()
        event = parse_event(raw.strip())
        if event is not None:
            self._event(event)
            return

        # Prose. It informs the operator; it never decides anything.
        if self._log:
            self._log(raw)
        if not raw.strip():
            return
        if self._current is None or not raw.startswith("    "):
            return
        detail = raw.strip()
        # Lines like "[!] 10.1.1.12 is not on this port (...) — dropped" do
        # not fail the port but are the only record of why.
        self._step(self._current, detail,
                   "warning" if detail.startswith("[!]") else "info")

    def _event(self, event: dict) -> None:
        handler = getattr(self, f"_on_{event['event']}", None)
        if handler is not None:
            handler(event)

    def _on_phase(self, event: dict) -> None:
        self._current = None
        self._enter_phase(str(event.get("phase", "")))

    def _on_pass_started(self, event: dict) -> None:
        try:
            self._pass = int(event.get("pass", 1))
        except (TypeError, ValueError):
            return
        self._current = None
        self._enter_phase("assign")

    def _on_port_started(self, event: dict) -> None:
        port = _port_of(event)
        if port is None or port not in self._ports:
            return
        target = str(event.get("target", ""))
        self._current = port
        self._fraction = 0.0
        self._step_label = _STARTING_LABEL
        note = (i18n.lazy("ip.willBeWritten", ip=target) if target
                else i18n.lazy("ip.starting"))
        self._write(port, "running", note, step=note)
        self._enter_phase("assign")

    def _on_port_step(self, event: dict) -> None:
        port = _port_of(event)
        if port is None or port not in self._ports:
            return
        code = str(event.get("step", ""))
        if code not in _STEP_FRACTION:
            return
        self._current = port
        self._fraction = max(self._fraction, _STEP_FRACTION[code])
        self._step_label = _STEP_LABEL[code]
        detail = str(event.get("detail") or i18n.t(_STEP_LABEL[code]))
        self._job.update_row(self._port_key(port), "running", detail[:160])
        self._enter_phase("assign")

    def _on_port_identified(self, event: dict) -> None:
        """Replace the generic physical-port row with the proven map name."""
        port = _port_of(event)
        name = str(event.get("name", "")).strip()
        target = str(event.get("target", "")).strip()
        if port is None or port not in self._ports or not name:
            return
        note = (i18n.lazy("ip.willBeWritten", ip=target) if target
                else i18n.lazy("ip.starting"))
        # add_row preserves the step history while allowing the title to
        # change from "Compartment LCD" to the exact DeviceMap identifier.
        self._job.add_row(
            self._port_key(port),
            i18n.lazy("ip.portRow", port=port, name=name),
            state="running", note=note, counted=True)

    def _on_port_note(self, event: dict) -> None:
        port = _port_of(event)
        text = str(event.get("text", "")).strip()
        if port is None or not text:
            return
        level = str(event.get("level", "info"))
        self._step(port, text, "warning" if level == "warning" else "info")

    def _on_port_written(self, event: dict) -> None:
        port = _port_of(event)
        if port is None:
            return
        if str(event.get("reason")) == "already_correct":
            self._close(port, WRITTEN, i18n.lazy("ip.alreadyCorrect"))
        else:
            self._close(port, WRITTEN, i18n.lazy("ip.writtenAwaitingCheck"))

    def _on_port_ok(self, event: dict) -> None:
        port = _port_of(event)
        if port is not None:
            self._close(port, "done", i18n.lazy("ip.writtenAndVerified"))

    def _on_port_failed(self, event: dict) -> None:
        port = _port_of(event)
        if port is None:
            return
        self._failures += 1
        reason = str(event.get("reason", "")).strip()
        self._close(port, "failed",
                    reason or i18n.t("ip.couldNotComplete"))

    def _on_summary_row(self, event: dict) -> None:
        # The final table has the last word: a port that looked failed
        # mid-pass may have completed later, and one that looked written may
        # not answer on its new address.
        port = _port_of(event)
        if port is None:
            return
        if port in self._ports:
            self._summary_seen += 1
        target = str(event.get("target", ""))
        reason = str(event.get("reason", "")).strip()
        if str(event.get("status")) == "ok":
            self._write(port, "done", i18n.lazy("ip.verified", ip=target),
                        step=i18n.lazy("ip.verified", ip=target))
        else:
            reason = reason or i18n.t("ip.noAnswer")
            self._write(port, "failed", reason,
                        step=i18n.lazy("ip.finalCheck", reason=reason))
        self._publish()

    def _close(self, port: int, state: str, note: str) -> None:
        self._write(port, state, note, step=note)
        if port == self._current:
            self._current = None
            self._fraction = 0.0
        self._publish()

    def finish(self) -> None:
        """Close any remaining rows and clear the phase."""
        for port in self._ports:
            state = self._states.get(port, "queued")
            if state in ("queued", "running"):
                self._write(port, "skipped", i18n.lazy("ip.notReached"),
                            step=i18n.lazy("ip.notReached"))
            elif state == WRITTEN:
                # The run ended before the final verification (cancel, crash):
                # the IP was written but never confirmed, so "done" would be
                # wrong.
                self._write(port, "warning",
                            i18n.lazy("ip.writtenNoCheck"),
                            step=i18n.lazy("ip.checkDidNotRun"))
        # The percentage only fills when the run reached its own end: showing
        # a cancelled run at 100% reads as finished work.
        if not self._ports or self._summary_seen >= len(self._ports):
            self._job.set_progress(1.0)
        self._job.set_phase("")


def _port_of(event: dict) -> int | None:
    try:
        return int(event["port"])
    except (KeyError, TypeError, ValueError):
        return None
