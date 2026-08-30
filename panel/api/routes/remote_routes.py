#!/usr/bin/env python3
"""The remote service session: getting in from somewhere else entirely.

The service key needs somebody standing at the machine with a stick. This is
the same permission granted down a telephone line: an engineer opens a
session on the grant service, reads eight characters out, and the panel holds
admin mode for as long as that session keeps signing for it.

`/api/admin/remote` is OPEN, and `connect` is open too — which looks like the
hole and is not. A field package that could not ASK to connect could never
use the feature at all, so the path has to be reachable from field mode by
definition. What is not reachable is admin mode itself: connecting needs a
code that only the engineer has, and an answer signed by a key only the
service holds (`panel.remotekey.verify`). The guard is not what is keeping
anybody out here; the signature is.

THE SQUARE IS THE SAME PERMISSION, ASKED THE OTHER WAY ROUND. `pair` draws
one instead of waiting for eight characters to be read out, and `pair/poll`
waits for somebody holding a phone to approve it. The code that comes back is
not believed either: it goes through `WATCH.connect` exactly as a typed one
does, and the mode moves on the same signature check. All three are open for
the reason `connect` is — a package that could not ask could not be helped.

AND SO IS `signin`, WHICH IS THE THIRD SHAPE OF THE ONE QUESTION. An engineer
standing at the machine gives their own e-mail and password, the service
mints a session bound to this installation, and the code it answers with goes
through `WATCH.connect` like every other. The password is not this panel's
business and does not stay in it for a moment longer than the request it
travels in (see `panel.remotekey.account`).

`signup` IS OPEN TOO, AND IT IS THE ONE PATH HERE THAT GRANTS NOTHING AT ALL.
Anybody holding the application may ask the service for an account; what
comes back is a row with every permission at zero, which `signin` then
refuses with `noPermission` until an administrator turns a switch on their
own page. Making an account and being allowed to use one are two separate
acts, and only the second one is anybody's to give.

Disconnecting is open for the reason leaving admin mode has always been open:
giving something up is never an escalation, and the customer whose machine it
is must be able to end the session without asking anybody
(`admin_routes.post_mode`).
"""
from __future__ import annotations

from ... import authority, editions, i18n, remotekey, settings
from ..response import respond
from .edition_routes import edition_body

# Why a session could not be opened, or why one ended, as an HTTP status and
# a sentence. THE SERVICE'S OWN WORDS ARE NEVER SHOWN: what comes back over
# the network is a fixed vocabulary (see panel.remotekey.client), and the
# text belongs to the panel's own catalogue in the panel's own language.
FAILURES: dict[str, tuple[int, str]] = {
    # The build has no public key at all — cut before the service existed.
    "unavailable":       (409, "error.remoteUnavailable"),
    "badCode":           (400, "error.remoteBadCode"),
    "unknownCode":       (404, "error.remoteUnknownCode"),
    "closed":            (410, "error.remoteClosed"),
    "editionNotAllowed": (403, "error.remoteEditionNotAllowed"),
    # A session minted for one machine by an approval on somebody's phone,
    # and this is not that machine. Reachable by typing a code that was read
    # off a QR session's listing rather than dictated for this installation.
    "notThisMachine":    (403, "error.remoteNotThisMachine"),
    # The square on screen is no longer attached to anything: expired, or
    # cancelled, or swept. One sentence, because there is one thing to do
    # about all of them — ask for another square.
    "pairLost":          (410, "error.remotePairGone"),
    "installLimit":      (409, "error.remoteInstallLimit"),
    # Signing in with an account. FOUR REFUSALS, NOT ONE, because they are
    # four different things to do next: type it again, use the square
    # instead, telephone whoever administers the accounts, or wait.
    "badCredentials":    (401, "error.remoteBadCredentials"),
    "noPermission":      (403, "error.remoteNoPermission"),
    "accountDisabled":   (403, "error.remoteAccountDisabled"),
    "locked":            (429, "error.remoteLocked"),
    "notConfigured":     (503, "error.remoteNotConfigured"),
    # Asking for an account. Four ways to be wrong, four boxes to be wrong
    # in: one sentence for all of them would leave the reader looking for
    # which field it meant.
    "emailTaken":        (409, "error.remoteEmailTaken"),
    "badEmail":          (400, "error.remoteBadEmail"),
    "passwordShort":     (400, "error.remotePasswordShort"),
    "passwordLong":      (400, "error.remotePasswordLong"),
    "passwordObvious":   (400, "error.remotePasswordObvious"),
    "busy":              (429, "error.remoteBusy"),
    "offline":           (503, "error.remoteOffline"),
    "expired":           (410, "error.remoteExpired"),
    # Something answered, and it was not the service. A customer pointing the
    # name at a server of their own lands here, and so does a genuine
    # man-in-the-middle: neither can produce the signature.
    "untrusted":         (502, "error.remoteUntrusted"),
    # The grant was for another package. The service should have refused it
    # outright, so this is the belt to that braces — but it is the same fact,
    # and the operator should read the same sentence.
    "edition":           (403, "error.remoteEditionNotAllowed"),
}
# Everything else the checks can say — a replayed nonce, another machine's
# id, a version from the future, a body that is not a grant — means the
# answer was not a valid answer. They are one sentence to the operator
# because there is one thing to do about them, and they stay separate words
# in `reason` because there is not one thing to do about them in a test.
DEFAULT = (502, "error.remoteService")


# How a settled pairing is put to the operator. `pending` is not here: it is
# not a failure and the window has its own line for it.
PAIR_STATES: dict[str, str] = {
    "denied":    "error.remotePairDenied",
    "expired":   "error.remotePairGone",
    "cancelled": "error.remotePairGone",
    # Approved, and the session was closed between the approval and this
    # answer. The operator reads what they would read if it had closed a
    # moment later, because it is the same fact.
    "closed":    "error.remoteClosed",
}


def _failure(reason: str) -> tuple[int, str]:
    return FAILURES.get(reason, DEFAULT)


def _refused(reason: str, **extra):
    status, message = _failure(reason)
    return respond(status, {"error": i18n.t(message), "reason": reason,
                            **extra})


def get_remote(_query=None):
    """What the session is doing. Polled by the window once a second.

    `fresh` rather than `snapshot`, for the reason the key endpoint gives:
    the beat is four seconds and a grant can run out between two of them, so
    asking is what makes the observation.
    """
    state = remotekey.WATCH.fresh()
    reason = state.get("reason") or ""
    return respond(200, {**state,
                         "reasonText": i18n.t(_failure(reason)[1])
                         if reason else ""})


def post_connect(body):
    """Open a session with a code, and enter admin mode if it opens.

    The round trip happens BEFORE the mode changes, and the mode changes only
    on a signature that checked. Nothing about the client's request is taken
    on trust — the code is a claim, and the answer to it comes from the
    service rather than from this process (`panel.remotekey.watcher`).
    """
    reason = remotekey.WATCH.connect(body.get("code"))
    if reason:
        return _refused(reason)
    editions.set_admin(True)
    return respond(200, {**edition_body(),
                         "remote": remotekey.WATCH.snapshot()})


def post_disconnect(_body=None):
    """End the session. Admin mode goes with it unless something else holds it.

    "Unless something else holds it" is the arbiter's business and not this
    handler's: an engineer who connected remotely while their own stick was
    in the machine stays in admin mode when the remote session ends, because
    the stick is still a reason to be there (`panel.authority`).
    """
    remotekey.WATCH.disconnect()
    authority.settle()
    return respond(200, {**edition_body(),
                         "remote": remotekey.WATCH.snapshot()})


def post_signin(body):
    """An account instead of a dictated code. Admin mode on the same evidence.

    THE PASSWORD IS NOT LOGGED, NOT STORED AND NOT ANSWERED WITH. It arrives
    in this body, goes into one request to the service, and is gone when this
    function returns — there is nothing here that could hold it and nothing
    that would want to (see `panel.remotekey.account`).

    Open, for the reason `post_connect` is: a field package that could not
    ASK to sign in could never use the feature. What is not open is admin
    mode, which still moves only after `WATCH.connect` has had an answer
    signed by the service and checked it against a key this build carries.
    Signing in proves who somebody is; the signature is what proves the
    session exists.
    """
    edition = editions.active()
    code, reason, retry = remotekey.account.sign_in(
        email=body.get("email"), password=body.get("password"),
        install_id=remotekey.session.install_id(),
        edition=edition.id, app_version=settings.APP_VERSION,
        hint=edition.product_name)
    if reason:
        if reason == "locked" and retry:
            # The one refusal that ends by itself, and the only one worth a
            # number: "in forty seconds" is something to wait out, "try
            # later" is something to keep pressing.
            return respond(429, {"error": i18n.t("error.remoteLockedFor",
                                                 seconds=retry),
                                 "reason": reason, "retry": retry})
        return _refused(reason)

    reason = remotekey.WATCH.connect(code)
    if reason:
        return _refused(reason)
    editions.set_admin(True)
    return respond(200, {**edition_body(),
                         "remote": remotekey.WATCH.snapshot()})


def post_signup(body):
    """Ask the service for an account. Grants nothing, and cannot.

    THE ONE ENDPOINT IN THIS FILE THAT DOES NOT TOUCH ADMIN MODE. What the
    service makes has every permission at zero, so the account this produces
    is refused by `post_signin` until an administrator says otherwise —
    which is exactly the arrangement asked for: anybody with the application
    may make an account, only an administrator may make one work.

    The password is handled the way `post_signin` handles one: it arrives in
    this body, goes into one request, and is gone when this returns.
    """
    reason = remotekey.account.sign_up(
        email=body.get("email"), password=body.get("password"),
        name=body.get("name"),
        install_id=remotekey.session.install_id())
    if reason:
        return _refused(reason)
    # No mode, no session, no code — the account exists and is waiting on
    # somebody, and that is the whole of what the window is told.
    return respond(200, {"waiting": True})


def post_pair(_body=None):
    """Ask the service for a square, so nobody has to dictate anything.

    WHAT GOES WITH THE REQUEST IS WHAT THE PERSON APPROVING WILL SEE. The
    install id says which machine, and the package name says whose — an
    engineer looking at a phone is being asked "is this the machine you are
    on the telephone about?", and that is not a question a bare identifier
    answers.
    """
    edition = editions.active()
    reason = remotekey.PAIR.start(
        install_id=remotekey.session.install_id(),
        edition=edition.id,
        app_version=settings.APP_VERSION,
        hint=edition.product_name)
    if reason:
        return _refused(reason)
    return respond(200, {"pair": remotekey.PAIR.snapshot()})


def post_pair_poll(_body=None):
    """Has anybody decided? Enters admin mode on the round that says yes.

    THE APPROVAL IS NOT THE PERMISSION. What comes back from a poll is a
    code, which is a claim like any other; the mode moves only after
    `WATCH.connect` has had an answer signed by the service and checked it
    against a key this build carries. So this handler grants exactly what
    `post_connect` grants, on exactly the same evidence — the only
    difference is who typed the eight characters.
    """
    state, code = remotekey.PAIR.poll()
    if state not in remotekey.pairing.STATES:
        # Not a state at all: the service could not be reached, or answered
        # with something that is not an answer.
        return _refused(state, pair=remotekey.PAIR.snapshot())
    if state != "approved":
        message = PAIR_STATES.get(state, "")
        return respond(200, {"pair": remotekey.PAIR.snapshot(),
                             "stateText": i18n.t(message) if message else ""})

    reason = remotekey.WATCH.connect(code)
    if reason:
        # Approved and refused: the session was closed in between, or this
        # machine cannot use it. The pairing is spent either way.
        remotekey.PAIR.forget(state)
        return _refused(reason, pair=remotekey.PAIR.snapshot())
    editions.set_admin(True)
    # The request has done its work, and the key that could read the code
    # back goes with it — before the answer is even written.
    remotekey.PAIR.forget(state)
    return respond(200, {**edition_body(),
                         "remote": remotekey.WATCH.snapshot(),
                         "pair": remotekey.PAIR.snapshot()})


def post_pair_cancel(_body=None):
    """The window closed the dialog. Take the request off the phone too.

    Open, and harmless: this ends a request THIS panel made, addressed with
    a key only this panel holds. A pairing already approved and used is
    already forgotten here, so a dialog closing after a successful
    connection cancels nothing.
    """
    remotekey.PAIR.cancel()
    return respond(200, {"pair": remotekey.PAIR.snapshot()})


GET = {
    "/api/admin/remote": get_remote,
}

POST = {
    "/api/admin/remote/connect": post_connect,
    "/api/admin/remote/disconnect": post_disconnect,
    "/api/admin/remote/signin": post_signin,
    "/api/admin/remote/signup": post_signup,
    "/api/admin/remote/pair": post_pair,
    "/api/admin/remote/pair/poll": post_pair_poll,
    "/api/admin/remote/pair/cancel": post_pair_cancel,
}
