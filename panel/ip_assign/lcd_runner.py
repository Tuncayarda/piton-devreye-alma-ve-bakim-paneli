#!/usr/bin/env python3
"""Compartment LCD commissioning over ADB, one switch port at a time.

The Android displays arrive on the set-1 form of their DeviceMap address
(``10.1.1.40`` and upwards).  A run isolates each selected switch port, can
install the APK while the display is still on that known address, then moves
it to the destination set's network.

Three flows share that machinery, and they differ only in which set supplies
the source addresses and which supplies the destinations:

* commissioning  — set 1 -> the open set (the ordinary run);
* factory reset  — the open set -> set 1, which for these displays means
  ``10.1.1.40`` upwards rather than one shared address, because each display
  keeps its own host octet;
* set transfer   — set 3 -> set 5, say, when a whole train changes number.

:func:`run_manual` is the fourth and is not a set at all: one port, one
address the operator typed.

ADB's TCP serial is the address itself.  Changing the address can therefore
leave both the old and the new serial in the ADB server.  Every device command
in this module uses ``-s <ip>:5555`` and success is decided only after a fresh
connection to the new serial identifies the same Android device.
"""
from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from types import SimpleNamespace

from .. import firmware, i18n, script_loader, settings
from ..inventory.device_map import Device, Inventory, resolve_template
from .addressing import DEFAULT_TARGET_PREFIX

ETHERNET_INTERFACE = "eth0"
# Kept as the module's own name for the default; the run takes the mask it
# actually writes from its options (see panel.ip_assign.addressing).
TARGET_PREFIX = DEFAULT_TARGET_PREFIX
POE_SETTLE = 2.0
LINK_WAIT = 45.0
CONNECT_ATTEMPTS = 12
CONNECT_RETRY_INTERVAL = 2.0
RESTORE_ATTEMPTS = 3
RESTORE_RETRY_INTERVAL = 5.0
# A moved test cable means the physical port no longer identifies an LCD.
# Candidate addresses are tried concurrently in two bounded sweeps.  Without
# these limits, 11 displays x source+target x the old 12 retries could leave a
# missing-device job searching for many minutes.
DISCOVERY_ROUNDS = 2
DISCOVERY_WORKERS = 8
DISCOVERY_COMMAND_TIMEOUT = 2.0
DISCOVERY_TIMEOUT = 45.0
DISCOVERY_RETRY_INTERVAL = 1.0


class AdbUnavailable(RuntimeError):
    """The host cannot execute ADB at all."""


class AdbTimeout(RuntimeError):
    """One ADB command exceeded its bounded wait."""


def commissioning_ip(device: Device, set_no: int = 1) -> str:
    """This display's own address on `set_no` — set 1 by default.

    Set 1 is where a display sits before it knows which train it joins, so it
    is both the ordinary starting point and the destination a factory reset
    puts it back on. A transfer names another set on either side.
    """
    return resolve_template(device.ip_template, int(set_no) or 1)


def _event(emit, event: str, **fields) -> None:
    emit("@EVT " + json.dumps({"event": event, **fields},
                              ensure_ascii=False, separators=(",", ":")))


def _adb(*args: str, timeout: float | None = None):
    """Run ADB without ever relying on its implicit current device."""
    try:
        return subprocess.run(
            ["adb", *args], capture_output=True, text=True,
            timeout=(settings.ADB_TIMEOUT if timeout is None else timeout))
    except FileNotFoundError as exc:
        raise AdbUnavailable("adb command was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbTimeout(f"adb {args[0] if args else ''} timed out") from exc


def _target(ip: str) -> str:
    return f"{ip}:{settings.ADB_PORT}"


def _disconnect(ip: str, *, timeout: float | None = None) -> None:
    if not ip:
        return
    try:
        _adb("disconnect", _target(ip), timeout=timeout)
    except Exception:
        # Cleanup must neither hide the port result nor prevent PoE restore.
        pass


def _connect_once(ip: str, *, timeout: float | None = None) -> bool:
    """Connect and prove that this exact TCP serial is in ``device`` state."""
    target = _target(ip)
    command_timeout = (min(settings.ADB_TIMEOUT, 5) if timeout is None
                       else timeout)
    _disconnect(ip, timeout=command_timeout)
    connected = _adb("connect", target, timeout=command_timeout)
    if getattr(connected, "returncode", 0) != 0:
        return False
    state = _adb("-s", target, "get-state",
                 timeout=command_timeout)
    return (getattr(state, "returncode", 0) == 0
            and str(getattr(state, "stdout", "") or "").strip() == "device")


def _connect(ip: str, cancelled=None, attempts: int = CONNECT_ATTEMPTS) -> bool:
    """Bounded reconnect; stale ``adb devices`` rows are never consulted."""
    for attempt in range(max(1, int(attempts))):
        if cancelled is not None and cancelled():
            return False
        try:
            if _connect_once(ip):
                return True
        except AdbUnavailable:
            raise
        except Exception:
            pass
        if attempt + 1 < attempts and CONNECT_RETRY_INTERVAL:
            time.sleep(CONNECT_RETRY_INTERVAL)
    return False


def _shell(ip: str, *command: str) -> str:
    """Run a shell command on one explicitly named Android transport."""
    result = _adb("-s", _target(ip), "shell", *command)
    if getattr(result, "returncode", 0) != 0:
        detail = (str(getattr(result, "stderr", "") or "").strip()
                  or str(getattr(result, "stdout", "") or "").strip())
        raise RuntimeError(detail[:160] or "adb shell failed")
    return str(getattr(result, "stdout", "") or "").strip()


def _serial(ip: str) -> str:
    return _shell(ip, "getprop", "ro.serialno").splitlines()[0].strip()


def _cidrs(ip: str) -> set[str]:
    raw = _shell(ip, "ip", "-o", "-4", "addr", "show", "dev",
                 ETHERNET_INTERFACE, "scope", "global")
    return set(re.findall(r"\binet\s+([0-9.]+/[0-9]+)\b", raw))


def _write_address(ip: str, target_ip: str, prefix: int) -> None:
    """Send the complete root transaction before its first address disappears.

    The TCP reply is deliberately not interpreted as success: removing the old
    address can cut off the ADB response even though all commands ran.  The
    caller disconnects the stale transport and verifies at the new address.
    """
    script = (
        f"ip -4 addr flush dev {ETHERNET_INTERFACE} scope global; "
        f"ip addr add {target_ip}/{int(prefix)} dev {ETHERNET_INTERFACE}; "
        f"ip link set {ETHERNET_INTERFACE} up"
    )
    try:
        _adb("-s", _target(ip), "shell", "su", "-c", script)
    except AdbTimeout:
        # An address change commonly drops the reply.  Reconnect is the proof.
        pass


# ── the small public surface other screens borrow ──────────────────────────
# The device settings screen writes a display's address too, and it must do it
# the same way this file does or the two would disagree about what "written"
# means. These are that flow's entry points; everything above stays private to
# the run.
def connect(ip: str, attempts: int = CONNECT_ATTEMPTS) -> bool:
    """Open and prove an ADB transport to exactly this address."""
    return _connect(ip, attempts=attempts)


def disconnect(ip: str) -> None:
    """Drop this exact TCP serial from the global ADB server."""
    _disconnect(ip)


def addresses(ip: str) -> set[str]:
    """Every global IPv4 CIDR eth0 currently holds."""
    return _cidrs(ip)


def serial_of(ip: str) -> str:
    """The Android serial answering at this address."""
    return _serial(ip)


def write_address(ip: str, target_ip: str, prefix: int) -> None:
    """Send the address transaction. Success is decided by reconnecting."""
    _write_address(ip, target_ip, prefix)


def _switch_config(switch, account) -> SimpleNamespace:
    """Arguments expected by the field-proven PoE/MAC helper functions."""
    return SimpleNamespace(
        switch_ip=switch.ip,
        kyland_port=settings.KYLAND_PORT,
        kyland_user=account[0],
        kyland_pass=account[1],
        timeout=8.0,
        switch_retries=3,
        switch_retry_wait=3.0,
        poe_read_endpoint=None,
        verbose=False,
        dry_run=False,
        poll_interval=1.0,
        link_wait=LINK_WAIT,
        verify_mac=True,
        mac_endpoint=None,
        # A table learned for the previous display is already stale.
        mac_cache_ttl=0.0,
        arp_flush=True,
    )


def _right_port(module, ip: str, port: int, cfg) -> tuple[bool, str]:
    """Require positive MAC -> switch-port proof; absence is not identity."""
    verified, reason = module.verify_port(ip, port, cfg)
    return verified is True, str(reason or "port could not be verified")


def _discovery_addresses(candidates, used: set[str]):
    """Unique source addresses first, then set addresses, with their owner."""
    out, seen = [], set()
    for field in ("source", "target"):
        for candidate in candidates:
            device = candidate["device"]
            if device.id in used:
                continue
            ip = candidate[field]
            if ip in seen:
                continue
            seen.add(ip)
            out.append((ip, candidate))
    return out


def _connect_sweep(addresses, cancelled=None):
    """Try one bounded concurrent ADB sweep; return reachable addresses.

    The global ADB server may retain many TCP serials, therefore a successful
    ``adb connect`` is not enough.  Every worker checks the exact transport
    with ``adb -s <ip>:5555 get-state``; no implicit device or kill-server is
    used.
    """
    if not addresses:
        return []

    def one(index, ip):
        if cancelled is not None and cancelled():
            return index, ip, False, "cancelled"
        try:
            ok = _connect_once(ip, timeout=DISCOVERY_COMMAND_TIMEOUT)
            return index, ip, ok, "" if ok else "adb did not connect"
        except AdbUnavailable:
            raise
        except Exception as exc:
            return index, ip, False, str(exc)[:100] or type(exc).__name__

    results = []
    workers = max(1, min(DISCOVERY_WORKERS, len(addresses)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, index, ip)
                   for index, ip in enumerate(addresses)]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results)


def _probe_round(module, addresses, port: int, cfg, cancelled, reasons: dict):
    """One sweep, and the first address it proves is on `port`.

    Returns ``(ip, serial, cidrs)`` or None.  The concurrent sweep can open
    several exact TCP transports; only the proven one survives this call, so
    the write transaction that follows cannot inherit a stale one.
    """
    for ip in addresses:
        module.arp_forget([ip], cfg)
    sweep = _connect_sweep(addresses, cancelled=cancelled)
    connected_ips = [ip for _index, ip, connected, _reason in sweep
                     if connected]
    found = None
    try:
        for _index, ip, connected, connect_reason in sweep:
            if not connected:
                reasons[ip] = connect_reason
                continue
            try:
                serial = _serial(ip)
                if not serial:
                    reasons[ip] = "Android serial is empty"
                    continue
                correct, reason = _right_port(module, ip, port, cfg)
                if not correct:
                    reasons[ip] = reason
                    continue
                found = (ip, serial, _cidrs(ip))
                break
            except AdbUnavailable:
                raise
            except Exception as exc:
                reasons[ip] = str(exc)[:100] or type(exc).__name__
    finally:
        keep = found[0] if found else ""
        for connected_ip in connected_ips:
            if connected_ip != keep:
                _disconnect(connected_ip, timeout=DISCOVERY_COMMAND_TIMEOUT)
    return found


def _discover(module, addresses, port: int, cfg, cancelled=None):
    """Bounded search for the one display sitting on a physical port.

    Returns ``(ip, serial, cidrs, detail)``.  An empty ip means nothing on
    this port could be proved and `detail` says what each address answered.
    """
    reasons: dict[str, str] = {}
    deadline = time.monotonic() + DISCOVERY_TIMEOUT
    for attempt in range(DISCOVERY_ROUNDS):
        if cancelled is not None and cancelled():
            break
        found = _probe_round(module, addresses, port, cfg, cancelled, reasons)
        if found is not None:
            return (*found, "")
        if attempt + 1 >= DISCOVERY_ROUNDS or time.monotonic() >= deadline:
            break
        if DISCOVERY_RETRY_INTERVAL:
            time.sleep(min(DISCOVERY_RETRY_INTERVAL,
                           max(0.0, deadline - time.monotonic())))
    detail = "; ".join(f"{ip}: {reason}" for ip, reason in reasons.items())
    return "", "", set(), detail[-320:]


def _find_candidate(module, candidates, used: set[str], port: int, cfg,
                    cancelled=None):
    """Find and return the immutable DeviceMap candidate on a physical port."""
    pairs = _discovery_addresses(candidates, used)
    owner = dict(pairs)
    ip, serial, cidrs, detail = _discover(
        module, [address for address, _candidate in pairs], port, cfg,
        cancelled)
    if not ip:
        return None, "", "", set(), detail
    return owner[ip], ip, serial, cidrs, ""


def _reconnect_and_verify(module, target_ip: str, expected_serial: str,
                          port: int, cfg, prefix: int) -> tuple[bool, str]:
    module.arp_forget([target_ip], cfg)
    if not _connect(target_ip):
        return False, f"{target_ip}: adb did not reconnect"
    try:
        actual = _serial(target_ip)
        if not actual:
            return False, f"{target_ip}: Android serial is empty"
        if actual != expected_serial:
            return False, (f"{target_ip}: Android serial changed "
                           f"({expected_serial} -> {actual})")
        expected_cidr = f"{target_ip}/{int(prefix)}"
        actual_cidrs = _cidrs(target_ip)
        if actual_cidrs != {expected_cidr}:
            shown = ", ".join(sorted(actual_cidrs)) or "none"
            return False, (f"{target_ip}: eth0 must contain only "
                           f"{expected_cidr} (found: {shown})")
        correct, reason = _right_port(module, target_ip, port, cfg)
        if not correct:
            return False, f"{target_ip}: {reason}"
        return True, ""
    except Exception as exc:
        return False, f"{target_ip}: {str(exc)[:160] or type(exc).__name__}"


def _valid_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(str(value)).version == 4
    except ValueError:
        return False


def _restore(module, cfg, state, managed: set[int], emit) -> bool:
    _event(emit, "phase", phase="restore")
    for attempt in range(RESTORE_ATTEMPTS):
        try:
            module.poe_apply(cfg, state, managed, managed)
            return True
        except Exception:
            if attempt + 1 < RESTORE_ATTEMPTS and RESTORE_RETRY_INTERVAL:
                time.sleep(RESTORE_RETRY_INTERVAL)
    _event(emit, "ports_left_closed", switch=cfg.switch_ip)
    return False


def run(inventory: Inventory, switch, ports: list[int], account, emit,
        options: dict | None = None, cancelled=None) -> int:
    """Move selected Compartment LCD ports between two sets; return 0/1/130.

    ``sourceSet`` is where the displays are now (set 1 unless a transfer says
    otherwise) and ``targetSet`` where they are going (the open set unless a
    factory reset says set 1).  ``targetPrefix`` is the mask written with the
    new address.
    """
    options = options or {}
    prefix = int(options.get("targetPrefix") or TARGET_PREFIX)
    source_set = int(options.get("sourceSet") or 1)
    target_set = int(options.get("targetSet") or inventory.set_no)
    module = script_loader.intercom_ip_assign()
    cfg = _switch_config(switch, account)
    # ``switch`` remains the physical PoE/MAC boundary.  The generic runner
    # derives this private DeviceMap source server-side for the explicit LCD
    # switch override; no device id, IP or source switch comes from the UI.
    device_switch_id = str(options.get("_deviceSwitchId") or switch.id)
    devices = sorted((device for device in inventory.devices
        if device.switch_id == device_switch_id
        and device.type == "LCD" and (device.subtype or "") == "Compartment"
        and device.port and str(device.port).isdigit()),
        key=lambda device: (int(device.port), device.id))
    if not devices:
        raise ValueError("No Compartment LCD candidate is defined in DeviceMap")

    candidates = []
    address_owner: dict[str, str] = {}
    for device in devices:
        source = commissioning_ip(device, source_set)
        target = commissioning_ip(device, target_set)
        if not (_valid_ip(source) and _valid_ip(target)):
            raise ValueError(
                f"Invalid Compartment LCD address for {device.name}")
        # One address may be both the source and target of the SAME device
        # when assigning set 1.  It must never identify two different rows.
        for address in (source, target):
            previous = address_owner.setdefault(address, device.id)
            if previous != device.id:
                raise ValueError(
                    "Compartment LCD candidate addresses are not unique")
        candidates.append({"device": device, "source": source,
                           "target": target})

    if options.get("installApk"):
        absent = [device.name for device in devices
                  if not firmware.has_selection(
                      device.id, set_no=inventory.set_no)]
        if absent:
            raise ValueError(
                f"No APK is selected for candidates: {', '.join(absent)}")

    # The field helper caches its discovered MAC endpoint and last table.  The
    # LCD run changes the powered device on every iteration, so start fresh.
    cache = getattr(module, "_MAC_CACHE", None)
    if isinstance(cache, dict):
        cache.update(endpoint=None, table={}, at=0.0, dead=False)

    managed = set(ports)
    completed: set[int] = set()
    used_devices: set[str] = set()
    identified: dict[int, dict] = {}
    failures: dict[int, str] = {}
    state = module.poe_read(cfg)
    known = {int(row["pid"]) for row in state}
    if not managed.issubset(known):
        raise ValueError(
            f"Ports not present on the switch: {sorted(managed - known)}")

    _event(emit, "phase", phase="baseline")
    try:
        # Establish a quiet starting point.  Completed ports remain on later;
        # a display already commissioned is never power-cycled again mid-run.
        module.poe_apply(cfg, state, set(), managed)
        if POE_SETTLE:
            time.sleep(POE_SETTLE)
        _event(emit, "pass_started", **{"pass": 1})

        for index, port in enumerate(sorted(managed), start=1):
            device = None
            source = target_ip = ""
            old_ip = ""
            _event(emit, "port_started", port=port, target="",
                   index=index, total=len(managed))
            if cancelled is not None and cancelled():
                failures[port] = "cancelled"
                break
            try:
                _event(emit, "port_step", port=port, step="poe_on",
                       detail=f"opening switch port {port}")
                module.poe_apply(cfg, state, completed | {port}, managed)
                if POE_SETTLE:
                    time.sleep(POE_SETTLE)
                linked, _elapsed = module.wait_for_link(cfg, port, cfg.link_wait)
                if linked is False:
                    raise RuntimeError("the switch port did not link")

                _event(emit, "port_step", port=port, step="searching",
                       detail=(f"looking for one of {len(candidates)} "
                               "DeviceMap LCD candidates"))
                candidate, old_ip, before_serial, cidrs, reason = (
                    _find_candidate(module, candidates, used_devices, port,
                                    cfg, cancelled=cancelled))
                if candidate is None or not old_ip:
                    raise RuntimeError(reason or "the display was not found")
                device = candidate["device"]
                source, target_ip = candidate["source"], candidate["target"]
                used_devices.add(device.id)
                identified[port] = candidate
                _event(emit, "port_identified", port=port,
                       deviceId=device.id, name=device.name,
                       source=old_ip, target=target_ip)
                _event(emit, "port_step", port=port, step="device_found",
                       detail=f"{device.name} · {old_ip}")

                if options.get("installApk"):
                    _event(emit, "port_step", port=port, step="firmware",
                           detail="installing the selected APK")
                    # The ordinary firmware flow uses DeviceMap's destination
                    # address.  During commissioning the same verified device
                    # is still at old_ip, so only this immutable copy differs.
                    firmware.install(replace(device, ip=old_ip),
                                     set_no=inventory.set_no)
                    if not _connect(old_ip):
                        raise RuntimeError("adb did not reconnect after APK install")
                    if _serial(old_ip) != before_serial:
                        raise RuntimeError("Android serial changed after APK install")
                    cidrs = _cidrs(old_ip)

                expected_cidr = f"{target_ip}/{prefix}"
                already_correct = (old_ip == target_ip
                                   and cidrs == {expected_cidr})
                if already_correct:
                    _event(emit, "port_written", port=port,
                           reason="already_correct", target=target_ip)
                else:
                    if cancelled is not None and cancelled():
                        raise RuntimeError("cancelled")
                    _event(emit, "port_step", port=port, step="writing_ip",
                           detail=f"writing {target_ip}/{prefix}")
                    _write_address(old_ip, target_ip, prefix)
                    _event(emit, "port_written", port=port, reason="written",
                           target=target_ip)

                _event(emit, "port_step", port=port, step="verifying",
                       detail=f"reconnecting to {target_ip}")
                _disconnect(old_ip)
                _disconnect(target_ip)
                ok, reason = _reconnect_and_verify(
                    module, target_ip, before_serial, port, cfg, prefix)
                if not ok:
                    raise RuntimeError(reason)
                completed.add(port)
                _event(emit, "port_ok", port=port, target=target_ip)
            except Exception as exc:
                failures[port] = str(exc)[:240] or type(exc).__name__
                _event(emit, "port_failed", port=port,
                       reason=failures[port])
            finally:
                # Remove both aliases from the global ADB server.  The next
                # port must never inherit an implicit/stale transport.
                _disconnect(old_ip or source)
                _disconnect(target_ip)
    finally:
        restored = _restore(module, cfg, state, managed, emit)

    _event(emit, "phase", phase="verify")
    for port in sorted(managed):
        target_ip = (identified.get(port) or {}).get("target", "")
        _event(emit, "summary_row", port=port, target=target_ip,
               status="ok" if port in completed else "missing",
               reason=failures.get(port, "not reached"))

    if cancelled is not None and cancelled():
        return 130
    return 0 if len(completed) == len(managed) and restored else 1


def _lcd_devices(inventory: Inventory, switch_id: str) -> list[Device]:
    """The canonical Compartment LCD rows of one DeviceMap switch, by port."""
    return sorted(
        (device for device in inventory.devices
         if device.switch_id == switch_id and device.type == "LCD"
         and (device.subtype or "") == "Compartment"
         and device.port and str(device.port).isdigit()),
        key=lambda device: (int(device.port), device.id))


def manual_candidates(inventory: Inventory, switch_id: str, target_ip: str,
                      extra_sets=()) -> list[str]:
    """Where a display on a bench port might currently answer.

    The operator says which address the display should END UP on, never where
    it is now — on the bench that is the thing they do not know.  So every
    address a Compartment LCD could plausibly hold is tried: the set-1 form of
    each DeviceMap row (a fresh display), the open set's form (one already
    commissioned), any set the operator names, and the requested address
    itself, which is what makes running the same write twice harmless.

    The list stays short by construction — the number of displays in the map
    times a handful of sets — and every answer still has to prove itself on
    the selected switch port before anything is written.
    """
    sets = [1, int(inventory.set_no),
            *(int(number) for number in extra_sets if number)]
    addresses = [str(target_ip or "").strip()]
    for device in _lcd_devices(inventory, switch_id):
        for set_no in sets:
            addresses.append(commissioning_ip(device, set_no))
    return [address for address in dict.fromkeys(addresses)
            if address and _valid_ip(address)]


def run_manual(inventory: Inventory, switch, port: int, account, emit,
               options: dict | None = None, cancelled=None) -> int:
    """Write one operator-chosen address to the display on ONE switch port.

    The bench flow, and deliberately not a small version of :func:`run`.  No
    DeviceMap row decides anything here: there is one display on one port and
    the operator says what address it should get, which is how a display gets
    tested before the train it belongs to exists.

    What does NOT change is the proof.  The port is still isolated, the
    answering display's MAC still has to be learned on that exact port before
    a single command is sent to it, and afterwards the same Android serial has
    to answer at the new address with nothing else left on eth0.  A cable in
    the wrong socket therefore fails the port instead of quietly addressing
    the wrong display.
    """
    options = options or {}
    prefix = int(options.get("targetPrefix") or TARGET_PREFIX)
    target_ip = str(options.get("targetIp") or "").strip()
    if not _valid_ip(target_ip):
        raise ValueError(i18n.t("error.lcdManualTargetInvalid"))
    port = int(port)

    module = script_loader.intercom_ip_assign()
    cfg = _switch_config(switch, account)
    device_switch_id = str(options.get("_deviceSwitchId") or switch.id)
    addresses = manual_candidates(inventory, device_switch_id, target_ip,
                                  extra_sets=(options.get("sourceSet"),))
    if not addresses:
        raise ValueError(i18n.t("error.lcdManualNoCandidates"))

    # As in the ordinary run: a MAC table learned for another display is
    # already stale by the time this port powers up.
    cache = getattr(module, "_MAC_CACHE", None)
    if isinstance(cache, dict):
        cache.update(endpoint=None, table={}, at=0.0, dead=False)

    managed = {port}
    state = module.poe_read(cfg)
    known = {int(row["pid"]) for row in state}
    if not managed.issubset(known):
        raise ValueError(
            f"Ports not present on the switch: {sorted(managed - known)}")

    failure = ""
    done = False
    old_ip = ""
    _event(emit, "phase", phase="baseline")
    try:
        module.poe_apply(cfg, state, set(), managed)
        if POE_SETTLE:
            time.sleep(POE_SETTLE)
        _event(emit, "pass_started", **{"pass": 1})
        _event(emit, "port_started", port=port, target=target_ip,
               index=1, total=1)
        try:
            if cancelled is not None and cancelled():
                raise RuntimeError("cancelled")
            _event(emit, "port_step", port=port, step="poe_on",
                   detail=f"opening switch port {port}")
            module.poe_apply(cfg, state, managed, managed)
            if POE_SETTLE:
                time.sleep(POE_SETTLE)
            linked, _elapsed = module.wait_for_link(cfg, port, cfg.link_wait)
            if linked is False:
                raise RuntimeError("the switch port did not link")

            _event(emit, "port_step", port=port, step="searching",
                   detail=f"trying {len(addresses)} candidate addresses")
            old_ip, before_serial, cidrs, reason = _discover(
                module, addresses, port, cfg, cancelled=cancelled)
            if not old_ip:
                raise RuntimeError(reason or "the display was not found")
            # There is no DeviceMap identity to claim here, so the row is
            # titled with the address the display actually answered on —
            # which is the most identifying thing this flow ever learns.
            _event(emit, "port_identified", port=port, deviceId="",
                   name=old_ip, source=old_ip, target=target_ip)
            _event(emit, "port_step", port=port, step="device_found",
                   detail=f"{old_ip} · {before_serial}")

            expected_cidr = f"{target_ip}/{prefix}"
            if old_ip == target_ip and cidrs == {expected_cidr}:
                _event(emit, "port_written", port=port,
                       reason="already_correct", target=target_ip)
            else:
                if cancelled is not None and cancelled():
                    raise RuntimeError("cancelled")
                _event(emit, "port_step", port=port, step="writing_ip",
                       detail=f"writing {expected_cidr}")
                _write_address(old_ip, target_ip, prefix)
                _event(emit, "port_written", port=port, reason="written",
                       target=target_ip)

            _event(emit, "port_step", port=port, step="verifying",
                   detail=f"reconnecting to {target_ip}")
            _disconnect(old_ip)
            _disconnect(target_ip)
            ok, reason = _reconnect_and_verify(
                module, target_ip, before_serial, port, cfg, prefix)
            if not ok:
                raise RuntimeError(reason)
            done = True
            _event(emit, "port_ok", port=port, target=target_ip)
        except Exception as exc:
            failure = str(exc)[:240] or type(exc).__name__
            _event(emit, "port_failed", port=port, reason=failure)
        finally:
            _disconnect(old_ip)
            _disconnect(target_ip)
    finally:
        restored = _restore(module, cfg, state, managed, emit)

    _event(emit, "phase", phase="verify")
    _event(emit, "summary_row", port=port, target=target_ip,
           status="ok" if done else "missing",
           reason=failure or "not reached")

    if cancelled is not None and cancelled():
        return 130
    return 0 if done and restored else 1


__all__ = ["TARGET_PREFIX", "addresses", "commissioning_ip", "connect",
           "disconnect", "manual_candidates", "run", "run_manual",
           "serial_of", "write_address"]
