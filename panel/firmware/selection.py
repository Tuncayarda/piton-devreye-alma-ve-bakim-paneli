#!/usr/bin/env python3
"""Which file is queued for which device — memory only."""
from __future__ import annotations

import threading
from pathlib import Path

from ..config_sync.validation import scope_key
from .. import i18n

MAX_SIZE = 32 * 1024 * 1024      # 32 MB — these devices' images are tiny

# (set number, device id) -> {"path": Path, "size": int, "version": str}
# DeviceMap ids repeat across sets; without the set scope an image picked for
# Set 1 would leak to the same-named device when Set 2 was opened.
_SELECTED: dict[tuple[int, str], dict] = {}
_LOCK = threading.Lock()


def validate_file(path: str) -> tuple[Path, int]:
    """Check the path and return (path, size). Raises ValueError if invalid.

    Called the moment the user supplies a path, not at install time: learning
    about a typo only during a run means learning at the worst moment, while
    devices are being flashed in sequence.
    """
    target = Path(str(path or "").strip()).expanduser()
    if not target.is_file():
        raise ValueError(i18n.t("error.selectionFileNotFound",
                                name=target.name or path))
    size = target.stat().st_size
    if size == 0:
        raise ValueError(i18n.t("error.fileEmpty"))
    if size > MAX_SIZE:
        raise ValueError(i18n.t("error.fileTooLarge",
                                size=size // 1024 // 1024))
    return target, size


def select_file(device_ids, path: str, version: str = "", *,
                set_no: int = 1) -> dict:
    """Assign the image to the given devices (kept in memory only)."""
    keys = [scope_key(set_no, device_id) for device_id in (device_ids or [])
            if str(device_id).strip()]
    if not keys:
        raise ValueError(i18n.t("error.noDeviceSelected"))
    target, size = validate_file(path)
    record = {"path": target, "size": size,
              "version": str(version or "").strip()[:32]}
    with _LOCK:
        for key in keys:
            _SELECTED[key] = dict(record)
    return selections([device_id for _number, device_id in keys],
                      set_no=set_no)


def set_target_version(device_ids, version: str, *,
                       set_no: int = 1) -> dict:
    """Change the selected image's target version without touching the file.

    The target version cannot be read from the file, the user types it — no
    reason to make them pick the file again.
    """
    cleaned = str(version or "").strip()[:32]
    keys = [scope_key(set_no, device_id) for device_id in (device_ids or [])
            if str(device_id).strip()]
    with _LOCK:
        for key in keys:
            if key in _SELECTED:
                _SELECTED[key]["version"] = cleaned
    return selections([device_id for _number, device_id in keys],
                      set_no=set_no)


def clear_selection(device_ids, *, set_no: int = 1) -> int:
    """Drop the given devices' selections; returns how many were removed."""
    keys = [scope_key(set_no, device_id) for device_id in (device_ids or [])
            if str(device_id).strip()]
    with _LOCK:
        return sum(1 for key in keys
                   if _SELECTED.pop(key, None) is not None)


def _dto(record: dict | None) -> dict:
    if not record:
        return {"selected": False, "name": "", "path": "", "size": 0,
                "version": ""}
    return {
        "selected": True,
        "name": record["path"].name,
        # The full path goes out too: the row shows the file name and the
        # tooltip says where it came from. On the desktop the data travels
        # only over the local pywebview bridge, and in browser diagnostic mode
        # only from 127.0.0.1; the path is the user's own choice.
        "path": str(record["path"]),
        "size": record["size"],
        "version": record["version"],
    }


def selections(device_ids=None, *, set_no: int = 1) -> dict:
    """{deviceId: record} — only the selections in the given set."""
    number, _ = scope_key(set_no, "_")
    with _LOCK:
        if device_ids is None:
            return {device_id: _dto(record)
                    for (set_number, device_id), record in _SELECTED.items()
                    if set_number == number}
        return {str(device_id): _dto(_SELECTED.get((number, str(device_id))))
                for device_id in device_ids}


def selection_for(device_id: str, *, set_no: int = 1) -> dict:
    key = scope_key(set_no, device_id)
    with _LOCK:
        return _dto(_SELECTED.get(key))


def take_selection(device_id: str, *, set_no: int = 1) -> dict | None:
    """The raw record (with the Path) for the installer."""
    key = scope_key(set_no, device_id)
    with _LOCK:
        return _SELECTED.get(key)


def has_selection(device_id: str, *, set_no: int = 1) -> bool:
    key = scope_key(set_no, device_id)
    with _LOCK:
        return key in _SELECTED


def clear_all(set_no: int | None = None) -> None:
    """Clear selections; without a set number, empty the whole store."""
    with _LOCK:
        if set_no is None:
            _SELECTED.clear()
            return
        number, _ = scope_key(set_no, "_")
        for key in [k for k in _SELECTED if k[0] == number]:
            _SELECTED.pop(key, None)
