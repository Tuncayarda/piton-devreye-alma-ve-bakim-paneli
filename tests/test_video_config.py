#!/usr/bin/env python3
"""Camera and NVR configuration over ISAPI.

The shared concern here is what the field scripts learned on the hardware and
the panel must not lose:

  · a camera's third stream cannot be written until it is enabled, and
    enabling it reboots the camera;
  · a disk is formatted only when it is unusable as it stands — never a
    healthy one, because that would wipe recordings;
  · the NVR's input channels come from the project, and the NVR is restarted
    afterwards so it picks them up;
  · addresses and masks are set by hand in the field. The panel reads them
    and writes NEITHER;
  · motion detection is not part of this project at all.

And the rule the whole configuration screen runs on: a value counts as
written only once it has been read back off the device.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from unittest import mock

import requests

from panel import config_sync, credentials, i18n, settings
from panel.config_sync import fields as field_table
from panel.errors import AuthError, VerificationError
from panel.probe import camera as camera_probe
from panel.video_config import health
from panel.video_config import isapi as video_isapi
from panel.video_config import nvr as nvr_config
from panel.video_config import payloads

from .support import fakes
from .support.base import PanelTest

PASSWORD = "fake-camera-password"
ACCOUNT = ("admin", PASSWORD)

CAMERAS = [
    {"Name": "Corridor_Cam_1", "CameraID": "1", "CameraName": "Corridor 1",
     "IP": "10.n.1.24", "Type": "Camera", "SubType": "Corridor",
     "IsActive": True, "Port": "1", "Status": {"NoError": True}},
    {"Name": "Corridor_Cam_2", "CameraID": "2", "CameraName": "Corridor 2",
     "IP": "10.n.1.25", "Type": "Camera", "SubType": "Corridor",
     "IsActive": True, "Port": "2", "Status": {"NoError": True}},
    {"Name": "Landing_Cam_1", "CameraID": "3", "CameraName": "Landing 1",
     "IP": "10.n.1.26", "Type": "Camera", "SubType": "Landing",
     "IsActive": True, "Port": "3", "Status": {"NoError": True}},
    {"Name": "Landing_Cam_2", "CameraID": "4", "CameraName": "Landing 2",
     "IP": "10.n.1.27", "Type": "Camera", "SubType": "Landing",
     "IsActive": True, "Port": "4", "Status": {"NoError": True}},
]
PISCU = {"Name": "Piscu", "IP": "10.n.1.1", "Type": "PISCU", "SubType": "",
         "IsActive": True, "Port": "7", "Status": {"NoError": True}}
NVR = {"Name": "Nvr", "IP": "127.0.0.1", "Type": "NVR", "SubType": "",
       "IsActive": True, "Port": "5", "Status": {"NoError": True}}

# The channel list the NVR should end up with — DeviceMap's CameraID,
# CameraName and address, resolved for set 1.
EXPECTED_CHANNELS = {
    1: ("Corridor 1", "10.1.1.24"),
    2: ("Corridor 2", "10.1.1.25"),
    3: ("Landing 1", "10.1.1.26"),
    4: ("Landing 2", "10.1.1.27"),
}
EXPECTED_CHANNEL_ADDRESSES = {
    number: ip for number, (_name, ip) in EXPECTED_CHANNELS.items()
}


class VideoTest(PanelTest):

    def setUp(self):
        super().setUp()
        # A device really does take a minute to come back; the tests must not.
        self._waits = (video_isapi.REBOOT_DELAY,
                       video_isapi.REBOOT_ATTEMPTS,
                       video_isapi.REBOOT_INTERVAL)
        video_isapi.REBOOT_DELAY = 0.01
        video_isapi.REBOOT_ATTEMPTS = 3
        video_isapi.REBOOT_INTERVAL = 0.01

    def tearDown(self):
        (video_isapi.REBOOT_DELAY, video_isapi.REBOOT_ATTEMPTS,
         video_isapi.REBOOT_INTERVAL) = self._waits
        super().tearDown()

    def build(self, devices):
        inventory = self.build_map(fakes.device_map(devices))
        return inventory


class CameraConfiguration(VideoTest):

    def build_camera(self):
        """One camera at the fake's address, plus the set's PISCU.

        The camera is the only device the panel talks to here; the PISCU is
        in the map because it is the project's time source.
        """
        inventory = self.build(
            [{**CAMERAS[0], "IP": "127.0.0.1"}, PISCU])
        return inventory, inventory.by_type("Camera")[0]

    def apply(self, fake, inventory, device):
        settings.VIDEO_PORT = fake.port
        return config_sync.apply_targets(device, inventory, ACCOUNT, "Camera")

    def test_a_fresh_camera_is_brought_to_the_project_settings(self):
        inventory, device = self.build_camera()
        with fakes.video_camera() as fake:
            result = self.apply(fake, inventory, device)
            state = dict(fake.state)

        self.assertEqual(state["timezone"], settings.EXPECTED_TIMEZONE)
        # The NTP server is the set's PISCU — here the fake's own address.
        self.assertEqual(state["ntp"], "10.1.1.1")
        self.assertEqual(state["ir"], "close")
        self.assertTrue(state["third"])
        # The stream profiles: the DeviceMap name, audio on (a corridor
        # camera has a microphone) and the project's third-stream size.
        self.assertEqual(state["channels"]["101"]["name"], "Corridor 1")
        self.assertEqual(state["channels"]["101"]["audio"], "true")
        self.assertEqual(state["channels"]["102"]["w"], "320")
        self.assertEqual(state["channels"]["103"]["w"], "1280")
        self.assertEqual(state["channels"]["103"]["h"], "1024")
        self.assertTrue(result["rebooted"])

    def test_nothing_is_written_when_the_camera_already_matches(self):
        """A camera in agreement is not touched, and not restarted."""
        inventory, device = self.build_camera()
        with fakes.video_camera(third_stream=True, ir="close",
                                hdd={"1": "ok"},
                                channel_name="Corridor 1") as fake:
            fake.state["timezone"] = settings.EXPECTED_TIMEZONE
            fake.state["ntp"] = "10.1.1.1"
            fake.state["channels"]["103"] = {"name": "Corridor 1",
                                             "audio": "true",
                                             "w": "1280", "h": "1024"}
            result = self.apply(fake, inventory, device)
            writes = fakes.video_writes(fake)
            state = dict(fake.state)

        self.assertEqual(result["writtenFields"], [])
        self.assertFalse(result["rebooted"])
        self.assertEqual(writes, [])
        self.assertEqual(state["reboots"], 0)

    def test_the_third_stream_is_enabled_and_written_after_the_reboot(self):
        """103 does not exist until the third stream is on.

        So the order matters: enable, restart, wait, then write the profile.
        Writing 103 first is what the field script's reboot dance avoids.
        """
        inventory, device = self.build_camera()
        with fakes.video_camera(third_stream=False, ir="close") as fake:
            self.apply(fake, inventory, device)
            writes = fakes.video_writes(fake)
            state = dict(fake.state)

        self.assertIn("/ISAPI/System/Software/channels/1", writes)
        self.assertIn("/ISAPI/System/reboot", writes)
        self.assertIn("/ISAPI/Streaming/channels/103", writes)
        self.assertGreater(writes.index("/ISAPI/Streaming/channels/103"),
                           writes.index("/ISAPI/System/reboot"))
        self.assertEqual(state["reboots"], 1)
        self.assertEqual(state["channels"]["103"]["w"], "1280")

    def test_the_ir_light_alone_restarts_the_camera(self):
        inventory, device = self.build_camera()
        with fakes.video_camera(third_stream=True, ir="auto") as fake:
            result = self.apply(fake, inventory, device)
            state = dict(fake.state)

        self.assertEqual(state["ir"], "close")
        self.assertEqual(state["reboots"], 1)
        self.assertTrue(result["rebooted"])

    def test_an_unusable_sd_card_is_formatted(self):
        inventory, device = self.build_camera()
        with fakes.video_camera(hdd={"1": "unformatted"}) as fake:
            self.apply(fake, inventory, device)
            writes = fakes.video_writes(fake)
            state = dict(fake.state)

        self.assertIn("/ISAPI/ContentMgmt/Storage/hdd/1/format", writes)
        self.assertEqual(state["hdd"]["1"], "ok")

    def test_a_healthy_sd_card_is_left_alone(self):
        """Applying a setting must never wipe a card that is recording."""
        inventory, device = self.build_camera()
        with fakes.video_camera(hdd={"1": "ok"}) as fake:
            self.apply(fake, inventory, device)
            writes = fakes.video_writes(fake)

        self.assertNotIn("/ISAPI/ContentMgmt/Storage/hdd/1/format", writes)

    def test_a_camera_without_an_sd_card_is_not_a_failure(self):
        inventory, device = self.build_camera()
        with fakes.video_camera(hdd={}) as fake:
            result = self.apply(fake, inventory, device)
            rows = {row["field"]: row for row in result["rows"]}

        self.assertEqual(rows["storageStatus"]["current"], "No disk")

    def test_no_network_value_is_ever_written(self):
        """The one setting the panel refuses to touch.

        A mask written over ISAPI answers OK and then the device is gone
        from its address: it takes a power cycle and SADP, in the cabinet,
        to get it back. Seen on the hardware with the CCTV field script,
        whose `set_network_mask` step is the one this panel does not have.
        Every other target here is reversible from the panel; this one is
        not, so the mask is read and reported, never written.
        """
        inventory, device = self.build_camera()
        with fakes.video_camera() as fake:
            result = self.apply(fake, inventory, device)
            writes = fakes.video_writes(fake)
            state = dict(fake.state)
            rows = {row["field"]: row for row in result["rows"]}

        self.assertEqual(
            [path for path in writes if "Network/interfaces" in path], [])
        self.assertEqual(state["mask"], "255.0.0.0")     # untouched
        self.assertEqual(state["address"], "127.0.0.1")
        # Read, shown, and not editable.
        self.assertEqual(rows["subnetMask"]["current"], "255.0.0.0")
        self.assertFalse(rows["subnetMask"]["editable"])
        self.assertNotIn("ipAddress", rows)

    def test_a_rear_camera_gets_no_audio(self):
        """Rear and pantograph positions have no microphone fitted."""
        inventory = self.build([
            {**CAMERAS[0], "Name": "Rear_Cam_1", "CameraName": "Rear 1",
             "IP": "127.0.0.1"}, PISCU])
        device = inventory.by_type("Camera")[0]
        with fakes.video_camera() as fake:
            self.apply(fake, inventory, device)
            state = dict(fake.state)

        self.assertEqual(state["channels"]["101"]["audio"], "false")

    def test_a_value_entered_on_screen_wins_over_the_project_default(self):
        inventory, device = self.build_camera()
        config_sync.set_group_target("Camera", "stream3Resolution",
                                     "1024x768", "Camera")
        with fakes.video_camera() as fake:
            self.apply(fake, inventory, device)
            state = dict(fake.state)

        self.assertEqual(state["channels"]["103"]["w"], "1024")
        self.assertEqual(state["channels"]["103"]["h"], "768")

    def test_a_wrong_password_is_a_credential_problem(self):
        inventory, device = self.build_camera()
        with fakes.video_camera() as fake:
            settings.VIDEO_PORT = fake.port
            with self.assertRaises(AuthError):
                config_sync.apply_targets(device, inventory,
                                          ("admin", "wrong"), "Camera")

    def test_a_row_carries_the_label_not_its_message_key(self):
        """The window's first column is the setting's NAME.

        The field table stores a message key, because it is read on every
        request and has to answer in the language chosen at that moment. A
        row that ships the key renders as "field.ntpServer" on screen.
        """
        inventory, device = self.build_camera()
        with fakes.video_camera(third_stream=True) as fake:
            settings.VIDEO_PORT = fake.port
            body = config_sync.fetch(device, inventory, ACCOUNT, "Camera")
        labels = {row["field"]: row["label"] for row in body["rows"]}

        self.assertEqual(labels["ntpServer"], "NTP server")
        self.assertFalse(any(label.startswith("field.")
                             for label in labels.values()), labels)

    def test_the_screen_shows_the_camera_fields_and_no_sip_row(self):
        inventory, device = self.build_camera()
        with fakes.video_camera(third_stream=True) as fake:
            settings.VIDEO_PORT = fake.port
            body = config_sync.fetch(device, inventory, ACCOUNT, "Camera")
        rows = {row["field"]: row for row in body["rows"]}

        self.assertIn("ntpServer", rows)
        self.assertIn("thirdStream", rows)
        self.assertIn("channelName", rows)
        self.assertNotIn("sipRegistration", rows)
        self.assertNotIn("speakerVolume", rows)
        # The target is the project's, and it says so.
        self.assertEqual(rows["irLight"]["target"], "close")
        self.assertEqual(rows["irLight"]["source"], "project")


class NvrConfiguration(VideoTest):

    def build_nvr(self):
        inventory = self.build([*CAMERAS, PISCU, NVR])
        return inventory, inventory.by_type("NVR")[0]

    def apply(self, fake, inventory, device):
        settings.VIDEO_PORT = fake.port
        return config_sync.apply_targets(device, inventory, ACCOUNT, "NVR")

    def test_the_channels_come_from_devicemap(self):
        """No per-project channel table: CameraID, CameraName and the IP are
        already on the camera's own record."""
        inventory, device = self.build_nvr()
        with fakes.video_nvr() as fake:
            self.apply(fake, inventory, device)
            state = dict(fake.state)

        self.assertEqual(state["channels"], EXPECTED_CHANNELS)

    def test_an_existing_channel_is_updated_and_a_missing_one_added(self):
        inventory, device = self.build_nvr()
        with fakes.video_nvr(channels={1: ("Old name", "10.9.9.9")}) as fake:
            self.apply(fake, inventory, device)
            writes = fakes.video_writes(fake)
            state = dict(fake.state)

        self.assertEqual(
            {number: ip for number, (_name, ip) in state["channels"].items()},
            EXPECTED_CHANNEL_ADDRESSES)
        # Old firmware does not accept <name> in an existing-channel PUT, so
        # correcting its descriptor preserves the recorder-owned old label.
        self.assertEqual(state["channels"][1][0], "Old name")
        # Channel 1 exists, so it is corrected in place; 2–4 are new.
        self.assertIn("/ISAPI/ContentMgmt/InputProxy/channels/1", writes)
        self.assertEqual(
            writes.count("/ISAPI/ContentMgmt/InputProxy/channels"), 3)

    def test_legacy_channels_are_removed_after_yatakli_is_verified(self):
        """A recorder reused from the 26-camera project ends as Yatakli 1–4.

        Destructive cleanup deliberately comes last: every expected PUT/POST
        must have been accepted and read back before channel 5 is deleted.
        """
        inventory, device = self.build_nvr()
        legacy = {1: ("Rear 1", "10.1.1.28")}
        legacy.update({number: (f"Legacy {number}", f"10.9.9.{number}")
                       for number in range(5, 27)})
        with fakes.video_nvr(channels=legacy) as fake:
            result = self.apply(fake, inventory, device)
            history = list(fake.history)
            state = dict(fake.state)

        self.assertEqual(
            {number: ip for number, (_name, ip) in state["channels"].items()},
            EXPECTED_CHANNEL_ADDRESSES)
        self.assertEqual(state["channels"][1][0], "Rear 1")
        deletes = [(method, path) for method, path in history
                   if method == "DELETE"]
        self.assertEqual(
            {path for _method, path in deletes},
            {f"/ISAPI/ContentMgmt/InputProxy/channels/{number}"
             for number in range(5, 27)})
        expected_writes = [index for index, (method, path) in enumerate(history)
                           if method in ("PUT", "POST")
                           and "InputProxy/channels" in path]
        first_delete = next(index for index, (method, _path) in enumerate(history)
                            if method == "DELETE")
        self.assertGreater(first_delete, max(expected_writes))
        self.assertIn("Camera channels", result["writtenFields"])
        self.assertEqual(state["reboots"], 1)

    def test_legacy_channels_survive_when_an_expected_write_is_ignored(self):
        """HTTP OK is not enough to authorize deletion of old channels."""
        inventory, device = self.build_nvr()
        legacy = {1: ("Rear 1", "10.1.1.28")}
        legacy.update({number: (f"Legacy {number}", f"10.9.9.{number}")
                       for number in range(5, 27)})
        with fakes.video_nvr(channels=legacy, ignore_channel=3) as fake:
            with self.assertRaises(VerificationError):
                self.apply(fake, inventory, device)
            history = list(fake.history)
            state = dict(fake.state)

        self.assertEqual([path for method, path in history
                          if method == "DELETE"], [])
        self.assertTrue(all(number in state["channels"]
                            for number in range(5, 27)))
        self.assertNotIn(3, state["channels"])
        self.assertEqual(state["reboots"], 0)

    def test_an_empty_camera_map_never_wipes_the_recorder(self):
        inventory = self.build([PISCU, NVR])
        device = inventory.by_type("NVR")[0]
        legacy = {1: ("Existing", "10.8.8.1"),
                  2: ("Existing 2", "10.8.8.2")}
        with fakes.video_nvr(channels=legacy, triggers=0) as fake:
            self.apply(fake, inventory, device)
            history = list(fake.history)
            state = dict(fake.state)

        self.assertEqual(state["channels"], legacy)
        self.assertEqual([path for method, path in history
                          if method == "DELETE"], [])

    def test_an_unreadable_channel_list_stops_before_any_write(self):
        inventory, device = self.build_nvr()
        legacy = {1: ("Existing", "10.8.8.1"),
                  5: ("Legacy", "10.8.8.5")}
        with fakes.video_nvr(channels=legacy,
                             channel_list_error=True) as fake:
            with self.assertRaises(VerificationError) as caught:
                self.apply(fake, inventory, device)
            history = list(fake.history)
            state = dict(fake.state)

        self.assertIn("channel list", str(caught.exception).lower())
        self.assertEqual(state["channels"], legacy)
        self.assertEqual(
            [(method, path) for method, path in history
             if method in ("PUT", "POST", "DELETE")], [])
        self.assertEqual(state["reboots"], 0)

    def test_an_incomplete_yatakli_map_keeps_channel_four(self):
        inventory = self.build([*CAMERAS[:3], PISCU, NVR])
        device = inventory.by_type("NVR")[0]
        current = dict(EXPECTED_CHANNELS)
        with fakes.video_nvr(channels=current, triggers=0) as fake:
            self.apply(fake, inventory, device)
            history = list(fake.history)
            state = dict(fake.state)

        self.assertEqual(state["channels"], current)
        self.assertEqual([path for method, path in history
                          if method == "DELETE"], [])

    def test_input_proxy_uses_the_old_nvr_web_ui_content_type(self):
        inventory, device = self.build_nvr()
        with fakes.video_nvr(channels={
                1: ("Old name", "10.9.9.9"),
                5: ("Legacy", "10.9.9.5")}) as fake:
            self.apply(fake, inventory, device)
            wire = list(fake.request_content_types)

        mutations = [(path, content_type)
                     for method, path, content_type in wire
                     if method in ("PUT", "POST", "DELETE")]
        proxy = [content_type for path, content_type in mutations
                 if "InputProxy/channels" in path]
        other = [content_type for path, content_type in mutations
                 if "InputProxy/channels" not in path]
        self.assertTrue(proxy)
        self.assertTrue(other)
        self.assertEqual(set(proxy), {
            "application/x-www-form-urlencoded; charset=UTF-8"})
        self.assertEqual(set(other), {"application/xml; charset=UTF-8"})

    def test_refused_channel_shows_safe_hikvision_detail_and_prunes_nothing(self):
        inventory, device = self.build_nvr()
        legacy = {1: ("Rear 1", "10.1.1.28"),
                  5: ("Legacy", "10.9.9.5")}
        with fakes.video_nvr(channels=legacy, reject_channel=1) as fake:
            with self.assertRaises(VerificationError) as caught:
                self.apply(fake, inventory, device)
            history = list(fake.history)
            state = dict(fake.state)

        message = str(caught.exception)
        self.assertIn("Invalid XML Content", message)
        self.assertIn("badXmlContent", message)
        self.assertNotIn("must-not-leak", message)
        self.assertEqual([path for method, path in history
                          if method == "DELETE"], [])
        self.assertIn(5, state["channels"])

    def test_a_channel_that_already_matches_is_not_rewritten(self):
        inventory, device = self.build_nvr()
        with fakes.video_nvr(channels=dict(EXPECTED_CHANNELS)) as fake:
            self.apply(fake, inventory, device)
            writes = fakes.video_writes(fake)

        self.assertEqual(
            [path for path in writes if "InputProxy" in path], [])

    def test_the_buzzer_is_silenced(self):
        inventory, device = self.build_nvr()
        with fakes.video_nvr(triggers=2) as fake:
            result = self.apply(fake, inventory, device)
            state = dict(fake.state)

        for body in state["triggers"].values():
            self.assertNotIn("<notificationMethod>beep<", body)
            # The rest of the trigger survives: only the beep block goes.
            self.assertIn("<notificationMethod>record<", body)
        rows = {row["field"]: row for row in result["rows"]}
        self.assertEqual(rows["buzzer"]["comparison"], "match")

    def test_the_nvr_is_restarted_so_it_picks_the_channels_up(self):
        inventory, device = self.build_nvr()
        with fakes.video_nvr() as fake:
            result = self.apply(fake, inventory, device)
            writes = fakes.video_writes(fake)
            state = dict(fake.state)

        self.assertTrue(result["rebooted"])
        self.assertEqual(state["reboots"], 1)
        # Last of all: everything else has to be written before it.
        self.assertEqual(writes[-1], "/ISAPI/System/reboot")

    def test_an_nvr_in_agreement_is_not_restarted(self):
        """Rebooting for a run that changed nothing takes the set off air."""
        inventory, device = self.build_nvr()
        with fakes.video_nvr(channels=dict(EXPECTED_CHANNELS),
                             triggers=0) as fake:
            fake.state["timezone"] = settings.EXPECTED_TIMEZONE
            fake.state["ntp"] = "10.1.1.1"
            result = self.apply(fake, inventory, device)
            state = dict(fake.state)

        self.assertEqual(result["writtenFields"], [])
        self.assertFalse(result["rebooted"])
        self.assertEqual(state["reboots"], 0)

    def test_no_motion_detection_request_is_made(self):
        """Motion detection belongs to another project and is not here."""
        inventory, device = self.build_nvr()
        with fakes.video_nvr() as fake:
            self.apply(fake, inventory, device)
            paths = [path for _method, path in fake.history]

        self.assertEqual(
            [path for path in paths
             if "motionDetection" in path or "schedules" in path], [])

    def test_no_network_value_is_ever_written(self):
        inventory, device = self.build_nvr()
        with fakes.video_nvr() as fake:
            self.apply(fake, inventory, device)
            writes = fakes.video_writes(fake)
            state = dict(fake.state)

        self.assertEqual(
            [path for path in writes if "Network/interfaces" in path], [])
        self.assertEqual(state["mask"], "255.0.0.0")
        self.assertEqual(state["address"], "127.0.0.1")

    def test_the_channel_count_is_shown_on_the_screen(self):
        inventory, device = self.build_nvr()
        with fakes.video_nvr(channels=dict(EXPECTED_CHANNELS)) as fake:
            settings.VIDEO_PORT = fake.port
            body = config_sync.fetch(device, inventory, ACCOUNT, "NVR")
        rows = {row["field"]: row for row in body["rows"]}

        self.assertEqual(rows["proxyChannels"]["current"], "4/4")
        self.assertNotIn("channelName", rows)   # a camera field, not the NVR's

    def test_the_screen_exposes_legacy_channels_before_cleanup(self):
        inventory, device = self.build_nvr()
        current = {**EXPECTED_CHANNELS,
                   5: ("Legacy", "10.9.9.5"),
                   6: ("Legacy 2", "10.9.9.6")}
        with fakes.video_nvr(channels=current) as fake:
            settings.VIDEO_PORT = fake.port
            body = config_sync.fetch(device, inventory, ACCOUNT, "NVR")
        rows = {row["field"]: row for row in body["rows"]}

        self.assertEqual(rows["proxyChannels"]["current"], "4/4 · 2 extra")

    def test_the_camera_credential_is_needed_for_a_channel(self):
        """The NVR signs in to the camera itself, so the channel body needs
        that camera's password — and the panel keeps none on disk."""
        inventory, _device = self.build_nvr()
        camera = inventory.by_type("Camera")[0]
        with self.assertRaises(AuthError):
            nvr_config._camera_credential(camera, None)

        credentials.remember(camera.id, camera.ip, "admin", PASSWORD)
        self.assertEqual(nvr_config._camera_credential(camera, None), ACCOUNT)


class NvrPayloadSafety(PanelTest):

    def test_channel_xml_escapes_dynamic_values(self):
        name = "Landing & <Dort>"
        username = "ad&min<1>"
        password = "p<&>\"'"
        body = payloads.proxy_channel_body(
            4, name, "10.1.1.27", username, password)
        root = ET.fromstring(body)

        def value(tag):
            return next((element.text or "") for element in root.iter()
                        if element.tag.rsplit("}", 1)[-1] == tag)

        self.assertEqual(value("name"), name)
        self.assertEqual(value("userName"), username)
        self.assertEqual(value("password"), password)
        self.assertIn("&amp;", body)
        self.assertIn("&lt;", body)
        self.assertNotIn(password, body)

    def test_existing_channel_payload_matches_the_old_nvr_ui(self):
        body = payloads.proxy_channel_body(
            1, "Corridor 1", "10.1.1.24", "admin", PASSWORD,
            include_name=False)
        root = ET.fromstring(body)
        tags = [element.tag.rsplit("}", 1)[-1] for element in root.iter()]

        self.assertEqual(tags[0], "InputProxyChannel")
        self.assertEqual(tags[1], "id")
        self.assertNotIn("name", tags)
        self.assertIn("sourceInputPortDescriptor", tags)

    def test_only_documented_response_status_fields_reach_the_error(self):
        response = requests.Response()
        response.status_code = 400
        response._content = (
            b'<?xml version="1.0"?><ResponseStatus '
            b'xmlns="http://www.std-cgi.com/ver20/XMLSchema">'
            b'<statusCode>6</statusCode>'
            b'<statusString>Invalid\n XML\t Content</statusString>'
            b'<subStatusCode>badXmlContent</subStatusCode>'
            b'<password>response-secret</password></ResponseStatus>')
        response.headers = {}

        with mock.patch.object(video_isapi, "request", return_value=response):
            with self.assertRaises(VerificationError) as caught:
                video_isapi.write("127.0.0.1", "a/path", ACCOUNT,
                                  "<secret>request-secret</secret>")

        message = str(caught.exception)
        self.assertIn("HTTP 400", message)
        self.assertIn("Invalid XML Content / badXmlContent", message)
        self.assertNotIn("response-secret", message)
        self.assertNotIn("request-secret", message)

    def test_non_xml_error_body_is_not_echoed(self):
        response = requests.Response()
        response.status_code = 400
        response._content = b"<html>device-secret"
        response.headers = {}

        with mock.patch.object(video_isapi, "request", return_value=response):
            with self.assertRaises(VerificationError) as caught:
                video_isapi.write("127.0.0.1", "a/path", ACCOUNT, "")

        self.assertIn("HTTP 400", str(caught.exception))
        self.assertNotIn("device-secret", str(caught.exception))


class Scopes(PanelTest):
    """Which fields a video device has is decided by its Type."""

    def test_the_field_set_follows_the_device_type(self):
        self.assertEqual(field_table.writable_for_scope("NVR"),
                         ("ntpServer", "timeZone", "buzzer"))
        self.assertNotIn("subnetMask",
                         field_table.writable_for_scope("Camera"))
        self.assertIn("thirdStream", field_table.writable_for_scope("Camera"))
        # A camera's SubType is project vocabulary and carries no fields.
        self.assertEqual(field_table.writable_for_scope("Corridor"), ())

    def test_a_camera_is_scoped_by_type_and_an_intercom_by_subtype(self):
        inventory = self.build_map(fakes.device_map([
            {**CAMERAS[0], "IP": "127.0.0.1"},
            {"Name": "Intercom_1", "IP": "127.0.0.1", "Type": "Announcement",
             "SubType": "Intercom", "IsActive": True, "Port": "11",
             "Status": {"NoError": True}},
        ]))
        camera = inventory.by_type("Camera")[0]
        intercom = inventory.by_type("Announcement")[0]

        self.assertEqual(field_table.config_scope(camera), "Camera")
        self.assertEqual(field_table.config_scope(intercom), "Intercom")


class RunReport(VideoTest):
    """What the run says it did.

    A configuration write on video equipment is a procedure, not a field: the
    row's single note could only carry the last thing that happened. The
    steps are what answers "what did it actually change" — the same lines the
    field script prints.
    """

    def steps(self, fake, devices, group):
        inventory = self.build(devices)
        device = [d for d in inventory.devices if d.type == group][0]
        settings.VIDEO_PORT = fake.port
        collected = []
        config_sync.apply_targets(
            device, inventory, ACCOUNT, group,
            report=lambda text, state="done": collected.append(
                (i18n.render(text), state)))
        return [text for text, _state in collected]

    def test_the_nvr_run_names_every_channel_it_wrote(self):
        with fakes.video_nvr() as fake:
            lines = self.steps(fake, [*CAMERAS, PISCU, NVR], "NVR")

        self.assertIn("Channel 1 added: Corridor 1 @ 10.1.1.24", lines)
        self.assertIn("Channel 3 added: Landing 1 @ 10.1.1.26", lines)
        self.assertTrue(any("Buzzer silenced" in line for line in lines))
        self.assertTrue(any("Restarting the NVR" in line for line in lines))

    def test_a_run_that_changes_nothing_says_so(self):
        with fakes.video_nvr(channels=dict(EXPECTED_CHANNELS),
                             triggers=0) as fake:
            fake.state["timezone"] = settings.EXPECTED_TIMEZONE
            fake.state["ntp"] = "10.1.1.1"
            lines = self.steps(fake, [*CAMERAS, PISCU, NVR], "NVR")

        self.assertIn("The device already holds every target value", lines)
        self.assertTrue(any("already match" in line for line in lines))

    def test_the_camera_run_names_the_restart_and_its_reason(self):
        with fakes.video_camera(third_stream=False) as fake:
            lines = self.steps(
                fake, [{**CAMERAS[0], "IP": "127.0.0.1"}, PISCU], "Camera")

        self.assertIn("Third stream enabled — the camera restarts", lines)
        self.assertIn("The device answered again", lines)
        self.assertIn("Third stream profile written (channel 103)", lines)
        self.assertTrue(any("formatted" in line for line in lines))


class VerificationChecks(VideoTest):
    """The scan reads more than the clock.

    Time, NTP and mask say the device is on the network. Whether it will
    RECORD is a different question, and the field's verification pass has
    always asked it: the disk, the buzzer, the IR lamp, the third stream.
    """

    def read(self, fake, is_nvr):
        settings.VIDEO_PORT = fake.port
        return camera_probe.read("127.0.0.1", ACCOUNT,
                                 expected_ntp="10.1.1.1", is_nvr=is_nvr)

    def test_an_nvr_reports_its_disk_and_its_buzzer(self):
        with fakes.video_nvr(hdd={"1": "unformatted"}) as fake:
            fake.state["timezone"] = settings.EXPECTED_TIMEZONE
            fake.state["ntp"] = "10.1.1.1"
            fake.state["mask"] = settings.EXPECTED_SUBNET_MASK
            answer = self.read(fake, is_nvr=True)["networkTime"]

        self.assertIn("HDD fault (unformatted)", answer)
        self.assertIn("buzzer on", answer)
        # A camera's checks have no business on a recorder.
        self.assertNotIn("IR", answer)
        self.assertNotIn("third stream", answer)

    def test_a_healthy_nvr_is_simply_ok(self):
        with fakes.video_nvr(hdd={"1": "ok"}, triggers=0) as fake:
            fake.state["timezone"] = settings.EXPECTED_TIMEZONE
            fake.state["ntp"] = "10.1.1.1"
            fake.state["mask"] = settings.EXPECTED_SUBNET_MASK
            answer = self.read(fake, is_nvr=True)["networkTime"]

        self.assertEqual(answer, "OK")

    def test_a_camera_reports_its_card_ir_and_third_stream(self):
        with fakes.video_camera(hdd={}, ir="auto",
                                third_stream=False) as fake:
            fake.state["timezone"] = settings.EXPECTED_TIMEZONE
            fake.state["ntp"] = "10.1.1.1"
            fake.state["mask"] = settings.EXPECTED_SUBNET_MASK
            answer = self.read(fake, is_nvr=False)["networkTime"]

        self.assertIn("no SD card", answer)
        self.assertIn("IR on", answer)
        self.assertIn("third stream off", answer)
        self.assertNotIn("buzzer", answer)

    def test_a_buzzer_the_trigger_list_hides_is_still_found(self):
        """Some firmware answers the trigger list with ids alone.

        Reading that as "no beep configured" is how a cabinet leaves the
        depot beeping: the two triggers that can beep are asked by name.
        """
        with fakes.video_nvr(list_methods=False) as fake:
            settings.VIDEO_PORT = fake.port
            self.assertIs(health.buzzer_on("127.0.0.1", ACCOUNT), True)

    def test_an_unreadable_check_says_so_rather_than_passing(self):
        with fakes.video_nvr() as fake:
            settings.VIDEO_PORT = fake.port
        # The server is closed now; every check has to admit it could not
        # look rather than reporting the device as healthy.
        unreachable = health.problems("127.0.0.1", ACCOUNT, is_nvr=True,
                                      timeout=0.2)
        self.assertIn("HDD unreadable", unreachable)
        self.assertIn("buzzer unreadable", unreachable)
