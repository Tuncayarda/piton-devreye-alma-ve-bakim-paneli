#!/usr/bin/env python3
"""Recover the accepted digest from a service key that already exists.

FOR THE DAY THE BUILD SECRET IS LOST. The secret cannot be read back out of
a CI secret store, and nothing else can reproduce it — but it is not what a
package actually needs. A package needs the DIGEST, and the digest is of a
value every issued stick carries in plain sight:

    stick -> proof -> sha256(proof) -> the digest a build is stamped with

So one surviving stick is enough to keep cutting releases that recognise
every key already in the field:

    python3 tools/key_digest.py /Volumes/DABP-KEY
    DAP_ADMIN_KEY_DIGESTS=<the value it prints> pyinstaller dabp.spec

What is NOT recovered is the ability to MINT keys — that needs the secret
itself. Copying an existing stick still works, because every stick is
identical; see docs/BUILD_RELEASE.md.

With `--remember` it also records the digest for SOURCE RUNS on this
computer, so `python3 app.py --edition <anything>` recognises that stick
without a secret in the environment:

    python3 tools/key_digest.py /Volumes/DABP-KEY --remember

A key written from source records itself; this is for one made elsewhere —
by a packaged service package, or by a colleague. It changes nothing about
any packaged build: what a package accepts is stamped in at build time.

This prints a digest, never the proof: the digest is what a build is stamped
with and is useless for opening anything.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILENAME = "dabp-admin-key.json"


def digest_of(path: Path) -> str:
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("format") != "dabp-admin-key":
        raise ValueError(f"{path} is not a service key file")
    proof = body.get("proof")
    if not isinstance(proof, str):
        raise ValueError(f"{path} carries no proof")
    return hashlib.sha256(base64.b64decode(proof, validate=True)).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "path", help=f"the drive the key is on, or the {FILENAME} itself")
    parser.add_argument(
        "--remember", action="store_true",
        help="also accept this key in SOURCE runs on this computer "
             "(no effect on any packaged build)")
    arguments = parser.parse_args()

    path = Path(arguments.path)
    if path.is_dir():
        path = path / FILENAME
    try:
        value = digest_of(path)
    except (OSError, ValueError, binascii.Error) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(value)
    if arguments.remember:
        # Imported only here: printing a digest must work in a bare checkout,
        # before anything is installed.
        sys.path.insert(0, str(ROOT))
        from panel.adminkey import secret                  # noqa: PLC0415
        secret.remember(value)
        print(f"[OK] source runs on this computer will now accept this key "
              f"({secret._remembered_file()}).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
