"""Background job queue and the per-set device state view.

Two things are kept apart on purpose:

  · JOB   — the record of what was done. It finishes, sits in the queue, is
            removed.
  · VIEW  — the devices' current state. Independent of any job.

Without that split, an old job's result overwrites a fresh scan snapshot.
"""

from .job import (CANCELLED, DONE, FAILED, Job, QUEUED, RUNNING)
from .queue import JobQueue, QUEUE
from .sweep import sweep_devices
from .view import DeviceStateView, next_generation, view_for

__all__ = ["CANCELLED", "DONE", "FAILED", "Job", "JobQueue", "QUEUE",
           "QUEUED", "RUNNING", "DeviceStateView", "next_generation",
           "sweep_devices", "view_for"]
