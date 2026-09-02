#!/usr/bin/env python3
"""One project's equipment cannot answer for another's.

Two facts were global and had nowhere else to be: which reader reaches a
device kind, and what decides its configuration field set. Both were keyed by
Type and SubType alone, so "Intercom" meant one thing for every customer the
panel was ever built for — and the pickers on the operation screens listed
every customer's equipment at once, which is what these tests exist because
of.

The split is per PROJECT rather than per edition: one package can carry two
trains (VIP and Yatakli travel together) and the operator switches between
them in the top bar, so the edition is too coarse to be the answer.
"""
from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

from panel import settings
from panel.config_sync import fields
from panel.editions import catalogue
from panel.inventory import catalog, device_map, profiles


def maps() -> list[Path]:
    found = sorted((settings.ROOT / "devicemaps").rglob("DeviceMap*.json"))
    return [path for path in found if path.is_file()]


def project_key(path: Path) -> str:
    return path.stem.replace("DeviceMap", "").strip("_- ").lower()


class ProfilesCoverTheFleet(unittest.TestCase):

    def test_every_project_in_the_catalogue_has_a_profile(self):
        """The two tables are joined by the project key and nothing else.

        `panel/editions/catalogue.py` says which projects exist; this package
        says how each one's equipment is talked to. A project in one and not
        the other reads its devices through the shared rules without saying
        so, which is exactly the silence the split was meant to end.
        """
        declared = sorted(project.key for project in catalogue.ALL_PROJECTS)
        described = sorted(profiles.BY_KEY)
        self.assertEqual(declared, described)

    def test_a_map_belonging_to_no_listed_project_still_opens(self):
        """A DeviceMap delivered on a service key has no file of its own.

        There is nowhere to declare rules for a map that arrived on a stick
        (`panel.adminkey.pack`), so it gets the shared rules — read the
        ordinary way rather than refused or read as nothing.
        """
        shared = profiles.for_project("a-project-nobody-shipped")
        self.assertIs(shared, profiles.SHARED)
        self.assertEqual(shared.read_method("Announcement", "Intercom"),
                         "http")

    def test_the_map_is_read_through_its_own_project_s_rules(self):
        """Not through the shared table that happens to agree with them.

        Every device in every shipped map, checked against the profile for
        the project that map belongs to. If `device_map` ever went back to
        asking the vocabulary instead, this keeps passing only for as long as
        the two agree — and the moment a project differs, which is the whole
        point, it would fail.
        """
        for path in maps():
            profile = profiles.for_project(project_key(path))
            inventory = device_map.load(1, path, cache=False)
            with self.subTest(project=path.name):
                self.assertTrue(inventory.devices, "an empty map")
                for device in inventory.devices:
                    self.assertEqual(
                        device.read_method,
                        profile.read_method(device.type, device.subtype),
                        f"{device.type}/{device.subtype or '-'}")
                    self.assertEqual(
                        device.config_scope,
                        profile.config_scope(device.type, device.subtype),
                        f"{device.type}/{device.subtype or '-'}")

    def test_the_split_changed_nothing_for_the_fleet_as_it_stands(self):
        """The refactor was behaviour-preserving, and this says so.

        All five trains agree about their equipment today. That is a fact
        about the fleet rather than a structure, and it is worth pinning: the
        profiles were extracted from the one if-chain that used to answer for
        everybody, and an extraction that quietly changed an answer would
        have changed how a device is READ in the field.
        """
        for path in maps():
            profile = profiles.for_project(project_key(path))
            inventory = device_map.load(1, path, cache=False)
            for device in inventory.devices:
                with self.subTest(project=path.name,
                                  kind=f"{device.type}/{device.subtype or '-'}"):
                    self.assertEqual(
                        profile.read_method(device.type, device.subtype),
                        catalog.read_method_for(device.type, device.subtype))


class OneProjectCanDiffer(unittest.TestCase):
    """The thing the split exists for, exercised rather than promised."""

    def kinds(self, path: Path) -> dict:
        inventory = device_map.load(1, path, cache=False)
        return {(device.type, device.subtype or ""):
                (device.read_method, device.config_scope)
                for device in inventory.devices}

    def setUp(self):
        self.yatakli = next(path for path in maps()
                            if project_key(path) == "yatakli")
        self.vip = next(path for path in maps()
                        if project_key(path) == "vip")

    def test_a_rule_of_one_project_s_own_moves_only_that_project(self):
        """VIP and Yatakli ship in ONE package and share the word.

        They are the sharpest case in the fleet: the same operator, the same
        top bar, the same "Intercom" — and two different trains. If a rule
        written for one of them reached the other, the split would be
        decoration.
        """
        before = {"yatakli": self.kinds(self.yatakli),
                  "vip": self.kinds(self.vip)}

        # Yatakli's Intercom, and nobody else's, answering somewhere else.
        own = profiles.Rule("announcement/yatakli-only", ("Announcement",),
                            ("Intercom",), "adb", scope_by="type")
        changed = profiles.Profile(
            "yatakli", (own, *profiles.BY_KEY["yatakli"].rules))
        with mock.patch.dict(profiles.BY_KEY, {"yatakli": changed}):
            after = {"yatakli": self.kinds(self.yatakli),
                     "vip": self.kinds(self.vip)}

        intercom = ("Announcement", "Intercom")
        self.assertEqual(before["yatakli"][intercom], ("http", "Intercom"))
        self.assertEqual(after["yatakli"][intercom], ("adb", "Announcement"))
        # Every other kind on the same train is untouched...
        self.assertEqual(
            {key: value for key, value in after["yatakli"].items()
             if key != intercom},
            {key: value for key, value in before["yatakli"].items()
             if key != intercom})
        # ...and the train beside it in the same package did not move at all.
        self.assertEqual(after["vip"], before["vip"])
        self.assertEqual(after["vip"][intercom], ("http", "Intercom"))

    def test_the_field_set_follows_the_project_s_scope(self):
        """A scope is not decoration either: it picks the fields written.

        `config_scope` is what `ROUTES` in `panel/config_sync/fields.py` is
        keyed by, so a project giving its equipment a scope of its own is how
        that equipment gets a field set of its own — with no branch anywhere
        and no other project affected.
        """
        inventory = device_map.load(1, self.yatakli, cache=False)
        intercom = next(device for device in inventory.devices
                        if (device.type, device.subtype)
                        == ("Announcement", "Intercom"))
        self.assertEqual(fields.config_scope(intercom), "Intercom")
        self.assertIn("micVolume", fields.writable_for_scope(
            fields.config_scope(intercom)))

        # The same device under a scope this project alone declares: no rows
        # exist for it yet, so nothing is writable — which is the honest
        # answer, and the signal to add them.
        own = profiles.Rule("announcement/yatakli-only", ("Announcement",),
                            ("Intercom",), "http", scope_by="type")
        changed = profiles.Profile(
            "yatakli", (own, *profiles.BY_KEY["yatakli"].rules))
        with mock.patch.dict(profiles.BY_KEY, {"yatakli": changed}):
            reloaded = device_map.load(1, self.yatakli, cache=False)
        moved = next(device for device in reloaded.devices
                     if (device.type, device.subtype)
                     == ("Announcement", "Intercom"))
        self.assertEqual(fields.config_scope(moved), "Announcement")
        self.assertEqual(fields.writable_for_scope("Announcement"), ())


class StatusFromTheBroker(unittest.TestCase):
    """GDM listens to ALFA/DeviceMap for status; nothing else moved.

    GDM's PISCU publishes the live state of the whole train on the one
    topic, so its profile sets `probe="mqtt"` on every direct-read rule.
    `read` stays what it was on every rule of every project, because it also
    answers which protocol configuration and firmware travel over — the
    split is exactly STATUS and nothing else.
    """

    def test_every_project_probes_the_broker_and_configures_directly(self):
        """Fleet-wide, the shared profile included: a map delivered on a
        service key must read the same way as a shipped one."""
        for key, profile in {**profiles.BY_KEY,
                             "(shared)": profiles.SHARED}.items():
            for kind, subtype, read in (("Switch", None, "kyland"),
                                        ("Announcement", "Intercom", "http"),
                                        ("Camera", "Corridor", "isapi"),
                                        ("LCD", "Compartment", "adb")):
                if profile.rule_for(kind, subtype) is None:
                    continue              # a project without that equipment
                with self.subTest(project=key, kind=kind):
                    self.assertEqual(profile.probe_method(kind, subtype),
                                     "mqtt")
                    self.assertEqual(profile.read_method(kind, subtype),
                                     read)

    def test_the_broker_fed_control_units_probe_the_way_they_read(self):
        """PISCU and HMI were always read off the broker; no second visit."""
        for key, profile in profiles.BY_KEY.items():
            with self.subTest(project=key):
                self.assertEqual(profile.probe_method("PISCU", None),
                                 profile.read_method("PISCU", None))

    @staticmethod
    def _gdm_switch():
        from pathlib import Path
        import json as json_module
        import tempfile

        topology = {"Switches": [{
            "Name": "GDM_SW_1", "IP": "127.0.0.1", "IsActive": True,
            "Manufacturer": "KYLAND", "TrainSet": 1,
            "Status": {"NoError": True, "Uptime": 10},
            "Devices": [],
        }]}
        path = Path(tempfile.mkdtemp(prefix="panel-test-")) / \
            "DeviceMap_gdm.json"
        path.write_text(json_module.dumps(topology), encoding="utf-8")
        return device_map.load(1, path, cache=False).devices[0]

    class _Telemetry:
        error = None

        @staticmethod
        def record(ip):
            return {"SerialNumber": "GDM-1",
                    "Status": {"NoError": True, "Uptime": 42,
                               "Version": "9.9"}} \
                if ip == "127.0.0.1" else None

    def test_a_gdm_device_is_topped_up_from_its_own_protocol(self):
        """The hybrid, end to end: the broker record decides who is up and
        carries the base fields; the device the record calls alive is read
        once over its own protocol, and the two answers land as one row —
        the field script's shape (field_scripts/device_verify.py)."""
        from panel.probe import reader as probe_reader
        from panel.probe import result as probe_result
        from panel import status as status_module

        switch_device = self._gdm_switch()
        self.assertEqual(switch_device.probe_method, "mqtt")
        self.assertEqual(switch_device.read_method, "kyland")
        rich = probe_result.success({"version": "10.0", "model": "SICOM",
                                     "uptime": ""}, "kyland")
        with mock.patch.object(probe_reader, "_read_switch",
                               return_value=rich):
            outcome = probe_reader.read_device(switch_device,
                                               telemetry=self._Telemetry())
        self.assertEqual(outcome.state, status_module.OK)
        # The device's own answer wins; the record fills what it lacked.
        self.assertEqual(outcome.fields.get("version"), "10.0")
        self.assertEqual(outcome.fields.get("model"), "SICOM")
        self.assertEqual(outcome.fields.get("uptime"), "00:00:42")

    def test_a_silent_top_up_does_not_unsay_the_broker(self):
        """The record proved the device alive; a protocol that gives
        nothing on top empties no cell and turns nothing red."""
        from panel.errors import UnreachableError
        from panel.probe import reader as probe_reader
        from panel import status as status_module

        switch_device = self._gdm_switch()
        with mock.patch.object(probe_reader, "_read_switch",
                               side_effect=UnreachableError("no answer")):
            outcome = probe_reader.read_device(switch_device,
                                               telemetry=self._Telemetry())
        self.assertEqual(outcome.state, status_module.OK)
        self.assertEqual(outcome.read_method, "mqtt")
        self.assertEqual(outcome.fields.get("version"), "9.9")
        self.assertIn("no answer", outcome.detail)

    def test_a_top_up_that_wants_a_password_goes_amber(self):
        """The credential store is memory-only, so amber is the only road
        to the extra fields ever filling — and the base fields ride along
        so the row still shows what the broker knows."""
        from panel.errors import AuthError
        from panel.probe import reader as probe_reader
        from panel import status as status_module

        switch_device = self._gdm_switch()
        with mock.patch.object(probe_reader, "_read_switch",
                               side_effect=AuthError("who are you")):
            outcome = probe_reader.read_device(switch_device,
                                               telemetry=self._Telemetry())
        self.assertEqual(outcome.state, status_module.AUTH)
        self.assertEqual(outcome.fields.get("version"), "9.9")

    def test_no_broker_means_the_direct_read_every_project_had(self):
        """The broker is never a precondition. No telemetry at all — a
        stand, a bench — and the device is simply asked itself."""
        from panel.probe import reader as probe_reader
        from panel.probe import result as probe_result

        switch_device = self._gdm_switch()
        direct_answer = probe_result.success({"version": "10.0"}, "kyland")
        with mock.patch.object(probe_reader, "_read_switch",
                               return_value=direct_answer) as direct, \
                mock.patch.object(probe_reader, "_read_mqtt") as broker:
            outcome = probe_reader.read_device(switch_device, telemetry=None)
        direct.assert_called_once()
        broker.assert_not_called()
        self.assertIs(outcome, direct_answer)

    def test_a_device_the_record_does_not_list_is_asked_directly(self):
        """Absence of a record is not evidence of absence of the device."""
        from panel.probe import reader as probe_reader
        from panel.probe import result as probe_result

        switch_device = self._gdm_switch()

        class Empty:
            error = None

            @staticmethod
            def record(_ip):
                return None

        direct_answer = probe_result.success({"version": "10.0"}, "kyland")
        with mock.patch.object(probe_reader, "_read_switch",
                               return_value=direct_answer) as direct:
            outcome = probe_reader.read_device(switch_device,
                                               telemetry=Empty())
        direct.assert_called_once()
        self.assertIs(outcome, direct_answer)

    def test_a_named_method_is_exactly_that_one_answer(self):
        """The checklist export names the method; naming one skips the
        top-up — whoever asks for the direct read wants only it."""
        from panel.probe import reader as probe_reader
        from panel.probe import result as probe_result

        switch_device = self._gdm_switch()
        rich = probe_result.success({"version": "10.0"}, "kyland")
        with mock.patch.object(probe_reader, "_read_switch",
                               return_value=rich) as direct, \
                mock.patch.object(probe_reader, "_read_mqtt") as broker:
            outcome = probe_reader.read_device(switch_device,
                                               method="kyland")
        direct.assert_called_once()
        broker.assert_not_called()
        self.assertIs(outcome, rich)


if __name__ == "__main__":
    unittest.main()
