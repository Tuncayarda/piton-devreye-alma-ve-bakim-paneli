#!/usr/bin/env python3
"""Stable column identifiers for the checklist workbook.

A column has two names. The HEADING is what the operator reads in Excel — it
belongs to the shipped template and may be reworded, translated or reordered
at any time. The ID is what the code uses; it never changes.

Keying code off the heading made the two the same thing, so a heading edit
silently emptied a column. Everything below is addressed by id, and the
heading is resolved once, where the template is read.
"""
from __future__ import annotations

# ── column ids, in template order ────────────────────────────────────────
SECTION = "section"
SWITCH = "switch"
PORT = "port"
DEVICE_DEFINITION = "deviceDefinition"
IP_TEMPLATE = "ipTemplate"
EXPECTED_IP = "expectedIp"
EXPECTED_VERSION = "expectedVersion"
EXPECTED_SIP_EXTENSION = "expectedSipExtension"
DEVICE_NAME = "deviceName"
CONNECTION_INFO = "connectionInfo"
VERSION = "version"
DEVICE_NUMBER = "deviceNumber"
STATUS_DESCRIPTION = "statusDescription"
UPTIME = "uptime"
SPEAKER_VOLUME = "speakerVolume"
MIC_VOLUME = "micVolume"
SPEAKER_GAIN = "speakerGain"
MIC_GAIN = "micGain"
SIP_PBX = "sipPbx"
SIP_EXTENSION = "sipExtension"
SIP_OUTBOUND = "sipOutbound"
TIMEZONE = "timezone"
NETWORK_TIME = "networkTime"

# id -> the heading that id currently carries in the shipped template.
HEADING_FOR_COLUMN = {
    SECTION: "Section",
    SWITCH: "Switch",
    PORT: "Port",
    DEVICE_DEFINITION: "Device definition",
    IP_TEMPLATE: "IP template",
    EXPECTED_IP: "Expected IP",
    EXPECTED_VERSION: "Expected version",
    EXPECTED_SIP_EXTENSION: "Expected SIP extension",
    DEVICE_NAME: "Device name",
    CONNECTION_INFO: "Connection info",
    VERSION: "Version",
    DEVICE_NUMBER: "Device number",
    STATUS_DESCRIPTION: "Status description",
    UPTIME: "Uptime",
    SPEAKER_VOLUME: "Speaker volume",
    MIC_VOLUME: "Microphone volume",
    SPEAKER_GAIN: "Speaker gain",
    MIC_GAIN: "Microphone gain",
    SIP_PBX: "SIP PBX IP",
    SIP_EXTENSION: "SIP extension",
    SIP_OUTBOUND: "SIP outbound number",
    TIMEZONE: "Time zone",
    NETWORK_TIME: "Network/time check",
}

COLUMN_FOR_HEADING = {heading: column
                      for column, heading in HEADING_FOR_COLUMN.items()}

# Column ids filled in by hand in the template, never read from a device.
MANUAL_COLUMNS = frozenset({SECTION, SWITCH, PORT, DEVICE_DEFINITION,
                            IP_TEMPLATE, EXPECTED_IP, EXPECTED_VERSION,
                            EXPECTED_SIP_EXTENSION})

# probe result field -> the column its value lands in. The two happen to share
# most names, but the mapping stays explicit: a probe field is an API contract
# and a column id is a spreadsheet contract, and neither should drag the other
# along when it changes.
COLUMN_FOR_FIELD = {
    "version": VERSION,
    "serial": DEVICE_NUMBER,
    "uptime": UPTIME,
    "speakerVolume": SPEAKER_VOLUME,
    "micVolume": MIC_VOLUME,
    "speakerGain": SPEAKER_GAIN,
    "micGain": MIC_GAIN,
    "sipPbx": SIP_PBX,
    "sipExtension": SIP_EXTENSION,
    "sipOutbound": SIP_OUTBOUND,
    "timezone": TIMEZONE,
    "networkTime": NETWORK_TIME,
}

FIELD_FOR_COLUMN = {column: field
                    for field, column in COLUMN_FOR_FIELD.items()}

# Values written into the status column. They are read back by the summary
# formulas at the bottom of the sheet, so the workbook and this table have to
# be changed together.
STATUS_ACTIVE = "Active"
STATUS_INACTIVE = "Inactive"

# The full-width row that opens the formula summary; rows below it are not
# part of the device list.
SUMMARY_HEADING = "RESULT"


def column_for_heading(heading) -> str:
    """The id of a heading read from the template ("" when unknown)."""
    return COLUMN_FOR_HEADING.get(str(heading or "").strip(), "")
