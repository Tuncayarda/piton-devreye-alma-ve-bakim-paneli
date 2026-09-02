#!/usr/bin/env python3
"""Light refresh and device credentials."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ... import credentials as credential_store
from ... import jobs, settings, status
from ...adb.runner import RUNNER as ADB_RUNNER
from ...probe import reader
from ..presenters import (cached_telemetry,
                          collect_telemetry, credentials_for, device_dto,
                          find_device, inventory_for_write, probe_context,
                          state_body, store_telemetry)
from ..response import respond
from ... import i18n


def post_refresh(body):
    """A light refresh of the verified devices.

    Does not run while a full scan is in progress: two requests reaching the
    same device tires it and mixes up the results.

    Nor while a run that WRITES to devices (IP assignment, configuration,
    firmware) is in progress. The queue has one worker, so a full scan can
    never collide with those runs; a light refresh, however, reads on the
    request's own thread without entering the queue — that is the only path
    that can collide. During a run a device is rebooting or its PoE port is
    off, and an interleaved read would record that temporary state as the
    result.

    NOR WHILE THE ADB SCREEN IS WORKING, and that check cannot be folded
    into the two above because it is not a job: that screen runs outside the
    queue on purpose (see `panel.adb.runner`), so nothing in `jobs.QUEUE`
    mentions it. The collision is real and is the worst one available —
    both this round and that screen talk to a Compartment LCD over the same
    global ADB server, and a refresh landing mid-install takes the transport
    out from under it.
    """
    inventory = inventory_for_write(body.get("set"))
    # THE CLAIM, NOT A GLANCE. Three separate looks used to guard this round
    # (an active scan, a writing job, the ADB runner) and every one was
    # check-then-act: a job the single worker was one tick from starting
    # passed all three and then owned the devices this thread was reading.
    # The round now holds the same process-wide claim the workers hold
    # (panel/jobs/access.py) for the whole of its reads; the looks below
    # only choose the words a refusal is delivered in.
    if not jobs.access.try_acquire("refresh"):
        if jobs.QUEUE.active(f"scan:{inventory.set_no}"):
            return respond(409, {"error": i18n.t("error.fullScanRunning"),
                                 "waiting": True})
        writing = jobs.writing(inventory.set_no)
        if writing is not None:
            return respond(409, {"error": i18n.t("error.jobRunning",
                                                 title=writing.title),
                                 "waiting": True})
        if ADB_RUNNER.busy() or jobs.access.holder() == "adb-screen":
            return respond(409, {"error": i18n.t("error.adbRunnerBusy"),
                                 "waiting": True})
        # Anything else — another set's job, a claim mid-handover — is
        # named by the claim's own translator.
        return respond(409, {"error": jobs.busy_error(), "waiting": True})
    try:
        return _refresh_locked(inventory, body)
    finally:
        jobs.access.release("refresh")


def _refresh_locked(inventory, body):
    """The round itself, run while this thread holds the device claim."""
    view = jobs.view_for(inventory.set_no)
    requested = body.get("devices")
    if requested is not None and not isinstance(requested, list):
        raise ValueError(i18n.t("error.devicesMustBeList"))

    targets = []
    for device in inventory.devices:
        result = view.get(device.id)
        if result is None or result.state != status.OK:
            continue                      # verified devices only
        if requested and device.id not in requested:
            continue
        targets.append(device)
    targets = targets[:settings.REFRESH_LIMIT]

    snapshot = None
    # kyland and adb are in the list too: a switch cannot always report its
    # own uptime, nor an Android panel its SIP extension, and both are
    # completed from telemetry (see probe.reader). The PROBE method is what
    # the refresh is about to dispatch on, so it is what is asked — and it
    # is "mqtt" on every direct rule now, so the snapshot is the base of
    # every broker-first read in the round.
    if any((device.probe_method or device.read_method)
           in ("mqtt", "app", "kyland", "adb")
           for device in targets):
        snapshot = cached_telemetry(inventory.set_no)
        if snapshot is None:
            # Cache empty — the discovery round cannot have run yet. Collect
            # once; later rounds read from there.
            try:
                snapshot = collect_telemetry(inventory)
                store_telemetry(inventory.set_no, snapshot)
            except Exception:
                snapshot = None

    # The read contract in one place — see presenters.probe_context.
    context = probe_context(inventory)
    # Same fence as the full sweep (jobs/sweep.py): the view object survives
    # a project switch, this round's results must not.
    epoch = view.epoch

    # Read in parallel. Serially, the round ITSELF grew with the device count
    # (~7 s for 17 devices); the UI refreshing every two seconds then meant
    # nothing, because the "live" data was seven seconds old.
    def one(device):
        # The generation is taken right BEFORE the read: a parallel round
        # needs a number per device, not per round (see jobs.sweep_devices).
        generation = jobs.next_generation()
        result = reader.read_device(
            device, credentials=credentials_for(device), telemetry=snapshot,
            timeout=min(settings.PROBE_TIMEOUT, 3.0), **context)
        result.generation = generation
        view.write(device.id, result, epoch=epoch)

    if targets:
        pool = ThreadPoolExecutor(
            max_workers=min(settings.REFRESH_WORKERS, len(targets)))
        try:
            list(pool.map(one, targets))
        finally:
            pool.shutdown(wait=True)

    return respond(200, {**state_body(inventory),
                         "refreshed": [device.id for device in targets]})


def post_credentials(body):
    """Try the credentials the user entered ON THE SELECTED DEVICE.

    A filled-in form does not count as proof; a credential is only stored once
    verified data really came back from the device.
    """
    inventory = inventory_for_write(body.get("set"))
    device = find_device(inventory, body.get("deviceId"))
    username = body.get("username", "")
    password = body.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValueError(i18n.t("error.credentialsMustBeText"))
    if not username.strip():
        raise ValueError(i18n.t("error.usernameRequired"))
    if len(username) > 128 or len(password) > 256:
        raise ValueError(i18n.t("error.credentialsTooLong"))

    share = body.get("applyToGroup") is True
    group = reader.credential_group(device)

    generation = jobs.next_generation()
    # The DEVICE's own protocol, named explicitly: this flow exists to prove
    # a password against the thing that asked for it. On a broker-probed
    # (GDM) device the default dispatch would go to the DeviceMap record,
    # which knows no passwords and — with no telemetry in this route — would
    # answer grey, so no credential could ever be verified. Naming the
    # method is a no-op everywhere else: probe and read agree there.
    result = reader.read_device(
        device, credentials=(username, password), telemetry=None,
        timeout=settings.AUTH_TIMEOUT, method=device.read_method,
        **probe_context(inventory))
    result.generation = generation
    view = jobs.view_for(inventory.set_no)

    if result.state == status.OK:
        # Order matters: verified by the device first, then stored in memory.
        credential_store.remember(device.id, device.ip, username, password,
                                  group=group, share_with_group=share)
        view.write(device.id, result)
        return respond(200, {
            "result": "verified",
            "device": device_dto(device, view.get(device.id)),
            "state": state_body(inventory),
            "appliedToGroup": bool(share and group),
        })

    # FAILED: a working credential already in memory is not overwritten.
    existing = view.get(device.id)
    if existing is None or existing.state != status.OK:
        view.write(device.id, result)

    message = {
        status.AUTH_REQUIRED: i18n.t("error.credentialsUnverified"),
        status.UNVERIFIED: (result.detail
                            or i18n.t("error.responseUnverified")),
    }.get(result.verification,
          result.detail or i18n.t("error.deviceUnreadable"))
    code = 401 if result.verification == status.AUTH_REQUIRED else 502
    return respond(code, {
        "result": result.verification, "error": message,
        "device": device_dto(device, view.get(device.id)),
    })


def post_credentials_forget(body):
    if body.get("all") is True:
        credential_store.forget_all()
        # The video transport's digest handlers were built from these
        # credentials; forgetting means forgetting there too.
        from ...video_config import isapi                  # noqa: PLC0415
        isapi.reset()
        return respond(200, {"forgotten": "all"})
    inventory = inventory_for_write(body.get("set"))
    device = find_device(inventory, body.get("deviceId"))
    credential_store.forget(device.id, device.ip)
    return respond(200, {"forgotten": device.id})


GET: dict = {}

POST = {
    "/api/refresh": post_refresh,
    "/api/credentials": post_credentials,
    "/api/credentials/forget": post_credentials_forget,
}
