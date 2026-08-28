#!/usr/bin/env python3
"""The ADB screen: the device pool, and the operation running on it.

Two halves, and they are asked about separately on purpose.

`GET /api/adb` is the whole screen — the address list plus whatever the
runner is doing. It is what opening the screen fetches.

`GET /api/adb/state` is the runner alone, and it is polled every second while
an operation runs. Sending the pool back with it would mean re-reading and
re-sending a list of addresses that cannot have changed, sixty times a
minute; the runner's `generation` counter is there so the client can tell in
one integer whether anything moved (see `panel.adb.runner`).

The screen is an ADMIN one, so `panel.api.guard` refuses every path below
unless the service key is in. The reason is written once, in
`panel/editions/catalogue.py` beside the list itself — this file used to
restate it, which is how the copy here came to say the opposite of the
decision after the screen was moved.

What matters at THIS end is that the guard matches by prefix: `/api/adb`
covers every path in the tables below, including the next one added.
"""
from __future__ import annotations

import threading
from pathlib import Path

from ... import i18n
from ...adb import apps, autostart, packages, pool
from ...adb.runner import RUNNER, RunnerBusy
from ...system import files
from ..response import respond

# The one file type this screen installs.
APK = "apk"

# The APK the operator chose, as an absolute path on THIS machine. Session
# only — never written to disk, never sent to the browser, and gone when the
# application closes. See `post_apk` for why the browser is not given it.
_APK_LOCK = threading.Lock()
_CHOSEN_APK = ""


def _body() -> dict:
    return {"devices": pool.load(), "runner": RUNNER.state(),
            "operations": list(apps.OPERATIONS)}


def get_adb(_query):
    return respond(200, _body())


def get_adb_state(_query):
    return respond(200, RUNNER.state())


def _ips(body) -> list[str]:
    raw = body.get("devices")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(i18n.t("error.devicesMustBeList"))
    return [str(item) for item in raw]


def post_devices(body):
    """Add or remove one address, or replace the whole list.

    One endpoint for all three because they are one thing to the screen:
    every reply is the list as it now stands, so the table never has to work
    out what changed.
    """
    action = str(body.get("action") or "add").strip().lower()
    if action == "remove":
        return respond(200, {"devices": pool.remove(body.get("ip"))})
    if action == "replace":
        return respond(200, {"devices": pool.replace_all(body.get("devices"))})
    if action == "clear":
        return respond(200, {"devices": pool.clear()})
    if action != "add":
        raise ValueError(i18n.t("error.adbUnknownOperation", operation=action))
    # One box, several addresses: a list, a range, or both. `added` is part of
    # the answer rather than a detail — "10.1.1.45-47" that adds one because
    # the other two were already there is worth saying out loud.
    devices, added = pool.add_many(body.get("ip"), body.get("label", ""))
    return respond(200, {"devices": devices, "added": added})


def post_import(body):
    """Read a list somebody sent, through the operating system's own dialog.

    The path never comes from the client — the browser does not reveal one,
    and accepting a typed path would make this "read any file on this
    machine". Same shape as the firmware picker: a cancelled dialog is a 200
    saying so, not an error.
    """
    if body.get("path"):
        # The headless form, for tests and a scripted run. The UI never
        # sends a path.
        chosen = str(body.get("path"))
    else:
        try:
            chosen = files.pick_file(i18n.t("adb.importTitle"), ("json",))
        except RuntimeError as exc:
            return respond(500, {"error": str(exc)})
        if not chosen:
            return respond(200, {"cancelled": True})
    entries, skipped = pool.read_import(chosen)
    devices, added = pool.merge(entries)
    return respond(200, {"devices": devices, "imported": added,
                         "skipped": skipped,
                         "duplicates": len(entries) - added,
                         "file": Path(chosen).name})


def post_export(body):
    """Write the address list where the OPERATOR SAYS, through the OS dialog.

    It used to go to the Documents folder without asking, which is where the
    panel puts everything it produces. That is the right default for a file
    the panel itself will find again; this one is carried away on a stick or
    attached to an e-mail, and the person doing that has a folder in mind.

    The path still never comes from the client — the same rule the import
    above follows. The dialog runs in the operator's own session and only
    what it returned is written, so this cannot be turned into "write a file
    anywhere on this machine" by a crafted request. A cancelled dialog is a
    200 saying so, not an error.
    """
    if body.get("path"):
        # The headless form, for tests and a scripted run. The UI never
        # sends a path.
        chosen = str(body.get("path"))
    else:
        try:
            chosen = files.pick_save_path(i18n.t("adb.exportTitle"),
                                          pool.EXPORT_NAME, ("json",))
        except RuntimeError as exc:
            return respond(500, {"error": str(exc)})
        if not chosen:
            return respond(200, {"cancelled": True})
    try:
        path = pool.write_export(chosen)
    except OSError as exc:
        return respond(500, {"error": i18n.t("error.adbExportFailed",
                                             reason=str(exc))})
    return respond(200, {"file": path.name, "path": str(path),
                         "count": len(pool.load())})


def post_packages(body):
    """Which bundles on the selected devices match this word."""
    return respond(200, packages.search(_ips(body), body.get("keyword", "")))


def post_apk(body):
    """Choose the APK to install. ONLY ITS NAME COMES BACK.

    The path stays on this side. The browser has never seen a real one — the
    sandbox does not reveal it — and handing one out only to accept it back
    on `/api/adb/run` would turn that endpoint into "install any file on this
    machine", which is not a thing a local service should offer either (the
    same reasoning as `panel.system.files.open_path`, and the same
    arrangement the firmware screen uses for its selection).

    In memory and for this session only, like the firmware screen's
    selection: the panel never copies or keeps the file.
    """
    try:
        chosen = files.pick_file(i18n.t("adb.apkTitle"), (APK,))
    except RuntimeError as exc:
        return respond(500, {"error": str(exc)})
    if not chosen:
        return respond(200, {"cancelled": True})
    if Path(chosen).suffix.lower() != f".{APK}":
        # The OS filter is presentation only — macOS in particular classifies
        # an APK as `public.data` and cannot filter on it (see
        # `panel.system.files`). The suffix is enforced here, after the
        # choice.
        raise ValueError(i18n.t("error.fileExtensionMismatch",
                                extension=APK))
    with _APK_LOCK:
        global _CHOSEN_APK
        _CHOSEN_APK = chosen
    return respond(200, {"name": Path(chosen).name})


def _chosen_apk() -> str:
    with _APK_LOCK:
        return _CHOSEN_APK


def post_autostart_state(body):
    """Is the autostart in place on this one device?

    Deliberately one device rather than the selection: the answer is used to
    label a button, and asking twelve displays over ADB to decide what one
    button says is not a trade worth making. The operator asks about the
    device they are looking at.
    """
    ips = _ips(body)
    if len(ips) != 1:
        raise ValueError(i18n.t("error.adbOneDeviceOnly"))
    return respond(200, autostart.state(ips[0], body.get("package", "")))


def post_autostart_files(body):
    """Which two files an autostart install would write. Touches no device.

    The confirmation dialog lists them by full path, and it has to be the
    SAME paths the write uses. Assembling them in the browser from the
    package name would put that naming rule in two places, and the day they
    drift the dialog promises one file while another is left on the
    hardware — on the system partition, where it survives a factory reset.
    """
    package = apps.clean_package(body.get("package", ""))
    return respond(200, {"package": package,
                         "files": list(autostart.files(package))})


def _targets(body):
    """What the run works on: (device, bundle) pairs, or plain addresses.

    `targets` is what the screen sends — it knows which bundle the search
    found on which device, and sends only the pairs that exist. `devices` is
    the older, simpler shape and still right for installing an APK, where
    the package comes out of the file rather than off the screen.
    """
    raw = body.get("targets")
    if raw is None:
        return _ips(body)
    if not isinstance(raw, list):
        raise ValueError(i18n.t("error.devicesMustBeList"))
    pairs = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(i18n.t("error.devicesMustBeList"))
        pairs.append({"ip": str(entry.get("ip") or ""),
                      "package": str(entry.get("package") or ""),
                      "activity": str(entry.get("activity") or "")})
    return pairs


def post_run(body):
    """Start the operation. Returns immediately; the screen polls."""
    parameters = {
        "package": body.get("package", ""),
        "activity": body.get("activity", ""),
        # NOT from the request. The client asked for a file and was told its
        # name; the path it names is the one this side chose.
        "path": _chosen_apk(),
    }
    try:
        state = RUNNER.start(str(body.get("operation") or ""),
                             _targets(body), parameters)
    except RunnerBusy as exc:
        # The same shape the queue uses when it refuses a second run, so the
        # client's existing "it is busy, try again" handling applies.
        return respond(409, {"error": str(exc), "waiting": True})
    return respond(200, state)


def post_cancel(_body):
    return respond(200, RUNNER.cancel())


GET = {
    "/api/adb": get_adb,
    "/api/adb/state": get_adb_state,
}

POST = {
    "/api/adb/devices": post_devices,
    "/api/adb/import": post_import,
    "/api/adb/export": post_export,
    "/api/adb/packages": post_packages,
    "/api/adb/apk": post_apk,
    "/api/adb/autostart": post_autostart_state,
    "/api/adb/autostart/files": post_autostart_files,
    "/api/adb/run": post_run,
    "/api/adb/cancel": post_cancel,
}
