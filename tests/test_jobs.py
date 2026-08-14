#!/usr/bin/env python3
"""Job queue behaviour.

Covered requirements:
 13. Double-clicking Refresh does not create two jobs.
 14. A second scan does not start while the set's scan is active.
 18. Cancelling a scan ends the running job in a controlled way.
"""
from __future__ import annotations

import threading
import time
import unittest

from panel import jobs, settings, status
from panel.probe import result as probe_result

from .support import fakes
from .support.base import ServiceTest


def _topology(device_count=6):
    devices = [{
        "Name": f"Intercom_{i}", "IP": "127.0.0.1", "IsActive": True,
        "Type": "Announcement", "SubType": "Intercom", "Port": str(10 + i),
        "PBXExtension": str(2000 + i), "Status": {"NoError": True},
    } for i in range(1, device_count + 1)]
    return fakes.device_map(devices, switch_ip="127.0.0.1")


class Queue(ServiceTest):

    def test_13_a_double_click_does_not_create_two_jobs(self):
        self.build_map(_topology())
        with fakes.kyland() as switch, fakes.announcement() as device:
            self.switch_port(switch.port)
            settings.ANNOUNCEMENT_PORT = device.port
            base = self.start_service()

            replies = []
            barrier = threading.Barrier(2)

            def click():
                barrier.wait()
                replies.append(self.call(base, "/api/scan", {"set": 1}))

            t1 = threading.Thread(target=click)
            t2 = threading.Thread(target=click)
            t1.start(); t2.start(); t1.join(10); t2.join(10)

            self.assertEqual(len(replies), 2)
            ids = {reply[1]["id"] for reply in replies}
            self.assertEqual(len(ids), 1, "two separate jobs must not be created")
            flags = [reply[1]["new"] for reply in replies]
            self.assertCountEqual(flags, [True, False])

            code, listing = self.call(base, "/api/jobs")
            scans = [j for j in listing["jobs"] if j["kind"] == "scan"]
            self.assertEqual(len(scans), 1)

            self.await_job(jobs.QUEUE.find(ids.pop()))

    def test_14_a_second_scan_does_not_start_while_one_is_active(self):
        self.build_map(_topology())
        with fakes.kyland() as switch, fakes.announcement() as device:
            self.switch_port(switch.port)
            settings.ANNOUNCEMENT_PORT = device.port
            base = self.start_service()

            code, first = self.call(base, "/api/scan", {"set": 1})
            self.assertEqual(code, 200)
            self.assertTrue(first["new"])

            code, second = self.call(base, "/api/scan", {"set": 1})
            self.assertEqual(code, 202,
                             "no new job must open; the existing one must be returned")
            self.assertFalse(second["new"])
            self.assertEqual(second["id"], first["id"])

            self.await_job(jobs.QUEUE.find(first["id"]))

            # AFTER it finishes a new scan must be possible
            code, third = self.call(base, "/api/scan", {"set": 1})
            self.assertEqual(code, 200)
            self.assertNotEqual(third["id"], first["id"])
            self.await_job(jobs.QUEUE.find(third["id"]))

    def test_14b_different_sets_are_separate_jobs(self):
        self.build_map(_topology(2))
        with fakes.kyland() as switch, fakes.announcement() as device:
            self.switch_port(switch.port)
            settings.ANNOUNCEMENT_PORT = device.port
            base = self.start_service()
            code, one = self.call(base, "/api/scan", {"set": 1})
            code, two = self.call(base, "/api/scan", {"set": 2})
            self.assertNotEqual(one["id"], two["id"])
            self.await_job(jobs.QUEUE.find(one["id"]))
            self.await_job(jobs.QUEUE.find(two["id"]))

    def test_18_cancelling_ends_a_running_job_cleanly(self):
        """Silent devices: the job takes long and is cancelled mid-run."""
        self.build_map(_topology(12))
        with fakes.silent() as silent:
            self.switch_port(silent.port)
            settings.ANNOUNCEMENT_PORT = silent.port
            base = self.start_service()

            code, started = self.call(base, "/api/scan", {"set": 1})
            job = jobs.QUEUE.find(started["id"])
            time.sleep(0.5)

            code, cancelled = self.call(base, "/api/job/cancel",
                                        {"id": started["id"]})
            self.assertEqual(code, 200)
            self.assertTrue(cancelled["cancelled"])

            self.await_job(job, timeout=25)
            self.assertEqual(job.state, jobs.CANCELLED)

            # A cancelled job must be removable from the queue
            code, removed = self.call(base, "/api/job/remove",
                                      {"id": started["id"]})
            self.assertEqual(code, 200)
            self.assertTrue(removed["removed"])

    def test_18b_a_running_job_cannot_be_removed(self):
        self.build_map(_topology(12))
        with fakes.silent() as silent:
            self.switch_port(silent.port)
            settings.ANNOUNCEMENT_PORT = silent.port
            base = self.start_service()
            code, started = self.call(base, "/api/scan", {"set": 1})
            code, removed = self.call(base, "/api/job/remove",
                                      {"id": started["id"]})
            self.assertEqual(code, 409)
            self.assertFalse(removed["removed"])
            self.call(base, "/api/job/cancel", {"id": started["id"]})
            self.await_job(jobs.QUEUE.find(started["id"]), timeout=25)

    def test_the_light_refresh_reads_verified_devices_only(self):
        """The refresh is limited to devices the scan turned green.

        Retrying an unreachable device every round grows the round by that
        device's timeout, and while the refresh waits, the data of the working
        devices goes stale.
        """
        import socket

        # A closed port: the camera connection is refused at once -> red.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
        probe.close()

        topology = fakes.device_map([
            {"Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
             "Type": "Announcement", "SubType": "Intercom", "Port": "11",
             "PBXExtension": "2001", "Status": {"NoError": True}},
            {"Name": "Cam_1", "IP": "127.0.0.1", "IsActive": True,
             "Type": "Camera", "SubType": "Corridor", "Port": "12",
             "Status": {"NoError": True}},
        ], switch_ip="127.0.0.1")
        inventory = self.build_map(topology)
        camera = inventory.by_type("Camera")[0]

        with fakes.kyland() as switch, fakes.announcement() as device:
            self.switch_port(switch.port)
            settings.ANNOUNCEMENT_PORT = device.port
            settings.VIDEO_PORT = closed
            base = self.start_service()

            code, started = self.call(base, "/api/scan", {"set": 1})
            self.await_job(jobs.QUEUE.find(started["id"]), timeout=30)

            code, state = self.call(base, "/api/state?set=1")
            states = {d["id"]: d["result"]["state"] for d in state["devices"]}
            green = [i for i, s in states.items() if s == status.OK]
            self.assertEqual(states[camera.id], status.FAILED)
            self.assertTrue(green)

            code, refreshed = self.call(base, "/api/refresh", {"set": 1})
            self.assertEqual(code, 200)
            self.assertCountEqual(refreshed["refreshed"], green)
            self.assertNotIn(camera.id, refreshed["refreshed"])

            # A red device is not refreshed even when explicitly asked for.
            asked = self.call(base, "/api/refresh",
                              {"set": 1, "devices": [camera.id]})[1]
            self.assertEqual(asked["refreshed"], [])

    def test_the_light_refresh_is_rejected_during_a_full_scan(self):
        self.build_map(_topology(12))
        with fakes.silent() as silent:
            self.switch_port(silent.port)
            settings.ANNOUNCEMENT_PORT = silent.port
            base = self.start_service()
            code, started = self.call(base, "/api/scan", {"set": 1})

            code, refreshed = self.call(base, "/api/refresh", {"set": 1})
            self.assertEqual(code, 409)
            self.assertTrue(refreshed["waiting"])

            self.call(base, "/api/job/cancel", {"id": started["id"]})
            self.await_job(jobs.QUEUE.find(started["id"]), timeout=25)

    def test_the_light_refresh_is_rejected_during_a_writing_run(self):
        """No device is read while a run is in progress.

        A full scan enters the queue and so cannot collide with a run; the
        light refresh reads on the request's own thread and stays outside the
        queue. During a run a device is rebooting or its PoE port is off — that
        temporary state must not be recorded as a permanent result.
        """
        self.build_map(_topology(4))
        with fakes.silent() as silent:
            self.switch_port(silent.port)
            settings.ANNOUNCEMENT_PORT = silent.port
            base = self.start_service()

            release = threading.Event()
            job = jobs.Job("firmware", "Firmware install · 2 devices", 1)
            jobs.QUEUE.submit(job, lambda j: release.wait(20))
            try:
                for _ in range(100):        # wait for the job to start
                    if job.state == jobs.RUNNING:
                        break
                    time.sleep(0.05)
                self.assertEqual(job.state, jobs.RUNNING)

                code, refreshed = self.call(base, "/api/refresh", {"set": 1})
                self.assertEqual(code, 409)
                self.assertTrue(refreshed["waiting"])
            finally:
                release.set()
                self.await_job(job, timeout=25)

    def test_automatic_scans_do_not_fill_the_queue_history(self):
        """The minute-long scan must not push the user's records out.

        Under the normal history limit, twenty minutes of automatic scans
        would drop every IP assignment / configuration / firmware record from
        the queue. Only the newest finished automatic scan is kept; manually
        started jobs stay as they are.
        """
        manual = jobs.Job("firmware", "Firmware install · 1 device", 1)
        jobs.QUEUE.submit(manual, lambda j: None)
        self.await_job(manual, timeout=10)

        for _ in range(5):
            auto = jobs.Job("scan", "Automatic scan · Set 1", 1,
                            key="scan:1", auto=True)
            jobs.QUEUE.submit(auto, lambda j: None)
            self.await_job(auto, timeout=10)

        listing = jobs.QUEUE.list()
        automatic = [j for j in listing if j.auto]
        # Pruning runs while adding: the job being added has not finished yet
        # so it is not dropped. The count therefore never exceeds two and does
        # NOT grow with the number of rounds — which is the point.
        self.assertLessEqual(len(automatic), 2, "automatic scans piled up")
        self.assertIn(manual.id, [j.id for j in listing],
                      "a manually started job must stay in the history")

    def test_the_automatic_flag_is_in_the_reply(self):
        """The UI must be able to tell an automatic round from a manual one."""
        self.build_map(_topology(2))
        with fakes.silent() as silent:
            self.switch_port(silent.port)
            settings.ANNOUNCEMENT_PORT = silent.port
            base = self.start_service()

            code, started = self.call(base, "/api/scan",
                                      {"set": 1, "auto": True})
            self.assertEqual(code, 200)
            self.assertTrue(started["auto"])
            self.assertIn("Automatic scan", started["title"])
            self.call(base, "/api/job/cancel", {"id": started["id"]})
            self.await_job(jobs.QUEUE.find(started["id"]), timeout=25)

            code, second = self.call(base, "/api/scan", {"set": 1})
            self.assertFalse(second["auto"])
            self.assertIn("Full scan", second["title"])
            self.call(base, "/api/job/cancel", {"id": second["id"]})
            self.await_job(jobs.QUEUE.find(second["id"]), timeout=25)

    def test_job_rows_exist_from_the_start(self):
        """The rows must be ready before the scan begins."""
        self.build_map(_topology(4))
        with fakes.silent() as silent:
            self.switch_port(silent.port)
            settings.ANNOUNCEMENT_PORT = silent.port
            base = self.start_service()
            code, started = self.call(base, "/api/scan", {"set": 1})
            code, full = self.call(base, f"/api/job?id={started['id']}")
            # 4 devices + the switch; counters exclude progress rows
            self.assertEqual(full["counts"]["total"], 5)
            self.assertGreaterEqual(len(full["rows"]), 5)
            for row in full["rows"]:
                self.assertIn("name", row)
                self.assertIn("ip", row)
                self.assertIn("readMethod", row)

            self.call(base, "/api/job/cancel", {"id": started["id"]})
            self.await_job(jobs.QUEUE.find(started["id"]), timeout=25)

    def test_a_closed_queue_takes_no_job_and_can_be_reopened(self):
        """After shutdown the queue does not swallow silently; reopened it
        works again.

        A closed manager used to queue new jobs, but with the dispatcher
        thread dead none of them started: the user would see "Queued" forever.
        """
        queue = jobs.JobQueue()
        try:
            done = threading.Event()
            job = jobs.Job("test", "deneme", 1, key="t:1")
            queue.submit(job, lambda j: done.set())
            self.assertTrue(done.wait(5), "the job should have run")

            queue.close()
            self.assertTrue(queue.is_closed())
            with self.assertRaises(RuntimeError):
                queue.submit(jobs.Job("test", "ikinci", 1, key="t:2"),
                             lambda j: None)

            queue.open()
            second_done = threading.Event()
            queue.submit(jobs.Job("test", "ucuncu", 1, key="t:3"),
                         lambda j: second_done.set())
            self.assertTrue(second_done.wait(5),
                            "a reopened queue must run again")
        finally:
            queue.close()

    def test_shutdown_waits_for_a_running_job_to_finish_its_cleanup(self):
        """A daemon job must not be cut off before leaving hardware safe."""
        queue = jobs.JobQueue()
        started = threading.Event()
        entered_cleanup = threading.Event()
        finish_cleanup = threading.Event()
        closed = threading.Event()
        close_result = []

        def body(job):
            started.set()
            job.cancel.wait(2)
            entered_cleanup.set()
            finish_cleanup.wait(2)

        try:
            queue.submit(
                jobs.Job("ip", "PoE safety trial", 1, key="ip:1"),
                body,
            )
            self.assertTrue(started.wait(1))

            def close():
                close_result.append(queue.close())
                closed.set()

            shutdown = threading.Thread(target=close)
            shutdown.start()
            self.assertTrue(entered_cleanup.wait(1))
            self.assertFalse(closed.is_set())
            finish_cleanup.set()
            shutdown.join(1)
            self.assertTrue(closed.is_set())
            self.assertEqual(close_result, [True])
        finally:
            finish_cleanup.set()
            queue.close()

    def test_an_old_job_result_does_not_overwrite_the_new_view(self):
        """The job record and the device view are kept apart."""
        view = jobs.view_for(7)
        result = probe_result.success({"version": "1.2.5"}, "http")
        result.generation = jobs.next_generation()
        view.write("d1", result)

        old_job = jobs.Job("scan", "old", 7)
        old_job.add_row("d1", "Old job row", state="failed",
                        note="No answer")
        # The job row changed but the device view stayed the same
        self.assertEqual(view.get("d1").state, status.OK)
        self.assertEqual(old_job.rows()[0]["state"], "failed")

    def test_lifecycle_and_outcome_are_separate(self):
        """A job returning normally must not look successful on device errors."""
        job = jobs.Job("scan", "Scan", 1)
        job.add_row("d1", "First device", state="done", counted=True)
        job.add_row("d2", "Second device", state="failed", counted=True)
        job.state = jobs.DONE

        dto = job.dto()
        self.assertEqual(dto["state"], "done")
        self.assertEqual(dto["outcome"], "warning")

        job.state = jobs.FAILED
        self.assertEqual(job.dto()["outcome"], "failed")


class CrashingJobQueue(unittest.TestCase):
    """A crashing job must not lock the queue.

    The chain seen in the field: the IP assignment run crashes, the job stays
    "running" forever, and because that job counts as a "writing job" both the
    light refresh and the full scan are refused with 409 — after the run every
    screen stopped refreshing.
    """

    def setUp(self):
        self.queue = jobs.JobQueue()
        self.addCleanup(self.queue.close)

    def _wait(self, job, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if job.state in (jobs.DONE, jobs.CANCELLED, jobs.FAILED):
                return True
            time.sleep(0.02)
        return False

    def _run(self, explode):
        job = jobs.Job("ip", "IP atama · Test", 1)
        self.queue.submit(job, explode)
        self.assertTrue(self._wait(job), f"the job did not close: {job.state}")
        return job

    def test_systemexit_does_not_leave_a_job_running(self):
        """argparse calls sys.exit() on an invalid argument; that is NOT an
        Exception and the old `except Exception` missed it."""
        def explode(job):
            raise SystemExit(2)

        job = self._run(explode)
        self.assertEqual(job.state, jobs.FAILED)
        self.assertIn("2", job.error)

    def test_the_queue_keeps_working_after_a_crashed_job(self):
        """The dispatcher thread must not die: that is the real damage."""
        self._run(lambda job: (_ for _ in ()).throw(SystemExit(1)))

        following = jobs.Job("scan", "Next job", 1)
        ran = threading.Event()
        self.queue.submit(following, lambda job: ran.set())
        self.assertTrue(ran.wait(5.0), "the queue stalled")
        self.assertTrue(self._wait(following))
        self.assertEqual(following.state, jobs.DONE)

    def test_a_writing_job_does_not_stay_stuck(self):
        """The source of the lock: `active`/`RUNNING` saw the stuck job."""
        job = self._run(lambda j: (_ for _ in ()).throw(SystemExit(1)))
        self.assertIsNone(self.queue.active(job.key))
        self.assertEqual(
            [j for j in self.queue.list() if j.state == jobs.RUNNING], [])

    def test_a_job_without_a_body_is_closed(self):
        job = jobs.Job("scan", "Bodyless", 1)
        self.queue.submit(job, lambda j: None)
        self.queue._bodies.pop(job.id, None)        # as if pruned
        self.assertTrue(self._wait(job))
        self.assertEqual(job.state, jobs.FAILED)

    def test_an_ordinary_error_is_reported_as_before(self):
        job = self._run(
            lambda j: (_ for _ in ()).throw(ValueError("No port selected")))
        self.assertEqual(job.state, jobs.FAILED)
        self.assertEqual(job.error, "No port selected")


class IpSummaryError(unittest.TestCase):
    """What a partially completed run should say.

    "The IP assignment script exited with code 1" told the user nothing: the
    appeared even when ten of twelve ports were done.
    """

    def _summary(self, ok, failed, skipped=0, code=1):
        from panel.api.tasks.ip_task import _run_summary_error

        return _run_summary_error(
            {"total": ok + failed + skipped, "ok": ok,
             "failed": failed, "skipped": skipped}, code)

    def test_partial_success_reports_the_numbers(self):
        text = self._summary(ok=10, failed=2)
        self.assertIn("10/12", text)
        self.assertIn("2 port", text)
        self.assertNotIn("koduyla", text)

    def test_a_separate_sentence_when_none_finished(self):
        self.assertIn("No port could be completed", self._summary(ok=0, failed=12))

    def test_it_falls_back_to_the_exit_code_when_nothing_is_missing(self):
        """With clean port rows the only thing to say is the exit code."""
        self.assertIn("exited with code 2", self._summary(ok=12, failed=0, code=2))

    def test_skipped_ports_count_as_incomplete(self):
        text = self._summary(ok=8, failed=1, skipped=3)
        self.assertIn("8/12", text)
        self.assertIn("4 port", text)


if __name__ == "__main__":
    unittest.main()
