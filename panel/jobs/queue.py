#!/usr/bin/env python3
"""FIFO job queue — one job runs at a time."""
from __future__ import annotations

import threading
import time

from ..errors import DeviceError
from . import access
from .job import (CANCELLED, DONE, FAILED, Job, QUEUED, ROW_SKIPPED, RUNNING)
from .. import i18n


def _error_text(exc: BaseException) -> str:
    """One sentence telling the user why the job ended.

    Our own error classes (the DeviceError family) and input validation
    (ValueError) carry text written for the user: it holds no password and
    says what to do. For unknown exceptions only the class name survives —
    an unexpected error's message can carry internals or a raw trace.
    """
    if isinstance(exc, (DeviceError, ValueError, FileNotFoundError)):
        text = str(exc).strip()
        if text:
            return text
    if isinstance(exc, SystemExit):
        # A script running in-process called sys.exit() — almost always what
        # argparse does on a bad argument.
        return i18n.t("error.jobFailedExit", code=exc.code)
    return i18n.t("error.jobFailed", kind=type(exc).__name__)


class JobQueue:
    """FIFO job queue — one job runs at a time."""

    def __init__(self, history_limit: int = 20):
        self._jobs: list[Job] = []
        self._lock = threading.RLock()
        self._pending: list[Job] = []
        self._wake = threading.Condition(self._lock)
        self._shutdown = threading.Event()
        self._bodies: dict[str, callable] = {}
        self._worker: threading.Thread | None = None
        self.history_limit = history_limit
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        """(Re)start the dispatcher thread.

        Checked before every submit: if the thread dies unexpectedly the queue
        stops silently and every job shows "queued" forever. This recovers.
        """
        with self._lock:
            if self._shutdown.is_set():
                return
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._loop, daemon=True,
                                            name="job-queue")
            self._worker.start()

    def open(self) -> None:
        """Make a closed queue usable again."""
        self._shutdown.clear()
        self._ensure_worker()

    def is_closed(self) -> bool:
        return self._shutdown.is_set()

    # ---- queue ----
    def submit(self, job: Job, body) -> tuple[Job, bool]:
        """Add a job to the queue.

        If a queued/running job with the same key exists, NO new job is
        created and the existing one is returned. Pressing "Refresh" twice
        does not start a second scan.

        Returns: (job, is_new)
        """
        if self._shutdown.is_set():
            raise RuntimeError(i18n.t("error.queueClosed"))
        self._ensure_worker()
        with self._lock:
            existing = next((j for j in self._jobs
                             if j.key == job.key
                             and j.state in (QUEUED, RUNNING)), None)
            if existing is not None:
                return existing, False
            self._jobs.append(job)
            self._bodies[job.id] = body
            self._pending.append(job)
            self._prune()
            self._wake.notify()
            return job, True

    def find(self, job_id: str) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs if j.id == job_id), None)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs)

    def active(self, key: str) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs
                         if j.key == key and j.state in (QUEUED, RUNNING)),
                        None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self.find(job_id)
            if job is None or job.state in (DONE, CANCELLED, FAILED):
                return False
            job.cancel.set()
            if job.state == QUEUED:
                # Not started yet: drop it before it reaches a worker.
                if job in self._pending:
                    self._pending.remove(job)
                job.state = CANCELLED
                job.finished_at = time.time()
                for row in job.rows():
                    job.update_row(row["deviceId"], ROW_SKIPPED,
                                   i18n.lazy("row.cancelled"))
            return True

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self.find(job_id)
            if job is None:
                return False
            if job.state in (QUEUED, RUNNING):
                return False               # must be cancelled first
            self._jobs.remove(job)
            self._bodies.pop(job_id, None)
            return True

    def _prune(self) -> None:
        """Drop the oldest finished jobs so the queue cannot grow forever.

        Automatic scans are pruned harder. The UI queues one every minute, so
        under the normal limit twenty minutes would push the entire history —
        IP assignment, configuration, firmware records — out. Only the newest
        finished automatic scan is kept; the user's own jobs are untouched.
        """
        for job in [j for j in self._jobs
                    if j.auto and j.state in (DONE, CANCELLED, FAILED)][:-1]:
            self._jobs.remove(job)
            self._bodies.pop(job.id, None)
        finished = [j for j in self._jobs
                    if j.state in (DONE, CANCELLED, FAILED)]
        excess = len(finished) - self.history_limit
        for job in finished[:max(0, excess)]:
            self._jobs.remove(job)
            self._bodies.pop(job.id, None)

    # ---- runner ----
    def _loop(self) -> None:
        while not self._shutdown.is_set():
            with self._wake:
                while not self._pending and not self._shutdown.is_set():
                    self._wake.wait(0.5)
                if self._shutdown.is_set():
                    return
                job = self._pending.pop(0)
                body = self._bodies.get(job.id)
                # The cancel decision and the RUNNING stamp stay under the
                # SAME lock that popped the job. Outside it there was a
                # window in which `cancel()` still saw QUEUED and took the
                # "not started" branch — rows marked skipped, job marked
                # CANCELLED — while this thread went on to run the body to
                # DONE anyway. With the stamp inside the lock, `cancel()`
                # sees either QUEUED (and the job is still in `_pending`,
                # so it really is stopped before starting) or RUNNING (and
                # only the flag is set, for the body to honour).
                if job.cancel.is_set():
                    job.state = CANCELLED
                    job.finished_at = time.time()
                    continue
                job.state = RUNNING
                job.started_at = time.time()
            # THE DEVICE CLAIM, for the whole body. Outside the queue lock —
            # the wait can be long (the ADB screen may hold the claim through
            # an install) and submit/cancel must stay answerable meanwhile.
            # A cancel during the wait abandons it: the job ends CANCELLED
            # having touched nothing, exactly like a cancel while QUEUED.
            claim = f"job:{job.id}"
            # Said on the card while the wait lasts: the job is stamped
            # RUNNING before the claim (cancel() must see one truth), and a
            # silent RUNNING behind an ADB-screen operation read as a hang.
            job.phase = i18n.lazy("job.waitingForDevices")
            if not access.acquire(claim, cancelled=job.cancel.is_set):
                job.state = CANCELLED
                job.finished_at = time.time()
                for row in job.rows():
                    job.update_row(row["deviceId"], ROW_SKIPPED,
                                   i18n.lazy("row.cancelled"))
                continue
            job.phase = ""
            try:
                if body is None:
                    # The job was queued and its body pruned (or removed).
                    # Calling it was a TypeError with no obvious cause.
                    raise RuntimeError(i18n.t("error.jobBodyMissing"))
                body(job)
                job.state = CANCELLED if job.cancel.is_set() else DONE
            except Exception as exc:
                # A worker error is reported apart from a device error: the
                # problem is on the side running the job, not the device.
                job.state = FAILED
                job.error = _error_text(exc)
            except BaseException as exc:
                # SystemExit and friends must CLOSE the job too.
                #
                # Uncaught, the job stayed "running" forever and the
                # dispatcher thread died. Together that meant one crashed run
                # locked the whole panel: with a "write job in progress" both
                # light refresh and full scan were rejected with 409 and no
                # screen ever refreshed again.
                #
                # The best-known source is argparse: a script's main() calls
                # sys.exit() on a bad argument, and that is not an Exception.
                job.state = FAILED
                job.error = _error_text(exc)
                # Not re-raised: the dispatcher survives and the next job
                # runs. Shutdown handles the cancel flag separately.
            finally:
                access.release(claim)
                job.finished_at = time.time()

    def close(self, timeout: float | None = None) -> bool:
        """Stop the queue: no new jobs, running ones cancelled.

        Called on application shutdown. To reuse it, call `open()` — otherwise
        submitted jobs would sit "queued" forever. Production shutdown uses no
        timeout: an IP assignment job's ``finally`` block must reopen the PoE
        ports before the process can end. ``timeout`` is for controlled
        diagnostic/test calls only.
        """
        self._shutdown.set()
        with self._wake:
            for job in self._jobs:
                job.cancel.set()
            self._wake.notify_all()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)
        return worker is None or not worker.is_alive()


QUEUE = JobQueue()
