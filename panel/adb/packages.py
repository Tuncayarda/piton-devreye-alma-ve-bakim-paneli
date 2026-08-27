#!/usr/bin/env python3
"""Finding an application on the devices by a word out of its name.

The operator does not know the bundle id. They know the application by the
name on the display — "gebze", "kapi", the customer's own word — and typing
``com.piton.something`` correctly from memory is not a thing anybody does
twice. So the screen asks for a word and this module finds what matches.

The filtering happens HERE, not on the device. `pm list packages <word>` does
take a filter, but a locked-down Android build is not guaranteed to have the
shell utilities a pipeline would need and the filter's matching rules are the
package manager's rather than ours. Reading the whole list back and searching
it in Python costs one command and behaves identically on every device.

WHAT MAKES THIS MORE THAN A SEARCH BOX is that it runs on SEVERAL devices and
they need not agree. Four displays on a bench are routinely at different
stages of commissioning, and the honest answer to "which package matches
'gebze'?" is sometimes "this one, but only on three of them". That is exactly
the answer `search` gives: every match carries the devices it was found on
and the devices it is missing from. Collapsing that into a single list — the
obvious implementation — would have the operator press "start" on four
devices and be told nothing about the one that has no such application.
"""
from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor

from .. import i18n, settings
from ..errors import UnreachableError, user_message
from . import client

# `pm list packages` writes one per line, prefixed. Anything else on the line
# (a `-f` path, an installer name) is not asked for and not parsed.
_LINE = re.compile(r"^package:(\S+)", re.MULTILINE)
# A word short enough to match half the system matches the whole system; the
# operator gets 300 rows and no way to choose between them.
MIN_KEYWORD = 2


def parse_list(raw: str) -> list[str]:
    """Package names out of `pm list packages` output."""
    return sorted({name for name in _LINE.findall(raw or "")})


def installed(ip: str) -> list[str]:
    """Every package on one device.

    Raises rather than returning an empty list when the device cannot be
    reached: "no packages" and "no device" look identical on screen and mean
    opposite things.
    """
    if not client.connect(ip, attempts=2):
        raise UnreachableError(i18n.t("error.adbNoConnection"))
    return parse_list(client.shell(ip, "pm", "list", "packages"))


def keywords(raw) -> list[str]:
    """The words to search for, out of one comma-separated box.

    SEVERAL AT ONCE, because a bench rarely holds one kind of display. Four
    devices running three different customers' applications is the ordinary
    case, and searching them one word at a time means three searches, three
    selections and three separate runs — while the operator wanted one.

    Semicolons are accepted as well: a list pasted out of a spreadsheet
    arrives with whichever separator that spreadsheet used.
    """
    words = [word.strip()
             for word in str(raw or "").replace(";", ",").split(",")]
    return [word for word in dict.fromkeys(words) if word]


def matches(names, words) -> list[str]:
    """Names containing ANY of these words."""
    wanted = [str(word).strip().lower() for word in words if str(word).strip()]
    return [name for name in names
            if any(word in name.lower() for word in wanted)]


def search(ips, keyword) -> dict:
    """Which packages match, and on which of these devices.

    The reply is shaped for the screen:

        {"keywords": […],
         "packages": [{"name": …, "present": [ip…], "missing": [ip…]}],
         "failed":   [{"ip": …, "error": …}]}

    A device that could not be read is in `failed` and NOT in any package's
    `missing`: "the application is not installed here" and "this address did
    not answer" are two different problems with two different next steps.

    `present` is also what the operation bar builds its targets from, so a
    device that does not carry a package is never sent a command about it.
    """
    words = keywords(keyword)
    if not words:
        raise ValueError(i18n.t("error.adbKeywordTooShort", count=MIN_KEYWORD))
    short = [word for word in words if len(word) < MIN_KEYWORD]
    if short:
        # One short word in a list of good ones would otherwise pull the
        # whole system in beside the three packages that were wanted.
        raise ValueError(i18n.t("error.adbKeywordTooShort", count=MIN_KEYWORD))

    targets = [str(ip) for ip in ips if str(ip or "").strip()]
    if not targets:
        raise ValueError(i18n.t("error.adbNoDeviceSelected"))

    found: dict[str, list[str]] = {}
    failed: list[dict] = []
    reached: list[str] = []
    # The devices are read in parallel and all three collections above are
    # written from those threads.
    lock = threading.Lock()

    def one(ip: str) -> None:
        try:
            names = matches(installed(ip), words)
        except Exception as exc:
            with lock:
                failed.append({"ip": ip, "error": user_message(exc)})
            return
        finally:
            client.disconnect(ip)
        with lock:
            reached.append(ip)
            for name in names:
                found.setdefault(name, []).append(ip)

    pool = ThreadPoolExecutor(
        max_workers=min(settings.ADB_WORKERS, len(targets)))
    try:
        list(pool.map(one, targets))
    finally:
        pool.shutdown(wait=True)

    packages = [{
        "name": name,
        "present": sorted(present),
        # Only devices that answered. See the docstring.
        "missing": sorted(ip for ip in reached if ip not in set(present)),
    } for name, present in sorted(found.items())]
    return {"keywords": words, "packages": packages,
            "failed": sorted(failed, key=lambda row: row["ip"])}
