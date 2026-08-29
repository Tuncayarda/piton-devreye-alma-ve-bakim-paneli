// The three click rules two screens share. They had no test while they lived
// inside the switch screen, and the device list now depends on them too — a
// change that quietly broke shift-click would break both at once.

import assert from "node:assert/strict";

import { clickSelect, pruneSelection } from "../../static/js/core/selection.js";

const ORDER = [1, 2, 3, 4, 5, 6];
const plain = {};
const shift = { shiftKey: true };
// Ctrl and Cmd both, so the assertions read the same on either platform.
const modifier = { ctrlKey: true, metaKey: true };

const pick = (id, event, selected = [], anchor = null) =>
  clickSelect({ id, event, order: ORDER, selected: new Set(selected), anchor });

const ids = (result) => [...result.selected].sort((a, b) => a - b);

Deno.test("a plain click selects just that row", () => {
  const result = pick(3, plain, [1, 2]);
  assert.deepEqual(ids(result), [3]);
  assert.equal(result.anchor, 3);
});

// The undo that costs no button: a stray click is taken back by repeating it.
Deno.test("clicking the only selected row clears it", () => {
  const result = pick(3, plain, [3], 3);
  assert.deepEqual(ids(result), []);
  assert.equal(result.anchor, null);
});

Deno.test("clicking one of several selected rows keeps only that one", () => {
  assert.deepEqual(ids(pick(3, plain, [1, 3, 5])), [3]);
});

Deno.test("the modifier adds and removes without disturbing the rest", () => {
  assert.deepEqual(ids(pick(4, modifier, [1, 2])), [1, 2, 4]);
  assert.deepEqual(ids(pick(2, modifier, [1, 2, 4])), [1, 4]);
});

Deno.test("shift takes the range between the anchor and the click", () => {
  assert.deepEqual(ids(pick(5, shift, [2], 2)), [2, 3, 4, 5]);
});

// Backwards is the same range. Selecting downwards only would make the
// direction of the drag part of the meaning, which it is not.
Deno.test("a backwards shift range is the same range", () => {
  assert.deepEqual(ids(pick(2, shift, [5], 5)), [2, 3, 4, 5]);
});

Deno.test("a plain shift range replaces the selection", () => {
  assert.deepEqual(ids(pick(3, shift, [2, 6], 2)), [2, 3]);
});

Deno.test("shift with the modifier adds the range to the selection", () => {
  const result = pick(3, { shiftKey: true, ...modifier }, [2, 6], 2);
  assert.deepEqual(ids(result), [2, 3, 6]);
});

// The anchor survives a range so the operator can widen it by shift-clicking
// again; a moving anchor would walk the range away from where it started.
Deno.test("a shift range leaves the anchor where it was", () => {
  assert.equal(pick(5, shift, [2], 2).anchor, 2);
});

Deno.test("shift with no anchor behaves like a plain click", () => {
  const result = pick(4, shift, [1, 2], null);
  assert.deepEqual(ids(result), [4]);
  assert.equal(result.anchor, 4);
});

// The list filtered, or the switch lost a port; the anchor is a number that
// is no longer on screen and a range from it would mean nothing.
Deno.test("shift from an anchor that left the list behaves like a plain click", () => {
  assert.deepEqual(ids(pick(4, shift, [1], 99)), [4]);
});

Deno.test("the caller's set is never mutated", () => {
  const before = new Set([1, 2]);
  clickSelect({ id: 5, event: plain, order: ORDER, selected: before });
  assert.deepEqual([...before], [1, 2]);
});

Deno.test("pruning drops what is no longer on screen", () => {
  const kept = pruneSelection(new Set([1, 9, 3]), ORDER);
  assert.deepEqual([...kept].sort((a, b) => a - b), [1, 3]);
});
