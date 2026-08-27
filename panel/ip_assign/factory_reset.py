#!/usr/bin/env python3
"""Gathering the selected devices back on the factory address.

This is not the run's inverse: it builds the starting state the run expects —
every selected intercom written to the same factory address.

The first version tried to reach each device ONLY at its DeviceMap address and
made a single pass. Two field situations broke that, both visible in arp-scan
output:

  · The device is not at its DeviceMap address. After the operation has run
    once, most devices already sit on the factory address, and a second run
    reported "no answer" on every row.
  · TWO devices on one address (arp-scan "DUP: 2"). A single request to that
    address reaches only one; the second stayed there no matter how often the
    operation was repeated — exactly what the user saw (two devices stuck on
    10.1.1.14).

So the flow runs PASS BY PASS: every pass probes all candidate addresses,
writes the factory address to whoever answers, and confirms the address really
emptied. Once it empties, the second device behind it becomes visible; passes
repeat until no address answers. PoE is still untouched: what separates the
devices is the address emptying and the MAC, not power.
"""
from __future__ import annotations

import time

from .. import clock
from .. import credentials as credential_store
from .. import script_loader
from ..inventory.device_map import Inventory
from ..probe import switch as switch_probe
from .addressing import can_flush_arp, factory_ip, is_ipv4, search_candidates
from .audit import extension_of
from .plan import devices_by_port, resolve_groups
from .ports import port_key
from .progress import phase_table
from .runner import script_config
from .. import i18n

MAX_PASSES = 10
# Wait between passes. Without permission to flush the ARP cache this is the
# only remedy: devices on one address overwrite each other's ARP
# announcements and the OS entry flips to another device within seconds. It
# was measured in the field — 10.1.1.13's entry moved between two devices in
# about 20 seconds. So waiting turns an unreachable device into a reachable
# one.
PASS_INTERVAL_UNPRIVILEGED = 12.0
# When ARP can be flushed there is no need to wait for the entry to turn over;
# only enough time for the addresses to resolve again.
PASS_INTERVAL_PRIVILEGED = 2.0
# A pass where no address answers does NOT mean "nobody left". Without ARP
# flushing the entry may point at a device that has moved; with flushing the
# entry was JUST deleted and the address has to resolve from scratch. Either
# way one more look is taken, only the wait and the repeat count differ.
# With permission one extra look is enough — flushing really works, so the
# second probe already resolves freshly. Without it, waiting for the entry to
# turn over takes a few repeats.
EMPTY_PASS_TOLERANCE = 3
EMPTY_PASS_TOLERANCE_PRIVILEGED = 1

# Probe repeats within a pass. ONE probe is not enough: the run flushes the
# ARP entry each pass (with permission) and re-resolving a deleted entry can
# take longer than the probe's own timeout — measured in the field: a resolved
# address answers in 0.01 s, an unresolved one stays silent until the timeout.
# The assignment script distrusts a single probe for the same reason and spins
# find_device for seconds. Two attempts suffice and they measure DIFFERENT
# things: the first with whatever entry the OS holds (milliseconds if valid),
# the second after the entry is cleared (for the stale-entry case). A third
# just repeated the same measurement and lengthened the run.
PROBE_ATTEMPTS = 2
PROBE_INTERVAL = 1.0
# How long to wait for an address to empty after a write (the script's
# --reset-wait). It continues the moment the device stops answering; this is
# only the ceiling.
RESET_WAIT = 15.0
# How many times one address may fail to empty before giving up. If the
# responding device can be identified, one attempt is enough (it also scores
# two below); if not, one more is tried — an address still answering may mean
# a SECOND device behind it.
STUCK_LIMIT = 2

FACTORY_PHASES = (
    ("prepare", "factory.phasePrepare", 0.08),
    ("reset", "factory.phaseReset", 0.77),
    ("verify", "factory.phaseVerify", 0.15),
)
_ORDER, _LABEL, _SHARE, _START = phase_table(FACTORY_PHASES)


class FactoryResetProgress:
    """The queue view of a `reset_to_factory` job.

    Same shape as the run (see progress.RunProgress): one ROW per target
    device, its own steps beneath it, phase and percentage on top. Previously
    every output line became a separate info row, and since info rows do not
    count towards the counters the percentage sat at 0% throughout (see
    Job.add_row `counted`).
    """

    def __init__(self, job, targets):
        self._job = job
        self._phase = "prepare"
        self._pass = 1
        self._note = ""
        self._info_index = 0
        self._states: dict[str, str] = {}
        self._extra: dict[str, str] = {}     # address -> row key
        for port, device in targets:
            key = port_key(port)
            self._states[key] = "queued"
            job.add_row(key, f"Port {port} · {device.name}", state="queued",
                        note=f"{device.ip} → fabrika", ip=device.ip,
                        counted=True)
        self._publish()

    # ---- rows ----
    def info(self, text: str, state: str = "done") -> None:
        """A row not tied to a device; excluded from counters and percentage."""
        self._info_index += 1
        self._job.add_row(f"info{self._info_index}", text, state=state)

    def extra_row(self, ip: str) -> str:
        """Open a row for an address that maps to no target row.

        When the port of the device answering on an address cannot be resolved
        (no switch credentials, or the MAC is not in the table) the finding is
        not swallowed but written to its own row. It stays out of the
        counters: the target count comes from DeviceMap, not from how many
        addresses answered.
        """
        key = self._extra.get(ip)
        if key is None:
            key = f"extra:{ip}"
            self._extra[ip] = key
            self._job.add_row(key, i18n.lazy("factory.portUnresolved", ip=ip),
                              state="running",
                              note=i18n.lazy("factory.deviceFound"), ip=ip)
        return key

    def running(self, key: str, note: str) -> None:
        if key in self._states:
            self._states[key] = "running"
        self._job.update_row(key, "running", note)
        self._job.add_step(key, note, "info")
        self._publish()

    def step(self, key: str, text: str, state: str = "info") -> None:
        self._job.add_step(key, text, state)

    def close(self, key: str, state: str, note: str) -> None:
        if key in self._states:
            self._states[key] = state
        self._job.update_row(key, state, note)
        self._job.add_step(key, note, state)
        self._publish()

    def is_open(self, key: str) -> bool:
        return self._states.get(key) in ("queued", "running")

    def states(self) -> dict[str, str]:
        """Final state of the target rows — the summary counts from here."""
        return dict(self._states)

    # ---- phase and percentage ----
    def set_pass(self, number: int) -> None:
        """Which PRODUCTIVE pass this is. Repeats that found no device do not
        count: users read "8th pass" as the job dragging on when it was
        already done."""
        self._pass = int(number)
        self._note = ""
        self._publish()

    def set_note(self, text: str) -> None:
        """Short note appended to the phase text ("looking again")."""
        self._note = text
        self._publish()

    def set_phase(self, name: str) -> None:
        if _ORDER.index(name) >= _ORDER.index(self._phase):
            self._phase = name
        self._publish()

    def _closed(self) -> int:
        return sum(1 for state in self._states.values()
                   if state not in ("queued", "running"))

    def _inner_ratio(self) -> float:
        if self._phase == "reset":
            if not self._states:
                return 1.0
            return self._closed() / len(self._states)
        return 0.0

    def _text(self) -> str:
        if self._phase == "reset":
            prefix = (i18n.t("factory.passPrefix", **{"pass": self._pass})
                      if self._pass > 1 else "")
            suffix = (i18n.t("factory.noteSuffix", note=self._note)
                      if self._note else "")
            return i18n.t("factory.resetCount", prefix=prefix,
                          label=i18n.t(_LABEL["reset"]),
                          done=self._closed(), total=len(self._states),
                          suffix=suffix)
        return i18n.t(_LABEL[self._phase])

    def _publish(self) -> None:
        ratio = _START[self._phase] + _SHARE[self._phase] * min(
            1.0, max(0.0, self._inner_ratio()))
        self._job.set_progress(ratio)
        self._job.set_phase(self._text())

    def finish(self, complete: bool = True) -> None:
        # Showing an interrupted job at 100% reads as finished work (see
        # RunProgress.finish).
        if complete:
            self._job.set_progress(1.0)
        self._job.set_phase("")


class PortResolver:
    """Which port is the device answering on an address attached to?

    The ARP table gives the address's MAC and the switch's MAC learning table
    gives that MAC's port. It is the only way to write the row against the
    right port while a device is NOT at its DeviceMap address, and it is also
    what separates two devices on one address (once one moves the second
    appears on the same address but with a different MAC).

    Returns None when there are no switch credentials or the table cannot be
    read, and the caller falls back to address mapping: asking for credentials
    is not a precondition of this job.
    """

    def __init__(self, switch, ttl: float = 10.0):
        self._switch = switch
        self._ttl = ttl
        self._table: dict[str, int] = {}
        self._read_at = 0.0
        self._disabled = False

    def _refresh(self) -> None:
        if self._disabled or (self._table
                              and time.time() - self._read_at < self._ttl):
            return
        credentials = credential_store.lookup(self._switch.id,
                                              self._switch.ip, group="switch")
        if not credentials:
            self._disabled = True
            return
        try:
            self._table = switch_probe.mac_table(self._switch.ip, credentials)
        except Exception:
            self._disabled = True
            return
        self._read_at = time.time()

    def port_for(self, ip: str) -> int | None:
        self._refresh()
        if not self._table:
            return None
        try:
            mac = script_loader.intercom_ip_assign().host_mac(ip)
        except Exception:
            return None
        value = self._table.get(mac) if mac else None
        return int(value) if value is not None else None


def _device_trace(module, ip: str, device_settings: dict | None) -> str:
    """An identity for whoever answers on an address.

    In order: the extension the device reports, the MAC it reports, then the
    OS ARP table. The first two come from the device and are immune to a stale
    ARP entry. With none of them the result is empty, meaning the identity is
    unreadable and the caller decides what that means (see `_address_freed`).
    """
    extension = extension_of(device_settings)
    if extension:
        return f"extension:{extension}"
    for key in ("mac", "macAddress", "mac_address", "MAC"):
        value = str((device_settings or {}).get(key) or "").strip()
        if value:
            return value.lower()
    try:
        return str(module.host_mac(ip) or "").lower()
    except Exception:
        return ""


def _wait(seconds: float, cancelled=None) -> bool:
    """Sleep in slices, returning early on cancel. Returns whether it waited."""
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        if cancelled and cancelled():
            return False
        clock.sleep(min(0.5, max(0.0, deadline - clock.monotonic())))
    return not (cancelled and cancelled())


def _probe(module, config, candidates: list[str], cancelled=None) -> dict:
    """Probe the candidates, flushing ARP only IF NEEDED.

    The order is deliberate: look first with whatever entry the OS holds,
    because a valid entry answers in milliseconds. Deleting the entry forces
    the address to resolve from scratch, which can outlast the probe's own
    timeout — measured in the field: a resolved address 0.01 s, an unresolved
    one silent until the timeout.

    The old flow deleted every candidate's entry at the start of each pass;
    that is why all devices appeared as "no answer" at once. The flush still
    happens, but only when nothing answered — a stale entry is only a
    plausible explanation then.
    """
    found: dict = {}
    for attempt in range(max(1, PROBE_ATTEMPTS)):
        if cancelled and cancelled():
            return {}
        found = module.probe_all(candidates, config)
        if found:
            return found
        module.arp_forget(candidates)
        if attempt + 1 < PROBE_ATTEMPTS:
            if not _wait(PROBE_INTERVAL, cancelled):
                return {}
    return found


def _address_freed(module, config, ip: str, trace: str,
                   window: float | None = None) -> bool:
    """Did the write take effect — has the device left this address?

    "The address went quiet" is NOT the right test on its own: with two
    devices on one address it keeps answering after the first moves (the
    second is there), and the single-pass flow read that as "write not
    applied". So who the answer comes FROM is what matters: a changed identity
    means our device is gone.
    """
    # The window is read at call time: a module constant baked into a default
    # argument could not be changed by tests.
    deadline = clock.monotonic() + (RESET_WAIT if window is None else window)
    silent = 0
    while True:
        current = module.read_settings(ip, config)
        if current is not None:
            silent = 0
            latest = _device_trace(module, ip, current)
            if trace and latest and latest != trace:
                return True                  # a different device answers
        else:
            # One silence is not enough: it can mean our device left, or a
            # stale ARP entry. Clear it and look again; two silences in a row
            # mean the address is free.
            silent += 1
            if silent >= 2:
                return True
            module.arp_forget([ip])
        if clock.monotonic() >= deadline:
            return silent > 0
        clock.sleep(getattr(config, "poll_interval", 1.0))


def reset_to_factory(inventory: Inventory, switch_id: str, ports: list[int],
                     groups, job, options: dict | None = None,
                     cancelled=None) -> dict:
    """Gather the selected devices on the factory address (see module note).

    Only an IP write request is sent — PoE, the switch's settings and
    DeviceMap are untouched. Afterwards the devices all share one address,
    which is the starting state the run expects.

    `job` is the queue job: rows, steps and percentage are written there (see
    FactoryResetProgress).

    Returns a summary dict.
    """
    module = script_loader.intercom_ip_assign()
    switch = inventory.find(switch_id)
    if switch is None:
        raise ValueError(i18n.t("error.switchNotFound"))
    selected = resolve_groups(groups)
    if not selected:
        raise ValueError(
            i18n.t("error.intercomOnly"))

    options = options or {}
    factory = (str(options.get("factoryIp") or "").strip()
               or factory_ip(inventory))
    if not is_ipv4(factory):
        raise ValueError(i18n.t("error.factoryIpInvalid"))

    by_port = devices_by_port(inventory, selected, switch.id)
    targets = [(port, by_port[port][0]) for port in sorted(ports)
               if port in by_port]
    if not targets:
        raise ValueError(i18n.t("error.noDeviceOfGroup"))

    config = script_config(factory, switch.ip)
    report = FactoryResetProgress(job, targets)
    resolver = PortResolver(switch)
    target_ports = {port for port, _device in targets}

    # Candidates: the selected devices' DeviceMap addresses plus the user's
    # search range if given. The factory address is NOT included: a device
    # answering there is already where it belongs, and writing to it is
    # meaningless since which device answers is unknown.
    address_port: dict[str, int] = {}
    for port, device in targets:
        ip = str(device.ip or "").strip()
        if is_ipv4(ip) and ip != factory:
            address_port.setdefault(ip, port)
    extra_addresses = [
        ip for ip in search_candidates(
            options.get("searchNetwork"), options.get("searchNetmask"),
            first=options.get("searchFirst") or "",
            last=options.get("searchLast") or "")
        if ip != factory]
    candidates = list(dict.fromkeys(list(address_port) + extra_addresses))

    report.info(i18n.lazy("factory.intro", count=len(targets),
                          factory=factory))
    # Without ARP permission stale entries cannot be cleared: the OS entry
    # points at a moved device's MAC while that address shows "no answer" —
    # near certain when several devices share an address. The reason used to
    # be written nowhere; now it is on the first line.
    arp_ok = can_flush_arp()
    if not arp_ok:
        report.info(
            i18n.lazy("factory.noArp"),
            state="warning")
    if extra_addresses:
        report.info(i18n.lazy("factory.extraSearch",
                              count=len(extra_addresses),
                              first=extra_addresses[0],
                              last=extra_addresses[-1]))

    # A device whose target already IS the factory address: nothing to write.
    for port, device in targets:
        if str(device.ip or "").strip() == factory:
            report.close(port_key(port), "done",
                         i18n.lazy("factory.alreadyAtFactory",
                                   factory=factory))

    # Extension -> port. Because the device reports its own extension (see
    # extension_of), which device is where resolves without switch
    # credentials or ARP: that is how the field case of a device on 10.1.1.13
    # actually being port 22's device was spotted.
    extension_port = {device.pbx_extension: port
                      for port, (device, _group) in by_port.items()
                      if getattr(device, "pbx_extension", None)}

    def row_for(ip: str, device_settings: dict | None = None) -> tuple[str, str]:
        """The row for the device found at an address. Returns (key, reason).

        An empty key means the device is outside the selected ports: leave it
        alone. The order is order of certainty: the device's own extension,
        then MAC-based port resolution, then "whose address is this in
        DeviceMap".
        """
        extension = extension_of(device_settings)
        port = extension_port.get(extension) if extension else None
        how = (i18n.t("factory.byExtension", extension=extension, port=port)
               if port is not None else "")
        if port is None:
            port = resolver.port_for(ip)
            how = (i18n.t("factory.byMac", port=port)
                   if port is not None else "")
        if port is not None:
            if port in target_ports:
                return port_key(port), how
            return "", i18n.t(
                "factory.outsidePorts",
                how=how or i18n.t("factory.portFallback", port=port))
        port = address_port.get(ip)
        if port is not None:
            return port_key(port), ""
        return report.extra_row(ip), ""

    written = 0
    stopped = False
    empty_passes = 0
    tolerance = (EMPTY_PASS_TOLERANCE_PRIVILEGED if arp_ok
                 else EMPTY_PASS_TOLERANCE)
    pass_interval = (PASS_INTERVAL_PRIVILEGED if arp_ok
                     else PASS_INTERVAL_UNPRIVILEGED)
    warned = False
    stuck: dict[str, int] = {}          # address -> score for not emptying
    report.set_phase("reset")
    productive = 0                      # passes that found a device
    last_pass_empty = False
    for _index in range(1, MAX_PASSES + 1):
        if cancelled and cancelled():
            stopped = True
            break
        if not candidates:
            break
        found = _probe(module, config, candidates, cancelled)
        if not found:
            last_pass_empty = True
            empty_passes += 1
            if empty_passes > tolerance:
                break
            if not warned:
                warned = True
                report.info(
                    i18n.t("factory.noneAnswered")
                    + ("" if arp_ok
                       else i18n.t("factory.noneAnsweredArp")),
                    state="warning")
            # An empty repeat does NOT count as a pass: users read "8th pass"
            # as the job dragging on when it had already finished.
            report.set_note(i18n.lazy(
                "factory.lookingAgain",
                **{"pass": empty_passes, "total": tolerance + 1}))
            if not _wait(pass_interval, cancelled):
                stopped = True
                break
            continue
        last_pass_empty = False
        empty_passes = 0
        productive += 1
        report.set_pass(productive)
        advanced = False
        for ip in sorted(found):
            if cancelled and cancelled():
                stopped = True
                break
            key, reason = row_for(ip, found[ip])
            if not key:
                report.info(i18n.lazy("factory.notTouched", ip=ip,
                                      reason=reason), state="warning")
                continue
            report.running(key, i18n.lazy(
                "factory.writing", ip=ip, factory=factory,
                reason=(i18n.t("factory.reasonSuffix", reason=reason)
                        if reason else "")))
            trace = _device_trace(module, ip, found[ip])
            extension = extension_of(found[ip])
            try:
                module.write_ip(ip, found[ip], factory, config)
            except Exception as exc:
                # There may be no write response: the device processes the
                # request and resets, dropping the connection before it
                # answers. What proves the write landed is the device leaving
                # the address, not the response.
                report.step(key, i18n.lazy("factory.noWriteResponse",
                                           kind=type(exc).__name__),
                            "warning")
            if _address_freed(module, config, ip, trace):
                written += 1
                advanced = True
                report.close(key, "done", i18n.lazy(
                    "factory.writtenExtension" if extension
                    else "factory.written",
                    ip=ip, factory=factory, extension=extension))
                continue
            # The address did not empty. With a readable identity that is a
            # definite failure (the same device is still there); without one
            # there may be a second device behind it, so one more pass.
            stuck[ip] = stuck.get(ip, 0) + (1 if not trace else 2)
            report.step(key, i18n.lazy("factory.stillAnswers", ip=ip),
                        "warning")
            if stuck[ip] >= STUCK_LIMIT:
                report.close(key, "failed",
                             i18n.lazy("factory.didNotEmpty", ip=ip))
            else:
                advanced = True       # may be a second device: try again
        # Closed addresses are not probed again; if nothing moved, another
        # pass would give the same answer.
        candidates = [ip for ip in candidates
                      if stuck.get(ip, 0) < STUCK_LIMIT]
        if stopped or not advanced:
            break

    # ── final check: is anyone left on the old addresses? ──
    # Skipped when the run already ended on an empty probe: repeating the same
    # measurement only lengthens the job.
    report.set_phase("verify")
    if not stopped and candidates:
        if not last_pass_empty:
            for ip, remaining in sorted(
                    _probe(module, config, candidates, cancelled).items()):
                key, _reason = row_for(ip, remaining)
                if not key:
                    continue
                extension = extension_of(remaining)
                report.close(key, "failed", i18n.lazy(
                    "factory.deviceStillThereExtension" if extension
                    else "factory.deviceStillThere",
                    ip=ip, extension=extension))
        if not arp_ok:
            # The final check reads from the same stale entry: we cannot say
            # "nobody is left", only "nobody is visible with this entry".
            report.info(
                i18n.lazy("factory.checkedWithoutArp"),
                state="warning")

    for port, device in targets:
        key = port_key(port)
        if not report.is_open(key):
            continue
        if stopped:
            report.close(key, "skipped", i18n.lazy("factory.stopped"))
        else:
            # No answer is not a failure: the device is most likely ALREADY on
            # the factory address (this operation gets run repeatedly). Still
            # not "done" either — there is no proof.
            report.close(key, "skipped", i18n.lazy(
                "factory.noAnswerMaybeDone", ip=device.ip, factory=factory)
                if arp_ok else i18n.lazy("factory.noAnswerMaybeDoneArpFull",
                                         ip=device.ip, factory=factory))

    # Is anything answering on the factory address? One address cannot say how
    # many devices are there, but "nobody at all" versus "at least one" is a
    # big difference for the user: devices silent on their old addresses have
    # either gathered there or are invisible on this network.
    factory_answers = None
    if not stopped:
        factory_answers = module.read_settings(factory, config) is not None
        report.info(
            i18n.lazy("factory.factoryAnswers" if factory_answers
                      else "factory.factorySilent", factory=factory),
            state="done" if factory_answers else "warning")
    report.finish(complete=not stopped)

    states = report.states()
    return {
        "total": len(targets),
        "done": sum(1 for state in states.values() if state == "done"),
        "failed": sum(1 for state in states.values() if state == "failed"),
        "skipped": sum(1 for state in states.values() if state == "skipped"),
        # How many devices were actually written: a second device found on the
        # same address counts here too, so this can exceed the target count.
        "written": written,
        "stopped": stopped,
        "factoryIp": factory,
        "factoryAnswers": factory_answers,
        # Whether the ARP cache could be flushed: it decides how trustworthy
        # the "no answer" rows are.
        "arpFlush": arp_ok,
    }
