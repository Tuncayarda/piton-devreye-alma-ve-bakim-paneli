#!/usr/bin/env python3
"""The third way in: the person at the machine says who THEY are.

The code path is somebody reading eight characters down a telephone. The
square is somebody approving on a phone. This is neither — the engineer
standing in front of the panel signs in with their own account, and the
service mints a session for the machine they are standing at. Nobody dictates
anything and nobody has to be reachable to approve it.

WHAT COMES BACK IS STILL ONLY A CLAIM. A sign-in answers with a session code,
and a session code is exactly what the other two paths produce: it goes to
`watcher.RemoteWatch.connect`, which asks the service to sign for it and
checks that signature against a key this build was compiled with. Nothing
here grants anything, and a service talked into returning a code would still
not put this panel into admin mode.

THE PASSWORD PASSES THROUGH AND IS NEVER HELD. It is a parameter to one
function, it goes into one request body, and it is not written to the
settings file, not put in a log, not kept for a retry and not returned. There
is no "remember me" for the same reason there is no admin file on the
customer's disk: a secret left behind is a secret that opens the door again
tomorrow (see `panel.remotekey.session`).

THE SESSION IS BOUND TO THIS MACHINE. The service ties the code it issues to
the install id sent with the request, so the eight characters are worth
nothing anywhere else — the same rule an approved square follows, and the
reason both refuse with `notThisMachine`.

AND ASKING FOR AN ACCOUNT IS NOT ASKING FOR ANYTHING ELSE. `sign_up` is here
because it is the same conversation with the same service, but it grants
nothing and cannot: what the service makes has every permission at zero, so
the account it hands back is refused by `sign_in` with `noPermission` until
an administrator turns a switch on their own page. Anybody holding this
application may make an account; only an administrator may make one work.
"""
from __future__ import annotations

from . import client, protocol, verify

# The service's own ceilings. An address longer than this is not an account,
# so it is refused here rather than sent to be refused there: a `400
# malformed` reads as a panel fault, and this is a typed-in field.
MAX_EMAIL = 120
MAX_HINT = 64
MAX_NAME = 64


def sign_in(*, email, password, install_id: str, edition: str,
            app_version: str, hint: str) -> tuple[str, str, int]:
    """`(code, reason, retry)`. A session code, or why there is not one.

    `retry` is seconds and comes with `locked` and nothing else: the service
    counts wrong passwords per account and says when it will listen again,
    which is a better sentence than "try later".
    """
    if not verify.available():
        return "", "unavailable", 0

    address = email.strip().lower() if isinstance(email, str) else ""
    secret = password if isinstance(password, str) else ""
    # Not a refusal from the service, and it does not need to be one: an
    # empty field is a wrong credential by inspection, and answering it here
    # saves a round trip and a failed attempt against the account's lockout.
    if not address or len(address) > MAX_EMAIL or not secret:
        return "", "badCredentials", 0

    try:
        answer = client.signin(email=address, password=secret,
                               install_id=install_id, edition=edition,
                               app_version=app_version,
                               hint=(hint or "")[:MAX_HINT])
    except client.ServiceError as exc:
        return "", exc.reason, exc.retry

    # Normalised rather than taken as it came: the watcher normalises a typed
    # code before it asks with it, and a code that arrives in a shape the
    # panel would not accept from a person is not a code.
    code = protocol.normalise(answer.get("code"))
    if code is None:
        return "", "service", 0
    return code, "", 0


def sign_up(*, email, password, name, install_id: str) -> str:
    """Ask the service for an account. "" if there is one, else the reason.

    NOTHING IS RETURNED BUT THE VERDICT, because nothing else is worth
    having: no session, no code, no cookie. The account exists and is
    waiting on somebody, and the only thing the window can do about it is
    say so.

    An empty field is answered here and named — `badEmail` or
    `passwordShort` — rather than reported as one refusal for both: there
    are two boxes on the screen and the sentence has to say which.

    HOW LONG A PASSWORD MUST BE IS NOT DECIDED HERE. Only that there is one.
    The rule is the service's, it can change there without a panel release,
    and a panel carrying its own copy would start refusing passwords the
    service would have taken.
    """
    if not verify.available():
        return "unavailable"

    address = email.strip().lower() if isinstance(email, str) else ""
    if not address or len(address) > MAX_EMAIL:
        return "badEmail"
    secret = password if isinstance(password, str) else ""
    if not secret:
        return "passwordShort"
    called = name.strip()[:MAX_NAME] if isinstance(name, str) else ""

    try:
        client.signup(email=address, password=secret, name=called,
                      install_id=install_id)
    except client.ServiceError as exc:
        return exc.reason
    return ""
