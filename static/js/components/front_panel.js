// The switch faceplate — ONE drawing, used by two screens.
//
// The IP assignment screen and the Switch screen both show the front of the
// same SICOM3028GPT, and for a while they each drew their own. That is the
// UI form of the rule in `panel/switch/__init__.py`: a second implementation
// of the same thing drifts from the first, and here the drift is visible —
// two panels showing the same switch with the ports in different places is
// worse than either panel alone, because now the operator has to work out
// which one to believe.
//
// WHAT IS SHARED IS WHAT IS ACTUALLY THE SAME: the connector graphic, and the
// arithmetic that puts port 7 in the right hole. What is NOT shared is what
// the two screens genuinely disagree about — the IP screen colours ports by
// their role in an assignment run and takes its data from DeviceMap; the
// Switch screen colours them by live PoE state and takes its data from the
// switch. Forcing one port object on both would have meant inventing a
// lowest common denominator that neither screen actually wants.
//
// So each screen passes a `cell(number, isUplink)` that returns its own
// button, and gets back the physical layout.

import { el } from '../core/dom.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

// WHERE THE PINS GO. A PoE port is an M12 D-coded socket — four contacts on
// one ring. An uplink is M12 X-CODED: eight contacts, and an X marked on the
// face. Both rings start at the top and run clockwise.
export function pinRing(count, radius) {
  return Array.from({ length: count }, (_, i) => {
    const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
    return [20 + radius * Math.cos(angle), 20 + radius * Math.sin(angle)];
  });
}

// WHERE THE X GOES, and this is the whole reason it is computed rather than
// written out as a path.
//
// It used to be the literal `M13 13 L27 27 M27 13 L13 27` — a cross on the
// diagonals. Eight pins spaced 45° apart starting at the top sit ON those
// diagonals, so two arms of the cross ran straight down the middle of four
// contacts and the connector read as a scribble.
//
// The gaps between the contacts are at 22.5° + 45°k, and 22.5 + 90k stays in
// that set for every k — so ONE perpendicular cross, turned by half a pin
// spacing, puts all four of its arms in gaps. Nothing is drawn over a pin.
export const CROSS_OFFSET = Math.PI / 8;          // half of the 45° spacing

export function crossArms(reach, offset = CROSS_OFFSET) {
  return [0, 1].map((quarter) => {
    const angle = offset + quarter * (Math.PI / 2);
    const dx = reach * Math.cos(angle);
    const dy = reach * Math.sin(angle);
    return [[20 - dx, 20 - dy], [20 + dx, 20 + dy]];
  });
}

function crossPath(reach) {
  return crossArms(reach)
    .map(([[x1, y1], [x2, y2]]) =>
      `M${x1.toFixed(2)} ${y1.toFixed(2)} L${x2.toFixed(2)} ${y2.toFixed(2)}`)
    .join(' ');
}

// The connector. Class names only — every colour is CSS (see switch.css), so
// a state change is a class toggle rather than a redraw.
export function connectorSvg(poe) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 40 40');
  svg.setAttribute('aria-hidden', 'true');
  const add = (tag, attributes) => {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attributes)) {
      node.setAttribute(key, String(value));
    }
    svg.append(node);
  };
  add('circle', { class: 'shell', cx: 20, cy: 20, r: 18.4 });
  add('circle', { class: 'inner', cx: 20, cy: 20, r: 12.2 });
  // The X first, so a contact is never drawn under the line that misses it.
  if (!poe) add('path', { class: 'cross', d: crossPath(9.9) });
  add('rect', { class: 'key', x: 18.6, y: 1.6, width: 2.8, height: 4.2 });
  const pins = poe ? pinRing(4, 6.6) : pinRing(8, 7.2);
  for (const [x, y] of pins) {
    add('circle', {
      class: 'pin', cx: x.toFixed(2), cy: y.toFixed(2), r: poe ? 2.5 : 1.9,
    });
  }
  return svg;
}

function emptyCell(className) {
  return el('div', { class: className || 'pm-empty' });
}

// The faceplate's physical layout.
//
// FOUR ROWS, ALWAYS, and the numbering runs UP each column: 1-2-3-4 in the
// first, 5-6-7-8 in the second. That is how the numbers are silkscreened on
// the metal, so it is how they are drawn — a panel that reads left to right
// like a table would be faster to build and useless for finding a cable.
//
// The uplink column is on the right behind a dashed divider and numbered
// downwards (28 at the top), which is also what the hardware does.
//
// `cell(number, isUplink)` returns the screen's own element for that port, or
// null for a hole that should stay a hole: the panel draws the device's real
// face, empty ports included, or the map stops matching the hardware.
// `size` is the caller's, because the two screens have different room. The IP
// screen stands two faceplates side by side in a column and needs the compact
// one; the Switch screen gives a single switch the full width, and at the
// compact size its faceplate sat in the middle of all that space looking like
// a thumbnail of itself.
// `cell` and `svg` are pixels; `svgMax` marks a size as FLUID and caps how far
// its connector may grow. A fluid faceplate takes the width it is given rather
// than sitting in the middle of it — the switch screen hands one switch the
// whole card and the fixed 74px cells left a wide margin down both sides.
// `cell` becomes the smallest a track may be, so a narrow window scrolls the
// chassis (`.pm-wrap`) instead of crushing the connectors.
// `label` is the size of the port NUMBER, and it belongs beside the connector
// measurements rather than in the stylesheet: the two have to be chosen
// together. The first fluid faceplate grew the connector to 116px and left the
// number at the panel-wide 11px, which put a caption on a diagram — readable
// only if you already knew what it said.
export const PANEL_SIZES = {
  compact: { cell: 52, gap: 12, svg: 36 },
  large: { cell: 76, gap: 18, svg: 56, svgMax: 96, label: 15 },
};

export function portGrid({ poeCount = 24, uplinkCount = 4, cell,
                           size = 'compact' }) {
  const columns = Math.max(1, Math.ceil(poeCount / 4));
  const metrics = PANEL_SIZES[size] || PANEL_SIZES.compact;
  const grid = el('div', {
    class: metrics.svgMax ? 'pm-grid pm-grid-fluid' : 'pm-grid',
    style: `--pm-columns:${columns};--pm-cell:${metrics.cell}px;`
      + `--pm-gap:${metrics.gap}px;--pm-svg:${metrics.svg}px`
      + (metrics.svgMax ? `;--pm-svg-max:${metrics.svgMax}px` : '')
      + (metrics.label ? `;--pm-label:${metrics.label}px` : ''),
  });
  for (let row = 4; row >= 1; row -= 1) {
    for (let column = 0; column < columns; column += 1) {
      const number = row + column * 4;
      grid.append(
        (number <= poeCount && cell(number, false)) || emptyCell());
    }
    grid.append(emptyCell('pm-divider'));
    const uplink = row <= uplinkCount ? poeCount + row : null;
    grid.append((uplink && cell(uplink, true)) || emptyCell());
  }
  return grid;
}
