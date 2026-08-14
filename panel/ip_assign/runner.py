#!/usr/bin/env python3
"""Executing the assignment run in-process."""
from __future__ import annotations

import contextlib
import io
import sys
import threading
from types import SimpleNamespace

from .. import credentials as credential_store
from .. import script_loader, settings
from ..errors import AuthError
from ..inventory.device_map import Inventory, resolve_template
from .addressing import factory_ip, search_candidates
from .plan import devices_by_port, resolve_groups
from .ports import assert_not_protected, format_ports
from .. import i18n

# main() touches the process-wide sys.stdout/sys.argv, so only one run at a
# time. The job queue already runs one job; this is the second guard.
_RUN_LOCK = threading.Lock()


class _LineStream(io.TextIOBase):
    """Feeds the script's output to a callback line by line.

    It is also where cancellation reaches the script. The script runs
    in-process as main(); setting a flag from outside does not stop it because
    nobody reads the flag. Its constant output, however, passes through here:
    when cancel is requested, the next print raises KeyboardInterrupt.

    KeyboardInterrupt is deliberate: the script already catches it, says
    "reopening the ports" and reopens every PoE port in range (finally). So
    cancelling takes the same path as Ctrl-C and no port is left closed. Being
    a BaseException, the script's own `except Exception` blocks do not swallow
    it.
    """

    def __init__(self, callback, cancelled=None):
        self._callback = callback
        self._cancelled = cancelled
        self._raised = False
        self._buffer = ""

    def _check_cancel(self):
        # Raised only once: the script writes while reopening the ports too,
        # and raising on every write would cut its own recovery step short and
        # leave the ports closed.
        #
        # Never raised mid-line either: print writes the text and then the
        # newline, and interrupting between them left half a line in the
        # buffer to be glued onto the next one.
        if self._buffer or self._raised:
            return
        if self._cancelled is None or not self._cancelled():
            return
        self._raised = True
        raise KeyboardInterrupt

    def write(self, text):
        self._buffer += text
        while "\n" in self._buffer:
            line, _, self._buffer = self._buffer.partition("\n")
            if line.strip():
                self._callback(line.rstrip())
        self._check_cancel()
        return len(text)

    def flush(self):
        if self._buffer.strip():
            self._callback(self._buffer.rstrip())
            self._buffer = ""


def script_config(factory: str, switch_ip: str):
    """The settings object the script's read_settings/write_ip/wait_gone want.

    Field names and defaults match the script's own argparse, so the write
    body and endpoints stay exactly as they are there — no second client.
    """
    return SimpleNamespace(
        arduino_port=settings.ANNOUNCEMENT_PORT,
        write_endpoint="api/v1/network/ip",
        # 2 s is too tight for an unresolved address: right after the ARP
        # entry is dropped, resolution may not fit (see factory_reset.probe).
        probe_timeout=3.0,
        timeout=8.0,
        netmask=settings.EXPECTED_SUBNET_MASK,
        gateway=switch_ip,
        ntp_ip=None,
        factory_ip=factory,
        full_net_payload=False,
        dry_run=False,
        # The pulse of the wait_gone/probe loops and ARP flushing: these come
        # from argparse in the script and are set explicitly here.
        poll_interval=1.0,
        arp_flush=True,
    )


def _run_intercom(inventory: Inventory, switch, ports: list[int], account,
                  emit, options: dict, cancelled=None) -> int:
    """The Intercom group's assignment script.

    The script opens ports one at a time: it closes every PoE port in range,
    opens only the target, finds whichever device comes up and writes the IP
    DeviceMap assigns to that port.

    It only works with SubType=Intercom records; on any other port it says
    "works with Intercom ports only" and exits. Hence the single entry
    in RUNNERS.
    """
    module = script_loader.intercom_ip_assign()
    argv = [
        "intercom_ip_assign.py",
        "--ports", *[str(port) for port in ports],
        "-n", str(inventory.set_no),
        "--device-map", str(inventory.source),
        "--switch-ip", switch.ip,
        "--kyland-port", str(settings.KYLAND_PORT),
        "--kyland-user", account[0],
        "--kyland-pass", account[1],
        "--arduino-port", str(settings.ANNOUNCEMENT_PORT),
    ]
    # The persistence check is OFF BY DEFAULT: at the end the script cuts and
    # restores power on every port to prove the setting reached flash. In the
    # field that blacks out devices that were already finished and lengthens
    # the run; the ordinary check already happens by reading back the target
    # IP after the write.
    #
    # But "written" and "written persistently" are not the same: a device may
    # have kept the setting in RAM only and returns to its old address on the
    # first power cut. Users who want to see that once at the end can enable
    # it (the "Verify persistence" box).
    if not options.get("persistenceCheck"):
        argv.append("--no-persist-check")
    else:
        emit("[Intercom] Persistence check on: at the end of the run the "
             "ports are power cycled once")
    # The factory address is always passed explicitly: the script's own
    # default is a template (10.n.1.12) resolved with the set number, while
    # devices always arrive on the same address regardless of set.
    factory = str(options.get("factoryIp") or "").strip() or factory_ip()
    argv += ["--factory-ip", factory]

    # The set-resolved address is tried as well. Before the factory address
    # was fixed, the run looked for devices at 10.n.1.12 and some field
    # devices still sit there; looking only at the fixed address marks them
    # "not found". Cost: one address. Cost of missing them: the whole run.
    extra = []
    set_address = resolve_template("10.n.1.12", inventory.set_no)
    if set_address != factory:
        extra.append(set_address)
    emit(f"[Intercom] Factory address: {factory}"
         + (f" ({set_address} is tried as well)" if extra else ""))

    # Extra candidates for devices not on the factory address. The script
    # already tries the factory IP and every intercom address in DeviceMap;
    # these are added on top.
    search = search_candidates(options.get("searchNetwork"),
                               options.get("searchNetmask"),
                               first=options.get("searchFirst") or "",
                               last=options.get("searchLast") or "")
    if search:
        emit(f"[Intercom] Extra search network: {len(search)} addresses "
             f"({search[0]} – {search[-1]})")
    extra = list(dict.fromkeys(extra + search))
    if extra:
        argv += ["--default-ip", *extra]
    return _execute(module, argv, emit, cancelled)


# Which group's assignment each script runs. Every device type's flow differs
# (PoE order, factory address, write endpoint), so there is no single
# "assign everything" script. New scripts are added here as they are written;
# a group absent from the table starts no run — showing a run that did nothing
# as "completed" would be the worst outcome.
RUNNERS = {
    "Intercom": _run_intercom,
}


def groups_without_runner(group_names) -> list[str]:
    """Selected groups that have no assignment script."""
    return [group["name"] for group in resolve_groups(group_names)
            if group["name"] not in RUNNERS]


def run(inventory: Inventory, switch_id: str, ports: list[int], emit,
        protected: dict[int, str] | None = None, groups=None,
        options: dict | None = None, cancelled=None) -> int:
    """Run the IP assignment. Returns the highest exit code.

    Each selected group runs in turn with its own script and its own ports:
    groups are not mixed into one call, because every device type's assignment
    flow differs.

    `emit(text)` is called for every output line of the script; the UI shows
    them in the job queue. No password enters this stream: the script only
    uses credentials in requests, never prints them.

    `protected` {port: reason}: ports the run must not touch. Since it cycles
    PoE, including the computer's port or the switch-to-switch link would cut
    the run's own path and leave it half done.
    """
    switch = inventory.find(switch_id)
    if switch is None:
        raise ValueError(i18n.t("error.switchNotFound"))
    if not ports:
        raise ValueError(i18n.t("error.noPortSelected"))
    assert_not_protected(ports, protected)

    # With no group given nothing is assumed: "which devices to assign" is not
    # something to guess.
    selected = resolve_groups(groups)
    if not selected:
        raise ValueError(
            i18n.t("error.intercomOnly"))
    missing = [group["name"] for group in selected
               if group["name"] not in RUNNERS]
    if missing:
        raise ValueError(
            i18n.t("error.noRunnerForGroup", groups=", ".join(missing)))

    account = credential_store.lookup(switch.id, switch.ip, group="switch")
    if not account:
        raise AuthError(
            i18n.t("error.noSwitchCredentials", switch=switch.name))

    # Each group gets only its own ports: handing one group's script another
    # group's port makes that script say "no device of mine here" and drop the
    # whole run.
    by_port = devices_by_port(inventory, selected, switch.id)
    code = 0
    for group in selected:
        group_ports = [port for port in ports
                       if by_port.get(port)
                       and by_port[port][1] == group["name"]]
        if not group_ports:
            emit(f"[{group['name']}] No device of this group on the "
                 "selected ports, skipped")
            continue
        emit(f"[{group['name']}] {format_ports(group_ports)} — assignment "
             "starting")
        code = max(code, RUNNERS[group["name"]](
            inventory, switch, group_ports, account, emit, options or {},
            cancelled))
        # Once cancelled, remaining groups are skipped.
        if cancelled and cancelled():
            emit("The remaining groups were cancelled")
            break
    return code


def _execute(module, argv, emit, cancelled=None) -> int:
    """Run the script in-process, forwarding its output line by line.

    main() touches the process-wide sys.argv/sys.stdout, so it runs under a
    lock (see _RUN_LOCK).

    On cancel the script goes through its own KeyboardInterrupt path: it
    reopens the ports, then returns here. The result is 130 (same as Ctrl-C)
    and the KeyboardInterrupt does not escape — the job queue must not read it
    as "the worker crashed".
    """
    with _RUN_LOCK:
        original_argv, original_stdout = sys.argv, sys.stdout
        stream = _LineStream(emit, cancelled)
        try:
            sys.argv = argv
            with contextlib.redirect_stdout(stream):
                code = module.main()
            stream.flush()
            return int(code or 0)
        except KeyboardInterrupt:
            stream.flush()
            emit("The run was stopped")
            return 130
        finally:
            sys.argv, sys.stdout = original_argv, original_stdout
