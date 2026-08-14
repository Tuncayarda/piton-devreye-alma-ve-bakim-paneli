#!/usr/bin/env python3
"""DeviceMap.json — the topology inventory.

The device list has exactly one source: this file. An IP or device type sent
by the client is never used as a connection target; the client sends a device
id and the target is looked up here.

DeviceMap also carries Username/Password fields. Those are project definition
data: the panel does NOT use them as credentials and never puts them in an API
response. Credentials come from the user and stay in memory only (see
`panel.credentials`).
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .. import settings
from .catalog import category_for, read_method_for
from .. import i18n

# Present in DeviceMap, never handed out
SECRET_FIELDS = {"password", "pbxpassword", "username"}


def resolve_template(template: str, set_no) -> str:
    """Replace the standalone 'n' in an IP template with the set number.

    10.n.1.24, set 3 -> 10.3.1.24
    """
    return re.sub(r"(?<![0-9a-zA-Z])n(?![0-9a-zA-Z])", str(set_no),
                  template or "")


def to_template(ip: str, set_no) -> str:
    """Turn a resolved IP back into template form (10.3.1.24 -> 10.n.1.24)."""
    parts = str(ip or "").split(".")
    if len(parts) == 4 and parts[1] == str(set_no):
        parts[1] = "n"
        return ".".join(parts)
    return ip


@dataclass
class Device:
    """A device's fixed identity; live state is not kept here.

    `id` is derived from the position in DeviceMap and is independent of the
    set number. Two devices with the same name get different ids; matching is
    always done on id + ip + type + subtype.
    """

    id: str
    name: str
    ip_template: str
    ip: str
    type: str
    subtype: str | None
    switch_name: str
    switch_id: str
    port: str | None
    active: bool
    category: str
    read_method: str
    pbx_extension: str | None = None
    # SIP registration password from DeviceMap. The device's SIP endpoint
    # requires it when writing configuration. Absent from `dto()`: it never
    # reaches the UI and is unrelated to the credential the panel uses to
    # connect.
    pbx_password: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def match_key(self) -> tuple:
        """Matching key — the quadruple, not the name."""
        return (self.id, self.ip, self.type, self.subtype or "")

    def dto(self) -> dict:
        """UI-safe view. Contains no password or username."""
        return {
            "id": self.id,
            "name": self.name,
            "ip": self.ip,
            "ipTemplate": self.ip_template,
            "type": self.type,
            "subtype": self.subtype or "",
            "typeLabel": (f"{self.type} / {self.subtype}" if self.subtype
                          else self.type),
            "switch": self.switch_name,
            "switchId": self.switch_id,
            "port": self.port or "",
            "portLabel": (i18n.lazy("device.managementPort",
                                    switch=self.switch_name)
                          if self.type == "Switch"
                          else f"{self.switch_name} · p{self.port}"),
            "category": self.category,
            "readMethod": self.read_method,
            "pbxExtension": self.pbx_extension or "",
            "active": self.active,
        }


class Inventory:
    """The resolved device list for one train set."""

    def __init__(self, set_no: int, devices: list[Device], project: str,
                 source: Path, config: dict | None = None):
        self.set_no = set_no
        self.devices = devices
        self.project = project
        self.source = source
        self.config = config or {}
        self._by_id = {d.id: d for d in devices}

    def find(self, device_id: str) -> Device | None:
        """Look a device up by id — the only field the client can be trusted for."""
        return self._by_id.get(str(device_id))

    def by_type(self, device_type: str,
                subtype: str | None = None) -> list[Device]:
        return [d for d in self.devices
                if d.type == device_type
                and (subtype is None or (d.subtype or "") == subtype)]

    def switches(self) -> list[Device]:
        return [d for d in self.devices if d.type == "Switch"]

    def piscu_ip(self) -> str | None:
        found = self.by_type("PISCU")
        return found[0].ip if found else None

    def project_settings(self, device: Device) -> dict:
        """DeviceMap-defined settings for a device — {lowercasefield: value}.

        Three levels merge, later overriding earlier:
          1. Config["Announcement"]          — the whole type
          2. Config["Announcement/Handset"]  — the subtype
          3. the device's own record (PBXExtension and friends)

        So one volume can be set for every Handset at once, and a single
        device that differs gets it on its own record.
        """
        merged: dict = {}
        for key in (device.type, f"{device.type}/{device.subtype or ''}"):
            block = self.config.get(key.lower())
            if isinstance(block, dict):
                merged.update(block)
        merged.update({k.lower(): v for k, v in device.extra.items()})
        return merged

    def dto(self) -> list[dict]:
        return [d.dto() for d in self.devices]


# ─────────────────────────────────────────────────────────── loading ──────
_CACHE: dict[tuple, Inventory] = {}
_CACHE_LOCK = threading.Lock()


def _without_secrets(record: dict) -> dict:
    return {k: v for k, v in record.items()
            if k.lower() not in SECRET_FIELDS and k not in ("Devices", "Status")}


def _read_raw(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(i18n.t("error.deviceMapNotFound", path=path))
    return json.loads(path.read_text(encoding="utf-8"))


def _read_config(raw: dict) -> dict:
    """The top-level `Config` block, if present.

        "Config": {
          "Announcement":         {"LogLevel": 1},
          "Announcement/Handset": {"SpeakerVolume": 80, "AnswerMode": 1}
        }

    Settings written once per type go here; a device-specific value goes on
    the device's own record.
    """
    block = raw.get("Config")
    if not isinstance(block, dict):
        return {}
    out = {}
    for key, value in block.items():
        if isinstance(value, dict):
            out[str(key).lower()] = {
                k.lower(): v for k, v in value.items()
                if k.lower() not in SECRET_FIELDS}
    return out


def load(set_no: int, path: Path | None = None,
         cache: bool = True) -> Inventory:
    """Build the inventory for a train set.

    The cache refreshes itself when the file changes (mtime is in the key).
    """
    path = Path(path or settings.DEVICE_MAP)
    stamp = (str(path), int(set_no),
             path.stat().st_mtime_ns if path.exists() else 0)
    if cache:
        with _CACHE_LOCK:
            ready = _CACHE.get(stamp)
            if ready:
                return ready

    raw = _read_raw(path)
    devices: list[Device] = []
    for si, sw in enumerate(raw.get("Switches") or [], start=1):
        sw_id = f"sw{si}"
        sw_name = sw.get("Name") or f"Switch {si}"
        sw_template = sw.get("IP", "")
        devices.append(Device(
            id=sw_id, name=sw_name, ip_template=sw_template,
            ip=resolve_template(sw_template, set_no), type="Switch",
            subtype=None, switch_name=sw_name, switch_id=sw_id, port=None,
            active=bool(sw.get("IsActive", True)),
            category=category_for("Switch"),
            read_method=read_method_for("Switch", None),
            extra=_without_secrets(sw),
        ))
        for di, dv in enumerate(sw.get("Devices") or [], start=1):
            device_type = dv.get("Type", "")
            subtype = dv.get("SubType") or None
            template = dv.get("IP", "")
            devices.append(Device(
                id=f"{sw_id}.d{di}", name=dv.get("Name", ""),
                ip_template=template, ip=resolve_template(template, set_no),
                type=device_type, subtype=subtype, switch_name=sw_name,
                switch_id=sw_id,
                port=str(dv.get("Port")) if dv.get("Port") is not None else None,
                active=bool(dv.get("IsActive", True)),
                category=category_for(device_type),
                read_method=read_method_for(device_type, subtype),
                pbx_extension=dv.get("PBXExtension") or None,
                pbx_password=dv.get("PBXPassword") or None,
                extra=_without_secrets(dv),
            ))

    inventory = Inventory(
        int(set_no), devices,
        project=path.stem.replace("DeviceMap", "").strip("_- ") or "YATAKLI",
        source=path, config=_read_config(raw))
    if cache:
        with _CACHE_LOCK:
            _CACHE[stamp] = inventory
    return inventory


def valid_set(value, default: int = 1) -> int:
    """Validate a set number from the client.

    The n in the template feeds the second octet directly; unvalidated, a
    client could make the panel connect to any network it likes.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if not (settings.SET_MIN <= number <= settings.SET_MAX):
        return default
    return number


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
