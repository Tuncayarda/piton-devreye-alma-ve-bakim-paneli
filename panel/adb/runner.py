#!/usr/bin/env python3
"""One operation, several devices, a table that fills in while it runs.

THIS IS NOT THE JOB QUEUE, AND THAT IS DELIBERATE. The queue
(`panel.jobs`) exists for runs that belong to the project: they are named
after a train set, they show in the history, and the single worker is what
keeps two of them from reaching the same device. This screen has no train
set and no project — its devices are addresses somebody typed in — so a run
here has nothing to be listed under and nothing to serialise against. Put in
the queue it would sit behind a scan of a device list it has never heard of.

What it borrows instead is the shape `panel.adminkey.watcher` and
`panel.telemetry.monitor` already use, because the browser polls and does not
listen: a module singleton, started by a POST, read by a GET.

    RUNNER.start(operation, targets, params)   returns at once
    RUNNER.state()                             what the screen draws
    RUNNER.cancel()
    RUNNER.busy()

A TARGET IS A DEVICE AND A BUNDLE, not a device. It began as one bundle
across several devices, which is the wrong shape for the bench it is used
on: four displays there routinely run three different customers'
applications, and "restart the application on all of them" means a different
package name on each. So a run carries pairs —

    [{"ip": "10.1.1.45", "package": "com.piton.gebze"},
     {"ip": "10.1.1.47", "package": "com.piton.darica"}]

— and the screen builds them from what the search actually FOUND on each
device. That is also what stops a command being sent about a package a
device does not carry: such a pair is never built, so no worker ever
connects to that display to be told "no such package".

A bare address is still accepted and takes its package from `params`; that
is the right shape for installing an APK, where the package is inside the
file rather than chosen.

Four decisions in here were paid for elsewhere in this panel and are repeated
on purpose:

* **The rows exist before the pool does.** Building them as results arrive
  means the operator watches a table grow from nothing and cannot tell a
  device that has not started from one that was never included
  (`panel.jobs.job`).
* **A device that fails writes a row, it does not end the run.** Twelve
  displays on a bench, one with a cable out — the other eleven are still the
  work.
* **`generation` counts CHANGES, not polls.** The screen asks once a second;
  without this it would redraw the whole table every second for an hour-long
  install (`panel.adminkey.watcher`).
* **Cancelling is checked BEFORE a device, never during one.** An APK
  install cut in half leaves a device with no working application, which is
  worse than the wait the operator was trying to stop
  (`panel.api.tasks.firmware_task`).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from .. import i18n, settings
from ..errors import UnreachableError, user_message
from . import apps, autostart, client

# Row states. The same words the job queue uses for its rows, so the screen's
# colours can follow the panel's existing status vocabulary.
PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

# States a row does not leave. A row reaching one of these is what writes a
# line in the log below.
FINISHED = (DONE, FAILED, CANCELLED)

# How many finished rows are kept. THE RUN TABLE SHOWS THE RUN; this is the
# afternoon behind it — the five runs before this one, which is what the
# operator is actually asked about ("did that display ever come back?"). The
# screen scrolls it and shows twenty at a time, so the number here only has
# to be larger than a bench session's worth of work, and small enough that
# every one-second poll can carry it without thinking about it.
LOG_LIMIT = 120


class AdbRunner:
    """The ADB screen's worker. One operation at a time, several devices."""

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._operation = ""
        self._params: dict = {}
        self._rows: dict[str, dict] = {}
        self._targets: dict[str, dict] = {}
        self._order: list[str] = []
        self._running = False
        self._started_at = 0.0
        self._finished_at = 0.0
        self._generation = 0
        # Finished rows, oldest first. See LOG_LIMIT.
        self._log: deque[dict] = deque(maxlen=LOG_LIMIT)

    # ── what the screen reads ────────────────────────────────────────────
    def busy(self) -> bool:
        with self._lock:
            return self._running

    def state(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "operation": self._operation,
                "package": str(self._params.get("package") or ""),
                "generation": self._generation,
                "cancelling": self._running and self._cancel.is_set(),
                "startedAt": self._started_at or None,
                "finishedAt": self._finished_at or None,
                "rows": [dict(self._rows[key]) for key in self._order],
                # Oldest first here, newest first on the screen — the
                # order is the screen's decision, not this module's.
                "log": [dict(entry) for entry in self._log],
            }

    # ── starting ─────────────────────────────────────────────────────────
    def start(self, operation: str, targets, params: dict | None = None
              ) -> dict:
        """Begin. Raises when something is already running.

        The caller turns that into 409: two operations at once would have
        two threads reaching the same display, which is the collision the
        rest of the panel takes such care to avoid.
        """
        name = str(operation or "").strip()
        if name not in apps.OPERATIONS:
            raise ValueError(i18n.t("error.adbUnknownOperation",
                                    operation=name or "?"))
        params = dict(params or {})
        pairs = _pairs(targets, params, name)
        if not pairs:
            raise ValueError(i18n.t("error.adbNoDeviceSelected"))

        with self._lock:
            if self._running:
                raise RunnerBusy(i18n.t("error.adbRunnerBusy"))
            self._cancel.clear()
            self._operation = name
            self._params = params
            # Built here, before a single worker starts, so the first poll
            # already shows every pair the operator selected.
            self._order = [_key(pair) for pair in pairs]
            self._rows = {_key(pair): {"ip": pair["ip"],
                                       "package": pair["package"],
                                       "state": PENDING, "detail": "",
                                       "result": None} for pair in pairs}
            self._targets = {_key(pair): pair for pair in pairs}
            self._running = True
            self._started_at = time.time()
            self._finished_at = 0.0
            self._generation += 1
            self._thread = threading.Thread(
                target=self._run, name="panel-adb-runner", daemon=True)
            self._thread.start()
        return self.state()

    def cancel(self) -> dict:
        """Ask the run to stop after the device it is on."""
        with self._lock:
            if self._running and not self._cancel.is_set():
                self._cancel.set()
                self._generation += 1
        return self.state()

    def reset(self) -> None:
        """Forget the last run. Tests, and leaving the screen."""
        self.cancel()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=30.0)
        with self._lock:
            self._operation = ""
            self._params = {}
            self._rows = {}
            self._targets = {}
            self._order = []
            self._running = False
            self._started_at = self._finished_at = 0.0
            self._log.clear()
            self._generation += 1

    # ── the run itself ───────────────────────────────────────────────────
    def _run(self) -> None:
        try:
            self._sweep(list(self._order))
            # THE SERVER, NOT THE BENCH. Every row failing to connect is not
            # twelve dead displays; it is the daemon on this computer, and it
            # gets stuck often enough to be worth one automatic attempt (see
            # panel/adb/client.py). One retry, and only when EVERY row failed
            # that way — a run where three of four worked has three healthy
            # transports that a restart would drop for nothing.
            #
            # BETWEEN ROUNDS, never inside one. `_sweep` has returned, so its
            # pool is shut down and no command is in flight; restarting the
            # server here cannot pull a socket out from under a thread.
            if self._should_recover() and self._recover_server():
                self._sweep(list(self._order))
        finally:
            with self._lock:
                self._running = False
                self._finished_at = time.time()
                self._generation += 1

    def _sweep(self, targets: list[str]) -> None:
        """One pass over these rows, in parallel."""
        if not targets:
            return
        pool = ThreadPoolExecutor(
            max_workers=max(1, min(settings.ADB_WORKERS, len(targets))))
        try:
            list(pool.map(self._one, targets))
        finally:
            pool.shutdown(wait=True)

    def _should_recover(self) -> bool:
        """Did this run fail in the shape a wedged ADB server makes?"""
        if self._operation in apps.HOST_OPERATIONS or self._cancel.is_set():
            return False
        with self._lock:
            rows = list(self._rows.values())
        return bool(rows) and all(
            row.get("state") == FAILED and row.get("connection") for row in rows)

    def _recover_server(self) -> bool:
        """Restart the ADB server once, and say whether it came back."""
        try:
            return bool(client.restart_server().get("ok"))
        except Exception:
            return False

    def _one(self, key: str) -> None:
        with self._lock:
            target = dict(self._targets.get(key) or {})
        ip = target.get("ip", "")
        if self._cancel.is_set():
            self._write(key, CANCELLED, i18n.t("adb.rowCancelled"))
            return
        self._write(key, RUNNING, "")
        try:
            result = self._perform(target)
        except Exception as exc:
            # One pair's failure is one row. The pool carries on; see the
            # module docstring.
            #
            # WHY the failure is recorded and not only its words: "could not
            # be reached" is the one shape that may be the ADB server rather
            # than the device, and `_should_recover` above reads it.
            self._write(key, FAILED, user_message(exc),
                        connection=isinstance(exc, UnreachableError))
        else:
            self._write(key, DONE, self._detail(result), result)
        finally:
            # The transport is global to the ADB server, so a serial left
            # connected is a serial the next operation may reach by
            # accident. Two pairs can share one address, so this runs once
            # per pair and disconnecting twice is harmless.
            #
            # `connect` is the exception and the whole point of it: it exists
            # to leave the display attached so `adb devices` lists it (see
            # apps.KEEP_CONNECTED).
            if self._operation not in apps.KEEP_CONNECTED:
                client.disconnect(ip)

    def _perform(self, target: dict):
        operation = self._operation
        params = dict(self._params)
        ip = target.get("ip", "")
        package = target.get("package") or params.get("package") or ""
        activity = target.get("activity") or params.get("activity") or ""
        if operation == "restart_server":
            return apps.restart_server()
        if operation == "connect":
            return apps.connect(ip)
        if operation == "start":
            return apps.start(ip, package, activity)
        if operation == "stop":
            return apps.stop(ip, package)
        if operation == "restart":
            return apps.restart(ip, package, activity)
        if operation == "uninstall":
            return apps.uninstall(ip, package)
        if operation == "install":
            return apps.install(ip, params.get("path"))
        if operation == "reboot":
            return apps.reboot(ip)
        if operation == "autostart_install":
            return autostart.install(ip, package, activity)
        if operation == "autostart_remove":
            return autostart.remove(ip, package)
        raise ValueError(i18n.t("error.adbUnknownOperation",
                                operation=operation or "?"))

    @staticmethod
    def _detail(result) -> str:
        """One line saying what actually happened on this device."""
        if not isinstance(result, dict):
            return ""
        if result.get("action") == "install":
            current = str(result.get("current") or "")
            return i18n.t("adb.rowInstalled", version=current) if current \
                else i18n.t("adb.rowDone")
        if result.get("action") == "autostart_install":
            return i18n.t("adb.rowAutostartVia",
                          route=str(result.get("route") or ""))
        if result.get("action") == "restart_server":
            return i18n.t("adb.rowServerRestarted")
        if result.get("action") == "connect":
            return i18n.t("adb.rowConnected",
                          serial=str(result.get("serial") or ""))
        if result.get("action") == "reboot":
            # How long it took to answer again, because that is the number
            # an operator compares displays by when one of them is sick.
            return i18n.t("adb.rowRebooted",
                          seconds=result.get("seconds", 0))
        return i18n.t("adb.rowDone")

    def _write(self, key: str, state: str, detail: str, result=None, *,
               connection: bool = False) -> None:
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                return
            changed = (row["state"] != state or row["detail"] != detail
                       or result is not None)
            row["state"] = state
            row["detail"] = detail
            # Not shown anywhere; read by `_should_recover`.
            row["connection"] = connection
            if result is not None:
                row["result"] = result
            # A row that has finished writes a line, once. `_write` is
            # called with `running` first and can be called twice with the
            # same result when the server is restarted between rounds (see
            # `_run`), so the guard is both the state and the change.
            if changed and state in FINISHED:
                self._log.append({
                    "at": time.time(),
                    "operation": self._operation,
                    "ip": row["ip"],
                    "package": row["package"],
                    "state": state,
                    "detail": detail,
                })
            # Only a real change moves the counter — a one-second poll must
            # not cost a redraw when nothing has happened.
            if changed:
                self._generation += 1


def _key(pair: dict) -> str:
    """What identifies a row.

    The address alone will not do any more: one display can carry two of the
    selected bundles, and both are real work with their own result.
    """
    return f"{pair['ip']}\u0000{pair['package']}"


def _pairs(targets, params: dict, operation: str = "") -> list[dict]:
    """(device, bundle) pairs, in the order given and without duplicates.

    A plain address is accepted and takes its package from `params` — the
    right shape for installing an APK, whose package is inside the file
    rather than chosen on screen.

    FOR A DEVICE-LEVEL OPERATION THE BUNDLE IS DROPPED FIRST, and that is
    what collapses the pairs back to one row per address. Rebooting is the
    case that makes it necessary: a display carrying two of the selected
    bundles produces two pairs, and two pairs would send that machine the
    reboot command twice — once while it is already on its way down.
    """
    # The host operation reaches no device, so it is ONE row whatever was
    # selected — and it must produce a row even with nothing selected at all,
    # which is exactly when an operator reaches for it.
    if operation in apps.HOST_OPERATIONS:
        return [{"ip": "", "package": "", "activity": ""}]
    per_device = operation in apps.DEVICE_OPERATIONS
    fallback = "" if per_device else str(params.get("package") or "")
    pairs, seen = [], set()
    for target in (targets or []):
        if isinstance(target, dict):
            ip = str(target.get("ip") or "").strip()
            package = str(target.get("package") or fallback).strip()
            activity = str(target.get("activity") or "").strip()
        else:
            ip, package, activity = str(target or "").strip(), fallback, ""
        if not ip:
            continue
        if per_device:
            package, activity = "", ""
        pair = {"ip": ip, "package": package, "activity": activity}
        key = _key(pair)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(pair)
    return pairs


class RunnerBusy(RuntimeError):
    """Something is already running on these devices."""


RUNNER = AdbRunner()
