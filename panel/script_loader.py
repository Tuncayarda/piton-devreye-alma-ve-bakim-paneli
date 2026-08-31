#!/usr/bin/env python3
"""Loads the working engines under field_scripts/.

The panel does not reimplement two field-proven scripts; it imports them
from disk at runtime:

    field_scripts/device_verify.py        field extraction + Excel schema
    field_scripts/intercom_ip_assign.py   IP assignment run

Why import rather than rewrite: a second implementation drifts from the first,
and a run that works in the field starts failing here.

Switch access used to be a third entry. It is not any more — it is
`panel.switch`, part of this package, because the switch screen needs to WRITE
and a borrowed read-only script could not grow that without becoming a second
client to the same hardware.

The scripts live outside the package tree, so a plain `import` will not do.
Each is loaded once and cached. A missing script is not skipped silently —
the caller gets a readable error.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

from . import settings
from . import i18n

_LOCK = threading.Lock()
_LOADED: dict[str, object] = {}

# Every attribute the panel reaches for on a loaded script, verified the
# moment the script executes. The scripts also run standalone in the field,
# so nothing stops a rename over there from landing here — and reaching for
# the names lazily meant a rename did not fail, it DEGRADED: a missing
# `_parse_mac_table` quietly turned MAC→port verification off for a whole IP
# run. One loud RuntimeError at load is the version of that mistake someone
# actually notices. Each name below is listed with the panel module that
# consumes it, so the next rename knows every place that must move with it.
CONTRACTS: dict[str, tuple[str, ...]] = {
    # intercom_ip_assign.py
    #   panel/ip_assign/runner.py         main, BEFORE_WRITE
    #   panel/probe/switch.py             MAC_ENDPOINTS, parse_mac_table
    #   panel/ip_assign/lcd_runner.py     reset_mac_cache, poe_read,
    #                                     poe_apply, wait_for_link,
    #                                     verify_port, arp_forget
    #   panel/ip_assign/audit.py          probe_all, arp_forget
    #   panel/ip_assign/factory_reset.py  probe_all, read_settings, write_ip,
    #                                     host_mac, arp_forget
    #   panel/ip_assign/addressing.py     can_flush_arp, arp_forget
    "field_ip_assign": (
        "main", "BEFORE_WRITE", "MAC_ENDPOINTS", "parse_mac_table",
        "reset_mac_cache", "poe_read", "poe_apply", "wait_for_link",
        "verify_port", "arp_forget", "probe_all", "read_settings",
        "write_ip", "host_mac", "can_flush_arp",
    ),
    # device_verify.py
    #   panel/checklist/workbook.py       FILLABLE, HEADER_ROW, NA_FILL
    #   panel/checklist/preview.py        HEADER_ROW, NA_FILL
    #   panel/checklist/columns.py        COL_*, COLUMN_HEADINGS,
    #                                     COLUMN_FOR_HEADING, STATUS_*
    #                                     (the script is the single source of
    #                                     the column contract; the panel
    #                                     re-exports these names)
    "field_device_verify": (
        "FILLABLE", "HEADER_ROW", "NA_FILL",
        "COLUMN_HEADINGS", "COLUMN_FOR_HEADING",
        "STATUS_ACTIVE", "STATUS_INACTIVE",
        "COL_SECTION", "COL_SWITCH", "COL_PORT", "COL_DEVICE_DEFINITION",
        "COL_IP_TEMPLATE", "COL_EXPECTED_IP", "COL_EXPECTED_VERSION",
        "COL_EXPECTED_SIP_EXTENSION", "COL_DEVICE_NAME",
        "COL_CONNECTION_INFO", "COL_VERSION", "COL_DEVICE_NUMBER",
        "COL_STATUS_DESCRIPTION", "COL_UPTIME", "COL_SPEAKER_VOLUME",
        "COL_MIC_VOLUME", "COL_SPEAKER_GAIN", "COL_MIC_GAIN", "COL_SIP_PBX",
        "COL_SIP_EXTENSION", "COL_SIP_OUTBOUND", "COL_TIMEZONE",
        "COL_NETWORK_TIME",
    ),
}


def load_module(name: str, path: Path, description: str):
    """Load the module at `path` once and return it."""
    with _LOCK:
        ready = _LOADED.get(name)
        if ready is not None:
            return ready
        if not Path(path).exists():
            raise RuntimeError(i18n.t("error.scriptNotFound",
                                  description=description, path=path))
        spec = importlib.util.spec_from_file_location(name, str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(i18n.t("error.scriptNotImported",
                                  description=description, path=path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        missing = [attr for attr in CONTRACTS.get(name, ())
                   if not hasattr(module, attr)]
        if missing:
            # Out of sys.modules again: a later retry must reload the file,
            # not find this rejected half-registered module by import.
            sys.modules.pop(name, None)
            raise RuntimeError(i18n.t("error.scriptContractBroken",
                                  description=description,
                                  missing=", ".join(missing)))
        _LOADED[name] = module
        return module


def device_verify():
    """Field verification script — field helpers and the Excel schema.

    Requires openpyxl, so it is only loaded when actually needed (extracting
    fields and producing Excel, not while scanning).
    """
    return load_module("field_device_verify", settings.DEVICE_VERIFY_SCRIPT,
                       i18n.t("script.deviceVerify"))


def intercom_ip_assign():
    """IP assignment script — PoE port toggling and writing IPs."""
    return load_module("field_ip_assign", settings.IP_ASSIGN_SCRIPT,
                       i18n.t("script.ipAssign"))

