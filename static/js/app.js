// Devreye Alma Paneli — UI start-up and the refresh loops.
//
// Timing rules:
//   · setInterval is never used. Every round is set up with setTimeout AFTER
//     the previous request finished, so a slow device cannot make requests
//     pile up.
//   · Refreshing runs at two speeds and cannot be stopped:
//       – Discovery (full scan) once a minute. It looks at EVERY address in
//         DeviceMap, so it waits one timeout per unreachable device; that is
//         the expensive one. The "Scan now" button pulls that round forward.
//       – The light refresh every few seconds, ONLY for devices that went
//         green in the last round. It never touches an unreachable device,
//         which is what makes it fast.
//   · The light refresh does not run while a full scan is in progress.
//   · No scan is started on its own while an IP assignment / configuration /
//     firmware run is in progress; those runs reboot devices. A scan the user
//     asks for enters the queue and runs after the job.
//   · Every reply carries a generation; a late old reply never overwrites a
//     newer one.

import { $, preserveScroll } from './core/dom.js';
import { api } from './core/api.js';
import { state, patch, subscribe } from './core/store.js';
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

// Runs that WRITE to devices. No scan starts on its own while one is in
// progress (the server-side counterpart: panel.api.presenters.
// WRITING_JOB_KINDS).
const WRITING_JOB_KINDS = new Set(['ip', 'ipfactory', 'config', 'firmware']);

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
    if (state.role) {
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

function writingRunInProgress() {
  return (state.jobs || []).some(
    j => WRITING_JOB_KINDS.has(j.kind)
      && (j.state === 'running' || j.state === 'queued'));
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
    if (!state.role || state.scanRunning || writingRunInProgress()) {
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
    const allowed = state.role && !state.scanRunning
      && !(state.jobs || []).some(j => j.state === 'running');
    if (allowed) {
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
            console.warn('hafif yenileme:', e.message);
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
  if (!state.role) return;

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
  $('#role-badge').textContent =
    state.role === 'admin' ? t('role.admin') : t('role.user');
  $('#role-badge').style.color = state.role === 'admin' ? 'var(--accent)' : '';
  $('#status-text').textContent = queue.summaryText(refreshTargets().length);
  $('#footer-version').textContent = `v${state.version}`;

  const refreshButton = $('#refresh-btn');
  refreshButton.disabled = !!state.scanRunning;
  // Only the visible label changes; the measuring label stays in place to
  // keep the button's width fixed (see index.html).
  $('.label-live', refreshButton).textContent = state.scanRunning
    ? t('topbar.scanning') : t('topbar.scanNow');
  alignSidePanel();

  sidebar.render();
  queue.render();
  locked.render();

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
    playTransition($(selector));
    onViewEntered(state.view);
  }
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
  const running = writingRunInProgress();
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
function alignSidePanel() {
  const button = $('#refresh-btn');
  const body = $('.body');
  if (!button || !body) return;
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

// ───────────────────────────────────────────────────────── role screen ───
async function selectRole(role) {
  patch({ role });
  $('#role-screen').hidden = true;
  $('#app').hidden = false;
  try {
    await loadInitialData();
  } catch (e) {
    showError(e.message);
  }
  jobLoop();
  lightLoop();
  // A session opened with an empty table and the user had to press "Scan
  // tara" for the first data; since refreshing is continuous, the first
  // discovery should run on its own too.
  scanLoop(FIRST_SCAN_DELAY);
  render();
  $('#content').focus();
}

function signOut() {
  // Closing the session resets the UI. The device credentials in memory stay
  // on the server (the application is still open); "Kimlikleri Unut" is on
  // the admin screen. They are all cleared when the application closes.
  clearTimeout(lightTimer);
  clearTimeout(jobTimer);
  clearTimeout(scanTimer);
  detail.close();
  dialog.close();
  patch({
    role: null, view: 'overview', category: 'all', subtype: null,
    detailId: null, queueOpen: false, lockedOpen: false, openJob: null,
    historyFilter: 'all', sidebarOpen: false,
  });
  lastView = null;
  $('#app').hidden = true;
  $('#role-screen').hidden = false;
  $('#admin-form').hidden = true;
  $('#admin-password').value = '';
  $('#role-error').hidden = true;
  $('#role-user').focus();
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
    $('#role-version').textContent = `v${version.version}`;
    $('#footer-version').textContent = `v${version.version}`;
    $('#role-screen').dataset.passwordRequired =
      String(version.adminPasswordRequired);
  } catch {
    showError(t('error.serviceUnreachable'));
  }

  $('#role-user').addEventListener('click', () => selectRole('field'));

  $('#role-admin').addEventListener('click', async () => {
    const required = $('#role-screen').dataset.passwordRequired === 'true';
    if (!required) {
      try { await api.adminLogin(''); } catch { /* opens without a password */ }
      selectRole('admin');
      return;
    }
    $('#admin-form').hidden = false;
    $('#admin-password').focus();
  });

  $('#admin-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const field = $('#admin-password');
    const warning = $('#role-error');
    try {
      await api.adminLogin(field.value);
      field.value = '';                     // the password is not kept in the UI
      warning.hidden = true;
      selectRole('admin');
    } catch (err) {
      field.value = '';
      warning.textContent = err.message || t('role.passwordFailed');
      warning.hidden = false;
      field.focus();
    }
  });

  $('#refresh-btn').addEventListener('click', refreshNow);
  $('#queue-btn').addEventListener('click', queue.toggle);
  $('#locked-btn').addEventListener('click', locked.toggle);
  $('#signout-btn').addEventListener('click', signOut);
  $('#project-btn').addEventListener('click', () => {
    if (state.role === 'admin') patch({ view: 'admin' });
    else notify(t('role.adminOnlyProject'));
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
    if (e.key !== 'Escape') return;
    if (dialog.isOpen()) return;            // the dialog handles its own Escape
    if (state.detailId) { detail.close(); return; }
    if (state.queueOpen || state.lockedOpen) {
      patch({ queueOpen: false, lockedOpen: false });
    }
  });

  // The open screen is refreshed after a credential is verified too: the IP
  // assignment screen locks the run on the switch credential, and the user
  // had to leave and re-enter the page for the summary to update.
  locked.onCredentialsAccepted(() => {
    fetchJobs();
    onViewEntered(state.view);
  });
  subscribe(render);
  $('#role-user').focus();
}

// Stop the running loops as the tab/window closes.
globalThis.addEventListener('pagehide', () => {
  clearTimeout(lightTimer);
  clearTimeout(jobTimer);
  clearTimeout(scanTimer);
});

start();
