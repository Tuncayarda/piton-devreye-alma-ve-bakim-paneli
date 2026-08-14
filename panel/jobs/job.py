#!/usr/bin/env python3
"""One background job: its rows, steps, counters and progress.

Job rows never contain a password, an Authorization header or a raw
traceback — only text that can be shown to the user.
"""
from __future__ import annotations

import threading
import time
import uuid
from .. import i18n

QUEUED, RUNNING, DONE, CANCELLED, FAILED = (
    "queued", "running", "done", "cancelled", "failed")

# Row states, which are richer than job states.
ROW_QUEUED, ROW_RUNNING, ROW_DONE = "queued", "running", "done"
ROW_AUTH, ROW_FAILED, ROW_SKIPPED = "auth", "failed", "skipped"
ROW_WARNING, ROW_INFO, ROW_WRITTEN = "warning", "info", "written"

# Cap on steps kept under one row. Steps go to the UI on every poll of an
# open job; unbounded they would bloat the response on a long run. The newest
# are the valuable ones, so the oldest are dropped.
STEP_LIMIT = 40


def _text(value, limit: int) -> str:
    """Render a stored value and cut it to length.

    Rows and titles hold raw text OR a deferred message; both arrive here on
    the way out. Truncating after rendering is the point: the two languages do
    not have the same length, and cutting the key would have been meaningless.
    """
    if value is None:
        return ""
    return str(value).strip()[:limit]


class Job:
    """A single background job."""

    def __init__(self, kind: str, title: str, set_no: int,
                 key: str | None = None, auto: bool = False):
        self.id = f"j{uuid.uuid4().hex[:10]}"
        self.kind = kind
        self.title = title
        self.set_no = int(set_no)
        self.key = key or f"{kind}:{set_no}"
        # Started by the UI's own timer rather than the user. Only affects
        # history pruning (see JobQueue._prune).
        self.auto = bool(auto)
        self.state = QUEUED
        # The job's current phase — separate from the title, which is fixed
        # ("IP atama · Yatakli_2") while the job moves from "opening ports"
        # to "final verification". A percentage alone did not say where it was.
        self.phase = ""
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.error: str | None = None      # worker error, not a device error
        self.cancel = threading.Event()
        # A progress ratio the job computes itself. The default is
        # "finished rows / total rows", which is wrong for some jobs
        # (see progress). When set, it replaces that calculation.
        self._ratio: float | None = None
        self._rows: dict[str, dict] = {}
        self._order: list[str] = []
        self._informational: set[str] = set()   # rows excluded from counters
        self._lock = threading.Lock()

    # ---- rows ----
    def add_device_row(self, device) -> None:
        """Create a row per device before the scan starts, so the UI can show
        what is happening from the first second: devices do not appear as they
        finish, their state changes."""
        with self._lock:
            self._rows[device.id] = {
                "deviceId": device.id, "name": device.name, "ip": device.ip,
                "readMethod": device.read_method, "state": QUEUED,
                "note": i18n.lazy("row.queued"),
            }
            self._order.append(device.id)

    def add_row(self, key: str, name: str, state: str = DONE,
                note: str = "", ip: str = "", path: str = "",
                counted: bool = False) -> None:
        """A row not tied to a device (script output, a generated file...).

        These stay out of the counters by default: "7 of 42 devices succeeded"
        must not include a progress line.

        `counted=True` is the exception: when the job's real unit of work is
        not a device (for an IP assignment run it is a PORT), progress has to
        be computed from these rows or the bar sits at 0% throughout.

        A `path` means the row points at a file the UI can open. The UI never
        sends the path; it is read from here (see panel.system.files).
        """
        with self._lock:
            if key not in self._rows:
                self._order.append(key)
            if counted:
                self._informational.discard(key)
            else:
                self._informational.add(key)
            # Steps survive a row being rebuilt: in an IP assignment run a
            # port restarts on the second pass, and what happened on the first
            # ("device not found") is exactly what you want to know.
            previous = self._rows.get(key) or {}
            # Text is stored RAW — it may be a deferred message (see
            # panel.i18n.Message). Rendering and truncation happen on read, so
            # a language switch retranslates a queue that is already running.
            self._rows[key] = {
                "deviceId": key, "name": name, "ip": ip,
                "readMethod": "", "state": state, "note": note,
                "file": bool(path), "path": path,
                "steps": previous.get("steps", []),
            }

    def add_step(self, key: str, text: str, state: str = DONE) -> None:
        """Append a step under a row — that row's own small history.

        A run moves step by step ("opening port", "searching for device",
        "writing IP") and that detail did not fit in a single `note` field:
        each new line erased the previous one, so when a port failed you could
        not tell what happened when. The UI shows these in a collapsed
        accordion under the row.
        """
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                return
            steps = row.setdefault("steps", [])
            # Compared raw: two Messages with the same key and parameters are
            # the same step even before either has been rendered.
            if steps and steps[-1]["text"] == text:
                return                       # never write the same step twice
            steps.append({"text": text, "state": state, "time": time.time()})
            if len(steps) > STEP_LIMIT:
                del steps[:len(steps) - STEP_LIMIT]

    def set_phase(self, text) -> None:
        with self._lock:
            self.phase = text

    def update_row(self, device_id: str, state: str, note: str = "") -> None:
        with self._lock:
            row = self._rows.get(device_id)
            if row is None:
                return
            row["state"] = state
            if note:
                row["note"] = note

    def rows(self) -> list[dict]:
        # The file path is not sent to the UI: all it needs to know is that
        # the row IS a file. The endpoint serving the request reads the path
        # from here (file_path).
        #
        # The step list is COPIED: it gets serialised to JSON outside the lock
        # and the run may append a step while that happens.
        with self._lock:
            out = []
            for key in self._order:
                row = self._rows.get(key)
                if row is None:
                    continue
                copy = {k: v for k, v in row.items() if k != "path"}
                copy["name"] = _text(row.get("name"), 200)
                copy["note"] = _text(row.get("note"), 200)
                copy["steps"] = [
                    {**step, "text": _text(step.get("text"), 160)}
                    for step in row.get("steps", ())]
                out.append(copy)
            return out

    def file_path(self, key: str) -> str:
        with self._lock:
            return (self._rows.get(key) or {}).get("path", "")

    # ---- counters ----
    def counts(self) -> dict:
        counts = {"total": 0, "ok": 0, "auth": 0, "failed": 0,
                  "pending": 0, "skipped": 0}
        with self._lock:
            informational = set(self._informational)
        for row in self.rows():
            if row["deviceId"] in informational:
                continue
            counts["total"] += 1
            state = row["state"]
            if state == ROW_DONE:
                counts["ok"] += 1
            elif state == ROW_AUTH:
                counts["auth"] += 1
            elif state == ROW_FAILED:
                counts["failed"] += 1
            elif state == ROW_SKIPPED:
                counts["skipped"] += 1
            else:
                counts["pending"] += 1
        return counts

    def set_progress(self, ratio: float) -> None:
        """Set the job's own ratio (0..1) — it never goes backwards.

        "Finished rows / total rows" is not the right answer for every job:
        in an IP assignment run ports close during the single verification
        pass at the end, not along the way, so the bar stayed at 0% and then
        jumped to 100% in the last second. That job knows its own phases and
        writes the ratio from there (see ip_assign.progress).

        Never going backwards is a rule: a user who sees the bar retreat stops
        trusting every number on the screen.
        """
        try:
            value = float(ratio)
        except (TypeError, ValueError):
            return
        value = min(1.0, max(0.0, value))
        with self._lock:
            if self._ratio is None or value > self._ratio:
                self._ratio = value

    def progress(self) -> float:
        with self._lock:
            ratio = self._ratio
        if ratio is not None:
            return round(ratio, 4)
        counts = self.counts()
        if not counts["total"]:
            return 1.0 if self.state in (DONE, CANCELLED, FAILED) else 0.0
        finished = counts["total"] - counts["pending"]
        return round(finished / counts["total"], 4)

    def outcome(self) -> str | None:
        """The user-facing result, separate from the queue lifecycle."""
        if self.state in (QUEUED, RUNNING):
            return None
        if self.state == FAILED:
            return "failed"
        if self.state == CANCELLED:
            return "stopped"
        # A body returning normally does not mean every device succeeded. A
        # scan can complete with devices that never answered, and that must
        # not look like a green success.
        counts = self.counts()
        if (counts["failed"] or counts["auth"] or counts["skipped"]
                or counts["pending"]):
            return "warning"
        return "success"

    def dto(self, rows: bool = True) -> dict:
        data = {
            "id": self.id, "kind": self.kind, "title": _text(self.title, 200),
            "auto": self.auto, "phase": _text(self.phase, 120),
            "setNo": self.set_no, "state": self.state,
            "createdAt": self.created_at, "startedAt": self.started_at,
            "finishedAt": self.finished_at, "progress": self.progress(),
            "error": _text(self.error, 400) or None,
            "counts": self.counts(),
            "outcome": self.outcome(),
            # Cancel was requested but the job is still stopping: the worker
            # may be waiting out a device timeout. If the UI still said
            # "Running" in that gap, whoever pressed the button assumed
            # nothing had happened.
            "cancelRequested": self.cancel.is_set(),
        }
        if rows:
            data["rows"] = self.rows()
        return data
