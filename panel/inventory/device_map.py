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
from .catalog import category_for
from ..editions import catalogue
from . import profiles
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
    # What decides this device's configuration field set — the SubType for
    # most equipment, the Type for video. Settled here, with the read method,
    # because both are the PROJECT's answer (see inventory/profiles) and the
    # device is the only thing that travels afterwards.
    config_scope: str
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
                 source: Path, config: dict | None = None,
                 project_label: str | None = None):
        self.set_no = set_no
        self.devices = devices
        # TWO NAMES, ON PURPOSE. `project` is the file stem — ASCII, and what
        # `profiles.for_project` and `panel/video_config/nvr.py` match on.
        # `project_label` is the same project written the way it is said, and
        # is the only one of the two a person should ever be shown.
        self.project = project
        self.project_label = project_label or project
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

    # The prefixes a network is described with here — the octet boundaries,
    # and nothing between them. A project is laid out as "a /24" or "a /16",
    # never as "a /21", and reporting the tighter number would invent a
    # boundary nobody drew.
    OCTET_PREFIXES = (24, 16, 8)

    def span(self, *extra: str):
        """The network this project occupies, on an octet boundary.

        THE PROJECT'S REACH, computed rather than declared. A device has to be
        able to talk to everything in here — the other devices, the switches,
        and whatever `extra` names (the broker, which is a role and not a
        device) — so a device whose own mask does not cover this network
        cannot do its job, and that is a fault worth reporting.

        Computed instead of compared against a fixed mask, because no fixed
        mask is right for every project: Yatakli sits inside one /24 and
        Gaziray needs a /16, while the CCTV commissioning scripts write a /8
        to both. All three are correct — "wide enough" is the only question
        with one answer.

        WIDENED TO AN OCTET BOUNDARY, and that is the point of the constant
        above. The addresses themselves would give something tighter —
        Yatakli's run .1 to .101 and fit in a /25, Gaziray's fit in a /21 —
        but those are accidents of which addresses happen to be in use today,
        not decisions anybody made. Answering /25 would fail a camera set to
        the /24 the train is actually built on. Narrowing past /24 has to be
        SAID, and the place to say it is the DeviceMap (`subnetMask` is
        already a field it may carry, see panel/config_sync/fields.py); no map
        says it today.

        None when there is nothing to span, or when the addresses do not fit
        in a /8 at all — a project spread across unrelated ranges has no one
        network, and claiming one would be worse than saying nothing.
        """
        import ipaddress                                    # noqa: PLC0415

        numbers = []
        for address in [d.ip for d in self.devices] + list(extra):
            try:
                numbers.append(int(ipaddress.IPv4Address(str(address).strip())))
            except (ipaddress.AddressValueError, ValueError):
                continue          # a template that never resolved, or ""
        if not numbers:
            return None
        low, high = min(numbers), max(numbers)
        for length in self.OCTET_PREFIXES:                  # 24, then 16, then 8
            network = ipaddress.ip_network((low, length), strict=False)
            if ipaddress.IPv4Address(high) in network:
                return network
        return None

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
    # The project decides how its own equipment is talked to. Its key is the
    # map's file stem, which `tests/test_editions.py` holds equal to the
    # catalogue's `Project.key`; a map that belongs to no listed project — one
    # delivered on a service key — gets the shared rules.
    project = path.stem.replace("DeviceMap", "").strip("_- ") or "YATAKLI"
    # The stem is ASCII by the naming rule, and so is the fallback above,
    # so neither can spell a project name that is not. The name for the
    # screen is therefore asked of the catalogue, not read off the file.
    project_label = catalogue.label_for(project)
    profile = profiles.for_project(project)
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
            read_method=profile.read_method("Switch", None),
            config_scope=profile.config_scope("Switch", None),
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
                read_method=profile.read_method(device_type, subtype),
                config_scope=profile.config_scope(device_type, subtype),
                pbx_extension=dv.get("PBXExtension") or None,
                pbx_password=dv.get("PBXPassword") or None,
                extra=_without_secrets(dv),
            ))

    inventory = Inventory(
        int(set_no), devices, project=project,
        project_label=project_label,
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


def required_set(value) -> int:
    """Validate a required set number without silently choosing another set.

    Read-only screens use :func:`valid_set` so an absent query parameter can
    still open the default project.  A write operation cannot use that
    fallback: turning an invalid external-set entry into set 1 would direct the
    operation at a different train.  Accept JSON integers and digit-only form
    values, but reject booleans, fractions and missing values explicitly.
    """
    if isinstance(value, bool):
        raise ValueError(i18n.t("error.invalidSetNumber"))
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        number = int(value.strip())
    else:
        raise ValueError(i18n.t("error.invalidSetNumber"))
    if not (settings.SET_MIN <= number <= settings.SET_MAX):
        raise ValueError(i18n.t("error.invalidSetNumber"))
    return number


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
