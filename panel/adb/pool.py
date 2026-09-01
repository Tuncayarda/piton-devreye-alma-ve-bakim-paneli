#!/usr/bin/env python3
"""The ADB screen's own list of devices.

IT IS NOT A DEVICE MAP AND MUST NOT BECOME ONE. Every other screen in the
panel works from the project definition: a device has an id, a type, a switch
port and a place in a train set, and that definition is the truth against
which the field is checked. This list is the opposite kind of thing — a bench
tool's address book. Somebody types in the four displays on the table in
front of them, or imports the twelve they were given in an e-mail, and works
on those. Nothing here knows which project is open, and nothing here should.

That difference decides how failure is handled, and it is the reverse of the
DeviceMap's rule. A broken DeviceMap STOPS THE PANEL (`device_map.py` raises
on purpose): opening it half-read would mean writing an address to whatever
device happens to sit in that slot. A broken list here must leave the screen
WORKING — the bad line is dropped and the rest is kept, because the worst
outcome is an operator locked out of a tool by a file they can retype in
thirty seconds.

The file follows the `format` contract the configuration store already uses
(`panel.config_sync.storage`): the number is written in and checked on read,
so a file from a future version is ignored rather than guessed at.

    {"format": 1, "devices": [{"ip": "10.1.1.47", "label": "bench 2"}]}

`label` is optional and may be empty: an operator who has typed four
addresses should not have to name them as well.
"""
from __future__ import annotations

import ipaddress
import json
import threading
from pathlib import Path

from .. import i18n, settings

FORMAT = 1
# What one entry may hold. Bounds rather than validation for its own sake:
# the file can be hand-edited and the import below reads a file chosen from
# a USB stick or an e-mail attachment.
MAX_DEVICES = 512
MAX_LABEL = 60
# Ceiling on an imported file, the same reasoning as `panel.adminkey.pack`:
# nothing read from removable media is read unbounded.
MAX_IMPORT_BYTES = 256 * 1024

# One writer at a time. Reentrant because `add`/`remove` read the current
# list, change it and write it back, and all three take the lock.
#
# PER PROCESS, and that is all it can be. Two copies of the panel running on
# one machine share this file, as they share every other file under
# `data_dir()`; the atomic write below is what keeps a race between them to a
# lost edit rather than a lost file.
_LOCK = threading.RLock()


class PoolError(ValueError):
    """The list itself could not be changed — a bad address, or a full list."""


def normalise_ip(value) -> str:
    """The address as it will be stored, or raise.

    IPv4 only, and no port: the port is a panel-wide setting
    (`settings.ADB_PORT`) and a second one typed into an address field is a
    silent way of reaching a device the rest of the panel cannot.
    """
    text = str(value or "").strip()
    if not text:
        raise PoolError(i18n.t("error.adbAddressRequired"))
    if ":" in text or "/" in text:
        raise PoolError(i18n.t("error.adbAddressPlain"))
    try:
        parsed = ipaddress.IPv4Address(text)
    except ValueError as exc:
        raise PoolError(i18n.t("error.adbAddressInvalid")) from exc
    return str(parsed)


# ── one box, several addresses ──────────────────────────────────────────
# What an operator actually types when they have twelve displays in front of
# them. Adding those one at a time is twelve rounds of type-tab-type-Enter,
# and the addresses are consecutive, which is the whole point of a range.
#
#     10.1.1.45                one
#     10.1.1.45, 10.1.1.51     a list, comma or semicolon or whitespace
#     10.1.1.45-47             .45 .46 .47 — the short form, LAST OCTET only
#     10.1.1.45-10.1.1.47      the long form, written out
#
# BOTH ENDS ARE INCLUDED. "45-47" means three displays to the person holding
# them, and a range that quietly dropped .47 would be found by the operator
# rather than by anyone reading this.
#
# The short form is deliberately limited to the last octet. `10.1.1.45-10.2.1.5`
# is arithmetic nobody typed on purpose, and a range that crosses a network is
# far more likely to be a typo than an intention — see MAX_RANGE.
MAX_RANGE = 256
_SEPARATORS = (";", "\n", "\t")


def _range(text: str) -> list[str] | None:
    """`10.1.1.45-47` or `10.1.1.45-10.1.1.47` -> every address in it."""
    if "-" not in text:
        return None
    first, _, last = text.partition("-")
    start = normalise_ip(first)
    tail = last.strip()
    if not tail:
        raise PoolError(i18n.t("error.adbRangeInvalid", range=text))
    # The short form: only the final octet was written out.
    end = (normalise_ip(tail) if "." in tail
           else normalise_ip(start.rsplit(".", 1)[0] + "." + tail))
    low, high = int(ipaddress.IPv4Address(start)), int(ipaddress.IPv4Address(end))
    if high < low:
        raise PoolError(i18n.t("error.adbRangeBackwards", range=text))
    if high - low + 1 > MAX_RANGE:
        raise PoolError(i18n.t("error.adbRangeTooLarge", range=text,
                               maximum=MAX_RANGE))
    return [str(ipaddress.IPv4Address(value)) for value in range(low, high + 1)]


def parse_addresses(value) -> list[str]:
    """Every address one box asked for, in order, without duplicates.

    ONE BAD PIECE FAILS THE WHOLE BOX, unlike the file import, and the two
    differ on purpose. A file is somebody else's and arrives with whatever is
    in it, so the readable rows are kept and the rest counted. This is what
    the operator just typed: a silently dropped piece is an address they
    believe they added and will look for later.
    """
    text = str(value or "")
    for separator in _SEPARATORS:
        text = text.replace(separator, ",")
    pieces = [piece.strip() for piece in text.replace(" ", ",").split(",")]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        raise PoolError(i18n.t("error.adbAddressRequired"))

    found: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        for ip in (_range(piece) or [normalise_ip(piece)]):
            if ip not in seen:
                seen.add(ip)
                found.append(ip)
    return found


def normalise_label(value) -> str:
    return " ".join(str(value or "").split())[:MAX_LABEL]


def _entry(raw) -> dict | None:
    """One stored row, or None when it cannot be read.

    Accepts a bare string as well as an object. An operator's own list is
    very often a plain array of addresses — from a spreadsheet column, or
    typed into a text editor — and refusing it would mean refusing the
    common case to keep one shape.
    """
    if isinstance(raw, str):
        ip, label = raw, ""
    elif isinstance(raw, dict):
        ip, label = raw.get("ip"), raw.get("label")
    else:
        return None
    try:
        return {"ip": normalise_ip(ip), "label": normalise_label(label)}
    except PoolError:
        return None


def _read(path: Path) -> list[dict]:
    """Whatever of the file can be read. Never raises."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(body, dict) or body.get("format") != FORMAT:
        return []
    return _clean(body.get("devices"))


def _clean(raw_list) -> list[dict]:
    """Valid rows only, in order, with duplicate addresses collapsed."""
    if not isinstance(raw_list, list):
        return []
    seen: set[str] = set()
    devices: list[dict] = []
    for raw in raw_list[:MAX_DEVICES * 4]:
        entry = _entry(raw)
        if entry is None or entry["ip"] in seen:
            continue
        seen.add(entry["ip"])
        devices.append(entry)
        if len(devices) >= MAX_DEVICES:
            break
    return devices


def _write(devices: list[dict]) -> None:
    """Replace the file atomically, or raise OSError.

    tmp + `replace()`, the way the configuration store writes
    (`config_sync/storage.py`). A plain `write_text` that dies half way
    leaves a file that reads as an EMPTY list, and the operator's address
    book is gone with no error anywhere — which is exactly the shape of the
    bug this list must not have.
    """
    path = settings.adb_devices_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"format": FORMAT, "devices": devices},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    temporary.replace(path)


def load() -> list[dict]:
    """The devices, as the screen shows them."""
    with _LOCK:
        return _read(settings.adb_devices_file())


def replace_all(entries) -> list[dict]:
    """Store exactly this list, and hand back what was stored.

    Every mutation below funnels through here, and every one of them returns
    the list READ BACK rather than the list it meant to write — the same
    rule `panel.network.prepare.save_preferences` follows. A screen that
    draws what it hoped happened is a screen that shows an address which is
    not in the file.
    """
    with _LOCK:
        devices = _clean(entries)
        _write(devices)
        return load()


def add(ip, label="") -> list[dict]:
    """Add one address, or update the label of one already there."""
    with _LOCK:
        entry = {"ip": normalise_ip(ip), "label": normalise_label(label)}
        devices = load()
        for existing in devices:
            if existing["ip"] == entry["ip"]:
                # Re-adding is how a label is corrected; it is not an error.
                existing["label"] = entry["label"] or existing["label"]
                return replace_all(devices)
        if len(devices) >= MAX_DEVICES:
            raise PoolError(i18n.t("error.adbPoolFull", limit=MAX_DEVICES))
        return replace_all([*devices, entry])


def add_many(value, label="") -> tuple[list[dict], int]:
    """Add everything one box asked for. Returns (devices, how many were new).

    The label goes on every address the box produced. That is right for a
    range — "cabin 3" for .45 to .47 is a shelf, not three names — and it is
    what the operator gets to correct afterwards by re-adding one of them.
    """
    with _LOCK:
        wanted = parse_addresses(value)
        text = normalise_label(label)
        devices = load()
        known = {entry["ip"] for entry in devices}
        fresh = [ip for ip in wanted if ip not in known]
        if len(devices) + len(fresh) > MAX_DEVICES:
            raise PoolError(i18n.t("error.adbPoolFull", limit=MAX_DEVICES))
        for entry in devices:
            if entry["ip"] in wanted and text:
                # Re-adding is how a label is corrected; it is not an error.
                entry["label"] = text
        devices.extend({"ip": ip, "label": text} for ip in fresh)
        return replace_all(devices), len(fresh)


def remove(ip) -> list[dict]:
    """Drop one address. Removing one that is not there is not an error."""
    with _LOCK:
        wanted = normalise_ip(ip)
        return replace_all(
            [entry for entry in load() if entry["ip"] != wanted])


def clear() -> list[dict]:
    with _LOCK:
        return replace_all([])



def addresses() -> list[str]:
    return [entry["ip"] for entry in load()]


# ── handing the list to somebody else ───────────────────────────────────
# The file name is fixed rather than stamped with the time. This is an address
# book, not a record: an operator who exports twice in an afternoon wants the
# second file, and a Documents folder filling up with
# `adb-devices-2026-08-28T14-03-11.json` is how a convenience becomes a chore.
EXPORT_NAME = "adb-devices.json"


def write_export(path=None) -> Path:
    """Write the list where somebody can pick it up. Returns the path.

    `path` is what the operator named in the OS save dialog (see
    `panel/system/files.pick_save_path` — the route opens it, never this
    module). Without one it falls back to the OS Documents folder, which is
    where this panel puts everything it produces for a person to carry away
    (the checklist workbook is the other one — `panel/checklist/workbook.py`).

    The SAME SHAPE THE IMPORT READS, format number included, so a list
    exported here goes back in through `read_import` above without anybody
    editing it. `tests/test_adb.py` holds the round trip.
    """
    target = Path(path) if path else (settings.OUTPUT_DIR / EXPORT_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Written whole rather than atomically, unlike `_write` above: this is a
    # copy for somebody else, and a half-written one is noticed at once by the
    # person opening it. The address book itself is the file that must never
    # be left empty.
    target.write_text(
        json.dumps({"format": FORMAT, "devices": load()},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return target


# ── importing a list somebody sent ──────────────────────────────────────
def read_import(path) -> tuple[list[dict], int]:
    """Parse a chosen file: (entries, how many lines were unusable).

    THE SKIPPED COUNT IS PART OF THE ANSWER, not a detail to swallow. A file
    with three good addresses and nine typos imports three devices, and an
    operator who is told only "3 imported" will spend the afternoon looking
    for the other nine on the bench.
    """
    file_path = Path(path)
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise PoolError(i18n.t("error.adbImportUnreadable")) from exc
    if size > MAX_IMPORT_BYTES:
        raise PoolError(i18n.t("error.adbImportTooLarge"))
    try:
        body = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PoolError(i18n.t("error.adbImportNotJson")) from exc

    if isinstance(body, list):
        raw_list = body
    elif isinstance(body, dict) and isinstance(body.get("devices"), list):
        raw_list = body["devices"]
    else:
        raise PoolError(i18n.t("error.adbImportShape"))

    entries, skipped = [], 0
    for raw in raw_list:
        entry = _entry(raw)
        if entry is None:
            skipped += 1
            continue
        entries.append(entry)
    return entries, skipped


def adopt(entries) -> list[dict]:
    """The imported file BECOMES the list. Returns it as stored.

    AN IMPORT REPLACES; it does not add. It added once, and the reasoning
    was that somebody importing a colleague's twelve addresses has their own
    four on the bench in front of them. In use it reads the other way round:
    the file IS the bench a moment from now — a train handed over, a list
    sent for a job — and the addresses left from the last one had to be
    picked out of the table a row at a time, which is the chore the button
    was there to save.

    Nothing goes silently: what the panel holds can be written out first
    (`write_export`), the screen asks before it replaces a list that has
    anything in it, and the count is said out loud afterwards.
    """
    with _LOCK:
        return replace_all(entries)
