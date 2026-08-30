#!/usr/bin/env python3
"""Ed25519 SIGNING, for the tests and only for the tests.

The panel verifies and never signs: the private key belongs to the grant
service, and a signing routine shipped inside a customer package would be a
package that could grant itself admin mode (see panel/remotekey/ed25519.py).

But a test of a verifier needs signatures — real ones, made by a key the test
chose, over bytes the test chose — or it is only a test that the RFC's three
vectors still parse. So the other half of RFC 8032 lives here, out of the
product, and borrows the curve arithmetic from the module under test. That it
borrows is the point: if the shared half were wrong, a signature made here
would verify there and the suite would agree with itself. The RFC's own
vectors are what stops that, and they are checked first.
"""
from __future__ import annotations

import hashlib

from panel.remotekey.ed25519 import BASE, P, Q, _multiply


def _compress(point) -> bytes:
    x, y, z, _ = point
    inverse = pow(z, P - 2, P)
    x, y = x * inverse % P, y * inverse % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _clamp(seed: bytes) -> tuple[int, bytes]:
    digest = bytearray(hashlib.sha512(seed).digest())
    digest[0] &= 248
    digest[31] &= 127
    digest[31] |= 64
    return int.from_bytes(digest[:32], "little"), bytes(digest[32:])


def public_key(seed: bytes) -> bytes:
    scalar, _ = _clamp(seed)
    return _compress(_multiply(BASE, scalar))


def sign(seed: bytes, message: bytes) -> bytes:
    scalar, prefix = _clamp(seed)
    holder = _compress(_multiply(BASE, scalar))
    nonce = int.from_bytes(hashlib.sha512(prefix + message).digest(),
                           "little") % Q
    upper = _compress(_multiply(BASE, nonce))
    challenge = int.from_bytes(
        hashlib.sha512(upper + holder + message).digest(), "little") % Q
    lower = (nonce + challenge * scalar) % Q
    return upper + lower.to_bytes(32, "little")
