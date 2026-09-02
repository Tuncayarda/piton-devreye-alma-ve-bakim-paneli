#!/usr/bin/env python3
"""This computer's network identity — which interface, which MAC.

An IP assignment run must not touch the switch port the computer is plugged
into: cutting that port's PoE cuts the run's own path. This module produces
half of what is needed to find that port from the switch's MAC table; the
other half is `panel.probe.switch.mac_table`.

It is also the read side of `panel.network`, which ADDS addresses to an
interface: what is already there decides what has to be added and to which
adapter. This module never writes.

Only the local interface name, its addresses and its MAC are read. No
credentials, no user data.

Why an OS command: the standard library does not expose interface MACs
(`uuid.getnode()` returns one possibly random value and does not say which
card it came from), and pulling in psutil for one field was too heavy.

Output is NOT parsed by label. `ipconfig /all` says "Fiziksel Adres" on a
Turkish Windows and "Physical Address" in English, so label matching means a
locale-dependent interface. Instead the output is split into per-interface
blocks and each block is searched for a MAC pattern and the address itself —
neither depends on language.
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys

from .spawn import NO_CONSOLE

# Both 00:11:22:33:44:55 and 00-11-22-33-44-55 (Windows).
_MAC_PATTERN = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")
_IPV4_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")

# Locally administered / meaningless MACs: they cannot produce a port match.
_EMPTY_MACS = {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"}

COMMAND_TIMEOUT = 4.0

# Command output is read as BYTES and decoded here; `text=True` is not used.
#
# `text=True` lets Python choose, and on Windows Python picks the ANSI code
# page (cp1254 on a Turkish install) while console tools write in the OEM one
# (cp857). The "ı" in the first line of `ipconfig /all` is 0x8d in cp857 and
# UNDEFINED in cp1254: UnicodeDecodeError. That is neither OSError nor
# SubprocessError, so it escaped the handler below and surfaced as a 500 —
# on Windows the computer's switch port was never found. Everything we search
# for is ASCII, so errors="replace" loses nothing here.
_CODE_PAGE = "oem" if sys.platform == "win32" else "utf-8"

# On a windowed (console-less) Windows build every command flashes a console
# window; CREATE_NO_WINDOW suppresses it. The one rule lives in
# `panel.system.spawn`; the local name is kept because the switch tests
# patch it to prove the flag reaches `subprocess.run`.
_NO_WINDOW = NO_CONSOLE


def decode(raw: bytes) -> str:
    """Decode command output; never raises on any code page."""
    try:
        return (raw or b"").decode(_CODE_PAGE, errors="replace")
    except LookupError:               # code page missing in this Python
        return (raw or b"").decode("latin-1", errors="replace")


def normalize_mac(value) -> str:
    """5c-1-3B-8A-76-43 / 5c01.3b8a.7643 -> 5c:01:3b:8a:76:43"""
    if not value:
        return ""
    hex_parts = re.findall(r"[0-9a-fA-F]{1,2}", str(value).replace(".", ""))
    if len(hex_parts) < 6:
        return ""
    return ":".join(h.rjust(2, "0").lower() for h in hex_parts[:6])


def local_address_for(target_ip: str) -> str:
    """The local address used when reaching `target_ip`.

    Binding a UDP socket sends no packet; it is the portable way to ask the
    kernel's routing table which interface leads to an address.
    """
    if not target_ip:
        return ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.connect((str(target_ip), 9))
            return sock.getsockname()[0]
    except OSError:
        return ""


def run_command(argv: list[str],
                timeout: float = COMMAND_TIMEOUT) -> tuple[int | None, str]:
    """Run a command; returns (exit code, decoded stdout + stderr).

    A code of `None` means the command never started (missing binary, timeout)
    — a different outcome from "it ran and failed", which `panel.network` has
    to tell apart before it reports an address as added.

    Output is decoded here rather than by `text=True`; see the code page note
    above.
    """
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout,
                                **_NO_WINDOW, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return int(result.returncode), decode(result.stdout) + decode(result.stderr)


def _run(argv: list[str]) -> str:
    return run_command(argv)[1]


def dump() -> str:
    """The platform's interface dump. First non-empty answer wins."""
    if sys.platform == "win32":
        candidates = [["ipconfig", "/all"]]
    else:
        # macOS only has ifconfig; on a Linux box without it the `ip` path
        # below takes over (`ip -o addr` alone carries no MAC, so it cannot be
        # used as a drop-in dump here).
        candidates = [["ifconfig", "-a"], ["ifconfig"]]
    for argv in candidates:
        text = _run(argv)
        if text.strip():
            return text
    return ""


def blocks(text: str) -> list[str]:
    """Split the dump into per-interface blocks.

    In all three formats a new interface starts on an unindented line:
      ifconfig : "en0: flags=8863<UP,...> mtu 1500"
      ip -o    : "2: eth0    inet 10.1.1.50/16 ..."  (one block per line)
      ipconfig : "Ethernet adapter Ethernet:"
    """
    found: list[list[str]] = []
    for line in text.splitlines():
        if line.strip() and not line[0].isspace():
            found.append([line])
        elif found:
            found[-1].append(line)
    return ["\n".join(block) for block in found]


def block_mac(block: str) -> str:
    for match in _MAC_PATTERN.findall(block):
        mac = normalize_mac(match)
        if mac and mac not in _EMPTY_MACS:
            return mac
    return ""


# Interface flags, not labels: `flags=8863<UP,BROADCAST,RUNNING,...>` on
# ifconfig, `<BROADCAST,MULTICAST,UP,LOWER_UP>` on `ip`. ASCII tokens in every
# locale — unlike "Media disconnected", which a localised Windows translates,
# and which is exactly the trap the module docstring above describes.
_FLAGS_PATTERN = re.compile(r"<([^>]*)>")


def block_up(block: str) -> bool | None:
    """Does this interface have a carrier? None when the dump does not say.

    RUNNING (ifconfig) and LOWER_UP (ip) both mean "a cable is in and the
    other end answers", which is the question that matters when picking the
    adapter to add an address to. Plain UP only means "administratively
    enabled" and is true of every unplugged port.
    """
    match = _FLAGS_PATTERN.search(block)
    if not match:
        return None
    flags = {flag.strip().upper() for flag in match.group(1).split(",")}
    return "RUNNING" in flags or "LOWER_UP" in flags


# `ip -o link` lines start "2: eth0: <FLAGS> mtu ...". A veth carries its peer
# after an @ ("eth0@if5"), which is not part of the device name.
_IP_LINK_PATTERN = re.compile(r"^\d+:\s*([^:@\s]+)")
_IP_ADDR_PATTERN = re.compile(r"^\d+:\s*(\S+)\s+inet\s+(\d{1,3}(?:\.\d{1,3}){3})")


def ip_interfaces() -> list[dict]:
    """The `ip` command's answer — two calls merged by device name.

    `ip -o addr` carries no MAC and `ip -o link` carries no address, so
    neither is usable alone; a Linux box without ifconfig (most current
    distributions) was left with no readable interface at all.
    """
    _code, links = run_command(["ip", "-o", "link"])
    if not links.strip():
        return []
    _code, addresses = run_command(["ip", "-o", "addr"])

    by_name: dict[str, list[str]] = {}
    for line in addresses.splitlines():
        match = _IP_ADDR_PATTERN.match(line.strip())
        if match:
            by_name.setdefault(match.group(1), []).append(match.group(2))

    found, seen = [], set()
    for line in links.splitlines():
        match = _IP_LINK_PATTERN.match(line.strip())
        if not match:
            continue
        name = match.group(1)
        mac = block_mac(line)
        if not mac or mac in seen:
            continue
        seen.add(mac)
        found.append({"name": name, "mac": mac,
                      "addresses": by_name.get(name, []),
                      "up": block_up(line)})
    return found


def list_interfaces() -> list[dict]:
    """[{"name", "mac", "addresses", "up"}] for every interface with a MAC.

    `up` is True/False when the dump reports a carrier and None when it does
    not (`ipconfig` says it only in the local language, so on Windows the
    answer is filled in later — see `panel.network.adapters`).

    Expected to be called once and held: each call runs an OS command, and
    doing that per switch while querying several is pointless.
    """
    found, seen = [], set()
    for block in blocks(dump()):
        mac = block_mac(block)
        if not mac or mac in seen:
            continue
        seen.add(mac)
        found.append({
            "name": block.splitlines()[0].split(":")[0].strip(),
            "mac": mac,
            "addresses": _IPV4_PATTERN.findall(block),
            "up": block_up(block),
        })
    if not found and sys.platform != "win32":
        return ip_interfaces()
    return found


def interface_toward(target_ip: str,
                     interfaces: list[dict] | None = None) -> dict:
    """The MAC of the interface that reaches `target_ip`.

    Pass `interfaces` to avoid re-reading the dump (see `list_interfaces`).

    Returns {"mac", "name", "localIp", "candidates"}. An empty `mac` means the
    interface could not be determined; `candidates` still carries every local
    MAC, so the switch's table can be searched for all of them and the port may
    still be found. Nothing is invented.
    """
    interfaces = list_interfaces() if interfaces is None else interfaces
    candidates = [i["mac"] for i in interfaces]
    address = local_address_for(target_ip)
    if address:
        # Exact match: searching by substring would let "10.1.1.5" match
        # "10.1.1.50".
        for entry in interfaces:
            if address in entry["addresses"]:
                return {"mac": entry["mac"], "name": entry["name"],
                        "localIp": address, "candidates": candidates}
    return {"mac": "", "name": "", "localIp": address,
            "candidates": candidates}
