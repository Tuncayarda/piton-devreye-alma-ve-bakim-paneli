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
import { ownProjects, state, patch, subscribe } from './core/store.js';
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
import * as switchView from './views/switch/index.js';
import * as configView from './views/config.js';
import * as firmwareView from './views/firmware.js';
import * as checklistView from './views/checklist.js';
import * as historyView from './views/history.js';
import * as piscuView from './views/piscu.js';
import * as mqttView from './views/mqtt.js';
import * as adminView from './views/admin.js';
import { createRemoteSession } from './components/remote_session.js';
import { createAdminKey } from './components/admin_key.js';

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
      } catch (error) {
        // The job is gone — removed, or the service restarted and forgot
        // the id. A real status (a 404) means the id can never answer
        // again, and keeping it would cost a doomed second request every
        // round for the rest of the session. Status 0 is the service being
        // unreachable and is left alone: the next round retries.
        if (error && error.status) patch({ openJob: null });
      }
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

// The per-view lifecycle, in one table.
//
// `enter` runs when a screen is OPENED: it fetches the screen's own data
// (not everything is fetched at start-up) and arms whatever timers that
// screen keeps. `leave` runs when it is LEFT: polls disarmed, menus closed,
// half-typed credentials dropped. Between the two, `render` stays DRAWING
// ONLY — app.js calls it on every store publish, and a screen that fetched
// or armed timers inside render paid for it twice already: a request per
// publish (the switch screen's note), and timers rebuilt every round so
// none ever elapsed (the IP screen's double-timer bug). The IP screen was
// the last one still arming its rounds from render; its enter()/leave()
// now carry them (views/ip/index.js).
//
// A screen with no entry needs nothing fetched and nothing stopped
// (overview, devices, history, admin all draw from state already loaded).
const VIEW_LIFECYCLE = {
  ip: { enter: () => ipView.enter(), leave: () => ipView.leave() },
  adb: { enter: () => adbView.refresh(), leave: () => adbView.stop() },
  switch: { enter: () => switchView.refresh(), leave: () => switchView.stop() },
  checklist: { enter: () => checklistView.refresh() },
  network: { enter: () => networkView.refresh() },
  config: { enter: () => configView.refresh() },
  firmware: { enter: () => firmwareView.refresh() },
  piscu: { enter: () => piscuView.refresh() },
  mqtt: { enter: () => mqttView.refresh() },
};

function enterView(name) {
  const hooks = VIEW_LIFECYCLE[name];
  if (hooks && hooks.enter) hooks.enter();
}

function leaveView(name) {
  const hooks = VIEW_LIFECYCLE[name];
  if (hooks && hooks.leave) hooks.leave();
}

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
  // The two side panels skip identical redraws by signature, and the
  // signature knows nothing about language: with a panel open, the old
  // catalogue's rows passed the comparison and stayed untranslated.
  queue.reset();
  locked.reset();
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
  // The outgoing screen is torn down before the incoming one draws. Not on
  // a redrawEverything (lastView is null then): the screen is not being
  // left, and stopping its poll would leave a running sweep unfollowed.
  if (viewChanged && lastView) leaveView(lastView);

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
    enterView(state.view);
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
    // Only the flag. The queue panel is not opened (see above), so the job
    // is not marked open either: an `openJob` set here was never cleared
    // when the scan ended, and every later poll round paid for a second
    // /api/job request against it for the rest of the session.
    patch({ scanRunning: true });
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
    enterView(state.view);
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

// The two components that own the ways into admin mode. Factories rather
// than plain modules so their dialogs and polls can be driven by import in
// the tests (tests/js/remote_pair_test.js, tests/js/admin_key_test.js):
// everything they need defaults to the real thing, and what app.js alone
// owns is passed in — `applyEdition` above, and the remote-session poll
// ridden on the service key's beat.
const remoteSession = createRemoteSession({ applyEdition });
const adminKey = createAdminKey({
  applyEdition,
  pollRemote: remoteSession.pollRemote,
});

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
//
// The filter itself is `ownProjects` in core/store.js: a selector over
// state, importable by its test — nothing in this self-starting file can be.

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
    enterView(state.view);
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
  $('#leave-admin-btn').addEventListener('click', adminKey.leaveAdmin);
  $('#enter-admin-btn').addEventListener('click', adminKey.enterAdmin);
  $('#remote-admin-btn').addEventListener('click',
    remoteSession.askForRemoteSession);
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
    enterView(state.view);
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
  adminKey.start();
  render();
  $('#content').focus();

  await adminKey.checkAtLaunch();
}

// Stop the running loops as the tab/window closes.
globalThis.addEventListener('pagehide', () => {
  clearTimeout(lightTimer);
  clearTimeout(jobTimer);
  clearTimeout(scanTimer);
  adminKey.stop();
});

start();
