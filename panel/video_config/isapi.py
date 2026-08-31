#!/usr/bin/env python3
"""THE ISAPI transport — every camera / NVR request goes through here.

`panel.probe.camera` reads a device's identity over this module and the
procedures in `camera.py` / `nvr.py` write through it, so the rules are the
same on both sides (the same reason `panel.switch.client` is the one switch
client):

  · digest authentication, 401/403 (or a WWW-Authenticate header) is an
    AuthError — the fix is a password, not a cable;
  · HTTP 200 is not success on its own. Hikvision answers 200 with a
    ResponseStatus body whose statusCode says the request was refused, so
    every write goes through `ok()` (the field script's `isapi_ok`);
  · a reply that will not parse as XML is not success either.

The endpoints themselves are listed in `panel/video_config/camera.py` and
`nvr.py`, next to the procedure that uses them.
"""
from __future__ import annotations

import threading
import xml.etree.ElementTree as ET

import requests
import urllib3
from requests.adapters import HTTPAdapter
from requests.auth import HTTPDigestAuth

from .. import clock, i18n, settings
from ..errors import AuthError, VerificationError, classify

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _create_session(pool_size: int = 8) -> requests.Session:
    """One pooled session for all camera and recorder traffic.

    `trust_env = False` is the important line, exactly as it is for the
    switch client (panel/switch/client.py): a camera on 10.1.1.x is on the
    cable in front of the operator, and routing its requests through
    whatever HTTP_PROXY the machine happens to have set makes every video
    device unreachable for a reason nothing on screen can explain — while
    the switch screens, which already ignored the proxy, keep working.

    The pool is what makes a device read cheap: one camera read is about
    seven GETs, and without a session each one paid a fresh TCP handshake.
    The pool is small because a run talks to a handful of devices at a time,
    not a /24. `max_retries=0` — the procedures decide their own retries
    (see `wait_until_back`).
    """
    session = requests.Session()
    session.trust_env = False
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size,
                          max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_SESSION = _create_session()

# One digest handler per (device, account), shared across requests. Not a
# micro-optimisation: HTTPDigestAuth remembers the device's challenge, so a
# reused handler authenticates pre-emptively and a read stops paying a 401
# round trip per GET (fourteen requests for seven reads). The state inside
# is thread-local, so sharing a handler between worker threads is safe; the
# key includes the address because nonces belong to one device.
_AUTH_HANDLERS: dict[tuple[str, str, str], HTTPDigestAuth] = {}
_AUTH_GUARD = threading.Lock()


def reset() -> None:
    """Forget every cached digest handler, and the session's cookies with
    them. Called when the in-memory credentials go (shutdown, "forget all",
    a project switch): the handlers hold the passwords they were built
    from, and a store that outlived `credentials.forget_all()` would keep
    camera passwords in memory that the operator believes are gone. The
    session is rebuilt too — per-host cookies a device set under the old
    account must not ride into the new one.
    """
    global _SESSION
    with _AUTH_GUARD:
        _AUTH_HANDLERS.clear()
        old_session, _SESSION = _SESSION, _create_session()
    try:
        old_session.close()
    except Exception:
        pass


def _auth(ip: str, credentials) -> HTTPDigestAuth | None:
    if not credentials:
        return None
    username, password = credentials
    key = (ip, username, password)
    with _AUTH_GUARD:
        handler = _AUTH_HANDLERS.get(key)
        if handler is None:
            handler = _AUTH_HANDLERS[key] = HTTPDigestAuth(username, password)
        return handler

# Default for camera and recorder ISAPI resources whose bodies are XML.
HEADERS = {"Content-Type": "application/xml; charset=UTF-8"}

# Older recorder firmware uses this content type for its InputProxy channel
# editor even though the request body is XML.  It is also what the recorder's
# own web UI and the field-proven NVR script send.  Keep it endpoint-specific:
# cameras and the NVR's other ISAPI resources continue to use XML.
FORM_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

# Words that mean "this hdd/channel is not usable as it stands". Kept here
# because both the camera and the NVR storage step share them.
UNUSABLE_STORAGE = ("unformatted", "uninitialized")

# How long a Hikvision device takes to answer again after it has been told to
# restart — or after a network change, which re-initialises the interface and
# on many models reboots the whole device. The field script waits 15 seconds
# and then retries for two and a half minutes; the same budget is kept here.
# Tests shorten them.
REBOOT_DELAY = 15.0
REBOOT_ATTEMPTS = 30
REBOOT_INTERVAL = 5.0


def no_report(_text, _state="done") -> None:
    """The default step reporter.

    Both procedures narrate what they are doing so the queue can show it
    under the device's row. A run nobody is watching — a test, an API call —
    still has to work, so the default swallows the lines.
    """


def url(ip: str, path: str) -> str:
    return f"http://{ip}:{settings.VIDEO_PORT}/ISAPI/{path}"


def request(method: str, ip: str, path: str, credentials, *, data=None,
            timeout: float | None = None,
            headers: dict[str, str] | None = None) -> requests.Response:
    """One ISAPI request. Network problems come back as DeviceError."""
    try:
        return _SESSION.request(
            method, url(ip, path), auth=_auth(ip, credentials), data=data,
            headers=headers or HEADERS,
            timeout=timeout if timeout is not None else settings.PROBE_TIMEOUT,
            verify=False)
    except Exception as exc:
        raise classify(exc)


def check_auth(response: requests.Response) -> None:
    """The one rule for "this device wants a password".

    Shared with the read side (`panel.probe.camera`): a scan and a
    configuration run must not disagree about what counts as locked.
    """
    if (response.status_code in (401, 403)
            or "WWW-Authenticate" in response.headers):
        raise AuthError(i18n.t("error.probeAuth"))


def ok(response: requests.Response) -> bool:
    """Did the device accept the write?

    Verbatim from the field script's `isapi_ok`: a 200 whose body carries a
    ResponseStatus counts only when that status says OK.
    """
    check_auth(response)
    if response.status_code not in (200, 201):
        return False
    text = (response.text or "").strip()
    if (not text or "<subStatusCode>ok" in text
            or "<statusString>OK" in text or "<statusCode>1<" in text):
        return True
    return "<statusCode>" not in text


def read(ip: str, path: str, credentials,
         timeout: float | None = None) -> ET.Element | None:
    """GET and parse. None means "this device has no such endpoint".

    An absent endpoint is normal (a camera without an SD card slot answers
    404 on the storage list) and must not fail the whole read; a credential
    problem is raised, because every following request would fail the same
    way and "no SD card" would be a lie.
    """
    response = request("GET", ip, path, credentials, timeout=timeout)
    check_auth(response)
    if response.status_code >= 400:
        return None
    try:
        return ET.fromstring(response.content)
    except ET.ParseError:
        return None


def _response_detail(response: requests.Response) -> str:
    """The safe part of a Hikvision ResponseStatus error.

    Never return the raw response: a device can echo request data and an NVR
    channel request contains the camera password.  The two documented status
    fields are enough to distinguish malformed XML, invalid content and an
    unsupported operation.
    """
    try:
        root = ET.fromstring(response.content)
    except (ET.ParseError, TypeError, ValueError):
        return ""
    details = []
    for name in ("statusString", "subStatusCode"):
        value = first(root, name)
        # Collapse control/whitespace and cap device-controlled text before it
        # reaches a job row in the UI.
        value = " ".join(str(value or "").split())[:120]
        if not value or value.lower() == "ok":
            continue
        if not any(value.lower() == item.lower() for item in details):
            details.append(value)
    return " / ".join(details)


def write(ip: str, path: str, credentials, body: str, *, method: str = "PUT",
          timeout: float | None = None,
          headers: dict[str, str] | None = None) -> None:
    """PUT/POST/DELETE a body and raise unless the device accepted it."""
    response = request(method, ip, path, credentials,
                       data=body.encode("utf-8"), timeout=timeout,
                       headers=headers)
    if not ok(response):
        detail = _response_detail(response)
        key = "error.isapiRefusedDetailed" if detail else "error.isapiRefused"
        raise VerificationError(
            i18n.t(key, path=path, code=response.status_code, detail=detail))


def tag_name(element) -> str:
    """Local tag name — ISAPI replies are namespaced, inconsistently."""
    return element.tag.rsplit("}", 1)[-1]


def first(root, name: str) -> str | None:
    if root is None:
        return None
    for element in root.iter():
        if tag_name(element) == name:
            return (element.text or "").strip()
    return None


def blocks(root, name: str) -> list:
    if root is None:
        return []
    return [element for element in root.iter() if tag_name(element) == name]


def child_text(element, name: str) -> str:
    for child in element:
        if tag_name(child) == name:
            return (child.text or "").strip()
    return ""


def interface_mask(root, ip: str) -> str:
    """The subnet mask of the interface holding `ip`; "" when there is none.

    EXACT match, with no fallback to "some other interface". A recorder can
    have several, and reporting one NIC's mask under another's address is
    how a device that is correctly configured reads as wrong — or the other
    way round, which is worse.

    Nothing here writes this value; see the subnetMask field in
    panel.config_sync.fields for why.
    """
    for address in blocks(root, "IPAddress"):
        if child_text(address, "ipAddress") == ip:
            return child_text(address, "subnetMask")
    return ""


def wait_until_back(ip: str, credentials) -> bool:
    """Wait for a device to answer again after a restart."""
    clock.sleep(REBOOT_DELAY)
    for _attempt in range(REBOOT_ATTEMPTS):
        try:
            if read(ip, "System/deviceInfo", credentials) is not None:
                return True
        except Exception:
            pass
        clock.sleep(REBOOT_INTERVAL)
    return False


def storage_status(root) -> tuple[str, list[tuple[str, str]]]:
    """(summary for the screen, [(hdd id, status)]).

    A device with no storage at all is not a fault: most cameras in the set
    have no SD card fitted.
    """
    disks = [(child_text(hdd, "id"), child_text(hdd, "status").lower())
             for hdd in blocks(root, "hdd") if child_text(hdd, "id")]
    if not disks:
        return i18n.t("video.noStorage"), []
    return ", ".join(f"{hid}: {status or '?'}" for hid, status in disks), disks


def needs_format(status: str) -> bool:
    """The field script's rule: only an unformatted or faulty disk is
    formatted. A disk that is merely full or in use is left alone — the
    panel must not wipe recordings because a setting was applied."""
    text = (status or "").lower()
    return text in UNUSABLE_STORAGE or "error" in text
