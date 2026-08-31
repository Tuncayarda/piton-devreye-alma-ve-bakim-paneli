#!/usr/bin/env python3
"""The switch screen: discovery, sign-in, ports, PoE and the switch's network.

TWO SHAPES OF ENDPOINT, and the split follows how long the work takes.

Everything that talks to ONE switch at a known address answers on the calling
thread: a port read or a PoE write is one request to one device, and the
screen wants the result, not a job to poll.

Discovery is not that. A /24 is 254 addresses and a sweep of it runs for
minutes, so it goes into the job queue like a scan does (`panel.jobs`) and the
screen polls. Running it inline blocked the bridge — every other screen froze
while a scan the operator started in the background was still going.

The results live here, in memory, for the same reason: reopening the screen
should show what the last scan found rather than starting another one. They
are dropped on shutdown with everything else (`panel.api.lifecycle`).

Credentials are never in this module's own state. Each handler looks the
switch's account up in `panel.credentials` under the shared "switch" group,
which is the account the IP assignment screen already uses — signing in here
signs in there (see `panel.ip_assign.factory_reset`).
"""
from __future__ import annotations

import threading

from ... import credentials, i18n, jobs, switch
# THIS MACHINE'S network, not the switch's. Both appear in this
# file — `network` below is the switch's own management address —
# and one of them has to say which it is.
from ...switch import device, network, ports, validation
from ...switch.discovery import DEFAULT_DISCOVERY_CIDR
from ..response import respond
from ..tasks.network_prepare import prepare_expression
from .helpers import submit

# What the last scan found, and the job that is filling it. Module level
# because the screen is one screen however many times it is opened, and a
# result that vanished when the operator looked at another tab would mean a
# fresh minute-long sweep every time they came back.
_LOCK = threading.Lock()
_DISCOVERED: list[dict] = []
_JOB_ID = ""


def _credentials(ip: str):
    """The account for one switch — its own, or the shared switch account.

    Keyed by the address twice over: this screen has no device id to work
    with, and `panel.credentials` wants both halves.
    """
    return credentials.lookup(ip, ip, group=device.GROUP)


def _scan_job():
    """The discovery job, if one is still in the queue."""
    with _LOCK:
        job_id = _JOB_ID
    return jobs.QUEUE.find(job_id) if job_id else None


def _scanning() -> bool:
    job = _scan_job()
    return bool(job and job.state in (jobs.QUEUED, jobs.RUNNING))


def _store(found: list[dict]) -> None:
    with _LOCK:
        _DISCOVERED[:] = found


def reset() -> None:
    """Forget the last scan. Called on shutdown and between projects."""
    global _JOB_ID
    with _LOCK:
        _DISCOVERED.clear()
        _JOB_ID = ""


def _body() -> dict:
    with _LOCK:
        found = list(_DISCOVERED)
    return {
        "discovered": found,
        "scanning": _scanning(),
        # The KEY, not the word: the screen renders it through its own
        # catalogue, the way it renders every other label it draws.
        "poeModes": [{"value": value, "labelKey": key}
                     for value, key in ports.POE_MODE.items()],
        "defaultCidr": DEFAULT_DISCOVERY_CIDR,
    }


# ---- reads -------------------------------------------------------------

def get_switch(_query):
    """The whole screen in one request, the way `/api/adb` is."""
    return respond(200, _body())


def get_info(query):
    ip = validation.query_ip(query)
    return respond(200, device.get_info(switch.CLIENT, ip, _credentials(ip)))


def get_ports(query):
    ip = validation.query_ip(query)
    return respond(200, {"ports": ports.get_ports(switch.CLIENT, ip,
                                                  _credentials(ip))})


# ---- discovery ---------------------------------------------------------

def _prepare_network(job: jobs.Job, expression: str) -> None:
    """Put the computer on the network about to be swept, if it is not.

    A sweep of 10.1.1.0-255 from a machine sitting on 10.17.1.222 finds
    nothing, and the result is indistinguishable from "there are no switches
    here": no packet ever left the network card. Every other operation in the
    panel already does this from the DeviceMap (`panel.api.tasks.
    network_prepare`); this screen has no DeviceMap, only the network the
    operator typed.

    Never fatal. The computer may reach the switches by a route this cannot
    see, and if it cannot, the empty result says more than a guess here.
    """
    target = switch.target_network(expression)
    if target is None:
        return
    # The shared reporter, not a private copy: the copy that lived here had
    # already drifted — it dropped the stranded-route warning, which exists
    # precisely because a stranded network fails every probe with the same
    # wording as "there are no switches here".
    prepare_expression(job, target)


def _discover_task(expression: str):
    def body(job: jobs.Job):
        job.add_row("scan", i18n.lazy("switch.jobDiscoveryRow"),
                    state="running",
                    note=i18n.lazy("switch.jobSearching", network=expression))
        _prepare_network(job, expression)
        if not switch.CLIENT.start_scan():
            raise RuntimeError(i18n.t("switch.errorScanInProgress"))
        # The job's own cancel flag drives the client's, so pressing stop in
        # the queue stops the sweep rather than only unlisting the job. The
        # watcher must also END with the sweep: it used to block on
        # `job.cancel.wait()` alone, and on a successful sweep nothing ever
        # sets that flag — one OS thread plus a pinned Job (rows and all)
        # leaked per discovery, on a screen made for sweeping repeatedly.
        # (Setting the flag from the finally instead would mark a finished
        # job CANCELLED — the queue reads it right after the body returns.)
        done = threading.Event()

        def watch():
            while not job.cancel.wait(0.25):
                if done.is_set():
                    return
            switch.CLIENT.scan_cancel_event.set()

        try:
            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            result = switch.CLIENT.discover(
                expression, cancel_event=switch.CLIENT.scan_cancel_event)
        finally:
            switch.CLIENT.finish_scan()
            done.set()
        _store(result["switches"])
        job.add_row(
            "scan", i18n.lazy("switch.jobDiscoveryRow"),
            state="done",
            note=i18n.lazy("switch.jobFound", count=len(result["switches"]),
                           probed=result["probed"]))
        job.set_progress(1.0)

    return body


def post_discover(body):
    """Start a sweep. Returns at once; the screen polls `/api/switch`."""
    global _JOB_ID
    expression = validation.text(body, "cidr", DEFAULT_DISCOVERY_CIDR).strip()
    # Parsed here rather than inside the job so a typed-in network that cannot
    # be a network is a 400 on the spot, not a job that fails a second later.
    switch.resolve_addresses(expression)
    if _scanning():
        return respond(409, {"error": i18n.t("switch.errorScanInProgress"),
                             "waiting": True})
    job = jobs.Job("switchscan",
                   i18n.lazy("switch.jobDiscoveryTitle", network=expression),
                   0, key="switchscan")
    response = submit(job, _discover_task(expression))
    with _LOCK:
        # The QUEUED job's id, which on a 202 is the EXISTING sweep's, not
        # the duplicate the screen just asked for.
        _JOB_ID = response.body["id"]
    return response


def post_discover_cancel(_body):
    job = _scan_job()
    if job is not None:
        jobs.QUEUE.cancel(job.id)
    return respond(200, {"stopped": switch.CLIENT.stop_scan(wait=2.0)})


# ---- session -----------------------------------------------------------

def _remember_identity(info: dict) -> None:
    """Update the scan result with what signing in just revealed.

    The stored list is what the screen draws, and until now nothing wrote
    back to it: a switch signed into carried on showing "sign in required"
    and an empty name until somebody swept the network again. The sweep is
    the expensive way to learn something the login reply already said.
    """
    with _LOCK:
        for index, entry in enumerate(_DISCOVERED):
            if entry.get("ip") == info.get("ip"):
                _DISCOVERED[index] = {**entry, **info}
                return
        # Signed into a switch that no sweep found — an address typed by
        # hand. It belongs on the list for the same reason the swept ones do.
        _DISCOVERED.append(dict(info))


def post_login(body):
    """Check an account and keep it in memory if the switch accepts it.

    The password arrives in this body and goes no further than
    `panel.credentials` — not to disk, not into a job row, not back to the
    browser in the reply.
    """
    ip = validation.body_ip(body)
    info = device.login(
        switch.CLIENT, ip,
        validation.text(body, "username", ""),
        validation.text(body, "password", ""),
        share_with_group=body.get("applyToGroup") is True)
    _remember_identity(info)
    return respond(200, info)


def post_logout(body):
    """Forget one switch's account, or every device's."""
    if body.get("all") is True:
        credentials.forget_all()
        return respond(200, {"ok": True, "all": True})
    ip = validation.body_ip(body)
    credentials.forget(ip, ip)
    return respond(200, {"ok": True, "ip": ip})


# ---- writes ------------------------------------------------------------

def _owned_by_run(ip: str):
    """The 409 for a switch an IP-assignment run holds right now, or None.

    The run drives PoE through the field script's own HTTP client, outside
    `switch.CLIENT`'s per-write lock — it holds the switch for MINUTES, and
    a lock held that long would hang every request here instead of
    answering. So the run leaves a claim (`panel.api.tasks.ip_task`) and
    the write endpoints refuse over it: a PoE or port-table write landing
    mid-run would overwrite the very ports the run just changed, with
    values this screen read before it started.
    """
    owner = switch.CLIENT.run_owner(ip)
    if not owner:
        return None
    return respond(409, {"error": i18n.t("switch.errorRunOwnsSwitch"),
                         "waiting": True})


def post_poe(body):
    ip = validation.body_ip(body)
    return _owned_by_run(ip) or respond(200, ports.set_poe(
        switch.CLIENT, ip, validation.port_id(body),
        validation.text(body, "mode"), _credentials(ip)))


def post_port(body):
    """Bring a port up or down, or write its whole configuration.

    One endpoint for both because the screen means one thing by it: the two
    are told apart by whether `enabled` is present, the way the switch panel
    has always done it.
    """
    ip = validation.body_ip(body)
    refused = _owned_by_run(ip)
    if refused is not None:
        return refused
    port = validation.port_id(body)
    if "enabled" in body:
        return respond(200, ports.set_port_enabled(
            switch.CLIENT, ip, port, validation.boolean(body, "enabled"),
            _credentials(ip)))
    return respond(200, ports.set_port_config(
        switch.CLIENT, ip, port, validation.mapping(body, "config"),
        _credentials(ip)))


def post_batch(body):
    ip = validation.body_ip(body)
    refused = _owned_by_run(ip)
    if refused is not None:
        return refused
    poe = validation.port_mapping(body, "poe", str)
    selected = validation.port_mapping(body, "ports",
                                       validation.boolean_value)
    if not poe and not selected:
        raise ValueError(i18n.t("switch.errorNoChanges"))
    return respond(200, ports.apply_batch(switch.CLIENT, ip, poe, selected,
                                          _credentials(ip)))


def post_network(body):
    ip = validation.body_ip(body)
    return _owned_by_run(ip) or respond(200, network.set_network(
        switch.CLIENT, ip,
        validation.text(body, "address"),
        validation.text(body, "prefix"),
        validation.text(body, "mtu", "1500"),
        credentials=_credentials(ip)))


def post_config_save(body):
    ip = validation.body_ip(body)
    return _owned_by_run(ip) or respond(200, device.save_configuration(
        switch.CLIENT, ip, _credentials(ip)))


def post_reboot(body):
    ip = validation.body_ip(body)
    return _owned_by_run(ip) or respond(200, device.reboot(
        switch.CLIENT, ip, _credentials(ip)))


def post_factory_reset(body):
    """Wipe the switch. The operator types the address to get here.

    Not a checkbox: this is the one operation on the screen that cannot be
    undone from the screen, and a mistyped address that matches nothing is a
    far better outcome than a confirmed reset of the wrong switch.
    """
    ip = validation.body_ip(body)
    if validation.text(body, "confirm", "").strip() != ip:
        raise ValueError(i18n.t("switch.errorConfirmationFailed"))
    return _owned_by_run(ip) or respond(200, device.factory_reset(
        switch.CLIENT, ip, _credentials(ip)))


GET = {
    "/api/switch": get_switch,
    "/api/switch/info": get_info,
    "/api/switch/ports": get_ports,
}

POST = {
    "/api/switch/discover": post_discover,
    "/api/switch/discover/cancel": post_discover_cancel,
    "/api/switch/login": post_login,
    "/api/switch/logout": post_logout,
    "/api/switch/poe": post_poe,
    "/api/switch/port": post_port,
    "/api/switch/batch": post_batch,
    "/api/switch/network": post_network,
    "/api/switch/config-save": post_config_save,
    "/api/switch/reboot": post_reboot,
    "/api/switch/factory-reset": post_factory_reset,
}
