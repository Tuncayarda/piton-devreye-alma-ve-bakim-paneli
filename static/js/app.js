// Devreye Alma Paneli — UI start-up and the refresh loops.
//
// Timing rules:
//   · setInterval is never used. Every round is set up with setTimeout AFTER
//     the previous request finished, so a slow device cannot make requests
//     pile up.
//   · Refreshing runs at two speeds:
//       – Discovery (full scan) once a minute. It looks at EVERY address in
//         DeviceMap, so it waits one timeout per unreachable device; that is
//         the expensive one. The "Scan now" button pulls that round forward.
//       – The light refresh every few seconds, ONLY for devices that went
//         green in the last round. It never touches an unreachable device,
//         which is what makes it fast.
//   · Both automatic rounds can be PAUSED (`state.autoRefresh`, the top
//     bar's pause button), and THE PANEL OPENS PAUSED. Reading a device is
//     not free: a Compartment LCD is read over adb, and a round arriving
//     mid-session takes the connection out from under whoever is working on
//     that panel. The panel is opened far more often to do one thing to one
//     device than to watch a whole set, so the rounds are something the
//     operator turns ON when they want to watch (see core/store.js).
//     Pausing stops both rounds, never a job already queued, and never
//     "Scan now" — the operator keeps a way to read on demand. While paused
//     the status text says so, because a screen that quietly stops updating
//     is worse than one that interrupts.
//   · The light refresh does not run while a full scan is in progress.
//   · No scan is started on its own while an IP assignment / configuration /
//     firmware run is in progress; those runs reboot devices. A scan the user
//     asks for enters the queue and runs after the job.
//   · Every reply carries a generation; a late old reply never overwrites a
//     newer one.

import { $, el, fill, preserveScroll } from './core/dom.js';
import { api } from './core/api.js';
import { state, patch, subscribe } from './core/store.js';
import {
  lightRoundAllowed, scanRoundAllowed, writingRunInProgress,
} from './core/schedule.js';
import { t } from './core/i18n.js';
import * as language from './components/language.js';
import * as sidebar from './components/sidebar.js';
import * as queue from './components/queue.js';
import * as locked from './components/locked.js';
import * as detail from './components/detail.js';
import * as dialog from './components/dialog.js';
import { notify, showError, showSuccess } from './components/toast.js';
import { loadFailed, loading } from './components/placeholder.js';
import * as overviewView from './views/overview.js';
import * as devicesView from './views/devices.js';
import * as ipView from './views/ip/index.js';
import * as networkView from './views/network.js';
import * as adbView from './views/adb/index.js';
import * as switchView from './views/switch/index.js';
import * as configView from './views/config.js';
import * as firmwareView from './views/firmware.js';
import * as checklistView from './views/checklist.js';
import * as historyView from './views/history.js';
import * as piscuView from './views/piscu.js';
import * as mqttView from './views/mqtt.js';
import * as adminView from './views/admin.js';

// The GAP between rounds (not their duration). The light round only visits
// green devices so it finishes quickly on its own; two seconds is what a
// field eye reads as "live". The server reads the round in order, so
// shortening this does not overlap requests, it only tires the devices.
const LIGHT_INTERVAL = 2000;
// Discovery round: is there a device at this IP? It runs rarely because each
// unreachable device costs a full timeout.
const FULL_SCAN_INTERVAL = 60000;
// The screen is empty when a session opens and when the set changes; the
// first discovery does not wait a whole minute. The short delay keeps the
// first render from racing the scan.
const FIRST_SCAN_DELAY = 1500;
// How long to wait before looking again when a scan was skipped for a reason.
const BLOCKED_RETRY = 3000;
const JOB_INTERVAL = 900;
// The service key: a USB stick appearing is a physical act, and a second is
// the difference between "the panel noticed" and "the panel is broken".
// The cost is nothing but reading back what the panel's own watcher already
// established (see panel/adminkey/watcher.py), not a device read, so this
// round is not held back by a running job the way the two above are.
const ADMIN_KEY_INTERVAL = 1000;

let stateGeneration = 0;
let lightTimer = null;
let jobTimer = null;
let scanTimer = null;

// ───────────────────────────────────────────────────────── fetching ──────
async function fetchState() {
  const generation = ++stateGeneration;
  const data = await api.state(state.setNo);
  if (generation !== stateGeneration) return null;   // a newer request exists
  locked.applyState(data);
  await refreshOpenView();
  return data;
}

// The checklist is fed by its own endpoint rather than by device reads
// (/api/checklist, the template plus the current view). Because it was only
// fetched on entering the screen, old rows stayed on screen while a scan ran
// or the light refresh brought new values.
//
// Signature: a digest of the device results. Unchanged, no request is made —
// there is no point fetching the template preview on every 900 ms job round.
const REFRESH_INTERVAL = 1500;
let lastSignature = '';
let lastRefreshAt = 0;

function deviceSignature() {
  return (state.devices || [])
    .map(d => `${d.id}${d.result.state}${d.result.readAt || 0}`)
    .join('|');
}

async function refreshOpenView() {
  if (state.view !== 'checklist') return;
  const signature = deviceSignature();
  const now = Date.now();
  if (signature === lastSignature || now - lastRefreshAt < REFRESH_INTERVAL) {
    return;
  }
  lastSignature = signature;
  lastRefreshAt = now;
  await checklistView.refresh();
}

// The job list arrives as a new array every round; because `patch` compares
// by reference, the whole UI was redrawn even when nothing had changed. With
// the queue panel open that meant a full render every second.
let lastJobSignature = null;

async function fetchJobs() {
  try {
    const body = await api.jobs();
    let jobs = body.jobs || [];
    if (state.openJob) {
      try {
        const full = await api.job(state.openJob);
        jobs = jobs.map(j => (j.id === full.id ? full : j));
      } catch { /* the job may have been removed */ }
    }
    const signature = JSON.stringify(jobs);
    if (signature === lastJobSignature) return;
    lastJobSignature = signature;
    patch({ jobs });
  } catch { /* if the service missed a round, the next one retries */ }
}

// ───────────────────────────────────────────────────────── loops ─────────
function jobLoop() {
  clearTimeout(jobTimer);
  const running = (state.jobs || []).some(
    j => j.state === 'running' || j.state === 'queued');
  const needed = running || state.queueOpen;
  jobTimer = setTimeout(async () => {
    if (state.meta) {
      await fetchJobs();
      if (running) { try { await fetchState(); } catch { /* ignore */ } }
    }
    jobLoop();
  }, needed ? JOB_INTERVAL : 4000);
}

// The light refresh targets ONLY devices that went green in the last scan.
// Retrying an unreachable device every round grows the round by that device's
// timeout and the working devices' data goes stale. Retrying the unreachable
// is the minute-long discovery round's job. The server applies the same
// filter (panel.api.routes.session_routes.post_refresh); listing them here
// keeps the request small.
function refreshTargets() {
  return (state.devices || [])
    .filter(d => d.result && d.result.state === 'ok')
    .map(d => d.id);
}

// Did the running scan come from the UI's own timer? A scan the user asked
// for is worth making them wait for; the round that appears once a minute on
// its own must not lock the UI (see setUpSetPicker).
function automaticScanJob() {
  return (state.jobs || []).find(
    j => j.kind === 'scan' && j.auto
      && (j.state === 'running' || j.state === 'queued')) || null;
}

// The discovery round. How long to wait can be passed in: "Scan now",
// opening a session and changing the set each reset the timer with their own
// delay.
function scanLoop(delay = FULL_SCAN_INTERVAL) {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(async () => {
    // When a round is skipped the timer is not reset to a full minute but
    // retried shortly: the scan should run the moment the obstacle clears,
    // not a minute later. After a long firmware run the devices' state has
    // changed from top to bottom, and the delay there is the most annoying
    // one. The check reads local state, so looking often costs nothing.
    // Being paused is one of those reasons, and retrying it shortly is what
    // makes resuming feel immediate.
    if (!scanRoundAllowed(state)) {
      scanLoop(BLOCKED_RETRY);
      return;
    }
    try {
      await api.scan(state.setNo, true);
      await fetchJobs();
    } catch { /* if the service missed a round, the next one retries */ }
    scanLoop();
  }, delay);
}

function lightLoop() {
  clearTimeout(lightTimer);
  lightTimer = setTimeout(async () => {
    if (lightRoundAllowed(state)) {
      const targets = refreshTargets();
      if (targets.length) {
        const generation = ++stateGeneration;
        try {
          const data = await api.refresh(state.setNo, targets);
          if (generation === stateGeneration) {
            locked.applyState(data);
            await refreshOpenView();
          }
        } catch (e) {
          // 409 = a full scan cut in; quietly leave it to the next round
          if (e.status && e.status !== 409) {
            console.warn('light refresh:', e.message);
          }
        }
      } else {
        // No green device to refresh — but the open screen's own endpoint
        // (the checklist) does not depend on device reads. Without this
        // branch the list froze at its first view whenever no device was
        // green. The signature check already skips the request when nothing
        // changed.
        await refreshOpenView();
      }
    }
    lightLoop();
  }, LIGHT_INTERVAL);
}

// ───────────────────────────────────────────────────────── rendering ─────
const VIEWS = {
  overview: ['#v-overview', (root) => overviewView.render(root, refreshNow)],
  devices: ['#v-devices', (root) => devicesView.render(root)],
  ip: ['#v-ip', (root) => ipView.render(root)],
  network: ['#v-network', (root) => networkView.render(root)],
  adb: ['#v-adb', (root) => adbView.render(root)],
  switch: ['#v-switch', (root) => switchView.render(root)],
  config: ['#v-config', (root) => configView.render(root)],
  firmware: ['#v-firmware', (root) => firmwareView.render(root)],
  checklist: ['#v-checklist', (root) => checklistView.render(root, refreshNow)],
  history: ['#v-history', (root) => historyView.render(root)],
  piscu: ['#v-piscu', (root) => piscuView.render(root)],
  mqtt: ['#v-mqtt', (root) => mqttView.render(root)],
  admin: ['#v-admin', (root) => adminView.render(root, openProject)],
};

let lastView = null;

// Only the side panels depend on these keys. Opening and closing a job in the
// queue does not need the rest of the screen (device table, sidebar, top bar)
// rebuilt — and rebuilding it stuttered visibly.
const PANEL_KEYS = new Set(['openJob', 'queueOpen', 'lockedOpen']);

// A language switch changes every string on screen, so the whole shell is
// redrawn: the sidebar is rebuilt from scratch (it is normally built once and
// left alone) and the open view is drawn again from the same state.
// The top bar says nothing in field mode: the package IS the role, and a
// badge repeating that on every screen of every customer's copy was noise.
// In admin mode it says so, and it says when the key has been pulled but a
// write is still finishing (panel/adminkey/watcher.py holds the mode open
// until the queue clears rather than dropping it mid-run).
function renderMode() {
  const badge = $('#mode-badge');
  const leave = $('#leave-admin-btn');
  const enter = $('#enter-admin-btn');
  const remoteButton = $('#remote-admin-btn');
  const admin = state.mode === 'admin';
  const pending = !!(state.adminKey && state.adminKey.revokePending);
  // Which way in is holding the mode open changes what the badge says, and
  // it is worth saying: an engineer connected from somewhere else is a
  // different fact about this machine than a stick in its side, and the
  // person sitting at it should be able to see which one is true.
  const remote = state.remote;
  const viaRemote = admin && !pending && !!(remote && remote.active);
  badge.hidden = !admin;
  badge.textContent = admin
    ? t(pending ? 'topbar.adminModeEnding'
      : viaRemote ? 'topbar.adminModeRemote' : 'topbar.adminMode')
    : '';
  badge.dataset.pending = pending ? '1' : '0';
  leave.hidden = !admin;
  // No key material needed for this one, and no stick: what it needs is a
  // build that can CHECK a grant (panel/remotekey/verify.py) and a mode
  // that is not already open.
  remoteButton.hidden = admin
    || !(state.edition && state.edition.remoteAvailable);
  // The way BACK IN, and it is offered only where it would work: the key is
  // in the machine, or this run holds the build secret and needs no key. A
  // customer with neither never sees it, which is the same rule the server
  // enforces on the request itself (panel/api/routes/admin_routes.py).
  enter.hidden = admin || !canEnterAdmin();
}

function canEnterAdmin() {
  // `withoutKey` rather than the edition's `adminByDefault`: the same fact,
  // but off the poll rather than off the body that was read at launch. The
  // build secret can be dropped into the checkout while the panel is open
  // (panel/adminkey/secret.py), and then this button has to appear without
  // anybody restarting anything.
  const key = state.adminKey;
  return !!(key && (key.recognised || key.withoutKey))
    || !!(state.edition && state.edition.adminByDefault);
}

function redrawEverything() {
  sidebar.reset();
  lastView = null;
  detail.close();
  dialog.close();
  render(state, null);
  queue.render();
  locked.render();
}

function render(_state, changed) {
  // Nothing is drawn before the project metadata arrives. It used to be the
  // chosen role that gated this; there is no such moment now, and `meta` is
  // what every panel below actually reads.
  if (!state.meta) return;

  if (Array.isArray(changed) && changed.length
      && changed.every(key => PANEL_KEYS.has(key))) {
    queue.render();
    locked.render();
    return;
  }

  // top bar
  const meta = state.meta;
  if (meta) {
    $('#project-name').textContent = meta.project;
    setUpSetPicker();
  }
  // GDM and the exhibition rack are addressed in fixed form — there is no
  // `n` in their maps for the set number to replace, so this box substitutes
  // nothing. Hidden rather than disabled: a greyed-out control still says
  // "this exists here, something is stopping it", and nothing is.
  //
  // Marked on the BAR, not on the field: the "/" between the project name
  // and the box is a separator for two things, and hiding one of them
  // leaves it separating nothing.
  const projectBar = $('.project-bar');
  if (projectBar) {
    projectBar.dataset.setPicker =
      (state.edition && state.edition.fixedAddressing) ? '0' : '1';
  }
  renderMode();
  $('#status-text').textContent = queue.summaryText(refreshTargets().length);
  $('#footer-version').textContent = `v${state.version}`;

  const refreshButton = $('#refresh-btn');
  refreshButton.disabled = !!state.scanRunning;
  // Only the visible label changes; the measuring label stays in place to
  // keep the button's width fixed (see index.html).
  $('.label-live', refreshButton).textContent = state.scanRunning
    ? t('topbar.scanning') : t('topbar.scanNow');

  // Pressed means paused. The GLYPH says what the click does — the media
  // convention, bars to stop and a triangle to start — because a picture is
  // not read as a sentence and "▶" has never meant "it is playing". What the
  // panel IS doing is said twice over instead, and in the two places that
  // cannot be misread: the amber frame around the pair, and the footer, in
  // words ("Paused since 14:19" — see components/queue.js summaryText).
  const paused = !state.autoRefresh;
  const autoButton = $('#auto-btn');
  autoButton.setAttribute('aria-pressed', String(paused));
  autoButton.title = t(paused ? 'topbar.resumeScans' : 'topbar.pauseScans');
  autoButton.setAttribute('aria-label', autoButton.title);
  $('#auto-icon').setAttribute('d', paused
    ? 'M7.5 5 15 10l-7.5 5z'
    : 'M7.5 5.5v9M12.5 5.5v9');
  $('#scan-group').dataset.paused = paused ? '1' : '0';
  alignSidePanel();

  sidebar.render();
  queue.render();
  locked.render();
  $('#panel-scrim').hidden = !(state.queueOpen || state.lockedOpen);

  for (const [name, [selector]] of Object.entries(VIEWS)) {
    $(selector).hidden = name !== state.view;
  }
  const [selector, renderView] = VIEWS[state.view] || VIEWS.overview;
  const viewChanged = lastView !== state.view;

  // Staying on the same screen preserves the scroll position; on a screen
  // change, starting at the top is the right behaviour.
  //
  // Rebuilding a screen recreates the boxes inside it and loses the value
  // being typed (fields save on change, i.e. when focus leaves). With the
  // refresh round now arriving seconds apart, that meant constantly losing
  // text while typing in a configuration field. A round's render is skipped
  // while focus is in a box on the screen; a screen change is the user's own
  // action, so it is never skipped.
  //
  // Rendering over an open dropdown closes it. While a scan runs, device
  // reads arrive every second and a device read can cut in on a timeout, so
  // the list closed before the user could press an option and picking a
  // target group or device became impossible.
  //
  // It does not matter which data arrived: rendering waits while a list has
  // focus. Where the screen must refresh after a selection (target type,
  // target group) the `change` handler moves focus off the list — this
  // condition then falls away and the selection renders at once (see
  // group_bar.picker).
  if (viewChanged || !(focusInScreenField() || focusInDropdown())) {
    preserveScroll(viewChanged ? null : $('#content'),
                   () => renderView($(selector)));
  }

  if (viewChanged) {
    lastView = state.view;
    $('#content').scrollTop = 0;
    announceView();
    playTransition($(selector));
    onViewEntered(state.view);
  }
}

// What tells anyone NOT looking at the screen that the screen changed.
//
// Clicking a menu item used to leave focus on that menu button: Tab carried
// on through the rail instead of entering the new screen, and a screen reader
// said nothing at all — the whole content area had swapped underneath without
// a word. Three things fix it, and they say the same sentence:
//
//   · the document's only h1 is renamed to the open screen;
//   · #route-status announces it (its own live region — #toast holds one
//     message at a time and the job queue overwrites it constantly);
//   · focus moves into #content, so the next Tab starts where the user is
//     actually looking.
//
// Only on a real screen change. Doing it on every render would steal focus
// from whatever the user was typing in, every refresh round.
// The name of a screen, as the operator knows it. Not derivable from the
// view id: the three operation screens are named by their tab, not by the
// "Operations" area that holds all three.
const VIEW_NAME = {
  overview: 'nav.overview',
  devices: 'nav.devices',
  ip: 'tabs.networkAndIp',
  config: 'tabs.deviceSettings',
  firmware: 'tabs.firmware',
  // The rail has room for one word; the announcement does not have to
  // settle for it. "The computer's network" is what the screen is.
  network: 'net.title',
  adb: 'nav.adb',
  switch: 'nav.switch',
  checklist: 'nav.verification',
  history: 'nav.history',
  piscu: 'nav.piscu',
  mqtt: 'nav.mqtt',
  admin: 'nav.project',
};

function announceView() {
  const name = t(VIEW_NAME[state.view] || 'nav.overview');
  const title = $('#view-title');
  const status = $('#route-status');
  if (title) title.textContent = name;
  if (status) status.textContent = name;
  $('#content').focus();
}

// Keyboard shortcuts.
//
// The panel is used all day and mostly between three screens; reaching for
// the mouse to move between them is the kind of small cost that is paid a
// hundred times a shift. Digits pick a screen, `/` jumps to the device
// search, `?` lists them all.
//
// None of them fire while somebody is typing: a field or a dropdown with
// focus owns every key, or "/" in a search box would open a dialog instead
// of being typed. Modifier combinations are left to the browser.
// IN THE ORDER OF THE RAIL (components/sidebar.js), because the digit is
// only useful if it is the position the operator can see. The switch screen
// was appended to the end of this list, so the help dialog offered "7" for a
// screen sitting sixth; the ADB screen beside it had no digit at all, which
// is what pushed everything below the two of them out of step.
const SHORTCUT_VIEWS = ['overview', 'devices', 'ip', 'network', 'adb',
                        'switch', 'checklist', 'history'];

// AND FILTERED BY WHAT THIS PACKAGE SHOWS, the same question the rail asks.
// Two of these screens are behind the service key now, and a fixed list would
// have handed a field user a digit that opened one — drawn, empty, and with
// every request on it refused by the server (panel/api/guard.py). Before
// `/api/edition` answers there is nothing to filter against, so the whole
// list stands, exactly as the rail does.
function shortcutViews() {
  const allowed = state.views || [];
  if (!allowed.length) return SHORTCUT_VIEWS;
  return SHORTCUT_VIEWS.filter(view => allowed.includes(view));
}

// Derived, not written out. The digit range used to be a literal `[1-6]`
// beside a list of six, and the next screen added to the list got a line in
// the help dialog and a key that did nothing.
const shortcutKeys = (views) => views.map((_, index) => String(index + 1));

function shortcut(event) {
  if (dialog.isOpen() || event.metaKey || event.ctrlKey || event.altKey) {
    return;
  }
  const active = document.activeElement;
  if (active && active.matches(
    'input, textarea, select, [contenteditable="true"]')) {
    return;
  }

  const views = shortcutViews();
  if (shortcutKeys(views).includes(event.key)) {
    const wanted = views[Number(event.key) - 1];
    if (wanted && wanted !== state.view) patch({ view: wanted });
    event.preventDefault();
    return;
  }
  if (event.key === '/') {
    // Straight to the search box, opening the device list if it is not the
    // screen already.
    if (state.view !== 'devices') patch({ view: 'devices' });
    const box = $('#device-search');
    if (box) box.focus();
    event.preventDefault();
    return;
  }
  if (event.key === '?') {
    shortcutHelp();
    event.preventDefault();
  }
}

function shortcutHelp() {
  const rows = shortcutViews().map((view, position) => [
    String(position + 1), t(VIEW_NAME[view]),
  ]);
  rows.push(['/', t('shortcuts.search')]);
  rows.push(['Esc', t('shortcuts.close')]);
  dialog.show({
    title: t('shortcuts.title'),
    content: el('div', { class: 'shortcut-list' }, rows.map(
      ([key, label]) => el('div', { class: 'row' }, [
        el('kbd', { text: key }),
        el('span', { text: label }),
      ]))),
    actions: [el('button', {
      type: 'button', class: 'btn', text: t('detail.close'),
      onclick: () => dialog.close(),
    })],
  });
}

// A short entry animation on a screen change. Moving between tabs, the
// content shifting in a single frame looked like "nothing happened" because
// the heading and the group bar stay in place. The animation must restart on
// every transition; hence the class is removed first and a reflow forced.
function playTransition(root) {
  if (!root) return;
  root.classList.remove('view-enter');
  void root.offsetWidth;
  root.classList.add('view-enter');
}

// A render is skipped only for a box being TYPED IN. Dropdowns were not
// included: the moment a selection finished with `change`, focus was still on
// the list and that round's render was skipped — so a changed device or
// target group only showed its fields after switching tabs.
function focusInScreenField() {
  const active = document.activeElement;
  if (!active || !$('#content').contains(active)) return false;
  return active.matches(
    'input:not([type="checkbox"]):not([type="radio"]):not([type="button"]),'
    + ' textarea, [contenteditable="true"]');
}

// An open dropdown keeps focus on itself. The list may be on the screen or in
// a device settings dialog (see config.openDevice) — both are where the user
// is looking.
function focusInDropdown() {
  const active = document.activeElement;
  if (!active || !active.matches('select')) return false;
  return [$('#content'), $('#dialog-slot')].some(
    root => root && root.contains(active));
}

// A screen fetches its own data the first time it opens (not everything is
// fetched at start-up).
function onViewEntered(name) {
  if (name === 'checklist') checklistView.refresh();
  else if (name === 'ip') ipView.refresh();
  else if (name === 'network') networkView.refresh();
  else if (name === 'adb') adbView.refresh();
  else if (name === 'switch') switchView.refresh();
  else if (name === 'config') configView.refresh();
  else if (name === 'firmware') firmwareView.refresh();
  else if (name === 'piscu') piscuView.refresh();
  else if (name === 'mqtt') mqttView.refresh();
}

// ───────────────────────────────────────────────────────── actions ───────
// "Scan now" no longer STARTS a scan, it PULLS the next one FORWARD: the
// scan already runs once a minute, and the button queues that round now and
// resets the timer. If a run (IP assignment, configuration, firmware) is in
// progress the scan waits in the queue — with a single worker it can never
// collide with the run — and the user is told it is waiting.
//
// Starting a scan does NOT open the queue panel. When the job enters the
// queue the news appears on the queue button (badge + a short flash); whoever
// wants the panel presses the button. A panel covering the screen forced a
// user who wanted to watch the device list during a scan to close it every
// time.
async function refreshNow() {
  // Deliberately not gated on `state.autoRefresh`: pausing stops the rounds
  // the panel starts by itself, never the one the user asks for.
  const running = writingRunInProgress(state.jobs);
  try {
    const job = await api.scan(state.setNo);
    patch({ openJob: job.id, scanRunning: true });
    if (job.new === false) {
      notify(t('topbar.scanAlreadyQueued'));
    } else {
      queue.flash();
      if (running) notify(t('topbar.scanQueued'));
    }
    await fetchJobs();
  } catch (e) {
    showError(e.message);
  } finally {
    // After a manual scan the minute timer starts from zero; otherwise
    // pressing the button could trigger a second round a second later.
    scanLoop();
  }
}

// Aligns the left edge of the panels that open from the right with the left
// edge of the "Scan now" button: the buttons that open a panel stay above
// it and the panel looks like one piece attached to the top bar. The width
// cannot be hard-coded because the button labels in the top bar change
// ("Scanning…", the role badge).
//
// This only applies while the panel OVERLAYS the content, under 900px — the
// width at which every narrow rail in the application gives up its column
// (see base.css). Above it the panel takes a column of its own and the
// content narrows beside it, and then measuring against the top bar would be
// a feedback loop: the panel's width would set the content's width, which
// moves the button, which sets the panel's width. The wide layout uses the
// fixed --queue-width instead.
const OVERLAY_PANEL_MAX = 900;

function alignSidePanel() {
  const button = $('#refresh-btn');
  const body = $('.body');
  if (!button || !body) return;
  if (globalThis.innerWidth > OVERLAY_PANEL_MAX) return;
  const width = Math.round(
    body.getBoundingClientRect().right - button.getBoundingClientRect().left);
  if (width > 0) {
    document.documentElement.style.setProperty('--side-panel', `${width}px`);
  }
}

// The set number is typed into the top bar; anyone can use it regardless of
// role. The field is not touched while the user types — writing the value
// back while focus was in it erased what had been typed.
function setUpSetPicker(force = false) {
  const picker = $('#set-picker');
  if (!picker) return;
  const { min, max } = setLimits();
  picker.min = String(min);
  picker.max = String(max);
  if ((force || document.activeElement !== picker)
      && picker.value !== String(state.setNo)) {
    picker.value = String(state.setNo);
  }
  // Only a MANUALLY started scan locks the field. Because a scan runs once a
  // minute on its own, counting the automatic round too would make changing
  // the set number impossible for a few seconds every minute; unable to
  // predict when the lock would lift, the user clicked the field for nothing.
  const isLocked = manualScanRunning();
  picker.disabled = isLocked;
  picker.title = isLocked
    ? t('topbar.setLockedByScan')
    : t('topbar.changeTrainSet', { min, max });
}

function manualScanRunning() {
  return !!state.scanRunning && !automaticScanJob();
}

// The accepted range comes from the server; a limit is needed before meta
// arrives too, so the same default as the server's lives here.
function setLimits() {
  const meta = state.meta || {};
  return { min: meta.setMin || 1, max: meta.setMax || 254 };
}

async function changeSet(value) {
  const { min, max } = setLimits();
  const next = Number(String(value).trim());
  if (!Number.isInteger(next) || next < min || next > max) {
    notify(t('topbar.setOutOfRange', { min, max }));
    setUpSetPicker(true);
    return;
  }
  if (next === state.setNo) return;
  if (manualScanRunning()) {
    notify(t('topbar.setLockedByScan'));
    setUpSetPicker(true);
    return;
  }
  // The automatic round is reading the old set's devices; its results are of
  // no use in the new set and there is no point waiting for it.
  const automatic = automaticScanJob();
  if (automatic) {
    try { await api.jobCancel(automatic.id); } catch { /* may have ended */ }
  }
  // The view is kept per set, so the old set's results are not carried over.
  detail.close();
  patch({ setNo: next, devices: [], locked: [], lastScan: null, ipState: null,
    configState: null, piscuState: null, checklistState: null,
    detailId: null });
  try {
    await loadInitialData();
    onViewEntered(state.view);
    showSuccess(t('topbar.setLoaded', { set: next }));
  } catch (e) {
    showError(e.message);
  }
  // A new set arrives empty: run the discovery round without waiting a minute.
  scanLoop(FIRST_SCAN_DELAY);
}

async function loadInitialData() {
  const meta = await api.project(state.setNo);
  patch({ meta, setNo: meta.setNo });
  await fetchState();
  await fetchJobs();
}

// ──────────────────────────────────────────────────── edition and mode ───
// What this package is allowed to show. Everything about it arrives in one
// body so the screen list, the mode and the project list can never be half
// updated: entering admin mode changes all three at once, and a redraw that
// caught two of them would draw a menu entry whose data the server refuses.
function applyEdition(body) {
  const wasAdmin = state.mode === 'admin';
  patch({
    edition: body,
    mode: body.mode,
    views: body.views || [],
    projects: body.projects || [],
  });
  // The open screen may have just stopped existing — leaving admin mode
  // while standing on PISCU. `patch` refuses the view rather than the state,
  // so the move has to be made here.
  if (!(state.views || []).includes(state.view)) {
    patch({ view: state.views[0] || 'overview' });
  }
  if (wasAdmin !== (body.mode === 'admin')) redrawEverything();
  return body;
}

async function enterAdmin() {
  try {
    applyEdition(await api.adminMode(true));
    showSuccess(t('adminkey.entered'));
  } catch (e) {
    showError(e.message);
  }
}

async function leaveAdmin() {
  try {
    applyEdition(await api.adminMode(false));
    notify(t('adminkey.left'));
  } catch (e) {
    showError(e.message);
  }
}

// ──────────────────────────────────────── the remote service session ─────
// The other way into admin mode, on a machine with no service key in it: the
// panel opens a session on the grant service and then keeps asking that
// service to sign for it, and the mode lasts as long as the answers do (see
// panel/remotekey/watcher.py).
//
// TWO DOORS, ONE ROOM, AND SO ONE DIALOG. A square somebody approves on a
// telephone, and an engineer standing at the panel signing in as themselves.
// They end in the same place by the same evidence — a grant the SERVER
// checked a signature on — so they are laid out side by side rather than
// hidden behind a choice nobody can make before they know which one they
// have. The account is on the left because it needs nobody else awake; the
// square is on the right because it is what to reach for when the person who
// can say yes is somewhere else.
//
// EACH COLUMN IS NAMED, and that heading is the only thing telling the two
// apart: same ground, same rhythm, one line of accent caps over each. Two
// ways in that look alike and are labelled are read as alternatives; two
// that are drawn differently are read as a main way and a fallback, which is
// not true of either of these.
//
// THERE WAS A THIRD: eight characters read down a telephone into two boxes
// of four, with a button swapping them for the square. It is gone. It needed
// the same person awake at the other end that the square needs, so it bought
// nothing the square does not give, and it asked the operator to transcribe
// eight characters while standing next to a train. The service still mints
// those codes and `/api/admin/remote/connect` still takes one; nothing in
// this window asks for one any more.

function askForRemoteSession() {
  // Filled in by `startPairing` below, and refilled every time the square
  // moves on: asked for, waiting, refused, gone.
  const square = el('div', { class: 'remote-square' });

  dialog.show({
    title: t('remote.title'),
    // The account column, a rule, and the square's column. The square is
    // what fixes the right-hand number; the left takes what is left, which
    // is comfortably more than two fields and a button need.
    width: '720px',
    // The width the RIGHT-HAND column is drawn to, declared before the
    // service is even asked. It is here rather than in the stylesheet
    // because the window is what needs the number: the square's scale is
    // worked out from it, in whole modules (see squareBox).
    content: el('div', {
      class: 'remote-ways', style: `--remote-width:${PAIR_SIDE}px`,
    }, [
      accountSide(),
      el('div', { class: 'remote-way remote-pair' }, [
        wayHead(t('remote.wayQr')),
        square,
      ]),
    ]),
    actions: [
      el('button', {
        type: 'button', class: 'btn', text: t('locked.cancel'),
        onclick: () => dialog.close(),
      }),
    ],
    // Escape, the backdrop and the Cancel button all arrive here, which is
    // the only place that knows the square is no longer being looked at.
    onClose: stopPairing,
  });
  startPairing(square);
}

// ─────────────────────────────────── signing in as yourself ─────────────
// The left-hand column, and the only way in that needs nobody else awake:
// the engineer standing at the machine gives their own e-mail and password,
// and the service mints a session bound to this installation. The SERVER
// enters admin mode on the round that succeeds, on a signature it checked —
// exactly as it does for an approved square
// (panel/api/routes/remote_routes.py).
//
// THREE FACES, ONE COLUMN, ONE AT A TIME: signing in, asking for an account,
// and the sentence that follows a new one. They replace each other in place
// rather than opening dialogs of their own — the square on the right is live
// throughout, and a second window on top of it would cover the very thing
// the operator may be about to point a phone at.
//
// THE HEADING BELONGS TO THE FACE, not to the column, which is why the whole
// column is what gets refilled. A column headed "Sign in with an account"
// with a four-field "create an account" form under it is a heading that has
// stopped describing what is beneath it.
//
// THE PASSWORD LIVES IN ONE FIELD AND ONE REQUEST BODY. It is not put in
// `state`, not remembered for a retry, and the field is emptied the moment
// the reply lands — whichever way it landed, because a wrong password left
// on screen is a wrong password somebody tries to correct rather than
// retype.
//
// A REFUSAL KEEPS THE DIALOG OPEN, and that is the point of the layout: an
// account without permission to sign in from the panel is told so beside a
// square that is already drawn and already waiting. The fallback is not a
// second dialog; it is the other half of this one.
function accountSide() {
  const pane = el('div', { class: 'remote-way remote-account' });
  showSignIn(pane, '');
  return pane;
}

const wayHead = (caption) => el('h4', {
  class: 'remote-way-head', text: caption,
});

const fieldLabel = (caption, field) => el('label', { class: 'field-label' }, [
  el('span', { class: 'label', text: caption }),
  field,
]);

// The quiet line under the button: a sentence nobody has to read, and the
// way to the column's other face. It is a link rather than a second button
// because the column already has the one thing to press, and two buttons of
// equal weight under two fields is a question where there was an answer.
const aside = (sentence, link) => el('p', { class: 'remote-aside' }, [
  el('span', { text: sentence }),
  link,
]);

function showSignIn(pane, address) {
  const email = el('input', {
    class: 'field', type: 'email', autocomplete: 'off', value: address,
    autocapitalize: 'off', spellcheck: 'false', inputmode: 'email',
  });
  const password = el('input', {
    class: 'field', type: 'password', autocomplete: 'new-password',
  });
  const warning = el('p', { class: 'warning', role: 'alert', hidden: true });
  const submit = el('button', {
    type: 'submit', class: 'btn btn-primary remote-submit',
    text: t('remote.signIn'),
  });

  fill(pane, [wayHead(t('remote.wayAccount')), el('form', {
    class: 'remote-account-pane',
    onsubmit: async (event) => {
      event.preventDefault();
      warning.hidden = true;
      submit.disabled = true;
      submit.textContent = t('remote.signingIn');
      try {
        const answer = await api.remoteSignin(email.value.trim(),
                                              password.value);
        password.value = '';
        // Closing takes the square back at the same time: the dialog's
        // `onClose` is the only thing that knows a pairing was asked for.
        dialog.close();
        patch({ remote: answer.remote });
        applyEdition(answer);
        showSuccess(t('remote.connected'));
      } catch (e) {
        password.value = '';
        warning.textContent = e.message;
        warning.hidden = false;
        password.focus();
      } finally {
        submit.disabled = false;
        submit.textContent = t('remote.signIn');
      }
    },
  }, [
    fieldLabel(t('remote.email'), email),
    fieldLabel(t('remote.password'), password),
    warning,
    submit,
    aside(t('remote.noAccount'), el('button', {
      type: 'button', class: 'btn-link', text: t('remote.signUp'),
      // What is typed already comes along. Somebody who filled the address
      // in, was told there is no such account and pressed this should not be
      // asked for it a second time.
      onclick: () => showSignUp(pane, email.value.trim()),
    })),
  ])]);
  email.focus();
}

// Asking for an account, from the panel, by anybody holding it.
//
// WHAT THIS MAKES CANNOT DO ANYTHING. The service gives a new account every
// permission at zero, so the very next sign-in with it is refused until an
// administrator turns a switch on their own page — which is why the door can
// be open at all. The screen says so before the account is asked for and
// again after it exists, because somebody who was not told would spend the
// afternoon retyping a password that is perfectly correct.
function showSignUp(pane, address) {
  const name = el('input', {
    class: 'field', type: 'text', autocomplete: 'off', spellcheck: 'false',
  });
  const email = el('input', {
    class: 'field', type: 'email', autocomplete: 'off', value: address,
    autocapitalize: 'off', spellcheck: 'false', inputmode: 'email',
  });
  const password = el('input', {
    class: 'field', type: 'password', autocomplete: 'new-password',
  });
  const again = el('input', {
    class: 'field', type: 'password', autocomplete: 'new-password',
  });
  const warning = el('p', { class: 'warning', role: 'alert', hidden: true });
  const submit = el('button', {
    type: 'submit', class: 'btn btn-primary remote-submit',
    text: t('remote.signUp'),
  });

  const refuse = (message, field) => {
    password.value = '';
    again.value = '';
    warning.textContent = message;
    warning.hidden = false;
    field.focus();
  };

  fill(pane, [wayHead(t('remote.signUp')), el('form', {
    class: 'remote-account-pane',
    onsubmit: async (event) => {
      event.preventDefault();
      warning.hidden = true;
      // The two boxes are compared HERE and nowhere else. There is no
      // recovering a password nobody knows on an account nobody has
      // approved yet, and a mismatch needs no round trip to notice.
      if (password.value !== again.value) {
        refuse(t('remote.passwordMismatch'), password);
        return;
      }
      submit.disabled = true;
      submit.textContent = t('remote.signingUp');
      const wanted = email.value.trim();
      try {
        await api.remoteSignup(wanted, password.value, name.value.trim());
        password.value = '';
        again.value = '';
        showSignedUp(pane, wanted);
      } catch (e) {
        refuse(e.message, password);
      } finally {
        submit.disabled = false;
        submit.textContent = t('remote.signUp');
      }
    },
  }, [
    fieldLabel(t('remote.name'), name),
    fieldLabel(t('remote.email'), email),
    fieldLabel(t('remote.password'), password),
    fieldLabel(t('remote.passwordAgain'), again),
    warning,
    submit,
    aside(t('remote.haveAccount'), el('button', {
      type: 'button', class: 'btn-link', text: t('remote.backToSignIn'),
      onclick: () => showSignIn(pane, email.value.trim()),
    })),
  ])]);
  name.focus();
}

// The account exists and is waiting on somebody. Said as an `.info` rather
// than a `.warning`: nothing went wrong, and the one thing left to do about
// it is not on this machine.
function showSignedUp(pane, address) {
  const back = el('button', {
    type: 'button', class: 'btn btn-primary remote-submit',
    text: t('remote.backToSignIn'),
    // The address goes back with it, so the person who has just chosen a
    // password can try it the moment somebody says yes.
    onclick: () => showSignIn(pane, address),
  });
  fill(pane, [wayHead(t('remote.signUp')),
    el('div', { class: 'remote-account-pane' }, [
      el('p', {
        class: 'info', role: 'status', text: t('remote.signUpWaiting'),
      }),
      back,
    ])]);
  back.focus();
}


// ─────────────────────────────────────────────── the square ─────────────
// The other half of the same dialog, for the far more common case: nobody
// has to read anything out. The panel asks the service for a pairing, draws
// the square that comes back, and asks every couple of seconds whether
// anybody has approved it. The round that finds an approval is the round
// that enters admin mode — and the SERVER does that, on a signature it
// checked, exactly as it does for a code typed in below
// (panel/api/routes/remote_routes.py).
//
// THE SQUARE IS AN `<img>` WITH AN INLINE-ENCODED SOURCE, and that is not
// decoration. What the service draws is SVG; SVG inside an `<img>` is static
// by specification — no script runs, nothing is fetched. Putting the same
// markup into the page AS markup would hand a drawing that came off the
// network the run of the panel's own DOM, which is the one thing `el()`
// exists to make impossible (see core/dom.js).

// A late answer never touches a screen that has moved on. Every round takes
// a number, closing the dialog burns it, and an answer that comes back with
// an old one is dropped — the same rule the refresh loops follow.
let pairRound = 0;
let pairTimer = null;
// Whether the service is holding a pairing this window asked for. Only this
// says whether closing the dialog has anything to take back.
let pairingOpen = false;

// Statuses worth asking again after. Everything else is a decision — the
// pairing was refused, expired or swept — and the square says so and stops
// rather than beating against it.
const PAIR_RETRY = new Set([0, 429, 503]);

// How big the square wants to be, before it is rounded to whole modules.
//
// MEASURED IN MODULES, NOT IN PIXELS. A pairing address is 54 characters,
// which is a version 4 code: 33 modules of code, 41 across with its margin.
// At 176px — where this started — each module was four pixels, which is
// below what a phone can resolve at the distance it will also focus at.
// Eight is comfortable and does not take over the dialog.
//
// It is not a workaround for anything. The square was unreadable at every
// size for a fortnight because the service was drawing the format
// information backwards, and enlarging it did nothing at all; the fix was
// in the service (dabp-remote-key/src/qr.js). This is just a legible size.
const PAIR_SIDE = 224;

// HOW MUCH WHITE IS LEFT AROUND IT, IN MODULES.
//
// The service draws the four the standard asks for, which is the right thing
// for a code that might be printed and photographed off a wall. On a panel
// it is a fifth of the picture: with the margin also counted into the scale,
// the code came out at seven pixels a module inside a plate that was a third
// white — a small drawing floating on a card, which is what made the square
// look pasted on rather than presented.
//
// Two, and they are the ONLY white: the scale is worked out from the code
// plus these two and nothing else, so the plate is filled by what somebody
// is meant to point a telephone at. Not zero, and this is the one place the
// number cannot be chosen by eye — a code with nothing clear around it is
// read against whatever is behind it, and behind this one is a dark panel.
// Two modules is what a screen decoder wants at arm's length.
const PAIR_QUIET = 2;

// Everything the window needs to draw one: the picture's real size, the
// size of the hole it is seen through, and how far to pull it up and left
// behind that hole.
//
// A WHOLE NUMBER OF PIXELS PER MODULE. The drawing asks for crisp edges, so
// a fractional scale — 300 across 41 modules is 7.3 — is not blurred; it is
// SNAPPED, and the modules come out alternating seven and eight pixels wide.
// Rounding down to seven costs thirteen pixels of size and makes every
// square the same size as every other, which is the assumption a decoder
// starts from.
function squareBox(modules, quiet) {
  const across = Number(modules);
  const margin = Number(quiet);
  if (!(across > 0)) return { side: PAIR_SIDE, shown: PAIR_SIDE, offset: 0 };
  // The margin the picture keeps, and the margin the plate has to supply
  // because the picture did not carry it. Between them the code always sits
  // inside `PAIR_QUIET` clear modules, however the service drew it.
  const kept = Math.min(margin, PAIR_QUIET);
  const crop = margin - kept;
  const shownModules = across - crop * 2;
  // THE SCALE IS WORKED OUT FROM WHAT IS SEEN, not from the whole picture.
  // Dividing by `across` sized the code against margin that was then cropped
  // away, so it lost a pixel a module to white nobody ever saw.
  const boxModules = shownModules + (PAIR_QUIET - kept) * 2;
  const scale = Math.max(1, Math.floor(PAIR_SIDE / boxModules));
  return {
    side: across * scale,
    shown: shownModules * scale,
    offset: -crop * scale,
  };
}

function stopPairing() {
  pairRound += 1;
  if (pairTimer !== null) { clearTimeout(pairTimer); pairTimer = null; }
  if (!pairingOpen) return;
  pairingOpen = false;
  // Nothing waits for this and nothing is shown if it fails: the dialog has
  // already gone, and a pairing nobody takes back expires on its own.
  api.remotePairCancel().catch(() => {});
}

async function startPairing(square) {
  const mine = (pairRound += 1);
  // Nothing arms a timer and then offers "another square", so this should
  // already be clear — but a round left beating against a square that has
  // been replaced is the one failure here nobody would ever see.
  if (pairTimer !== null) { clearTimeout(pairTimer); pairTimer = null; }
  // The spinner and nothing else. "Preparing the square" is a sentence whose
  // whole content is already on screen as a spinner, in a dialog the
  // operator opened one second ago.
  fill(square, [loading('')]);
  let answer;
  try {
    answer = await api.remotePair();
  } catch (e) {
    if (mine === pairRound) fill(square, [pairFailed(square, e.message)]);
    return;
  }
  // The dialog closed while the service was answering, so there is a pairing
  // out there that nothing will use. It is left to expire rather than
  // cancelled: another square may have been asked for since, and the service
  // keeps one at a time — cancelling now would take back the wrong one.
  if (mine !== pairRound) return;

  pairingOpen = true;
  const pair = answer.pair || {};
  const box = squareBox(pair.modules, pair.quiet);
  // The plate is a fixed square (see components.css .remote-qr) and the code
  // is centred in it: a code is drawn in whole modules, so its own side is
  // whatever the module count makes it, and a plate that took that number
  // would be a different size for a different code. What is left over is
  // white, which is quiet zone, which is the one thing a decoder wants more
  // of. This is the only number that comes from the answer.
  const inset = Math.round((PAIR_SIDE - box.shown) / 2);
  fill(square, [
    el('div', { class: 'remote-qr' }, [
      el('img', {
        src: pair.image, alt: t('remote.pairAlt'),
        width: box.side, height: box.side,
        style: `left:${box.offset + inset}px;top:${box.offset + inset}px`,
      }),
    ]),
    // ONE ROW, NOT TWO SENTENCES. What it is doing on the left, which
    // request it is on the right, both ending where the square ends. The
    // number is there because a square that will not scan is not the end of
    // the road — the same request is waiting on the operator's own page
    // under it — and it is a badge rather than a sentence because nobody
    // reads it until they need it.
    el('div', { class: 'remote-status', role: 'status', 'aria-live': 'polite' }, [
      el('span', { class: 'remote-status-live' }, [
        el('span', { class: 'dot', 'data-state': 'busy', 'aria-hidden': 'true' }),
        el('span', { text: t('remote.pairWaiting') }),
      ]),
      el('span', {
        class: 'badge', title: t('remote.pairNumber'),
        text: pair.pairId || '',
      }),
    ]),
  ]);
  waitForPairing(square, pair.pollAfter, mine);
}

function waitForPairing(square, after, mine) {
  const seconds = Number(after) > 0 ? Number(after) : 2;
  pairTimer = setTimeout(() => pollPairing(square, seconds, mine),
                         seconds * 1000);
}

async function pollPairing(square, seconds, mine) {
  pairTimer = null;
  let answer;
  try {
    answer = await api.remotePairPoll();
  } catch (e) {
    if (mine !== pairRound) return;
    if (!PAIR_RETRY.has(e.status)) {
      pairingOpen = false;
      fill(square, [pairFailed(square, e.message)]);
      return;
    }
    // The network, or a service asking to be left alone for a moment. The
    // square is still good and the deadline is the service's, so this is
    // ridden out exactly as the grant beat rides out silence.
    waitForPairing(square, seconds, mine);
    return;
  }
  if (mine !== pairRound) return;

  // Approved, and the server has already been in and out of the service with
  // it: what came back is the whole edition, the way a sign-in gets it.
  if (answer.mode !== undefined) {
    pairingOpen = false;                  // used, not abandoned — never cancel
    dialog.close();
    patch({ remote: answer.remote });
    applyEdition(answer);
    showSuccess(t('remote.connected'));
    return;
  }
  const settled = (answer.pair || {}).state;
  if (settled !== 'pending') {
    pairingOpen = false;
    // Expired, or given up on: there is nothing to say about it that the
    // button underneath does not say better. A REFUSAL IS DIFFERENT —
    // somebody decided that, and swallowing it would leave the operator
    // pressing "new square" until they wore out.
    fill(square, [pairFailed(square,
      settled === 'denied' ? (answer.stateText || '') : '')]);
    return;
  }
  waitForPairing(square, seconds, mine);
}

// The square is gone, and here is the one thing to do about it. The
// sentence above the button is for the cases where it would not otherwise
// be obvious — a refusal, or a service that could not be reached — and is
// left out where it would only be reading the button back.
function pairFailed(square, message) {
  return el('div', { class: 'remote-pair-failed' }, [
    message ? loadFailed(message) : null,
    el('button', {
      type: 'button', class: 'btn', text: t('remote.pairRetry'),
      onclick: () => startPairing(square),
    }),
  ]);
}

// Polled on the same beat as the service key, and only where it could do
// anything: a package built without a public key for the service has no
// session to ask about.
async function pollRemote() {
  if (!(state.edition && state.edition.remoteAvailable)) return;
  let seen;
  try { seen = await api.remote(); } catch { return; }
  const previous = state.remote;
  patch({ remote: seen });
  if (!previous || previous.generation === seen.generation) return;
  // The session was holding the door and is not any more — the link was
  // closed, the network went, or the grant simply ran out. The server has
  // already dropped the mode (or is holding it until a write finishes), so
  // what is on screen has to be read again rather than guessed at.
  if (previous.active && !seen.active) {
    try { applyEdition(await api.edition()); } catch { /* next round */ }
    notify(seen.reasonText || t('remote.ended'));
  }
}

// ────────────────────────────────────────────────── the service key ──────
// The only way into admin mode on a customer package. There is no socket, so
// the panel asks; `generation` counts OBSERVED CHANGES rather than polls, so
// asking twice a second still means "nothing has happened" almost every
// time (see panel/adminkey/watcher.py).
let adminKeyTimer = null;
// The observation the user has already said no to. Without this the question
// would come back every two seconds; with it, it comes back only after the
// key has been taken out and put in again.
let declinedGeneration = -1;
let askingAboutKey = false;

function adminKeyLoop() {
  clearTimeout(adminKeyTimer);
  adminKeyTimer = setTimeout(async () => {
    try {
      const seen = await api.adminKey();
      const previous = state.adminKey;
      patch({ adminKey: seen });
      // `withoutKey` as well as the generation: the secret appearing or
      // going away changes what may be done without anything happening to
      // a volume, so the observation counter would not move.
      if (!previous || previous.generation !== seen.generation
          || previous.withoutKey !== seen.withoutKey) {
        await onKeyChanged(seen, previous);
      }
    } catch { /* the next round retries */ }
    // On the same beat rather than a timer of its own: both questions are
    // "has the way in gone away", both are cheap, and two timers would mean
    // two answers arriving out of step about one mode.
    await pollRemote();
    adminKeyLoop();
  }, ADMIN_KEY_INTERVAL);
}

async function onKeyChanged(seen, previous) {
  // Admin mode may have just ended on its own: the key was pulled — or the
  // secret file taken away — and the server dropped it (or is holding it
  // until a write finishes).
  if (state.mode === 'admin' && !seen.recognised && !seen.withoutKey) {
    try { applyEdition(await api.edition()); } catch { /* next round */ }
    if (state.mode !== 'admin') {
      // Which of the two went away decides which sentence is true. Saying
      // "the key was removed" to somebody who deleted the secret file would
      // send them looking at a USB port for no reason.
      const pulled = !!(previous && previous.recognised);
      notify(t(pulled ? 'adminkey.removed' : 'adminkey.closed'));
    }
    return;
  }
  if (state.mode === 'admin' || !seen.recognised) {
    // A key was found and NOT recognised: worth saying, because a stick that
    // looks right and is not is otherwise indistinguishable from no stick.
    if (seen.present && !seen.recognised) {
      // "denied" is not a bad key, it is a key nobody was allowed to read:
      // the operating system gates removable volumes and the panel runs
      // elevated (see panel/adminkey/keyfile.py). Said even at launch —
      // `previous` null — because there is something to go and do about it,
      // and it will not fix itself on the next poll.
      if (seen.reason === 'denied') notify(t('adminkey.denied'));
      else if (previous) notify(t('adminkey.notRecognised'));
    }
    return;
  }
  if (seen.generation === declinedGeneration) return;
  await askAboutKey(seen, !previous);
}

async function askAboutKey(seen, atLaunch) {
  if (askingAboutKey) return;
  askingAboutKey = true;
  try {
    const yes = await dialog.ask({
      title: t(atLaunch ? 'adminkey.launchTitle' : 'adminkey.switchTitle'),
      body: t(atLaunch ? 'adminkey.launchLead' : 'adminkey.switchLead',
              { label: seen.label || t('adminkey.unlabelled') }),
      confirm: t(atLaunch ? 'adminkey.startAdmin' : 'adminkey.switchNow'),
      cancel: t(atLaunch ? 'adminkey.continueNormal' : 'adminkey.notNow'),
    });
    if (yes) await enterAdmin();
    else declinedGeneration = seen.generation;
  } finally {
    askingAboutKey = false;
  }
}

// ────────────────────────────────────────────────── project switching ────
// TWO DIFFERENT QUESTIONS, and they are deliberately not in the same place.
//
// The top bar switches between THIS PACKAGE'S OWN projects — VIP and
// Yatakli, one operator's two train types. That is an everyday move for the
// person the package was built for, so it sits on the project name where
// they already are.
//
// Opening ANOTHER CUSTOMER'S project is not that. It exists only in admin
// mode, it is an engineer's act rather than an operator's, and it belongs
// with the rest of what admin mode is for — so it lives on the project card
// of the admin screen (`views/admin.js`), beside the project it replaces.
// Mixing the two put another customer's train one click from the name of
// the one on screen, which is the wrong shape for the heavier act.
const ownProjects = () =>
  (state.projects || []).filter(project => project.origin !== 'extra');

async function chooseProject() {
  const projects = ownProjects();
  const current = projects.find(p => p.current);
  const picked = await dialog.pick({
    title: t('topbar.projectSwitch'),
    cancel: t('locked.cancel'),
    options: projects.map(project => ({
      value: project.key,
      label: project.label,
      // A project whose device list has not arrived yet (VIP today) is
      // listed with the reason rather than left out: it exists, and the
      // engineer asking for it deserves to be told why not.
      note: project.available ? '' : t('admin.projectUnavailable'),
      disabled: !project.available || project.key === (current || {}).key,
    })),
  });
  if (!picked || (current && picked === current.key)) return;
  await openProject(picked);
}

// The switch itself, wherever it was asked for. Handed to the admin screen
// the same way `changeSet` is: that screen must not have to know how a
// project switch unwinds the session, and this module must not have to know
// what that screen looks like.
async function openProject(key) {
  const current = (state.projects || []).find(p => p.current);
  if (!key || (current && key === current.key)) return;
  try {
    applyEdition(await api.selectProject(key));
  } catch (e) {
    showError(e.message);
    return;
  }
  // The new project's devices are different hardware behind the same ids.
  detail.close();
  patch({
    devices: [], locked: [], lastScan: null, ipState: null, configState: null,
    piscuState: null, checklistState: null, detailId: null, jobs: [],
    // Was missing while its four neighbours were cleared: `firmwareState`
    // holds a list of device ids, and ids repeat across projects.
    firmwareState: null,
    // The chosen device type belonged to the old project's list, and the new
    // one may not have it. `group_bar.currentGroup` falls back on its own, so
    // nothing broke — but the stored name then disagreed with the picker, and
    // the fallback is worth being deliberate about rather than lucky.
    targetGroup: null,
  });
  try {
    await loadInitialData();
    onViewEntered(state.view);
    showSuccess(t('admin.projectSwitched', { project: state.meta.project }));
  } catch (e) {
    showError(e.message);
  }
  scanLoop(FIRST_SCAN_DELAY);
}

// ───────────────────────────────────────────────────────── start-up ──────
async function start() {
  // The catalogue comes first: every screen below reads from it, and the
  // shell in index.html is translated in place.
  try {
    await language.load();
  } catch { /* the version call below reports an unreachable service */ }
  language.renderAll(redrawEverything);

  try {
    const version = await api.version();
    patch({ version: version.version });
    $('#footer-version').textContent = `v${version.version}`;
  } catch {
    showError(t('error.serviceUnreachable'));
  }

  // WHICH PACKAGE IS THIS. Read before anything is drawn: the menu, the
  // keyboard shortcuts and the project button all ask what may be shown, and
  // an empty answer means "everything", which is the wrong way round to be
  // wrong (see core/store.js:viewAllowed).
  try {
    applyEdition(await api.edition());
  } catch {
    showError(t('error.serviceUnreachable'));
  }

  $('#refresh-btn').addEventListener('click', refreshNow);
  $('#auto-btn').addEventListener('click', () => {
    const resuming = !state.autoRefresh;
    patch({ autoRefresh: resuming });
    // Resuming does not wait out the remaining pause: the operator pressed it
    // because they want current data now.
    if (resuming) scanLoop(0);
  });
  $('#queue-btn').addEventListener('click', queue.toggle);
  $('#locked-btn').addEventListener('click', locked.toggle);
  $('#leave-admin-btn').addEventListener('click', leaveAdmin);
  $('#enter-admin-btn').addEventListener('click', enterAdmin);
  $('#remote-admin-btn').addEventListener('click', askForRemoteSession);
  // The project name does two different things depending on the package. On
  // one that carries a single project there is nothing to switch to, so it
  // opens the project screen if that screen exists at all; on one that
  // carries several it opens the menu.
  $('#project-btn').addEventListener('click', () => {
    // Counted over the package's OWN projects: the ones admin mode adds are
    // switched to from the admin screen, so a package carrying one project
    // still opens that screen rather than a menu of somebody else's trains.
    if (ownProjects().length > 1) chooseProject();
    else if ((state.views || []).includes('admin')) patch({ view: 'admin' });
  });
  globalThis.addEventListener('resize', alignSidePanel);

  // change also fires on leaving the field; there is no need to wait for
  // Enter.
  $('#set-picker').addEventListener('change',
    (e) => changeSet(e.target.value));
  $('#set-picker').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      changeSet(e.target.value);
    } else if (e.key === 'Escape') {
      setUpSetPicker(true);
      e.target.blur();
    }
  });

  for (const button of document.querySelectorAll('[data-close]')) {
    button.addEventListener('click', () => patch(
      button.dataset.close === 'queue'
        ? { queueOpen: false }
        : { lockedOpen: false }));
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (dialog.isOpen()) return;          // the dialog handles its own Escape
      if (state.detailId) { detail.close(); return; }
      if (state.queueOpen || state.lockedOpen) {
        patch({ queueOpen: false, lockedOpen: false });
      }
      return;
    }
    shortcut(e);
  });

  // The open screen is refreshed after a credential is verified too: the IP
  // assignment screen locks the run on the switch credential, and the user
  // had to leave and re-enter the page for the summary to update.
  locked.onCredentialsAccepted(() => {
    fetchJobs();
    onViewEntered(state.view);
  });
  subscribe(render);

  // The panel opens straight onto the application — there is no screen in
  // front of it any more — so the first data round starts here rather than
  // after a role was chosen.
  try {
    await loadInitialData();
  } catch (e) {
    showError(e.message);
  }
  jobLoop();
  lightLoop();
  // The table used to open empty and wait for "Scan now". Refreshing is
  // continuous, so the first discovery round should start on its own too.
  scanLoop(FIRST_SCAN_DELAY);
  adminKeyLoop();
  render();
  $('#content').focus();

  // One look at the slot before the first paint: a key already in the
  // machine should be offered at launch, not two seconds later.
  try {
    const seen = await api.adminKey();
    patch({ adminKey: seen });
    // "denied" as well as recognised: a key the panel is not allowed to read
    // looks exactly like an empty slot, and this is the moment to say so.
    if (seen.recognised || seen.reason === 'denied') {
      await onKeyChanged(seen, null);
    }
  } catch { /* the loop retries */ }
}

// Stop the running loops as the tab/window closes.
globalThis.addEventListener('pagehide', () => {
  clearTimeout(lightTimer);
  clearTimeout(jobTimer);
  clearTimeout(scanTimer);
  clearTimeout(adminKeyTimer);
});

start();
