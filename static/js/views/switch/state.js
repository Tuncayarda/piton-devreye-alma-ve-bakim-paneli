// The switch screen's own state: what is selected, and the poll that follows
// a running scan.
//
// SPLIT INTO SEVEN FILES FROM THE FIRST LINE, for the reason written at the
// top of `views/adb/index.js`: the IP screen was one file and reached
// fourteen hundred lines before anyone could face dividing it.
//
// The selection lives in the browser, like the ADB screen's and unlike the
// firmware screen's. It is a selection of PORTS ON ONE SWITCH — it means
// nothing once the operator looks at another switch, it does not have to
// survive a screen change, and the write that uses it happens on the spot
// rather than as a job in the queue. A server-side store would be a second
// place to keep something the screen can hold itself.
//
// NOTHING IS STAGED. A change to a port goes to the switch when it is made,
// which is how the Switch Management Panel this screen replaces has always
// worked. There was briefly a "staged changes + apply" bar here; it put a
// second step in front of the one thing this screen is for, and it meant the
// dropdown could show a value the hardware did not have.
//
// What does NOT live here is the password. It goes from the sign-in dialog
// straight into the API call (see `session.js`); `core/store.js` refuses
// those keys anyway, and this object must not become the way around that.

import { state } from '../../core/store.js';
import { clickSelect, pruneSelection as prune, selectionModifier }
  from '../../core/selection.js';

export { selectionModifier };

// How often a running scan is asked about. The same beat as the queue panel
// and the ADB screen — the answer changes once a scan finishes, not sixty
// times a minute, so anything faster is cost without information.
export const POLL_INTERVAL = 1000;

export const local = {
  // The addresses to sweep, and the mask they are read against — two fields
  // on screen, joined into one expression on the way to the server (see
  // discovery.js). Seeded from the server's default on the first load, then
  // whatever the operator typed.
  range: '',
  prefix: '24',
  // Row credentials being typed. See `typed()` below for why they live here.
  credentials: {},
  scanning: false,
  // Which ports are ticked, and where a shift-click range starts from.
  selected: new Set(),
  anchor: null,
  // The switch being looked at: its identity, its ports, and when they were
  // read. Held here rather than in the store because it is one screen's
  // working copy of one device.
  info: null,
  ports: [],
  loadingPorts: false,
  // The management-address form. Kept across redraws so a poll cannot wipe
  // a half-typed address.
  form: { address: '', prefix: '24', mtu: '1500' },
};

// What is typed into a row's user/password boxes, keyed by address.
//
// NOT IN `core/store.js`, and that is the rule rather than an oversight: the
// store refuses these keys outright, and nothing here is written to disk or
// to browser storage. This is the same place the sign-in dialog's own input
// elements used to hold the value — module memory, for the seconds between
// typing it and sending it — and each entry is dropped the moment the switch
// accepts it (see `index.js:connectSwitch`).
export function typed(ip) {
  if (!local.credentials[ip]) local.credentials[ip] = { user: '', password: '' };
  return local.credentials[ip];
}

export function forgetTyped(ip) {
  delete local.credentials[ip];
}

export const live = { timer: null };

export function onScreen() {
  return state.view === 'switch';
}

export function screen() {
  return state.switchState || null;
}

export function discovered() {
  const body = screen();
  return (body && body.discovered) || [];
}

export function scanning() {
  const body = screen();
  return !!(body && body.scanning);
}

export function poeModes() {
  const body = screen();
  return (body && body.poeModes) || [];
}

export function selectedIp() {
  return state.switchSelected || '';
}

export function current() {
  const ip = selectedIp();
  return discovered().find(entry => entry.ip === ip) || null;
}

// Ports in the order the operator reads them: the PoE block, then uplinks.
export function orderedPortIds() {
  return local.ports.filter(port => port.supportsPoe).map(port => port.id)
    .concat(local.ports.filter(port => !port.supportsPoe).map(p => p.id));
}

export function poePorts() {
  return local.ports.filter(port => port.supportsPoe);
}

export function uplinkPorts() {
  return local.ports.filter(port => !port.supportsPoe);
}

export function portById(id) {
  return local.ports.find(port => port.id === Number(id)) || null;
}

// ── selection ───────────────────────────────────────────────────────────
// Click, ctrl/cmd-click and shift-click, the same three the sibling panel
// had: an operator turning PoE off on ports 5 to 12 should drag once, not
// click eight times. The rules themselves are core/selection.js — the device
// list picks rows the same way and the two must not drift apart.

export function clickPort(id, event) {
  const result = clickSelect({
    id, event, order: orderedPortIds(),
    selected: local.selected, anchor: local.anchor,
  });
  local.selected = result.selected;
  local.anchor = result.anchor;
}

export function clearSelection() {
  local.selected = new Set();
  local.anchor = null;
}

export function selectAllPorts() {
  local.selected = new Set(orderedPortIds());
  local.anchor = null;
}

// A port that is no longer on the switch cannot stay selected — it would be
// an invisible target for the next thing the operator does to the selection.
export function pruneSelection() {
  local.selected = prune(local.selected, orderedPortIds());
}

// A compact "1–4, 9, 20–24" for the selection bar. A list of twenty numbers
// is not something anybody reads.
export function compactRange(ids) {
  const sorted = [...ids].sort((a, b) => a - b);
  const parts = [];
  let start = null;
  let end = null;
  for (const id of sorted) {
    if (start === null) { start = id; end = id; continue; }
    if (id === end + 1) { end = id; continue; }
    parts.push(start === end ? `${start}` : `${start}–${end}`);
    start = id;
    end = id;
  }
  if (start !== null) {
    parts.push(start === end ? `${start}` : `${start}–${end}`);
  }
  return parts.join(', ');
}

// NO SESSION LOG. There was a card here listing what had been done to
// switches since the panel opened — the sibling application had one and wrote
// it to a file. Every line it held was already said twice: as a toast when the
// write returned, and, for a sweep, as a row in the job queue. A third copy
// that scrolled away when the window closed was not worth the space it took
// under the port tables.

export function stopPolling() {
  clearTimeout(live.timer);
  live.timer = null;
}
