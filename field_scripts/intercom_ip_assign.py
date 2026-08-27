#!/usr/bin/env python3
"""Automatic intercom IP assignment.

Intercoms arrive on the same factory IP wired to switch ports. Enabling PoE
ports one at a time, each device is given the IP DeviceMap assigns to its port.

Flow (per target port):
  1. Turn OFF every PoE port in range, turn ON only the target port
  2. Wait for boot, look for /api/v1/system/settings on candidate IPs
  3. If the device sits on the wrong IP, write the right one
  4. The device (ESP32) resets — wait for it on the target IP
  5. Move to the next port
Afterwards every port in range is turned back on.

Besides the human-readable log the script prints machine-readable progress
events (see `emit_event`). Those events, not the prose, are the contract with
the panel — see panel/ip_assign/progress.py.

Usage:
    python3 intercom_ip_assign.py --ports 11 12 13 14
    python3 intercom_ip_assign.py --ports 11-14 --default-ip 10.1.1.12
    python3 intercom_ip_assign.py --ports 11-22 -n 2 --dry-run
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HERE = Path(__file__).resolve().parent

POE_ON, POE_OFF = "1", "0"

# ───────────────────────────────────────────────── progress event protocol ──
# Every line starting with this prefix is one JSON object describing what the
# run just did. The panel reads ONLY these lines to build queue rows, phases
# and the percentage; the surrounding prose is for the operator and the log.
#
# Prose used to be the contract, which meant a reworded sentence silently
# broke the panel's progress bar. Keep the event names and field names below
# stable, and change the prose freely.
EVENT_PREFIX = "@EVT "

# Phase identifiers (must match panel/ip_assign/progress.py PHASES).
PHASE_BASELINE = "baseline"
PHASE_RESTORE = "restore"
PHASE_VERIFY = "verify"

# Step identifiers within one port (must match PORT_STEPS in the panel).
STEP_POE_ON = "poe_on"
STEP_SEARCHING = "searching"
STEP_DEVICE_FOUND = "device_found"
STEP_FIRMWARE = "firmware"
STEP_WRITING_IP = "writing_ip"
STEP_VERIFYING = "verifying"

# ─────────────────────────────────────────────────────── extension point ────
# Called once a device has been found on a port and verified to be on it, and
# BEFORE its IP is written. Left as None here: run standalone, this script
# does exactly what it always did.
#
# It exists for one field problem. Some intercoms shipped long ago are on
# firmware old enough that they report their version and identity wrongly, and
# they have to be flashed before anything else is done to them. The only
# moment that is possible is this one: the run has just brought up a single
# port, so exactly one device is reachable and it is still on the factory
# address. Afterwards it has moved to its own address and is one of many.
#
# The panel installs a callable here before calling main() and clears it
# afterwards (see panel/ip_assign/runner.py and preflash.py). Contract:
#
#     BEFORE_WRITE(port, ip, settings, cfg) -> (ok, note)
#
# `ok` False fails the port and the IP is NOT written — a device that could
# not be flashed is a device that must not be quietly moved on to. `note` is a
# sentence for the operator, printed either way. The callback must not raise:
# whatever it does is its own to report.
BEFORE_WRITE = None


def emit_event(event: str, **fields) -> None:
    """Print one machine-readable progress event.

    Written as a single line so a line-buffered reader never sees half an
    event, and with sorted keys so the output is stable across runs.
    """
    payload = {"event": event}
    payload.update(fields)
    print(EVENT_PREFIX + json.dumps(payload, ensure_ascii=False,
                                    sort_keys=True))


# --------------------------------------------------------------- helpers --
def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def resolve(template: str, set_no) -> str:
    return re.sub(r"(?<![0-9a-zA-Z])n(?![0-9a-zA-Z])", str(set_no),
                  template or "")


def parse_ports(values: list[str]) -> list[int]:
    """['11','12'] or ['11-14'] -> [11, 12, 13, 14]"""
    ports = []
    for value in values:
        if "-" in value:
            first, last = value.split("-", 1)
            ports.extend(range(int(first), int(last) + 1))
        else:
            ports.append(int(value))
    return sorted(set(ports))


# ------------------------------------------------------------ switch PoE ---
POE_READ_ENDPOINTS = ["stat/poeStatus", "stat/poePort", "stat/portList"]


def switch_request(cfg, method: str, endpoint: str, **kw):
    """Send a switch request, retrying on transient failures.

    KYLAND's web server can stop answering for a few seconds while PoE is
    switching; one blip must not fail the whole run.
    """
    url = f"http://{cfg.switch_ip}:{cfg.kyland_port}/{endpoint}"
    last = None
    for attempt in range(cfg.switch_retries + 1):
        try:
            r = requests.request(method, url,
                                 auth=HTTPBasicAuth(cfg.kyland_user,
                                                    cfg.kyland_pass),
                                 timeout=cfg.timeout, **kw)
            # 4xx is permanent (no endpoint / no permission) — no point retrying
            if 400 <= r.status_code < 500:
                r.raise_for_status()
            r.raise_for_status()
            return r
        except requests.HTTPError as exc:
            if (exc.response is not None
                    and 400 <= exc.response.status_code < 500):
                raise                        # give up without waiting
            last = exc
        except requests.RequestException as exc:
            last = exc
        if attempt < cfg.switch_retries:
            wait = cfg.switch_retry_wait * (attempt + 1)
            print(f"    (switch did not answer, retrying in {wait:.0f} s "
                  f"— {type(last).__name__})")
            time.sleep(wait)
    raise last


MAC_ENDPOINTS = ["stat/macQuery", "stat/macAddress", "stat/fdb"]


def norm_mac(value) -> str | None:
    """5c-1-3b-8A-76-43 / 5c01.3b8a.7643 -> 5c:01:3b:8a:76:43"""
    if not value:
        return None
    hexes = re.findall(r"[0-9a-fA-F]{1,2}", str(value).replace(".", ""))
    if len(hexes) < 6:
        return None
    return ":".join(h.rjust(2, "0").lower() for h in hexes[:6])


WINDOWS = sys.platform == "win32"

# Console tools write in the OEM code page on Windows (cp857 on a Turkish
# install), not the ANSI one Python picks with `text=True` (cp1254). The byte
# for "ı" is undefined in cp1254, and UnicodeDecodeError is neither OSError
# nor SubprocessError — the handlers below missed it and the run died.
# Everything searched for is ASCII, so errors="replace" loses nothing.
_CODE_PAGE = "oem" if WINDOWS else "utf-8"
# On a console-less Windows build every command flashed a console window.
_NO_WINDOW = {"creationflags": 0x08000000} if WINDOWS else {}   # NO_WINDOW


def _decode(raw) -> str:
    try:
        return (raw or b"").decode(_CODE_PAGE, errors="replace")
    except LookupError:               # code page missing in this Python
        return (raw or b"").decode("latin-1", errors="replace")


def command_output(cmd, timeout: float = 3.0):
    """Run a command, return (returncode, stdout+stderr).

    Output is captured as bytes and decoded here, so no code page raises.
    Returns (None, "") if the command could not be run.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                **_NO_WINDOW, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return result.returncode, _decode(result.stdout) + _decode(result.stderr)


# Both "5c:01:3b:..." (POSIX) and "5c-01-3b-..." (Windows arp).
_MAC_PATTERN = re.compile(r"(?:[0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2}")


def host_mac(ip: str) -> str | None:
    """Read an IP's MAC from the OS ARP table.

    The entry is fresh because HTTP was just spoken to the device.

    Windows differs in both command and output: there is no `arp -n` (only
    `-a`) and MACs use dashes. Missing both, this returned None forever there
    and MAC-based port verification silently never ran.
    """
    commands = ([["arp", "-a", ip]] if WINDOWS
                else [["arp", "-n", ip], ["ip", "neigh", "show", ip]])
    for cmd in commands:
        _code, out = command_output(cmd)
        match = _MAC_PATTERN.search(out)
        if match:
            return norm_mac(match.group(0))
    return None


# ─────────────────────────────────────────────────────────── ARP cache ────
# Every intercom arrives on the same factory address (10.n.1.12) with its own
# MAC. Once one is given an IP and the next port opens, the OS ARP table still
# maps that address to the PREVIOUS device's MAC:
#
#     ARP table   10.1.1.12 -> 5c:01:3b:53:a4:73   (already moved to .13)
#     reality     10.1.1.12 -> 5c:01:3b:53:65:ff
#
# The HTTP probe goes to the stale MAC, gets nothing, and the device counts as
# "not found". On macOS the entry lives 20 minutes — this is why runs dragged
# on and why arp-scan saw devices the script could not. host_mac() reads the
# same stale entry, so MAC verification reports the wrong port too.
#
# Deleting the entry makes the kernel re-ARP and learn the right MAC.
_ARP_WARNING_SHOWN = False


def is_admin() -> bool:
    """Are we running elevated (Administrator) on Windows?"""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def arp_permission_hint() -> str:
    """What the user should do when permission is missing, per platform."""
    if WINDOWS:
        return ("right-click the application and start it with "
                "\"Run as administrator\"")
    return "run once in a terminal: sudo -v    (or start the app with sudo)"


def can_flush_arp() -> bool:
    """May we delete ARP entries?

    Permission is checked directly; judging by a delete attempt's output
    misleads — an address with no entry says "cannot locate" even without
    permission, which read as "the mechanism works".

    This used to return False unconditionally on Windows: `os.geteuid` does
    not exist there, the AttributeError was caught and treated as "no
    permission". So even run as Administrator the ARP cache was never
    flushed, and the user was told to run `sudo -v`, which Windows has no
    such thing as. The equivalent there is an elevated process: `arp -d`
    needs Administrator.
    """
    if WINDOWS:
        return is_admin()
    try:
        if os.geteuid() == 0:
            return True
    except AttributeError:                 # platform without geteuid
        return False
    try:
        # -n never prompts for a password; returns 0 if the timestamp is fresh.
        return subprocess.run(["sudo", "-n", "true"], capture_output=True,
                              timeout=5, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def arp_forget(ips, cfg=None) -> bool:
    """Delete the given addresses from the ARP cache. Returns whether it could.

    Deleting means writing to the routing socket, so it needs root. If the app
    is not root, `sudo -n` is tried: it works when the user ran `sudo -v` once
    before the run, and each success refreshes sudo's timestamp, which is
    enough for the whole run.
    """
    global _ARP_WARNING_SHOWN
    if cfg is not None and not getattr(cfg, "arp_flush", True):
        return False
    if not can_flush_arp():
        if not _ARP_WARNING_SHOWN:
            _ARP_WARNING_SHOWN = True
            required = "Administrator" if WINDOWS else "root"
            print(f"[!] Cannot flush the ARP cache ({required} required). "
                  "Devices sharing the factory address")
            print("    are addressed by their old MAC, so they fail with "
                  "'device not found'. Before the run,")
            print(f"    {arp_permission_hint()}")
        return False
    for ip in ips:
        for cmd in _arp_delete_commands(ip):
            code, output = command_output(cmd, timeout=5)
            if code is None:
                continue
            # "cannot locate" / "no entry" = there was nothing to delete.
            # Text matching is locale dependent (Turkish Windows differs); if
            # it misses, the next command is simply tried too — harmless.
            if (code == 0 or "no entry" in output
                    or "cannot locate" in output):
                break
    return True


def _arp_delete_commands(ip: str) -> list[list[str]]:
    """Platform-specific ways to drop one address's ARP entry.

    Windows has no `ip neigh` and no `sudo`; `arp -d` works in an elevated
    process. `netsh` is the fallback: on some builds `arp -d` only sees the
    legacy ARP table, not the neighbour cache.
    """
    if WINDOWS:
        return [["arp", "-d", ip],
                ["netsh", "interface", "ipv4", "delete", "neighbors",
                 f"address={ip}"]]
    if os.geteuid() == 0:
        return [["arp", "-d", ip], ["ip", "neigh", "flush", "to", ip]]
    return [["sudo", "-n", "arp", "-d", ip],
            ["sudo", "-n", "ip", "neigh", "flush", "to", ip]]


def _mac_rows(data) -> list[dict]:
    if isinstance(data, dict):
        for value in data.values():
            if (isinstance(value, list) and value
                    and isinstance(value[0], dict)
                    and any("mac" in k.lower() for k in value[0])):
                return value
    return []


_MAC_CACHE = {"endpoint": None, "table": {}, "at": 0.0, "dead": False}


def _find_port(obj):
    """Find the port number in a record, including nested structures.

    KYLAND can return {"mac": "...", "portList": [{"pid": 11}]}; looking for
    'pid' at the top level is not enough.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            lowered = key.lower()
            if lowered in ("pid", "port", "portid", "portno", "pname"):
                digits = re.sub(r"\D", "", str(value))
                if digits:
                    return int(digits)
        for value in obj.values():
            if isinstance(value, (dict, list)):
                found = _find_port(value)
                if found is not None:
                    return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_port(item)
            if found is not None:
                return found
    return None


def _parse_mac_table(data) -> dict:
    table = {}
    for row in _mac_rows(data):
        mac = norm_mac(next((v for k, v in row.items()
                             if "mac" in k.lower()
                             and not isinstance(v, (dict, list))), None))
        port = _find_port(row)
        if mac and port is not None:
            table[mac] = port
    return table


def switch_mac_table(cfg) -> dict:
    """The switch's MAC table: {mac: port}.

    The working endpoint is discovered once and remembered; the table is
    short-lived because PoE keeps changing (mac_cache_ttl). If no endpoint
    works, it is not retried.
    """
    if _MAC_CACHE["dead"]:
        return {}
    if (_MAC_CACHE["table"]
            and time.monotonic() - _MAC_CACHE["at"] < cfg.mac_cache_ttl):
        return _MAC_CACHE["table"]

    endpoints = ([_MAC_CACHE["endpoint"]] if _MAC_CACHE["endpoint"]
                 else [cfg.mac_endpoint] if cfg.mac_endpoint else MAC_ENDPOINTS)
    for endpoint in endpoints:
        try:
            table = _parse_mac_table(
                switch_request(cfg, "GET", endpoint).json())
        except Exception:
            continue
        if table:
            if _MAC_CACHE["endpoint"] != endpoint:
                print(f"    MAC table: {endpoint} ({len(table)} entries)")
            _MAC_CACHE.update(endpoint=endpoint, table=table,
                              at=time.monotonic())
            return table

    _MAC_CACHE["dead"] = True
    print("    [!] Could not read the switch MAC table "
          f"({', '.join(endpoints)}) — MAC verification disabled, "
          "falling back to the uptime method")
    return {}


def verify_port(ip: str, expected_port: int, cfg) -> tuple[bool | None, str]:
    """Is the device on this IP really on the expected port?

    Returns: (True verified / False wrong port / None unverifiable, reason)
    Facts, not guesses: host ARP -> MAC, switch MAC table -> port.
    """
    if not cfg.verify_mac:
        return None, "MAC verification disabled"
    mac = host_mac(ip)
    if not mac:
        return None, "no MAC in ARP"
    table = switch_mac_table(cfg)
    if not table:
        return None, "switch MAC table unreadable"
    port = table.get(mac)
    if port is None:
        return None, f"MAC {mac} not in the table"
    return port == expected_port, f"MAC {mac} -> port {port}"


def port_link(cfg, port: int):
    """Is the port's link up per the switch? True/False/None (unreadable).

    Switch-side proof that the device really has power and has brought the
    line up. Checking this before probing over HTTP removes the time spent
    looking for a device that has not booted yet.
    """
    try:
        response = switch_request(cfg, "GET", "stat/portMode")
        rows = response.json().get("portMode", [])
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("pid")) == str(port):
            return str(row.get("linkStat", "")).lower() == "up"
    return None


def wait_for_link(cfg, port: int, timeout: float):
    """Wait until the port link comes up. Returns (state, elapsed seconds).

    state True  — linked
          False — did not link within the timeout
          None  — the switch does not report link state (fall back)

    On the run's first port the link may already be up: that port was never
    closed and the device never rebooted. The elapsed time (~0 s) shows it and
    the caller prints the difference.
    """
    started = time.monotonic()
    initial = port_link(cfg, port)
    if initial is None:
        return None, 0.0
    if initial is True:
        return True, 0.0
    while True:
        if port_link(cfg, port):
            return True, time.monotonic() - started
        if time.monotonic() - started >= timeout:
            return False, time.monotonic() - started
        time.sleep(cfg.poll_interval)


def _poe_rows(data) -> list[dict]:
    """Find the list of records carrying a 'pid' inside the response."""
    if isinstance(data, dict):
        for value in data.values():
            if (isinstance(value, list) and value
                    and isinstance(value[0], dict) and "pid" in value[0]):
                return value
    return []


def poe_read(cfg) -> list[dict]:
    """Read current PoE port states from the switch.

    Read and write endpoints differ: writes go to POST /stat/poePort, reads to
    /stat/poeStatus. It varies by firmware, so they are tried in turn and the
    body is inspected rather than retCode.
    """
    errors = []
    for endpoint in ([cfg.poe_read_endpoint] if cfg.poe_read_endpoint
                     else POE_READ_ENDPOINTS):
        try:
            data = switch_request(cfg, "GET", endpoint).json()
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}")
            continue

        rows = _poe_rows(data)
        if rows:
            if cfg.verbose:
                print(f"    PoE state read from the {endpoint} endpoint "
                      f"({len(rows)} ports)")
            return [{"pid": int(x["pid"]),
                     "poeMode": str(x.get("poeMode", x.get("mode", POE_ON))),
                     "priority": str(x.get("priority", "0")),
                     "maxPower": str(x.get("maxPower", "154"))} for x in rows]
        errors.append(f"{endpoint}: retCode={data.get('retCode')!r}, "
                      f"keys={list(data)[:6]}")

    raise RuntimeError("could not read the PoE state -> " + " | ".join(errors))


def poe_apply(cfg, ports_state: list[dict], enabled_in_range: set[int],
              managed: set[int]) -> None:
    """Write the PoE state.

    Within the managed range only enabled_in_range stays on; ports outside the
    range keep their current settings.
    """
    fields = []
    for row in ports_state:
        pid = int(row["pid"])
        if pid in managed:
            mode = POE_ON if pid in enabled_in_range else POE_OFF
        else:
            mode = str(row.get("poeMode", POE_ON))
        fields.append(f"mode_{pid}={mode}"
                      f"&priority_{pid}={row.get('priority', '0')}"
                      f"&maxPower_{pid}={row.get('maxPower', '154')}")
    payload = "&".join(fields)

    if cfg.dry_run:
        states = {pid: (POE_ON if pid in enabled_in_range else POE_OFF)
                  for pid in sorted(managed)}
        print(f"    [dry-run] PoE: {states}")
        return

    response = switch_request(
        cfg, "POST", "stat/poePort",
        headers={"Content-Type":
                 "application/x-www-form-urlencoded; charset=UTF-8",
                 "X-Requested-With": "XMLHttpRequest"},
        data=payload)
    ret = response.json().get("retCode")
    if ret not in (["success"], "success"):
        raise RuntimeError(f"poePort write failed: {ret}")


# ------------------------------------------------------------- intercom ----
def read_settings(ip: str, cfg) -> dict | None:
    """Return the device's settings if it is up, else None."""
    try:
        response = requests.get(
            f"http://{ip}:{cfg.arduino_port}/api/v1/system/settings",
            timeout=cfg.probe_timeout)
        if response.ok:
            return response.json()
    except requests.RequestException:
        pass
    return None


def probe_all(candidates: list[str], cfg) -> dict:
    """Return the candidates that answered, {ip: settings} — in parallel."""
    candidates = list(candidates)
    if not candidates:
        return {}
    with cf.ThreadPoolExecutor(max_workers=min(len(candidates), 32)) as pool:
        results = pool.map(lambda ip: (ip, read_settings(ip, cfg)), candidates)
    return {ip: s for ip, s in results if s is not None}


def uptime_of(settings: dict):
    for key in ("uptime", "uptimeSeconds", "upTime"):
        if key in settings:
            try:
                return float(settings[key])
            except (TypeError, ValueError):
                return None
    return None


def find_device(candidates: list[str], cfg, deadline: float,
                baseline: dict | None = None):
    """Find the device whose port was just powered on.

    How they are told apart:
      1. UPTIME — the port just opened, so our device's uptime is small. With
         several answers the smallest uptime wins, which also picks correctly
         when two devices share one IP.
      2. Not in the baseline — the fallback when uptime is unavailable.

    Baseline = whoever answered while the range's ports were off; those sit on
    unmanaged ports and must not be touched.
    """
    baseline = baseline or {}
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        found = probe_all(candidates, cfg)
        if len(found) > 1:
            print(f"    [!] {len(found)} devices answered: "
                  f"{', '.join(found)} — the most recently booted wins")

        # A device on the factory IP is definitely an unconfigured intercom;
        # it wins. Then the smallest uptime.
        factory = getattr(cfg, "factory_ip", None)
        fresh = [(0 if ip == factory else 1, uptime_of(s), ip, s)
                 for ip, s in found.items()
                 if uptime_of(s) is not None
                 and uptime_of(s) <= cfg.fresh_uptime]
        if fresh:
            fresh.sort(key=lambda x: (x[0], x[1]))
            _, _, ip, settings = fresh[0]
            if ip == factory:
                print("    (factory IP — unconfigured device)")
            return ip, settings

        # Even without uptime the factory IP is a strong signal
        if factory in found and factory not in baseline:
            print("    (factory IP — unconfigured device)")
            return factory, found[factory]

        for ip, settings in found.items():          # no uptime -> baseline
            if ip not in baseline:
                return ip, settings

        time.sleep(cfg.poll_interval)
    return None, None


def wait_gone(ips, cfg, deadline: float) -> list[str]:
    """Wait until the given IPs go quiet; return the ones still answering.

    After an IP is written the device resets and its uptime restarts. Moving
    to the next port while it is still up would make it look like the
    "freshest device" and get overwritten. So silence is confirmed first.
    """
    ips = list(ips)
    if not ips:
        return []
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        still = [ip for ip in ips if read_settings(ip, cfg) is not None]
        if not still:
            return []
        time.sleep(cfg.poll_interval)
    return [ip for ip in ips if read_settings(ip, cfg) is not None]


def wait_until_quiet(candidates: list[str], cfg, deadline: float) -> dict:
    """Wait for devices to actually go quiet after the ports are closed.

    A device can keep answering for seconds after PoE is cut; a baseline read
    immediately would be wrong and that IP's device would end up on the "do
    not touch" list and be skipped. Wait until the answer count settles.
    """
    end = time.monotonic() + deadline
    last, stable = None, 0
    while time.monotonic() < end:
        now = probe_all(candidates, cfg)
        keys = set(now)
        if keys == last:
            stable += 1
            if stable >= 2:              # unchanged twice -> settled
                return now
        else:
            stable = 0
        last = keys
        time.sleep(cfg.poll_interval)
    return probe_all(candidates, cfg)


def write_ip(ip: str, settings: dict, new_ip: str, cfg) -> None:
    """Write a new IP — verified endpoint: POST /api/v1/network/ip

    The body is the full network block; everything but the IP is preserved
    from the device's current settings (netmask / gateway / ntpIp / useDhcp).
    After the write the device may reboot and the connection may drop.

    The netmask normally follows the device: whatever it already reports is
    sent back unchanged, and --netmask only fills the gap when it reports
    none. --force-netmask reverses that, because then the mask is not a
    fallback but the thing the operator asked to change.
    """
    # The device's own web UI sends only these three fields. Extra fields can
    # make the firmware reject the write silently.
    forced = getattr(cfg, "force_netmask", False)
    payload = {
        "ip":      new_ip,
        "netmask": (cfg.netmask if forced
                    else (settings.get("netmask") or cfg.netmask)),
        "gateway": settings.get("gateway") or cfg.gateway or "",
    }
    if cfg.full_net_payload:
        payload["useDhcp"] = bool(settings.get("useDhcp")
                                  or settings.get("usedhcp") or False)
        payload["ntpIp"] = (settings.get("ntpIp") or settings.get("ntpip")
                            or cfg.ntp_ip or "")
    if cfg.dry_run:
        print(f"    [dry-run] {ip} -> POST /{cfg.write_endpoint}: {payload}")
        return
    response = requests.post(
        f"http://{ip}:{cfg.arduino_port}/{cfg.write_endpoint}",
        json=payload, headers={"Content-Type": "application/json"},
        timeout=cfg.timeout)
    response.raise_for_status()

    # HTTP 200 alone is not enough; the body may report an error
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        blob = json.dumps(body).lower()
        if any(word in blob for word in ("error", "fail", "invalid", "reject")):
            raise RuntimeError(f"the device rejected the write: {body}")


# ---------------------------------------------------------------- flow --
def parse_args(env):
    parser = argparse.ArgumentParser(
        description="Automatic intercom IP assignment "
                    "(opening PoE ports one at a time)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--ports", nargs="+", required=True, metavar="P",
                        help="target port(s): '11 12 13 14' or '11-14'")
    parser.add_argument("-n", "--set", dest="set_no",
                        default=env.get("TRAIN_SET_NO", "1"),
                        help="set number — the 'n' in the IP template")
    parser.add_argument("--device-map", type=Path,
                        default=Path(env.get("DEVICE_MAP_FILE")
                                     or HERE / "DeviceMap.json"))
    parser.add_argument("--switch-ip", default=None,
                        help="switch IP (default: the switch these ports are "
                             "attached to in DeviceMap)")
    parser.add_argument("--factory-ip",
                        default=env.get("INTERCOM_FACTORY_IP", "10.n.1.12"),
                        help="the IP intercoms are expected on out of the "
                             "factory. 'n' is resolved with the set number; a "
                             "fixed address may be given instead. A device "
                             "answering here counts as an unconfigured "
                             "intercom.")
    parser.add_argument("--default-ip", nargs="+", default=[], metavar="IP",
                        help="extra candidate IPs. The factory IP and every "
                             "Intercom address in DeviceMap are already "
                             "candidates.")
    parser.add_argument("--fresh-uptime", type=float, default=180.0,
                        help="when two devices share an IP, the one with an "
                             "uptime below this counts as 'just booted' (s)")
    parser.add_argument("--max-passes", type=int, default=0,
                        help="how many passes at most (0 = unlimited, until "
                             "everything is done)")
    parser.add_argument("--stall-limit", type=int, default=2,
                        help="stop after this many consecutive passes with no "
                             "progress")
    parser.add_argument("--retry-backoff", type=float, default=1.5,
                        help="multiplier applied to the waits on every pass "
                             "without progress (1.0 = no increase)")
    parser.add_argument("--kyland-port", type=int,
                        default=int(env.get("KYLAND_HTTP_PORT", 80)))
    parser.add_argument("--kyland-user",
                        default=env.get("KYLAND_USERNAME", "admin"))
    parser.add_argument("--kyland-pass", default=env.get("KYLAND_PASSWORD", ""))
    parser.add_argument("--arduino-port", type=int,
                        default=int(env.get("ARDUINO_HTTP_PORT", 80)))
    parser.add_argument("--write-endpoint", default="api/v1/network/ip",
                        help="endpoint the network settings are written to")
    parser.add_argument("--netmask",
                        default=env.get("EXPECTED_SUBNET_MASK", "255.255.0.0"),
                        help="netmask to use when the device does not report one")
    parser.add_argument("--force-netmask", action="store_true",
                        help="write --netmask even when the device reports "
                             "one of its own (the operator asked for this "
                             "mask, so keeping the device's would ignore it)")
    parser.add_argument("--gateway", default=None,
                        help="gateway when the device does not report one "
                             "(default: the switch IP)")
    parser.add_argument("--ntp-ip", default=None,
                        help="NTP IP when the device does not report one "
                             "(default: PISCU)")
    parser.add_argument("--backup-dir", type=Path, default=None,
                        help="back up every device's settings here before "
                             "writing")
    # An ESP32 boots in ~10 s at most. The values below are UPPER BOUNDS; the
    # run continues as soon as the device answers. For a slow device
    # --retry-backoff already stretches them 1.5x on every stalled pass.
    parser.add_argument("--link-wait", type=float, default=25.0,
                        help="how long to wait for the switch link to come up "
                             "after the port is opened (s). The device is not "
                             "searched for until the link is up.")
    parser.add_argument("--find-wait", type=float, default=10.0,
                        help="how long to search for the device AFTER the link "
                             "is up (s)")
    parser.add_argument("--boot-wait", type=float, default=15.0,
                        help="how long to search for the device when the link "
                             "state is unreadable (s) — an ESP32 boots in ~10 s")
    parser.add_argument("--confirm-wait", type=float, default=30.0,
                        help="verification window after the IP is written "
                             "(reset) (s) — reset + boot is ~10 s")
    parser.add_argument("--settle", type=float, default=2.0,
                        help="wait after a PoE change (s)")
    parser.add_argument("--baseline-wait", type=float, default=12.0,
                        help="how long to wait for devices to go quiet after "
                             "the ports are closed (s)")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--probe-timeout", type=float, default=1.5,
                        help="timeout of a single IP probe (s)")
    parser.add_argument("--timeout", type=float, default=8.0,
                        help="timeout of switch/write requests (s)")
    parser.add_argument("--switch-retries", type=int, default=3,
                        help="how many retries when the switch does not answer")
    parser.add_argument("--switch-retry-wait", type=float, default=5.0,
                        help="wait between switch retries (s, grows)")
    parser.add_argument("--no-verify-mac", dest="verify_mac",
                        action="store_false",
                        help="turn off MAC-based port verification (fall back "
                             "to the uptime guess)")
    parser.add_argument("--mac-endpoint", default=None,
                        help=f"switch MAC table endpoint "
                             f"(tried: {', '.join(MAC_ENDPOINTS)})")
    parser.add_argument("--mac-cache-ttl", type=float, default=4.0,
                        help="how long the MAC table stays cached (s)")
    parser.add_argument("--no-defer-verify", dest="defer_verify",
                        action="store_false",
                        help="wait for the post-reset verification on every "
                             "port (default: verification is deferred to the "
                             "end)")
    parser.add_argument("--post-write-wait", type=float, default=2.0,
                        help="delay before waiting for the reset after the IP "
                             "is written")
    parser.add_argument("--reset-wait", type=float, default=15.0,
                        help="how long to wait for the device to drop off its "
                             "old IP after the write (proof of the reset)")
    parser.add_argument("--full-net-payload", action="store_true",
                        help="also send useDhcp and ntpIp in the network write "
                             "(default: same as the web UI — ip/netmask/gateway)")
    parser.add_argument("--no-persist-check", dest="persist_check",
                        action="store_false",
                        help="skip the final power cycle that proves the "
                             "settings are persistent")
    parser.add_argument("--no-arp-flush", dest="arp_flush", action="store_false",
                        help="do not flush the ARP cache before probing. The "
                             "flush is essential for devices sharing the "
                             "factory address: without it the old MAC is "
                             "addressed and the device is not found.")
    parser.add_argument("--poe-read-endpoint", default=None,
                        help=f"endpoint the PoE state is read from "
                             f"(tried: {', '.join(POE_READ_ENDPOINTS)})")
    parser.add_argument("--switch-port-count", type=int, default=None,
                        help="fallback port count when the read never works "
                             "(e.g. 24)")
    parser.add_argument("--dry-run", action="store_true",
                        help="write nothing; show the plan and the steps")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    env = load_env(HERE / ".env")
    cfg = parse_args(env)
    set_no = cfg.set_no
    ports = parse_ports(cfg.ports)

    device_map = json.loads(cfg.device_map.read_text(encoding="utf-8"))

    # Port -> target IP mapping (Intercom records only)
    plan: dict[int, dict] = {}
    switch_template = None
    for switch in device_map.get("Switches", []):
        for device in switch.get("Devices", []):
            if device.get("SubType") != "Intercom":
                continue
            try:
                port = int(str(device.get("Port")).strip())
            except (TypeError, ValueError):
                continue
            if port in ports:
                plan[port] = {"name": device.get("Name", ""),
                              "target": resolve(device.get("IP", ""), set_no)}
                switch_template = switch.get("IP", "")

    missing = [p for p in ports if p not in plan]
    if missing:
        print(f"[ERROR] No Intercom is defined in DeviceMap on these ports: "
              f"{missing}")
        print("        This script works with Intercom ports only for now.")
        return 1

    cfg.switch_ip = cfg.switch_ip or resolve(switch_template, set_no)
    cfg.gateway = cfg.gateway or cfg.switch_ip
    if not cfg.ntp_ip:
        for switch in device_map.get("Switches", []):
            for device in switch.get("Devices", []):
                if device.get("Type") == "PISCU":
                    cfg.ntp_ip = resolve(device.get("IP", ""), set_no)
    targets = [plan[p]["target"] for p in ports]
    # Candidate IPs: targets + EVERY intercom address in DeviceMap + whatever
    # the user added. A device may sit on another intercom's address with its
    # factory/old IP; looking only at its own target is not enough.
    all_intercoms = [resolve(device.get("IP", ""), set_no)
                     for switch in device_map.get("Switches", [])
                     for device in switch.get("Devices", [])
                     if device.get("SubType") == "Intercom"]
    cfg.factory_ip = resolve(cfg.factory_ip, set_no)
    candidates = list(dict.fromkeys(
        [cfg.factory_ip] + targets + all_intercoms
        + [resolve(ip, set_no) for ip in cfg.default_ip]))

    print(f"Set no      : {set_no}")
    print(f"Switch      : {cfg.switch_ip}")
    print(f"Ports       : {ports}")
    for port in ports:
        print(f"   port {port:>2}  ->  {plan[port]['target']:<14} "
              f"({plan[port]['name']})")
    print(f"Factory IP  : {cfg.factory_ip}   "
          f"(whoever answers here = unconfigured intercom)")
    print(f"Candidate IPs: {', '.join(candidates)}")

    # Flushing ARP is what lets the run finish in one pass; if permission is
    # missing the user should learn it at the start, not at the end.
    if (cfg.arp_flush and not cfg.dry_run
            and arp_forget([cfg.factory_ip], cfg)):
        print("ARP         : the cache can be flushed")
    if cfg.dry_run:
        print("\n[dry-run] Nothing will be changed.\n")

    try:
        state = poe_read(cfg)
    except Exception as exc:
        count = cfg.switch_port_count or (24 if cfg.dry_run else None)
        if count is None:
            print(f"[ERROR] Could not read the switch PoE state ({cfg.switch_ip})")
            print(f"        {exc}")
            print("        If you know the endpoint: --poe-read-endpoint stat/xxx")
            print("        Or give the port count: --switch-port-count 24")
            return 1
        print(f"[!] PoE state unreadable, falling back to {count} ports "
              f"({exc})")
        state = [{"pid": i, "poeMode": POE_ON, "priority": "0",
                  "maxPower": "154"} for i in range(1, count + 1)]
    known_pids = {int(p["pid"]) for p in state}
    unknown = [p for p in ports if p not in known_pids]
    if unknown:
        print(f"[ERROR] Port not present on the switch: {unknown}")
        return 1
    managed = set(ports)

    def do_port(port: int, baseline: dict, index: int, count: int,
                assigned: set[str]) -> tuple[bool, str]:
        target = plan[port]["target"]
        print(f"\n[{index}/{count}] Port {port} -> {target} "
              f"({plan[port]['name']})")
        emit_event("port_started", port=port, target=target, index=index,
                   total=count)

        # Ports in range are closed and the target opened in the SAME write:
        # one request to the switch, one closing as the other opens.
        print(f"    closing the ports in range, opening {port}...")
        emit_event("port_step", port=port, step=STEP_POE_ON,
                   detail=f"closing the ports in range, opening {port}")
        try:
            poe_apply(cfg, state, {port}, managed)
        except Exception as exc:
            return False, f"switch error: {type(exc).__name__}"
        if cfg.dry_run:
            return True, ""
        time.sleep(cfg.settle)

        # Flush ARP BEFORE probing: these addresses may still map to the
        # previous device's MAC (see arp_forget).
        arp_forget({cfg.factory_ip, target}
                   | {plan[p]["target"] for p in ports}, cfg)

        # Ask the switch instead of counting blindly: is the port linked?
        # "up" means the device has power and brought the line up, and only
        # then does the search window start. Previously the 15 s window began
        # the moment the port opened and expired before the device booted —
        # most extra passes came from this.
        linked, elapsed = wait_for_link(cfg, port, cfg.link_wait)
        if linked is True:
            how = ("the link was already up" if elapsed < 0.5
                   else f"port linked ({elapsed:.1f} s)")
            print(f"    {how} — searching for the device "
                  f"(at most {cfg.find_wait:.0f} s)...")
            search_window = cfg.find_wait
        elif linked is None:
            print(f"    (link state unreadable) searching for the device "
                  f"(at most {cfg.boot_wait:.0f} s)...")
            search_window = cfg.boot_wait
        else:
            print(f"    [!] The port did not link in {elapsed:.0f} s — the "
                  f"cable or the device may need checking")
            emit_event("port_note", port=port, level="warning",
                       text=f"the port did not link in {elapsed:.0f} s")
            return False, "the port did not link (no link up)"
        emit_event("port_step", port=port, step=STEP_SEARCHING,
                   detail="searching for the device")

        # Already-assigned IPs drop out of the candidate list (factory IP aside).
        search = [ip for ip in candidates
                  if ip not in assigned or ip == cfg.factory_ip]

        # MAC verification: devices on the wrong port are excluded and the
        # search continues
        blocked, found_ip, settings = [], None, None
        end = time.monotonic() + search_window
        while True:
            remaining = max(1.0, end - time.monotonic())
            ip, found_settings = find_device(
                [c for c in search if c not in blocked], cfg, remaining,
                baseline)
            if ip is None:
                return False, "device not found"
            verified, why = verify_port(ip, port, cfg)
            if verified is False:
                print(f"    [!] {ip} is not on this port ({why}) — dropped")
                emit_event("port_note", port=port, level="warning",
                           text=f"{ip} is not on this port ({why}) — dropped")
                blocked.append(ip)
                if time.monotonic() >= end:
                    return False, "no device found on the right port"
                continue
            found_ip, settings = ip, found_settings
            print(f"    device found: {ip}"
                  + (f"  [{why}]" if verified else f"  ({why})"))
            emit_event("port_step", port=port, step=STEP_DEVICE_FOUND,
                       detail=f"device found: {ip}")
            break

        # The one moment a single device is reachable and still unconfigured
        # (see BEFORE_WRITE at the top of this file).
        if BEFORE_WRITE is not None and not cfg.dry_run:
            emit_event("port_step", port=port, step=STEP_FIRMWARE,
                       detail="firmware check")
            ok, note = BEFORE_WRITE(port, found_ip, settings, cfg)
            if note:
                print(f"    {note}")
            if not ok:
                emit_event("port_note", port=port, level="warning",
                           text=note or "the firmware step did not complete")
                return False, note or "the firmware step did not complete"
            # A firmware upload reboots the device, so the settings read
            # before it are stale — and write_ip builds its payload out of
            # them. Re-read; keep the old ones if the device is not back yet,
            # because the write below is what will really tell us.
            refreshed = read_settings(found_ip, cfg)
            if refreshed:
                settings = refreshed

        if found_ip == target:
            print("    the IP is already correct")
            emit_event("port_written", port=port, reason="already_correct",
                       target=target)
            return True, ""

        if cfg.backup_dir:
            cfg.backup_dir.mkdir(parents=True, exist_ok=True)
            backup = cfg.backup_dir / f"port{port}_{found_ip}.json"
            backup.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2),
                encoding="utf-8")
            print(f"    backup: {backup.name}")

        print(f"    writing the IP: {found_ip} -> {target}")
        emit_event("port_step", port=port, step=STEP_WRITING_IP,
                   detail=f"writing the IP: {found_ip} -> {target}")
        try:
            write_ip(found_ip, settings, target, cfg)
        except requests.RequestException as exc:
            print(f"    (no write response: {exc.__class__.__name__} "
                  f"— it may have reset, verifying)")

        if cfg.defer_verify:
            # Moving to the next port cuts this device's power. First wait for
            # proof the write landed: the device must drop off its old IP,
            # meaning it reset. Trusting HTTP 200 alone is not enough.
            time.sleep(cfg.post_write_wait)
            still_there = wait_gone([found_ip], cfg, cfg.reset_wait)
            if still_there:
                print(f"    [!] {found_ip} is still on the old IP — the write "
                      f"may not have been applied")
                return False, f"{found_ip} did not reset"
            print("    written (reset confirmed), the IP check is deferred "
                  "to the end")
            emit_event("port_written", port=port, reason="written",
                       target=target)
            return True, ""

        print(f"    verification: waiting for {target} "
              f"(reset + at most {cfg.confirm_wait:.0f} s)...")
        emit_event("port_step", port=port, step=STEP_VERIFYING,
                   detail=f"verification: waiting for {target}")
        # The target's ARP entry can be stale too: the device just moved there
        # while the cache may still hold another device's MAC.
        arp_forget([target], cfg)
        confirmed_ip, _ = find_device([target], cfg, cfg.confirm_wait)
        if confirmed_ip == target:
            print(f"    [OK] Port {port} -> {target}")
            emit_event("port_ok", port=port, target=target)
            return True, ""
        return False, f"{target} did not answer"

    done, failed = [], {}
    try:
        # Who answers while every managed port is off? Those are devices on
        # unmanaged ports — do not touch them.
        baseline = {}
        if not cfg.dry_run:
            print("\nBaseline scan (the ports in range are off)...")
            emit_event("phase", phase=PHASE_BASELINE)
            poe_apply(cfg, state, set(), managed)
            time.sleep(cfg.settle)
            # Devices do not go quiet the instant PoE is cut; wait for settle
            baseline = wait_until_quiet(candidates, cfg, cfg.baseline_wait)
            print(f"    {len(baseline)} device(s) up outside the range"
                  + (f": {', '.join(baseline)}" if baseline else ""))
            if cfg.factory_ip in baseline:
                print(f"    [!] {cfg.factory_ip} (factory IP) answers from "
                      f"outside the range — an unconfigured intercom may be "
                      f"on another port")

        # Keep passing until everything is done. A pass with no progress
        # stretches the waits; stall-limit consecutive stalled passes stop the
        # run so it cannot loop forever.
        pending = list(ports)
        assigned: set[str] = set()      # completed target IPs — do not touch
        turn, stalled = 0, 0
        while pending:
            turn += 1
            if cfg.max_passes and turn > cfg.max_passes:
                print(f"\n[!] Pass limit reached ({cfg.max_passes}), "
                      f"remaining: {pending}")
                break
            if turn > 1:
                print(f"\n=== Pass {turn} — remaining ports: {pending}"
                      f"  (waits: boot {cfg.boot_wait:.0f}s / "
                      f"verify {cfg.confirm_wait:.0f}s) ===")
            emit_event("pass_started", **{"pass": turn})

            before = len(pending)
            next_round = []
            for index, port in enumerate(pending, start=1):
                ok, error = do_port(port, baseline, index, len(pending),
                                    assigned)
                if ok:
                    done.append(port)
                    assigned.add(plan[port]["target"])
                    failed.pop(port, None)
                else:
                    print(f"    [!] Port {port}: {error}")
                    emit_event("port_failed", port=port, reason=error)
                    failed[port] = error
                    next_round.append(port)
            pending = next_round

            if len(pending) < before:
                stalled = 0                      # progress, keep going
                continue
            stalled += 1
            if stalled >= cfg.stall_limit:
                print(f"\n[!] No progress for {stalled} pass(es), stopping. "
                      f"Remaining: {pending}")
                break
            if cfg.retry_backoff > 1:
                # Search windows grow on every stalled pass, and so does the
                # link wait — a slow device can exceed both.
                cfg.boot_wait *= cfg.retry_backoff
                cfg.confirm_wait *= cfg.retry_backoff
                cfg.find_wait *= cfg.retry_backoff
                cfg.link_wait *= cfg.retry_backoff
    except KeyboardInterrupt:
        print("\n\n[CANCELLED] Stopped by the user — reopening the ports...")
    finally:
        print(f"\nReopening every port in range: {ports}")
        emit_event("phase", phase=PHASE_RESTORE)
        for attempt in range(3):
            try:
                poe_apply(cfg, state, managed, managed)
                break
            except Exception as exc:
                print(f"[!] Could not reopen the ports ({attempt + 1}/3): "
                      f"{type(exc).__name__}")
                time.sleep(5)
        else:
            emit_event("ports_left_closed", switch=cfg.switch_ip)
            print("[!] THE PORTS MAY HAVE BEEN LEFT CLOSED — open them by hand:")
            print(f"    http://{cfg.switch_ip}/poePort.html")

    # ------------------------------------------------- final verification ----
    if not cfg.dry_run:
        print(f"\nFinal verification (waiting up to {cfg.boot_wait:.0f} s for "
              f"every device to come up)...")
        emit_event("phase", phase=PHASE_VERIFY)
        # The ports just reopened and devices settled on their new addresses;
        # every ARP entry may be stale.
        arp_forget(targets, cfg)
        end = time.monotonic() + cfg.confirm_wait
        seen = {}
        while time.monotonic() < end:
            seen = probe_all(targets, cfg)      # parallel, ~1 s
            if len(seen) == len(targets):
                break
            time.sleep(cfg.poll_interval)
        # With verification deferred, stragglers can still be fixed
        missing_ports = [p for p in ports if plan[p]["target"] not in seen]
        if missing_ports and cfg.defer_verify:
            print(f"    {len(missing_ports)} port(s) unverified, retrying: "
                  f"{missing_ports}")
            for port in missing_ports:
                failed.setdefault(port, "no answer in the final verification")

        print(f"\n{'port':>5}  {'target IP':<14} state")
        print("  " + "-" * 44)
        for port in ports:
            target = plan[port]["target"]
            if target in seen:
                print(f"{port:>5}  {target:<14} OK")
                emit_event("summary_row", port=port, target=target,
                           status="ok", reason="")
            else:
                reason = failed.get(port, "no answer")
                print(f"{port:>5}  {target:<14} MISSING — {reason}")
                emit_event("summary_row", port=port, target=target,
                           status="missing", reason=reason)

        # ------------------------------------------ persistence check ----
        # If the setting landed in RAM but never reached flash, the device
        # returns to its old IP on power loss. The only proof is to cycle the
        # power once and look again.
        if cfg.persist_check and seen:
            print("\nPersistence check (the ports are power cycled once)...")
            try:
                poe_apply(cfg, state, set(), managed)
                time.sleep(cfg.settle + 2)
                poe_apply(cfg, state, managed, managed)
            except Exception as exc:
                print(f"    [!] Could not cycle the power: {type(exc).__name__}")
            else:
                end = time.monotonic() + cfg.confirm_wait
                while time.monotonic() < end:
                    seen = probe_all(targets, cfg)
                    if len(seen) == len(targets):
                        break
                    time.sleep(cfg.poll_interval)
                persisted = [p for p in ports if plan[p]["target"] in seen]
                print(f"    {len(persisted)}/{len(ports)} target IP(s) up "
                      f"after the power cycle")
                if len(persisted) < len(ports):
                    print("    [!] Some settings are NOT PERSISTENT — the "
                          "device returns to its old IP when power is cut.")
                    print("        The write request is accepted but may not "
                          "reach flash; try --full-net-payload.")

        if (cfg.factory_ip not in targets
                and read_settings(cfg.factory_ip, cfg) is not None):
            print(f"\n[!] {cfg.factory_ip} still answers — an "
                  f"unconfigured intercom is left")

        incomplete = [p for p in ports if plan[p]["target"] not in seen]
        if incomplete:
            print(f"\n{len(incomplete)} port(s) not completed: {incomplete}")
            print("Next step — retry only these:")
            print(f"    python3 {Path(__file__).name} --ports "
                  f"{' '.join(map(str, incomplete))} "
                  f"--boot-wait 45 --confirm-wait 60")
            print("If the device is never found, check it with the port open:")
            print("    sudo arp-scan --interface=en6 -l")
            return 1
        print(f"\nAll done: {len(ports)}/{len(ports)} ports")
        return 0

    print(f"\n[dry-run] {len(done)}/{len(ports)} ports planned")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[CANCELLED] Stopped by the user.")
        print("Make sure the ports are open: "
              "http://10.n.1.101/poePort.html")
        sys.exit(130)
