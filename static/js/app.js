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

import { $, el, preserveScroll } from './core/dom.js';
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
import * as overviewView from './views/overview.js';
import * as devicesView from './views/devices.js';
import * as ipView from './views/ip/index.js';
import * as networkView from './views/network.js';
import * as adbView from './views/adb/index.js';
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
  config: ['#v-config', (root) => configView.render(root)],
  firmware: ['#v-firmware', (root) => firmwareView.render(root)],
  checklist: ['#v-checklist', (root) => checklistView.render(root, refreshNow)],
  history: ['#v-history', (root) => historyView.render(root)],
  piscu: ['#v-piscu', (root) => piscuView.render(root)],
  mqtt: ['#v-mqtt', (root) => mqttView.render(root)],
  admin: ['#v-admin', (root) => adminView.render(root, changeSet)],
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
  const admin = state.mode === 'admin';
  const pending = !!(state.adminKey && state.adminKey.revokePending);
  badge.hidden = !admin;
  badge.textContent = admin
    ? t(pending ? 'topbar.adminModeEnding' : 'topbar.adminMode') : '';
  badge.dataset.pending = pending ? '1' : '0';
  leave.hidden = !admin;
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
  renderMode();
  $('#status-text').textContent = queue.summaryText(refreshTargets().length);
  $('#footer-version').textContent = `v${state.version}`;

  const refreshButton = $('#refresh-btn');
  refreshButton.disabled = !!state.scanRunning;
  // Only the visible label changes; the measuring label stays in place to
  // keep the button's width fixed (see index.html).
  $('.label-live', refreshButton).textContent = state.scanRunning
    ? t('topbar.scanning') : t('topbar.scanNow');

  // Pressed means paused. The label says what the panel IS doing, not what
  // the click would do: a button reading "Resume" is easy to read as "it is
  // resuming", and being wrong about that means trusting stale readings.
  const autoButton = $('#auto-btn');
  autoButton.setAttribute('aria-pressed', state.autoRefresh ? 'false' : 'true');
  $('.label-live', autoButton).textContent = state.autoRefresh
    ? t('topbar.pause') : t('topbar.paused');
  autoButton.title = t(state.autoRefresh
    ? 'topbar.pauseHint' : 'topbar.resumeHint');
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
  network: 'nav.network',
  adb: 'nav.adb',
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
const SHORTCUT_VIEWS = ['overview', 'devices', 'ip', 'network', 'checklist',
                        'history'];

function shortcut(event) {
  if (dialog.isOpen() || event.metaKey || event.ctrlKey || event.altKey) {
    return;
  }
  const active = document.activeElement;
  if (active && active.matches(
    'input, textarea, select, [contenteditable="true"]')) {
    return;
  }

  if (/^[1-6]$/.test(event.key)) {
    const wanted = SHORTCUT_VIEWS[Number(event.key) - 1];
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
  const rows = SHORTCUT_VIEWS.map((view, position) => [
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
// This only applies while the panel OVERLAYS the content, under 1080px. Above
// that it takes a column of its own and the content narrows beside it — and
// then measuring against the top bar would be a feedback loop: the panel's
// width would set the content's width, which moves the button, which sets the
// panel's width. The wide layout uses the fixed --queue-width instead.
const OVERLAY_PANEL_MAX = 1080;

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
  patch({ meta, piscuIp: meta.piscuIp, setNo: meta.setNo });
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
// A package may carry more than one project (VIP and Yatakli belong to the
// same operator), and in admin mode it may also carry whatever came on the
// service key. Both go through the same menu.
async function chooseProject() {
  const projects = state.projects || [];
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
  try {
    applyEdition(await api.selectProject(picked));
  } catch (e) {
    showError(e.message);
    return;
  }
  // The new project's devices are different hardware behind the same ids.
  detail.close();
  patch({
    devices: [], locked: [], lastScan: null, ipState: null, configState: null,
    piscuState: null, checklistState: null, detailId: null, jobs: [],
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
  // The project name does two different things depending on the package. On
  // one that carries a single project there is nothing to switch to, so it
  // opens the project screen if that screen exists at all; on one that
  // carries several it opens the menu.
  $('#project-btn').addEventListener('click', () => {
    if ((state.projects || []).length > 1) chooseProject();
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
