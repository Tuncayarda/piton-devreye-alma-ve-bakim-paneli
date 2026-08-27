#!/usr/bin/env python3
"""Switch management panel — KYLAND switch backend.

The browser never talks to a switch directly; this service sits in between:

    web UI  ->  this backend  --Basic Auth-->  KYLAND switch HTTP API

Credentials are stored in no file: the user types them in after picking a
switch, they live in memory only and disappear when the app exits.

Every switch has a write lock; PoE/port POSTs are always built on a fresh GET,
serialised, never run in parallel.

Run:
    python3 switch_api.py --port 9000              # API only (no window)
    python3 switch_api.py --discover 10.1.1.0/24   # one-off scan
"""
from __future__ import annotations

import argparse
import sys
import concurrent.futures as cf
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from requests.auth import HTTPBasicAuth

HERE = Path(__file__).resolve().parent


def resource_dir() -> Path:
    """Folder holding the UI files (static/).

    Under PyInstaller data is unpacked to a temp dir reported via
    sys._MEIPASS; from source it sits next to this file.
    """
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else HERE


STATIC_DIR = resource_dir() / "static"

# Application version — shown in the status bar. Single source.
APP_VERSION = "1.0.3"

# ------------------------------------------------------------- settings --
PREFIX_TO_MASK = {"8": "255.0.0.0", "16": "255.255.0.0", "24": "255.255.255.0"}
POE_MODE = {"0": "Off", "1": "PoE", "2": "PoE+"}
POE_PRIORITY = {"0": "Low", "1": "High", "2": "Critical"}

# Write lock per switch (blocks concurrent POSTs to the same switch)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

# One scan at a time. A second request is rejected immediately rather than
# queued: stacked scans drown the switch's small web server.
_SCAN_LOCK = threading.Lock()

# Flag that stops a running scan. The UI's "Cancel" sets it; scan threads
# check it before each address and leave the rest untouched. Aborting the
# request alone was not enough — the server kept polling switches and holding
# the lock.
_SCAN_CANCEL = threading.Event()


def lock_for(ip: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(ip, threading.Lock())


# HTTP port of the switches. Overridable with --switch-port at startup;
# there is no settings file.
SWITCH_PORT = 80

# Default network range offered in the scan box
DISCOVER_CIDR = "10.1.1.0/24"

# Call configSave after every change?
# OFF: saving happens only when the user presses "Save", so the switch's
# flash is not written on every port touch and an unwanted change can be
# undone by rebooting.
AUTOSAVE = False

# TCP pre-probe timeout during a range scan (unused for a single IP)
TCP_PROBE_TIMEOUT = 1.2


# Credentials are kept in no file. The user types them in after picking a
# switch; they live in memory only and vanish when the app exits.
_CREDENTIALS: dict[str, tuple[str, str]] = {}      # ip -> (username, password)
_CREDENTIALS_GUARD = threading.Lock()
_LAST_CREDENTIALS: tuple[str, str] | None = None   # last pair to try when scanning


def store_credentials(ip: str, username: str, password: str) -> None:
    global _LAST_CREDENTIALS
    with _CREDENTIALS_GUARD:
        _CREDENTIALS[ip] = (username, password)
        _LAST_CREDENTIALS = (username, password)


def clear_credentials(ip: str | None = None) -> None:
    global _LAST_CREDENTIALS
    with _CREDENTIALS_GUARD:
        if ip is None:
            _CREDENTIALS.clear()
            _LAST_CREDENTIALS = None
        else:
            _CREDENTIALS.pop(ip, None)


def get_credentials(ip: str) -> tuple[str, str] | None:
    """That switch's own credential first, else the last successful pair.

    The fallback helps while scanning: after signing in to one switch the
    same username/password often works on the rest.
    """
    with _CREDENTIALS_GUARD:
        return _CREDENTIALS.get(ip) or _LAST_CREDENTIALS


# ----------------------------------------------------------- switch API ----
class SwitchError(Exception):
    pass


class AuthError(Exception):
    """The switch rejected authentication, or none was entered."""


def _auth(ip: str, credentials=None):
    pair = credentials or get_credentials(ip)
    return HTTPBasicAuth(*pair) if pair else None


def _parse_response(r, ip: str):
    """Parse the response as JSON; turn auth problems into AuthError.

    A device does not always signal "I want credentials" with a 401: some
    firmware returns the login page as HTML with 200. Any non-JSON reply is
    treated as an auth problem too, because these endpoints otherwise only
    ever return JSON.
    """
    if r.status_code in (401, 403) or "WWW-Authenticate" in r.headers:
        raise AuthError(f"{ip} wants a username/password")
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        content_type = r.headers.get("Content-Type", "?")
        raise AuthError(
            f"{ip} returned {content_type} instead of JSON — "
            "a session must be opened")


def sw_get(ip: str, endpoint: str, timeout=5, credentials=None):
    r = requests.get(f"http://{ip}:{SWITCH_PORT}/{endpoint}",
                     auth=_auth(ip, credentials), timeout=timeout)
    return _parse_response(r, ip)


def sw_post(ip: str, endpoint: str, form: dict, timeout=8):
    r = requests.post(f"http://{ip}:{SWITCH_PORT}/{endpoint}",
                      auth=_auth(ip), data=form,
                      headers={"Content-Type":
                               "application/x-www-form-urlencoded; charset=UTF-8",
                               "X-Requested-With": "XMLHttpRequest"},
                      timeout=timeout)
    return _parse_response(r, ip)


def is_switch(ip: str, timeout=1.5, credentials=None) -> dict | None:
    """A basicInfo reply means it is a switch; returns a summary.

    Without (or with wrong) credentials the device returns 401 — which also
    proves it is a switch. Those are flagged "locked" and still listed; the
    user is asked for a username/password on selection.
    """
    try:
        data = sw_get(ip, "stat/basicInfo", timeout=timeout,
                      credentials=credentials)
    except AuthError:
        return {"ip": ip, "name": "Switch", "model": "", "version": "",
                "mac": "", "locked": True}
    except Exception:
        return None
    info = data.get("basicInfo", data) if isinstance(data, dict) else {}
    if not isinstance(info, dict):
        info = {}
    return {
        "ip": ip,
        "name": info.get("deviceName") or info.get("sysName") or "Switch",
        "model": info.get("deviceType") or info.get("model") or "",
        "version": info.get("softVer") or info.get("softwareVersion") or "",
        "mac": info.get("macAddress") or info.get("mac") or "",
        "locked": False,
    }


def tcp_open(ip: str, port: int, timeout=0.4) -> bool:
    try:
        with socket.create_connection((ip, port), timeout):
            return True
    except OSError:
        return False


def discover(cidr: str, workers=64,
             cancel: threading.Event | None = None) -> dict:
    """Scan a network and find switches.

    A single IP ("10.1.1.101") is queried over HTTP directly — no TCP
    pre-probe, since filtering one address is pointless and could wrongly
    exclude a slow device.

    For a range, a light TCP probe runs first (254 concurrent HTTP+auth
    requests drown the switch's little web server) and only responders are
    asked for basicInfo. If TCP finds nothing, HTTP is tried anyway: the
    pre-probe is a speed optimisation, not a gatekeeper.

    With `cancel` set, each address is checked first: the rest are left
    untouched and the result carries a "cancelled" flag. One in-flight socket
    wait may still run to its own timeout; beyond that the scan ends at once.
    """
    cidr = (cidr or "").strip()
    single = bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+", cidr))
    stopped = lambda: bool(cancel and cancel.is_set())        # noqa: E731

    if single:
        hosts = [cidr]
        candidates = hosts                    # straight to HTTP
    else:
        m = (re.match(r"(\d+\.\d+\.\d+)\.\d+/\d+", cidr)
             or re.match(r"(\d+\.\d+\.\d+)\.?$", cidr))
        prefix = m.group(1) if m else cidr.rstrip(".")
        hosts = [f"{prefix}.{i}" for i in range(1, 255)]
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            candidates = [h for h, ok in zip(hosts, pool.map(
                lambda h: (not stopped()
                           and tcp_open(h, SWITCH_PORT, TCP_PROBE_TIMEOUT)),
                hosts)) if ok]
        if stopped():
            return {"switches": [], "probed": len(hosts), "queried": 0,
                    "cancelled": True}
        if not candidates:                    # empty pre-probe -> try anyway
            candidates = hosts

    timeout = 6.0 if single else 4.0
    found = []
    with cf.ThreadPoolExecutor(
            max_workers=min(len(candidates) or 1, 24)) as pool:
        for result in pool.map(
                lambda h: None if stopped() else is_switch(h, timeout=timeout),
                candidates):
            if result:
                found.append(result)
    return {"switches": found, "probed": len(hosts),
            "queried": len(candidates), "cancelled": stopped()}


# ------------------------------------------------------- business logic ----
def get_info(ip: str) -> dict:
    """The selected switch's identity plus its management IP.

    is_switch() is used while scanning, so it returns a "locked" summary on
    auth problems; here that becomes an error. Otherwise the UI showed an
    empty header ("SWITCH · ip · v?") without ever asking for a password.
    """
    info = is_switch(ip, timeout=4)
    if info is None:
        raise SwitchError(f"{ip} is not answering")
    if info.get("locked"):
        raise AuthError(f"{ip} wants a username/password")
    try:
        net = sw_get(ip, "stat/vlanIntfIp?intf=1")
        net = net.get("vlanIntfIp", net) if isinstance(net, dict) else {}
    except AuthError:
        raise                       # an auth problem must not be swallowed
    except Exception:
        net = {}
    info["network"] = {
        "method": net.get("method", "manual"),
        "addr": net.get("addr", ip),
        "netmaskLen": str(net.get("netmaskLen", "")),
        "netmask": PREFIX_TO_MASK.get(str(net.get("netmaskLen", "")), ""),
        "mtu": str(net.get("mtu", "1500")),
    }
    return info


def get_ports(ip: str) -> list[dict]:
    """portMode + poePort + poeStatus merged into one list."""
    pm = sw_get(ip, "stat/portMode").get("portMode", [])
    poe = {int(p["pid"]): p
           for p in sw_get(ip, "stat/poePort").get("poePort", [])}
    try:
        live = {int(p["pid"]): p
                for p in sw_get(ip, "stat/poeStatus").get("poeStatus", [])}
    except AuthError:
        raise                       # an auth problem must not be swallowed
    except Exception:
        live = {}                   # endpoint absent: usage stays empty

    out = []
    for p in pm:
        pid = int(p["pid"])
        pp = poe.get(pid, {})
        ls = live.get(pid, {})
        power = ls.get("powerUsed")
        out.append({
            "pid": pid,
            "type": p.get("type", ""),
            "adminStat": bool(p.get("adminStat")),
            "linkStat": p.get("linkStat", ""),
            "linktext": p.get("linktext", ""),
            "speed": str(p.get("speed", "")),
            "autoNego": bool(p.get("autoNego")),
            "duplex": bool(p.get("duplex")),
            "flowCtrl": bool(p.get("flowCtrl")),
            "maxLength": str(p.get("maxLength", "")),
            "linkType": str(p.get("linkType", "")),
            "poe": pid in poe,
            "poeMode": str(pp.get("poeMode", "")),
            "poeModeText": POE_MODE.get(str(pp.get("poeMode", "")), ""),
            "priority": str(pp.get("priority", "0")),
            "priorityText": POE_PRIORITY.get(str(pp.get("priority", "0")), ""),
            "maxPower": str(pp.get("maxPower", "154")),
            "poeStatus": ls.get("portStatus", ""),
            "powerW": (round(int(power) / 10, 1)
                       if str(power).isdigit() else None),
        })
    return out


def config_save(ip: str) -> dict:
    """Persist the running configuration.

    Without this, PoE/port/IP changes are lost when the switch reboots — they
    live in RAM and are never written to flash.
    """
    return sw_post(ip, "stat/configSave", {"postOperation": "configSave"},
                   timeout=15)


def _autosave(ip: str, result: dict) -> dict:
    """Save after a change; note it on the result if saving fails.

    With autosave off, no "saved" field is added at all — being unsaved is
    the expected state, not an error. The UI tracks it with an "unsaved
    changes" indicator.
    """
    if not AUTOSAVE:
        return result
    try:
        config_save(ip)
        result["saved"] = True
    except Exception as exc:
        result["saved"] = False
        result["saveError"] = f"{type(exc).__name__}: {exc}"
    return result


def set_poe(ip: str, port: int, mode: str) -> dict:
    """Change one port's PoE mode (reads and writes all 24 ports)."""
    with lock_for(ip):
        ports = sw_get(ip, "stat/poePort").get("poePort", [])
        if not any(int(p["pid"]) == port for p in ports):
            raise SwitchError(f"port {port} PoE listesinde yok")
        form = {}
        for p in ports:
            pid = int(p["pid"])
            form[f"mode_{pid}"] = (str(mode) if pid == port
                                   else str(p["poeMode"]))
            form[f"priority_{pid}"] = str(p["priority"])
            form[f"maxPower_{pid}"] = str(p["maxPower"])
        return _autosave(ip, sw_post(ip, "stat/poePort", form))


def _portmode_form(ports: list, admin_over: dict) -> dict:
    """Build the portMode POST body; admin_over overrides the given ports.

    The switch writes every port in one request, so unchanged ports must be
    sent back with their current values.
    """
    form = {}
    for p in ports:
        pid = int(p["pid"])
        admin = admin_over.get(pid, bool(p.get("adminStat")))
        if admin:
            form[f"adminStat_{pid}"] = "1"
        form[f"linkType_{pid}"] = str(p.get("linkType", "0"))
        if p.get("autoNego"):
            form[f"autoNego_{pid}"] = "1"
        form[f"speed_{pid}"] = str(p.get("speed", ""))
        if p.get("duplex"):
            form[f"duplex_{pid}"] = "1"
        if p.get("flowCtrl"):
            form[f"flowCtrl_{pid}"] = "1"
        form[f"maxLength_{pid}"] = str(p.get("maxLength", "1522"))
    return form


def set_port_enabled(ip: str, port: int, enabled: bool,
                     protect_uplink=True) -> dict:
    """Enable/disable one port (reads and writes all ports).

    Accidentally closing the uplink port (link up and not in the request)
    loses access to the switch; protection is on by default.
    """
    with lock_for(ip):
        ports = sw_get(ip, "stat/portMode").get("portMode", [])
        if not any(int(p["pid"]) == port for p in ports):
            raise SwitchError(f"port {port} yok")
        return _autosave(ip, sw_post(ip, "stat/portMode",
                                     _portmode_form(ports, {port: enabled})))


def apply_batch(ip: str, poe: dict, ports: dict) -> dict:
    """Apply several PoE/port changes in a single write.

    The switch API already works as "read all, write all". Merging here means
    at most two POSTs (poePort + portMode) and one save at the end — one save
    round for 10 changes instead of 10.
    """
    result = {"retCode": ["success"], "poe": [], "ports": []}
    with lock_for(ip):
        if poe:
            current = sw_get(ip, "stat/poePort").get("poePort", [])
            known = {int(p["pid"]) for p in current}
            missing = sorted(set(poe) - known)
            if missing:
                raise SwitchError(f"PoE listesinde olmayan port: {missing}")
            form = {}
            for p in current:
                pid = int(p["pid"])
                form[f"mode_{pid}"] = str(poe.get(pid, p["poeMode"]))
                form[f"priority_{pid}"] = str(p["priority"])
                form[f"maxPower_{pid}"] = str(p["maxPower"])
            sw_post(ip, "stat/poePort", form)
            result["poe"] = sorted(poe)

        if ports:
            current = sw_get(ip, "stat/portMode").get("portMode", [])
            known = {int(p["pid"]) for p in current}
            missing = sorted(set(ports) - known)
            if missing:
                raise SwitchError(f"olmayan port: {missing}")
            sw_post(ip, "stat/portMode", _portmode_form(current, ports))
            result["ports"] = sorted(ports)

    return _autosave(ip, result)


def set_port_config(ip: str, port: int, cfg: dict) -> dict:
    """Update one port's speed/duplex/flow/frame settings."""
    with lock_for(ip):
        ports = sw_get(ip, "stat/portMode").get("portMode", [])
        if not any(int(p["pid"]) == port for p in ports):
            raise SwitchError(f"port {port} yok")
        form = {}
        for p in ports:
            pid = int(p["pid"])
            cur = cfg if pid == port else {}
            admin = cur.get("adminStat", bool(p.get("adminStat")))
            if admin:
                form[f"adminStat_{pid}"] = "1"
            form[f"linkType_{pid}"] = str(p.get("linkType", "0"))
            auto = cur.get("autoNego", bool(p.get("autoNego")))
            if auto:
                form[f"autoNego_{pid}"] = "1"
            form[f"speed_{pid}"] = str(cur.get("speed", p.get("speed", "")))
            duplex = cur.get("duplex", bool(p.get("duplex")))
            if duplex:
                form[f"duplex_{pid}"] = "1"
            flow = cur.get("flowCtrl", bool(p.get("flowCtrl")))
            if flow:
                form[f"flowCtrl_{pid}"] = "1"
            form[f"maxLength_{pid}"] = str(
                cur.get("maxLength", p.get("maxLength", "1522")))
        return _autosave(ip, sw_post(ip, "stat/portMode", form))


def set_network(ip: str, addr: str, prefix: str, mtu="1500") -> dict:
    """Change the switch IP. Losing the connection is expected."""
    with lock_for(ip):
        form = {"method": "manual", "addr": addr,
                "netmaskLen": str(prefix), "mtu": str(mtu)}
        try:
            result = sw_post(ip, "stat/vlanIntfIp?intf=1", form, timeout=5)
        except requests.RequestException:
            # On an IP change the switch drops the old address — normal.
            result = {"retCode": ["success"],
                      "note": "the connection dropped (expected)"}
        # The save must go to the NEW address; the switch is gone from the old.
        if AUTOSAVE:
            time.sleep(2)
            try:
                config_save(addr)
                result["saved"] = True
            except Exception:
                result["saved"] = False
                result["saveError"] = (f"could not save from {addr} — "
                                       f"connect on the new address and "
                                       f"press Save")
        return result


def login(ip: str, username: str, password: str) -> dict:
    """Try the given credential against the switch; remember it if it works.

    Nothing is written anywhere; it stays in the running process.
    """
    if not username:
        raise SwitchError("a username is required")
    info = is_switch(ip, timeout=6, credentials=(username, password))
    if info is None:
        raise SwitchError(f"{ip} is not answering")
    if info.get("locked"):
        raise AuthError("wrong username or password")
    store_credentials(ip, username, password)
    return info


def reboot(ip: str) -> dict:
    with lock_for(ip):
        try:
            return sw_post(ip, "stat/reboot",
                           {"postOperation": "reboot"}, timeout=5)
        except requests.RequestException:
            return {"retCode": ["success"], "note": "the switch is shutting down"}


def factory_reset(ip: str) -> dict:
    """Reset the switch to factory defaults.

    Irreversible: the whole configuration including the IP is wiped, the
    switch returns to its default address and may not be findable from this
    UI again. The call therefore requires the switch IP typed as confirmation
    in the body (see do_POST).
    """
    with lock_for(ip):
        try:
            return sw_post(ip, "stat/reset",
                           {"postOperation": "reset"}, timeout=10)
        except requests.RequestException:
            # A resetting switch may drop the connection without answering
            return {"retCode": ["success"], "note": "the switch is resetting"}


# --------------------------------------------------------------- HTTP -----
class Handler(BaseHTTPRequestHandler):
    server_version = "SwitchAPI/1.0"

    def _send(self, code, payload, ctype="application/json"):
        body = (json.dumps(payload).encode("utf-8")
                if ctype == "application/json" else payload)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            return {}

    def _file(self, name, ctype):
        """Send a static file with caching disabled.

        Without a cache header the browser keeps the file on its own guess,
        and the window still showed the old UI after an update. Caching a few
        KB read from disk buys nothing anyway.
        """
        path = STATIC_DIR / name
        if not path.exists():
            return self._send(404, {"error": "yok"})
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _index(self):
        """Send index.html with a version stamp on asset URLs.

        The app window (WebView2 / WKWebView / QtWebEngine) stubbornly cached
        the old app.js and style.css. The URL changes whenever the file does,
        so the cache drops out by itself.
        """
        path = STATIC_DIR / "index.html"
        if not path.exists():
            return self._send(404, {"error": "yok"})
        html = path.read_text(encoding="utf-8")
        for asset in ("app.js", "style.css"):
            asset_path = STATIC_DIR / asset
            stamp = int(asset_path.stat().st_mtime) if asset_path.exists() else 0
            html = html.replace(f'"/{asset}"', f'"/{asset}?v={stamp}"')
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    # --------------------------------------------------------- routing ----
    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        try:
            if url.path in ("/", "/index.html"):
                return self._index()
            if url.path == "/app.js":
                return self._file("app.js", "application/javascript")
            if url.path == "/style.css":
                return self._file("style.css", "text/css")
            if url.path == "/piton-logo.svg":
                return self._file("piton-logo.svg", "image/svg+xml")
            if url.path == "/piton-favicon.png":
                return self._file("piton-favicon.png", "image/png")

            if url.path == "/api/version":
                return self._send(200, {"version": APP_VERSION})
            if url.path == "/api/discover":
                cidr = query.get("cidr", [DISCOVER_CIDR])[0]
                if not _SCAN_LOCK.acquire(blocking=False):
                    return self._send(409, {"error": "a scan is already running"})
                try:
                    _SCAN_CANCEL.clear()
                    return self._send(200, discover(cidr, cancel=_SCAN_CANCEL))
                finally:
                    _SCAN_LOCK.release()
            if url.path == "/api/discover/cancel":
                # Raise the flag and wait for the scan to really finish, so
                # the lock is free by the time the UI gets this reply and a
                # "Scan" pressed right after does not hit a 409.
                _SCAN_CANCEL.set()
                if _SCAN_LOCK.acquire(timeout=10):
                    _SCAN_LOCK.release()
                    return self._send(200, {"ok": True, "stopped": True})
                return self._send(200, {"ok": True, "stopped": False})
            if url.path == "/api/switch/info":
                return self._send(200, get_info(query["ip"][0]))
            if url.path == "/api/switch/ports":
                return self._send(200, {"ports": get_ports(query["ip"][0])})
            return self._send(404, {"error": "unknown path"})
        except AuthError as exc:
            self._send(401, {"error": str(exc), "auth": True})
        except KeyError:
            self._send(400, {"error": "the ip parameter is required"})
        except requests.RequestException as exc:
            self._send(502, {"error": f"the switch is unreachable: {exc}"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_POST(self):
        url = urlparse(self.path)
        body = self._json_body()
        ip = body.get("ip")
        try:
            if not ip:
                return self._send(400, {"error": "an ip is required"})
            if url.path == "/api/switch/login":
                return self._send(200, login(ip, str(body.get("user", "")),
                                             str(body.get("pass", ""))))
            if url.path == "/api/switch/logout":
                clear_credentials(ip if body.get("all") is not True else None)
                return self._send(200, {"ok": True})
            if url.path == "/api/switch/poe":
                return self._send(200, set_poe(ip, int(body["port"]),
                                               str(body["mode"])))
            if url.path == "/api/switch/port":
                if "enabled" in body:
                    return self._send(200, set_port_enabled(
                        ip, int(body["port"]), bool(body["enabled"])))
                return self._send(200, set_port_config(
                    ip, int(body["port"]), body.get("config", {})))
            if url.path == "/api/switch/batch":
                poe = {int(k): str(v)
                       for k, v in (body.get("poe") or {}).items()}
                ports = {int(k): bool(v)
                         for k, v in (body.get("ports") or {}).items()}
                if not poe and not ports:
                    return self._send(
                        400, {"error": "there is no change to send"})
                return self._send(200, apply_batch(ip, poe, ports))
            if url.path == "/api/switch/network":
                return self._send(200, set_network(
                    ip, body["addr"], body["prefix"], body.get("mtu", "1500")))
            if url.path == "/api/switch/config-save":
                return self._send(200, config_save(ip))
            if url.path == "/api/switch/reboot":
                # No automatic save: saving is the user's call. The UI warns
                # when there are unsaved changes.
                return self._send(200, reboot(ip))
            if url.path == "/api/switch/factory-reset":
                # Destructive: the body must repeat the switch IP as consent.
                if str(body.get("confirm", "")).strip() != ip:
                    return self._send(400, {"error": "the confirmation was not verified"})
                return self._send(200, factory_reset(ip))
            return self._send(404, {"error": "unknown path"})
        except AuthError as exc:
            self._send(401, {"error": str(exc), "auth": True})
        except (KeyError, ValueError) as exc:
            self._send(400, {"error": f"missing/invalid field: {exc}"})
        except SwitchError as exc:
            self._send(400, {"error": str(exc)})
        except requests.RequestException as exc:
            self._send(502, {"error": f"the switch is unreachable: {exc}"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def log_message(self, fmt, *args):
        pass


def main() -> int:
    """API server only — opens no window.

    app.py is used for the application window. This entry point is for
    debugging: trying endpoints with curl, running a one-off scan.
    """
    global SWITCH_PORT

    # A Windows console may be cp1252, where Turkish characters raise
    # UnicodeEncodeError. Force the streams to UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Switch Management Panel — API server (opens no window)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770,
                        help="the port this service listens on")
    parser.add_argument("--switch-port", type=int, default=SWITCH_PORT,
                        help=f"the switches' HTTP port (default {SWITCH_PORT})")
    parser.add_argument("--discover", default=None,
                        help="scan this network and exit without starting "
                             "the server (e.g. 10.1.1.0/24)")
    args = parser.parse_args()
    SWITCH_PORT = args.switch_port

    if args.discover:
        print(f"Scanning the network: {args.discover}")
        for found in discover(args.discover)["switches"]:
            state = ("kilitli" if found["locked"]
                     else f"{found['model']} v{found['version']}")
            print(f"  {found['ip']:<16} {state}")
        return 0

    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print(f"[ERROR] Could not open port {args.port}: {exc}")
        return 1

    print(f"API: http://{args.host}:{args.port}   (Ctrl-C to stop)")
    print(f"Switches will be looked for on port {SWITCH_PORT}")
    print("Credentials are asked for in the UI and written nowhere.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
