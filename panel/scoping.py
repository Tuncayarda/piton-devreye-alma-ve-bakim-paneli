#!/usr/bin/env python3
"""Small validators shared across otherwise unrelated packages.

`scope_key` used to live in `panel.config_sync.validation` and `is_ipv4`
beside it. Both are (set number, identifier) plumbing with no configuration
semantics — and `firmware.selection` importing `scope_key` from config_sync
was the one edge that closed a three-package import cycle
(ip_assign → firmware → config_sync → ip_assign). Moving the helpers here
breaks that edge without moving any behaviour; `config_sync.validation`
re-exports both so its own callers do not change.
"""
from __future__ import annotations

from . import i18n, settings


def is_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    return all(part.isdigit() and len(part) <= 3 and 0 <= int(part) <= 255
               for part in parts)


def scope_key(set_no, name: str) -> tuple[int, str]:
    """Turn a set number and a device/group id into a safe store key."""
    try:
        number = int(set_no)
    except (TypeError, ValueError):
        raise ValueError(i18n.t("error.invalidSetNumber"))
    if not (settings.SET_MIN <= number <= settings.SET_MAX):
        raise ValueError(i18n.t("error.invalidSetNumber"))
    identifier = str(name or "").strip()
    if not identifier or len(identifier) > 128:
        raise ValueError(i18n.t("error.invalidTargetId"))
    return number, identifier
