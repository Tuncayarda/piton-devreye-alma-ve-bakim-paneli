#!/usr/bin/env python3
"""Compartment LCD IP-assignment API boundaries.

The Android runner has its own hardware-level tests.  These tests pin the
public contract around it: per-device commissioning addresses, APK selections
that never expose a path, and Intercom-only diagnostics which must not accept
an LCD merely because the LCD now supports IP assignment.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from panel import api, firmware
from panel.api.routes import ip_routes
from panel.inventory import device_map

from .support import fakes
from .support.base import PanelTest


def _lcd(name: str, host: int, port: int) -> dict:
    return {
        "Name": name,
        "IP": f"10.n.1.{host}",
        "IsActive": True,
        "Type": "LCD",
        "SubType": "Compartment",
        "Port": str(port),
        "PBXExtension": str(6000 + host - 39),
        "Status": {"NoError": True},
    }


class LcdIpApi(PanelTest):

    def setUp(self):
        super().setUp()
        self.build_map(fakes.device_map(
            [_lcd("Compartment_Lcd_1", 40, 13),
             _lcd("Compartment_Lcd_2", 41, 14)],
            switch_ip="10.n.1.101"))

    def two_switches(self):
        self.build_map(fakes.device_map(
            [_lcd("Compartment_Lcd_1", 40, 13),
             _lcd("Compartment_Lcd_2", 41, 14)],
            switch_ip="10.n.1.101",
            second_switch={
                "Name": "Bench_SW_2", "IP": "10.n.1.102",
                "IsActive": True, "Manufacturer": "KYLAND",
                "Status": {"NoError": True}, "Devices": [],
            }))

    @staticmethod
    def plan(set_no: int = 7):
        with mock.patch.object(ip_routes.ip_assign, "can_flush_arp",
                               return_value=True):
            return api.call("GET", "/api/ip/plan", query={
                "set": str(set_no), "groups": "Compartment LCD"})

    @staticmethod
    def apk(name: str = "train-lcd.apk") -> str:
        path = Path(tempfile.mkdtemp(prefix="lcd-apk-")) / name
        path.write_bytes(b"apk-test-payload")
        return str(path)

    def test_set_seven_plan_keeps_each_factory_host_and_changes_the_set(self):
        response = self.plan(7)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["assignmentKind"], "compartment-lcd")
        self.assertEqual(response.body["sourceMode"], "perDevice")
        # A display goes back to ITS OWN set-1 address, not to a shared one.
        self.assertTrue(response.body["factoryResetSupported"])
        self.assertEqual(response.body["factoryResetKind"], "perDevice")
        self.assertTrue(response.body["manualAssignSupported"])
        self.assertEqual(response.body["software"]["extension"], "apk")
        self.assertTrue(response.body["physicalPortMode"])
        rows = response.body["candidateRows"]
        self.assertEqual([row["sourceIp"] for row in rows],
                         ["10.1.1.40", "10.1.1.41"])
        self.assertEqual([row["factoryIp"] for row in rows],
                         ["10.1.1.40", "10.1.1.41"])
        self.assertEqual([row["targetIp"] for row in rows],
                         ["10.7.1.40", "10.7.1.41"])

    def test_lcd_plan_can_execute_on_switch_two_without_moving_device_map_rows(self):
        self.two_switches()

        with mock.patch.object(ip_routes.ip_assign, "can_flush_arp",
                               return_value=True):
            response = api.call("GET", "/api/ip/plan", query={
                "set": "7", "groups": "Compartment LCD", "switch": "sw2"})

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["switchId"], "sw2")
        self.assertEqual(response.body["switchIp"], "10.7.1.102")
        self.assertEqual(response.body["deviceSwitchId"], "sw1")
        self.assertTrue(response.body["switchOverride"])
        self.assertEqual(response.body["allowedPorts"], list(range(1, 25)))
        self.assertEqual(
            [(row["deviceId"], row["deviceSwitchId"], row["port"],
              row["sourceIp"], row["targetIp"])
             for row in response.body["candidateRows"]],
            [("sw1.d1", "sw1", 13, "10.1.1.40", "10.7.1.40"),
             ("sw1.d2", "sw1", 14, "10.1.1.41", "10.7.1.41")])
        self.assertEqual(
            {row["id"]: row["groupDevices"]
             for row in response.body["switches"]},
            {"sw1": 2, "sw2": 2})

    def test_arbitrary_port_plan_separates_physical_work_from_candidates(self):
        with mock.patch.object(ip_routes.ip_assign, "can_flush_arp",
                               return_value=True):
            response = api.call("GET", "/api/ip/plan", query={
                "set": "7", "groups": "Compartment LCD", "ports": "8"})

        self.assertEqual(response.status, 200)
        self.assertTrue(response.body["physicalPortMode"])
        self.assertEqual(response.body["rows"], [{
            **response.body["rows"][0],
            "port": 8,
            "deviceId": None,
            "sourceIp": "",
            "targetIp": "",
            "identityMode": "discover",
        }])
        self.assertEqual(
            [row["deviceId"] for row in response.body["candidateRows"]],
            ["sw1.d1", "sw1.d2"])

    def test_plan_shows_apk_names_but_never_the_local_path(self):
        inventory = device_map.load(7, self.map_path)
        lcds = inventory.by_type("LCD", "Compartment")
        path = self.apk()
        firmware.select_file([device.id for device in lcds], path, set_no=7)

        response = self.plan(7)

        files = response.body["software"]["files"]
        self.assertEqual(set(files), {device.id for device in lcds})
        self.assertTrue(all(record["selected"] for record in files.values()))
        self.assertTrue(all(record["name"] == "train-lcd.apk"
                            for record in files.values()))
        self.assertNotIn(str(Path(path).parent), str(response.body))

    def _run_request(self, **extra) -> dict:
        return {
            "set": 7,
            "switch": "sw1",
            "groups": ["Compartment LCD"],
            "ports": "13-14",
            "installApk": True,
            **extra,
        }

    def test_apk_install_is_rejected_before_queueing_when_a_port_has_no_file(self):
        with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                return_value={"ports": []}),
              mock.patch.object(ip_routes.jobs.QUEUE, "submit") as submit):
            response = api.call("POST", "/api/ip/run",
                                body=self._run_request())

        self.assertEqual(response.status, 400)
        self.assertIn("file", response.body["error"].lower())
        submit.assert_not_called()

    def test_valid_apk_selection_reaches_the_job_as_a_boolean_not_a_path(self):
        inventory = device_map.load(7, self.map_path)
        lcds = inventory.by_type("LCD", "Compartment")
        apk_path = self.apk()
        firmware.select_file([device.id for device in lcds], apk_path,
                             set_no=7)
        queued = {}

        def submit(job, task):
            queued.update(job=job, task=task)
            return job, True

        task = object()
        with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                return_value={"ports": []}),
              mock.patch.object(ip_routes, "ip_assign_task",
                                return_value=task) as make_task,
              mock.patch.object(ip_routes.jobs.QUEUE, "submit",
                                side_effect=submit)):
            response = api.call("POST", "/api/ip/run",
                                body=self._run_request())

        self.assertEqual(response.status, 200)
        options = make_task.call_args.args[-1]
        self.assertIs(options["installApk"], True)
        self.assertNotIn("apkPath", options)
        self.assertNotIn(apk_path, str(options))
        self.assertIs(queued["task"], task)

    def test_switch_two_is_the_job_and_task_boundary_not_the_device_map_switch(self):
        self.two_switches()
        inventory = device_map.load(7, self.map_path)
        lcds = inventory.by_type("LCD", "Compartment")
        firmware.select_file(
            [device.id for device in lcds], self.apk(), set_no=7)
        task = object()

        with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                return_value={"ports": []}),
              mock.patch.object(ip_routes, "ip_assign_task",
                                return_value=task) as make_task,
              mock.patch.object(ip_routes.jobs.QUEUE, "submit",
                                side_effect=lambda job, work: (job, True))
              as submit):
            response = api.call("POST", "/api/ip/run", body={
                "set": 7,
                "switch": "sw2",
                "groups": ["Compartment LCD"],
                "ports": "13-14",
                "installApk": True,
            })

        self.assertEqual(response.status, 200)
        args = make_task.call_args.args
        self.assertEqual(args[1:5], ("sw2", [13, 14], {},
                                     ["Compartment LCD"]))
        self.assertIs(args[-1]["installApk"], True)
        queued_job, queued_task = submit.call_args.args
        self.assertEqual(queued_job.key, "ip:7:sw2")
        self.assertIs(queued_task, task)

    def test_an_empty_mask_reaches_the_runner_as_unstated_not_as_24(self):
        """The route must not materialise /24 before the runner can decide.

        `effective_prefix` asks the operator, then the PROJECT, then falls
        to 24 — but the route used to parse an empty mask box straight to
        24, so the project branch (Gaziray's stated /16) was unreachable
        and every HTTP-driven run wrote 255.255.255.0. The runner-side
        halves of this contract are pinned in tests/test_data.py
        (`test_a_project_that_states_a_mask_has_it_written` and
        neighbours); this is the route-side half.
        """
        self.two_switches()
        inventory = device_map.load(7, self.map_path)
        lcds = inventory.by_type("LCD", "Compartment")
        firmware.select_file(
            [device.id for device in lcds], self.apk(), set_no=7)
        task = object()

        with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                return_value={"ports": []}),
              mock.patch.object(ip_routes, "ip_assign_task",
                                return_value=task) as make_task,
              mock.patch.object(ip_routes.jobs.QUEUE, "submit",
                                side_effect=lambda job, work: (job, True))):
            response = api.call("POST", "/api/ip/run", body={
                "set": 7,
                "switch": "sw2",
                "groups": ["Compartment LCD"],
                "ports": "13-14",
                "targetMask": "",
            })

        self.assertEqual(response.status, 200)
        self.assertEqual(make_task.call_args.args[-1]["targetPrefix"], 0)

    def test_a_device_id_cannot_be_used_as_the_physical_switch(self):
        with mock.patch.object(ip_routes.jobs.QUEUE, "submit") as submit:
            response = api.call("POST", "/api/ip/run", body={
                "set": 7,
                "switch": "sw1.d1",
                "groups": ["Compartment LCD"],
                "ports": "13",
            })

        self.assertEqual(response.status, 400)
        submit.assert_not_called()

    def test_lcd_run_accepts_a_physical_poe_port_not_used_in_device_map(self):
        self.two_switches()

        with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                return_value={"ports": []}),
              mock.patch.object(ip_routes, "ip_assign_task",
                                return_value=object()) as make_task,
              mock.patch.object(ip_routes.jobs.QUEUE, "submit",
                                side_effect=lambda job, task: (job, True))
              as submit):
            response = api.call("POST", "/api/ip/run", body={
                "set": 7,
                "switch": "sw2",
                "groups": ["Compartment LCD"],
                "ports": "8",
            })

        self.assertEqual(response.status, 200)
        self.assertEqual(make_task.call_args.args[2], [8])
        submit.assert_called_once()

    def test_client_cannot_inject_an_lcd_identity_or_address_for_a_port(self):
        task = object()
        with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                return_value={"ports": []}),
              mock.patch.object(ip_routes, "ip_assign_task",
                                return_value=task) as make_task,
              mock.patch.object(ip_routes.jobs.QUEUE, "submit",
                                side_effect=lambda job, work: (job, True))):
            response = api.call("POST", "/api/ip/run", body={
                "set": 7,
                "switch": "sw1",
                "groups": ["Compartment LCD"],
                "ports": "8",
                "deviceId": "sw1.d2",
                "deviceSwitchId": "sw2",
                "sourceIp": "192.0.2.10",
                "targetIp": "192.0.2.11",
            })

        self.assertEqual(response.status, 200)
        options = make_task.call_args.args[-1]
        for key in ("deviceId", "deviceSwitchId", "sourceIp", "targetIp"):
            self.assertNotIn(key, options)

    def test_lcd_physical_port_must_stay_inside_the_poe_face(self):
        with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                return_value={"ports": []}),
              mock.patch.object(ip_routes.jobs.QUEUE, "submit") as submit):
            response = api.call("POST", "/api/ip/run", body={
                "set": 7,
                "switch": "sw1",
                "groups": ["Compartment LCD"],
                "ports": "25",
            })

        self.assertEqual(response.status, 400)
        submit.assert_not_called()

    def test_lcd_cannot_enter_the_intercom_address_map(self):
        """The map reads an HTTP settings page; a display has none."""
        address_map = api.call("GET", "/api/ip/address-map", query={
            "set": "7", "switch": "sw1", "group": "Compartment LCD"})

        self.assertEqual(address_map.status, 400)

    def test_an_lcd_factory_reset_runs_the_android_flow_back_to_set_one(self):
        """Not the Intercom flow: nothing is gathered on one address.

        Each display keeps its own host octet, so "factory" here means the
        set-1 form of its own DeviceMap row — which is the ordinary run with
        the two sets the other way round.
        """
        queued = {}

        def submit(job, task):
            queued.update(job=job, task=task)
            return job, True

        task = object()
        with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                return_value={"ports": []}),
              mock.patch.object(ip_routes, "ip_assign_task",
                                return_value=task) as make_task,
              mock.patch.object(ip_routes.jobs.QUEUE, "submit",
                                side_effect=submit)):
            response = api.call("POST", "/api/ip/factory-reset", body={
                "set": 7,
                "switch": "sw1",
                "groups": ["Compartment LCD"],
                "ports": "13-14",
            })

        self.assertEqual(response.status, 200)
        self.assertIs(queued["task"], task)
        options = make_task.call_args.args[-1]
        self.assertEqual(options["sourceSet"], 7)
        self.assertEqual(options["targetSet"], 1)
        # 0 = the operator stated no mask. The route no longer materialises
        # /24 here; `lcd_runner` resolves 0 through `effective_prefix`, which
        # asks the project first — the /24 default used to make a project's
        # stated /16 unreachable.
        self.assertEqual(options["targetPrefix"], 0)

    def test_the_bench_flow_writes_the_address_the_operator_typed(self):
        queued = {}

        def submit(job, task):
            queued.update(job=job, task=task)
            return job, True

        task = object()
        with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                return_value={"ports": []}),
              mock.patch.object(ip_routes, "lcd_manual_task",
                                return_value=task) as make_task,
              mock.patch.object(ip_routes.jobs.QUEUE, "submit",
                                side_effect=submit)):
            response = api.call("POST", "/api/ip/lcd-assign", body={
                "set": 7, "switch": "sw1", "port": "8",
                "targetIp": "10.9.1.44", "targetMask": "/8",
            })

        self.assertEqual(response.status, 200)
        self.assertIs(queued["task"], task)
        self.assertEqual(make_task.call_args.args[2], 8)
        options = make_task.call_args.args[-1]
        self.assertEqual(options["targetIp"], "10.9.1.44")
        self.assertEqual(options["targetPrefix"], 8)

    def test_the_bench_flow_refuses_a_bad_address_a_bad_mask_and_two_ports(self):
        for body, missing in (
                ({"port": "8", "targetIp": "not-an-ip"}, "address"),
                ({"port": "8", "targetIp": "10.9.1.44",
                  "targetMask": "255.0.255.0"}, "mask"),
                ({"port": "8-9", "targetIp": "10.9.1.44"}, "one port")):
            with (mock.patch.object(ip_routes.ip_assign, "protected_ports",
                                    return_value={"ports": []}),
                  mock.patch.object(ip_routes.jobs.QUEUE, "submit") as submit):
                response = api.call("POST", "/api/ip/lcd-assign", body={
                    "set": 7, "switch": "sw1", **body})
            self.assertEqual(response.status, 400, missing)
            submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
