#!/usr/bin/env python3
"""Field definitions and the device endpoints each one is written to.

WRITE ENDPOINTS
───────────────
Reading uses one endpoint (GET api/v1/system/settings) but writing does not:
that endpoint returns HTTP 405 to a POST. The device's own web UI posts each
topic to its own endpoint and the panel does the same. Every row in ROUTES is
taken verbatim from that device type's page — guessed fields are never added,
because the device ignores unknown ones silently.

  api/v1/audio/volume    volumes, gain, log level — accepts a partial body
  api/v1/system/modes    Handset modes — all four mode fields required
  api/v1/uic/gains       UIC TC/TL gains — all four required together
  api/v1/sip/settings    SIP — pbxIp+pbxExtension+pbxPassword required, and
                         THE DEVICE REBOOTS after this one

So writing is not "send everything in one body": only fields that differ from
the device go out, each to its own endpoint. A matching field triggers no
request at all — a pointless call to the SIP endpoint would reboot every
device for nothing.

SIP PASSWORD
────────────
The SIP endpoint demands the password, so without it the extension cannot be
written either. Sources in order: what the user typed on this screen (memory
only), PBXPassword from DeviceMap (project data), and **the extension
itself**.

That last step is the field rule: in this project the SIP password equals the
extension. Devices with no PBXPassword in DeviceMap (Amplifier, UIC) had no
password at all, and since the SIP endpoint requires one, their extension
could not be written either. Change the number on screen and the password
follows.

This value is NEVER sent to the UI: the row shows only "matches/differs" and
the source. It is for the device's SIP registration and is unrelated to the
credential the panel uses to connect (see panel.credentials).
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import i18n
from ..probe import fields as probe_fields

# ── the device's endpoints ──────────────────────────────────────────────
AUDIO_ENDPOINT = "api/v1/audio/volume"
MODES_ENDPOINT = "api/v1/system/modes"
UIC_ENDPOINT = "api/v1/uic/gains"
SIP_ENDPOINT = "api/v1/sip/settings"

# Write order: SIP last, because the device reboots after it and any later
# request would fail with a connection error.
ENDPOINT_ORDER = (AUDIO_ENDPOINT, MODES_ENDPOINT, UIC_ENDPOINT, SIP_ENDPOINT)
REBOOTING_ENDPOINTS = {SIP_ENDPOINT}

# Endpoints that reject a partial body need these fields on every request.
# Missing, the device answers "Missing required fields" / "Missing mode
# fields", and uic/gains simply drops the connection. Required fields that
# are not being changed are filled from what the device reports.
REQUIRED_FIELDS = {
    SIP_ENDPOINT: ("sipPbx", "sipExtension", "sipPassword"),
    MODES_ENDPOINT: ("ptt", "answerMode", "callMode", "hangupMode"),
    UIC_ENDPOINT: ("tcSpeakerGain", "tcMicGain",
                   "tlSpeakerGain", "tlMicGain"),
}

# ── option lists (same as the dropdowns on the device's pages) ──────────
GAIN = tuple((str(value), f"{value}x")
             for value in (1, 2, 4, 6, 8, 12, 16, 24, 32, 48, 64))
LOG_LEVEL = (("1", "option.errorsAndInfo"), ("0", "option.errorsOnly"))
RING_TIMEOUT = (("0", "option.off"), ("5", "option.s5"), ("10", "option.s10"),
                ("15", "option.s15"), ("20", "option.s20"), ("30", "option.s30"),
                ("45", "option.s45"), ("60", "option.min1"), ("90", "option.min15"),
                ("120", "option.min2"))
ON_OFF = (("1", "option.on"), ("0", "option.off"))
ANSWER_MODE = (("0", "option.pressButton"), ("1", "option.answerAuto"))
CALL_MODE = (("0", "option.singlePress"), ("1", "option.longPress"))
HANGUP_MODE = (("0", "option.singlePress"), ("1", "option.doublePress"), ("2", "option.dtmf"))

# ── sections ────────────────────────────────────────────────────────────
# A section id is a stable contract value shared with the UI; the label next
# to it is the only thing on screen. Reworded headings must never move a
# field between panels, which is why the two are separate.
SECTION_SIP = "sip"
SECTION_AUDIO = "audio"
SECTION_MODE = "mode"
SECTION_THRESHOLDS = "thresholds"
SECTION_ROUTING = "routing"
SECTION_INFORMATION = "information"

SECTION_LABELS = {
    SECTION_SIP: "section.sip",
    SECTION_AUDIO: "section.audio",
    SECTION_MODE: "section.mode",
    SECTION_THRESHOLDS: "section.thresholds",
    SECTION_ROUTING: "section.routing",
    SECTION_INFORMATION: "section.information",
}


@dataclass(frozen=True)
class Field:
    """One row on screen, one field on the device.

    `write_name` is the device's real field name; None means read-only.
    `read_names` are the candidates to read it by — kept wide for fields
    renamed between firmware versions; empty falls back to `write_name`.

    `label`, `hint` and the option labels are message KEYS, not text: this
    table is read on every request and the answer has to be in the language
    selected at that moment (see panel.i18n).
    """

    label: str
    write_name: str | None = None
    section: str = ""
    kind: str = "text"     # text · ip · digits · integer · decimal · choice
    options: tuple = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    secret: bool = False   # the value never reaches the UI
    read_names: tuple = ()
    exclude: tuple = ()
    hint: str = ""

    def candidates(self) -> tuple:
        return self.read_names or ((self.write_name,) if self.write_name
                                   else ())


FIELDS: dict[str, Field] = {
    # ── SIP ──────────────────────────────────────────────────────────
    "sipPbx": Field("field.sipPbx", "pbxIp", SECTION_SIP, "ip",
                    read_names=probe_fields.PBX_KEYS),
    "sipExtension": Field("field.sipExtension", "pbxExtension", SECTION_SIP,
                          "digits", read_names=probe_fields.EXTENSION_KEYS,
                          exclude=probe_fields.EXTENSION_EXCLUDE),
    "sipPassword": Field("field.sipPassword", "pbxPassword", SECTION_SIP, "text",
                         secret=True, read_names=("pbxPassword",),
                         hint="field.sipPasswordHint"),
    "sipOutbound": Field("field.sipOutbound", "pbxOutExtension",
                         SECTION_SIP, "digits",
                         read_names=probe_fields.OUTBOUND_KEYS),
    "ringTimeout": Field("field.ringTimeout", "callTimeout", SECTION_SIP, "choice",
                         options=RING_TIMEOUT, read_names=("callTimeout",)),
    # ── audio ────────────────────────────────────────────────────────
    "speakerVolume": Field("field.speakerVolume", "speakerVolume", SECTION_AUDIO,
                           "integer", minimum=0, maximum=100,
                           read_names=probe_fields.SPEAKER_KEYS,
                           exclude=("gain",)),
    "micVolume": Field("field.micVolume", "micVolume", SECTION_AUDIO,
                       "integer", minimum=0, maximum=100,
                       read_names=probe_fields.MIC_KEYS, exclude=("gain",)),
    "speakerGain": Field("field.speakerGain", "speakerGain", SECTION_AUDIO,
                         "choice", options=GAIN,
                         read_names=probe_fields.SPEAKER_GAIN_KEYS),
    "micGain": Field("field.micGain", "micGain", SECTION_AUDIO, "choice",
                     options=GAIN, read_names=probe_fields.MIC_GAIN_KEYS),
    "logLevel": Field("field.logLevel", "logLevel", SECTION_AUDIO, "choice",
                      options=LOG_LEVEL, read_names=("logLevel",)),
    # ── Handset modes ────────────────────────────────────────────────
    "ptt": Field("field.ptt", "pttEnabled", SECTION_MODE, "choice", options=ON_OFF,
                 read_names=("pttEnabled",)),
    "answerMode": Field("field.answerMode", "answerMode", SECTION_MODE, "choice",
                        options=ANSWER_MODE, read_names=("answerMode",)),
    "callMode": Field("field.callMode", "callMode", SECTION_MODE, "choice",
                      options=CALL_MODE, read_names=("callMode",)),
    "hangupMode": Field("field.hangupMode", "hangupMode", SECTION_MODE, "choice",
                        options=HANGUP_MODE, read_names=("hangupMode",)),
    # ── UIC gains ────────────────────────────────────────────────────
    "tcSpeakerGain": Field("field.tcSpeakerGain", "tcSpeakerGain", SECTION_AUDIO,
                           "choice", options=GAIN,
                           read_names=("tcSpeakerGain",)),
    "tcMicGain": Field("field.tcMicGain", "tcMicGain", SECTION_AUDIO,
                       "choice", options=GAIN, read_names=("tcMicGain",)),
    "tlSpeakerGain": Field("field.tlSpeakerGain", "tlSpeakerGain", SECTION_AUDIO,
                           "choice", options=GAIN,
                           read_names=("tlSpeakerGain",)),
    "tlMicGain": Field("field.tlMicGain", "tlMicGain", SECTION_AUDIO,
                       "choice", options=GAIN, read_names=("tlMicGain",)),
    # ── UIC voltage thresholds (device page: 0–5 V, 0.1 steps) ───────
    "tcHigh": Field("field.tcHigh", "tcHigh", SECTION_THRESHOLDS,
                    "decimal", minimum=0, maximum=5, step=0.1,
                    read_names=("tcHigh",)),
    "tcLow": Field("field.tcLow", "tcLow", SECTION_THRESHOLDS,
                   "decimal", minimum=0, maximum=5, step=0.1,
                   read_names=("tcLow",)),
    "tlHigh": Field("field.tlHigh", "tlHigh", SECTION_THRESHOLDS,
                    "decimal", minimum=0, maximum=5, step=0.1,
                    read_names=("tlHigh",)),
    "tlLow": Field("field.tlLow", "tlLow", SECTION_THRESHOLDS,
                   "decimal", minimum=0, maximum=5, step=0.1,
                   read_names=("tlLow",)),
    # ── UIC call routing (target1..4, in the device page's order) ────
    "tcOutbound": Field("field.tcOutbound", "target1",
                        SECTION_ROUTING, "digits", read_names=("target1",)),
    "tlOutbound": Field("field.tlOutbound", "target2",
                        SECTION_ROUTING, "digits", read_names=("target2",)),
    "tcInbound": Field("field.tcInbound", "target3", SECTION_ROUTING,
                       "digits", read_names=("target3",)),
    "tlInbound": Field("field.tlInbound", "target4", SECTION_ROUTING,
                       "digits", read_names=("target4",)),
    # ── read-only ────────────────────────────────────────────────────
    # SIP registration is what to check after writing extension/password:
    # the device may have accepted the setting yet failed to register with
    # the PBX (a mismatched password, say). Write verification cannot show
    # that.
    "sipRegistration": Field("field.sipRegistration", None, SECTION_INFORMATION,
                             read_names=("status", "sipStatus",
                                         "registrationState")),
    "version": Field("field.version", None, SECTION_INFORMATION,
                     read_names=probe_fields.VERSION_KEYS),
    "serial": Field("field.serial", None, SECTION_INFORMATION,
                    read_names=probe_fields.SERIAL_KEYS),
}

# Which field goes to which endpoint on which device type. Every row matches
# the body that device's own web UI sends.
ROUTES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (AUDIO_ENDPOINT, ("Amplifier",),
     ("speakerVolume", "speakerGain", "logLevel")),
    (AUDIO_ENDPOINT, ("Intercom",),
     ("speakerVolume", "micVolume", "speakerGain", "micGain", "logLevel")),
    (AUDIO_ENDPOINT, ("Handset",), ("speakerVolume", "micVolume")),
    (AUDIO_ENDPOINT, ("UIC",), ("speakerVolume", "micVolume", "logLevel")),
    # On a Handset, gain and log level live on the modes endpoint, not audio.
    (MODES_ENDPOINT, ("Handset",),
     ("ptt", "answerMode", "callMode", "hangupMode", "speakerGain",
      "micGain", "logLevel")),
    (UIC_ENDPOINT, ("UIC",),
     ("tcSpeakerGain", "tcMicGain", "tlSpeakerGain", "tlMicGain")),
    (SIP_ENDPOINT, ("Amplifier",),
     ("sipPbx", "sipExtension", "sipPassword")),
    (SIP_ENDPOINT, ("Intercom",),
     ("sipPbx", "sipExtension", "sipPassword", "sipOutbound")),
    (SIP_ENDPOINT, ("Handset",),
     ("sipPbx", "sipExtension", "sipPassword", "sipOutbound", "ringTimeout")),
    (SIP_ENDPOINT, ("UIC",),
     ("sipPbx", "sipExtension", "sipPassword", "ringTimeout",
      "tcOutbound", "tlOutbound", "tcInbound", "tlInbound",
      "tcHigh", "tcLow", "tlHigh", "tlLow")),
)

# Display order — keeps each section tidy.
ORDER = ("sipPbx", "sipExtension", "sipPassword", "sipOutbound", "ringTimeout",
         "tcOutbound", "tlOutbound", "tcInbound", "tlInbound",
         "speakerVolume", "micVolume", "speakerGain", "micGain",
         "tcSpeakerGain", "tcMicGain", "tlSpeakerGain", "tlMicGain",
         "logLevel",
         "ptt", "answerMode", "callMode", "hangupMode",
         "tcHigh", "tcLow", "tlHigh", "tlLow",
         "sipRegistration", "version", "serial")

# Read-only fields appear on every device type.
READ_ONLY = tuple(name for name in ORDER if FIELDS[name].write_name is None)

WRITABLE = {name for _endpoint, _subtypes, names in ROUTES for name in names}


def endpoint_for(name: str, subtype: str | None) -> str | None:
    """The endpoint this field is written to on this device type."""
    for endpoint, subtypes, names in ROUTES:
        if name in names and (subtype or "") in subtypes:
            return endpoint
    return None


def writable_for_subtype(subtype: str | None) -> tuple[str, ...]:
    """Fields writable on this device type — in display order."""
    available = {name for _endpoint, subtypes, names in ROUTES
                 if (subtype or "") in subtypes for name in names}
    return tuple(name for name in ORDER if name in available)


def fields_for_subtype(subtype: str | None) -> tuple[str, ...]:
    """Every field shown for this device type, read-only ones included."""
    writable = set(writable_for_subtype(subtype))
    return tuple(name for name in ORDER
                 if name in writable or name in READ_ONLY)


def field_list(subtype: str | None = None) -> list[dict]:
    """Field definitions for the screen — known even without reading a device.

    Group values must be enterable regardless: in the field, settings get
    prepared while a device is unreachable. Without `subtype`, every type's
    fields are returned.
    """
    names = fields_for_subtype(subtype) if subtype else ORDER
    out = []
    for name in names:
        field = FIELDS[name]
        out.append({
            "field": name, "label": i18n.t(field.label),
            "section": field.section,
            "sectionLabel": i18n.t(
                SECTION_LABELS.get(field.section, field.section)),
            "editable": bool(field.write_name),
            "kind": field.kind,
            "options": [{"value": value, "label": i18n.t(label)}
                        for value, label in field.options],
            "minimum": field.minimum, "maximum": field.maximum,
            "step": field.step, "secret": field.secret,
            "hint": i18n.t(field.hint) if field.hint else "",
        })
    return out
