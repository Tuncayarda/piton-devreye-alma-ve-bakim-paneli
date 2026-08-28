#!/usr/bin/env python3
"""Fake devices for the tests.

This is TEST scaffolding, not part of the application: the panel never
creates, shows or connects to a fake device.

They imitate the real hardware:
  · KYLAND switch — Basic Auth, /stat/basicInfo, JSON
  · a switch that answers with a login page — HTTP 200 + HTML (not a success)
  · Hikvision camera — Digest Auth, /ISAPI/System/deviceInfo, XML
  · Hikvision camera / NVR with the WRITE side of ISAPI (video_camera,
    video_nvr): time, streams, storage, input channels, triggers
  · announcement device — credential-less JSON /api/v1/system/settings
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

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

# Realistic portMode rows. The extra fields are not decoration: every write
# to this endpoint rewrites the WHOLE table from what was read (see
# panel.switch.ports), so a row missing `linkType` or `maxLength` would let a
# test pass while the real switch had those columns reset.
def _port_mode_row(pid: int, kind: str = "GE") -> dict:
    return {"pid": pid, "type": kind, "adminStat": 1,
            "linkStat": "up" if pid < 3 else "down", "linktext": "1000M",
            "linkType": "0", "autoNego": 1, "speed": "1000",
            "duplex": 1, "flowCtrl": 0, "maxLength": "1522"}


PORT_MODE = {"portMode": [_port_mode_row(i) for i in range(1, 25)]}

# The PoE tables. `poeStatus` is the one that may be absent by model, so the
# fake can be built without it (see `kyland(poe_status=False)`).
POE_PORT = {"poePort": [
    {"pid": i, "poeMode": "1", "priority": "0", "maxPower": "154"}
    for i in range(1, 25)
]}
POE_STATUS = {"poeStatus": [
    # Ten times the real figure, exactly as the hardware reports it: 123 here
    # must reach the panel as 12.3 W.
    {"pid": i, "portStatus": "on" if i < 3 else "off",
     "powerUsed": "123" if i < 3 else "0"}
    for i in range(1, 25)
]}
VLAN_INTF_IP = {"vlanIntfIp": {"method": "manual", "addr": "10.1.1.2",
                               "netmaskLen": "24", "mtu": "1500"}}
SUCCESS = {"retCode": ["success"]}

LOGIN_HTML = (b"<!DOCTYPE html><html><head><title>Login</title></head>"
              b"<body><form>Username<input name=user></form></body></html>")

# NOT a switch: a web interface that answers every path with its own page
# rather than a 404. The PISCU is one, and it shares the network and the port
# with the switches, so a discovery sweep meets it. It has to be told apart
# from LOGIN_HTML above — both are 200 text/html — and the thing that tells
# them apart is that this one has nothing to sign in with.
WEB_UI_HTML = (b"<!DOCTYPE html><html><head><title>PISCU</title></head>"
               b"<body><div id=root><h1>PISCU</h1>"
               b"<p>Loading the interface.</p></div></body></html>")

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
        # Content-Type only; never retain Authorization or request bodies here.
        self.request_content_types: list[tuple[str, str, str]] = []
        # (endpoint, parsed form) for the fakes that record writes. Form
        # fields only — an Authorization header never reaches this list.
        self.posts: list[tuple[str, dict]] = []
        handler_class.fake = self
        # POLL FAST, so closing is quick. `serve_forever` defaults to a
        # half-second poll and `shutdown()` blocks until the loop next comes
        # round — so every fake server cost about half a second to close,
        # and this suite closes a few hundred of them. That was the single
        # largest cost in the run: 9.7 of test_video_config's 9.8 seconds
        # were spent here, waiting for servers that had nothing left to do.
        # The tighter beat is only paid while a server is actually up.
        self._t = threading.Thread(
            target=self.srv.serve_forever, kwargs={"poll_interval": 0.01},
            daemon=True)
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
        # ISAPI writes are PUTs; without this they would 501 and every
        # video test would pass for the wrong reason.
        "do_PUT": lambda self: send(self),
        "do_DELETE": lambda self: send(self),
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


# The realm and nonce a Hikvision device challenges with. Fixed values: the
# tests are about the panel's behaviour, not about digest itself.
DIGEST_REALM, DIGEST_NONCE = "IP Camera", "abc123nonce"
DIGEST_CHALLENGE = (f'Digest realm="{DIGEST_REALM}", nonce="{DIGEST_NONCE}", '
                    'qop="auth"')


def _digest_check(username: str, password: str):
    """A callable that says whether an Authorization header is correct."""

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
            f"{username}:{DIGEST_REALM}:{password}".encode()).hexdigest()
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

    return correct


# ─────────────────────────────────────────────────────── KYLAND switch ────
def kyland(username="admin", password="123", login_page=False,
           mac_table=None, mac=None, poe_status=True, uplinks=0):
    """A KYLAND switch imitation that demands Basic Auth.

    With `login_page=True` it answers 200 with the login HTML instead of JSON
    even for CORRECT credentials — the panel must not count that as success.

    `mac_table` {mac: port} produces a `stat/macQuery` answer; without it the
    endpoint 404s (a switch that does not expose its MAC table).

    `mac` overrides the switch's OWN MAC: looking that up in a neighbour's
    table yields the inter-switch link port, so two fake switches must not
    carry the same MAC.

    `poe_status=False` drops `stat/poeStatus`, which genuinely does not exist
    on every model — the port list must still come back, without live power.

    `uplinks` adds that many ports to portMode that are NOT in the PoE table.
    The real SICOM3028GPT is 24 PoE + 4 uplink, and the uplinks are what the
    front panel draws with the eight-pin connector — a fake without them
    leaves half the faceplate untested.

    EVERY POST BODY IS KEPT, parsed, in `server.posts` as
    (endpoint, {field: value}). The switch rewrites whole tables, so what a
    test needs to check is not "did a write happen" but "did all 24 ports go
    out with only the intended one changed".
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
        if self.command == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode() if length else ""
            self.fake.posts.append(
                (path.lstrip("/"),
                 {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True)
                  .items()}))
            if path in ("/stat/poePort", "/stat/portMode", "/stat/vlanIntfIp",
                        "/stat/configSave", "/stat/reboot", "/stat/reset"):
                return self.write(200, json.dumps(SUCCESS).encode(),
                                  "application/json")
            return self.write(404, b'{"error":"missing"}', "application/json")
        if path == "/stat/basicInfo":
            body = BASIC_INFO
            if mac:
                body = {"basicInfo": {**BASIC_INFO["basicInfo"],
                                      "macAddress": mac}}
            return self.write(200, json.dumps(body).encode(),
                              "application/json")
        if path == "/stat/portMode":
            body = PORT_MODE
            if uplinks:
                body = {"portMode": PORT_MODE["portMode"] + [
                    _port_mode_row(24 + n, "XGE")
                    for n in range(1, uplinks + 1)]}
            return self.write(200, json.dumps(body).encode(),
                              "application/json")
        if path == "/stat/poePort":
            return self.write(200, json.dumps(POE_PORT).encode(),
                              "application/json")
        if path == "/stat/poeStatus" and poe_status:
            return self.write(200, json.dumps(POE_STATUS).encode(),
                              "application/json")
        if path == "/stat/vlanIntfIp":
            return self.write(200, json.dumps(VLAN_INTF_IP).encode(),
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


def web_ui():
    """A web interface that answers EVERY path with 200 and its own page.

    Not a switch and not asking to be signed in to — but it shares the network
    and port 80 with the switches, so a discovery sweep knocks on it. See
    WEB_UI_HTML and `panel.switch.client.looks_like_login_page`.
    """
    def send(self):
        self.fake.request_count += 1
        self.write(200, WEB_UI_HTML, "text/html; charset=utf-8")

    return _Server(_base_handler("WebUiHandler", send))


# ───────────────────────────────────────────────────────── ISAPI camera ───
def camera(username="admin", password="fake-camera-password"):
    """A Hikvision ISAPI imitation that demands Digest Auth.

    The default password is made up ON PURPOSE: a fake server's default must
    never be a real field password. Tests pass their own value
    (see test_credentials.PASSWORD).
    """
    correct = _digest_check(username, password)

    def send(self):
        self.fake.request_count += 1
        if not correct(self.headers.get("Authorization", ""), self.command):
            return self.write(401, b"<html>401</html>", "text/html",
                              {"WWW-Authenticate": DIGEST_CHALLENGE})
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


# ─────────────────────────────────────────── Hikvision camera and NVR ────
# The WRITE side of ISAPI, which `camera()` above does not cover. Details
# that the panel's behaviour depends on, and which are therefore imitated:
#   · a write is a PUT — a new NVR input channel is the one POST;
#   · the answer to a write is a ResponseStatus body, not a bare 200;
#   · channel 103 does not exist while the third stream is disabled. That is
#     the entire reason the panel enables it and waits out a reboot;
#   · System/Network/interfaces is readable and NOT writable here on purpose:
#     a test asserts the panel never tries to write an address or a mask.
OK_XML = (b'<?xml version="1.0" encoding="UTF-8"?><ResponseStatus>'
          b'<statusCode>1</statusCode><statusString>OK</statusString>'
          b'</ResponseStatus>')
BAD_XML_CONTENT = (
    b'<?xml version="1.0" encoding="UTF-8"?><ResponseStatus>'
    b'<statusCode>6</statusCode>'
    b'<statusString>Invalid XML Content</statusString>'
    b'<subStatusCode>badXmlContent</subStatusCode>'
    b'<password>must-not-leak</password></ResponseStatus>')

IFACE_ADDRESS_PATH = "/ISAPI/System/Network/interfaces/1/ipAddress"
FORMAT_PATH = re.compile(r"^/ISAPI/ContentMgmt/Storage/hdd/([^/]+)/format$")
PROXY_PATH = re.compile(r"^/ISAPI/ContentMgmt/InputProxy/channels/(\d+)$")
TRIGGER_PATH = re.compile(r"^/ISAPI/Event/triggers/([\w-]+)$")
STREAM_PATH = re.compile(r"^/ISAPI/Streaming/channels/(\d+)$")


def _value(body: str, name: str, default: str = "") -> str:
    found = re.search(rf"<{name}>(.*?)</{name}>", body, re.DOTALL)
    return found.group(1).strip() if found else default


def _inner(body: str, name: str) -> str:
    found = re.search(rf"<{name}>(.*?)</{name}>", body, re.DOTALL)
    return found.group(1) if found else ""


def _beep_trigger(name: str) -> str:
    """A trigger that sounds the buzzer, as the NVR ships it."""
    return (f"<EventTrigger><id>{name}</id><eventType>{name}</eventType>"
            "<EventTriggerNotificationList>"
            "<EventTriggerNotification><id>beep</id>"
            "<notificationMethod>beep</notificationMethod>"
            "</EventTriggerNotification>"
            "<EventTriggerNotification><id>record</id>"
            "<notificationMethod>record</notificationMethod>"
            "</EventTriggerNotification>"
            "</EventTriggerNotificationList></EventTrigger>")


def _video_common(state, path, command, body):
    """The endpoints a camera and an NVR answer identically.

    (status, xml) when handled, None when the path belongs to one of them
    alone — or to nothing at all.
    """
    if command == "GET":
        if path == "/ISAPI/System/deviceInfo":
            return 200, DEVICE_INFO_XML
        if path == "/ISAPI/System/time":
            return 200, (f"<Time><timeMode>NTP</timeMode>"
                         f"<timeZone>{state['timezone']}</timeZone>"
                         f"</Time>").encode()
        if path == "/ISAPI/System/time/ntpServers/1":
            return 200, (f"<NTPServer><id>1</id>"
                         f"<addressingFormatType>ipaddress"
                         f"</addressingFormatType>"
                         f"<ipAddress>{state['ntp']}</ipAddress>"
                         f"</NTPServer>").encode()
        if path == "/ISAPI/System/Network/interfaces":
            return 200, (f"<NetworkInterfaceList><NetworkInterface><id>1</id>"
                         f"<IPAddress><ipVersion>v4</ipVersion>"
                         f"<ipAddress>{state['address']}</ipAddress>"
                         f"<subnetMask>{state['mask']}</subnetMask>"
                         f"<DefaultGateway><ipAddress>{state['gateway']}"
                         f"</ipAddress></DefaultGateway>"
                         f"</IPAddress></NetworkInterface>"
                         f"</NetworkInterfaceList>").encode()
        if path == IFACE_ADDRESS_PATH:
            return 200, (f"<IPAddress><ipVersion>v4</ipVersion>"
                         f"<ipAddress>{state['address']}</ipAddress>"
                         f"<subnetMask>{state['mask']}</subnetMask>"
                         f"<DefaultGateway><ipAddress>{state['gateway']}"
                         f"</ipAddress></DefaultGateway></IPAddress>").encode()
        if path == "/ISAPI/ContentMgmt/Storage/hdd":
            if not state["hdd"]:
                return 404, b"<html>404</html>"
            disks = "".join(
                f"<hdd><id>{number}</id><status>{status}</status></hdd>"
                for number, status in state["hdd"].items())
            return 200, f"<hddList>{disks}</hddList>".encode()
        return None

    if path == "/ISAPI/System/time":
        state["timezone"] = _value(body, "timeZone")
        return 200, OK_XML
    if path == "/ISAPI/System/time/ntpServers/1":
        state["ntp"] = _value(body, "ipAddress")
        return 200, OK_XML
    if path == IFACE_ADDRESS_PATH:
        state["mask"] = _value(body, "subnetMask")
        # The gateway and the address must survive the write: the panel sends
        # the block back as it came, with one value replaced.
        state["gateway"] = _value(_inner(body, "DefaultGateway"), "ipAddress")
        state["address"] = _value(body, "ipAddress")
        return 200, OK_XML
    if path == "/ISAPI/System/reboot":
        state["reboots"] += 1
        return 200, OK_XML
    formatting = FORMAT_PATH.match(path)
    if formatting:
        state["hdd"][formatting.group(1)] = "ok"
        return 200, OK_XML
    return None


def _video_handler(name: str, state, extra):
    """Wire a state dict and an endpoint table into a running server."""
    correct = _digest_check(state["username"], state["password"])

    def send(self):
        self.fake.request_count += 1
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        # The body is read even on a 401: it is already on the wire, and
        # leaving it there desynchronises the next request on the socket.
        body = (self.rfile.read(length) or b"").decode("utf-8", "replace")
        if not correct(self.headers.get("Authorization", ""), self.command):
            return self.write(401, b"<html>401</html>", "text/html",
                              {"WWW-Authenticate": DIGEST_CHALLENGE})
        self.fake.history.append((self.command, path))
        content_type = self.headers.get("Content-Type", "")
        self.fake.request_content_types.append(
            (self.command, path, content_type))
        if (self.command in ("PUT", "POST", "DELETE")
                and path.startswith(
                    "/ISAPI/ContentMgmt/InputProxy/channels")
                and not content_type.lower().startswith(
                    "application/x-www-form-urlencoded")):
            return self.write(400, BAD_XML_CONTENT, "application/xml")
        answer = (_video_common(state, path, self.command, body)
                  or extra(state, path, self.command, body))
        if answer is None:
            return self.write(404, b"<html>404</html>", "text/html")
        code, payload = answer
        return self.write(code, payload, "application/xml")

    server = _Server(_base_handler(name, send))
    server.state = state
    return server


def video_camera(username="admin", password="fake-camera-password",
                 third_stream=False, ir="auto", hdd=None,
                 channel_name="Camera 01", audio="true"):
    """A Hikvision camera that can be configured, not just read."""
    state = {
        "username": username, "password": password,
        # The tests reach the device on 127.0.0.1, so that is the address
        # its interface reports: the mask is written to the interface that
        # holds the device's OWN address and to no other.
        "timezone": "CST+2:00:00", "ntp": "", "address": "127.0.0.1",
        "gateway": "10.1.1.1",
        "mask": "255.0.0.0", "ir": ir, "third": bool(third_stream),
        "hdd": dict(hdd if hdd is not None else {"1": "unformatted"}),
        "reboots": 0,
        "channels": {"101": {"name": channel_name, "audio": audio,
                             "w": "1280", "h": "720"}},
    }

    def channel_xml(number: str) -> bytes:
        channel = state["channels"].get(number) or {
            "name": "", "audio": "false", "w": "", "h": ""}
        return (f"<StreamingChannel><id>{number}</id>"
                f"<channelName>{channel['name']}</channelName>"
                f"<enabled>true</enabled>"
                f"<Audio><enabled>{channel['audio']}</enabled></Audio>"
                f"<Video><videoResolutionWidth>{channel['w']}"
                f"</videoResolutionWidth><videoResolutionHeight>"
                f"{channel['h']}</videoResolutionHeight></Video>"
                f"</StreamingChannel>").encode()

    def extra(state, path, command, body):
        stream = STREAM_PATH.match(path)
        if command == "GET":
            if path == "/ISAPI/System/Hardware":
                return 200, (f"<HardwareService><IrLightSwitch>"
                             f"<mode>{state['ir']}</mode></IrLightSwitch>"
                             f"</HardwareService>").encode()
            if path == "/ISAPI/System/Software/channels/1":
                return 200, (f"<SoftwareService><ThirdStream><enabled>"
                             f"{'true' if state['third'] else 'false'}"
                             f"</enabled></ThirdStream>"
                             f"</SoftwareService>").encode()
            if stream:
                if stream.group(1) == "103" and not state["third"]:
                    return 404, b"<html>404</html>"
                return 200, channel_xml(stream.group(1))
            return None

        if path == "/ISAPI/System/Hardware":
            state["ir"] = _value(body, "mode")
            return 200, OK_XML
        if path == "/ISAPI/System/Software/channels/1":
            state["third"] = _value(body, "enabled") == "true"
            return 200, OK_XML
        if stream:
            number = stream.group(1)
            # Refusing 103 while the third stream is off is what the real
            # camera does, and what the panel's reboot dance exists for.
            if number == "103" and not state["third"]:
                return 404, b"<html>404</html>"
            state["channels"][number] = {
                "name": _value(body, "channelName"),
                "audio": _value(_inner(body, "Audio"), "enabled"),
                "w": _value(body, "videoResolutionWidth"),
                "h": _value(body, "videoResolutionHeight"),
            }
            return 200, OK_XML
        return None

    return _video_handler("VideoCameraHandler", state, extra)


def video_nvr(username="admin", password="fake-camera-password",
              channels=None, hdd=None, triggers=2, list_methods=True,
              reject_channel=None, ignore_channel=None,
              channel_list_error=False):
    """A Hikvision NVR: input channels, triggers, disk.

    `list_methods=False` imitates the firmware whose trigger LIST answers
    with ids alone. The buzzer is still armed on it; the only way to see
    that is to ask the beeping triggers by name.
    """
    state = {
        "username": username, "password": password,
        "timezone": "CST+2:00:00", "ntp": "", "address": "127.0.0.1",
        "gateway": "10.1.1.1",
        "mask": "255.0.0.0", "reboots": 0,
        "hdd": dict(hdd if hdd is not None else {"1": "ok"}),
        "channels": dict(channels or {}),
        # `diskerror` and `diskfull` are the two an NVR beeps on; the field
        # script asks for them by name when the list says nothing.
        "triggers": {name: _beep_trigger(name)
                     for name in ["diskerror", "diskfull"][:triggers]},
    }

    def channel_list() -> bytes:
        root = ET.Element("InputProxyChannelList")
        for number, (name, ip) in sorted(state["channels"].items()):
            channel = ET.SubElement(root, "InputProxyChannel")
            ET.SubElement(channel, "id").text = str(number)
            ET.SubElement(channel, "name").text = str(name)
            source = ET.SubElement(channel, "sourceInputPortDescriptor")
            ET.SubElement(source, "ipAddress").text = str(ip)
            ET.SubElement(source, "managePortNo").text = "8000"
        return ET.tostring(root, encoding="utf-8")

    def channel_body(body: str) -> tuple[int, str, str]:
        root = ET.fromstring(body)

        def text(name: str) -> str:
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] == name:
                    return (element.text or "").strip()
            return ""

        return int(text("id")), text("name"), text("ipAddress")

    def store(body: str) -> int:
        number, name, ip = channel_body(body)
        if not name and number in state["channels"]:
            # The old NVR's update body has no <name>; PUT preserves it.
            name = state["channels"][number][0]
        state["channels"][number] = (name, ip)
        return number

    def extra(state, path, command, body):
        trigger = TRIGGER_PATH.match(path)
        if command == "GET":
            if path == "/ISAPI/ContentMgmt/InputProxy/channels":
                if channel_list_error:
                    return 500, b"<html>channel list unavailable</html>"
                return 200, channel_list()
            if path == "/ISAPI/Event/triggers":
                bodies = state["triggers"].values()
                if not list_methods:
                    bodies = [re.sub(r"<EventTriggerNotificationList>.*?"
                                     r"</EventTriggerNotificationList>", "",
                                     body, flags=re.DOTALL)
                              for body in bodies]
                return 200, ("<EventTriggerList>" + "".join(bodies)
                             + "</EventTriggerList>").encode()
            if trigger and trigger.group(1) in state["triggers"]:
                return 200, state["triggers"][trigger.group(1)].encode()
            return None

        proxy = PROXY_PATH.match(path)
        if (command == "POST"
                and path == "/ISAPI/ContentMgmt/InputProxy/channels"):
            number, _name, _ip = channel_body(body)
            if number == reject_channel:
                return 400, BAD_XML_CONTENT
            if number != ignore_channel:
                store(body)
            return 200, OK_XML
        if proxy and command == "PUT":
            number, name, _ip = channel_body(body)
            if name:
                # Captures the live old-firmware web UI contract: adding a
                # channel carries its name; updating one must omit it.
                return 400, BAD_XML_CONTENT
            if number != int(proxy.group(1)):
                return 400, BAD_XML_CONTENT
            if number == reject_channel:
                return 400, BAD_XML_CONTENT
            if number != ignore_channel:
                store(body)
            return 200, OK_XML
        if proxy and command == "DELETE":
            state["channels"].pop(int(proxy.group(1)), None)
            return 200, OK_XML
        if trigger and trigger.group(1) in state["triggers"]:
            state["triggers"][trigger.group(1)] = body
            return 200, OK_XML
        return None

    return _video_handler("VideoNvrHandler", state, extra)


def video_writes(server) -> list[str]:
    """The paths written to on a video device — in order."""
    return [path for method, path in server.history
            if method in ("PUT", "POST", "DELETE")]


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
