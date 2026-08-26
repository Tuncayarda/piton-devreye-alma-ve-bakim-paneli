#!/usr/bin/env python3
"""Reading and writing one camera's configuration over ISAPI.

ENDPOINTS
─────────
  System/time                          time mode + time zone
  System/time/ntpServers/1             NTP server
  System/Hardware                      IrLightSwitch (the IR illuminator)
  System/Software/channels/1           ThirdStream on/off — REBOOTS the camera
  System/Network/interfaces            READ ONLY. Writing a network value
                                       over ISAPI loses the device (see the
                                       note on the subnetMask field)
  ContentMgmt/Storage/hdd[/{id}/format]  SD card
  Streaming/channels/101 · 102 · 103   the three stream profiles
  System/reboot

WHAT REBOOTS THE CAMERA
───────────────────────
Turning the third stream on or off, and changing the IR mode. Both are
applied only when the device does not already hold the target value — a
camera must not be blacked out to write a setting it already has. The third
stream can only be configured once the camera is back up, so after a reboot
channel 103 is retried until it answers.
"""
from __future__ import annotations

from .. import i18n
from . import channels, isapi, payloads

# The stream profiles are written as one unit: any of these differing means
# all three channels are sent, because a profile is only meaningful whole.
STREAM_FIELDS = ("channelName", "audioEnabled", "stream3Resolution")


def _flag(value) -> str:
    return "1" if str(value or "").strip().lower() == "true" else "0"


def read_state(device, inventory, credentials) -> dict:
    """Everything the configuration screen shows for a camera.

    Keys are the field names in lower case, so `config_sync.apply._rows` can
    read this straight through `probe.fields.pick` — the same path the
    announcement devices take.
    """
    ip = device.ip
    hardware = isapi.read(ip, "System/Hardware", credentials)
    ir_mode = ""
    for switch in isapi.blocks(hardware, "IrLightSwitch"):
        ir_mode = isapi.child_text(switch, "mode").lower()
        break

    main = isapi.read(ip, "Streaming/channels/101", credentials)
    audio = ""
    for block in isapi.blocks(main, "Audio"):
        audio = _flag(isapi.child_text(block, "enabled"))
        break

    third = isapi.read(ip, "Streaming/channels/103", credentials)
    width = isapi.first(third, "videoResolutionWidth")
    height = isapi.first(third, "videoResolutionHeight")

    summary, _disks = isapi.storage_status(
        isapi.read(ip, "ContentMgmt/Storage/hdd", credentials))
    identity = isapi.read(ip, "System/deviceInfo", credentials)

    return {
        "timezone": isapi.first(
            isapi.read(ip, "System/time", credentials), "timeZone") or "",
        "ntpserver": isapi.first(
            isapi.read(ip, "System/time/ntpServers/1", credentials),
            "ipAddress") or "",
        "subnetmask": isapi.interface_mask(
            isapi.read(ip, "System/Network/interfaces", credentials), ip),
        "irlight": ir_mode,
        "thirdstream": _flag(isapi.first(
            isapi.read(ip, "System/Software/channels/1", credentials),
            "enabled")),
        "channelname": isapi.first(main, "channelName") or "",
        "audioenabled": audio,
        "stream3resolution": f"{width}x{height}" if width and height else "",
        "storagestatus": summary,
        "firmwareversion": isapi.first(identity, "firmwareVersion") or "",
        "serialnumber": isapi.first(identity, "serialNumber") or "",
    }


def _format_storage(device, credentials, say) -> bool:
    """Format the SD card only when it is unusable as it stands.

    A card that is formatted and recording is left alone: applying a setting
    must never wipe footage (see isapi.needs_format).
    """
    summary, disks = isapi.storage_status(
        isapi.read(device.ip, "ContentMgmt/Storage/hdd", credentials))
    if not disks:
        say(i18n.lazy("video.stepNoStorage"), "info")
        return False
    formatted = False
    for hdd_id, status in disks:
        if not isapi.needs_format(status):
            continue
        isapi.write(device.ip, f"ContentMgmt/Storage/hdd/{hdd_id}/format",
                    credentials, "", timeout=15)
        say(i18n.lazy("video.stepStorageFormatted", id=hdd_id,
                      status=status or "?"), "written")
        formatted = True
    if not formatted:
        say(i18n.lazy("video.stepStorageOk", detail=summary), "info")
    return formatted


def _reboot(device, credentials) -> None:
    """Ask for a reboot. A dropped connection means it started."""
    try:
        isapi.request("PUT", device.ip, "System/reboot", credentials)
    except Exception:
        pass


def apply(device, inventory, targets: dict, credentials, report=None) -> dict:
    """Write the targets that differ, and report what was done.

    Returns {"written": [field names], "rebooted": bool, "state": flat dict}.
    The state is read AFTER the writes so the caller verifies against the
    device rather than against the reply to the write.

    `report(text, state)` receives one line per step, the way the field
    script prints them — which channel was written, which card was
    formatted, why the device is being restarted. The queue shows them under
    the device's row, so "what did it actually change" has an answer that is
    not "read the code".
    """
    say = report or isapi.no_report
    ip = device.ip
    state = read_state(device, inventory, credentials)
    written: list[str] = []

    def differs(name: str) -> bool:
        return (name in targets
                and str(state.get(name.lower(), "")) != str(targets[name]))

    if differs("timeZone"):
        isapi.write(ip, "System/time", credentials,
                    payloads.time_body(targets["timeZone"]))
        say(i18n.lazy("video.stepTimeZone", value=targets["timeZone"]),
            "written")
        written.append("timeZone")
    if differs("ntpServer"):
        isapi.write(ip, "System/time/ntpServers/1", credentials,
                    payloads.ntp_body(targets["ntpServer"]))
        say(i18n.lazy("video.stepNtp", value=targets["ntpServer"]), "written")
        written.append("ntpServer")

    ir_changed = differs("irLight")
    if ir_changed:
        isapi.write(ip, "System/Hardware", credentials,
                    payloads.ir_body(targets["irLight"]))
        say(i18n.lazy("video.stepIr", value=targets["irLight"]), "written")
        written.append("irLight")

    if _format_storage(device, credentials, say):
        written.append("storageStatus")

    stream_changed = any(differs(name) for name in STREAM_FIELDS)
    bodies = payloads.stream_bodies(
        targets.get("channelName") or channels.display_name(device),
        str(targets.get("audioEnabled",
                        channels.audio_default(device))) == "1",
        targets.get("stream3Resolution", payloads.DEFAULT_STREAM3))
    if stream_changed:
        for channel in ("101", "102"):
            isapi.write(ip, f"Streaming/channels/{channel}", credentials,
                        bodies[channel])
        say(i18n.lazy("video.stepStreams",
                      name=targets.get("channelName")
                      or channels.display_name(device)), "written")
        written.extend(name for name in STREAM_FIELDS if differs(name))

    third_changed = differs("thirdStream")
    if third_changed:
        isapi.write(ip, "System/Software/channels/1", credentials,
                    payloads.third_stream_body(targets["thirdStream"] == "1"))
        say(i18n.lazy("video.stepThirdStreamOn" if targets["thirdStream"] == "1"
                      else "video.stepThirdStreamOff"), "written")
        written.append("thirdStream")

    # The camera reboots for the third stream and for the IR mode; channel
    # 103 exists only once it is back, so the write waits for it.
    rebooted = ir_changed or third_changed
    if rebooted:
        say(i18n.lazy("video.stepRebooting"), "info")
        _reboot(device, credentials)
        back = isapi.wait_until_back(device.ip, credentials)
        say(i18n.lazy("video.stepBack" if back else "video.stepNotBack"),
            "done" if back else "warning")

    wants_third = str(targets.get("thirdStream", "1")) == "1"
    if wants_third and (stream_changed or third_changed):
        isapi.write(ip, "Streaming/channels/103", credentials, bodies["103"])
        say(i18n.lazy("video.stepThirdProfile"), "written")

    if not written:
        say(i18n.lazy("video.stepNothingToDo"), "info")
    return {"written": written, "rebooted": rebooted,
            "state": read_state(device, inventory, credentials)}
