#!/usr/bin/env python3
"""Sealing a file so that only a service key can open it.

WHY THIS EXISTS. Every package used to carry one customer's DeviceMap and no
other, which is a strong separation — the other customer's device list is not
in the file — but it also means an engineer in the field cannot open another
project without being handed another package. The maps travel on the stick
instead (`pack.py`), and that works only as long as the stick has them on it.

So the maps ship in every package after all, sealed: present as bytes,
unreadable without the key. A customer running their own package sees exactly
what they saw before. Admin mode with the stick in the machine opens them.

WHAT MAKES THAT SAFE is the shape of the key material rather than anything
here (see `secret.py`):

    S   the build secret          — ships to nobody
    K   = pbkdf2(S)               — written on the stick, and the SEALING KEY
    D   = sha256(K)               — all a customer package is built with

A customer package holds D, and sha256 does not run backwards, so the package
that carries the sealed bytes carries nothing that opens them. The stick
does, because the stick IS K. Nothing new is trusted: the value that already
decided whether admin mode may open is the value that decrypts.

STDLIB ONLY, deliberately — the same constraint the rest of the key material
was built under, so no dependency is added to a program that is shipped as a
frozen bundle to sites with no package manager.

THE CONSTRUCTION IS ENCRYPT-THEN-MAC, and both halves are a hash used the way
it was designed to be used rather than a cipher written by hand:

    keystream = SHAKE256(domain | "enc" | K | nonce)   — an XOF, asked for
                                                         exactly as many
                                                         bytes as the file
    ciphertext = plaintext XOR keystream
    tag       = HMAC-SHA256(sha256(domain | "mac" | K | nonce),
                            magic | nonce | ciphertext)

The tag is verified BEFORE a byte is decrypted, so a tampered file is a
refusal rather than a JSON parser fed attacker-chosen bytes. The nonce is
random per seal, which is what keeps two files sealed with the same K — every
file in every package, since K is one value — from sharing a keystream.

WHAT THIS DOES NOT CLAIM, and it is the same disclaimer `secret.py` carries:
a stick is a physical key and a copy of it is the key. This is the line
between a customer using their own product and a customer wandering into
another customer's, not a defence against someone taking the package apart.
"""
from __future__ import annotations

import hashlib
import hmac
import os

MAGIC = b"DAPSEAL1"
NONCE_BYTES = 16
TAG_BYTES = 32
HEADER = len(MAGIC) + NONCE_BYTES + TAG_BYTES

# Versioned by name, like `secret.SALT`: a later construction gets a later
# domain rather than a field in the file that a forger could turn down.
DOMAIN = b"dabp-seal-v1"

# Nothing shipped is anywhere near this. It is here so that unsealing is
# never asked to allocate a keystream the size of a file somebody replaced.
MAX_BYTES = 8 * 1024 * 1024


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    return hashlib.shake_256(
        DOMAIN + b"|enc|" + key + nonce).digest(length)


def _mac_key(key: bytes, nonce: bytes) -> bytes:
    return hashlib.sha256(DOMAIN + b"|mac|" + key + nonce).digest()


def _tag(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    return hmac.new(_mac_key(key, nonce),
                    MAGIC + nonce + ciphertext, hashlib.sha256).digest()


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, stream))


def seal(key: bytes, plaintext: bytes) -> bytes:
    """Seal `plaintext` under `key`. Raises — this one runs at build time.

    Unlike `unseal`, a failure here must be loud: a package built with a
    silently unsealed map is a package that leaks the thing this module
    exists to keep.
    """
    if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
        raise ValueError("sealing key is too short")
    if len(plaintext) > MAX_BYTES:
        raise ValueError("too large to seal")
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = _xor(bytes(plaintext), _keystream(key, nonce,
                                                   len(plaintext)))
    return MAGIC + nonce + _tag(key, nonce, ciphertext) + ciphertext


def unseal(key, blob) -> bytes | None:
    """The plaintext, or None for every kind of "could not".

    NEVER RAISES. This is asked about files found in a bundle and about a key
    read off removable media, on paths where the answer "not this one" has to
    keep the panel running — the same rule `keyfile.read` follows.
    """
    if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
        return None
    try:
        blob = bytes(blob)
    except (TypeError, ValueError):
        return None
    if len(blob) < HEADER or len(blob) - HEADER > MAX_BYTES:
        return None
    if not hmac.compare_digest(blob[:len(MAGIC)], MAGIC):
        return None
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_BYTES]
    tag = blob[len(MAGIC) + NONCE_BYTES:HEADER]
    ciphertext = blob[HEADER:]
    # VERIFIED BEFORE DECRYPTED. The other way round hands whatever the file
    # happens to contain to a JSON parser and only then asks whether the file
    # was genuine.
    if not hmac.compare_digest(tag, _tag(bytes(key), nonce, ciphertext)):
        return None
    return _xor(ciphertext, _keystream(bytes(key), nonce, len(ciphertext)))
