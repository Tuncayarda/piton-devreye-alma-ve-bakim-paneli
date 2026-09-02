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
from types import SimpleNamespace

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

            _code, listing = self.call(base, "/api/jobs")
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
            _code, one = self.call(base, "/api/scan", {"set": 1})
            _code, two = self.call(base, "/api/scan", {"set": 2})
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

            _code, started = self.call(base, "/api/scan", {"set": 1})
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
            _code, started = self.call(base, "/api/scan", {"set": 1})
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

            _code, started = self.call(base, "/api/scan", {"set": 1})
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

            # A "needs inspection" row IS refreshed: somebody proved that
            # device alive, and it should heal the moment its protocol
            # answers again rather than sit orange until the next scan.
            from panel.probe.result import ProbeResult
            jobs.view_for(1).write(camera.id, ProbeResult(
                state=status.REVIEW, generation=jobs.next_generation()))
            again = self.call(base, "/api/refresh",
                              {"set": 1, "devices": [camera.id]})[1]
            self.assertEqual(again["refreshed"], [camera.id])
            code, state = self.call(base, "/api/state?set=1")
            states = {d["id"]: d["result"]["state"]
                      for d in state["devices"]}
            # The port is still closed and nothing answers ping here, so
            # the re-read settles the row honestly back to red.
            self.assertEqual(states[camera.id], status.FAILED)

    def test_the_light_refresh_is_rejected_during_a_full_scan(self):
        self.build_map(_topology(12))
        with fakes.silent() as silent:
            self.switch_port(silent.port)
            settings.ANNOUNCEMENT_PORT = silent.port
            base = self.start_service()
            _code, started = self.call(base, "/api/scan", {"set": 1})

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
            _code, started = self.call(base, "/api/scan", {"set": 1})
            _code, full = self.call(base, f"/api/job?id={started['id']}")
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


class CancelDispatchRace(unittest.TestCase):
    """The cancel decision and the RUNNING stamp share the dispatch lock.

    The dispatcher used to pop the job under the lock but stamp it RUNNING
    outside it. A cancel landing in that gap still saw QUEUED and took the
    "never started" branch — every row marked skipped with "cancelled", the
    job closed — while the dispatcher went on to run the body anyway. The
    user was told nothing ran; the devices were written to regardless.
    """

    def setUp(self):
        self.queue = jobs.JobQueue()
        self.addCleanup(self.queue.close)

    def test_a_cancel_landing_on_the_dispatch_window_sees_running(self):
        """Pins the race by parking the dispatcher at the exact instant it
        stamps RUNNING — the widest version of the old gap — and cancelling
        right there. The cancel must find a RUNNING job (flag only, rows
        left to the body), never a QUEUED one it can pretend to stop."""

        class HeldJob(jobs.Job):
            """Parks whoever stamps it RUNNING until told to proceed."""

            def __init__(self, *args, **kwargs):
                self.entering = threading.Event()
                self.proceed = threading.Event()
                super().__init__(*args, **kwargs)

            @property
            def state(self):
                return self._state

            @state.setter
            def state(self, value):
                if value == jobs.RUNNING and not self.entering.is_set():
                    self.entering.set()
                    self.proceed.wait(5)
                self._state = value

        job = HeldJob("scan", "Race trial", 1)
        # A row the body never touches: under the old code the too-early
        # cancel branch marked it "skipped · cancelled" while the job ran.
        job.add_row("bystander", "Untouched device", state="queued",
                    counted=True)
        ran = threading.Event()
        cancel_done = threading.Event()

        def body(j):
            # The body waits for the cancel to land first, so the final
            # state is decided by the flag and not by thread luck.
            cancel_done.wait(5)
            ran.set()

        self.queue.submit(job, body)
        self.assertTrue(job.entering.wait(5), "the job never dispatched")

        answers = []

        def cancel():
            answers.append(self.queue.cancel(job.id))
            cancel_done.set()

        canceller = threading.Thread(target=cancel)
        canceller.start()
        # Let the cancel reach the queue lock the dispatcher now holds.
        # Under the old code there was no lock to reach: this pause was
        # exactly the time it needed to finish its "never started" branch.
        time.sleep(0.2)
        job.proceed.set()
        canceller.join(5)

        deadline = time.time() + 5
        while (job.state not in (jobs.DONE, jobs.CANCELLED, jobs.FAILED)
               and time.time() < deadline):
            time.sleep(0.02)

        self.assertEqual(answers, [True])
        self.assertTrue(ran.is_set(),
                        "the body was already dispatched and must have run")
        self.assertEqual(job.state, jobs.CANCELLED)
        # The proof of the fix: the cancel took the RUNNING branch, so no
        # row was stamped "skipped before start" for a job that ran.
        self.assertEqual(job.rows()[0]["state"], "queued")


class DeviceClaim(unittest.TestCase):
    """panel.jobs.access — the one gate the three sweeping workers share."""

    def setUp(self):
        jobs.access.reset()
        self.addCleanup(jobs.access.reset)

    def test_a_cancelled_wait_abandons_without_taking_the_claim(self):
        """QUEUE.close() must not hang behind an ADB-screen operation: the
        worker waiting for the claim polls its job's cancel flag, and a
        cancel ends the wait with nothing acquired."""
        self.assertTrue(jobs.access.try_acquire("adb-screen"))
        flag = {"cancelled": True}
        self.assertFalse(jobs.access.acquire("job:x",
                                             cancelled=lambda: flag["cancelled"],
                                             poll=0.01))
        # The abandoned waiter took nothing: the holder is unchanged and a
        # release from it must not free the screen's claim.
        jobs.access.release("job:x")
        self.assertEqual(jobs.access.holder(), "adb-screen")
        self.assertFalse(jobs.access.try_acquire("refresh"))

    def test_release_by_a_non_owner_changes_nothing(self):
        self.assertTrue(jobs.access.try_acquire("refresh"))
        jobs.access.release("job:someone-else")
        self.assertEqual(jobs.access.holder(), "refresh")
        jobs.access.release("refresh")
        self.assertEqual(jobs.access.holder(), "")
        self.assertTrue(jobs.access.try_acquire("adb-screen"))

    def test_reset_frees_a_held_claim_and_survives_the_late_release(self):
        """Shutdown drops the claim; the worker it belonged to may still run
        its finally afterwards, and that late release must neither raise
        nor free a claim the NEXT service has taken."""
        self.assertTrue(jobs.access.try_acquire("job:old"))
        jobs.access.reset()
        self.assertTrue(jobs.access.try_acquire("job:new"))
        jobs.access.release("job:old")      # the stale finally
        self.assertEqual(jobs.access.holder(), "job:new")

    def test_busy_error_speaks_sentences_not_claim_tokens(self):
        """The refusal a claim produces is user-facing text: the internal
        token ("adb-screen", "job:j3f…") leaked into a toast verbatim the
        first time it was needed."""
        self.assertTrue(jobs.access.try_acquire("adb-screen"))
        self.assertNotIn("adb-screen", jobs.busy_error())
        jobs.access.reset()

        job = jobs.Job("config", "Configure 3 devices", 1, key="cfg:test")
        jobs.QUEUE._jobs.append(job)
        self.addCleanup(lambda: jobs.QUEUE._jobs.remove(job))
        self.assertTrue(jobs.access.try_acquire(f"job:{job.id}"))
        message = jobs.busy_error()
        self.assertIn("Configure 3 devices", message)
        self.assertNotIn(job.id, message)


class DeviceView(unittest.TestCase):
    """The registry of per-set views, across a project switch and a cancel."""

    def setUp(self):
        jobs.view.clear_all()

    def _result(self, version: str) -> probe_result.ProbeResult:
        result = probe_result.success({"version": version}, "http")
        result.generation = jobs.next_generation()
        return result

    def test_clear_all_keeps_a_captured_view_receiving_writes(self):
        """A sweep captures its view once, at start (see sweep_devices).

        `clear_all` used to rebuild the registry, so a sweep racing a
        project switch kept writing into an orphan nothing would ever read
        again — the scan finished green and its results silently vanished.
        The views must be emptied IN PLACE, the objects kept.
        """
        view = jobs.view_for(4)
        view.write("d1", self._result("0.9"))

        jobs.view.clear_all()

        self.assertIs(jobs.view_for(4), view,
                      "the registry must hand out the same object")
        self.assertIsNone(view.get("d1"), "results must still be dropped")
        # The captured reference is still the live one: what the "sweep"
        # writes now is what the next reader sees.
        view.write("d1", self._result("1.0"))
        self.assertEqual(jobs.view_for(4).get("d1").fields["version"], "1.0")

    def test_clearing_undates_the_view(self):
        """`lastScan` feeds the staleness banner; an emptied view must not
        claim it was verified recently."""
        view = jobs.view_for(4)
        view.last_scan = 1234.5
        jobs.view.clear_all()
        self.assertIsNone(view.last_scan)

    def test_a_write_from_before_the_clear_is_refused(self):
        """The other half of keeping the object alive across a project
        switch: a sweep CANCELLED for the switch still finishes its
        in-flight device, and without a fence that one result — the OLD
        project's device, under an id the NEW project reuses — landed in
        the fresh view as a green row. The sweep captures `view.epoch`
        with the view (jobs/sweep.py); a `clear()` in between bumps it and
        the late write becomes a refusal instead."""
        view = jobs.view_for(4)
        epoch = view.epoch
        self.assertTrue(view.write("d1", self._result("0.9"), epoch=epoch))

        jobs.view.clear_all()

        self.assertFalse(view.write("d1", self._result("1.0"), epoch=epoch),
                         "a stale-epoch write must be dropped")
        self.assertIsNone(view.get("d1"))
        # A writer born after the clear is the new project's own.
        self.assertTrue(view.write("d1", self._result("1.1"),
                                   epoch=view.epoch))

    def test_a_cancelled_sweep_does_not_stamp_last_scan(self):
        """A scan cancelled before reading anything used to stamp
        `last_scan` on its way out — and `lastScan` is what the checklist
        staleness banner trusts, so stale data looked freshly verified."""
        job = jobs.Job("scan", "Cancelled scan", 6)
        job.cancel.set()
        reads = []
        jobs.sweep_devices(job, [SimpleNamespace(id="d1")],
                           lambda device: reads.append(device))
        self.assertIsNone(jobs.view_for(6).last_scan)
        self.assertEqual(reads, [], "a cancelled sweep reads nothing")

    def test_a_completed_sweep_stamps_last_scan(self):
        """The counterpart: a sweep that ran IS the verification."""
        job = jobs.Job("scan", "Full scan", 6)
        jobs.sweep_devices(job, [SimpleNamespace(id="d1")],
                           lambda device: self._result("1.0"))
        self.assertIsNotNone(jobs.view_for(6).last_scan)


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
        # ...and NOT the bare exit code, which is the sentence this class
        # exists to keep out of a run that mostly worked. It used to be
        # asserted here by its Turkish wording, from before the codebase was
        # English; that string could no longer appear whatever the code did.
        self.assertNotIn("exited with code", text)

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
