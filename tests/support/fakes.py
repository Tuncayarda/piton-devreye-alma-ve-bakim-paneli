#!/usr/bin/env python3
"""Fake devices for the tests.

This is TEST scaffolding, not part of the application: the panel never
creates, shows or connects to a fake device.

They imitate the real hardware:
  · KYLAND switch — Basic Auth, /stat/basicInfo, JSON
  · a switch that answers with a login page — HTTP 200 + HTML (not a success)
  · Hikvision camera — Digest Auth, /ISAPI/System/deviceInfo, XML
  · announcement device — credential-less JSON /api/v1/system/settings
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASIC_INFO = {
    "basicInfo": {
        "deviceName": "Yatakli_Test_SW",
        "deviceType": "SICOM3028GPT",
        "softVer": "F6014",
        "macAddress": "00:11:22:33:44:55",
        # Field KYLAND units expose no single uptime field; it arrives split.
        "operateTime": {"day": "1", "hour": "2", "minute": "3", "second": "4"},
    }
}

PORT_MODE = {"portMode": [
    {"pid": i, "type": "GE", "adminStat": 1, "linkStat": "up" if i < 3 else "down"}
    for i in range(1, 25)
]}

LOGIN_HTML = (b"<!DOCTYPE html><html><head><title>Login</title></head>"
              b"<body><form>Username<input name=user></form></body></html>")

DEVICE_INFO_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema">'
    b'<deviceName>Test Camera</deviceName>'
    b'<model>DS-2CD1023</model>'
    b'<serialNumber>SN-TEST-0001</serialNumber>'
    b'<firmwareVersion>V5.7.3</firmwareVersion>'
    b'</DeviceInfo>')

# Field names match the real device exactly: /api/v1/system/settings
ANNOUNCEMENT_SETTINGS = {
    "firmwareVersion": "1.2.5",
    "serialNumber": "ANON-0001",
    "status": "Registered",
    "uptime": 1234,
    "pbxIp": "10.9.1.1",
    "pbxExtension": "2001",
    "pbxPassword": "2001",
    "pbxOutExtension": "5001",
    "speakerVolume": 70,
    "micVolume": 60,
    "speakerGain": 4,
    "micGain": 2,
    "logLevel": 1,
}


class _Server:
    """A single-use HTTP server running in the background."""

    def __init__(self, handler_class):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.port = self.srv.server_address[1]
        self.request_count = 0
        # (method, path) — to see which endpoint was really hit.
        self.history: list[tuple[str, str]] = []
        handler_class.fake = self
        self._t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self._t.start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _base_handler(name: str, send):
    """Builds a Handler class whose only body is `send(self)`."""
    return type(name, (BaseHTTPRequestHandler,), {
        "fake": None,
        "do_GET": lambda self: send(self),
        "do_POST": lambda self: send(self),
        "log_message": lambda self, *a: None,
        "write": _write,
    })


def _write(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
    self.send_response(code)
    self.send_header("Content-Type", ctype)
    self.send_header("Content-Length", str(len(body)))
    for k, v in (extra or {}).items():
        self.send_header(k, v)
    self.end_headers()
    self.wfile.write(body)


# ─────────────────────────────────────────────────────── KYLAND switch ────
def kyland(username="admin", password="123", login_page=False,
           mac_table=None, mac=None):
    """A KYLAND switch imitation that demands Basic Auth.

    With `login_page=True` it answers 200 with the login HTML instead of JSON
    even for CORRECT credentials — the panel must not count that as success.

    `mac_table` {mac: port} produces a `stat/macQuery` answer; without it the
    endpoint 404s (a switch that does not expose its MAC table).

    `mac` overrides the switch's OWN MAC: looking that up in a neighbour's
    table yields the inter-switch link port, so two fake switches must not
    carry the same MAC.
    """
    expected = "Basic " + base64.b64encode(
        f"{username}:{password}".encode()).decode()

    def send(self):
        self.fake.request_count += 1
        auth = self.headers.get("Authorization")
        if auth != expected:
            return self.write(401, b'{"error":"auth"}', "application/json",
                              {"WWW-Authenticate": 'Basic realm="switch"'})
        if login_page:
            return self.write(200, LOGIN_HTML, "text/html")
        path = self.path.split("?")[0]
        if path == "/stat/basicInfo":
            body = BASIC_INFO
            if mac:
                body = {"basicInfo": {**BASIC_INFO["basicInfo"],
                                      "macAddress": mac}}
            return self.write(200, json.dumps(body).encode(),
                              "application/json")
        if path == "/stat/portMode":
            return self.write(200, json.dumps(PORT_MODE).encode(),
                              "application/json")
        if path == "/stat/macQuery" and mac_table:
            # Field shape: the port sits inside portList, not at top level.
            body = {"macQuery": [{"mac": m, "portList": [{"pid": p}]}
                                 for m, p in mac_table.items()]}
            return self.write(200, json.dumps(body).encode(),
                              "application/json")
        return self.write(404, b'{"error":"missing"}', "application/json")

    return _Server(_base_handler("KylandHandler", send))


def empty_json_switch():
    """A device that answers 200 with valid JSON but NO switch identity."""
    def send(self):
        self.fake.request_count += 1
        self.write(200, json.dumps({"welcome": True}).encode(),
                   "application/json")

    return _Server(_base_handler("EmptyJsonHandler", send))


# ───────────────────────────────────────────────────────── ISAPI camera ───
def camera(username="admin", password="fake-camera-password"):
    """A Hikvision ISAPI imitation that demands Digest Auth.

    The default password is made up ON PURPOSE: a fake server's default must
    never be a real field password. Tests pass their own value
    (see test_credentials.PASSWORD).
    """
    realm, nonce = "IP Camera", "abc123nonce"

    def correct(auth: str, method: str) -> bool:
        if not auth or not auth.lower().startswith("digest "):
            return False
        fields = {}
        for part in auth[7:].split(","):
            if "=" not in part:
                continue
            k, _, v = part.partition("=")
            fields[k.strip()] = v.strip().strip('"')
        if fields.get("username") != username:
            return False
        ha1 = hashlib.md5(
            f"{username}:{realm}:{password}".encode()).hexdigest()
        ha2 = hashlib.md5(
            f"{method}:{fields.get('uri', '')}".encode()).hexdigest()
        if fields.get("qop"):
            expected = hashlib.md5(
                f"{ha1}:{fields.get('nonce')}:{fields.get('nc')}:"
                f"{fields.get('cnonce')}:{fields.get('qop')}:{ha2}"
                .encode()).hexdigest()
        else:
            expected = hashlib.md5(
                f"{ha1}:{fields.get('nonce')}:{ha2}".encode()).hexdigest()
        return fields.get("response") == expected

    def send(self):
        self.fake.request_count += 1
        if not correct(self.headers.get("Authorization", ""), self.command):
            return self.write(
                401, b"<html>401</html>", "text/html",
                {"WWW-Authenticate":
                 f'Digest realm="{realm}", nonce="{nonce}", qop="auth"'})
        path = self.path.split("?")[0]
        if path == "/ISAPI/System/deviceInfo":
            return self.write(200, DEVICE_INFO_XML, "application/xml")
        return self.write(404, b"<html>404</html>", "text/html")

    return _Server(_base_handler("CameraHandler", send))


# ──────────────────────────────────────────────── announcement device ─────
# The device's write endpoints and their required fields. Verified against
# field hardware: the main endpoint 405s on POST, every endpoint demands its
# own required set, and writing SIP reboots the device.
MODE_FIELDS = ("pttEnabled", "answerMode", "callMode", "hangupMode")
UIC_FIELDS = ("tcSpeakerGain", "tcMicGain", "tlSpeakerGain", "tlMicGain")
SIP_REQUIRED = ("pbxIp", "pbxExtension", "pbxPassword")


def announcement(settings=None, modes=None, ignore=(), new_version="1.2.6"):
    """An announcement device imitation, with read and write endpoints.

    With `modes` the device behaves like a Handset: mode fields live on the
    `system/modes` endpoint rather than the main one, and are written there.

    Fields listed in `ignore` are accepted with 200 and silently dropped —
    that is what the field device does with a field it does not know.

    `new_version`: the version the device reports after a firmware install.
    """
    state = dict(settings or ANNOUNCEMENT_SETTINGS)
    mode_state = dict(modes) if modes else None
    lock = threading.Lock()
    # The uploaded image body: a test reads which file reached which device
    # straight from here.
    uploaded: list[bytes] = []

    def clamp(incoming: dict) -> dict:
        # The device stores decimals as float32: after writing 2.4 you read
        # back 2.4000000953674316. The panel's comparison must not call that
        # "not written".
        return {k: (struct.unpack("f", struct.pack("f", v))[0]
                    if isinstance(v, float) else v)
                for k, v in incoming.items() if k not in ignore}

    def plain(self, code: int, s: str):
        # The device answers plain text; the panel must not assume JSON.
        return self.write(code, s.encode(), "text/plain")

    def read_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def missing(incoming: dict, required) -> bool:
        return any(f not in incoming for f in required)

    def send(self):
        self.fake.request_count += 1
        path = self.path.split("?")[0]
        self.fake.history.append((self.command, path))

        if self.command == "GET":
            if path == "/api/v1/system/settings":
                with lock:
                    return self.write(200, json.dumps(state).encode(),
                                      "application/json")
            if path == "/api/v1/system/modes" and mode_state is not None:
                with lock:
                    return self.write(200, json.dumps(mode_state).encode(),
                                      "application/json")
            return self.write(404, b"File not found", "text/plain")

        # The main endpoint is read-only.
        if path == "/api/v1/system/settings":
            return plain(self, 405, "Method Not Allowed")

        # Firmware upload: the body is multipart/form-data, not JSON.
        if path == "/api/v1/system/firmware":
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n)
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("multipart/form-data"):
                return plain(self, 400, "Expected multipart/form-data")
            if b'name="firmware"' not in raw:
                return plain(self, 400, "Missing firmware field")
            with lock:
                uploaded.append(raw)
                state["firmwareVersion"] = new_version
                state["uptime"] = 1             # the device rebooted
            return plain(self, 200, "Update started")

        incoming = read_body(self)
        if path == "/api/v1/audio/volume":
            with lock:
                state.update(clamp(incoming))   # a partial body is accepted
            return plain(self, 200, "Volume updated")

        if path == "/api/v1/system/modes" and mode_state is not None:
            if missing(incoming, MODE_FIELDS):
                return plain(self, 400, "Missing mode fields")
            with lock:
                mode_state.update(clamp(incoming))
            return plain(self, 200, "Modes updated successfully")

        if path == "/api/v1/uic/gains" and "tcSpeakerGain" in state:
            if missing(incoming, UIC_FIELDS):
                return plain(self, 400, "Missing UIC gain fields")
            with lock:
                state.update(clamp(incoming))
            return plain(self, 200, "UIC gains saved")

        if path == "/api/v1/sip/settings":
            if missing(incoming, SIP_REQUIRED):
                return plain(self, 400, "Missing required fields")
            with lock:
                state.update(clamp(incoming))
                state["uptime"] = 1             # rebooted
            return plain(self, 200, "SIP configuration saved. Rebooting...")

        return self.write(404, b"File not found", "text/plain")

    server = _Server(_base_handler("AnnouncementHandler", send))
    server.state = state                        # tests may read the state
    server.mode_state = mode_state
    server.uploaded = uploaded
    return server


def announcement_writes(server) -> list[str]:
    """The endpoints written to on the device — in order."""
    return [path for method, path in server.history if method == "POST"]


def silent():
    """A device that accepts the connection and never answers (times out)."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    port = s.getsockname()[1]
    stop = threading.Event()

    def loop():
        held = []
        s.settimeout(0.3)
        while not stop.is_set():
            try:
                connection, _ = s.accept()
                held.append(connection)       # deliberately never answered
            except OSError:
                continue
        for c in held:
            try:
                c.close()
            except OSError:
                pass
        s.close()

    t = threading.Thread(target=loop, daemon=True)
    t.start()

    class _Silent:
        def __init__(self):
            self.port = port

        def close(self):
            stop.set()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    return _Silent()


# ──────────────────────────────────────────────────────── DeviceMap ───────
def device_map(devices: list[dict], switch_ip="127.0.0.1",
               switch_name="Test_SW_1",
               second_switch: dict | None = None) -> dict:
    """Builds DeviceMap.json content for the tests.

    Because the IPs are 127.0.0.1 the 'n' substitution never kicks in; each
    device's port is the fake server's port (see the port patches in tests).
    """
    topology = {"Screens": None, "Switches": [{
        "Name": switch_name, "IP": switch_ip, "IsActive": True,
        "Manufacturer": "KYLAND", "TrainSet": 1,
        "Username": "admin", "Password": "secret-devicemap-password",
        "Status": {"NoError": True, "Uptime": 10},
        "Devices": devices,
    }]}
    if second_switch:
        topology["Switches"].append(second_switch)
    return topology
