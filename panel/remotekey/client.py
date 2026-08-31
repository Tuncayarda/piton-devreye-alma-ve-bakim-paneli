#!/usr/bin/env python3
"""The one place in the panel that talks to the internet.

Everything else `requests` does here goes to a device on 10.1.1.x, and the
switch client turns `trust_env` OFF for exactly that reason — a company's
HTTP proxy has no business in the middle of a conversation with a switch on
the bench (see panel.switch.client).

THIS SESSION IS THE OPPOSITE CASE and takes the opposite setting. The grant
service is on the public internet, and on a customer's network the way out to
it may well BE the proxy the environment names. So `trust_env` is left alone,
and the switch's session is deliberately not reused: they are two different
networks with two different rules, and one `Session` cannot hold both.

SIX CALLS, ONE SHAPE. `ask` is the beat that holds the door open; `release`
gives a session back rather than letting it run out; `pair` and `poll` are
the square on the screen and the wait for somebody to approve it; `signin` is
the person standing at the machine proving who they are, and `signup` is the
same person asking for an account to prove it with. They differ only in the
path, the ceiling on the answer and which statuses mean what, so they are one
function with a table each rather than six functions with the same body
written out six times.

NO RETRIES. Failure here is not exceptional, it is the ordinary state of a
laptop between wireless access points, and the beat is already a retry every
four seconds. A retry inside the call would only make each failure take
longer to notice, and noticing quickly is the entire promise of the feature.
"""
from __future__ import annotations

import threading

import requests

from . import verify

CONNECT_TIMEOUT = 4.0
READ_TIMEOUT = 6.0

# Grant answers are a few hundred bytes. A body larger than this is not one,
# and is not read into memory to find that out.
MAX_BODY = 16 * 1024
# A pairing answer carries a QR code drawn as SVG — a few hundred paths
# rather than a few hundred bytes. Still a ceiling, and still checked before
# the body is read.
MAX_PAIR_BODY = 128 * 1024

_SESSION: requests.Session | None = None
# Guards the build and the teardown of that one Session. The first connect
# races the first beat here — three threads can arrive within a second of
# each other — and an unguarded lazy build let two of them each make a
# Session: one won the global, the other lived on inside whichever call had
# already taken it, its connection pool never closed by any later `reset`.
_SESSION_LOCK = threading.Lock()


class ServiceError(Exception):
    """The service could not be asked, or said no.

    `reason` is a fixed word, not a sentence: it crosses the API to the
    window, which has the translated text for each (see
    `panel.api.routes.remote_routes`). A message from a server the panel
    does not control is never shown to the user.
    """

    def __init__(self, reason: str, retry: int = 0):
        super().__init__(reason)
        self.reason = reason
        # Seconds, and only ever set where the service names one: a sign-in
        # locked out after too many wrong passwords ends by itself, and
        # "try again later" is a worse sentence than the number.
        self.retry = retry


# HTTP statuses the service uses to say a definite no. These END the session
# rather than waiting for the grant to expire — the operator closing a link
# should be felt at once, not in twelve seconds' time.
REFUSALS = {
    404: "unknownCode",
    410: "closed",
    403: "editionNotAllowed",
    409: "installLimit",
    429: "busy",
}

# Handing a session back on the way out. `notThisMachine` is the interesting
# one and is not an error worth a sentence: it means this machine never had
# an activation against that code, so there was nothing to give back.
RELEASE_REFUSALS = {
    400: "service",
    404: "unknownCode",
    403: "notThisMachine",
    429: "busy",
}

# Asking for a square. A 400 here is a panel bug rather than anything the
# operator did, so it lands in the same bucket as a service that answered
# with nonsense.
PAIR_REFUSALS = {
    400: "service",
    429: "busy",
}

# Waiting on one. The service tells an unknown pairing from a wrong key, and
# the panel does not: both mean the square on this screen is no longer
# attached to anything, and the only thing to do about either is draw a new
# one.
POLL_REFUSALS = {
    400: "service",
    404: "pairLost",
    403: "pairLost",
    429: "busy",
}

# Signing in with an account. THE STATUSES ARE SHARED AND THE WORDS ARE NOT:
# a 403 is an account without the permission or an account switched off, and
# a 429 is a lockout that ends by itself or an address asking too often.
# Those are four different things to tell somebody standing at the machine,
# so the word decides between them (see `DISCRIMINATED`).
SIGNIN_REFUSALS = {
    # A field missing or over length. The panel builds this body itself, so
    # it is a panel bug rather than anything the person typing did.
    400: "service",
    401: "badCredentials",
    403: "noPermission",
    429: "busy",
    # The service is deployed without the secret it hashes passwords with.
    # Nobody in the field can do anything about it, and it is not a wrong
    # password — saying so would send them round the same loop.
    503: "notConfigured",
}

# Asking for an account. THE 400 CARRIES FOUR DIFFERENT COMPLAINTS and each
# is a different thing to correct in a different field, so — unlike every
# other table here — a 400 is not one word. It would be no use as one: "the
# request was wrong" beside four boxes is a puzzle, not a message.
SIGNUP_REFUSALS = {
    400: "service",
    409: "emailTaken",
    429: "busy",
    503: "notConfigured",
}

# TWO REFUSALS NOW SHARE THE 403, and the panel has a different sentence for
# each: a session opened for another package, and a session opened by QR on
# another machine. The word in the body is what tells them apart, and it is
# read ONLY as a discriminator between statuses the panel already refuses on.
# It is never shown — what appears on screen is still the panel's own
# catalogue, chosen by the panel's own fixed vocabulary.
DISCRIMINATED = {
    (403, "notThisMachine"): "notThisMachine",
    (403, "disabled"): "accountDisabled",
    (429, "locked"): "locked",
    (400, "badEmail"): "badEmail",
    (400, "passwordShort"): "passwordShort",
    (400, "passwordLong"): "passwordLong",
    (400, "passwordObvious"): "passwordObvious",
}


def _session() -> requests.Session:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            session = requests.Session()
            session.headers.update({"content-type": "application/json",
                                    "accept": "application/json"})
            _SESSION = session
        return _SESSION


def reset() -> None:
    """Drop the pooled connection. Shutdown, and tests."""
    global _SESSION
    with _SESSION_LOCK:
        session, _SESSION = _SESSION, None
    # Closed OUTSIDE the lock: close() can wait on sockets, and nothing
    # about an already-detached Session needs the guard.
    if session is not None:
        try:
            session.close()
        except Exception:
            pass


def _refusal(response) -> tuple[str, int]:
    """The service's own account of a refusal: `(word, seconds to wait)`.

    The word chooses between the panel's sentences where one status carries
    more than one meaning (see `DISCRIMINATED`); the seconds are only ever
    sent with a lockout. NEITHER IS EVER SHOWN. What appears on screen is
    the panel's own catalogue, in the panel's own language, chosen by the
    panel's own fixed vocabulary — this reads a discriminator and a number.
    """
    if len(response.content) > MAX_BODY:
        return "", 0
    try:
        body = response.json()
    except ValueError:
        return "", 0
    if not isinstance(body, dict):
        return "", 0
    word = body.get("error")
    return (word if isinstance(word, str) else ""), _seconds(body.get("retry"))


def _seconds(value) -> int:
    """A wait, in seconds, or 0 for anything that is not one.

    Clamped, because a number off a socket decides what a screen says: an
    hour is already longer than anybody stands there waiting, and a negative
    or absurd one is simply not reported.
    """
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 0
    return seconds if 0 < seconds <= 3600 else 0


def _post(path: str, body: dict, *, refusals: dict[int, str],
          max_body: int = MAX_BODY) -> dict:
    """One request, and a dictionary back. Raises `ServiceError` otherwise.

    What comes back is NOT trusted in any way — this returns whatever JSON
    object came off a socket. Whether it means anything is decided by the
    caller, and for a grant by `protocol.check` against a key this build was
    compiled with.
    """
    url = verify.service_url().rstrip("/") + path
    try:
        response = _session().post(
            url, json=body, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except requests.RequestException as exc:
        raise ServiceError("offline") from exc

    if response.status_code in refusals:
        status = response.status_code
        word, retry = _refusal(response)
        raise ServiceError(DISCRIMINATED.get((status, word))
                           or refusals[status], retry)
    if response.status_code != 200:
        raise ServiceError("service")
    if len(response.content) > max_body:
        raise ServiceError("service")
    try:
        answer = response.json()
    except ValueError as exc:
        raise ServiceError("service") from exc
    if not isinstance(answer, dict):
        raise ServiceError("service")
    return answer


def ask(*, code: str, nonce: bytes, install_id: str, edition: str,
        app_version: str) -> tuple[str, str]:
    """One round. Returns `(payload, signature)`, both base64url, or raises.

    The answer is NOT trusted here in any way — this returns two strings that
    came off a socket. Whether they mean anything is decided by
    `protocol.check`, against a key this build was compiled with.
    """
    answer = _post("/v1/grant",
                   {"v": 1, "code": code, "installId": install_id,
                    "nonce": verify.encode(nonce), "edition": edition,
                    "appVersion": app_version},
                   refusals=REFUSALS)
    payload = answer.get("payload")
    signature = answer.get("sig")
    if not isinstance(payload, str) or not isinstance(signature, str):
        raise ServiceError("service")
    return payload, signature


def release(*, code: str, install_id: str) -> None:
    """Give the session back. Idempotent at the service, and best effort here.

    A session that is not handed back runs to its own expiry with nobody in
    it — harmless, but it holds a machine slot and shows on the operator's
    list as live. Nothing depends on the answer: the caller is already on its
    way out, and if this never arrives the grant loop has stopped anyway and
    the mode falls within one ttl.
    """
    _post("/v1/release", {"v": 1, "code": code, "installId": install_id},
          refusals=RELEASE_REFUSALS)


def pair(*, install_id: str, edition: str, app_version: str,
         hint: str) -> dict:
    """Ask for a square. `{pairId, pollKey, url, qr, expires, pollAfter}`.

    Everything but the install id is for the person who will be looking at a
    phone: `hint` is what tells them which machine is asking.
    """
    return _post("/v1/pair",
                 {"v": 1, "installId": install_id, "edition": edition,
                  "appVersion": app_version, "hint": hint},
                 refusals=PAIR_REFUSALS, max_body=MAX_PAIR_BODY)


def poll(*, pair_id: str, poll_key: str) -> dict:
    """Has anybody decided yet? `{state, …}`, and a `code` once approved."""
    return _post("/v1/pair/poll",
                 {"v": 1, "pairId": pair_id, "pollKey": poll_key},
                 refusals=POLL_REFUSALS)


def signin(*, email: str, password: str, install_id: str, edition: str,
           app_version: str, hint: str) -> dict:
    """Sign in with an account. `{code, expires, edition, account}`.

    THE PASSWORD IS A PARAMETER AND NOTHING ELSE. It goes into one request
    body and this module keeps no copy of it: not in the pooled session, not
    in a retry, not in the exception raised when the service says no. What
    comes back that the panel does keep is the session code, which is what
    it keeps for a code somebody read out over a telephone.

    The rest is the same request `pair` makes, and for the same reason: the
    machine's own name for itself binds the session to it, and the package
    and the hint are what the operator's listing shows.
    """
    return _post("/v1/signin",
                 {"v": 1, "email": email, "password": password,
                  "installId": install_id, "edition": edition,
                  "appVersion": app_version, "hint": hint},
                 refusals=SIGNIN_REFUSALS)


def signup(*, email: str, password: str, name: str,
           install_id: str) -> dict:
    """Ask for an account. `{account, waiting}`.

    WHAT COMES BACK OPENS NOTHING, and that is the whole reason this call
    can exist beside the anonymous ones: the row the service makes has every
    permission at zero, so the next `signin` with it answers `noPermission`
    until an administrator decides otherwise. Nothing here is a way in.

    The password is a parameter and nothing else, exactly as in `signin` —
    with the one difference that this one is the person's own choice rather
    than one they were given.
    """
    return _post("/v1/signup",
                 {"v": 1, "email": email, "password": password,
                  "name": name, "installId": install_id},
                 refusals=SIGNUP_REFUSALS)


def cancel(*, pair_id: str, poll_key: str) -> None:
    """The square is off the screen. Take it off the operator's phone too."""
    _post("/v1/pair/cancel",
          {"v": 1, "pairId": pair_id, "pollKey": poll_key},
          refusals=POLL_REFUSALS)
