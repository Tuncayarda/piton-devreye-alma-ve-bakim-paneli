// The ADB screen's pure logic: which addresses an operation will touch.
//
// THE PAIRS ARE THE POINT OF THE SCREEN (see views/adb/state.js
// operationTargets): an operation is not "this bundle on those devices" but
// a list of (device, bundle) pairs built from what the search FOUND, so no
// worker ever connects to a display to be told there is no such package.
// The functions asserted here decide what a restart/stop/uninstall run
// actually reaches — and, like the switch screen's, they had no test.
//
// The device list lives in the real store (`adbState` is one of its keys),
// so these tests drive it through patch() exactly as the screen does.
import assert from "node:assert/strict";

import {
  local,
  operationTargets,
  pruneSelection,
  running,
  selectAll,
  selectedIps,
  toggle,
  togglePackage,
  untouchedIps,
} from "../../static/js/views/adb/state.js";
import { patch } from "../../static/js/core/store.js";

const DEVICES = [
  { ip: "10.1.1.44", label: "saloon" },
  { ip: "10.1.1.45", label: "vestibule" },
  { ip: "10.1.1.46", label: "bench" },
];

function reset({ devices = DEVICES, runner = null } = {}) {
  patch({ adbState: { devices, runner } });
  local.selected.clear();
  local.packages.clear();
  local.found = null;
}

Deno.test("toggle and select-all drive the target set", () => {
  reset();
  toggle("10.1.1.44");
  toggle("10.1.1.46");
  assert.deepEqual(selectedIps(), ["10.1.1.44", "10.1.1.46"]);
  toggle("10.1.1.44");
  assert.deepEqual(selectedIps(), ["10.1.1.46"]);
  selectAll(true);
  assert.equal(selectedIps().length, DEVICES.length);
  selectAll(false);
  assert.deepEqual(selectedIps(), []);
});

Deno.test("a device removed from the list stops being a target at once", () => {
  // Two layers on purpose: selectedIps() filters on read (so a stale tick
  // can never reach an operation even before anyone pruned), and
  // pruneSelection() cleans the set itself after the list changes.
  reset();
  selectAll(true);
  patch({ adbState: { devices: DEVICES.slice(0, 2), runner: null } });
  assert.deepEqual(selectedIps(), ["10.1.1.44", "10.1.1.45"],
    "the read already excludes the gone device");
  assert.equal(local.selected.size, 3, "…while the set still remembers it");
  pruneSelection();
  assert.equal(local.selected.size, 2, "until it is pruned for good");
});

Deno.test("an operation touches only (device, bundle) pairs that exist", () => {
  reset();
  selectAll(true);
  toggle("10.1.1.46");                       // deselect the bench
  local.found = {
    packages: [
      { name: "com.acme.pis", present: ["10.1.1.44", "10.1.1.46"] },
      { name: "com.acme.cctv", present: ["10.1.1.45"] },
      { name: "com.acme.idle", present: ["10.1.1.44"] },
    ],
  };
  togglePackage("com.acme.pis");
  togglePackage("com.acme.cctv");
  assert.deepEqual(operationTargets(), [
    // .46 carries the bundle but is not selected; .44 is selected but does
    // not carry cctv — neither produces a pair, and no worker dials either.
    { ip: "10.1.1.44", package: "com.acme.pis" },
    { ip: "10.1.1.45", package: "com.acme.cctv" },
  ]);
});

Deno.test("choosing a bundle twice unchooses it", () => {
  reset();
  togglePackage("com.acme.pis");
  assert.ok(local.packages.has("com.acme.pis"));
  togglePackage("com.acme.pis");
  assert.equal(local.packages.size, 0);
});

Deno.test("before any search there are no pairs at all", () => {
  reset();
  selectAll(true);
  assert.deepEqual(operationTargets(), [],
    "a selection with nothing found yet must not invent targets");
});

Deno.test("devices no chosen bundle is on are named, not dropped", () => {
  // The operator picked those devices deliberately; "nothing happened on
  // 10.1.1.46" is a question they would otherwise have to ask.
  reset();
  selectAll(true);
  local.found = {
    packages: [{ name: "com.acme.pis", present: ["10.1.1.44"] }],
  };
  togglePackage("com.acme.pis");
  assert.deepEqual(untouchedIps(), ["10.1.1.45", "10.1.1.46"]);
});

Deno.test("running() reads the runner and survives its absence", () => {
  reset({ runner: { running: true, generation: 3 } });
  assert.equal(running(), true);
  reset({ runner: { running: false, generation: 4 } });
  assert.equal(running(), false);
  reset({ runner: null });
  assert.equal(running(), false);
  patch({ adbState: null });
  assert.equal(running(), false, "the screen before its first read is idle");
});
