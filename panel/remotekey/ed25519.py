#!/usr/bin/env python3
"""Ed25519 signature VERIFICATION, and nothing else.

RFC 8032, in the standard reference form: a decompressed point, two scalar
multiplications and one comparison. About sixty lines of integer arithmetic
over `hashlib`.

WHY THIS IS VENDORED RATHER THAN INSTALLED. The panel ships four runtime
dependencies and no compiled cryptography, which is what keeps a PyInstaller
build across Windows, macOS and Linux boring. `cryptography` would add a
binary wheel to all three for one function, and the one function is short
enough to read.

WHY A HAND-WRITTEN IMPLEMENTATION IS ACCEPTABLE HERE, when it usually is not:
the verifier holds NO SECRET. Only a public key and a signature pass through
this module, both of which the other side already has, so there is no timing
channel to leak and nothing to leak through it. The risk that remains is
plain correctness — accepting a signature that should not verify — and that
is answered by testing against the RFC's own vectors rather than by trusting
the reading (see tests/test_remotekey.py).

SIGNING IS DELIBERATELY ABSENT. Nothing in the panel signs anything; the
private key lives on the grant service and never on a customer's machine. A
signing routine here would be dead code that looks like an invitation. The
tests generate their own signatures from `tests/support/ed25519_sign.py`.
"""
from __future__ import annotations

import hashlib

# The curve, as RFC 8032 §5.1 gives it.
P = 2 ** 255 - 19
Q = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
# sqrt(-1) mod p, needed to pick the other root in `_recover_x`.
ROOT_MINUS_ONE = pow(2, (P - 1) // 4, P)

# Points are kept in EXTENDED coordinates (x, y, z, t) with x = X/Z, y = Y/Z
# and t = XY/Z. Affine addition needs a modular inverse per step — a `pow` of
# its own — and there are some four hundred steps in a verification.
IDENTITY = (0, 1, 1, 0)


def _recover_x(y: int, sign: int) -> int | None:
    """The x that goes with `y` on the curve, or None if there is none.

    A y with no matching x is not a point, and a signature carrying one is
    refused rather than repaired.
    """
    if y >= P:
        return None                     # non-canonical encoding
    numerator = (y * y - 1) % P
    denominator = (D * y * y + 1) % P
    if denominator == 0:
        return None
    square = numerator * pow(denominator, P - 2, P) % P
    x = pow(square, (P + 3) // 8, P)
    if (x * x - square) % P != 0:
        x = x * ROOT_MINUS_ONE % P
    if (x * x - square) % P != 0:
        return None                     # not a square: off the curve
    if x == 0 and sign:
        return None                     # RFC 8032: x = 0 with the sign set
    if x & 1 != sign:
        x = P - x
    return x


def _add(point, other):
    x1, y1, z1, t1 = point
    x2, y2, z2, t2 = other
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = t1 * 2 * D * t2 % P
    e = z1 * 2 * z2 % P
    f, g, h, i = b - a, e - c, e + c, b + a
    return (f * g % P, h * i % P, g * h % P, f * i % P)


def _multiply(point, scalar: int):
    """`scalar` times `point`, double-and-add, lowest bit first.

    Iterative rather than recursive: a 253-bit scalar is 253 frames deep, and
    the panel's default stack has been reached by less.
    """
    result = IDENTITY
    while scalar > 0:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _same(point, other) -> bool:
    """Projective equality: x1/z1 == x2/z2 and y1/y2 likewise, cross-multiplied."""
    x1, y1, z1, _ = point
    x2, y2, z2, _ = other
    return ((x1 * z2 - x2 * z1) % P == 0
            and (y1 * z2 - y2 * z1) % P == 0)


def _decode(encoded: bytes):
    """A 32-byte compressed point, or None if those bytes are not one."""
    if len(encoded) != 32:
        return None
    packed = int.from_bytes(encoded, "little")
    sign = packed >> 255
    y = packed & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


# The base point, from the y in RFC 8032 §5.1. Derived rather than pasted:
# the derivation is the same code the rest of the module is checked by.
_BASE_Y = 4 * pow(5, P - 2, P) % P
_BASE_X = _recover_x(_BASE_Y, 0)
BASE = (_BASE_X, _BASE_Y, 1, _BASE_X * _BASE_Y % P)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Does `signature` say that the holder of `public_key` signed `message`?

    Returns False for every kind of "no", malformed input included. Nothing
    raises: this is called from a polling thread, and a signature is a thing
    that arrives over a network from a party that may be lying.
    """
    if len(signature) != 64 or len(public_key) != 32:
        return False
    upper = _decode(signature[:32])
    holder = _decode(public_key)
    if upper is None or holder is None:
        return False
    scalar = int.from_bytes(signature[32:], "little")
    if scalar >= Q:
        # Non-canonical S. Accepting it would make a second, different
        # signature valid for the same message — harmless here, but the
        # cheapest place to refuse it is where the RFC says to.
        return False
    challenge = int.from_bytes(
        hashlib.sha512(signature[:32] + public_key + message).digest(),
        "little") % Q
    return _same(_multiply(BASE, scalar),
                 _add(upper, _multiply(holder, challenge)))
