"""The other way into admin mode: a signed session, held open over the network.

The service key answers "is the engineer here?" with a stick in a socket.
This answers the same question from four hundred kilometres away, without
leaving anything behind on the customer's machine that could answer it again
tomorrow.

    ed25519   RFC 8032 verification, vendored, verification only
    verify    the public keys this build trusts, and where it asks
    protocol  the challenge, and every reason an answer is refused
    session   this installation's random name for itself
    client    the one place the panel talks to the internet
    pairing   the square on the screen, and the wait for an approval
    account   an engineer signing in with their own e-mail and password
    watcher   the beat, and the deadline that ends the mode

The private key is on a Cloudflare Worker in a separate private repository
and exists nowhere in this one. Nothing here grants anything either:
`panel.editions` records the mode, `panel.authority` decides when it ends,
and `panel.api.guard` enforces it.
"""

from . import account, client, ed25519, pairing, protocol, session, verify
from .pairing import PAIR, Pairing
from .protocol import MAX_TTL, Grant, display, mask, normalise
from .verify import available, service_url
from .watcher import WATCH, RemoteWatch

__all__ = [
                      "MAX_TTL",
                      "PAIR",
                      "WATCH",
                      "Grant",
                      "Pairing",
                      "RemoteWatch",
                      "account",
                      "available",
                      "client",
                      "display",
                      "ed25519",
                      "mask",
                      "normalise",
                      "pairing",
                      "protocol",
                      "service_url",
                      "session",
                      "verify",
]
