#!/usr/bin/env python3
"""Progress reporting for the IP assignment run.

The script's line output used to be dumped into the queue as-is: two hundred
rows, 0% from start to finish, and the user could not tell which phase it was
in. These tests pin down what the translation
(`panel.ip_assign.RunProgress`) does with the real script output.

The script now prints a machine-readable event per transition alongside its
prose, and only those events are the contract (see
`field_scripts/intercom_ip_assign.py`). OUTPUT below is a shortened copy of a
real run: prose and events interleaved exactly as the script emits them. Two
details determine all the behaviour:

  · The script defers verification (the default --defer-verify). So when a
    port finishes, no `port_ok` event is emitted; it emits `port_written` and
    the confirmation arrives as `summary_row` at the end.
  · Prose lines never change state. The plan dump at the start of the run
    ("   port 11  ->  10.1.1.10") is prose, and so is every detail line.
"""
from __future__ import annotations

import json
import unittest

from panel import i18n, ip_assign, jobs
from panel.ip_assign import progress as run_progress


PLAN = [
    {"port": 11, "name": "Intercom_1", "targetIp": "10.1.1.10",
     "actionable": True},
    {"port": 12, "name": "Intercom_2", "targetIp": "10.1.1.11",
     "actionable": True},
    {"port": 13, "name": "Intercom_3", "targetIp": "10.1.1.12",
     "actionable": True},
    # A port with no device in the plan: no row may open for it.
    {"port": 14, "name": "—", "targetIp": "—", "actionable": False},
]


def ev(event: str, **fields) -> str:
    """One event line, formatted exactly as the field script writes it."""
    payload = {"event": event}
    payload.update(fields)
    return run_progress.EVENT_PREFIX + json.dumps(
        payload, ensure_ascii=False, sort_keys=True)


# Output from the field run (cut down to three ports). Whitespace included,
# this is what the script prints.
LINES = [
    "[Intercom] 11-13 — assignment starting",
    "[Intercom] Factory address: 10.1.1.12",
    "Set no      : 1",
    "Switch      : 10.1.1.101",
    "Ports       : [11, 12, 13]",
    "   port 11  ->  10.1.1.10      (10011001)",
    "   port 12  ->  10.1.1.11      (10011002)",
    "   port 13  ->  10.1.1.12      (10011003)",
    "Factory IP  : 10.1.1.12   (whoever answers here = unconfigured intercom)",
    "Candidate IPs: 10.1.1.12, 10.1.1.10, 10.1.1.11",
    "ARP         : the cache can be flushed",
    "",
    "Baseline scan (the ports in range are off)...",
    ev("phase", phase="baseline"),
    "    0 device(s) up outside the range",
    ev("pass_started", **{"pass": 1}),

    "",
    "[1/3] Port 11 -> 10.1.1.10 (10011001)",
    ev("port_started", port=11, target="10.1.1.10", index=1, total=3),
    "    closing the ports in range, opening 11...",
    ev("port_step", port=11, step="poe_on",
       detail="closing the ports in range, opening 11"),
    "    port linked (6.6 s) — searching for the device (at most 10 s)...",
    ev("port_step", port=11, step="searching",
       detail="searching for the device"),
    "    (factory IP — unconfigured device)",
    "    device found: 10.1.1.12  [MAC 5c:01:3b:53:2d:ab -> port 11]",
    ev("port_step", port=11, step="device_found",
       detail="device found: 10.1.1.12"),
    "    writing the IP: 10.1.1.12 -> 10.1.1.10",
    ev("port_step", port=11, step="writing_ip",
       detail="writing the IP: 10.1.1.12 -> 10.1.1.10"),
    "    written (reset confirmed), the IP check is deferred to the end",
    ev("port_written", port=11, reason="written", target="10.1.1.10"),

    "",
    "[2/3] Port 12 -> 10.1.1.11 (10011002)",
    ev("port_started", port=12, target="10.1.1.11", index=2, total=3),
    "    closing the ports in range, opening 12...",
    ev("port_step", port=12, step="poe_on",
       detail="closing the ports in range, opening 12"),
    "    [!] The port did not link in 45 s — the cable or the device may need "
    "checking",
    ev("port_note", port=12, level="warning",
       text="the port did not link in 45 s"),
    "    [!] Port 12: the port did not link (no link up)",
    ev("port_failed", port=12, reason="the port did not link (no link up)"),

    "",
    "[3/3] Port 13 -> 10.1.1.12 (10011003)",
    ev("port_started", port=13, target="10.1.1.12", index=3, total=3),
    "    closing the ports in range, opening 13...",
    ev("port_step", port=13, step="poe_on",
       detail="closing the ports in range, opening 13"),
    "    port linked (12.1 s) — searching for the device (at most 10 s)...",
    ev("port_step", port=13, step="searching",
       detail="searching for the device"),
    "    device found: 10.1.1.12  [MAC 5c:01:3b:53:65:ff -> port 13]",
    ev("port_step", port=13, step="device_found",
       detail="device found: 10.1.1.12"),
    "    the IP is already correct",
    ev("port_written", port=13, reason="already_correct", target="10.1.1.12"),

    "",
    "=== Pass 2 — remaining ports: [12]  (waits: boot 30s / verify 60s) ===",
    ev("pass_started", **{"pass": 2}),
    "",
    "[1/1] Port 12 -> 10.1.1.11 (10011002)",
    ev("port_started", port=12, target="10.1.1.11", index=1, total=1),
    "    closing the ports in range, opening 12...",
    ev("port_step", port=12, step="poe_on",
       detail="closing the ports in range, opening 12"),
    "    port linked (5.2 s) — searching for the device (at most 15 s)...",
    ev("port_step", port=12, step="searching",
       detail="searching for the device"),
    "    device found: 10.1.1.12  [MAC 5c:01:3b:53:a4:73 -> port 12]",
    ev("port_step", port=12, step="device_found",
       detail="device found: 10.1.1.12"),
    "    writing the IP: 10.1.1.12 -> 10.1.1.11",
    ev("port_step", port=12, step="writing_ip",
       detail="writing the IP: 10.1.1.12 -> 10.1.1.11"),
    "    written (reset confirmed), the IP check is deferred to the end",
    ev("port_written", port=12, reason="written", target="10.1.1.11"),

    "",
    "Reopening every port in range: [11, 12, 13]",
    ev("phase", phase="restore"),
    "",
    "Final verification (waiting up to 15 s for every device to come up)...",
    ev("phase", phase="verify"),
    "",
    " port  target IP      state",
    "  --------------------------------------------",
    "   11  10.1.1.10      OK",
    ev("summary_row", port=11, target="10.1.1.10", status="ok", reason=""),
    "   12  10.1.1.11      OK",
    ev("summary_row", port=12, target="10.1.1.11", status="ok", reason=""),
    "   13  10.1.1.12      MISSING — no answer",
    ev("summary_row", port=13, target="10.1.1.12", status="missing",
       reason="no answer"),
]

PROSE = [line for line in LINES
         if not line.startswith(run_progress.EVENT_PREFIX)]


# The assertions below are written against the English wording.
i18n.use("en", persist=False)


def _build():
    job = jobs.Job("ip", "IP assignment · Test_SW", 1)
    return job, ip_assign.RunProgress(job, PLAN)


def _rows(job):
    return {row["deviceId"]: row for row in job.rows()}


def _play(progress, lines):
    for line in lines:
        progress.line(line)


def _until(marker: str) -> list[str]:
    """The output up to and including the given line."""
    return LINES[:LINES.index(marker) + 1]


class ProgressTranslation(unittest.TestCase):

    def test_one_row_per_target_port(self):
        """The row count comes from the PORT count, not the output lines."""
        job, _ = _build()
        rows = _rows(job)
        self.assertEqual(sorted(rows), ["p11", "p12", "p13"])
        self.assertNotIn("p14", rows)        # no device in the plan
        self.assertEqual(job.counts()["total"], 3)
        self.assertEqual(job.progress(), 0.0)

    def test_the_plan_dump_does_not_start_ports(self):
        """This was the real fault: the plan dump at the start of the run.

        The script prints the whole plan up front as
        "   port 11  ->  10.1.1.10". Matching that prose showed twelve ports
        "running" in the run's first second. Only a `port_started` event
        starts a port now.
        """
        job, progress = _build()
        _play(progress, _until("    0 device(s) up outside the range"))
        rows = _rows(job)
        self.assertEqual([row["state"] for row in rows.values()],
                         ["queued"] * 3)
        self.assertEqual(job.counts()["pending"], 3)

    def test_prose_alone_never_changes_state(self):
        """Every line of the run, with the events stripped out, is inert."""
        job, progress = _build()
        _play(progress, PROSE)
        rows = _rows(job)
        self.assertEqual([row["state"] for row in rows.values()],
                         ["queued"] * 3)
        self.assertEqual(job.progress(), 0.0)

    def test_only_one_port_runs_at_a_time(self):
        """The run processes ports in order; the screen must show that."""
        job, progress = _build()
        for line in LINES:
            progress.line(line)
            running = [row for row in _rows(job).values()
                       if row["state"] == "running"]
            self.assertLessEqual(len(running), 1, line)

    def test_a_port_closes_within_the_run(self):
        """`port_written` is a port's finish marker.

        Because the script defers verification, no `port_ok` event arrives. A
        counter waiting only for that closed no port at all throughout the run.
        """
        job, progress = _build()
        _play(progress, _until(
            ev("port_written", port=11, reason="written",
               target="10.1.1.10")))
        self.assertEqual(_rows(job)["p11"]["state"], run_progress.WRITTEN)

    def test_an_already_correct_ip_closes_the_port(self):
        job, progress = _build()
        _play(progress, _until(
            ev("port_written", port=13, reason="already_correct",
               target="10.1.1.12")))
        self.assertEqual(_rows(job)["p13"]["state"], run_progress.WRITTEN)
        self.assertIn("already correct", _rows(job)["p13"]["note"])

    def test_the_final_table_has_the_last_word(self):
        """A port that failed in one pass may be finished in the next; the
        deferred verification can either confirm or refute "written"."""
        job, progress = _build()
        _play(progress, LINES)
        rows = _rows(job)
        self.assertEqual(rows["p11"]["state"], "done")
        self.assertEqual(rows["p12"]["state"], "done")   # fixed in pass 2
        self.assertEqual(rows["p13"]["state"], "failed")  # written but absent
        self.assertIn("no answer", rows["p13"]["note"])

        counts = job.counts()
        self.assertEqual(
            (counts["total"], counts["ok"], counts["failed"]), (3, 2, 1))

    def test_a_device_not_found_falls_to_failed(self):
        job, progress = _build()
        _play(progress, [
            ev("port_started", port=11, target="10.1.1.10", index=1, total=3),
            "    closing the ports in range, opening 11...",
            ev("port_failed", port=11, reason="device not found"),
        ])
        row = _rows(job)["p11"]
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["note"], "device not found")
        self.assertEqual(progress.failure_count, 1)

    def test_a_second_count_is_not_mistaken_for_a_port_number(self):
        """`The port did not link in 45 s` — that is 45 seconds, not a port.

        Prose can never open a row now, so the whole class of mistake is gone.
        """
        job, progress = _build()
        progress.line("    [!] The port did not link in 45 s — the cable")
        self.assertNotIn("p45", _rows(job))
        self.assertEqual(job.counts()["total"], 3)

    def test_detail_lines_do_not_open_a_new_row(self):
        """The script's step events become the running port's NOTE."""
        job, progress = _build()
        _play(progress, _until(
            ev("port_step", port=11, step="writing_ip",
               detail="writing the IP: 10.1.1.12 -> 10.1.1.10")))
        rows = _rows(job)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows["p11"]["state"], "running")
        self.assertIn("writing the IP", rows["p11"]["note"])

    def test_the_prose_goes_to_the_log_and_the_events_do_not(self):
        """The lines were taken out of the queue but not lost.

        Event lines are machine chatter; putting them in the operator's log
        would only duplicate the sentence printed right next to them.
        """
        collected = []
        job = jobs.Job("ip", "IP assignment · Test_SW", 1)
        progress = ip_assign.RunProgress(job, PLAN, log=collected.append)
        _play(progress, LINES)
        self.assertEqual(len(collected), len(PROSE))
        self.assertIn("   11  10.1.1.10      OK", collected)
        self.assertFalse([line for line in collected
                          if line.startswith(run_progress.EVENT_PREFIX)])

    def test_the_ok_event_also_works_in_a_verified_run(self):
        """Run with --no-defer-verify, the finish marker is `port_ok`."""
        job, progress = _build()
        _play(progress, [
            ev("port_started", port=11, target="10.1.1.10", index=1, total=3),
            ev("port_step", port=11, step="verifying",
               detail="verification: waiting for 10.1.1.10"),
            ev("port_ok", port=11, target="10.1.1.10"),
        ])
        self.assertEqual(_rows(job)["p11"]["state"], "done")

    def test_a_broken_event_line_is_treated_as_prose(self):
        """One garbled line must not take the run down with it."""
        job, progress = _build()
        progress.line(run_progress.EVENT_PREFIX + "{not json")
        progress.line(run_progress.EVENT_PREFIX + '{"no": "event key"}')
        self.assertEqual([row["state"] for row in _rows(job).values()],
                         ["queued"] * 3)


class Percentage(unittest.TestCase):
    """The percentage must advance throughout the run.

    The old calculation was "finished ports / total ports". Because ports
    close in the summary table at the end rather than mid-run, the bar sat at
    0% and jumped to 100% in the last second. The new calculation is
    phase-weighted (PHASES).
    """

    def test_the_phase_shares_add_up_to_one(self):
        self.assertAlmostEqual(
            sum(share for _name, _text, share in run_progress.PHASES), 1.0)

    def test_it_never_goes_back_and_spreads_out(self):
        job, progress = _build()
        seen = []
        for line in LINES:
            progress.line(line)
            seen.append(job.progress())

        self.assertEqual(seen, sorted(seen))       # never goes backwards
        # The bar moves throughout the run, not in three or four jumps.
        self.assertGreater(len(set(seen)), 10)

    def test_it_advances_before_the_first_port_finishes(self):
        """One port can take a minute; the bar moves inside a port too."""
        job, progress = _build()
        _play(progress, _until("    0 device(s) up outside the range"))
        baseline = job.progress()
        self.assertGreater(baseline, 0.0)

        _play(progress, [
            ev("port_started", port=11, target="10.1.1.10", index=1, total=3),
            ev("port_step", port=11, step="poe_on", detail="opening the port"),
        ])
        opened = job.progress()
        progress.line(ev("port_step", port=11, step="searching",
                         detail="searching for the device"))
        searching = job.progress()
        progress.line(ev("port_step", port=11, step="device_found",
                         detail="device found: 10.1.1.12"))
        found = job.progress()

        self.assertLess(baseline, opened)
        self.assertLess(opened, searching)
        self.assertLess(searching, found)

    def test_the_percentage_jumps_clearly_when_the_first_port_ends(self):
        job, progress = _build()
        _play(progress, _until(
            ev("port_written", port=11, reason="written",
               target="10.1.1.10")))
        # Prepare + baseline + one of three ports: roughly 35%.
        self.assertGreater(job.progress(), 0.30)
        self.assertLess(job.progress(), 0.45)

    def test_most_is_done_when_the_final_verification_begins(self):
        job, progress = _build()
        _play(progress, _until(ev("phase", phase="verify")))
        self.assertGreater(job.progress(), 0.80)
        self.assertLess(job.progress(), 1.0)

    def test_the_percentage_fills_when_the_run_ends(self):
        job, progress = _build()
        _play(progress, LINES)
        progress.finish()
        self.assertEqual(job.progress(), 1.0)

    def test_an_interrupted_run_does_not_show_one_hundred_percent(self):
        """Showing a cancelled run at 100% reads as half the work being done."""
        job, progress = _build()
        _play(progress, _until(
            ev("port_written", port=11, reason="written",
               target="10.1.1.10")))
        progress.finish()
        self.assertLess(job.progress(), 1.0)
        rows = _rows(job)
        # Written but not verified: calling it "done" would be wrong.
        self.assertEqual(rows["p11"]["state"], "warning")
        self.assertEqual(rows["p12"]["state"], "skipped")


class Phase(unittest.TestCase):

    def test_the_phase_text_is_enough_to_follow_the_run(self):
        job, progress = _build()
        self.assertIn("Preparing", job.phase)

        progress.line(ev("phase", phase="baseline"))
        self.assertIn("Baseline scan", job.phase)

        progress.line(
            ev("port_started", port=11, target="10.1.1.10", index=1, total=3))
        progress.line(ev("port_step", port=11, step="searching",
                         detail="searching for the device"))
        self.assertIn("Port 11", job.phase)
        self.assertIn("Searching for the device", job.phase)
        self.assertIn("(0/3)", job.phase)

        progress.line(ev("pass_started", **{"pass": 2}))
        self.assertIn("pass 2", job.phase)

        progress.line(ev("phase", phase="restore"))
        self.assertIn("Reopening", job.phase)

        progress.line(ev("phase", phase="verify"))
        self.assertIn("Final verification", job.phase)

        progress.finish()
        self.assertEqual(job.phase, "")

    def test_the_phase_never_goes_back(self):
        """Pass 2 does not restart the run — never after final verification."""
        job, progress = _build()
        progress.line(ev("phase", phase="verify"))
        before = job.progress()
        progress.line(ev("phase", phase="baseline"))
        self.assertIn("Final verification", job.phase)
        self.assertGreaterEqual(job.progress(), before)

    def test_an_unknown_phase_is_ignored(self):
        job, progress = _build()
        progress.line(ev("phase", phase="teleport"))
        self.assertIn("Preparing", job.phase)


class Steps(unittest.TestCase):
    """The accordion under the row: the port's own history."""

    def _steps(self, job, key):
        return [step["text"] for step in _rows(job)[key]["steps"]]

    def test_port_steps_accumulate(self):
        job, progress = _build()
        _play(progress, _until(
            ev("port_written", port=11, reason="written",
               target="10.1.1.10")))
        steps = self._steps(job, "p11")
        self.assertIn("closing the ports in range, opening 11...", steps)
        self.assertIn(
            "device found: 10.1.1.12  [MAC 5c:01:3b:53:2d:ab -> port 11]",
            steps)
        self.assertIn("writing the IP: 10.1.1.12 -> 10.1.1.10", steps)
        self.assertEqual(steps[-1],
                         "IP written, awaiting the final verification")

    def test_steps_do_not_mix_between_ports(self):
        job, progress = _build()
        _play(progress, LINES)
        for key in ("p11", "p12", "p13"):
            self.assertTrue(self._steps(job, key))
        self.assertNotIn("closing the ports in range, opening 11...",
                         self._steps(job, "p12"))

    def test_the_first_pass_steps_survive_into_the_second(self):
        """This answers "why did the port fail in the first pass?"."""
        job, progress = _build()
        _play(progress, LINES)
        steps = self._steps(job, "p12")
        self.assertIn("the port did not link (no link up)", steps)
        self.assertIn("10.1.1.11 verified", steps)

    def test_a_failed_step_is_marked(self):
        job, progress = _build()
        _play(progress, LINES)
        states = {step["text"]: step["state"]
                  for step in _rows(job)["p12"]["steps"]}
        self.assertEqual(states["the port did not link (no link up)"], "failed")
        self.assertEqual(states["the port did not link in 45 s"], "warning")

    def test_the_step_count_is_capped(self):
        """Steps go to the UI on every poll of an open job."""
        job, _ = _build()
        for i in range(jobs.job.STEP_LIMIT + 20):
            job.add_step("p11", f"step {i}")
        steps = _rows(job)["p11"]["steps"]
        self.assertEqual(len(steps), jobs.job.STEP_LIMIT)
        self.assertEqual(steps[-1]["text"],
                         f"step {jobs.job.STEP_LIMIT + 19}")


if __name__ == "__main__":
    unittest.main()
