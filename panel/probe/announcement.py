#!/usr/bin/env python3
"""Announcement equipment — Amplifier / Handset / Intercom / UIC.

Plain /api/v1 HTTP API. The main endpoint is the one intercom_ip_assign.py
uses; the extra endpoints are read only when present and never break success.
"""
from __future__ import annotations

import requests

from .. import settings
from ..errors import AuthError, VerificationError, classify
from . import fields
from .. import i18n

# Proxy-free, like every other device transport in this panel (see
# panel/switch/client.py on why trust_env=False is the important line): an
# HTTP_PROXY set on the machine must not route traffic for a device that is
# on the cable in front of the operator.
_SESSION = requests.Session()
_SESSION.trust_env = False

# The verified endpoint every announcement device serves.
MAIN_ENDPOINT = "system/settings"
# Extras vary by device type. A Handset exposes its gain fields under
# `system/modes`; an absent endpoint returns 404 and is skipped.
EXTRA_ENDPOINTS = ("system/modes", "system/info", "system/status",
                   "system/sip", "system/audio", "system/network")


def read(ip: str, credentials=None, timeout: float | None = None,
         extra_endpoints: tuple | None = None) -> dict:
    """Read a device's settings.

    Without `extra_endpoints` every known extra is tried — that is how a scan
    works, since which firmware serves what is unknown. Callers that know
    which endpoint they need should narrow it: waiting for an absent endpoint
    to 404 slows the read down for nothing.
    """
    limit = timeout if timeout is not None else settings.PROBE_TIMEOUT
    base = f"http://{ip}:{settings.ANNOUNCEMENT_PORT}/api/v1"
    auth = tuple(credentials) if credentials else None

    try:
        response = _SESSION.get(f"{base}/{MAIN_ENDPOINT}", timeout=limit,
                                auth=auth)
    except Exception as exc:
        raise classify(exc)
    if (response.status_code in (401, 403)
            or "WWW-Authenticate" in response.headers):
        raise AuthError(i18n.t("error.probeAuth"))
    if response.status_code >= 400:
        raise VerificationError(
            i18n.t("error.probeHttp", code=response.status_code))
    try:
        body = response.json()
    except ValueError:
        content_type = response.headers.get("Content-Type", "?")
        raise VerificationError(
            i18n.t("error.probeNotJson", type=content_type))
    if not isinstance(body, dict) or not body:
        raise VerificationError(
            i18n.t("error.probeEmptySettings"))

    flat = fields.flatten(body)
    # Extras are a bonus: the device counts as read without them.
    for endpoint in (EXTRA_ENDPOINTS if extra_endpoints is None
                     else extra_endpoints):
        try:
            extra = _SESSION.get(f"{base}/{endpoint}",
                                 timeout=min(limit, 2.5), auth=auth)
            if extra.ok:
                flat.update(fields.flatten(extra.json()))
        except Exception:
            pass

    return {
        "version": fields.pick(flat, *fields.VERSION_KEYS) or "",
        "serial": fields.pick(flat, *fields.SERIAL_KEYS) or "",
        "uptime": fields.pick(flat, *fields.UPTIME_KEYS),
        "sipPbx": fields.pick(flat, *fields.PBX_KEYS) or "",
        "sipExtension": fields.pick(flat, *fields.EXTENSION_KEYS,
                                    exclude=fields.EXTENSION_EXCLUDE) or "",
        "sipOutbound": fields.pick(flat, *fields.OUTBOUND_KEYS) or "",
        "speakerVolume": fields.pick(flat, *fields.SPEAKER_KEYS,
                                     exclude=("gain",)),
        "micVolume": fields.pick(flat, *fields.MIC_KEYS, exclude=("gain",)),
        "speakerGain": fields.pick(flat, *fields.SPEAKER_GAIN_KEYS),
        "micGain": fields.pick(flat, *fields.MIC_GAIN_KEYS),
        "settings": body,
        # The full flattened field set including the extras. The
        # configuration screen needs this: a Handset's mode fields live on
        # `system/modes`, not the main endpoint, so `settings` alone would
        # make them look unread.
        "flat": flat,
    }
