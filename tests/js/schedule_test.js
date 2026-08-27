import assert from "node:assert/strict";

import {
  lightRoundAllowed,
  scanRoundAllowed,
  writingRunInProgress,
} from "../../static/js/core/schedule.js";

function running(overrides = {}) {
  return {
    meta: { project: "YATAKLI" }, autoRefresh: true,
    scanRunning: false, jobs: [],
    ...overrides,
  };
}

// ── the reason this module exists ──────────────────────────────────────
// A Compartment LCD is read over adb. A round arriving mid-session takes the
// connection out from under whoever is working on that panel, so the operator
// has to be able to stop the rounds — BOTH of them. The light round is the
// one that matters most here: it runs every two seconds, against exactly the
// devices that answered, which is exactly the panel being worked on.
Deno.test("pausing stops both rounds", () => {
  const paused = running({ autoRefresh: false });
  assert.equal(scanRoundAllowed(paused), false);
  assert.equal(lightRoundAllowed(paused), false);
});

Deno.test("resuming needs nothing else to be true", () => {
  assert.equal(scanRoundAllowed(running()), true);
  assert.equal(lightRoundAllowed(running()), true);
});

Deno.test("a state from before the pause control does not read as paused", () => {
  const older = { meta: { project: "YATAKLI" }, scanRunning: false,
                  jobs: [] };
  assert.equal(scanRoundAllowed(older), true);
  assert.equal(lightRoundAllowed(older), true);
});

// ── the obstacles that were already there ──────────────────────────────
// No round before the project metadata has arrived. There is no role screen
// to wait behind any more — the panel opens straight onto the application —
// so what the rounds wait for is the first /api/project reply, which is what
// tells them which devices exist at all.
Deno.test("no round before the project metadata has arrived", () => {
  const empty = running({ meta: null });
  assert.equal(scanRoundAllowed(empty), false);
  assert.equal(lightRoundAllowed(empty), false);
});

Deno.test("neither round runs on top of a scan", () => {
  const scanning = running({ scanRunning: true });
  assert.equal(scanRoundAllowed(scanning), false);
  assert.equal(lightRoundAllowed(scanning), false);
});

// A run that WRITES to devices holds both back: the device is rebooting or
// its PoE port is off, and an interleaved read would record that as truth.
Deno.test("a writing run holds both rounds back", () => {
  const writing = running({ jobs: [{ kind: "firmware", state: "running" }] });
  assert.equal(scanRoundAllowed(writing), false);
  assert.equal(lightRoundAllowed(writing), false);
  assert.equal(writingRunInProgress(writing.jobs), true);
});

// Queued counts too — the scan would otherwise slip in just before the run.
Deno.test("a queued writing run counts as in progress", () => {
  assert.equal(writingRunInProgress([{ kind: "ip", state: "queued" }]), true);
  assert.equal(writingRunInProgress([{ kind: "ip", state: "done" }]), false);
  assert.equal(
    writingRunInProgress([{ kind: "scan", state: "running" }]), false);
  assert.equal(writingRunInProgress(undefined), false);
});

// The two rounds differ on a READING job: discovery is queued behind the
// single worker and is safe to start, the light round reads on the request's
// own thread and would collide.
Deno.test("the two rounds differ on a reading job", () => {
  const reading = running({ jobs: [{ kind: "scan", state: "running" }] });
  assert.equal(scanRoundAllowed(reading), true);
  assert.equal(lightRoundAllowed(reading), false);
});
