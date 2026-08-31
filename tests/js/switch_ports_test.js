// The switch screen's pure logic: the reading order of the ports, the
// compact range the selection bar shows, the selection rules wired onto
// core/selection.js, and the dot that must agree with the faceplate.
//
// These are the functions the screen's writes aim at — the right-click menu
// applies to `local.selected`, and a selection model that drifted would aim
// a PoE write at the wrong ports — yet none of them had a test: the two
// screen families that write to hardware were the two with zero coverage.
// Pure-module tests in the house style: no DOM, state driven through the
// exported `local` bag.
import assert from "node:assert/strict";

import {
  clearSelection,
  clickPort,
  compactRange,
  local,
  orderedPortIds,
  poePorts,
  portById,
  pruneSelection,
  selectAllPorts,
  uplinkPorts,
} from "../../static/js/views/switch/state.js";
import { dotState } from "../../static/js/views/switch/ports.js";

// A small switch: four PoE ports and two uplinks, deliberately interleaved
// so the reading order below is something the code has to WORK OUT, not the
// array order it was handed.
const PORTS = [
  { id: 1, supportsPoe: true },
  { id: 2, supportsPoe: true },
  { id: 25, supportsPoe: false },
  { id: 3, supportsPoe: true },
  { id: 4, supportsPoe: true },
  { id: 26, supportsPoe: false },
];

function reset() {
  local.ports = [...PORTS];
  clearSelection();
}

// ── the order the operator reads ────────────────────────────────────────
Deno.test("ports are ordered as the tables draw them: PoE block, then uplinks", () => {
  reset();
  // This order is what shift-click ranges run along — it must match the two
  // tables on screen, or a drag from 2 to 4 would silently include port 25.
  assert.deepEqual(orderedPortIds(), [1, 2, 3, 4, 25, 26]);
  assert.deepEqual(poePorts().map((p) => p.id), [1, 2, 3, 4]);
  assert.deepEqual(uplinkPorts().map((p) => p.id), [25, 26]);
});

Deno.test("portById answers for a string id the DOM handed over", () => {
  reset();
  // Ids travel through dataset attributes, so they arrive as text.
  assert.equal(portById("25").id, 25);
  assert.equal(portById(3).id, 3);
  assert.equal(portById("99"), null);
});

// ── the compact range ───────────────────────────────────────────────────
Deno.test("a selection reads as ranges, not as twenty numbers", () => {
  assert.equal(compactRange([1, 2, 3, 4, 9, 20, 21, 22, 23, 24]),
    "1–4, 9, 20–24");
});

Deno.test("the range sorts first, so click order does not show", () => {
  assert.equal(compactRange([4, 2, 3]), "2–4");
  assert.equal(compactRange(new Set([26, 25])), "25–26");
});

Deno.test("singletons and the empty selection stay plain", () => {
  assert.equal(compactRange([7]), "7");
  assert.equal(compactRange([]), "");
});

// ── the selection rules on this screen's order ──────────────────────────
Deno.test("a plain click replaces the selection", () => {
  reset();
  clickPort(2, {});
  clickPort(4, {});
  assert.deepEqual([...local.selected], [4]);
  assert.equal(local.anchor, 4);
});

Deno.test("a shift range runs along the drawn order, uplinks included", () => {
  reset();
  clickPort(3, {});
  clickPort(26, { shiftKey: true });
  // 3 → 4 → 25 → 26: the range crosses the table boundary in reading
  // order, exactly as the operator sees the two tables stacked.
  assert.deepEqual([...local.selected].sort((a, b) => a - b), [3, 4, 25, 26]);
});

Deno.test("select-all takes every port on the open switch", () => {
  reset();
  selectAllPorts();
  assert.equal(local.selected.size, PORTS.length);
});

Deno.test("a port that left the switch cannot stay selected", () => {
  // It would be an invisible target for the next thing the operator does to
  // the selection.
  reset();
  selectAllPorts();
  local.ports = PORTS.filter((p) => p.id !== 26);
  pruneSelection();
  assert.deepEqual([...local.selected].includes(26), false);
  assert.equal(local.selected.size, PORTS.length - 1);
});

// ── the dot beside the word ─────────────────────────────────────────────
Deno.test("the dot asks the faceplate's questions in the faceplate's order", () => {
  // Same questions, same order as front_panel.js:liveClass — the two are
  // read side by side, and a grey connector above a row saying "Linked"
  // is the panel arguing with itself.
  assert.equal(dotState({ enabled: false, powerWatts: 5, linkState: "up" }),
    "failed", "disabled wins over everything");
  assert.equal(dotState({ enabled: true, powerWatts: 3.4, linkState: "up" }),
    "ok", "drawing power is the strongest sign of life");
  assert.equal(dotState({ enabled: true, powerWatts: 0, linkState: "up" }),
    "link", "linked but unpowered — an uplink, or a device on its own supply");
  assert.equal(dotState({ enabled: true, powerWatts: 0, linkState: "down" }),
    "unknown");
});

Deno.test("the wattage is read as a number, however it arrived", () => {
  // The switch reports text; "0.0" must not read as powered.
  assert.equal(dotState({ enabled: true, powerWatts: "0.0", linkState: "up" }),
    "link");
  assert.equal(dotState({ enabled: true, powerWatts: "4.2", linkState: "up" }),
    "ok");
});
