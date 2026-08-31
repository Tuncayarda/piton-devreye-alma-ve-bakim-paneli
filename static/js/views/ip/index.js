// The automatic IP assignment screen.
//
// The plan comes from the server (derived from DeviceMap); the browser never
// invents a target of its own. The run writes to the network, so the targets
// and the protected ports are validated both in the UI and on the server
// before it starts.
//
// If the project has several switches, every switch's panel is shown. Because
// the run goes over a single switch, one of them is "active"; clicking a port
// on another switch moves the run to that switch.
//
// The port the computer is plugged into is NEVER TYPED IN: the local network
// interface's MAC address is looked up in the switch's learning table (see
// state.refreshProtected and panel/ip_assign/ports.py). Manual entry opens
// only when the search returns nothing.

import { $, el, fill, focusHeld, preserveScroll } from '../../core/dom.js';
import { api } from '../../core/api.js';
import { latest } from '../../core/latest.js';
import { poll } from '../../core/poll.js';
import { state, patch } from '../../core/store.js';
import * as actionTabs from '../../components/action_tabs.js';
import { confirmWrite } from '../../components/confirm.js';
import { showError, showSuccess, notify } from '../../components/toast.js';
import { emptyState, loadFailed, loading } from '../../components/placeholder.js';
import { value } from '../../core/format.js';
import {
  PROTECTED_INTERVAL, REFRESH_INTERVAL, currentTarget, ipTargets, live,
  local, onScreen, protectedFound,
  refreshProtected, resetProtectedForSet, screen, selectedGroups,
  selectAssignmentSwitch, targetLabel,
} from './state.js';
import { formatPorts, parsePorts, validatePorts } from './ports.js';
import { legend, panelCard, writeFreshness } from './panel.js';
import {
  factoryResetCard, lcdFactoryResetCard, searchOptions,
} from './diagnostics.js';
import { planTable } from './plan_table.js';
import { manualAssignCard } from './manual.js';
import { settingsCard } from './settings_card.js';
import { forgetMaskBoxes, validateRun } from './validation.js';
import {
  deviceMapName, isCompartmentPlan,
} from './software.js';
import { t } from '../../core/i18n.js';

// The container app.js hands to render(). Captured so the screen can redraw
// ITSELF (see draw below) without a round trip through the store.
let root = null;

// Redraws ONLY the panel cards after re-reading them.
async function refreshPanels() {
  const data = state.ipState;
  if (!data || !onScreen()) return;
  const setNo = state.setNo;
  const fresh = await Promise.all((data.plan.switches || []).map(
    entry => api.ipPanel(setNo, entry.id).catch(() => null)));
  const usable = fresh.filter(Boolean);
  if (!usable.length || setNo !== state.setNo || !onScreen()) return;
  // The state object is updated in place: calling `patch` would redraw the
  // whole screen (and drop focus out of the form).
  data.panels = usable;
  drawPanels(data);
}

function drawPanels(data) {
  if (!live.stack) return;
  fill(live.stack, data.panelsLoading
    ? [loading(t('ip.readingSwitchPanel'))]
    : data.panels.length
    ? data.panels.map(panel => panelCard(panel, data.plan, {
      onPortClick: togglePort,
      onCredentials: () => refresh(),
    }))
    : [emptyState(t('ip.noPanelInformation'), '', { tall: true })]);
  writeFreshness();
}

// The three rounds this screen keeps while it is open, as core/poll.js
// handles (setTimeout chained after each round — the house rule — so
// requests cannot pile up). They are armed by the lifecycle below and by
// refresh(), NEVER from render: timers rebuilt on every render never
// elapse, which is exactly the double-timer bug this screen had (neither
// the 5 s panel round nor the 30 s verification round ever ran again).
const panelRound = poll({
  run: async () => {
    try {
      await refreshPanels();
    } catch { /* the "x s ago" indicator already reports staleness */ }
  },
  interval: REFRESH_INTERVAL,
  while: () => onScreen() && live.enabled,
});

const protectedRound = poll({
  run: async () => {
    await refreshProtected();
    // The finding shows as an amber port, in the run summary and in the
    // readiness header, so the whole screen redraws — through the screen's
    // OWN draw, not an identity-swap patch (see state.refreshProtected).
    draw();
  },
  interval: PROTECTED_INTERVAL,
  while: () => onScreen() && live.enabled,
});

// The per-second tick that rewrites "x s ago". Not gated on `live.enabled`:
// while the refresh is paused the age of what is on screen is the one thing
// that must keep counting.
const FRESHNESS_INTERVAL = 1000;
const ticker = poll({
  run: writeFreshness,
  interval: FRESHNESS_INTERVAL,
  while: onScreen,
});

// Write the freshness now and keep the beat — what the tick's callers want
// is never "in one second" (the pause button flips the label immediately).
function freshnessTick() {
  if (!onScreen()) return;
  writeFreshness();
  ticker.arm();
}

function stopRounds() {
  panelRound.stop();
  ticker.stop();
  protectedRound.stop();
}

// An established round is LEFT IN PLACE, not rebuilt — `active()` is asked
// first. Called from refresh() once the first panel read has landed; the
// rounds stop themselves when their `while` goes false (screen left, pause
// pressed), and leave() below stops them the moment the view changes.
function startRefreshing() {
  if (!ticker.active()) freshnessTick();
  if (!live.enabled) return;
  if (!panelRound.active()) panelRound.arm();
  if (!protectedRound.active()) protectedRound.arm();
}

// ── lifecycle ───────────────────────────────────────────────────────────
// Called by app.js from its VIEW_LIFECYCLE table. enter() fetches and arms,
// leave() disarms, render() only draws — the division that keeps a timer
// from ever being armed twice by a redraw.
export function enter() {
  // The freshness tick has no request behind it and starts at once. The two
  // data rounds are armed by refresh() only after the first panel read has
  // landed: armed here, the 5 s round could duplicate the initial read of a
  // slow or unreachable switch that is still in flight.
  freshnessTick();
  refresh();
}

export function leave() {
  // The 5 s panel round, the 1 s freshness tick and the 30 s protected-port
  // verification all stop with the screen. They used to stop themselves one
  // fire later (each round re-checked onScreen); stopping them here means a
  // slow switch is never read again for a screen nobody is looking at.
  stopRounds();
}

// The target type picker. It stays visible even with one option: the user
// should be able to read from the screen which devices IP assignment goes to.
function targetPicker() {
  const active = currentTarget();
  const targets = ipTargets();
  return el('label', { class: 'target-picker' }, [
    el('span', { class: 'label', text: t('groupbar.deviceType') }),
    el('select', {
      class: 'field', 'aria-label': t('ip.deviceTypeToAssignIps'),
      disabled: local.apkPickerOpen,
      onchange: (e) => {
        if (e.target.value === local.targetId) return;
        // A focused list holds the render back (see app.focusInDropdown);
        // the selection is done, so focus leaves the list.
        e.target.blur();
        local.targetId = e.target.value;
        // The port selection belonged to the old target's devices; while the
        // plan is rebuilt it falls back to the default (the new target's
        // ports).
        selectAssignmentSwitch(null);
        // Address discovery and software choices have different meanings for
        // Intercom and Android. Never carry a shared factory address, a .bin
        // preflash option or an APK toggle into the other target's run.
        local.factoryIp = null;
        local.searchOpen = false;
        local.searchNetwork = null;
        local.searchNetmask = null;
        local.searchFirst = null;
        local.searchLast = null;
        local.preflash = false;
        local.targetMask = null;
        local.manualPort = '';
        local.manualIp = '';
        refresh();
      },
    }, targets.map(target => el('option', {
      value: target.id,
      selected: active && target.id === active.id ? true : null,
      text: targetLabel(target),
    }))),
  ]);
}

// `latest` retires an overtaken refresh; the reply is also dropped when the
// TRAIN SET moved underneath it — the plan is derived per set, and a set
// change mid-request must not land the old set's plan (the same rule
// firmware.js follows; the adb and switch screens are set-free on purpose).
export const refresh = latest(async (fresh) => {
  // A fresh plan starts its own initial panel request. Retire the older DATA
  // rounds first so they cannot read the same slow switch in parallel — but
  // only those two: the freshness ticker has no request behind it, and
  // stopping it here silently undid enter()'s "starts at once".
  panelRound.stop();
  protectedRound.stop();
  const setNo = state.setNo;
  const groups = selectedGroups();
  local.errorText = '';
  // The old plan must not mix with the new selection; starting is disabled
  // for the duration of the request.
  patch({ ipState: null });
  try {
    const plan = await api.ipPlan(
      setNo, groups.join(','), local.portText || '', local.switchId || '');
    if (!fresh() || setNo !== state.setNo) return;
    local.errorText = '';
    // Protected-port findings belong to one set. Clear an old set's finding
    // before publishing the new plan so even the first render cannot use it.
    resetProtectedForSet(setNo);
    // The plan is derived from DeviceMap and does not need switch access. Draw
    // it as soon as it arrives; an unreachable switch must not leave the whole
    // page on the loading spinner while its front-panel request times out.
    patch({ ipState: { plan, panels: [], panelsLoading: true } });
    // The search goes to the switches and can take seconds; it starts AFTER
    // the plan is drawn so the screen does not wait for it.
    //
    // A finding that came back EMPTY is retried too. The field sequence is:
    // the app opens, the IP screen is entered while the scan runs, and the
    // switch's MAC table cannot be read because its credentials are not in
    // yet. The user then types the password — `locked.onCredentialsAccepted`
    // refreshes this screen, but "we already have a finding" meant it was
    // never searched again and the port was never found. A successful finding
    // is not renewed; the PROTECTED_INTERVAL round keeps it fresh.
    if (!protectedFound()) refreshProtected().then(() => draw());

    // Each switch's panel comes from its own endpoint; if one cannot be read
    // (no credentials, unreachable) the others are still drawn. This happens
    // after the plan has been published, so only the panel area waits.
    const panels = await Promise.all(
      (plan.switches || []).map(entry => api.ipPanel(setNo, entry.id)
        .catch(() => null)));
    if (!fresh() || setNo !== state.setNo) return;
    patch({
      ipState: { plan, panels: panels.filter(Boolean), panelsLoading: false },
    });
    // The initial panel request has just landed, so the five-second loop can
    // no longer duplicate it — this is the one safe moment to arm the
    // rounds, which is why refresh() owns it and render never did it well.
    startRefreshing();
  } catch (e) {
    if (!fresh() || setNo !== state.setNo) return;
    local.errorText = e.message;
    patch({ ipState: null });
  }
});

// The header: the readiness indicator and the start button, plus the one
// function that keeps them in step.
//
// Fields are validated WITHOUT a redraw (a redraw would move focus out of the
// input on every keystroke), so the header has to be updated by hand. That is
// what `showActionState` is for, and it is the only writer of these nodes.
function runHeader(data, check) {
  const headerState = data
    ? check.ready ? 'ready' : check.error ? 'error' : 'waiting'
    : local.errorText ? 'error' : 'waiting';
  const headerText = data
    ? t(check.ready ? 'ip.planReady'
      : check.error ? 'ip.checkTheSettings' : 'ip.badgeWaiting')
    : t(local.errorText ? 'ip.planUnusable' : 'ip.preparingPlan');
  const readinessText = el('span', { text: headerText });
  const readiness = el('span', {
    class: 'ip-readiness', dataset: { state: headerState },
  }, [el('i', { 'aria-hidden': 'true' }), readinessText]);
  const startButton = el('button', {
    type: 'button', class: 'btn btn-primary ip-start-btn',
    text: t('ip.startIpAssignment'),
    disabled: !data || !check.ready,
    title: check && (check.error || check.waiting)
      ? (check.error || check.waiting) : t('ip.startJobTitle'),
    onclick: start,
  });
  const summaryBadge = data ? el('span', {
    class: check.ready ? 'badge ip-ready-badge'
      : check.error ? 'badge ip-error-badge' : 'badge ip-waiting-badge',
    text: t(check.ready ? 'ip.badgeReady'
      : check.error ? 'ip.badgeNeedsCheck' : 'ip.badgeWaiting'),
  }) : null;
  const runError = data ? el('p', {
    class: 'ip-run-error', role: 'alert', text: check.error,
    hidden: !check.error,
  }) : null;
  // The one error the operator cannot fix on this screen gets a way to the
  // screen that can fix it.
  const networkLink = data && check.networkError ? el('button', {
    type: 'button', class: 'btn btn-small ip-network-link',
    text: t('ip.openNetworkScreen'),
    onclick: () => patch({ view: 'network' }),
  }) : null;

  function showActionState(result, waitingText = '') {
    const waitText = waitingText || result.waiting || '';
    const ready = !!result.ready && !waitText;
    startButton.disabled = !ready;
    startButton.title = result.error || waitText
      || t('ip.startJobTitle');
    readiness.dataset.state = ready ? 'ready'
      : result.error ? 'error' : 'waiting';
    readinessText.textContent = ready
      ? t('ip.planReady')
      : result.error ? t('ip.checkTheSettings') : waitText;
    summaryBadge.className = ready
      ? 'badge ip-ready-badge'
      : result.error ? 'badge ip-error-badge' : 'badge ip-waiting-badge';
    summaryBadge.textContent = ready ? t('ip.badgeReady')
      : t(result.error ? 'ip.badgeNeedsCheck' : 'ip.badgeWaiting');
    runError.textContent = result.error || '';
    runError.hidden = !result.error;
  }

  // The action goes at the FOOT of the form, not the head of the page.
  //
  // The form runs long — switch, ports, addressing, mask, set transfer, APK —
  // and the button used to sit above all of it. Filling in the last field
  // meant scrolling back up to press it, and the readiness line that explains
  // why the button is disabled was up there with it, out of sight of the
  // field that had caused it.
  const actionBar = el('div', { class: 'ip-action-bar' }, [
    readiness, startButton,
  ]);

  return { actionBar, summaryBadge, runError, networkLink,
           showActionState };
}

// The physical switch is deliberately independent of the DeviceMap switch
// that supplied the device/IP mapping. This is useful on a test bench (and
// when a train is temporarily patched through another switch). The backend
// remains the authority for how the chosen switch changes the plan.
function switchArea(plan) {
  const switches = plan.switches || [];
  return el('fieldset', { class: 'ip-form-section ip-switch-picker-area' }, [
    el('legend', { class: 'visually-hidden', text: t('ip.assignmentSwitch') }),
    el('label', {
      class: 'label', for: 'ip-assignment-switch',
      text: t('ip.assignmentSwitch'),
    }),
    el('select', {
      id: 'ip-assignment-switch', class: 'field',
      'aria-label': t('ip.assignmentSwitch'),
      disabled: !switches.length || local.apkPickerOpen,
      onchange: (event) => {
        if (event.target.value === plan.switchId) return;
        event.target.blur();
        selectAssignmentSwitch(event.target.value);
        refresh();
      },
    }, switches.map(entry => el('option', {
      value: entry.id,
      selected: entry.id === plan.switchId ? true : null,
      // Both values come straight from DeviceMap; never translate either.
      text: [entry.name, entry.ip].filter(Boolean).join(' · '),
    }))),
  ]);
}

// The target ports: typed as text ("11-14, 18-19, 21") rather than picked,
// because in the field the ports come off a wiring list.
function portArea(data, check, showActionState) {
  const { plan } = data;
  const { allowed, portText, selectedPorts } = check;
  const portWarning = el('p', {
    id: 'port-warning', class: 'warning', text: check.portError,
    role: 'alert', hidden: !check.portError,
  });
  const portInput = el('input', {
    id: 'ip-ports', class: 'field', value: portText,
    'aria-invalid': String(!!check.portError),
    'aria-describedby': 'port-warning',
    autocomplete: 'off', spellcheck: 'false',
    // While typing only the warning is shown; the screen is not redrawn, or
    // focus would leave the field on every keystroke.
    oninput: (e) => {
      const parsed = parsePorts(e.target.value, allowed);
      const message = validatePorts(e.target.value, allowed, plan)
        || (!parsed.ports.length ? t('ip.selectTargetPort') : '');
      e.target.setAttribute('aria-invalid', String(!!message));
      portWarning.textContent = message;
      portWarning.hidden = !message;
      showActionState({ ready: false, error: message },
                      message ? '' : t('ip.updateThePlan'));
    },
    onchange: (e) => {
      const { ports, error } = parsePorts(e.target.value, allowed);
      if (error || !ports.length
          || validatePorts(e.target.value, allowed, plan)) return;
      local.portText = formatPorts(ports);
      refresh();
    },
  });

  return el('fieldset', { class: 'ip-form-section ip-port-area' }, [
    el('legend', { class: 'visually-hidden', text: t('ip.targetPorts') }),
    el('div', { class: 'ip-field-head' }, [
      el('label', { class: 'label', for: 'ip-ports', text: t('ip.targetPorts') }),
      el('span', {
        class: 'ip-field-count',
        text: t('ip.portsSelected', { count: selectedPorts }),
      }),
    ]),
    portInput,
    portWarning,
  ]);
}

// The mask written WITH the new address, as opposed to the one searched.
// Every target has it: a display may need a /8 while the intercoms beside it
// stay /24.
//
// The SAME setting appears on two cards — the group run and the single-port
// run below it — because the person doing a single port should not have to
// scroll to another card to see what mask it will get. It is one value, so
// the boxes are kept in step by hand: neither card redraws on a keystroke
// (that would take focus out of the box), which is why the live instances
// are listed rather than re-rendered.

// One front panel per switch, plus the pause control for their live refresh.
function panelSection(panels) {
  const panelStack = el('div', { class: 'panel-stack' });
  live.stack = panelStack;

  const refreshButton = el('button', {
    type: 'button', class: 'btn btn-small ip-refresh-btn',
    'aria-pressed': String(live.enabled),
    title: t(live.enabled ? 'ip.pauseRefresh' : 'ip.resumeRefresh'),
    onclick: (e) => {
      live.enabled = !live.enabled;
      e.currentTarget.setAttribute('aria-pressed', String(live.enabled));
      e.currentTarget.textContent = t(live.enabled ? 'ip.refreshOn'
        : 'ip.refreshPaused');
      stopRounds();
      freshnessTick();
      if (live.enabled) {
        panelRound.now();               // read once as soon as it resumes
        protectedRound.now();           // re-verify the protected ports too
      }
    },
    text: t(live.enabled ? 'ip.refreshOn' : 'ip.refreshPaused'),
  });

  return el('details', {
    class: 'ip-panel-area ip-collapsible',
    open: local.openSections.panels,
    ontoggle: (e) => { local.openSections.panels = e.currentTarget.open; },
  }, [
    el('summary', { class: 'ip-section-head ip-collapsible-summary' }, [
      el('div', { class: 'ip-section-title' }, [
        el('div', {}, [
          el('h3', { text: t('ip.switchAndPorts') }),
        ]),
      ]),
      el('span', {
        class: 'ip-section-count',
        text: t('ip.panelCount', { count: panels.length }),
      }),
    ]),
    el('div', { class: 'ip-section-action ip-panel-tools' }, [refreshButton]),
    panelStack,
    panels.length ? legend() : null,
  ]);
}

// DRAWING ONLY. app.js calls this on every store publish — the job queue
// alone republishes once a second — so nothing here fetches and nothing
// here arms a timer: the data comes from refresh() (called by enter() when
// the screen opens) and the rounds are armed there too. (Same division as
// the switch and adb screens; the note above the poll handles records what
// arming timers from render cost this screen.)
export function render(container) {
  root = container;
  // The sub-modules' repaint hook — see state.screen.
  screen.draw = draw;
  paint();
}

// The screen redrawing ITSELF, for changes only it can see (the
// protected-port finding lives in `local`, not in the store). The guards
// are the ones app.js applies before ITS renders, or this path would lose
// the protection those have: never over a box being typed in, and the
// scroll position survives.
function draw() {
  if (!root || state.view !== 'ip' || !state.meta) return;
  if (focusHeld(root)) return;
  preserveScroll($('#content'), paint);
}

function paint() {
  forgetMaskBoxes();
  const data = state.ipState;
  const check = data ? validateRun(data) : null;
  const header = runHeader(data, check);
  const parts = [actionTabs.render([targetPicker()])];
  if (header.runError) parts.push(header.runError);
  if (header.networkLink) parts.push(header.networkLink);

  if (!data) {
    // Two different facts, and they were one shape with a swapped class:
    // the plan is still being worked out, or working it out failed.
    parts.push(local.errorText
      ? loadFailed(local.errorText)
      : loading(t('ip.preparingPlanLong')));
    fill(root, parts);
    return;
  }

  const { plan, panels } = data;
  parts.push(el('div', { class: 'ip-grid' }, [
    settingsCard(data, check, header, { switchArea, portArea }),
    panelSection(panels),
  ]));
  // The panels are filled in only once the stack node exists (panelSection
  // publishes it as live.stack). Their refresh loop is NOT started here:
  // refresh() arms it when the initial panel request lands, so a slow
  // switch's in-flight read can never be duplicated by the 5 s round.
  drawPanels(data);

  if (plan.factoryResetSupported === true) {
    parts.push(plan.factoryResetKind === 'perDevice'
      ? lcdFactoryResetCard(data, check) : factoryResetCard(data, check));
  }
  if (plan.manualAssignSupported === true) {
    parts.push(manualAssignCard(data, check));
  }
  parts.push(planTable(plan, check));

  fill(root, parts);
}

function togglePort(number, context) {
  const plan = state.ipState && state.ipState.plan;
  if (!plan) return;
  // Clicking a port on another switch moves the run to that switch; the
  // selection there starts with that port.
  if (!context.active) {
    selectAssignmentSwitch(context.switchId);
    local.portText = String(number);
    refresh();
    return;
  }
  const selected = new Set(
    plan.rows.filter(row => row.actionable).map(row => row.port));
  if (selected.has(number)) selected.delete(number);
  else selected.add(number);
  local.portText = formatPorts([...selected]);
  refresh();
}

// The heaviest operation in the panel: PoE goes off port by port, every
// selected device is rewritten, and a display or intercom is dark while its
// port is worked on. It used to fire on one click.
function start() {
  const data = state.ipState;
  const plan = data && data.plan;
  if (!plan) return;
  const check = validateRun(data);
  if (!check.ready) {
    showError(check.error);
    return;
  }
  const rows = (plan.rows || []).filter(row => row.actionable);
  confirmWrite({
    title: t('ip.startIpAssignment'),
    lead: t('confirm.ipRunLead', {
      count: check.inPlan, switch: value(plan.switch),
      ports: check.portText,
    }),
    items: rows.map(row => ({
      name: deviceMapName(row) || `${t('ip.lcdManualPort')} ${row.port}`,
      detail: row.targetIp || '',
    })),
    confirmLabel: t('ip.startIpAssignment'),
    run: () => startRun(plan, check),
  });
}

// The run itself. Errors travel out to `confirmWrite`, which reports them.
async function startRun(plan, check) {
  const body = {
    set: state.setNo,
    switch: plan.switchId,
    groups: plan.groups || [],
    ports: local.portText ?? plan.portText,
    // The server finds the protected ports ITSELF when the run starts; this
    // list is only the last known information should the switch not answer
    // at that moment.
    protected: (local.protected && local.protected.ports) || [],
    // The mask written with the new address; empty means the /24 default.
    targetMask: local.targetMask || '',
  };
  if (isCompartmentPlan(plan)) {
    // File paths stay in the server-side firmware selection store. The run
    // only needs to know whether the prepared APK step was requested.
    body.installApk = !!local.installApk;
  } else {
    Object.assign(body, {
      factoryIp: check.factoryIp,
      ...searchOptions(plan),
      // The file itself is not sent: the server holds the path the user
      // picked in the OS dialog (see panel/ip_assign/preflash.py).
      preflash: !!local.preflash,
    });
  }
  const job = await api.ipRun(body);
  patch({ queueOpen: true, openJob: job.id });
  if (job.new === false) {
    notify(t('ip.anIpAssignmentJobIs'));
  } else {
    showSuccess(t('ip.theIpAssignmentJobWas'));
  }
}
