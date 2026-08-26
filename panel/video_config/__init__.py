"""Camera and NVR configuration over Hikvision ISAPI.

Where `panel.config_sync` writes announcement equipment field by field, video
equipment is configured as a PROCEDURE: time and NTP, the stream profiles,
the third stream (which reboots the camera), the SD card, and on the NVR the
input channels and the buzzer. The order matters and some steps only make
sense once an earlier one has taken effect.

The screen, the target values, the credentials and the job queue are still
`config_sync`'s: `fetch()` and `apply_targets()` dispatch here on the
device's read method (`isapi`), exactly as they already do for `adb`.

WHAT THIS MODULE NEVER DOES
  · touch a device's network settings. The address and the mask are set with
    SADP in the field; a mask written over ISAPI answers OK and then the
    device is gone from its address, recoverable only by a power cycle and
    SADP. The panel READS both and reports them;
  · configure motion detection — out of scope for this project.
"""
from __future__ import annotations

from .. import i18n
from ..errors import NotApplicableError
from . import camera, channels, defaults, health, isapi, nvr, payloads

__all__ = ["apply", "audio_default", "camera", "channels", "defaults",
           "health", "isapi", "nvr", "payloads", "read_state"]

audio_default = channels.audio_default


def _engine(device):
    if device.type == "NVR":
        return nvr
    if device.type == "Camera":
        return camera
    raise NotApplicableError(i18n.t("error.videoTypeUnsupported"))


def read_state(device, inventory, credentials=None) -> dict:
    """Everything the configuration screen shows, flattened by field name."""
    return _engine(device).read_state(device, inventory, credentials)


def apply(device, inventory, targets: dict, credentials=None,
          report=None) -> dict:
    """Write the targets. {"written": [...], "rebooted": bool, "state": {}}.

    `report(text, state)` is called once per step of the procedure; see
    `camera.apply`.
    """
    return _engine(device).apply(device, inventory, targets, credentials,
                                 report)
