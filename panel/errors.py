#!/usr/bin/env python3
"""Device error classification.

The panel's colour logic reads straight off these classes. "unreachable",
"needs credentials" and "returned something unexpected" mean three different
actions for the user — a cable, a password, or the wrong device/endpoint.

User-facing text NEVER contains a password, and never a raw traceback.
"""
from __future__ import annotations

from . import status
from . import i18n


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


def user_message(exc: BaseException) -> str:
    """Reduce a technical error to one sentence the user can read."""
    if isinstance(exc, DeviceError):
        text = str(exc).strip()
        return text or str(exc.title)

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
    if name in TIMEOUT_NAMES or name in UNREACHABLE_NAMES or name == "SSLError":
        return UnreachableError(user_message(exc))
    return VerificationError(user_message(exc))
