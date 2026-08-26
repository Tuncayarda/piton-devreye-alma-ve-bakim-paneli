#!/usr/bin/env python3
"""Software installation — two device families, two paths.

**Announcement equipment (HTTP).** Same shape as the device's own web UI:
multipart/form-data, field name "firmware", endpoint
/api/v1/system/firmware. The device reboots afterwards.

**Compartment LCD (ADB).** Android; an APK is installed rather than an image:
`adb install -r`. The new version is verified from the same place the probe
layer reads it (see probe.android.package_info) against the version inside the
chosen APK's own manifest — nobody types a version anywhere.

On both paths, HTTP 200 / "Success" alone is not success: the device is read
again and it must really report a version.

The file is chosen PER SET AND PER DEVICE. Two devices in one group need not
take the same file: a field intercom can be an older hardware revision and
not accept the group's .bin. With a single "selected file" there was no way to
see that — the install started and the wrong image went out. For convenience
one file can be assigned to a whole group in one call.

The file comes from the user and only its path is kept — the panel never
copies or stores the image. The selection is memory-only and disappears when
the application closes.
"""
from __future__ import annotations

from pathlib import Path

from ..errors import NotApplicableError
from ..inventory.device_map import Device
from .apk_install import install_apk
from .http_upload import post_image, upload_image
from .selection import (MAX_APK_SIZE, MAX_BIN_SIZE, MAX_SIZE, clear_all,
                        clear_selection, has_selection, max_size_for,
                        selection_for, selections, select_file,
                        validate_file, take_selection)
from .. import i18n

# Read method -> expected file extension. The file picker's filter and the
# on-screen help come from here; offering a .bin to a device that wants an
# APK makes no sense.
EXTENSIONS = {"http": "bin", "adb": "apk"}


def is_supported(device: Device) -> bool:
    """Can software be installed on this device?"""
    return device.read_method in EXTENSIONS


def file_extension(device: Device) -> str:
    """The extension this device expects ("bin" / "apk")."""
    return EXTENSIONS.get(device.read_method, "")


def install(device: Device, credentials=None, verify_window: float = 45.0, *,
            set_no: int = 1) -> dict:
    """Install this device's selected file and verify the version."""
    if not is_supported(device):
        raise NotApplicableError(
            i18n.t("error.firmwareTypeNotDefined"))
    record = take_selection(device.id, set_no=set_no)
    if record is None:
        raise ValueError(i18n.t("error.noFileForDevice"))
    path = record["path"]
    # The file may have been deleted or moved since selection; a clear error
    # beats an unopenable file mid-run.
    if not Path(path).is_file():
        raise ValueError(i18n.t("error.fileGone", name=Path(path).name))

    if device.read_method == "adb":
        return install_apk(device, path, verify_window)
    return upload_image(device, path, credentials, verify_window)


__all__ = ["EXTENSIONS", "MAX_APK_SIZE", "MAX_BIN_SIZE", "MAX_SIZE",
           "clear_all", "clear_selection", "file_extension", "has_selection",
           "install", "is_supported", "max_size_for", "post_image",
           "selection_for", "selections", "select_file", "validate_file"]
