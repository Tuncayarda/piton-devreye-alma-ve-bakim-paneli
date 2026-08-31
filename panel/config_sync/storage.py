#!/usr/bin/env python3
"""Persisting target values.

Values entered on the configuration screen are written to disk so they
survive a restart. NO PASSWORDS: secret fields never reach the file and live
in memory for the session only. This is the configuration-side counterpart of
"no password is stored in any file" (see panel.credentials).

`FORMAT` is written into the file and checked on read. A file from an
unknown format is ignored rather than guessed at: a value written to the
wrong field would be sent to a device.
"""
from __future__ import annotations

import json

from .. import settings
from .fields import FIELDS
from .store import DEVICE_TARGETS, GROUP_TARGETS, LOCK
from .validation import scope_key, validate

FORMAT = 3


def _storable(values: dict) -> dict:
    return {name: value for name, value in values.items()
            if name in FIELDS and not FIELDS[name].secret}


def _set_block(store: dict, set_no: int) -> dict:
    return {name: cleaned for (number, name), values in store.items()
            if number == set_no and (cleaned := _storable(values))}


def save() -> None:
    """Write the targets to disk. Failing to write does not break the flow."""
    with LOCK:
        set_numbers = sorted({n for n, _name in DEVICE_TARGETS}
                             | {n for n, _name in GROUP_TARGETS})
        sets = {}
        for number in set_numbers:
            groups = _set_block(GROUP_TARGETS, number)
            devices = _set_block(DEVICE_TARGETS, number)
            if groups or devices:
                sets[str(number)] = {"groups": groups, "devices": devices}
        body = {"format": FORMAT, "sets": sets}
    path = settings.config_defaults_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        temporary.replace(path)             # never leave a half-written file
    except OSError:
        pass


def _load_block(block, store: dict, *, set_no: int | None = None) -> int:
    """Validate one group/device block into the live or quarantine store."""
    if not isinstance(block, dict):
        return 0
    loaded = 0
    for name, values in block.items():
        if not isinstance(values, dict):
            continue
        try:
            key = (str(name) if set_no is None
                   else scope_key(set_no, str(name)))
        except ValueError:
            continue
        for field_name, value in values.items():
            if field_name not in FIELDS or FIELDS[field_name].secret:
                continue
            try:
                cleaned = validate(field_name, value)
            except ValueError:
                continue
            if cleaned:
                store.setdefault(key, {})[field_name] = cleaned
                loaded += 1
    return loaded


def load_saved_defaults() -> int:
    """Load saved targets into memory; return how many values were loaded.

    A corrupt file or a field that is no longer known is skipped: neither an
    old file preventing startup nor an undefined field being written to a
    device is acceptable.
    """
    body = _read_json(settings.config_defaults_file())
    if not isinstance(body, dict) or body.get("format") != FORMAT:
        return 0

    loaded = 0
    with LOCK:
        DEVICE_TARGETS.clear()
        GROUP_TARGETS.clear()
        loaded += _load_sets(body.get("sets"))
    return loaded


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _load_sets(sets) -> int:
    if not isinstance(sets, dict):
        return 0
    loaded = 0
    for raw_set, block in sets.items():
        try:
            number, _ = scope_key(raw_set, "_")
        except ValueError:
            continue
        if not isinstance(block, dict):
            continue
        loaded += _load_block(block.get("groups"), GROUP_TARGETS,
                              set_no=number)
        loaded += _load_block(block.get("devices"), DEVICE_TARGETS,
                              set_no=number)
    return loaded


def clear_saved_defaults(set_no: int | None = None) -> None:
    """Remove saved defaults from memory and disk.

    With `set_no` only that set is cleared. The parameterless form is for
    application/test shutdown and removes the whole store.
    """
    from .targets import forget_targets

    forget_targets(set_no)
    if set_no is not None:
        save()
        return
    try:
        settings.config_defaults_file().unlink()
    except OSError:
        pass


def saved_defaults_summary(set_no: int = 1) -> dict:
    """What the UI shows about saved state — counts, not values."""
    number, _ = scope_key(set_no, "_")
    with LOCK:
        group_values = sum(len(_storable(values))
                           for (set_number, _name), values
                           in GROUP_TARGETS.items() if set_number == number)
        device_values = sum(len(_storable(values))
                            for (set_number, _name), values
                            in DEVICE_TARGETS.items() if set_number == number)
    # The "unscoped" quarantine that used to be counted here was VERIFIED
    # DEAD: its only writer read the same always-empty dicts back from the
    # file its only producer wrote. Format-1 files, if any still exist in
    # the field, were never actually routed into it.
    return {"file": str(settings.config_defaults_file()),
            "saved": bool(group_values + device_values),
            "setNo": number, "groupValues": group_values,
            "deviceValues": device_values}
