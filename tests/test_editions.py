#!/usr/bin/env python3
"""One program, one package per customer.

What these tests hold in place is the rule that makes the separation worth
anything: a packaged build is the edition it was built as, and nothing said
on the command line changes that. Everything else here — the screen list, the
per-edition settings folder, the project table — exists to serve that rule
and is checked so it cannot drift away from it.
"""
from __future__ import annotations

import contextlib
import dataclasses
import importlib
import os
import sys
import unittest
from unittest import mock

from .support.base import PanelTest

from panel import api, editions, jobs, settings
from panel.editions import catalogue
from panel.inventory import device_map


@contextlib.contextmanager
def undelivered(edition_id: str, project_key: str):
    """Make one project's DeviceMap look as though it has not arrived.

    THE STATE IS BUILT RATHER THAN BORROWED, and it has to be now. These
    tests used to point at whichever project was still a placeholder — VIP,
    then GDM — and the day that project's map was delivered they stopped
    testing anything at all while still passing: `available()` answered yes,
    the panel opened, and the assertions that a missing map is reported went
    green for the wrong reason.

    `Project.path` is the seam, and it is not one invented here: it is how a
    map delivered on the service key names itself (`panel.adminkey.pack`),
    and `runtime.map_path` returns it untouched. Pointed at a file that is
    not there, the project is exactly as undelivered as an empty folder.
    """
    edition = catalogue.find(edition_id)
    missing = dataclasses.replace(
        next(p for p in edition.projects if p.key == project_key),
        path="/nonexistent/not-delivered/DeviceMap_Nowhere.json")
    patched = dataclasses.replace(
        edition, projects=tuple(missing if p.key == project_key else p
                                for p in edition.projects))
    with mock.patch.dict(catalogue.BY_ID, {edition_id: patched}):
        yield


class Table(unittest.TestCase):
    """The catalogue itself, before anything runs."""

    def test_the_catalogue_needs_nothing_but_the_standard_library(self):
        """`dabp.spec` loads this file directly and must not need `panel`.

        The spec deliberately does not import the application (it would pull
        in `requests`, which a build environment need not have). It reads the
        table with importlib instead, so the table has to stand alone.
        """
        source = (settings.ROOT / "panel" / "editions"
                  / "catalogue.py").read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                self.assertNotIn(
                    "panel", stripped,
                    f"catalogue.py may not import from the package: {line}")
                self.assertFalse(stripped.startswith("from ."), line)

    def test_the_spec_can_load_it_the_way_the_build_does(self):
        """Loaded standalone, exactly as dabp.spec does it."""
        path = settings.ROOT / "panel" / "editions" / "catalogue.py"
        spec = importlib.util.spec_from_file_location("dap_cat_probe", path)
        module = importlib.util.module_from_spec(spec)
        # Without this line the dataclasses below fail to resolve their own
        # string annotations. The spec has the same line for the same reason.
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            self.assertEqual(module.IDS, catalogue.IDS)
        finally:
            sys.modules.pop(spec.name, None)

    def test_every_edition_is_coherent(self):
        for edition in catalogue.EDITIONS:
            with self.subTest(edition.id):
                self.assertTrue(edition.id.replace("-", "").isalnum())
                self.assertTrue(edition.id.islower())
                keys = [project.key for project in edition.projects]
                self.assertEqual(len(keys), len(set(keys)))
                self.assertIn(edition.default_project, keys)
                # An edition may leave a field screen out; it may not invent
                # one, and it may not hand itself an admin screen — those are
                # added by the MODE, not by the table.
                for view in edition.views:
                    self.assertIn(view, catalogue.BASE_VIEWS, view)

    def test_the_windows_app_ids_are_distinct(self):
        """Two editions on one machine must update themselves, not each other."""
        ids = [edition.windows_app_id for edition in catalogue.EDITIONS]
        self.assertEqual(len(ids), len(set(ids)))
        for value in ids:
            self.assertRegex(value, r"^\{[0-9A-F-]{36}\}$")

    def test_every_edition_is_a_customers_package(self):
        """THE FOURTH ROW IS GONE ON PURPOSE. There used to be an internal
        "service" edition that opened as admin with nothing plugged in — a
        build that lets itself in, one copy of which reaching a customer's
        machine would undo the whole arrangement. Admin is a mode now, and
        the stick is the only way into it."""
        self.assertEqual(list(catalogue.IDS),
                         ["vip-yatakli", "gdm", "gaziray", "fuar"])
        self.assertFalse([field for field
                          in catalogue.Edition.__dataclass_fields__
                          if "admin" in field])

    def test_the_editions_between_them_carry_every_project(self):
        """A project in the table that no package ships is a device list
        nobody can open."""
        shipped = {project.key for edition in catalogue.EDITIONS
                   for project in edition.projects}
        self.assertEqual(shipped, {p.key for p in catalogue.ALL_PROJECTS})

    def test_the_bundled_name_is_the_source_file_name(self):
        """`dabp.spec` places data files at the bundle root under their own
        basename — `map_name` is what the running app then looks for. If the
        two ever disagreed the package would build cleanly and open with
        "DeviceMap not found"."""
        for project in catalogue.ALL_PROJECTS:
            with self.subTest(project.key):
                self.assertEqual(project.map_name, project.source_path[-1])

    def test_every_project_file_is_named_by_the_rule(self):
        """One standard, applied by the table itself.

        `catalogue.project()` derives all four names from the key, so this
        cannot fail while the rows are written that way — which is the
        point. It fails the moment somebody adds a row by calling `Project`
        directly and spells a path by hand, and that is exactly how the
        delivered maps arrived misnamed: `DeviceMap_gdm.json` beside
        `DeviceMap_Fuar.json`. A case-insensitive filesystem opens both;
        Linux opens one, and the package builds there without its map.
        """
        for project in catalogue.ALL_PROJECTS:
            with self.subTest(project.key):
                self.assertEqual(project.key, project.key.lower())
                self.assertEqual(project.map_name,
                                 f"DeviceMap_{project.key.capitalize()}.json")
                self.assertEqual(
                    project.checklist_name,
                    f"Field_Device_Verification_"
                    f"{project.key.capitalize()}.xlsx")
                folder = (catalogue.MAPS_DIR, project.key)
                self.assertEqual(project.source_path,
                                 (*folder, project.map_name))
                self.assertEqual(project.checklist_source,
                                 (*folder, project.checklist_name))

    def test_every_project_carries_its_own_checklist_workbook(self):
        """The workbook fills rows BY IP TEMPLATE (`panel/checklist/`), so a
        project filled from another project's file gets an empty report and
        nothing on screen says why. There is no shared workbook any more —
        `devicemaps/_base/` holds the template they are generated FROM."""
        for project in catalogue.ALL_PROJECTS:
            with self.subTest(project.key):
                self.assertTrue(project.checklist_name)
                self.assertTrue(project.checklist_source)

    def test_a_project_label_matches_the_name_taken_from_the_file(self):
        """`Inventory.project` is derived from the file stem, and
        `panel/video_config/nvr.py` branches on that derived string. The
        label shown in the menu has to be the same word or the two drift."""
        for project in catalogue.ALL_PROJECTS:
            with self.subTest(project.key):
                stem = project.map_name.rsplit(".", 1)[0]
                derived = stem.replace("DeviceMap", "").strip("_- ") or "YATAKLI"
                self.assertEqual(project.label.upper(), derived.upper())

    def test_the_screen_is_given_the_label_and_not_the_file_stem(self):
        """The stem is ASCII because the file name has to be, so for two of
        the five projects it is not how the name is written. The panel used
        to show the stem, which put a misspelling in the top bar and,
        worse, next to the project picker one line below it showing the
        label — the same project spelled two ways on one screen."""
        for project in catalogue.ALL_PROJECTS:
            with self.subTest(project.key):
                stem = project.map_name.rsplit(".", 1)[0]
                derived = stem.replace("DeviceMap", "").strip("_- ")
                self.assertEqual(catalogue.label_for(derived), project.label)

    def test_a_project_nobody_listed_is_called_what_its_file_calls_it(self):
        """A map delivered on the service key has no catalogue entry, and
        its stem is then the best name anyone has for it."""
        self.assertEqual(catalogue.label_for("Ozel"), "Ozel")
        self.assertEqual(catalogue.label_for(""), "")


class Resolution(unittest.TestCase):
    """Which edition this process is, and who gets to say so."""

    def setUp(self):
        self._active = editions.runtime._ACTIVE
        self._env = os.environ.get("DAP_EDITION")

    def tearDown(self):
        os.environ["DAP_EDITION"] = self._env or "vip-yatakli"
        editions.activate(self._active.id if self._active
                          else "vip-yatakli")

    def test_an_edition_must_be_named(self):
        """A bare source run has no sensible answer, so it refuses to guess."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DAP_EDITION", None)
            with self.assertRaises(editions.EditionError):
                editions.resolve(None)

    def test_the_flag_beats_the_environment(self):
        with mock.patch.dict(os.environ, {"DAP_EDITION": "gaziray"}):
            self.assertEqual(editions.resolve("gdm"), "gdm")

    def test_an_unknown_name_is_refused(self):
        with self.assertRaises(editions.EditionError):
            editions.resolve("not-a-customer")

    def test_a_packaged_build_is_what_it_was_built_as(self):
        """THE RULE THE SERVICE KEY RESTS ON.

        If a customer could start their own package as another customer's,
        the separation would be decoration. So in a frozen build the stamp is
        the only
        answer, and a disagreeing --edition is an error rather than something
        quietly ignored — an ignored flag invites the next person to look for
        the one that works.
        """
        with mock.patch.object(editions.runtime, "stamped_edition",
                               return_value="gdm"):
            self.assertEqual(editions.resolve(None), "gdm")
            self.assertEqual(editions.resolve("gdm"), "gdm")
            with self.assertRaises(editions.EditionError):
                editions.resolve("gaziray")

    def test_a_stamp_left_in_a_source_tree_is_ignored(self):
        """A local package build leaves the generated module behind; a source
        run afterwards must behave as a source run."""
        self.assertFalse(settings.FROZEN)
        with mock.patch.dict(os.environ, {"DAP_EDITION": "gaziray"}):
            self.assertEqual(editions.resolve(None), "gaziray")


class Activation(PanelTest):
    """What activating an edition changes about the running process."""

    def tearDown(self):
        editions.activate("vip-yatakli")
        super().tearDown()

    def test_activation_points_the_panel_at_the_project(self):
        editions.activate("vip-yatakli")
        self.assertEqual(editions.current_project().key, "yatakli")
        self.assertEqual(settings.DEVICE_MAP.name, "DeviceMap_Yatakli.json")
        loaded = device_map.load(1)
        # The stem stays what the code matches on ...
        self.assertEqual(loaded.project, "Yatakli")
        # ... and the label is what a person is shown. The two
        # differ for this project, which is the whole point.
        self.assertEqual(loaded.project_label,
                         catalogue.YATAKLI.label)
        self.assertNotEqual(loaded.project, loaded.project_label)

    def test_each_edition_keeps_its_own_settings_folder(self):
        """Configuration targets are keyed by (train set, device id), and
        device ids are POSITIONAL — "sw1.d3" is a different device in another
        project. Sharing one file between editions would write a value
        entered for one customer onto another's hardware."""
        editions.activate("gdm")
        gdm = settings.config_defaults_file()
        editions.activate("gaziray")
        self.assertNotEqual(gdm, settings.config_defaults_file())
        self.assertEqual(settings.data_dir().name, "gaziray")

    def test_an_undelivered_device_list_still_opens_the_panel(self):
        """A package whose own map has not arrived yet must start and say so,
        not refuse to run: a window explaining the gap is a far better report
        than an executable that exits."""
        with undelivered("gdm", "gdm"):
            editions.activate("gdm")
            self.assertEqual(editions.current_project().key, "gdm")
            self.assertFalse(editions.available(editions.current_project()))

    def test_switching_to_an_undelivered_project_is_refused(self):
        """Activation tolerates a missing map; asking for one on purpose
        does not."""
        with undelivered("vip-yatakli", "vip"):
            editions.activate("vip-yatakli")
            with self.assertRaises(editions.EditionError):
                editions.use_project("vip")

    def test_the_device_map_environment_override_still_wins(self):
        """How a field engineer points the panel at a hand-edited map."""
        with mock.patch.dict(os.environ, {"DEVICE_MAP_FILE": "/tmp/x.json"}):
            before = settings.DEVICE_MAP
            editions.activate("gdm")
            self.assertEqual(settings.DEVICE_MAP, before)


def as_shipped(case):
    """A run with no build secret — which is every package that ships.

    The suite exports one so that the admin screens are exercised at all
    (see tests/support/base.py), and holding the secret is what opens admin
    mode now that no edition does. A test about what the CUSTOMER sees has
    therefore to put the secret back where the customer has it: nowhere.
    """
    case.enterContext(mock.patch.dict(os.environ, {}, clear=False))
    os.environ.pop("DAP_ADMIN_KEY_SECRET", None)


class Views(PanelTest):
    """Which screens exist, and when."""

    def tearDown(self):
        editions.activate("vip-yatakli")
        super().tearDown()

    def test_a_customer_package_shows_no_engineer_screens(self):
        as_shipped(self)
        editions.activate("gdm")
        self.assertEqual(editions.mode(), "field")
        for view in catalogue.ADMIN_VIEWS:
            self.assertNotIn(view, editions.views(), view)

    def test_the_two_address_driven_screens_need_the_service_key(self):
        """The ADB and switch screens are ADMIN, and that is a decision.

        It went the other way first: both replaced tools the field staff
        already ran, and putting them behind the key means the person holding
        the cabinet door open cannot turn a PoE port off. What changed the
        answer is WHAT THEY REACH. Every other field screen works through the
        project's DeviceMap and can only touch what is listed in it; these two
        take a typed address and act on whatever answers — on a shared network,
        any device at all. A PoE feed cut or an application pushed to the wrong
        box is not undone by noticing afterwards.
        """
        as_shipped(self)
        for view in ("adb", "switch"):
            with self.subTest(view):
                self.assertIn(view, catalogue.ADMIN_VIEWS)
                self.assertNotIn(view, catalogue.BASE_VIEWS)
                for edition in catalogue.EDITIONS:
                    editions.activate(edition.id)
                    self.assertNotIn(view, editions.views(), edition.id)

    def test_admin_mode_adds_them_to_any_edition(self):
        as_shipped(self)
        editions.activate("gaziray")
        editions.set_admin(True)
        for view in catalogue.ADMIN_VIEWS:
            self.assertIn(view, editions.views(), view)

    def test_a_run_that_opened_as_admin_can_drop_to_field_mode(self):
        """Both ways round, as often as asked: an engineer holding the
        secret still has to be able to see what the customer sees."""
        editions.activate("vip-yatakli")
        self.assertTrue(editions.admin())
        self.assertFalse(editions.set_admin(False))
        self.assertEqual(editions.mode(), "field")
        for view in catalogue.ADMIN_VIEWS:
            self.assertNotIn(view, editions.views(), view)
        self.assertTrue(editions.set_admin(True))
        self.assertEqual(editions.mode(), "admin")


class Guard(PanelTest):
    """Hiding a screen is not keeping it.

    The whole API is reachable from the page over the desktop bridge — the
    sidebar only decides what is DRAWN. So the refusal has to sit on the side
    that holds the data, and these tests are what say it does.
    """

    def tearDown(self):
        editions.activate("vip-yatakli")
        super().tearDown()

    def test_a_customer_package_is_refused_the_engineer_endpoints(self):
        as_shipped(self)
        editions.activate("gdm")
        for path in ("/api/piscu", "/api/mqtt"):
            with self.subTest(path):
                self.assertEqual(api.call("GET", path).status, 403)

    def test_admin_mode_opens_them(self):
        editions.activate("vip-yatakli")
        editions.set_admin(True)
        self.assertEqual(api.call("GET", "/api/piscu").status, 200)

    def test_an_undelivered_device_list_reads_as_missing_not_as_a_fault(self):
        """A package whose own map has not arrived yet is a real state. The
        screen has to say what is wrong, not "an unexpected problem"."""
        with undelivered("gdm", "gdm"):
            editions.activate("gdm")
            response = api.call("GET", "/api/state")
            self.assertEqual(response.status, 404)
            self.assertIn("DeviceMap", response.body["error"])

    def test_forgetting_every_credential_at_once_is_an_admin_act(self):
        """The single-device form is how a technician clears a password they
        mistyped and must keep working; "forget all" is not that."""
        as_shipped(self)
        editions.activate("gdm")
        self.assertEqual(
            api.call("POST", "/api/credentials/forget",
                     body={"all": True}).status, 403)

    def test_the_refusal_says_the_path_exists(self):
        """403 rather than 404: a genuine typo and a refusal must not look
        the same in a log."""
        as_shipped(self)
        editions.activate("gaziray")
        response = api.call("GET", "/api/piscu")
        self.assertEqual(response.status, 403)
        self.assertNotEqual(api.call("GET", "/api/nothing").status, 403)

    def test_the_guard_and_the_menu_read_the_same_list(self):
        """Two lists would drift, and then a menu entry would open a screen
        whose data the server refuses."""
        editions.activate("gdm")
        from panel.api import guard
        for path, view in guard.RESTRICTED.items():
            with self.subTest(path):
                self.assertIn(view, catalogue.BASE_VIEWS
                              + catalogue.ADMIN_VIEWS)

    def test_every_endpoint_of_a_guarded_screen_is_guarded(self):
        """Not the ones somebody remembered — all of them.

        This is why `guard.RESTRICTED` matches by PREFIX. The ADB screen has
        eleven endpoints and the switch screen fourteen; written out one by
        one, the list would be complete on the day it was written and quietly
        short from the next endpoint onwards. The check walks the ROUTING
        TABLE, so an endpoint added tomorrow is covered or this fails.
        """
        from panel.api import guard, routes
        registered = sorted(set(routes.GET_ROUTES)
                            | set(routes.POST_ROUTES))
        # Named so the check cannot pass by finding nothing to look at.
        self.assertIn("/api/adb/run", registered)
        self.assertIn("/api/switch/factory-reset", registered)

        for view in ("adb", "switch"):
            paths = [p for p in registered
                     if guard.restricted_view(p) == view]
            self.assertTrue(paths, view)
            with self.subTest(view=view, count=len(paths)):
                # Every path the screen owns, and nothing that is not its own.
                self.assertEqual(
                    paths,
                    sorted(p for p in registered
                           if p == f"/api/{view}" or p.startswith(f"/api/{view}/")))

    def test_a_customer_package_is_refused_the_two_new_ones(self):
        """The screens are gone from the rail; the data has to be gone too.

        Hiding a screen is not keeping it — the whole API is reachable from
        the page over the desktop bridge, so a field package that merely
        stopped drawing these would still turn a PoE port off for anyone who
        asked the endpoint directly.
        """
        as_shipped(self)
        editions.activate("gdm")
        for path in ("/api/adb", "/api/adb/state", "/api/switch",
                     "/api/switch/ports"):
            with self.subTest(path):
                self.assertEqual(api.call("GET", path).status, 403)
        for path, body in (("/api/adb/run", {}),
                           ("/api/switch/factory-reset", {})):
            with self.subTest(path):
                self.assertEqual(
                    api.call("POST", path, body=body).status, 403)

    def test_admin_mode_opens_the_two_new_ones(self):
        """A refusal that never lifts is a screen that does not work."""
        editions.activate("vip-yatakli")
        editions.set_admin(True)
        self.assertEqual(api.call("GET", "/api/switch").status, 200)
        self.assertEqual(api.call("GET", "/api/adb").status, 200)

    def test_a_prefix_does_not_claim_a_path_that_merely_starts_with_it(self):
        from panel.api import guard
        self.assertEqual(guard.restricted_view("/api/switch"), "switch")
        self.assertEqual(guard.restricted_view("/api/switch/ports"), "switch")
        self.assertIsNone(guard.restricted_view("/api/switchboard"))
        self.assertIsNone(guard.restricted_view("/api/adbxyz"))
        self.assertIsNone(guard.restricted_view("/api/state"))


class ProjectSwitching(PanelTest):
    """Opening another project without restarting."""

    def tearDown(self):
        editions.activate("vip-yatakli")
        super().tearDown()

    def test_an_undelivered_project_is_refused_with_a_reason(self):
        with undelivered("vip-yatakli", "vip"):
            editions.activate("vip-yatakli")
            response = api.call("POST", "/api/project/select",
                                body={"key": "vip"})
            self.assertEqual(response.status, 409)
            self.assertIn("VIP", response.body["error"])

    def test_an_unknown_project_is_not_found(self):
        editions.activate("gaziray")
        self.assertEqual(
            api.call("POST", "/api/project/select",
                     body={"key": "somebody-else"}).status, 404)

    def test_a_write_in_progress_blocks_the_switch(self):
        """An IP run is addressed at the devices of the project that was open
        when it was queued; swapping the map underneath it would point the
        rest of the run at different hardware."""
        editions.activate("vip-yatakli")
        job = jobs.Job("ip", "assigning", 1)
        job.state = jobs.RUNNING
        with mock.patch.object(jobs.QUEUE, "list", return_value=[job]):
            response = api.call("POST", "/api/project/select",
                                body={"key": "yatakli"})
        self.assertEqual(response.status, 409)

    def test_switching_drops_what_belonged_to_the_old_project(self):
        """Device ids are positional: "sw1.d3" is a different device in
        another project, so a result kept across the switch would be shown
        against hardware it was never read from."""
        editions.activate("vip-yatakli")
        jobs.view_for(1).write("sw1.d3", mock.Mock(generation=1))
        api.call("POST", "/api/project/select", body={"key": "yatakli"})
        self.assertIsNone(jobs.view_for(1).get("sw1.d3"))


class ServiceKeyExtras(PanelTest):
    """Projects delivered on the stick, next to the ones built in."""

    def tearDown(self):
        editions.activate("vip-yatakli")
        super().tearDown()

    def test_a_stick_carrying_an_own_project_does_not_shadow_the_built_in(self):
        """`add_extra` refuses a key the edition already owns.

        A stick carrying the customer's own map is the natural thing for an
        engineer to carry, and it used to SHADOW the built-in row:
        `projects()` filtered built-ins out of the extras it appended, but
        `is_extra`/`current_is_extra` did not — so selecting the project
        then demanded admin mode, with a 403 that made no sense on the
        customer's own project.
        """
        editions.activate("vip-yatakli")
        self.assertTrue(editions.admin())
        built_in = catalogue.YATAKLI
        # Exactly how a map off the stick names itself: the catalogue row
        # re-pointed at the session copy (see panel.adminkey.pack).
        off_the_stick = dataclasses.replace(
            built_in,
            path="/media/KEY/dabp-projects/DeviceMap_Yatakli.json")
        editions.add_extra(off_the_stick)

        # The menu offers the BUILT-IN row, once, and not the stick's copy.
        offered = [p for p in editions.projects() if p.key == built_in.key]
        self.assertEqual(offered, [built_in])
        self.assertFalse(editions.is_extra(off_the_stick))

        # Opening it is an ordinary field act, not an admin one.
        opened = editions.use_project(built_in.key)
        self.assertEqual(opened, built_in)
        self.assertFalse(editions.current_is_extra())


if __name__ == "__main__":
    unittest.main()
