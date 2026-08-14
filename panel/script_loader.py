#!/usr/bin/env python3
"""Loads the working engines under field_scripts/.

The panel does not reimplement three field-proven scripts; it imports them
from disk at runtime:

    field_scripts/switch_api.py           switch access
    field_scripts/device_verify.py        field extraction + Excel schema
    field_scripts/intercom_ip_assign.py   IP assignment run

Why import rather than rewrite: a second implementation drifts from the first,
and an account that works on the switch panel starts reporting "unverified"
here.

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
        _LOADED[name] = module
        return module


def switch_api():
    """Switch management backend — the single source of switch access."""
    module = load_module("field_switch_api", settings.SWITCH_API_SCRIPT,
                         i18n.t("script.switchApi"))
    module.SWITCH_PORT = settings.KYLAND_PORT
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

