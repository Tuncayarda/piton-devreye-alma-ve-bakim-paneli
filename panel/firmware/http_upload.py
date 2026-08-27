#!/usr/bin/env python3
"""Announcement equipment — firmware image over HTTP multipart."""
from __future__ import annotations

from pathlib import Path

import requests

from .. import clock, settings
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


def post_image(ip: str, path, credentials=None, timeout: float = 120.0) -> None:
    """Send the image to one ADDRESS. Raises on anything but acceptance.

    Split out from `upload_image` because the IP assignment run flashes a
    device it cannot name: whatever answers on the factory address, before it
    has an address of its own and therefore before it is any DeviceMap record
    (see `panel.ip_assign.preflash`). Everything about the request — endpoint,
    field name, part type — stays the same for both callers.
    """
    auth = tuple(credentials) if credentials else None
    try:
        with open(path, "rb") as handle:
            response = requests.post(
                f"http://{ip}:{settings.ANNOUNCEMENT_PORT}/{UPLOAD_ENDPOINT}",
                files={FIELD_NAME: (Path(path).name, handle, PART_TYPE)},
                timeout=timeout, auth=auth)
    except Exception as exc:
        raise classify(exc)
    if response.status_code in (401, 403):
        raise AuthError(i18n.t("error.probeAuth"))
    if response.status_code >= 400:
        raise VerificationError(
            i18n.t("error.uploadRefused", code=response.status_code))


def upload_image(device: Device, path, credentials,
                 verify_window: float) -> dict:
    previous = ""
    try:
        previous = announcement.read(device.ip, credentials).get("version", "")
    except AuthError:
        raise
    except Exception:
        pass

    post_image(device.ip, path, credentials)

    # The device is rebooting: the version can only be read once it is back.
    deadline = clock.monotonic() + verify_window
    current = ""
    while clock.monotonic() < deadline:
        clock.sleep(2.0)
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
    return {"previous": previous, "current": current,
            "changed": bool(previous) and str(previous) != str(current)}
