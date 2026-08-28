import assert from "node:assert/strict";

import {
  CROSS_OFFSET,
  PANEL_SIZES,
  crossArms,
  pinRing,
} from "../../static/js/components/front_panel.js";

const CENTRE = 20;
const radiusOf = ([x, y]) => Math.hypot(x - CENTRE, y - CENTRE);
const round = (value) => Math.round(value * 100) / 100;

Deno.test("a PoE port is four contacts on one ring", () => {
  const pins = pinRing(4, 6.6);
  assert.equal(pins.length, 4);
  for (const pin of pins) assert.equal(round(radiusOf(pin)), 6.6);
});

// The bug this file exists for. The uplink's X used to be the literal path
// `M13 13 L27 27 M27 13 L13 27` — a cross on the diagonals — while its eight
// contacts sit 45 degrees apart starting at the top, which puts four of them
// ON those diagonals. Two arms ran down the middle of four contacts and the
// connector read as a scribble. Turning the cross by half a pin spacing puts
// every arm in a gap instead.
//
// Measured rather than eyeballed: what follows is the distance from each
// contact's centre to each arm's line. Less than the contact's radius means
// the line has gone through it.
const PIN_RADIUS = 1.9;
const STROKE = 0.45;                 // half of the .9 stroke-width in the CSS

// Distance from a point to the infinite line through a and b.
function distanceToLine([px, py], [[ax, ay], [bx, by]]) {
  const dx = bx - ax;
  const dy = by - ay;
  return Math.abs(dy * px - dx * py + bx * ay - by * ax) / Math.hypot(dx, dy);
}

const closestApproach = (pins, arms) =>
  Math.min(...pins.flatMap((pin) => arms.map((arm) => distanceToLine(pin, arm))));

Deno.test("an uplink is eight contacts on one ring", () => {
  const pins = pinRing(8, 7.2);
  assert.equal(pins.length, 8);
  for (const pin of pins) assert.equal(round(radiusOf(pin)), 7.2);
});

Deno.test("the X passes between the contacts, never through one", () => {
  const arms = crossArms(9.9);
  assert.equal(arms.length, 2);
  const closest = closestApproach(pinRing(8, 7.2), arms);
  // Clear of the contact AND of the width the line is actually stroked at.
  assert.ok(
    closest > PIN_RADIUS + STROKE,
    `the X comes within ${round(closest)} of a contact`,
  );
});

// The cross it replaced, kept as the counter-example: this is the number that
// made the old drawing a scribble, and it is why the offset is not decoration.
Deno.test("the diagonal cross it replaced did go through the contacts", () => {
  const closest = closestApproach(pinRing(8, 7.2), crossArms(9.9, 0));
  assert.ok(closest < PIN_RADIUS, "the diagonals would have missed after all");
});

Deno.test("the X is turned by half a contact spacing", () => {
  assert.equal(round(CROSS_OFFSET), round(Math.PI / 8));
  // Eight contacts is 45 degrees apart. A perpendicular cross has arms at
  // 90-degree steps, and 22.5 + 90k stays at 22.5 modulo 45 — which is why
  // ONE offset puts all four arms in gaps.
  for (let quarter = 0; quarter < 4; quarter += 1) {
    assert.equal(round((22.5 + quarter * 90) % 45), 22.5);
  }
});

Deno.test("the uplink contacts clear the inner ring they sit inside", () => {
  // The `inner` circle is r=12.2; a contact crossing it would sit on the line.
  for (const pin of pinRing(8, 7.2)) {
    assert.ok(radiusOf(pin) + PIN_RADIUS < 12.2, "a contact reaches the ring");
  }
});

Deno.test("the two faceplate sizes are actually different", () => {
  // The Switch screen asks for `large` because it shows one switch across the
  // full width; the IP screen stands two side by side and keeps `compact`.
  assert.ok(PANEL_SIZES.large.cell > PANEL_SIZES.compact.cell);
  assert.ok(PANEL_SIZES.large.svg > PANEL_SIZES.compact.svg);
  // The connector has to fit its cell with room for the number under it.
  for (const [name, size] of Object.entries(PANEL_SIZES)) {
    assert.ok(size.svg < size.cell, `${name}: the connector fills its cell`);
    // A fluid size stretches to the width it is handed; the cap has to leave
    // it somewhere to grow, or marking it fluid changes nothing.
    if (size.svgMax) {
      assert.ok(size.svgMax > size.svg, `${name}: the cap is below the floor`);
      // The number has to hold its own against the connector it labels. At
      // 116px of connector and 11px of text it did not, which is what put a
      // `label` in here at all.
      assert.ok(size.label >= 14, `${name}: the port number is a footnote`);
      assert.ok(size.svgMax < size.cell * 1.5, `${name}: the connector runs
        away from its number`);
    }
  }
});
