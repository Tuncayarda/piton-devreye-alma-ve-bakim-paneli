#!/usr/bin/env python3
"""Camera / NVR reads — Hikvision ISAPI.

Endpoints and parsing match `fetch_isapi` in field_scripts/device_verify.py.

The difference: credentials come from the user, not a .env, and live only in
memory. Without one the request goes out unauthenticated, the device answers
401, and it lands in the credentials list as "waiting for access".

The network/time answer carries more than the name suggests, and
deliberately so — it is ONE column in the verification sheet. Time zone, NTP
and mask are checked here; the disk, the buzzer, the IR lamp and the third
stream are checked by panel.video_config.health, which is where the writing
side of those settings lives too. A device that records nothing is not
"verified" because its clock is right.
"""
from __future__ import annotations

import ipaddress
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
         expected_ntp: str | None = None,
         is_nvr: bool = False,
         project_span: str = "") -> dict:
    """Device identity plus the verification checks.

    A missing identity raises. The checks are extras: if one cannot be read
    the device still counts as read, and the check says it could not be read
    rather than passing.
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
            ("System/time", "timeZone", settings.EXPECTED_TIMEZONE,
             "video.checkTime"),
            ("System/time/ntpServers/1", "ipAddress", expected_ntp,
             "video.checkNtp")):
        if expected is None:
            continue
        try:
            value = _tag(_xml(_request(ip, path, credentials, limit)), tag)
            if value != expected:
                problems.append(i18n.t(label))
        except AuthError:
            raise
        except Exception:
            problems.append(i18n.t(label))

    mask = _subnet_mask(ip, credentials, limit)
    if mask and not _mask_reaches(ip, mask, project_span):
        problems.append(i18n.t("video.checkMask"))

    # The recording-side checks. Imported here rather than at module level:
    # video_config reaches back into the inventory and the credential store,
    # and this module is imported by the probe dispatcher.
    from ..video_config import health
    from ..editions import runtime as editions
    problems.extend(health.problems(ip, credentials, is_nvr=is_nvr,
                                    storage=editions.storage_checked(),
                                    timeout=limit))

    return {
        "version": version or "",
        "serial": serial or "",
        "model": model or "",
        "subnetMask": mask,
        "networkTime": (i18n.t("video.checkOk") if not problems
                        else ", ".join(problems)),
        "raw": {"firmwareVersion": version, "serialNumber": serial,
                "model": model},
    }


def _mask_reaches(ip: str, mask: str, project_span: str) -> bool:
    """Is this device's own network wide enough for the project?

    NOT "does it equal a constant". No constant is right: Yatakli's devices
    fit in a /25 and Gaziray's need a /21, while the CCTV commissioning
    scripts write a /8 to both — all three masks work, and a check demanding
    one exact value calls two of them a fault.

    What matters is whether the device can reach the rest of the project, so
    the span comes from the DeviceMap (`Inventory.span`) and the question is
    containment. A Gaziray camera left on a /24 fails this and should: it
    cannot see the other cars, the broker, or the panel.

    Unanswerable questions pass. An empty span means the caller had no
    inventory to compute one from, and a device is not marked faulty for a
    check that was never made.
    """
    if not project_span:
        return True
    try:
        held = ipaddress.ip_network(f"{ip}/{mask}", strict=False)
        return ipaddress.ip_network(project_span).subnet_of(held)
    except ValueError:
        return True


def _subnet_mask(ip: str, credentials, timeout: float) -> str:
    """The mask of the interface holding this address; "" when unreadable.

    The same lookup the WRITE path uses (video_config.isapi.interface_mask),
    and deliberately so: a scan that reports one interface's mask while a run
    writes another's would flag a device the panel had just configured.
    """
    from ..video_config import isapi as video_isapi
    try:
        root = _xml(_request(ip, "System/Network/interfaces", credentials,
                             timeout))
    except AuthError:
        raise
    except Exception:
        return ""
    return video_isapi.interface_mask(root, ip)
