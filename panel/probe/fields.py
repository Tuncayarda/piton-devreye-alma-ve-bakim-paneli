#!/usr/bin/env python3
"""Flattening device JSON and picking fields out of it.

Manufacturers rename fields between firmware versions, so every value has a
list of candidate names rather than one. Binding to a single name makes a
working device look like it "returns no data".
"""
from __future__ import annotations

import re


def flatten(obj, prefix: str = "") -> dict:
    """Reduce nested JSON to a {lowercase.key: value} dict."""
    out: dict = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}{key}".lower()
            if isinstance(value, (dict, list)):
                out.update(flatten(value, f"{path}."))
            else:
                out[path] = value
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            out.update(flatten(value, f"{prefix}{index}."))
    return out


def _squash(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def pick(flat: dict, *candidates, exclude=()):
    """First non-empty value among the candidate names.

    Three passes: exact name, last path segment, then long substring.
    """
    def filled(value):
        return value not in ("", None) and str(value).strip() != ""

    for candidate in candidates:
        value = flat.get(candidate.lower())
        if filled(value):
            return value

    tails = {k: _squash(k.rsplit(".", 1)[-1]) for k in flat}
    for candidate in candidates:
        wanted = _squash(candidate)
        for key, value in flat.items():
            if tails[key] == wanted and filled(value):
                return value

    unwanted = tuple(_squash(x) for x in exclude)
    whole = {k: _squash(k) for k in flat}
    for candidate in candidates:
        wanted = _squash(candidate)
        if len(wanted) < 7:
            continue
        for key, value in flat.items():
            if (wanted in whole[key] and filled(value)
                    and not any(bad in whole[key] for bad in unwanted)):
                return value
    return None


VERSION_KEYS = ("firmwareversion", "firmware", "swversion", "softwareversion",
                "appversion", "fwversion", "version", "buildversion", "build")
SERIAL_KEYS = ("serialnumber", "serialno", "serial", "sn", "devicesn",
               "deviceserial", "deviceid", "chipid", "uuid")
UPTIME_KEYS = ("uptimeseconds", "uptimesec", "uptime", "systemuptime",
               "runtime", "runningtime")
PBX_KEYS = ("pbxip", "pbx_ip", "sippbx", "sipserver", "pbxserver", "sipproxy",
            "registrar", "serverip", "proxy", "pbx", "server")
EXTENSION_KEYS = ("pbxextension", "pbx_extension", "sipextension", "extension",
                  "ext")
SPEAKER_KEYS = ("speakervolume", "speaker_volume", "speakerlevel", "callvolume",
                "outputvolume", "playvolume", "speaker", "volume")
MIC_KEYS = ("microphonevolume", "microphone_volume", "micvolume", "miclevel",
            "inputvolume", "recordvolume", "microphone", "mic")
# Gain is a separate field from volume (speakerGain / micGain on the device).
# "gain" is excluded from the volume search so the two never mix.
SPEAKER_GAIN_KEYS = ("speakergain", "speaker_gain", "spkgain", "outputgain",
                     "playgain", "amplifiergain")
MIC_GAIN_KEYS = ("microphonegain", "microphone_gain", "micgain", "mic_gain",
                 "inputgain", "recordgain")
# Outbound call target (pbxOutExtension), kept apart from the device's own
# extension (pbxExtension).
OUTBOUND_KEYS = ("pbxoutextension", "pbx_out_extension", "pbxoutext",
                 "outextension", "out_extension", "outext",
                 "outboundextension", "outbound_extension", "outboundext",
                 "outboundcallextension", "outboundnumber",
                 "outboundcallnumber", "calloninput0", "destinationnumber",
                 "dialnumber", "callnumber")

# Exclusions that keep the device's own extension apart from the outbound one.
EXTENSION_EXCLUDE = ("outbound", "outext", "pbxout", "dial")
