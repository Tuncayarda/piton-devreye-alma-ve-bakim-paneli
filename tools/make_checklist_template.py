#!/usr/bin/env python3
"""Build a project's checklist workbook from its DeviceMap.

    python3 tools/make_checklist_template.py fuar

WHY A TOOL AND NOT A HAND-MADE FILE. The workbook matches its rows to devices
by IP template (`panel/checklist/workbook.py`), and the greyed-out cells in it
are what the on-screen preview reads to decide which fields a device type even
has (`panel/checklist/preview.py`). A file typed by hand drifts from the
DeviceMap the first time a device moves port, and the drift is silent: the row
simply stops being filled.

THE STYLE COMES FROM THE YATAKLI TEMPLATE, which is the one that was designed.
Its header rows are copied verbatim, and each device row takes its formatting
from a row of the same device type there — including the grey N/A fills, which
carry the real knowledge in this file: which columns a PISCU has and a camera
has not. Nothing about that is re-decided here.

A type the base template has never seen falls back to another with the SAME
READ METHOD, because that is what decides which fields exist. The fallback is
printed, so a new device type shows up in the output rather than quietly
inheriting the wrong columns.
"""
from __future__ import annotations

import shutil
import sys
from copy import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import openpyxl                                        # noqa: E402

from panel.editions import catalogue                   # noqa: E402
from panel.inventory import catalog, device_map        # noqa: E402

BASE = ROOT / "Field_Device_Verification.xlsx"
SHEET = "Checklist"
HEADER_ROWS = 4                     # set-no, title, groups, column headings
BANNER_FILL = "FFBDD7EE"


def _key(device) -> tuple[str, str]:
    return (device.type, device.subtype or "")


def _label(type_name: str, subtype: str) -> str:
    return f"{type_name} · {subtype}" if subtype else type_name


def donors(worksheet) -> list[tuple[str, str, int]]:
    """(type, subtype, row) read out of the base template's banners.

    Read from the file rather than listed here: the template is the source of
    truth for which columns a type has — the grey cells ARE that knowledge —
    and a list beside it would be a second one to keep in step.

    Matched case-insensitively later: the banners are shouted ("SWITCH") and
    a DeviceMap is not ("Switch").
    """
    found: list[tuple[str, str, int]] = []
    section = None
    for row in range(HEADER_ROWS + 1, worksheet.max_row + 1):
        cell = worksheet.cell(row, 1)
        fill = cell.fill.fgColor.rgb if cell.fill and cell.fill.fgColor else ""
        if cell.value and fill == BANNER_FILL:
            head = str(cell.value).split("·")[0:2]
            name = head[0].strip()
            sub = (head[1].strip()
                   if len(head) > 1 and "record" not in head[1] else "")
            section = (name, sub)
            continue
        known = any(t == section[0] and s == section[1] for t, s, _r in found)
        if cell.value and section and not known:
            found.append((section[0], section[1], row))
    return found


# Decided by hand, with the reason, where the rules below cannot tell.
# A gooseneck microphone is a microphone: it reports the same gains and the
# same outbound number a handset does, and the rules would otherwise hand it
# the UIC row, which has neither.
BY_HAND = {("announcement", "swanneck"): ("Announcement", "Handset")}


def pick_donor(device, table, worksheet) -> tuple[int, str]:
    """The row to copy formatting from, and a note when it is not exact.

    THE READ METHOD OUTRANKS THE SUBTYPE, because it is what decides which
    fields a device has at all. An LCD·Twin is read over ADB and an
    LCD·Landing over MQTT; taking the Landing row because both are LCDs would
    grey out the version, timezone and SIP columns the Twin actually fills.
    """
    label = _label(device.type, device.subtype or "")
    want = (device.type.lower(), (device.subtype or "").lower())
    method = catalog.read_method_for(device.type, device.subtype or "")

    def find(match):
        for name, sub, row in table:
            if match(name, sub):
                return name, sub, row
        return None

    exact = find(lambda n, s: (n.lower(), s.lower()) == want)
    if exact:
        return exact[2], ""

    chosen = BY_HAND.get(want)
    if chosen:
        found = find(lambda n, s: (n, s) == chosen)
        if found:
            return found[2], f"{label}: the {_label(*chosen)} row — decided by hand"

    for describe, match in (
            ("same type, same read method",
             lambda n, s: n.lower() == want[0]
             and catalog.read_method_for(n, s) == method),
            (f"same read method ({method})",
             lambda n, s: catalog.read_method_for(n, s) == method),
            ("same type", lambda n, s: n.lower() == want[0])):
        found = find(match)
        if found:
            return found[2], (f"{label}: the {_label(found[0], found[1])} "
                              f"row — {describe}")
    raise SystemExit(f"[tool] no row to copy formatting from: {label}")


def build(project_key: str) -> Path:
    project = next((p for p in catalogue.ALL_PROJECTS
                    if p.key == project_key), None)
    if project is None:
        raise SystemExit(f"[tool] unknown project: {project_key}. Choices: "
                         f"{', '.join(p.key for p in catalogue.ALL_PROJECTS)}")
    source = ROOT.joinpath(*project.source_path)
    if not source.exists():
        raise SystemExit(f"[tool] no DeviceMap at {source}")

    inventory = device_map.load(1, path=source, cache=False)

    # THE BASE FILE IS COPIED AND EDITED, not rebuilt beside it. openpyxl
    # stores a cell's formatting as an index into the workbook's own style
    # tables, so a style carried across two workbooks points at nothing —
    # which is not an error until the file is opened. Editing one workbook
    # keeps every index valid, and the header rows, column widths, frozen
    # pane and print setup come along untouched.
    name = f"Field_Device_Verification_{project.label}.xlsx"
    out_path = ROOT / "devicemaps" / name
    shutil.copy(BASE, out_path)
    book = openpyxl.load_workbook(out_path)
    sheet = book[SHEET]
    columns = sheet.max_column
    table = donors(sheet)

    # Devices grouped by type, in the order the DeviceMap lists them: the
    # operator walks the rack in that order and the sheet should follow.
    groups: dict[tuple[str, str], list] = {}
    for device in inventory.devices:
        groups.setdefault(_key(device), []).append(device)

    plan, notes = [], []
    for key, devices in groups.items():
        donor, note = pick_donor(devices[0], table, sheet)
        if note:
            notes.append(note)
        plan.append((key, devices, donor, sheet.cell(donor - 1, 1).row))

    # Every body merge goes before anything is written: the banners are
    # full-width merges and a leftover one would swallow a device row.
    for merged in list(sheet.merged_cells.ranges):
        if merged.min_row > HEADER_ROWS:
            sheet.unmerge_cells(str(merged))

    def copy_row(donor_row: int, into: int) -> None:
        for column in range(1, columns + 1):
            src, dst = sheet.cell(donor_row, column), sheet.cell(into, column)
            dst._style = copy(src._style)
            dst.value = None

    row = HEADER_ROWS + 1
    banners = []
    for key, devices, donor, banner_row in plan:
        copy_row(banner_row, row)
        sheet.cell(row, 1).value = f"  {_label(*key)}   ·   {len(devices)} records"
        banners.append(row)
        row += 1
        for device in devices:
            copy_row(donor, row)
            sheet.cell(row, 1).value = project.label
            sheet.cell(row, 2).value = device.switch_name
            sheet.cell(row, 3).value = device.port
            sheet.cell(row, 4).value = device.name
            sheet.cell(row, 5).value = device.ip_template
            sheet.cell(row, 6).value = (
                f'=IF($B$1="","",SUBSTITUTE(E{row},"n",$B$1))')
            row += 1

    if sheet.max_row >= row:
        sheet.delete_rows(row, sheet.max_row - row + 1)
    for banner in banners:
        sheet.merge_cells(start_row=banner, start_column=1,
                          end_row=banner, end_column=columns)
    sheet.cell(2, 1).value = (
        f"{project.label.upper()} — FIELD DEVICE VERIFICATION")

    book.save(out_path)
    print(f"[tool] {out_path.relative_to(ROOT)} — {len(inventory.devices)} "
          f"devices, {len(groups)} sections, {row - 1} rows")
    for note in notes:
        print(f"[tool] formatting borrowed — {note}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(sys.argv[1])
