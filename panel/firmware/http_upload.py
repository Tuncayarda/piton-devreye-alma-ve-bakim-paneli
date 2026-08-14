#!/usr/bin/env python3
"""Announcement equipment — firmware image over HTTP multipart."""
from __future__ import annotations

import time
from pathlib import Path

import requests

from .. import settings
from ..errors import AuthError, VerificationError, classify
from ..inventory.device_map import Device
from ..probe import announcement
from .. import i18n

# Endpoint and part shape taken verbatim from the device's own browser
# request. The endpoint is "firmware", not "update" — uploads to the wrong
# address failed with HTTP 404.
UPLOAD_ENDPOINT = "api/v1/system/firmware"
FIELD_NAME = "firmware"
# The part's Content-Type is left as the device's own UI sends it.
PART_TYPE = "application/macbinary"


def upload_image(device: Device, path, expected: str, credentials,
                 verify_window: float) -> dict:
    previous = ""
    try:
        previous = announcement.read(device.ip, credentials).get("version", "")
    except AuthError:
        raise
    except Exception:
        pass

    auth = tuple(credentials) if credentials else None
    try:
        with open(path, "rb") as handle:
            response = requests.post(
                f"http://{device.ip}:{settings.ANNOUNCEMENT_PORT}/"
                f"{UPLOAD_ENDPOINT}",
                files={FIELD_NAME: (Path(path).name, handle, PART_TYPE)},
                timeout=120, auth=auth)
    except Exception as exc:
        raise classify(exc)
    if response.status_code in (401, 403):
        raise AuthError(i18n.t("error.probeAuth"))
    if response.status_code >= 400:
        raise VerificationError(
            i18n.t("error.uploadRefused", code=response.status_code))

    # The device is rebooting: the version can only be read once it is back.
    deadline = time.time() + verify_window
    current = ""
    while time.time() < deadline:
        time.sleep(2.0)
        try:
            current = announcement.read(device.ip, credentials,
                                        timeout=2.5).get("version", "")
            if current:
                break
        except Exception:
            continue

    if not current:
        raise VerificationError(
            i18n.t("error.uploadNoReturn"))
    if expected and str(current).strip() != str(expected).strip():
        raise VerificationError(
            i18n.t("error.versionMismatch", current=current,
                   expected=expected))
    return {"previous": previous, "current": current,
            "changed": bool(previous) and str(previous) != str(current)}
