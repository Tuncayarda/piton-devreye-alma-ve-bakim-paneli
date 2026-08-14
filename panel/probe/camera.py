#!/usr/bin/env python3
"""Camera / NVR reads — Hikvision ISAPI.

Endpoints and parsing match `fetch_isapi` in field_scripts/device_verify.py.

The difference: credentials come from the user, not a .env, and live only in
memory. Without one the request goes out unauthenticated, the device answers
401, and it lands in the credentials list as "waiting for access".
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth
import urllib3

from .. import settings
from ..errors import AuthError, VerificationError, classify
from .. import i18n

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _tag(root, name):
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == name:
            return (element.text or "").strip()
    return None


def _request(ip: str, path: str, credentials, timeout: float):
    auth = HTTPDigestAuth(*credentials) if credentials else None
    return requests.get(f"http://{ip}:{settings.VIDEO_PORT}/ISAPI/{path}",
                        auth=auth, timeout=timeout, verify=False)


def _xml(response):
    """Parse the reply as XML; turn credential problems into AuthError.

    Hikvision devices return 401 unauthenticated. Some firmware answers 200
    with an HTML login page instead — unparseable XML is not success either.
    """
    if (response.status_code in (401, 403)
            or "WWW-Authenticate" in response.headers):
        raise AuthError(i18n.t("error.probeAuth"))
    if response.status_code >= 400:
        raise VerificationError(
            i18n.t("error.probeHttp", code=response.status_code))
    try:
        return ET.fromstring(response.content)
    except ET.ParseError:
        content_type = response.headers.get("Content-Type", "?")
        raise VerificationError(
            i18n.t("error.probeNotXml", type=content_type))


def read(ip: str, credentials: tuple[str, str] | None = None,
         timeout: float | None = None,
         expected_ntp: str | None = None) -> dict:
    """Device identity plus network/time checks.

    A missing identity raises. The time/mask checks are optional extras: if
    they cannot be read the device still counts as read and the field is
    left empty.
    """
    limit = timeout if timeout is not None else settings.PROBE_TIMEOUT
    try:
        response = _request(ip, "System/deviceInfo", credentials, limit)
    except Exception as exc:
        raise classify(exc)

    root = _xml(response)
    version = _tag(root, "firmwareVersion")
    serial = _tag(root, "serialNumber")
    model = _tag(root, "model") or _tag(root, "deviceType")
    if not (version or serial or model):
        raise VerificationError(
            i18n.t("error.probeIsapiEmpty"))

    problems: list[str] = []
    for path, tag, expected, label in (
            ("System/time", "timeZone", settings.EXPECTED_TIMEZONE, "Saat"),
            ("System/time/ntpServers/1", "ipAddress", expected_ntp, "NTP")):
        if expected is None:
            continue
        try:
            value = _tag(_xml(_request(ip, path, credentials, limit)), tag)
            if value != expected:
                problems.append(label)
        except AuthError:
            raise
        except Exception:
            problems.append(label)

    mask = _subnet_mask(ip, credentials, limit)
    if mask is not None and mask != settings.EXPECTED_SUBNET_MASK:
        problems.append("Maske")

    return {
        "version": version or "",
        "serial": serial or "",
        "model": model or "",
        "subnetMask": mask or "",
        "networkTime": "Uygun" if not problems else ", ".join(problems),
        "raw": {"firmwareVersion": version, "serialNumber": serial,
                "model": model},
    }


def _subnet_mask(ip: str, credentials, timeout: float) -> str | None:
    """Subnet mask of the interface on the 10.x network; None if unreadable."""
    try:
        root = _xml(_request(ip, "System/Network/interfaces", credentials,
                             timeout))
    except AuthError:
        raise
    except Exception:
        return None
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "IPAddress":
            continue
        address = mask = None
        for child in element:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "ipAddress":
                address = (child.text or "").strip()
            elif tag == "subnetMask":
                mask = (child.text or "").strip()
        if address and address.startswith("10."):
            return mask
    return None
