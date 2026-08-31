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

from .. import settings
from ..errors import AuthError, VerificationError, classify
from .. import i18n
# The transport is `panel.video_config.isapi` — THE one ISAPI client, shared
# with the write side, so the session (pooled, proxy-free: trust_env=False),
# the digest handling and the "401/403/WWW-Authenticate means sign in" rule
# cannot drift between a scan and a configuration run. This module keeps only
# the READ semantics: a scan treats an HTTP error or a non-XML page as its
# own verification failure, where the write side's `read()` treats an absent
# endpoint as "the device has no such resource".
from ..video_config import isapi

_tag = isapi.first


def _request(ip: str, path: str, credentials, timeout: float):
    return isapi.request("GET", ip, path, credentials, timeout=timeout)


def _xml(response):
    """Parse the reply as XML; turn credential problems into AuthError.

    Hikvision devices return 401 unauthenticated. Some firmware answers 200
    with an HTML login page instead — unparseable XML is not success either.
    """
    isapi.check_auth(response)
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

    # The recording-side checks live beside the writing side of the same
    # settings (panel.video_config.health), so the screen and the scan read
    # one truth about the disk, the buzzer, the IR lamp and the third stream.
    from ..editions import runtime as editions
    from ..video_config import health
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

    NOT "does it equal a constant". No constant is right: Yatakli is one /24
    and Gaziray a /16, while the CCTV commissioning scripts write a /8 to
    both — all three masks work, and a check demanding one exact value calls
    two of them a fault.

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
    try:
        root = _xml(_request(ip, "System/Network/interfaces", credentials,
                             timeout))
    except AuthError:
        raise
    except Exception:
        return ""
    return isapi.interface_mask(root, ip)
