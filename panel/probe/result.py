#!/usr/bin/env python3
"""The result of one read, with its state and verification outcome."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .. import status
from ..errors import AuthError, DeviceError, NotApplicableError, classify
from .. import i18n


@dataclass
class ProbeResult:
    """One read of one device.

    `generation` stops a stale answer from overwriting a newer one: while a
    scan is running the user may type a password and turn a device green, and
    the in-flight scan reply must not turn it amber again. The comparison uses
    a counter, not a clock — clocks can go backwards.
    """

    state: str = status.UNKNOWN
    verification: str = status.NOT_READ
    detail: str = ""
    fields: dict = field(default_factory=dict)
    read_method: str = ""
    read_at: float = 0.0
    generation: int = 0

    def dto(self) -> dict:
        return {
            "state": self.state,
            "verification": self.verification,
            "detail": self.detail,
            "fields": self.fields,
            "readMethod": self.read_method,
            "readAt": self.read_at or None,
            "generation": self.generation,
        }


def success(fields: dict, read_method: str, detail: str = "") -> ProbeResult:
    return ProbeResult(state=status.OK, verification=status.VERIFIED,
                       detail=detail or i18n.t("probe.verified"),
                       fields=fields or {}, read_method=read_method,
                       read_at=time.time())


def not_applicable(read_method: str, detail: str) -> ProbeResult:
    return ProbeResult(state=status.UNKNOWN,
                       verification=status.NOT_APPLICABLE, detail=detail,
                       read_method=read_method, read_at=time.time())


def not_read(read_method: str, detail: str = "") -> ProbeResult:
    return ProbeResult(state=status.UNKNOWN, verification=status.NOT_READ,
                       detail=detail, read_method=read_method)


def from_error(exc: BaseException, read_method: str) -> ProbeResult:
    """Turn an exception into a coloured result."""
    error: DeviceError = classify(exc)
    if isinstance(error, NotApplicableError):
        return not_applicable(read_method, str(error) or error.title)
    verification = (status.AUTH_REQUIRED if isinstance(error, AuthError)
                    else status.UNVERIFIED)
    return ProbeResult(state=error.state, verification=verification,
                       detail=str(error) or error.title,
                       read_method=read_method, read_at=time.time())


def needs_auth(result: ProbeResult) -> bool:
    return result.verification == status.AUTH_REQUIRED


def tally(results) -> dict:
    """State distribution across a scan snapshot."""
    counts = {status.OK: 0, status.AUTH: 0, status.REVIEW: 0,
              status.FAILED: 0, status.UNKNOWN: 0}
    for result in results:
        counts[result.state] = counts.get(result.state, 0) + 1
    return {
        "ok": counts[status.OK],
        "auth": counts[status.AUTH],
        "review": counts[status.REVIEW],
        "failed": counts[status.FAILED],
        "unknown": counts[status.UNKNOWN],
    }


def uptime_text(seconds) -> str:
    """Seconds as HH:MM:SS; empty when invalid."""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if total < 0:
        return ""
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
