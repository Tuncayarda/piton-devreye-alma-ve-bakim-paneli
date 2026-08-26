#!/usr/bin/env python3
"""The configuration write path.

The shared concern here: the panel must send a setting to the endpoint the
device really accepts, with the fields the device wants. The device offers no
single "write settings" endpoint (the main one 405s on POST); audio, modes, UIC
gains and SIP go to separate endpoints, some of them demand all their fields
together, and writing SIP reboots the device.
"""
from __future__ import annotations

import json

from panel import config_sync, settings
from panel.config_sync import apply as apply_module
from panel.inventory import device_map
from panel.config_sync import fields as field_table
from panel.errors import VerificationError

from .support import fakes
from .support.base import PanelTest, ServiceTest

# The UIC's extra fields as seen on the main endpoint (tc/tl gain, thresholds,
# targets).
UIC_SETTINGS = {
    **fakes.ANNOUNCEMENT_SETTINGS, "pbxExtension": "2006",
    "pbxPassword": "2005", "pbxOutExtension": "", "callTimeout": 0,
    "tcSpeakerGain": 1, "tcMicGain": 1, "tlSpeakerGain": 2, "tlMicGain": 1,
    "target1": "2002", "target2": "", "target3": "2002", "target4": "",
    "tcHigh": 5, "tcLow": 2.5, "tlHigh": 5, "tlLow": 2.5,
}

HANDSET_MODES = {"answerMode": 0, "hangupMode": 2, "callMode": 1,
                 "pttEnabled": 1, "speakerGain": 1, "micGain": 1,
                 "logLevel": 1}


class ConfigWrite(PanelTest):

    def setUp(self):
        super().setUp()
        # Waiting for the device to reboot must not slow the tests down; the
        # wait is shortened, the logic stays the same.
        self._old_wait = apply_module.REBOOT_WAIT
        apply_module.REBOOT_WAIT = 0.5

    def tearDown(self):
        apply_module.REBOOT_WAIT = self._old_wait
        super().tearDown()

    def build(self, subtype="Intercom", **extra):
        topology = fakes.device_map([{
            "Name": f"{subtype}_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": subtype, "Port": "11",
            "Status": {"NoError": True}, **extra,
        }])
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("Announcement")[0]

    # ── distribution across endpoints ────────────────────────────────
    def test_audio_and_sip_go_to_separate_endpoints(self):
        inventory, device = self.build("Intercom", PBXExtension="2001",
                                       PBXPassword="2001")
        config_sync.set_group_target("Intercom", "speakerVolume", "85",
                                     "Intercom")
        config_sync.set_target(device.id, "sipExtension", "2007", "Intercom")
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            result = config_sync.apply_targets(device, inventory, None,
                                               "Intercom")
            writes = fakes.announcement_writes(fake)
            state = dict(fake.state)

        self.assertEqual(state["speakerVolume"], 85)
        self.assertEqual(state["pbxExtension"], "2007")
        self.assertIn("/api/v1/audio/volume", writes)
        self.assertIn("/api/v1/sip/settings", writes)
        # The main endpoint is read-only; no write may be attempted there.
        self.assertNotIn("/api/v1/system/settings", writes)
        # SIP is written last: the device reboots after that request.
        self.assertEqual(writes[-1], "/api/v1/sip/settings")
        self.assertTrue(result["rebooted"])

    def test_no_request_is_sent_for_a_setting_that_already_matches(self):
        """If the target equals the device's value, the device is untouched.

        The SIP endpoint reboots the device; "write everything every time"
        would black out the whole set for nothing.
        """
        inventory, device = self.build("Intercom", PBXExtension="2001",
                                       PBXPassword="2001")
        config_sync.set_group_target("Intercom", "speakerVolume", "70",
                                     "Intercom")
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            result = config_sync.apply_targets(device, inventory, None,
                                               "Intercom")
            writes = fakes.announcement_writes(fake)

        self.assertEqual(writes, [])
        self.assertEqual(result["writtenFields"], [])
        self.assertFalse(result["rebooted"])

    def test_the_sip_endpoints_required_fields_are_completed(self):
        """Even changing only the outbound number, SIP demands the triple.

        Without pbxIp/pbxExtension/pbxPassword the device refuses with
        "Missing required fields"; the missing ones are filled from what was
        read off the device.
        """
        inventory, device = self.build("Intercom")
        config_sync.set_target(device.id, "sipOutbound", "5009", "Intercom")
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "Intercom")
            state = dict(fake.state)

        self.assertEqual(state["pbxOutExtension"], "5009")
        # The password and extension already on the device must be preserved
        self.assertEqual(state["pbxPassword"], "2001")
        self.assertEqual(state["pbxExtension"], "2001")

    def test_handset_modes_go_to_the_modes_endpoint_as_a_set_of_four(self):
        inventory, device = self.build("Handset")
        config_sync.set_target(device.id, "answerMode", "1", "Handset")
        with fakes.announcement(modes=HANDSET_MODES) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "Handset")
            writes = fakes.announcement_writes(fake)
            modes = dict(fake.mode_state)

        self.assertEqual(writes, ["/api/v1/system/modes"])
        self.assertEqual(modes["answerMode"], 1)
        # The unchanged mode fields must be sent too, or the device would say
        # "Missing mode fields".
        self.assertEqual(modes["hangupMode"], 2)
        self.assertEqual(modes["pttEnabled"], 1)

    def test_handset_gain_goes_to_the_modes_endpoint_not_audio(self):
        inventory, device = self.build("Handset")
        config_sync.set_target(device.id, "speakerGain", "8", "Handset")
        with fakes.announcement(modes=HANDSET_MODES) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "Handset")
            writes = fakes.announcement_writes(fake)
            modes = dict(fake.mode_state)

        self.assertEqual(writes, ["/api/v1/system/modes"])
        self.assertEqual(modes["speakerGain"], 8)

    def test_the_four_uic_gains_travel_together(self):
        inventory, device = self.build("UIC")
        config_sync.set_target(device.id, "tcSpeakerGain", "4", "UIC")
        with fakes.announcement(settings=UIC_SETTINGS) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "UIC")
            writes = fakes.announcement_writes(fake)
            state = dict(fake.state)

        self.assertEqual(writes, ["/api/v1/uic/gains"])
        self.assertEqual(state["tcSpeakerGain"], 4)
        self.assertEqual(state["tlSpeakerGain"], 2)   # unchanged, preserved

    def test_uic_thresholds_and_targets_go_to_the_sip_endpoint(self):
        inventory, device = self.build("UIC")
        config_sync.set_group_target("UIC", "tcHigh", "4.5", "UIC")
        config_sync.set_group_target("UIC", "tlOutbound", "2003", "UIC")
        with fakes.announcement(settings=UIC_SETTINGS) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "UIC")
            writes = fakes.announcement_writes(fake)
            state = dict(fake.state)

        self.assertEqual(writes, ["/api/v1/sip/settings"])
        self.assertEqual(state["tcHigh"], 4.5)        # sent as a decimal
        self.assertEqual(state["target2"], "2003")

    def test_a_decimal_threshold_survives_float32_rounding(self):
        """The device returns 2.4 as 2.4000000953674316.

        Comparing for exact equality made a written threshold look like "the
        device did not write it", and the next apply rewrote it for nothing,
        rebooting the device needlessly.
        """
        inventory, device = self.build("UIC")
        config_sync.set_group_target("UIC", "tcLow", "2.4", "UIC")
        with fakes.announcement(settings=UIC_SETTINGS) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "UIC")
            self.assertNotEqual(fake.state["tcLow"], 2.4)   # float32 noise
            # A second apply does not rewrite the same threshold
            second = config_sync.apply_targets(device, inventory, None, "UIC")
            self.assertEqual(second["writtenFields"], [])
            # The screen shows the entered value, not the noise
            row = next(r for r in second["rows"] if r["field"] == "tcLow")
            self.assertEqual(row["current"], "2.4")
            self.assertEqual(row["comparison"], "match")

    def test_the_extension_is_written_as_the_password_when_devicemap_lacks_one(
            self):
        """The SIP password is the same as the extension.

        A UIC/Amplifier record has no PBXPassword, but the SIP endpoint
        requires one. The device's old password used to be preserved and the
        device could not register with the PBX.
        """
        inventory, device = self.build("UIC", PBXExtension="4001")
        self.assertIsNone(device.pbx_password)
        with fakes.announcement(settings=UIC_SETTINGS) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "UIC")
            state = dict(fake.state)

        self.assertEqual(state["pbxExtension"], "4001")   # DeviceMap target
        self.assertEqual(state["pbxPassword"], "4001")    # same as the number

    def test_an_extension_entered_on_screen_changes_the_password_too(self):
        """When the number changes on screen, the password goes with it."""
        inventory, device = self.build("UIC", PBXExtension="4001")
        config_sync.set_target(device.id, "sipExtension", "4009", "UIC")
        with fakes.announcement(settings=UIC_SETTINGS) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "UIC")
            state = dict(fake.state)

        self.assertEqual(state["pbxExtension"], "4009")
        self.assertEqual(state["pbxPassword"], "4009")

    def test_an_explicit_devicemap_password_is_used(self):
        """A password written explicitly in the project is not derived."""
        inventory, device = self.build("Intercom", PBXExtension="2001",
                                       PBXPassword="custom-password")
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "Intercom")
            state = dict(fake.state)

        self.assertEqual(state["pbxExtension"], "2001")
        self.assertEqual(state["pbxPassword"], "custom-password")

    def test_a_device_that_hides_the_password_is_not_a_failure(self):
        """A masked secret field does not make the write a failure.

        A secret whose value cannot be read off the device cannot be verified;
        but not being readable does not mean "the device did not write it".
        """
        inventory, device = self.build("UIC", PBXExtension="4001")
        without_password = {k: v for k, v in UIC_SETTINGS.items()
                            if k != "pbxPassword"}
        with fakes.announcement(settings=without_password) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            result = config_sync.apply_targets(device, inventory, None, "UIC")
            self.assertEqual(fake.state["pbxExtension"], "4001")
        self.assertIn("SIP extension", result["writtenFields"])

    def test_a_silently_dropped_field_is_an_error(self):
        """HTTP 200 alone is not success; the write is verified by reading."""
        inventory, device = self.build("Intercom")
        config_sync.set_target(device.id, "speakerVolume", "85", "Intercom")
        # The device accepts the request with 200 and drops the field (its
        # field behaviour for a field it does not know).
        with fakes.announcement(ignore=("speakerVolume",)) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            with self.assertRaises(VerificationError) as caught:
                config_sync.apply_targets(device, inventory, None, "Intercom")
            self.assertEqual(fake.state["speakerVolume"], 70)
        self.assertIn("did not write", str(caught.exception))

    # ── field tables ─────────────────────────────────────────────────
    def test_the_field_list_varies_by_device_type(self):
        def names(subtype):
            return {f["field"] for f in config_sync.field_list(subtype)}

        amp, intercom, handset, uic = (names("Amplifier"), names("Intercom"),
                                       names("Handset"), names("UIC"))
        # An Amplifier has no microphone
        self.assertNotIn("micVolume", amp)
        self.assertNotIn("micGain", amp)
        self.assertIn("speakerGain", amp)
        # The outbound number is on neither the Amplifier nor the UIC page
        self.assertIn("sipOutbound", intercom)
        self.assertNotIn("sipOutbound", amp)
        self.assertNotIn("sipOutbound", uic)
        # Modes only on the Handset, thresholds/targets only on the UIC
        self.assertIn("hangupMode", handset)
        self.assertNotIn("hangupMode", intercom)
        self.assertIn("tcHigh", uic)
        self.assertIn("tlInbound", uic)
        self.assertNotIn("tcHigh", handset)
        # Read-only fields appear on every type
        for group in (amp, intercom, handset, uic):
            self.assertIn("version", group)

    def test_the_project_audio_defaults(self):
        """The supported announcement types share the required audio base."""
        data = json.loads((settings.ROOT / "DeviceMap.json").read_text(
            encoding="utf-8"))["Config"]
        amp = data["Announcement/Amplifier"]
        intercom = data["Announcement/Intercom"]
        handset = data["Announcement/Handset"]
        uic = data["Announcement/UIC"]

        self.assertEqual(intercom["MicVolume"], 100)
        self.assertEqual(handset["MicVolume"], 100)
        self.assertEqual(uic["MicVolume"], 100)
        self.assertEqual(amp["SpeakerGain"], 1)
        self.assertEqual(intercom["SpeakerGain"], 1)
        self.assertEqual(handset["SpeakerGain"], 1)
        self.assertEqual(uic["TcSpeakerGain"], 1)
        self.assertEqual(uic["TlSpeakerGain"], 1)
        for block in (amp, intercom, handset, uic):
            self.assertEqual(block["LogLevel"], 1)

    def test_the_sip_registration_row_is_shown_read_only(self):
        """Whether the registration held after writing the extension.

        The device may have accepted the setting yet failed to register with
        the PBX; write verification does not show that.
        """
        inventory, device = self.build("UIC")
        with fakes.announcement(
                settings={**UIC_SETTINGS, "status": "Unregistered"}) as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            row = next(r for r in config_sync.fetch(device, inventory)["rows"]
                       if r["field"] == "sipRegistration")
        self.assertEqual(row["current"], "Unregistered")
        self.assertFalse(row["editable"])

    def test_the_endpoints_match_the_device_type(self):
        self.assertEqual(field_table.endpoint_for("speakerGain", "Handset"),
                         field_table.MODES_ENDPOINT)
        self.assertEqual(field_table.endpoint_for("speakerGain", "Intercom"),
                         field_table.AUDIO_ENDPOINT)
        self.assertEqual(field_table.endpoint_for("logLevel", "UIC"),
                         field_table.AUDIO_ENDPOINT)
        self.assertEqual(field_table.endpoint_for("tcHigh", "UIC"),
                         field_table.SIP_ENDPOINT)
        self.assertIsNone(field_table.endpoint_for("tcHigh", "Intercom"))

    # ── value validation ─────────────────────────────────────────────
    def test_an_invalid_value_is_rejected_as_it_is_entered(self):
        _inventory, device = self.build("Intercom")
        for name, value in (("speakerVolume", "150"),
                            ("speakerVolume", "abc"),
                            ("speakerGain", "3"), ("sipPbx", "10.1.1"),
                            ("sipExtension", "20 01"), ("logLevel", "5")):
            with self.assertRaises(ValueError, msg=f"{name}={value}"):
                config_sync.set_target(device.id, name, value, "Intercom")
        # A UIC threshold sits in the 0–5 V range
        with self.assertRaises(ValueError):
            config_sync.set_target(device.id, "tcHigh", "9", "UIC")
        # A field absent from that device type is rejected too
        with self.assertRaises(ValueError):
            config_sync.set_target(device.id, "hangupMode", "1", "Intercom")

    def test_a_valid_value_is_accepted(self):
        _inventory, device = self.build("Intercom")
        config_sync.set_target(device.id, "speakerVolume", "85", "Intercom")
        config_sync.set_target(device.id, "speakerGain", "8", "Intercom")
        config_sync.set_target(device.id, "sipPbx", "10.1.1.1", "Intercom")
        self.assertEqual(config_sync.targets.device_targets(device.id),
                         {"speakerVolume": "85", "speakerGain": "8",
                          "sipPbx": "10.1.1.1"})
        # An empty value removes the device-specific target
        config_sync.set_target(device.id, "speakerVolume", "", "Intercom")
        self.assertNotIn("speakerVolume",
                         config_sync.targets.device_targets(device.id))


class DeviceMapConfig(PanelTest):
    """Settings defined in DeviceMap arrive as built-in target values.

    If the user touches no box, this is what is written to the device; the
    field name is the device's own field name (SpeakerVolume, Target1…) and the
    panel keeps no extra mapping table.
    """

    def setUp(self):
        super().setUp()
        self._old_wait = apply_module.REBOOT_WAIT
        apply_module.REBOOT_WAIT = 0.5

    def tearDown(self):
        apply_module.REBOOT_WAIT = self._old_wait
        super().tearDown()

    def build(self, config=None, device_extra=None, subtype="Intercom",
              second=None):
        devices = [{
            "Name": f"{subtype}_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": subtype, "Port": "11",
            "Status": {"NoError": True}, **(device_extra or {}),
        }]
        if second:
            devices.append({
                "Name": f"{subtype}_2", "IP": "127.0.0.1", "IsActive": True,
                "Type": "Announcement", "SubType": subtype, "Port": "12",
                "Status": {"NoError": True}, **second,
            })
        topology = fakes.device_map(devices)
        if config:
            topology["Config"] = config
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("Announcement")

    def test_a_type_config_block_becomes_the_target(self):
        inventory, (device,) = self.build(
            config={"Announcement": {"SpeakerVolume": 85},
                    "Announcement/Intercom": {"MicGain": 4}})
        self.assertEqual(
            config_sync.resolve_target(device, inventory, "speakerVolume"),
            ("85", "project"))
        self.assertEqual(
            config_sync.resolve_target(device, inventory, "micGain"),
            ("4", "project"))

    def test_the_device_record_overrides_the_type_block(self):
        inventory, (device,) = self.build(
            config={"Announcement": {"SpeakerVolume": 85}},
            device_extra={"SpeakerVolume": 60})
        self.assertEqual(
            config_sync.resolve_target(device, inventory, "speakerVolume"),
            ("60", "project"))

    def test_a_user_value_overrides_devicemap(self):
        inventory, (device,) = self.build(
            config={"Announcement": {"SpeakerVolume": 85}})
        config_sync.set_target(device.id, "speakerVolume", "42", "Intercom")
        self.assertEqual(
            config_sync.resolve_target(device, inventory, "speakerVolume"),
            ("42", "device"))

    def test_a_devicemap_setting_is_written_untouched(self):
        inventory, (device,) = self.build(config={
            "Announcement/Intercom": {"SpeakerVolume": 85, "MicVolume": 55,
                                      "SpeakerGain": 8, "LogLevel": 0}})
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            result = config_sync.apply_targets(device, inventory, None,
                                               "Intercom")
            state = dict(fake.state)
        self.assertEqual(
            (state["speakerVolume"], state["micVolume"], state["speakerGain"],
             state["logLevel"]), (85, 55, 8, 0))
        # The audio settings went to one endpoint and SIP was untouched (the
        # device did not reboot)
        self.assertFalse(result["rebooted"])

    def test_an_invalid_devicemap_value_is_not_written(self):
        """Bad project data does not reach the device; the row says why."""
        inventory, (device,) = self.build(
            config={"Announcement": {"SpeakerVolume": 150, "SpeakerGain": 3}})
        self.assertEqual(
            config_sync.resolve_target(device, inventory, "speakerVolume"),
            ("", ""))
        _value, _source, warning = config_sync.target_detail(
            device, inventory, "speakerVolume")
        self.assertIn("DeviceMap", warning)
        self.assertIn("between 0 and 100", warning)
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            row = next(r for r in config_sync.fetch(device, inventory)["rows"]
                       if r["field"] == "speakerGain")
            self.assertIn("DeviceMap", row["warning"])
            self.assertEqual(fake.state["speakerVolume"], 70)   # unchanged

    def test_the_group_summary_separates_shared_from_varying(self):
        """A shared value fills the box, a per-device one does not.

        The extension differs on every device; writing one number to the group
        would give every device the same number.
        """
        from panel.config_sync.targets import group_project_summary

        inventory, devices = self.build(
            config={"Announcement": {"SpeakerVolume": 85}},
            device_extra={"PBXExtension": "2001"},
            second={"PBXExtension": "2002"})
        shared, varying = group_project_summary(inventory, devices)
        self.assertEqual(shared.get("speakerVolume"), "85")
        self.assertIn("sipExtension", varying)
        self.assertNotIn("sipExtension", shared)


class SavedDefaults(PanelTest):
    """Entered values are written to a file and restored at start-up.

    A password NEVER reaches the file: it stays in memory for the session.
    """

    PASSWORD = "sip-parolasi-4471"

    def build(self, subtype="Intercom"):
        topology = fakes.device_map([{
            "Name": f"{subtype}_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": subtype, "Port": "11",
            "PBXExtension": "2001", "Status": {"NoError": True},
        }])
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("Announcement")[0]

    def test_an_entered_value_is_saved_and_restored(self):
        inventory, device = self.build()
        config_sync.set_group_target("Intercom", "speakerVolume", "85",
                                     "Intercom")
        config_sync.set_target(device.id, "sipOutbound", "5009", "Intercom")
        self.assertTrue(settings.config_defaults_file().exists())

        # Application shutdown: memory empties, the file stays.
        config_sync.forget_targets()
        self.assertEqual(config_sync.group_targets("Intercom"), {})

        # Reopening
        self.assertEqual(config_sync.load_saved_defaults(), 2)
        self.assertEqual(config_sync.group_targets("Intercom"),
                         {"speakerVolume": "85"})
        self.assertEqual(config_sync.targets.device_targets(device.id),
                         {"sipOutbound": "5009"})
        self.assertEqual(
            config_sync.resolve_target(device, inventory, "speakerVolume",
                                       "Intercom"),
            ("85", "group"))

    def test_the_same_device_and_group_are_kept_apart_across_sets(self):
        _inventory, device = self.build()
        config_sync.set_group_target("Intercom", "speakerVolume", "85",
                                     "Intercom", set_no=1)
        config_sync.set_group_target("Intercom", "speakerVolume", "42",
                                     "Intercom", set_no=2)
        config_sync.set_target(device.id, "sipOutbound", "5001", "Intercom",
                               set_no=1)
        config_sync.set_target(device.id, "sipOutbound", "5002", "Intercom",
                               set_no=2)

        self.assertEqual(config_sync.group_targets("Intercom", set_no=1),
                         {"speakerVolume": "85"})
        self.assertEqual(config_sync.group_targets("Intercom", set_no=2),
                         {"speakerVolume": "42"})
        self.assertEqual(
            config_sync.targets.device_targets(device.id, set_no=1),
            {"sipOutbound": "5001"})
        self.assertEqual(
            config_sync.targets.device_targets(device.id, set_no=2),
            {"sipOutbound": "5002"})

        # The persistent format carries the set outside the key explicitly.
        body = json.loads(settings.config_defaults_file().read_text(
            encoding="utf-8"))
        self.assertEqual(body["format"], 3)
        self.assertEqual(body["sets"]["1"]["groups"]["Intercom"]
                         ["speakerVolume"], "85")
        self.assertEqual(body["sets"]["2"]["groups"]["Intercom"]
                         ["speakerVolume"], "42")

        config_sync.forget_targets()
        self.assertEqual(config_sync.load_saved_defaults(), 4)
        self.assertEqual(
            config_sync.targets.device_targets(device.id,
                                               set_no=1)["sipOutbound"],
            "5001")
        self.assertEqual(
            config_sync.targets.device_targets(device.id,
                                               set_no=2)["sipOutbound"],
            "5002")

    def test_a_password_is_not_written_to_the_file(self):
        _inventory, device = self.build()
        config_sync.set_group_target("Intercom", "sipPassword", self.PASSWORD,
                                     "Intercom")
        config_sync.set_target(device.id, "sipPassword", self.PASSWORD,
                               "Intercom")
        path = settings.config_defaults_file()
        # The file was either never created or does not contain the password
        if path.exists():
            self.assertNotIn(self.PASSWORD, path.read_text(encoding="utf-8"))
        # Reloading does not bring it back, and what is in memory is cleared
        config_sync.forget_targets()
        config_sync.load_saved_defaults()
        self.assertEqual(config_sync.group_targets("Intercom"), {})
        self.assertEqual(config_sync.targets.device_targets(device.id), {})

    def test_an_empty_value_is_removed_from_the_record_too(self):
        _inventory, _device = self.build()
        config_sync.set_group_target("Intercom", "speakerVolume", "85",
                                     "Intercom")
        config_sync.set_group_target("Intercom", "speakerVolume", "",
                                     "Intercom")
        config_sync.forget_targets()
        self.assertEqual(config_sync.load_saved_defaults(), 0)

    def test_a_corrupt_file_does_not_stop_the_panel(self):
        self.build()
        path = settings.config_defaults_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{this is not valid json", encoding="utf-8")
        self.assertEqual(config_sync.load_saved_defaults(), 0)

    def test_invalid_and_unknown_fields_are_skipped(self):
        """An old or hand-edited file must not write a wrong value."""
        self.build()
        path = settings.config_defaults_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"format": 3, "sets": {"1": {
            "groups": {"Intercom": {
                "speakerVolume": "150",   # out of range
                "speakerGain": "3",       # not one of the choices
                "olmayanAlan": "1",       # a field that no longer exists
                "micVolume": "44",        # valid
            }}}}}), encoding="utf-8")
        self.assertEqual(config_sync.load_saved_defaults(), 1)
        self.assertEqual(config_sync.group_targets("Intercom"),
                         {"micVolume": "44"})

    def test_a_file_from_an_unknown_format_is_ignored(self):
        """Nothing is guessed out of a file this version does not understand.

        A value read from an unknown layout would be written to a device, so
        the file is left alone instead: no target is loaded, and nothing from
        it leaks into any set.
        """
        _inventory, device = self.build()
        path = settings.config_defaults_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "format": 1,
            "groups": {"Intercom": {"speakerVolume": "85"}},
            "devices": {device.id: {"sipOutbound": "5009"}},
        }), encoding="utf-8")

        self.assertEqual(config_sync.load_saved_defaults(), 0)
        for set_no in (1, 2):
            self.assertEqual(
                config_sync.group_targets("Intercom", set_no=set_no), {})
            self.assertEqual(
                config_sync.targets.device_targets(device.id, set_no=set_no),
                {})
        self.assertEqual(
            config_sync.saved_defaults_summary(1)["unscopedValues"], 0)

    def test_resetting_one_set_preserves_the_other(self):
        _inventory, _device = self.build()
        config_sync.set_group_target("Intercom", "speakerVolume", "85",
                                     "Intercom", set_no=1)
        config_sync.set_group_target("Intercom", "speakerVolume", "42",
                                     "Intercom", set_no=2)

        config_sync.clear_saved_defaults(1)

        self.assertEqual(config_sync.group_targets("Intercom", set_no=1), {})
        self.assertEqual(config_sync.group_targets("Intercom", set_no=2),
                         {"speakerVolume": "42"})
        config_sync.forget_targets()
        self.assertEqual(config_sync.load_saved_defaults(), 1)
        self.assertEqual(config_sync.group_targets("Intercom", set_no=2),
                         {"speakerVolume": "42"})

    def test_a_reset_deletes_the_file_too(self):
        _inventory, _device = self.build()
        config_sync.set_group_target("Intercom", "speakerVolume", "85",
                                     "Intercom")
        config_sync.clear_saved_defaults()
        self.assertFalse(settings.config_defaults_file().exists())
        self.assertEqual(config_sync.group_targets("Intercom"), {})

    def test_the_data_directory_is_outside_the_project_tree(self):
        """The persistent file goes neither into the tree nor beside DeviceMap."""
        self.build()
        path = settings.config_defaults_file().resolve()
        self.assertFalse(str(path).startswith(str(settings.ROOT.resolve())))
        self.assertNotEqual(path.parent, self.map_path.parent)


class FastFieldEndpoint(ServiceTest):
    """When the group changes, the screen does not wait for a device read."""

    def build(self):
        topology = fakes.device_map([{
            "Name": "Uic", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "UIC", "Port": "3",
            "PBXExtension": "4001", "Status": {"NoError": True},
        }])
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("Announcement")[0]

    def test_the_fields_endpoint_never_reaches_the_device(self):
        _inventory, device = self.build()
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            base = self.start_service()
            code, body = self.call(
                base, f"/api/config/fields?set=1&id={device.id}&group=UIC")
            self.assertEqual(code, 200)
            self.assertEqual(fake.request_count, 0)   # no device request
        self.assertTrue(body["reading"])
        self.assertEqual(body["rows"], [])
        # Everything the screen needs to draw at once is here
        names = {f["field"] for f in body["fields"]}
        self.assertIn("tcHigh", names)
        self.assertEqual(body["projectShared"].get("sipExtension"), "4001")

    def test_the_api_set_parameter_separates_the_group_target(self):
        _inventory, device = self.build()
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            base = self.start_service()
            for set_no, value in ((1, "85"), (2, "42")):
                code, _body = self.call(base, "/api/config/target", {
                    "set": set_no, "deviceId": device.id,
                    "field": "speakerVolume", "value": value,
                    "group": "UIC", "scope": "group"})
                self.assertEqual(code, 200)

            _c1, set1 = self.call(
                base, f"/api/config/fields?set=1&id={device.id}&group=UIC")
            _c2, set2 = self.call(
                base, f"/api/config/fields?set=2&id={device.id}&group=UIC")

        self.assertEqual(set1["groupTargets"]["speakerVolume"], "85")
        self.assertEqual(set2["groupTargets"]["speakerVolume"], "42")
        self.assertEqual(set1["savedDefaults"]["setNo"], 1)
        self.assertEqual(set2["savedDefaults"]["setNo"], 2)

    def test_the_config_read_tries_no_unnecessary_endpoint(self):
        """A device read finishes in one request; two on a Handset (modes)."""
        _inventory, device = self.build()
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            inventory = self.build_map(fakes.device_map([{
                "Name": "Uic", "IP": "127.0.0.1", "IsActive": True,
                "Type": "Announcement", "SubType": "UIC", "Port": "3",
                "Status": {"NoError": True}}]))
            config_sync.fetch(device, inventory, None, "UIC")
            self.assertEqual(fakes.announcement_writes(fake), [])
            self.assertEqual(fake.request_count, 1)


class SipPassword(ServiceTest):
    """The SIP password can be written but never comes back in a reply."""

    PASSWORD = "sip-parolasi-9713"

    def build(self):
        topology = fakes.device_map([{
            "Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "Intercom", "Port": "11",
            "PBXExtension": "2001", "PBXPassword": "2001",
            "Status": {"NoError": True},
        }])
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("Announcement")[0]

    def test_the_password_appears_in_no_reply(self):
        _inventory, device = self.build()
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            base = self.start_service()
            code, body = self.call(base, "/api/config/target", {
                "set": 1, "deviceId": device.id, "field": "sipPassword",
                "value": self.PASSWORD, "group": "Intercom",
                "scope": "group"})
            self.assertEqual(code, 200)
            self.assertNotIn(self.PASSWORD,
                             json.dumps(body, ensure_ascii=False))

            _code2, config = self.call(
                base, f"/api/config?set=1&id={device.id}&group=Intercom")
            self.assertNotIn(self.PASSWORD,
                             json.dumps(config, ensure_ascii=False))
            # The row still reports the state: the entered password differs
            # from the device's, so it must read "differs".
            row = next(r for r in config["rows"]
                       if r["field"] == "sipPassword")
            self.assertEqual(row["comparison"], "differs")
            self.assertEqual(row["source"], "group")
            self.assertEqual(row["current"], "")
            self.assertTrue(row["hasCurrent"])
            self.assertIn("sipPassword", config["groupSecrets"])
            self.assertEqual(config["groupTargets"].get("sipPassword", ""), "")

    def test_an_entered_password_is_written_to_the_device(self):
        inventory, device = self.build()
        config_sync.set_group_target("Intercom", "sipPassword", self.PASSWORD,
                                     "Intercom")
        previous = apply_module.REBOOT_WAIT
        apply_module.REBOOT_WAIT = 0.5
        self.addCleanup(setattr, apply_module, "REBOOT_WAIT", previous)
        with fakes.announcement() as fake:
            settings.ANNOUNCEMENT_PORT = fake.port
            config_sync.apply_targets(device, inventory, None, "Intercom")
            self.assertEqual(fake.state["pbxPassword"], self.PASSWORD)

    def test_the_devicemap_password_is_absent_from_the_dto(self):
        _inventory, device = self.build()
        self.assertEqual(device.pbx_password, "2001")
        self.assertNotIn("2001", json.dumps(
            {k: v for k, v in device.dto().items() if k != "pbxExtension"}))


if __name__ == "__main__":
    import unittest
    unittest.main()


class CompartmentLcdSettings(PanelTest):
    """The display's one writable setting: its own address.

    Everything else on this screen goes to an HTTP endpoint the device's web
    UI also posts to. An Android display has no such API, so its row is
    written over ADB — and the rule that decides success is the same one the
    commissioning run uses: the SAME serial has to answer at the NEW address
    with nothing else left on eth0.
    """

    def build(self, ip="10.n.1.40"):
        topology = fakes.device_map([{
            "Name": "Compartment_Lcd_1", "IP": ip, "IsActive": True,
            "Type": "LCD", "SubType": "Compartment", "Port": "13",
            "PBXExtension": "6001", "Status": {},
        }])
        inventory = self.build_map(topology)
        return inventory, inventory.by_type("LCD")[0]

    def fake_display(self, address="10.1.1.40", prefix=24, serial="LCD-40"):
        """A display that really moves when its address is written."""
        state = {"address": address, "prefix": prefix, "serial": serial,
                 "writes": []}

        def connect(ip, attempts=1):
            return ip == state["address"]

        def addresses(ip):
            return {f"{state['address']}/{state['prefix']}"}

        def write_address(ip, target_ip, prefix):
            state["writes"].append((ip, target_ip, prefix))
            state["address"] = target_ip

        self.patch_module(connect=connect, addresses=addresses,
                          serial_of=lambda ip: state["serial"],
                          write_address=write_address,
                          disconnect=lambda ip: None)
        return state

    def patch_module(self, **members):
        from panel.config_sync import adb_network
        previous = {}
        for name, value in members.items():
            previous[name] = getattr(adb_network.lcd_runner, name)
            setattr(adb_network.lcd_runner, name, value)
        self.addCleanup(lambda: [setattr(adb_network.lcd_runner, name, value)
                                 for name, value in previous.items()])

    def read_reports(self, version="0.0.5", serial="LCD-40"):
        from panel.probe import android
        previous = android.read
        android.read = lambda ip, timeout=None: {
            "serial": serial, "version": version,
            "sipRegistration": "registered", "sipExtension": "6001",
        }
        self.addCleanup(lambda: setattr(android, "read", previous))

    def test_a_display_offers_its_address_and_nothing_else_to_write(self):
        self.assertEqual(
            field_table.writable_for_scope("Compartment"), ("ipAddress",))
        self.assertEqual(
            field_table.endpoint_for("ipAddress", "Compartment"),
            field_table.ADB_NETWORK)
        # And the ADB marker is never in the HTTP write loop's order.
        self.assertNotIn(field_table.ADB_NETWORK, field_table.ENDPOINT_ORDER)

    def test_the_screen_shows_the_address_eth0_really_holds(self):
        inventory, device = self.build()
        self.fake_display(address="10.1.1.40")
        self.read_reports()

        rows = {row["field"]: row
                for row in config_sync.fetch(device, inventory)["rows"]}

        self.assertEqual(rows["ipAddress"]["current"], "10.1.1.40")
        # DeviceMap says where it SHOULD be; the display is still on set 1.
        self.assertEqual(rows["ipAddress"]["target"], "10.1.1.40")
        self.assertEqual(rows["version"]["current"], "0.0.5")
        self.assertEqual(rows["serial"]["current"], "LCD-40")
        self.assertEqual(rows["sipRegistration"]["current"], "registered")

    def test_the_devicemap_target_is_resolved_for_the_open_set(self):
        """`extra["IP"]` holds the TEMPLATE "10.n.1.40".

        Offering that as the target would ask the screen for an address that
        cannot exist; what the display should hold is the template resolved
        for the set that is open.
        """
        self.build()
        seven = device_map.load(7, self.map_path, cache=False)
        device = seven.by_type("LCD")[0]
        self.assertEqual(device.ip, "10.7.1.40")
        self.fake_display(address="10.7.1.40")
        self.read_reports()

        rows = {row["field"]: row
                for row in config_sync.fetch(device, seven)["rows"]}

        self.assertEqual(rows["ipAddress"]["target"], "10.7.1.40")
        # With the template offered instead, this row would read "differs"
        # against an address no device can hold.
        self.assertEqual(rows["ipAddress"]["comparison"], "match")

    def test_an_entered_address_is_written_and_read_back_at_the_new_one(self):
        inventory, device = self.build()
        state = self.fake_display(address="10.1.1.40")
        self.read_reports()
        config_sync.set_target(device.id, "ipAddress", "10.1.1.44",
                              "Compartment", set_no=inventory.set_no)

        result = config_sync.apply_targets(device, inventory)

        self.assertEqual(state["writes"], [("10.1.1.40", "10.1.1.44", 24)])
        rows = {row["field"]: row for row in result["rows"]}
        self.assertEqual(rows["ipAddress"]["current"], "10.1.1.44")
        self.assertEqual(result["writtenFields"], ["IP address"])

    def test_the_mask_the_display_is_using_is_preserved(self):
        """Changing the mask is a commissioning decision, not a settings row."""
        inventory, device = self.build()
        state = self.fake_display(address="10.1.1.40", prefix=8)
        self.read_reports()
        config_sync.set_target(device.id, "ipAddress", "10.1.1.44",
                              "Compartment", set_no=inventory.set_no)

        config_sync.apply_targets(device, inventory)

        self.assertEqual(state["writes"], [("10.1.1.40", "10.1.1.44", 8)])

    def test_an_address_that_already_matches_sends_no_command(self):
        inventory, device = self.build()
        state = self.fake_display(address="10.1.1.40")
        self.read_reports()

        result = config_sync.apply_targets(device, inventory)

        self.assertEqual(state["writes"], [])
        self.assertEqual(result["writtenFields"], [])

    def test_a_different_serial_at_the_new_address_fails_the_write(self):
        """Two displays swapped on the bench must not read as success."""
        inventory, device = self.build()
        state = self.fake_display(address="10.1.1.40")
        self.read_reports()

        original = state["serial"]

        def moved_serial(ip):
            return original if ip == "10.1.1.40" else "SOMEONE-ELSE"

        self.patch_module(serial_of=moved_serial)
        config_sync.set_target(device.id, "ipAddress", "10.1.1.44",
                              "Compartment", set_no=inventory.set_no)

        with self.assertRaises(VerificationError) as caught:
            config_sync.apply_targets(device, inventory)
        self.assertIn("SOMEONE-ELSE", str(caught.exception))

    def test_a_display_with_no_app_still_shows_and_writes_its_address(self):
        """The display most likely to need repairing is the broken one.

        An unreadable application version fails the ordinary device read, and
        should. It must not take the one row this screen can write with it.
        """
        inventory, device = self.build()
        state = self.fake_display(address="10.1.1.40")
        from panel.probe import android
        previous = android.read

        def explode(ip, timeout=None):
            raise VerificationError("the app version could not be read")

        android.read = explode
        self.addCleanup(lambda: setattr(android, "read", previous))
        config_sync.set_target(device.id, "ipAddress", "10.1.1.44",
                              "Compartment", set_no=inventory.set_no)

        rows = {row["field"]: row
                for row in config_sync.fetch(device, inventory)["rows"]}
        self.assertEqual(rows["ipAddress"]["current"], "10.1.1.40")
        self.assertEqual(rows["version"]["current"], "")
        # The serial comes from the display itself, not from the app read.
        self.assertEqual(rows["serial"]["current"], "LCD-40")

        config_sync.apply_targets(device, inventory)
        self.assertEqual(state["writes"], [("10.1.1.40", "10.1.1.44", 24)])

    def test_a_leftover_old_address_on_eth0_fails_the_write(self):
        inventory, device = self.build()
        self.fake_display(address="10.1.1.40")
        self.read_reports()
        self.patch_module(
            addresses=lambda ip: {"10.1.1.44/24", "10.1.1.40/24"})
        config_sync.set_target(device.id, "ipAddress", "10.1.1.44",
                              "Compartment", set_no=inventory.set_no)

        with self.assertRaises(VerificationError):
            config_sync.apply_targets(device, inventory)
