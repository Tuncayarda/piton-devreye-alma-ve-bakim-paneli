#!/usr/bin/env python3
"""One field of the edition table, printed for a shell to read.

The build workflow needs to know what to call the files it produces and what
to title the Release. Those answers live in `panel/editions/catalogue.py`,
and copying them into YAML would mean two places to change when an edition
is added — with the copy in the half nobody runs locally.

    python3 tools/edition_info.py --edition gdm --field app_name
    python3 tools/edition_info.py --list

Prints one line and nothing else, so the caller can do:

    NAME="$(python3 tools/edition_info.py --edition "$E" --field app_name)"

Loaded the same way `dabp.spec` loads it — directly, with no dependency on
the application package, so it works in a bare checkout before pip has run.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def catalogue():
    path = ROOT / "panel" / "editions" / "catalogue.py"
    spec = importlib.util.spec_from_file_location("dap_editions_info", path)
    module = importlib.util.module_from_spec(spec)
    # See the note in catalogue.py: dataclasses resolves its string
    # annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIELDS = {
    "app_name": lambda editions, edition: editions.app_name(edition.id),
    "display_name": lambda _editions, edition: edition.product_name,
    "app_id": lambda _editions, edition: edition.windows_app_id,
    "bundle_id": lambda _editions, edition: f"com.piton.dabp.{edition.id}",
}


def utf8_stdout() -> None:
    """Say the product name in the encoding it is actually spelled in.

    THE ONE TURKISH STRING IN THE CODE BASE is exactly what this tool hands
    to the build (see panel/editions/catalogue.py), and Windows gives a
    Python process a cp1252 stdout, which has no room for U+0131 (the
    dotless i). The build died here with a UnicodeEncodeError traceback
    nobody would connect to a letter in a product name. Reconfigured rather
    than escaped: what the caller wants is the name, spelled correctly.

    Guarded: a frozen GUI build has no stdout to reconfigure at all.
    """
    stream = getattr(sys, "stdout", None)
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def main() -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--edition")
    parser.add_argument("--field", choices=sorted(FIELDS))
    parser.add_argument("--list", action="store_true",
                        help="every edition id, one per line")
    arguments = parser.parse_args()

    editions = catalogue()
    if arguments.list:
        print("\n".join(editions.IDS))
        return 0
    if not arguments.edition or not arguments.field:
        print("[ERROR] --edition and --field are both required.",
              file=sys.stderr)
        return 2

    edition = editions.find(arguments.edition)
    if edition is None:
        print(f"[ERROR] unknown edition {arguments.edition!r}. "
              f"Editions: {', '.join(editions.IDS)}", file=sys.stderr)
        return 2
    print(FIELDS[arguments.field](editions, edition))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
