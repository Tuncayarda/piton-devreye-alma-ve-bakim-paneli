"""Background job queue and the per-set device state view.

Two things are kept apart on purpose:

  · JOB   — the record of what was done. It finishes, sits in the queue, is
            removed.
  · VIEW  — the devices' current state. Independent of any job.

Without that split, an old job's result overwrites a fresh scan snapshot.
"""

from . import access
from .job import (CANCELLED, DONE, FAILED, Job, QUEUED, RUNNING)
from .queue import JobQueue, QUEUE
from .sweep import sweep_devices
from .view import DeviceStateView, next_generation, view_for

# Job kinds that WRITE to devices — kept apart from the reading kinds (scan,
# light refresh), because while they run whatever a device reports is
# temporary. Defined HERE, where the kinds themselves are a jobs concern:
# it used to live in panel.api.presenters, which put a core policy fact in a
# presentation module and made panel.authority reach into the API layer for
# it (one arm of the authority ↔ api cycle).
WRITING_JOB_KINDS = ("ip", "ipfactory", "config", "firmware")


def busy_error() -> str:
    """The sentence for "the devices are claimed right now".

    `access.holder()` is an internal token — "job:j3f…", "adb-screen",
    "refresh" — and it leaked into a toast verbatim the first time a
    refusal needed words. Every claim string is minted in this package, so
    this is where each one turns back into the sentence the operator
    should read; a claim added without a line here falls to the generic
    wording rather than to its raw token.
    """
    from .. import i18n                                    # noqa: PLC0415
    from . import access
    holder = access.holder()
    if holder == "adb-screen":
        return i18n.t("error.adbRunnerBusy")
    if holder == "refresh":
        return i18n.t("error.refreshRunning")
    if holder.startswith("job:"):
        job = QUEUE.find(holder[4:])
        if job is not None:
            return i18n.t("error.jobRunning", title=job.title)
    return i18n.t("error.jobRunning", title="?")


def writing(set_no=None) -> Job | None:
    """The queued-or-running job that writes to devices, or None.

    THE ANSWER TO ONE QUESTION, GIVEN ONCE. Three callers used to scan the
    queue themselves and each answered "is a write in the way?" slightly
    differently — the light refresh only counted RUNNING, so a job the
    single worker was about to start did not block it. QUEUED counts:
    the queue has one worker, so a queued write is at most one job away
    from the devices this caller is about to touch.

    With `set_no`, only that train set's writers count; without it, any.
    """
    wanted = None if set_no is None else int(set_no)
    return next((job for job in QUEUE.list()
                 if job.kind in WRITING_JOB_KINDS
                 and job.state in (QUEUED, RUNNING)
                 and (wanted is None or job.set_no == wanted)), None)


__all__ = [
    "CANCELLED",
    "DONE",
    "FAILED",
    "QUEUE",
    "QUEUED",
    "RUNNING",
    "WRITING_JOB_KINDS",
    "DeviceStateView",
    "Job",
    "JobQueue",
    "access",
    "next_generation",
    "sweep_devices",
    "view_for",
    "writing",
]
