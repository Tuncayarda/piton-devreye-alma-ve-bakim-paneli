// The ADB screen's own state, and the poll that follows a running operation.
//
// EVERYTHING SELECTED HERE LIVES IN THE BROWSER. The firmware screen keeps
// its selection on the server, and rightly so: it is a selection of DEVICES
// FROM THE PROJECT, it has to survive a screen change, and the run that uses
// it is a job in the queue. None of that is true here. This screen's devices
// are addresses out of a list that belongs to no project (see
// panel/adb/pool.py), and its run is not a job. A server-side selection store
// would be a second place to keep something the screen can hold itself.
//
// The device list itself is the exception and does live on the server: it is
// typed in once and expected to be there tomorrow.

import { state } from '../../core/store.js';

// How often a running operation is asked about. A second is the beat the
// queue panel already uses, and the server's `generation` counter means a
// poll that finds nothing new costs one integer comparison rather than a
// redraw (see panel/adb/runner.py).
export const POLL_INTERVAL = 1000;

export const local = {
  // Which addresses the operations apply to. A Set rather than an array:
  // every use is a membership test while drawing a row.
  selected: new Set(),
  // The add-a-device form. Held here so a refresh round cannot empty a
  // half-typed address.
  newIp: '',
  newLabel: '',
  addError: '',
  // The application. `keyword` is what the operator typed — a
  // COMMA-SEPARATED LIST, because a bench rarely holds one kind of display
  // — `found` the server's answer, and `packages` the bundles they then
  // chose out of it. Several, on purpose: four displays running three
  // customers' applications is the ordinary case, and restarting them one
  // bundle at a time is three searches and three runs for one intention.
  keyword: '',
  found: null,
  searching: false,
  packages: new Set(),
  // The APK to install. Only ever a path the SERVER chose through the
  // operating system's dialog — the browser never sees a real one.
  apk: null,
  pickerOpen: false,
  importing: false,
  // What the autostart button should say for the one device it was asked
  // about: { ip, package, state }.
  autostart: null,
  checkingAutostart: false,
};

export const live = {
  timer: null,
  // The last runner generation drawn. The poll compares against this and
  // redraws only on a real change.
  generation: -1,
};

export function onScreen() {
  return state.view === 'adb';
}

export function selectedIps() {
  const known = new Set(devices().map(entry => entry.ip));
  // A device removed from the list while selected must not go on being an
  // operation target invisibly.
  return [...local.selected].filter(ip => known.has(ip));
}

export function devices() {
  const data = state.adbState;
  return (data && data.devices) || [];
}

export function runner() {
  const data = state.adbState;
  return (data && data.runner) || null;
}

export function running() {
  const current = runner();
  return !!(current && current.running);
}

// Selecting is not a per-row state that survives everything: a device that
// has left the list cannot stay selected.
export function pruneSelection() {
  const known = new Set(devices().map(entry => entry.ip));
  for (const ip of [...local.selected]) {
    if (!known.has(ip)) local.selected.delete(ip);
  }
}

export function toggle(ip) {
  if (local.selected.has(ip)) local.selected.delete(ip);
  else local.selected.add(ip);
}

export function selectAll(on) {
  local.selected.clear();
  if (!on) return;
  for (const entry of devices()) local.selected.add(entry.ip);
}

export function stopPolling() {
  clearTimeout(live.timer);
  live.timer = null;
}

// A chosen bundle is only meaningful while it is one of the answers on
// screen. A new search that does not contain it would leave the operation
// bar pointing at something nobody can see.
export function keepPackages() {
  const answer = local.found;
  if (!answer) return;
  const names = new Set((answer.packages || []).map(entry => entry.name));
  for (const name of [...local.packages]) {
    if (!names.has(name)) local.packages.delete(name);
  }
}

export function togglePackage(name) {
  if (local.packages.has(name)) local.packages.delete(name);
  else local.packages.add(name);
}

// ── what an operation will actually do ──────────────────────────────────
// THE PAIRS, and this is the point of the whole screen. An operation is not
// "this bundle on those devices"; it is a list of (device, bundle) pairs
// built from what the search FOUND. A bundle that is not on a device simply
// produces no pair, so no worker ever connects to that display to be told
// there is no such package — which is both faster and the difference
// between a table of real results and a table half full of noise.
export function operationTargets() {
  const chosen = new Set(selectedIps());
  const answer = local.found;
  if (!answer) return [];
  const pairs = [];
  for (const entry of answer.packages || []) {
    if (!local.packages.has(entry.name)) continue;
    for (const ip of entry.present || []) {
      if (chosen.has(ip)) pairs.push({ ip, package: entry.name });
    }
  }
  return pairs;
}

// Selected devices that no chosen bundle is on. Named rather than dropped
// silently: the operator picked those devices deliberately, and "nothing
// happened on 10.1.1.46" is a question they will otherwise have to ask.
export function untouchedIps() {
  const reached = new Set(operationTargets().map(pair => pair.ip));
  return selectedIps().filter(ip => !reached.has(ip));
}
