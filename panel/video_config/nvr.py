#!/usr/bin/env python3
"""Reading and writing the NVR's configuration over ISAPI.

ENDPOINTS
─────────
  System/time                            time mode + time zone
  System/time/ntpServers/1               NTP server
  System/Network/interfaces              READ ONLY. Writing a network
                                         value over ISAPI loses the device
                                         (see the subnetMask field note)
  ContentMgmt/InputProxy/channels[/{id}] the cameras, as input channels
  ContentMgmt/Storage/hdd[/{id}/format]  the disk
  Event/triggers[/{id}]                  the audible warning (beep)
  System/reboot

NOT HERE: motion detection. The VMD trigger, its 24/7 schedule and the grid
map exist in the field script for one project only and are deliberately not
part of the panel — see docs/DEGISIKLIKLER.md.

THE CHANNEL PASSWORD
────────────────────
An input channel carries the CAMERA's own credential: the NVR logs in to the
camera to pull its stream. The panel keeps no passwords on disk, so it takes
the one the user entered for that camera this session (panel.credentials),
falling back to the NVR's. Without either, the channel cannot be written and
the user is told which credential is missing.
"""
from __future__ import annotations

import re

from .. import credentials as credential_store
from .. import i18n
from ..errors import AuthError, VerificationError
from ..inventory.catalog import READ_METHODS
from . import channels, health, isapi, payloads, procedure

# One EventTriggerNotification block whose method is "beep". Removing the
# block is how the device's own page turns the buzzer off; there is no
# "enabled" flag to clear.
_BEEP_BLOCK = re.compile(
    r"<EventTriggerNotification>(?:(?!</EventTriggerNotification>).)*?"
    r"<notificationMethod>beep</notificationMethod>.*?"
    r"</EventTriggerNotification>", re.DOTALL)

# The current panel profile is Yatakli: exactly four camera inputs.  Deleting
# recorder channels is intentionally stricter than adding/updating them.  A
# partially loaded DeviceMap must not turn "three cameras were discovered"
# into permission to erase channel 4 and everything after it.
_YATAKLI_CHANNEL_IDS = frozenset({1, 2, 3, 4})


def _existing_channels(device, credentials) -> dict[int, tuple[str, str]]:
    """{channel id: (name, camera address)} already on the NVR."""
    root = isapi.read(device.ip, "ContentMgmt/InputProxy/channels",
                      credentials)
    # An unreadable required list is not an empty list.  Treating it as empty
    # would make the panel POST duplicates and could later authorize cleanup
    # from an invented view of the recorder.
    if root is None:
        raise VerificationError(i18n.t("error.nvrChannelsUnreadable"))
    found: dict[int, tuple[str, str]] = {}
    for channel in isapi.blocks(root, "InputProxyChannel"):
        number = isapi.child_text(channel, "id")
        if not number.isdigit():
            continue
        source = isapi.blocks(channel, "sourceInputPortDescriptor")
        address = isapi.child_text(source[0], "ipAddress") if source else ""
        found[int(number)] = (isapi.child_text(channel, "name"), address)
    return found


def _channel_status(expected, existing) -> tuple[str, bool, list[int]]:
    """Display summary, whether expected rows match, and unexpected ids."""
    expected_ids = {number for number, _name, _camera in expected}
    # Old NVR firmware does not accept <name> in an existing-channel PUT.
    # Channel identity and read-back verification therefore use the stable
    # channel id + camera address pair; the name is supplied on POST only.
    matching = sum(
        1 for number, _name, camera in expected
        if existing.get(number, ("", ""))[1] == camera.ip)
    stale = sorted(set(existing) - expected_ids)
    if not expected and not existing:
        summary = ""
    elif stale:
        summary = i18n.t("video.channelSummaryExtra", matching=matching,
                         expected=len(expected), extra=len(stale))
    else:
        summary = f"{matching}/{len(expected)}"
    return summary, matching == len(expected), stale


def _channel_ranges(numbers: list[int]) -> str:
    """[5, 6, 7, 9] -> '5–7, 9' for a compact queue message."""
    if not numbers:
        return ""
    ranges = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(str(start) if start == previous else f"{start}–{previous}")
        start = previous = number
    ranges.append(str(start) if start == previous else f"{start}–{previous}")
    return ", ".join(ranges)


def _complete_yatakli_map(inventory, expected) -> bool:
    ids = [number for number, _name, _camera in expected]
    return (str(inventory.project or "").upper() == "YATAKLI"
            and len(ids) == len(_YATAKLI_CHANNEL_IDS)
            and set(ids) == _YATAKLI_CHANNEL_IDS
            and all(name and camera.ip
                    for _number, name, camera in expected))


def _trigger_ids(device, credentials) -> list[str]:
    root = isapi.read(device.ip, "Event/triggers", credentials)
    ids = []
    for trigger in isapi.blocks(root, "EventTrigger"):
        number = isapi.child_text(trigger, "id")
        if number:
            ids.append(number)
    return ids


def _buzzer_state(device, credentials) -> str:
    """"1" while any trigger still sounds the buzzer, "" when unreadable.

    The same read the verification pass makes (panel.video_config.health), so
    the screen and the scan cannot disagree about it — and so the fallback
    for firmware whose trigger LIST carries no notification methods applies
    here too. Without it a device that beeps would be read as silent and
    never get silenced.
    """
    state = health.buzzer_on(device.ip, credentials)
    return "" if state is None else ("1" if state else "0")


def read_state(device, inventory, credentials) -> dict:
    ip = device.ip
    expected = channels.for_nvr(inventory)
    existing = _existing_channels(device, credentials)
    channel_summary, _matching, _stale = _channel_status(expected, existing)

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
        "proxychannels": channel_summary,
        "buzzer": _buzzer_state(device, credentials),
        "storagestatus": summary,
        "firmwareversion": isapi.first(identity, "firmwareVersion") or "",
        "serialnumber": isapi.first(identity, "serialNumber") or "",
    }


def _camera_credential(camera, fallback):
    # The credential group by hand rather than through panel.probe.reader:
    # the probe layer asks this package for its health checks, and importing
    # it back from here would close the circle.
    group = READ_METHODS.get(camera.read_method, {}).get("group")
    found = credential_store.lookup(camera.id, camera.ip, group=group)
    if found:
        return found
    if fallback:
        return fallback
    raise AuthError(i18n.t("error.cameraCredentialRequired",
                           device=camera.name))


def _write_channels(device, inventory, credentials, say) -> int:
    """Make the recorder's channel set exactly match DeviceMap.

    Expected channels are written and read back before any unexpected channel
    is deleted.  A recorder that returns HTTP 200 but silently ignores a write
    therefore leaves its legacy channels untouched instead of ending in a
    destructive half-configured state.
    """
    existing = _existing_channels(device, credentials)
    expected = channels.for_nvr(inventory)
    # An empty project list can mean malformed/incomplete DeviceMap data.  It
    # must never be interpreted as authorization to wipe every NVR channel.
    if not expected:
        return 0
    written = 0
    for number, name, camera in expected:
        current = existing.get(number)
        if current and current[1] == camera.ip:
            continue
        username, password = _camera_credential(camera, credentials)
        body = payloads.proxy_channel_body(number, name, camera.ip,
                                           username, password,
                                           include_name=current is None)
        if current is None:
            isapi.write(device.ip, "ContentMgmt/InputProxy/channels",
                        credentials, body, method="POST", timeout=10,
                        headers=isapi.FORM_HEADERS)
            say(i18n.lazy("video.stepChannelAdded", id=number, name=name,
                          ip=camera.ip), "written")
        else:
            isapi.write(device.ip,
                        f"ContentMgmt/InputProxy/channels/{number}",
                        credentials, body, timeout=10,
                        headers=isapi.FORM_HEADERS)
            say(i18n.lazy("video.stepChannelUpdated", id=number, name=name,
                          ip=camera.ip), "written")
        written += 1
    # Verify the non-destructive part first.  Do not prune a single legacy
    # channel unless every project channel can already be read back by id and
    # camera address.  Existing-channel names are firmware-owned because this
    # generation rejects that field on PUT.
    confirmed = _existing_channels(device, credentials)
    summary, expected_match, stale = _channel_status(expected, confirmed)
    if not expected_match:
        raise VerificationError(
            i18n.t("error.nvrChannelsUnverified", detail=summary or "?"))

    if stale and not _complete_yatakli_map(inventory, expected):
        say(i18n.lazy("video.stepChannelCleanupSkipped"), "info")
        stale = []

    for number in stale:
        isapi.write(device.ip,
                    f"ContentMgmt/InputProxy/channels/{number}",
                    credentials, "", method="DELETE", timeout=10,
                    headers=isapi.FORM_HEADERS)

    if stale:
        final = _existing_channels(device, credentials)
        final_summary, final_match, remaining = _channel_status(expected, final)
        if not final_match or remaining:
            raise VerificationError(i18n.t(
                "error.nvrChannelsUnverified", detail=final_summary or "?"))
        say(i18n.lazy("video.stepChannelsRemoved", count=len(stale),
                      ids=_channel_ranges(stale)), "written")
        written += len(stale)

    if not written:
        say(i18n.lazy("video.stepChannelsMatch", count=len(expected)), "info")
    return written


def _silence_buzzer(device, credentials, say) -> bool:
    """Strip the beep block from every trigger that carries one."""
    changed = 0
    for number in _trigger_ids(device, credentials):
        path = f"Event/triggers/{number}"
        response = isapi.request("GET", device.ip, path, credentials,
                                 timeout=10)
        if response.status_code != 200:
            continue
        text = response.text or ""
        if "<notificationMethod>beep<" not in text:
            continue
        body = _BEEP_BLOCK.sub("", text)
        # If the block did not come out the request would put the beep
        # straight back; leaving the trigger untouched is the safer answer.
        if "<notificationMethod>beep<" in body:
            continue
        isapi.write(device.ip, path, credentials, body, timeout=10)
        changed += 1
    if changed:
        say(i18n.lazy("video.stepBuzzerOff", count=changed), "written")
    return bool(changed)


def apply(device, inventory, targets: dict, credentials, report=None) -> dict:
    """Write the NVR's configuration.

    The verification read happens BEFORE the reboot: once the reboot request
    is sent the device stops answering, and a read that times out would
    report a perfectly good write as a failure.

    `report(text, state)` receives one line per step — which channel was
    written, which disk was formatted, why it is being restarted — the way
    the field script prints them. They appear under the device's row in the
    queue (see panel.api.tasks.config_task).
    """
    say = report or isapi.no_report
    ip = device.ip
    state = read_state(device, inventory, credentials)
    written = procedure.apply_time_targets(ip, state, targets, credentials,
                                           say)

    if _write_channels(device, inventory, credentials, say):
        written.append("proxyChannels")
    if procedure.format_storage(device, credentials, say):
        written.append("storageStatus")
    wants_silence = str(targets.get("buzzer", "0")) == "0"
    if (wants_silence and state.get("buzzer") == "1"
            and _silence_buzzer(device, credentials, say)):
        written.append("buzzer")

    final = read_state(device, inventory, credentials)
    # Rebooting is what makes the NVR pick the channels up. It is skipped
    # when nothing was written: a device already in agreement must not be
    # taken off air for a run that changed nothing.
    if written:
        say(i18n.lazy("video.stepNvrRebooting"), "info")
        procedure.reboot(device, credentials)
    else:
        say(i18n.lazy("video.stepNothingToDo"), "info")
    return {"written": written, "rebooted": bool(written), "state": final}
