import assert from "node:assert/strict";

import {
  adbRunInProgress,
  lightRoundAllowed,
  scanRoundAllowed,
  writingRunInProgress,
} from "../../static/js/core/schedule.js";
import { state } from "../../static/js/core/store.js";

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

// ── the run that is NOT in the queue ───────────────────────────────────
// The ADB screen works outside `jobs` on purpose (panel/adb/runner.py): it
// belongs to no train set, so there is nothing for it to be listed under.
// That means neither `state.jobs` check above can see it, and the rounds have
// to be told separately — which is what `state.adbBusy` is.
//
// It has to hold BOTH rounds, not only the light one. That screen installs
// APKs and writes to a display's system partition, and it reaches the display
// over the same global ADB server the rounds do.
Deno.test("an ADB screen operation holds both rounds back", () => {
  const working = running({ adbBusy: true });
  assert.equal(scanRoundAllowed(working), false);
  assert.equal(lightRoundAllowed(working), false);
  assert.equal(adbRunInProgress(working), true);
});

Deno.test("an idle ADB screen holds nothing back", () => {
  const idle = running({ adbBusy: false });
  assert.equal(scanRoundAllowed(idle), true);
  assert.equal(lightRoundAllowed(idle), true);
  assert.equal(adbRunInProgress(idle), false);
});

// A state written before this flag existed — and the first paint, where the
// store has not been filled in yet — must not read as "busy". Everything
// would stop refreshing and nothing on screen would say why.
Deno.test("an absent flag does not read as busy", () => {
  const older = { meta: { project: "YATAKLI" }, scanRunning: false,
                  jobs: [] };
  assert.equal(adbRunInProgress(older), false);
  assert.equal(scanRoundAllowed(older), true);
  assert.equal(lightRoundAllowed(older), true);
});

// ── what the panel does when it opens ──────────────────────────────────
// PAUSED. Reading a device is not free, and the panel is opened far more
// often to do one thing to one device — write an address, install an APK,
// restart an application on the bench — than to watch a whole train set.
// Starting in the middle of a scan meant that one thing was done against a
// background of traffic nobody asked for.
//
// Asserted here rather than trusted to a literal in the store, because it is
// this module that decides what the flag then stops.
Deno.test("the panel opens with the automatic rounds paused", () => {
  assert.equal(state.autoRefresh, false);
  assert.equal(scanRoundAllowed({ ...state, meta: { project: "YATAKLI" } }),
               false);
  assert.equal(lightRoundAllowed({ ...state, meta: { project: "YATAKLI" } }),
               false);
});
