#!/usr/bin/env python3
"""Stable column identifiers for the checklist workbook.

A column has two names. The HEADING is what the operator reads in Excel — it
belongs to the shipped template and may be reworded, translated or reordered
at any time. The ID is what the code uses; it never changes.

Keying code off the heading made the two the same thing, so a heading edit
silently emptied a column. Everything below is addressed by id, and the
heading is resolved once, where the template is read.

The contract itself — the ids and the heading each id currently carries —
lives in field_scripts/device_verify.py (COL_* / COLUMN_HEADINGS): the script
fills the same workbook in the field, and this module used to keep a second
copy of its table with only a "change together" comment holding the two in
step. Now the script is the single source and this module re-exports its
names: ``columns.SECTION`` is the script's ``COL_SECTION``,
``HEADING_FOR_COLUMN`` is its ``COLUMN_HEADINGS``, and so on — the loader
guarantees every one of them exists (script_loader.CONTRACTS). Only what is
genuinely panel-side stays defined here: how probe result fields map onto
columns, and the summary heading the preview stops at.

The re-export is lazy (a PEP 562 module ``__getattr__``): loading the script
imports openpyxl and requests, which the panel defers until Excel work
actually starts (see script_loader.device_verify). Importing this module has
to stay cheap — it happens at API startup, long before any template is read.
Attributes resolve on first use, by which time every caller is doing Excel
work anyway, and are then cached in the module.
"""
from __future__ import annotations

from .. import script_loader

# The full-width row that opens the formula summary; rows below it are not
# part of the device list. Panel-only: the field script fills device rows and
# never reads the summary block.
SUMMARY_HEADING = "RESULT"

# Panel names served straight from the script, under their historical names
# here. Every other UPPERCASE attribute resolves to the script's COL_* twin
# (SECTION -> COL_SECTION, ...).
_SCRIPT_TABLES = {
    "HEADING_FOR_COLUMN": "COLUMN_HEADINGS",
    "COLUMN_FOR_HEADING": "COLUMN_FOR_HEADING",
    # Values written into the status column. The summary formulas at the
    # bottom of the sheet count these exact strings, and the script writes
    # them too — one spelling for both.
    "STATUS_ACTIVE": "STATUS_ACTIVE",
    "STATUS_INACTIVE": "STATUS_INACTIVE",
}


def _verify():
    """The loaded field script (script_loader caches it)."""
    return script_loader.device_verify()


def _column_for_field(verify) -> dict[str, str]:
    """probe result field -> the column its value lands in.

    Panel-only. The two sides happen to share most names, but the mapping
    stays explicit: a probe field is an API contract and a column id is a
    spreadsheet contract, and neither should drag the other along when it
    changes.
    """
    return {
        "version": verify.COL_VERSION,
        "serial": verify.COL_DEVICE_NUMBER,
        "uptime": verify.COL_UPTIME,
        "speakerVolume": verify.COL_SPEAKER_VOLUME,
        "micVolume": verify.COL_MIC_VOLUME,
        "speakerGain": verify.COL_SPEAKER_GAIN,
        "micGain": verify.COL_MIC_GAIN,
        "sipPbx": verify.COL_SIP_PBX,
        "sipExtension": verify.COL_SIP_EXTENSION,
        "sipOutbound": verify.COL_SIP_OUTBOUND,
        "timezone": verify.COL_TIMEZONE,
        "networkTime": verify.COL_NETWORK_TIME,
    }


def __getattr__(name: str):
    """Resolve a script-backed name on first use and cache it here."""
    if name.startswith("_") or not name.isupper():
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}")
    verify = _verify()
    if name in _SCRIPT_TABLES:
        value = getattr(verify, _SCRIPT_TABLES[name])
    elif name == "MANUAL_COLUMNS":
        # Column ids filled in by hand in the template, never read from a
        # device — by the script's own definition the exact complement of
        # what it fills ("everything else is filled in by hand").
        value = frozenset(verify.COLUMN_HEADINGS) - frozenset(verify.FILLABLE)
    elif name == "COLUMN_FOR_FIELD":
        value = _column_for_field(verify)
    elif name == "FIELD_FOR_COLUMN":
        value = {column: field
                 for field, column in _column_for_field(verify).items()}
    elif hasattr(verify, "COL_" + name):
        value = getattr(verify, "COL_" + name)
    else:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def column_for_heading(heading) -> str:
    """The id of a heading read from the template ("" when unknown)."""
    return _verify().COLUMN_FOR_HEADING.get(str(heading or "").strip(), "")
