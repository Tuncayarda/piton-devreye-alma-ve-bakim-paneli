// The ADB screen.
//
// A bench tool inside the panel, and deliberately the only screen that knows
// nothing about the project. Its devices are addresses somebody typed in
// (panel/adb/pool.py); its work is starting, stopping, installing and
// removing an application on several of them at once. Nothing here reads
// DeviceMap, and no train set applies.
//
// SPLIT INTO SEVERAL FILES FROM THE FIRST LINE, not later. The IP screen was
// one file and reached fourteen hundred lines before anybody could stand to
// divide it. The division is the same one that screen ended up with: state
// and the polling round here, and one file per card.
//
//   state.js       what is selected, what was searched for, the poll's timer
//   fields.js      the one text-box shape — a tag in front, no placeholder
//   pool.js        the address list and the row selection
//   packages.js    the keyword search and the bundle choice
//   operations.js  the three operation cards and their confirmations
//   status.js      the running table and the log of what has finished
//
// WHILE AN OPERATION RUNS THE PANEL'S OWN ROUNDS STOP. Both this screen and
// the light refresh reach a Compartment LCD over the same global ADB server,
// and a refresh landing in the middle of an install takes the transport out
// from under it. The server refuses the round (panel/api/routes/
// session_routes.py) and the browser stops asking for it (core/schedule.js);
// `state.adbBusy` is what carries that fact from one to the other.

import { el, fill } from '../../core/dom.js';
import { api } from '../../core/api.js';
import { state, patch } from '../../core/store.js';
import { showError, showSuccess, notify } from '../../components/toast.js';
import { t } from '../../core/i18n.js';
import {
  POLL_INTERVAL, live, local, onScreen, operationTargets,
  pruneSelection, running, selectAll, selectedIps, stopPolling, toggle,
  togglePackage,
} from './state.js';
import { poolCard } from './pool.js';
import { packagesCard } from './packages.js';
import { applicationCard, installCard, serverCard } from './operations.js';
import { statusCard } from './status.js';

let refreshToken = 0;

// ── talking to the server ───────────────────────────────────────────────
export async function refresh() {
  const token = ++refreshToken;
  try {
    const body = await api.adb();
    if (token !== refreshToken) return;
    apply(body);
  } catch {
    if (token !== refreshToken) return;
    patch({ adbState: null, adbBusy: false });
  }
}

// One place writes the store, so `adbBusy` cannot fall out of step with the
// runner it is derived from. A screen that stopped the refresh rounds and
// then forgot to start them again is a screen that looks frozen.
function apply(body) {
  const current = body && body.runner;
  patch({ adbState: body, adbBusy: !!(current && current.running) });
  pruneSelection();
  live.generation = current ? current.generation : -1;
  schedulePoll();
}

// The runner's state alone, once a second while something is running. The
// device list is not re-read: it cannot have changed, and re-sending it sixty
// times a minute to redraw an identical table is the cost this endpoint
// exists to avoid.
//
// setTimeout AFTER the reply, never setInterval — the house rule, so a slow
// device cannot make requests pile up.
function schedulePoll() {
  stopPolling();
  if (!onScreen() || !running()) return;
  live.timer = setTimeout(pollRound, POLL_INTERVAL);
}

async function pollRound() {
  live.timer = null;
  if (!onScreen()) return;
  let current = null;
  try {
    current = await api.adbState();
  } catch {
    // A dropped poll is not worth a message: the next one is a second away
    // and the table on screen is still the last thing that was true.
    schedulePoll();
    return;
  }
  if (!onScreen()) return;

  const data = state.adbState;
  const moved = !data || !data.runner
    || current.generation !== live.generation;
  live.generation = current.generation;
  if (moved) {
    // Updated in place and re-drawn through `patch`, so the whole screen is
    // not rebuilt for a counter that did not move.
    patch({
      adbState: { ...(data || {}), runner: current },
      adbBusy: !!current.running,
    });
  } else if (state.adbBusy !== !!current.running) {
    patch({ adbBusy: !!current.running });
  }
  if (!current.running) finished(current);
  schedulePoll();
}

// Saying how it went, once, when the run ends. The table stays on screen with
// every row's own result; this is the line for somebody who walked away.
function finished(current) {
  const rows = current.rows || [];
  const failed = rows.filter(row => row.state === 'failed').length;
  const done = rows.filter(row => row.state === 'done').length;
  if (failed) notify(t('adb.finishedWithFailures', { done, failed }));
  else if (done) showSuccess(t('adb.finished', { count: done }));
}

// ── what the cards call ─────────────────────────────────────────────────
const actions = {
  toggle(ip) {
    toggle(ip);
    redraw();
  },

  selectAll(on) {
    selectAll(on);
    redraw();
  },

  async addDevice(ip, label) {
    local.addError = '';
    try {
      const body = await api.adbDevices({ action: 'add', ip, label });
      local.newIp = '';
      local.newLabel = '';
      patchDevices(body);
      // The box can carry a range, so the count is worth saying: "10.1.1.45-47"
      // that adds one because the other two were already in the list is not
      // what the operator thinks they just did.
      if ((body.added || 0) !== 1) {
        showSuccess(t('adb.addressAdded', { count: body.added || 0 }));
      }
    } catch (error) {
      // Beside the field rather than in the toast strip: the mistake is in
      // the box the user is looking at, and the correction happens there.
      local.addError = error.message;
      redraw();
    }
  },

  async removeDevice(ip) {
    local.selected.delete(ip);
    patchDevices(await api.adbDevices({ action: 'remove', ip }));
  },

  async importList() {
    local.importing = true;
    redraw();
    try {
      const body = await api.adbImport();
      if (body.cancelled) return;
      patchDevices(body);
      // Both numbers, always. A file with three good addresses and nine
      // typos imports three, and an operator told only "3 imported" spends
      // the afternoon looking for the other nine.
      showSuccess(t('adb.imported', {
        count: body.imported || 0, skipped: body.skipped || 0,
      }));
    } catch (error) {
      showError(error.message);
    } finally {
      local.importing = false;
      redraw();
    }
  },

  async exportList() {
    local.exporting = true;
    redraw();
    try {
      const body = await api.adbExport();
      // A cancelled save dialog is not a failure and gets no toast: the
      // operator closed the window they opened and knows nothing was
      // written.
      if (body.cancelled) return;
      // The file NAME, not the whole path. The operator has just chosen the
      // folder themselves, so naming it back at them is noise, and a full
      // path on a toast is a line of text nobody reads to the end.
      showSuccess(t('adb.exported', {
        count: body.count || 0, file: body.file,
      }));
    } catch (error) {
      showError(error.message);
    } finally {
      local.exporting = false;
      redraw();
    }
  },

  async search(keyword) {
    local.keyword = keyword;
    local.searching = true;
    redraw();
    try {
      local.found = await api.adbPackages(selectedIps(), keyword);
      // NOTHING IS SELECTED BY THE SEARCH. It used to tick every answer, on
      // the reasoning that the operator had asked for those words — which
      // holds for a search that returns one bundle and not for one that
      // returns six. A display carrying several of them then had all six
      // ticked, and the next operation ran on bundles nobody chose.
      //
      // A keyword is how the list is NARROWED; choosing from it is a
      // separate decision and is made on the list itself.
      local.packages = new Set();
    } catch (error) {
      local.found = null;
      showError(error.message);
    } finally {
      local.searching = false;
      redraw();
    }
  },

  choosePackage(name) {
    togglePackage(name);
    local.autostart = null;             // it was about another selection
    redraw();
  },

  async pickApk() {
    local.pickerOpen = true;
    redraw();
    try {
      // Only the NAME comes back. The path stays on the server, which is
      // also where the install reads it from — see panel/api/routes/
      // adb_routes.py post_apk.
      const body = await api.adbApk();
      if (!body.cancelled) local.apk = { name: body.name };
    } catch (error) {
      showError(error.message);
    } finally {
      local.pickerOpen = false;
      redraw();
    }
  },

  async checkAutostart() {
    const targets = operationTargets();
    if (!targets.length) return;
    const first = targets[0];
    local.checkingAutostart = true;
    redraw();
    try {
      // ONE pair, on purpose: the answer labels a button, and asking twelve
      // displays over ADB to decide what one button says is not a trade
      // worth making.
      const body = await api.adbAutostart([first.ip], first.package);
      local.autostart = { ip: first.ip, package: body.package,
                          state: body.state };
    } catch (error) {
      local.autostart = null;
      showError(error.message);
    } finally {
      local.checkingAutostart = false;
      redraw();
    }
  },

  async autostartFiles(pkg) {
    try {
      const body = await api.adbAutostartFiles(pkg);
      return body.files || [];
    } catch (error) {
      showError(error.message);
      return null;
    }
  },

  // `targets` are (device, bundle) pairs when the operation is about a
  // bundle. Installing an APK is the exception and passes none: the package
  // is inside the file, so the run works on the selected devices.
  async run(operation, parameters, targets = null) {
    try {
      const current = await api.adbRun({
        operation,
        ...(targets ? { targets } : { devices: selectedIps() }),
        ...parameters,
      });
      apply({ ...(state.adbState || {}), runner: current });
    } catch (error) {
      showError(error.message);
    }
  },

  async cancel() {
    try {
      apply({ ...(state.adbState || {}), runner: await api.adbCancel() });
    } catch (error) {
      showError(error.message);
    }
  },
};

function patchDevices(body) {
  const data = state.adbState || {};
  patch({ adbState: { ...data, devices: body.devices || [] } });
  pruneSelection();
  redraw();
}

// The screen is redrawn from the store, so a change that lives only in
// `local` still has to ask for a render. A new object reference is passed so
// the store publishes even when nothing it can see has changed.
function redraw() {
  if (!onScreen()) return;
  patch({ adbState: { ...(state.adbState || {}) } });
}

// ── drawing ─────────────────────────────────────────────────────────────
export function render(root) {
  const busy = running();
  fill(root, [
    el('div', { class: 'page-head' }, [
      el('h2', { text: t('nav.adb') }),
      el('div', { class: 'actions' }, [
        el('button', {
          type: 'button', class: 'btn',
          text: t('adb.reload'), disabled: busy,
          onclick: () => refresh(),
        }),
      ]),
    ]),
    busy
      ? el('p', { class: 'info', role: 'status', text: t('adb.roundsPaused') })
      : null,
    // The order somebody works in: pick the displays, find the application,
    // drive it, put things on it, and — only when the bench itself is the
    // suspect — the daemon on this computer. The status card is last because
    // it is read after a button was pressed, not before.
    poolCard(actions),
    packagesCard(actions),
    applicationCard(actions),
    installCard(actions),
    serverCard(actions),
    statusCard(actions),
  ]);
  // The poll owns its own timer and stops itself when the screen goes; it is
  // not rebuilt on every render (the IP screen's lesson: tearing the timers
  // down each round meant none of them ever elapsed).
  if (busy && !live.timer) schedulePoll();
}

export function stop() {
  stopPolling();
}
