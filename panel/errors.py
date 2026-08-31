#!/usr/bin/env python3
"""Device error classification.

The panel's colour logic reads straight off these classes. "unreachable",
"needs credentials" and "returned something unexpected" mean three different
actions for the user — a cable, a password, or the wrong device/endpoint.

User-facing text NEVER contains a password, and never a raw traceback.
"""
from __future__ import annotations

import errno

from . import status
from . import i18n


class NotFoundError(LookupError):
    """Something the client NAMED is not there — a device id, a job id.

    Its own class, and the only LookupError the API maps to a 404: a bare
    KeyError from a handler bug is a LookupError too, and mapping the whole
    family used to report a programming error to the operator as "not
    found" — a state the UI renders calmly — with a quoted Python key as
    the explanation and nothing in any log. Raisers carry a translated
    sentence; a KeyError never does.
    """


class DeviceError(Exception):
    """Common ancestor for a single device failing to be read."""

    state = status.FAILED
    title = i18n.lazy("error.deviceUnreadable")


class UnreachableError(DeviceError):
    """Timeout, refused connection, DNS/network error, dropped link."""

    state = status.FAILED
    title = i18n.lazy("error.deviceUnreachable")


class AuthError(DeviceError):
    """401/403, WWW-Authenticate, or a login page in the response.

    The device is up and talking; it just wants credentials. Amber rather
    than red: the fix is a password, not a cable.
    """

    state = status.AUTH
    title = i18n.lazy("error.credentialsRequired")


class VerificationError(DeviceError):
    """The device answered, but not with the expected data.

    HTTP 200 alone is not success: login HTML, an empty page and an
    unexpected JSON body all arrive with 200.
    """

    state = status.FAILED
    title = i18n.lazy("error.responseUnverified")


class NotApplicableError(DeviceError):
    """This device type has no such read method (N/A)."""

    state = status.UNKNOWN
    title = i18n.lazy("error.notApplicable")


# Exception names coming from the network layer. If the list is short a real
# timeout shows up as "unexpected problem" and the user cannot tell whether
# to check the cable or the password — hence requests, stdlib and subprocess
# names all appear here.
TIMEOUT_NAMES = {
    "ConnectTimeout", "ReadTimeout", "Timeout", "TimeoutError",
    "socket.timeout", "TimeoutExpired", "ConnectTimeoutError",
    "ReadTimeoutError", "MaxRetryError",
}
UNREACHABLE_NAMES = {
    "ConnectionError", "NewConnectionError", "OSError", "IOError",
    "ConnectionRefusedError", "ConnectionResetError", "ConnectionAbortedError",
    "BrokenPipeError", "gaierror", "herror", "URLError", "ProtocolError",
    "ChunkedEncodingError", "NameResolutionError",
}


def _os_errno(exc: BaseException) -> int | None:
    """The OS error number behind a wrapped network exception.

    `requests` raises its own ConnectionError with the real OSError two or
    three levels down, so the chain is walked — through `__cause__`,
    `__context__` and the exceptions libraries pass along as arguments.
    """
    pending, seen = [exc], set()
    while pending:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        number = getattr(current, "errno", None)
        if isinstance(number, int):
            return number
        pending.extend([current.__cause__, current.__context__,
                        *current.args])
    return None


def _no_local_address(exc: BaseException) -> bool:
    """Did the machine have no address to send this from?

    EADDRNOTAVAIL is not a device fault at all and must not be reported as
    one: nothing left the computer. It is what a route left pointing at an
    address that no longer exists produces (see `panel.network.routes`), and
    read as "device unreachable" it sends the user to the cabinet to check a
    cable that was never the problem — every device in the network fails at
    once, in milliseconds.

    urllib3 sometimes re-raises with the text only, hence the second test.
    """
    if _os_errno(exc) == errno.EADDRNOTAVAIL:
        return True
    text = str(exc).lower()
    return "errno 49" in text or "can't assign requested address" in text


def user_message(exc: BaseException) -> str:
    """Reduce a technical error to one sentence the user can read."""
    if isinstance(exc, DeviceError):
        text = str(exc).strip()
        return text or str(exc.title)

    if _no_local_address(exc):
        return i18n.t("error.noLocalAddress")

    name = type(exc).__name__
    if name in TIMEOUT_NAMES:
        return i18n.t("error.deviceTimedOut")
    if name in UNREACHABLE_NAMES:
        return i18n.t("error.noConnection")
    if name == "SSLError":
        return i18n.t("error.tlsFailed")
    return i18n.t("error.unexpectedDeviceProblem")


def classify(exc: BaseException) -> DeviceError:
    """Map any exception onto one of the classes above."""
    if isinstance(exc, DeviceError):
        return exc
    name = type(exc).__name__
    if (name in TIMEOUT_NAMES or name in UNREACHABLE_NAMES
            or name == "SSLError" or _no_local_address(exc)):
        return UnreachableError(user_message(exc))
    return VerificationError(user_message(exc))
