#!/usr/bin/env python3
"""Constants and path resolution.

No credentials live here and none are read from any settings file — see
`panel.credentials`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The name people read is NOT here: it follows the chosen language and
# lives in the catalogue as "app.name" (panel/messages/*.json). APP_SLUG
# names THINGS ON DISK — the settings folder below, and the same word names
# the executable, the .app bundle and every release asset (see dabp.spec).
# Short and ASCII so it survives every shell, ZIP and installer it passes
# through, and unchanged by the language.
APP_SLUG = "dabp"
APP_VERSION = "1.0.6"

# From source this is the parent of this file; PyInstaller unpacks data into a
# temp dir and reports it via sys._MEIPASS.
_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
FROZEN = bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else ROOT


def data_file(name: str, *source_path: str) -> Path:
    """Path of a data file shipped with the app.

    From source the file stays where it lives in the tree (`source_path`,
    relative to ROOT). Once frozen the same file sits at the bundle root, so
    tree-relative paths would point outside the install directory.
    """
    if FROZEN:
        return resource_dir() / name
    return ROOT.joinpath(*(source_path or (name,)))


STATIC_DIR = resource_dir() / "static"
# Under `devicemaps/`: a folder per project for the maps, and `_base/` for the
# checklist template the trains share (see panel/editions/catalogue.py for the
# layout and why a project's files travel together). Both are still flat at
# the bundle root once frozen, which is what the tree-relative arguments to
# `data_file` exist for.
#
# These two are the DEFAULTS ONLY. `panel.editions.activate()` points
# DEVICE_MAP at the project the running edition opens with, and
# `editions.checklist_path()` answers with a project's own workbook when it
# carries one; the values here are what a bare import sees before either has
# run.
DEVICE_MAP = Path(os.environ.get("DEVICE_MAP_FILE")
                  or data_file("DeviceMap_Yatakli.json", "devicemaps",
                               "yatakli", "DeviceMap_Yatakli.json"))
EXCEL_TEMPLATE = data_file("Field_Device_Verification.xlsx",
                           "devicemaps", "_base",
                           "Field_Device_Verification.xlsx")


def documents_dir() -> Path:
    """Where generated files go — the operating system's Documents folder.

    An installed app may sit in a read-only directory, and writing next to the
    source tree just litters it.
    """
    override = os.environ.get("PANEL_OUTPUT_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    # On Linux the folder name may be localised; the desktop environment
    # reports the real path through XDG_DOCUMENTS_DIR.
    xdg = os.environ.get("XDG_DOCUMENTS_DIR")
    if xdg:
        return Path(os.path.expandvars(xdg)).expanduser()
    documents = home / "Documents"
    return documents if documents.is_dir() else home


OUTPUT_DIR = documents_dir()


# The edition owns a sub-folder of its own under the settings directory. Two
# editions may be installed side by side, and their saved state cannot be
# shared: configuration defaults are keyed by (train set, device id), device
# ids are POSITIONAL ("sw1.d3" is the third device on the first switch), and
# the same id names a different device in another project. A GDM target value
# read back on a Gaziray machine would be written to whatever hardware
# happens to sit in that slot.
#
# Set by `panel.editions.activate()` rather than read from here: settings
# must not import the edition table, which needs `data_file()` from this
# module.
_DATA_SUFFIX = ""


def set_data_suffix(name: str) -> None:
    global _DATA_SUFFIX
    _DATA_SUFFIX = str(name or "").strip()


def data_dir() -> Path:
    """Where the panel keeps its own persistent state.

    Only values the user set in the UI land here. NO PASSWORDS — neither device
    credentials nor SIP passwords; those stay in memory (see
    `panel.credentials`).

    The edition sub-folder is appended to PANEL_DATA_DIR as well as to the
    per-OS default: the override says WHERE the panel keeps its state, not
    that two editions pointed at it should share one file.
    """
    return _per_edition(_base_data_dir())


def _base_data_dir() -> Path:
    override = os.environ.get("PANEL_DATA_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_SLUG
    if os.name == "nt":
        return Path(os.environ.get("APPDATA")
                    or (home / "AppData" / "Roaming")) / APP_SLUG
    return Path(
        os.environ.get("XDG_CONFIG_HOME") or (home / ".config")) / APP_SLUG


def _per_edition(base: Path) -> Path:
    return base / _DATA_SUFFIX if _DATA_SUFFIX else base


def config_defaults_file() -> Path:
    """Target values entered on the configuration screen; never passwords."""
    return data_dir() / "config_defaults.json"


def network_settings_file() -> Path:
    """Choices about preparing the computer's own network.

    Only the adapter selected for the panel's addresses is kept here; the host
    octet and /24 prefix are fixed by `panel.network` policy. Addresses
    actually in place are recorded separately
    (`panel.network.aliases.record_file`), because those have to survive a
    crash to be cleaned up and this preference does not.
    """
    return data_dir() / "network.json"


def adb_devices_file() -> Path:
    """The ADB screen's own device list — addresses the user typed in.

    A FUNCTION rather than a constant, like every other path here: the
    edition sub-folder is appended by `activate()` at start-up, and a module
    constant would have been resolved before that happened.

    Unlike the DeviceMap this list is a PREFERENCE, not a definition. It
    belongs to no project, it is not derived from anything, and a corrupt
    file must leave the screen usable rather than stop the panel opening
    (see `panel.adb.pool`).
    """
    return data_dir() / "adb_devices.json"


def remote_session_file() -> Path:
    """This installation's random name for itself, for remote service sessions.

    NOT A SECRET and not a credential: a uuid4 that lets the grant service
    tie an answer to the machine that asked (see `panel.remotekey.session`).
    Losing it costs nothing, and a copy of it grants nothing — which is
    exactly what the service key's file cannot say for itself.
    """
    # `remote_session.json`, not `remote.json`: the catalogue now has a
    # `remote.` area, and tests/test_i18n.py reads any quoted `word.word` in
    # that area as a message key — a file name that looks like one is
    # reported as a key with no translation. The underscore ends that, and
    # the longer name says more anyway.
    return data_dir() / "remote_session.json"


def ui_settings_file() -> Path:
    """Choices about the interface itself — currently just the language.

    Kept next to the panel's own state rather than in the browser: browser
    storage is closed to this application (see tests/test_frontend.py), and
    the server needs the language too, to translate its own messages.
    """
    return data_dir() / "ui.json"


# ── engines under field_scripts/ ────────────────────────────────────────
# The panel imports two field-proven scripts at runtime instead of
# rewriting them (see panel.script_loader). Packaging copies them to the
# bundle root, so path resolution knows both locations.
DEVICE_VERIFY_SCRIPT = Path(
    os.environ.get("DEVICE_VERIFY_SCRIPT")
    or data_file("device_verify.py", "field_scripts", "device_verify.py"))
IP_ASSIGN_SCRIPT = Path(
    os.environ.get("IP_ASSIGN_SCRIPT")
    or data_file("intercom_ip_assign.py",
                 "field_scripts", "intercom_ip_assign.py"))

# ────────────────────────────────────────────────────── network / ports ──
KYLAND_PORT = int(os.environ.get("KYLAND_HTTP_PORT", "80"))

# Physical layout of the front panel. The SICOM3028GPT in the field has
# 24 PoE + 4 uplink ports. The panel draws the device's real face, empty
# ports included — otherwise the map does not match the hardware.
SWITCH_POE_PORTS = int(os.environ.get("SWITCH_POE_PORTS", "24"))
SWITCH_UPLINK_PORTS = int(os.environ.get("SWITCH_UPLINK_PORTS", "4"))
VIDEO_PORT = int(os.environ.get("VIDEO_HTTP_PORT", "80"))
ANNOUNCEMENT_PORT = int(os.environ.get("ARDUINO_HTTP_PORT", "80"))
MQTT_PORT = int(os.environ.get("PISCU_MQTT_PORT", "1883"))
ADB_PORT = int(os.environ.get("COMPARTMENT_LCD_ADB_PORT", "5555"))

# Panel app running on the Compartment LCD. This is the authoritative
# version source: `ro.build.display.id` is the Android build id, not the
# app version (see dumpsys package ... versionName).
ADB_PACKAGE = os.environ.get("COMPARTMENT_LCD_PACKAGE",
                             "com.piton.train_lcd_panel")
# Must that package be ON the display for the read to count?
#
# NORMALLY NOBODY ANSWERS THIS: the open project does (see
# `panel.probe.android.app_required`). A train's display is there to run the
# application and its absence is the fault being commissioned for; a
# demonstration stand carries borrowed hardware running whatever each unit
# happens to have, and demanding one named application turns the whole board
# red and hides the units that genuinely cannot be reached.
#
# This is the override for a bench that is neither: "1" forces the demand on,
# "0" off, and anything else (the default) leaves it to the project.
ADB_REQUIRE_PACKAGE = os.environ.get("ADB_REQUIRE_PACKAGE", "")
# SIP registration is read from the app's own log; the PBX has no ARI account.
ADB_LOG_TAG = os.environ.get("COMPARTMENT_LCD_LOG_TAG", "AnnounceSip")

MQTT_DEVICE_MAP_TOPIC = os.environ.get("PISCU_DEVICE_MAP_TOPIC", "ALFA/DeviceMap")
MQTT_APP_STATUS_PREFIX = os.environ.get("PISCU_APP_STATUS_PREFIX", "ALFA/AppStatus")
# SIP extension per device: ALFA/SipPort/10.1.1.40 -> {"SipPort": 6001}
MQTT_SIP_PORT_PREFIX = os.environ.get("PISCU_SIP_PORT_PREFIX", "ALFA/SipPort")

# ──────────────────────────────────────────────────────────── timeouts ────
# Per-device ceiling during a full scan. Kept short: one silent device must
# not hold up a 30-device sweep.
PROBE_TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "5.0"))
# A credential attempt keeps the user waiting; slightly more generous.
AUTH_TIMEOUT = float(os.environ.get("AUTH_TIMEOUT", "6.0"))
MQTT_TIMEOUT = float(os.environ.get("MQTT_TIMEOUT", "4.0"))
ADB_TIMEOUT = int(os.environ.get("ADB_TIMEOUT", "12"))
# Installing an APK takes far longer than reading: push, then package manager.
ADB_INSTALL_TIMEOUT = int(os.environ.get("ADB_INSTALL_TIMEOUT", "180"))
SCAN_WORKERS = int(os.environ.get("SCAN_WORKERS", "12"))

# How many devices are flashed at once. Lower than scanning: every install
# reboots a device and then waits for version verification, and blacking out
# 12 devices behind one switch strains both the PoE budget and the person
# standing next to them. Four cuts a 12-intercom set to a quarter of serial.
FIRMWARE_WORKERS = int(os.environ.get("FIRMWARE_WORKERS", "4"))

# How many devices are configured at once. Serial writes stacked every
# device's read + write + verify wait end to end. Same width as firmware:
# a write can reboot the device, so it must stay narrower than scanning.
CONFIG_WORKERS = int(os.environ.get("CONFIG_WORKERS", FIRMWARE_WORKERS))

# How many devices the ADB screen works on at once. Wider than firmware
# because most of what that screen does is cheap and does not reboot
# anything — starting, stopping and listing packages — and the operator is
# watching a table of devices fill in. Installing an APK through it is the
# one heavy operation and is bounded by the same per-device timeout as
# everywhere else.
ADB_WORKERS = int(os.environ.get("ADB_WORKERS", "8"))

# How long a rebooted display is given to answer again. Generous, because
# what the operator wants to know is not "the command was accepted" but "it
# came back": a reboot that is reported as done while the display is still
# dark is a reboot they have to go and check by eye. These images take
# 40-70 seconds; two minutes leaves room for a slow one without leaving
# somebody watching a spinner for ever.
ADB_REBOOT_WAIT = float(os.environ.get("ADB_REBOOT_WAIT", "120"))
# How long it is given to GO DOWN first. Short: this only proves the reboot
# was really taken, and a display that never drops the connection has
# ignored the command.
ADB_REBOOT_DOWN_WAIT = float(os.environ.get("ADB_REBOOT_DOWN_WAIT", "25"))

# ────────────────────────────────────────────────────────── verification ──
EXPECTED_TIMEZONE = os.environ.get("EXPECTED_TIMEZONE", "CST-3:00:00")
EXPECTED_SUBNET_MASK = os.environ.get("EXPECTED_SUBNET_MASK", "255.255.0.0")

# Address an unconfigured device ships with. This does NOT vary by train set:
# a device leaves the factory without knowing which set it will join, so they
# all arrive on the same address.
FACTORY_IP = os.environ.get("INTERCOM_FACTORY_IP", "10.1.1.12")

# Train set (the n in the IP template). Every set number from outside must
# fall in this range. It feeds the second octet directly (10.n.1.x), so the
# bound is the valid octet range; field sets are not a fixed list (49, 112
# are in use), and a tighter ceiling would only exclude real sets.
SET_MIN, SET_MAX = 1, 254

# API body ceiling. Local service or not, bodies are not read unbounded.
BODY_LIMIT = 64 * 1024

# Most devices read in one light-refresh round.
REFRESH_LIMIT = 64
# How many devices a light refresh reads at once. This round only visits
# devices that already answered, so no timeouts are expected and the same
# width as scanning does not tire them.
REFRESH_WORKERS = int(os.environ.get("REFRESH_WORKERS", SCAN_WORKERS))
