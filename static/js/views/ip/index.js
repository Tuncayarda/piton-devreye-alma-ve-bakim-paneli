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

import { el, fill } from '../../core/dom.js';
import { api } from '../../core/api.js';
import { state, patch } from '../../core/store.js';
import * as actionTabs from '../../components/action_tabs.js';
import { confirmWrite } from '../../components/confirm.js';
import { showError, showSuccess, notify } from '../../components/toast.js';
import { fileSize, value } from '../../core/format.js';
import {
  IP_TARGETS, LCD_GROUP, PROTECTED_INTERVAL, REFRESH_INTERVAL, currentTarget, live,
  local, onScreen, protectedFound, protectedPortsFor, protectedWaitText,
  refreshProtected, resetProtectedForSet, selectedGroups,
  stopPanels, selectAssignmentSwitch, targetLabel,
} from './state.js';
import {
  SEARCH_LIMIT, activePanelError, formatPorts, isIpv4, parsePorts,
  validateSearch, validateTargetMask,
} from './ports.js';
import { legend, panelCard, writeFreshness } from './panel.js';
import {
  confirmFactoryReset, confirmLcdFactoryReset, searchOptions,
} from './diagnostics.js';
import { planTable } from './plan_table.js';
import {
  deviceMapName, isCompartmentPlan, mergedSoftware, missingSoftwareRows,
  softwareDeviceIds, softwareFiles, softwareRows, usesPhysicalPortDiscovery,
} from './software.js';
import { t } from '../../core/i18n.js';

let refreshToken = 0;

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
    ? [el('div', { class: 'info ip-panel-empty', role: 'status' }, [
        el('span', { text: t('ip.readingSwitchPanel') }),
      ])]
    : data.panels.length
    ? data.panels.map(panel => panelCard(panel, data.plan, {
      onPortClick: togglePort,
      onCredentials: () => refresh(),
    }))
    : [el('div', { class: 'ip-panel-empty' }, [
        el('span', { class: 'eyebrow', text: t('ip.noPanelInformation') }),
        el('p', { text: t('ip.theSwitchFrontPanelCannot') }),
      ])]);
  writeFreshness();
}

// The rounds are chained with setTimeout: if a read takes long, the next
// round does not start before it and requests cannot pile up.
function freshnessTick() {
  clearTimeout(live.ticker);
  live.ticker = null;
  if (!onScreen()) return;
  writeFreshness();
  live.ticker = setTimeout(freshnessTick, 1000);
}

async function refreshRound() {
  clearTimeout(live.timer);
  live.timer = null;
  if (!onScreen() || !live.enabled) return;
  try {
    await refreshPanels();
  } catch { /* the "x s ago" indicator already reports staleness */ }
  if (!onScreen() || !live.enabled) return;
  live.timer = setTimeout(refreshRound, REFRESH_INTERVAL);
}

async function protectedRound() {
  clearTimeout(live.protectedTimer);
  live.protectedTimer = null;
  if (!onScreen() || !live.enabled) return;
  try {
    await refreshProtected();
  } catch { /* retried on the next round */ }
  if (!onScreen() || !live.enabled) return;
  live.protectedTimer = setTimeout(protectedRound, PROTECTED_INTERVAL);
}

// An established round is LEFT IN PLACE, not rebuilt.
//
// `render` runs on every device refresh — the light refresh redraws the whole
// screen every few seconds. Tearing the timers down and rebuilding them on
// every render meant none of them ever elapsed: neither the 5 s panel round
// nor the 30 s verification round ever ran again. The rounds stop themselves
// on leaving the screen (see onScreen), so there is nothing to stop here.
function startRefreshing() {
  if (!live.ticker) freshnessTick();
  if (!live.enabled) return;
  if (!live.timer) live.timer = setTimeout(refreshRound, REFRESH_INTERVAL);
  if (!live.protectedTimer) {
    live.protectedTimer = setTimeout(protectedRound, PROTECTED_INTERVAL);
  }
}

// The target type picker. It stays visible even with one option: the user
// should be able to read from the screen which devices IP assignment goes to.
function targetPicker() {
  const active = currentTarget();
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
    }, IP_TARGETS.map(target => el('option', {
      value: target.id,
      selected: target.id === active.id ? true : null,
      text: targetLabel(target),
    }))),
  ]);
}

// The single source of validity for every setting on the screen. The status
// text at the top, the start button and the field warnings all use this
// result.
function validateRun(data) {
  const { plan, panels = [] } = data;
  const allowed = plan.allowedPorts || [];
  const rows = plan.rows || [];
  const portText = local.portText ?? formatPorts(
    rows.filter(row => row.actionable).map(row => row.port));
  const parsed = parsePorts(portText, allowed);
  const selectedPorts = parsed.ports.length;
  const inPlan = rows.filter(row => row.actionable).length;
  const outOfPlan = rows.length - inPlan;
  const panelById = new Map(panels.map(panel => [panel.switchId, panel]));
  // The run does not start before the protected ports are known: switching
  // PoE off without knowing which port carries our own link risks cutting our
  // own path. While the search runs this is not an "error" but a wait.
  const protectedText = protectedWaitText();
  const protectedPending = !local.protected;
  const protectedWait = protectedPending ? protectedText : '';
  const protectedError = protectedPending ? '' : protectedText;
  const portError = parsed.error || validatePorts(portText, allowed, plan);
  const target = currentTarget();
  const scopeError = !selectedPorts
    ? t('ip.selectTargetPort')
    : !inPlan ? t('ip.noTargetOnPorts', { target: targetLabel(target) }) : '';
  // The run connects to the switch with a username/password. Without one the
  // job entered the queue and fell over at the first step; saying so before
  // it starts is better.
  const activePanel = panelById.get(plan.switchId);
  const panelWait = data.panelsLoading ? t('ip.readingSwitchPanel') : '';
  const plannedSwitch = (plan.switches || []).find(
    entry => entry.id === plan.switchId);
  const credentialError = activePanelError(
    activePanel, plannedSwitch, data.panelsLoading);
  const groupError = target.groups.some(
    group => !(plan.groups || []).includes(group))
    ? t('ip.noTargetFound', { target: targetLabel(target) }) : '';
  const sharedSource = plan.sourceMode !== 'perDevice';
  const factoryIp = sharedSource ? (local.factoryIp ?? plan.factoryIp ?? '') : '';
  const factoryError = sharedSource && !isIpv4(factoryIp)
    ? t('ip.factoryIpInvalid') : '';
  const searchError = sharedSource && local.searchOpen
    ? validateSearch(local.searchNetwork ?? plan.searchNetwork,
                     local.searchNetmask ?? plan.searchNetmask,
                     local.searchFirst, local.searchLast)
    : '';
  const maskError = validateTargetMask(
    local.targetMask ?? '', plan.minTargetPrefix, plan.maxTargetPrefix);
  // The computer's own reach. A run cannot find a device it has no route to,
  // and the devices are on TWO networks at once here: the factory 10.1.1.x
  // they arrive on and the open set's. Missing networks are not a problem —
  // the run adds them itself before its first port. Not knowing WHICH
  // adapter to add them to is: nothing gets added and every port fails.
  const net = plan.network || {};
  const networkError = net.needsAdapter
    ? t('ip.networkNoAdapter')
    : (net.supported === false ? t('ip.networkUnsupported') : '');
  const software = plan.software || {};
  const apkMissing = local.installApk && isCompartmentPlan(plan)
    ? missingSoftwareRows(plan) : [];
  const apkUnsupported = local.installApk && isCompartmentPlan(plan)
    && (software.supported !== true || software.extension !== 'apk');
  const apkError = apkUnsupported ? t('ip.apkUnsupported')
    : apkMissing.length ? t('ip.apkMissingCount', { count: apkMissing.length })
    : '';
  const error = groupError || networkError || factoryError || maskError
    || searchError
    || apkError || protectedError || portError || scopeError || credentialError;
  return {
    groupError,
    factoryIp,
    factoryError,
    maskError,
    networkError,
    searchError,
    apkError,
    apkMissing,
    credentialError,
    waiting: panelWait || protectedWait,
    protectedError,
    allowed,
    portText,
    selectedPorts,
    inPlan,
    outOfPlan,
    panelById,
    portError: portError || (!selectedPorts ? scopeError : ''),
    error,
    ready: !error && !panelWait && !protectedWait,
  };
}

// The single validation point for the text in the field: format + defined on
// this switch + the ports the run must not touch. Returns the error text, or
// '' when there is none.
function validatePorts(text, allowed, plan) {
  const { ports, error } = parsePorts(text, allowed);
  if (error) return error;
  const protectedPorts = new Map(protectedPortsFor(plan));
  const clashing = ports.filter(port => protectedPorts.has(port));
  if (clashing.length) {
    const port = clashing[0];
    return t('ip.portProtected', {
      port, reason: protectedPorts.get(port),
    });
  }
  return '';
}

export async function refresh() {
  // A fresh plan starts its own initial panel request. Retire any older live
  // rounds first so they cannot read the same slow switch in parallel.
  stopPanels();
  const token = ++refreshToken;
  const setNo = state.setNo;
  const groups = selectedGroups();
  local.errorText = '';
  // The old plan must not mix with the new selection; starting is disabled
  // for the duration of the request.
  patch({ ipState: null });
  try {
    const plan = await api.ipPlan(
      setNo, groups.join(','), local.portText || '', local.switchId || '');
    if (token !== refreshToken || setNo !== state.setNo) return;
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
    if (!protectedFound()) refreshProtected();

    // Each switch's panel comes from its own endpoint; if one cannot be read
    // (no credentials, unreachable) the others are still drawn. This happens
    // after the plan has been published, so only the panel area waits.
    const panels = await Promise.all(
      (plan.switches || []).map(entry => api.ipPanel(setNo, entry.id)
        .catch(() => null)));
    if (token !== refreshToken || setNo !== state.setNo) return;
    patch({
      ipState: { plan, panels: panels.filter(Boolean), panelsLoading: false },
    });
  } catch (e) {
    if (token !== refreshToken || setNo !== state.setNo) return;
    local.errorText = e.message;
    patch({ ipState: null });
  }
}

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

  const bar = el('div', { class: 'page-head ip-page-head' }, [
    // The heading is the same on all three operation screens: the tab bar
    // below already says which screen this is.
    el('h2', { text: t('nav.operations') }),
  ]);

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

  return { bar, actionBar, summaryBadge, runError, networkLink,
           showActionState };
}

function showFieldWarning(input, warning, message) {
  input.setAttribute('aria-invalid', String(!!message));
  warning.textContent = message;
  warning.hidden = !message;
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
    el('p', { class: 'ip-field-help', text: t('ip.assignmentSwitchHelp') }),
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
    el('p', {
      class: 'ip-field-help',
      text: t('ip.rangesAndSinglePortsCan'),
    }),
  ]);
}

function optionToggle(pressed, label, title, onToggle, disabled = false) {
  return el('button', {
    type: 'button', class: 'checkbox', 'aria-pressed': String(pressed),
    title: title || null, disabled,
    onclick: () => {
      if (disabled) return;
      onToggle();
      patch({ ipState: { ...state.ipState } });
    },
  }, [
    el('span', { class: 'box', 'aria-hidden': 'true' }),
    el('span', { text: label }),
  ]);
}

function currentPlanIs(plan, setNo) {
  return state.setNo === setNo
    && !!state.ipState && state.ipState.plan === plan
    && isCompartmentPlan(plan);
}

function applySoftwareReply(plan, reply) {
  plan.software = mergedSoftware(plan, reply);
  patch({ ipState: { ...state.ipState } });
}

async function pickApk(plan) {
  const ids = softwareDeviceIds(plan);
  if (!ids.length || local.apkPickerOpen) return;
  const setNo = state.setNo;
  local.apkPickerOpen = true;
  patch({ ipState: { ...state.ipState } });
  try {
    const reply = await api.firmwarePick(setNo, LCD_GROUP, ids);
    if (!currentPlanIs(plan, setNo)) return;
    if (!reply.cancelled) {
      applySoftwareReply(plan, reply);
      showSuccess(t('firmware.fileSelectedFor', { count: ids.length }));
    }
  } catch (error) {
    showError(error.message);
  } finally {
    local.apkPickerOpen = false;
    if (state.view === 'ip' && state.ipState) {
      patch({ ipState: { ...state.ipState } });
    }
  }
}

async function removeApks(plan) {
  const ids = softwareDeviceIds(plan);
  if (!ids.length || local.apkPickerOpen) return;
  const setNo = state.setNo;
  try {
    const reply = await api.firmwareRemove(setNo, LCD_GROUP, ids);
    if (currentPlanIs(plan, setNo)) applySoftwareReply(plan, reply);
  } catch (error) {
    showError(error.message);
  }
}

function apkFields(plan, check) {
  const rows = softwareRows(plan);
  const files = softwareFiles(plan);
  const ready = rows.filter(row => files[row.deviceId]
    && files[row.deviceId].selected).length;
  const supported = !!(plan.software && plan.software.supported
    && plan.software.extension === 'apk');

  return el('div', { class: 'ip-apk-block' }, [
    el('div', { class: 'ip-apk-head' }, [
      el('span', { class: 'label', text: t('ip.apkFiles') }),
      el('span', {
        class: ready === rows.length && rows.length
          ? 'badge ip-ready-badge' : 'badge',
        text: t('ip.apkReadyCount', { ready, count: rows.length }),
      }),
    ]),
    el('div', { class: 'ip-apk-controls' }, [
      el('div', { class: 'ip-apk-actions' }, [
        el('button', {
          type: 'button', class: 'btn btn-small btn-primary',
          text: local.apkPickerOpen ? t('firmware.selectingFile')
            : t('ip.selectApkFor', { count: rows.length }),
          title: `${t('firmware.yourComputersFileDialogOpens')} (.apk)`,
          disabled: !supported || !rows.length || local.apkPickerOpen,
          onclick: () => pickApk(plan),
        }),
        el('button', {
          type: 'button', class: 'btn btn-small',
          text: t('firmware.clearTheSelections'),
          disabled: !ready || local.apkPickerOpen,
          onclick: () => removeApks(plan),
        }),
      ]),
    ]),
    el('div', { class: 'ip-apk-list' }, rows.map(row => {
      const file = files[row.deviceId] || { selected: false };
      return el('div', {
        class: 'ip-apk-row', dataset: { selected: file.selected ? '1' : '0' },
      }, [
        el('span', { class: 'mono truncate', text: deviceMapName(row) }),
        el('span', {
          class: file.selected ? 'mono truncate' : 'mono truncate text-dim',
          title: file.name || t('firmware.noFileSelectedYet'),
          text: file.selected ? file.name : t('firmware.noFileSelected'),
        }),
        el('span', {
          class: file.selected ? 'text-mid' : 'text-dim',
          text: file.selected
            ? t('firmware.readyToInstall', { size: fileSize(file.size) }) : '—',
        }),
      ]);
    })),
    check.apkError ? el('p', {
      class: 'ip-field-error ip-apk-error', role: 'alert',
      text: check.apkError,
    }) : null,
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
const maskBoxes = [];
const maskWatchers = [];

// Called at the start of every render: the nodes from the previous one are
// detached and writing to them would be writing to nothing.
function forgetMaskBoxes() {
  maskBoxes.length = 0;
  maskWatchers.length = 0;
}

function maskField(data, check, showActionState, prefix = 'ip-target-mask') {
  const { plan } = data;
  const defaultMask = plan.targetNetmask || '255.255.255.0';
  const maskWarning = el('p', {
    id: `${prefix}-error`, class: 'ip-field-error', role: 'alert',
    text: check.maskError, hidden: !check.maskError,
  });
  // The box carries the mask that WILL be written, not a ghost of it. An
  // empty box still means "the plan's default" — the value shown is that
  // default, so the two say the same thing.
  const input = el('input', {
    id: prefix, class: 'field ip-medium-field',
    value: local.targetMask ?? defaultMask,
    autocomplete: 'off', spellcheck: 'false',
    'aria-invalid': String(!!check.maskError),
    'aria-describedby': `${prefix}-error`,
    oninput: (event) => {
      local.targetMask = event.target.value.trim();
      const result = validateRun(data);
      // Every copy of the box, and every copy of its warning: one bad mask
      // must not read as valid on the card the user is not looking at.
      for (const box of maskBoxes) {
        if (box.input !== event.target) box.input.value = event.target.value;
        showFieldWarning(box.input, box.warning, result.maskError);
      }
      showActionState(result);
      for (const watch of maskWatchers) watch(result);
    },
  });
  maskBoxes.push({ input, warning: maskWarning });
  return [
    el('label', { class: 'setting-row', for: prefix }, [
      el('span', { class: 'label', text: t('ip.targetMask') }),
      input,
    ]),
    maskWarning,
    el('p', {
      class: 'ip-field-help', text: t('ip.targetMaskHelp', { mask: defaultMask }),
    }),
  ];
}


function lcdAddressingArea(data, check, showActionState) {
  const { plan } = data;
  const sources = softwareRows(plan)
    .map(row => row.sourceIp || row.factoryIp || '')
    .filter(Boolean);
  const sourceRange = !sources.length ? '—'
    : sources.length === 1 ? sources[0]
    : `${sources[0]} – ${sources[sources.length - 1]}`;

  return el('fieldset', { class: 'setting-section ip-lcd-settings' }, [
    el('legend', { class: 'visually-hidden', text: t('ip.lcdAddressing') }),
    el('div', { class: 'ip-sub-head' }, [
      el('span', { class: 'eyebrow', text: t('ip.lcdAddressing') }),
    ]),
    el('div', { class: 'ip-lcd-source' }, [
      el('div', { class: 'row' }, [
        el('span', { text: t('ip.lcdSourceRange') }),
        el('b', { class: 'mono', text: sourceRange }),
      ]),
      el('p', {
        class: 'ip-field-help',
        text: t(usesPhysicalPortDiscovery(plan)
          ? 'ip.lcdPhysicalSourcePolicy' : 'ip.lcdSourcePolicy'),
      }),
    ]),
    ...maskField(data, check, showActionState),
    optionToggle(
      local.installApk, t('ip.installApkBeforeAssignment'),
      t('ip.installApkNote'),
      () => { local.installApk = !local.installApk; },
      !(plan.software && plan.software.supported)),
    ...(local.installApk ? [apkFields(plan, check)] : []),
  ]);
}

// Factory IP: the address the devices come out of the box on (in the field
// they all show at the same address — five devices at 10.1.1.12 in arp-scan).
// Search network: the addresses to scan for devices configured earlier, i.e.
// not on the factory address.
// The two fields behind "install software before assigning".
//
// The file is chosen in the OPERATING SYSTEM'S dialog and stays on the server;
// the browser never sees or sends a path. Only its name comes back, which is
// all the screen has to show. Same rule as the job log files.
function preflashFields(plan) {
  const file = (plan && plan.preflashFile) || { name: '' };
  return [
    el('div', { class: 'setting-row' }, [
      el('span', { class: 'label', text: t('ip.preflashFile') }),
      el('span', { class: 'ip-preflash-file' }, [
        el('span', {
          class: file.name ? 'mono' : 'text-dim',
          text: file.name || t('ip.preflashNoFile'),
        }),
        el('button', {
          type: 'button', class: 'btn btn-small',
          text: t('ip.preflashPick'),
          onclick: async () => {
            try {
              const answer = await api.ipPreflashFile();
              if (answer.cancelled) return;
              plan.preflashFile = answer.preflashFile;
              patch({ ipState: { ...state.ipState } });
            } catch (e) { showError(e.message); }
          },
        }),
        file.name && el('button', {
          type: 'button', class: 'btn btn-small',
          text: t('net.releaseOne'),
          onclick: async () => {
            try {
              const answer = await api.ipPreflashFile(true);
              plan.preflashFile = answer.preflashFile;
              patch({ ipState: { ...state.ipState } });
            } catch (e) { showError(e.message); }
          },
        }),
      ]),
    ]),
  ];
}

function addressingArea(data, check, showActionState) {
  const { plan } = data;
  if (isCompartmentPlan(plan)) {
    return lcdAddressingArea(data, check, showActionState);
  }

  const factoryWarning = el('p', {
    id: 'ip-factory-error', class: 'ip-field-error', role: 'alert',
    text: check.factoryError, hidden: !check.factoryError,
  });
  const factoryInput = el('input', {
    id: 'ip-factory', class: 'field', value: check.factoryIp,
    autocomplete: 'off', spellcheck: 'false', inputmode: 'numeric',
    'aria-invalid': String(!!check.factoryError),
    'aria-describedby': 'ip-factory-error',
    oninput: (e) => {
      local.factoryIp = e.target.value.trim();
      const result = validateRun(data);
      showFieldWarning(e.target, factoryWarning, result.factoryError);
      showActionState(result);
    },
  });

  const searchWarning = el('p', {
    id: 'ip-search-error', class: 'ip-field-error', role: 'alert',
    text: check.searchError, hidden: !check.searchError,
  });
  const searchField = (key, id, label, fallback) => el('label', {
    class: 'setting-row', for: id,
  }, [
    el('span', { class: 'label', text: label }),
    el('input', {
      id, class: 'field ip-medium-field',
      value: local[key] ?? fallback ?? '',
      autocomplete: 'off', spellcheck: 'false',
      'aria-describedby': 'ip-search-error',
      oninput: (e) => {
        local[key] = e.target.value.trim();
        const result = validateRun(data);
        showFieldWarning(e.target, searchWarning, result.searchError);
        showActionState(result);
      },
    }),
  ]);

  return el('fieldset', { class: 'setting-section' }, [
    el('legend', { class: 'visually-hidden', text: t('ip.addressing') }),
    el('div', { class: 'ip-sub-head' }, [
      el('span', { class: 'eyebrow', text: t('ip.addressing') }),
    ]),
    el('label', { class: 'setting-row', for: 'ip-factory' }, [
      el('span', { class: 'label', text: t('ip.factoryIpAddress') }),
      factoryInput,
    ]),
    factoryWarning,
    ...maskField(data, check, showActionState),
    optionToggle(local.searchOpen, t('ip.searchIfNotFactory'), '',
                 () => { local.searchOpen = !local.searchOpen; }),
    // Flash before assigning. Old intercoms report their version and identity
    // wrongly, and the run is the only moment one of them is reachable alone
    // and still on the factory address.
    optionToggle(local.preflash, t('ip.preflash'), t('ip.preflashNote'),
                 () => { local.preflash = !local.preflash; }),
    ...(local.preflash ? preflashFields(plan) : []),
    ...(local.searchOpen ? [
      searchField('searchNetwork', 'ip-search-network',
        t('ip.searchNetwork'), plan.searchNetwork),
      searchField('searchNetmask', 'ip-search-mask',
        t('ip.searchNetmask'), plan.searchNetmask),
      // An explicit range: when the project mask is wide (/8 in the top bar)
      // opening the network means millions of addresses. With a range given,
      // the network/mask pair above is not used.
      searchField('searchFirst', 'ip-search-first', t('ip.rangeStart')),
      searchField('searchLast', 'ip-search-last', t('ip.rangeEnd')),
      searchWarning,
      el('p', {
        class: 'ip-field-help',
        text: t('ip.ifARangeIsGiven', { limit: SEARCH_LIMIT }),
      }),
    ] : []),
  ]);
}

function settingsCard(data, check, header) {
  const { plan } = data;
  return el('details', {
    class: 'card corner ip-settings-card ip-collapsible',
    open: local.openSections.scope,
    ontoggle: (e) => { local.openSections.scope = e.currentTarget.open; },
  }, [
    el('summary', { class: 'ip-card-head ip-collapsible-summary' }, [
      el('h3', { text: t('ip.ipSettings') }),
      header.summaryBadge,
    ]),
    switchArea(plan),
    portArea(data, check, header.showActionState),
    addressingArea(data, check, header.showActionState),

    // ── summary: what happens on which switch ──
    el('div', { class: 'setting-summary' }, [
      el('div', { class: 'ip-summary-head' }, [
        el('span', { class: 'eyebrow', text: t('ip.jobSummary') }),
      ]),
      el('div', { class: 'row' }, [
        el('span', { text: t('ip.target') }),
        el('b', {
          text: t('ip.targetSummary', { switch: value(plan.switch),
                                        count: plan.targetCount }),
        }),
      ]),
      el('div', { class: 'row' }, [
        el('span', { text: t('ip.targetMask') }),
        el('b', {
          class: 'mono',
          text: local.targetMask || plan.targetNetmask || '255.255.255.0',
        }),
      ]),
    ]),
    header.actionBar,
  ]);
}

// Returning devices to the factory address is a separate, destructive
// maintenance action. It stays visible on the IP page, but outside the primary
// assignment card so it cannot be mistaken for another run option.
function factoryResetSelection() {
  if (local.factoryResetScope !== 'external') {
    return { setNo: state.setNo, error: '' };
  }
  const raw = String(local.factoryResetSet || '').trim();
  const setNo = Number(raw);
  const error = Number.isInteger(setNo) && setNo >= 1 && setNo <= 254
    ? '' : t('topbar.setOutOfRange', { min: 1, max: 254 });
  return { setNo, error };
}

function factoryResetCard(data, check) {
  const isExternal = local.factoryResetScope === 'external';
  const initial = factoryResetSelection();
  const warning = el('p', {
    id: 'ip-factory-reset-set-error', class: 'ip-field-error', role: 'alert',
    text: initial.error, hidden: !initial.error,
  });
  let resetButton = null;

  const externalInput = isExternal ? el('input', {
    id: 'ip-factory-reset-set', class: 'field ip-reset-set-field',
    type: 'number', min: '1', max: '254', step: '1',
    value: local.factoryResetSet,
    placeholder: String(state.setNo), inputmode: 'numeric',
    autocomplete: 'off',
    'aria-invalid': String(!!initial.error),
    'aria-describedby': 'ip-factory-reset-set-error',
    oninput: (event) => {
      local.factoryResetSet = event.target.value.trim();
      const choice = factoryResetSelection();
      showFieldWarning(event.target, warning, choice.error);
      if (resetButton) {
        resetButton.disabled = !!choice.error || !!check.factoryError;
      }
    },
  }) : null;

  const scopeOption = (scope, label) => el('label', {
    class: 'ip-reset-scope-option',
    dataset: { active: local.factoryResetScope === scope ? '1' : '0' },
  }, [
    el('input', {
      type: 'radio', name: 'ip-factory-reset-scope', value: scope,
      checked: local.factoryResetScope === scope,
      onchange: () => {
        local.factoryResetScope = scope;
        patch({ ipState: { ...data } });
      },
    }),
    el('span', { text: label }),
  ]);

  resetButton = el('button', {
    type: 'button', class: 'btn btn-danger',
    text: t('ipmap.resetToTheFactoryIp'),
    disabled: !!initial.error || !!check.factoryError,
    onclick: async (event) => {
      const choice = factoryResetSelection();
      if (choice.error) { showError(choice.error); return; }
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = t('ipmap.preparingFactoryReset');
      try {
        await confirmFactoryReset(check.factoryIp, choice.setNo);
      } catch (error) {
        showError(error.message);
      } finally {
        if (button.isConnected) {
          button.disabled = !!factoryResetSelection().error
            || !!check.factoryError;
          button.textContent = t('ipmap.resetToTheFactoryIp');
        }
      }
    },
  });

  return el('section', { class: 'card corner ip-factory-reset-card' }, [
    el('div', { class: 'ip-factory-reset-head' }, [
      el('div', {}, [
        el('h3', { text: t('ipmap.factoryResetSection') }),
        el('p', { text: t('ipmap.factoryResetSectionNote') }),
      ]),
      el('span', { class: 'mono ip-factory-reset-address',
        text: check.factoryIp }),
    ]),
    el('fieldset', { class: 'ip-reset-scope' }, [
      el('legend', { class: 'label', text: t('ipmap.devicesSet') }),
      el('div', { class: 'ip-reset-scope-options' }, [
        scopeOption('current', t('ipmap.currentSet', { set: state.setNo })),
        scopeOption('external', t('ipmap.externalSet')),
      ]),
      isExternal ? el('label', {
        class: 'ip-reset-external-set', for: 'ip-factory-reset-set',
      }, [
        el('span', { class: 'label', text: t('ipmap.externalSetNumber') }),
        externalInput,
      ]) : null,
      isExternal ? warning : null,
    ]),
    el('div', { class: 'ip-factory-reset-actions' }, [
      el('p', { text: t('ipmap.factoryResetSelectionNote') }),
      resetButton,
    ]),
  ]);
}

// Putting the displays back where they started. Its own card and its own
// wording rather than a mode of the Intercom one: "factory" means something
// different here. No display is gathered onto a shared address — each keeps
// its own host octet and goes back to the set-1 form of it.
function lcdFactoryResetCard(data, check) {
  const { plan } = data;
  const isExternal = local.factoryResetScope === 'external';
  const initial = factoryResetSelection();
  const warning = el('p', {
    id: 'ip-lcd-reset-set-error', class: 'ip-field-error', role: 'alert',
    text: initial.error, hidden: !initial.error,
  });
  let resetButton = null;

  const scopeOption = (scope, label) => el('label', {
    class: 'ip-reset-scope-option',
    dataset: { active: local.factoryResetScope === scope ? '1' : '0' },
  }, [
    el('input', {
      type: 'radio', name: 'ip-lcd-reset-scope', value: scope,
      checked: local.factoryResetScope === scope,
      onchange: () => {
        local.factoryResetScope = scope;
        patch({ ipState: { ...data } });
      },
    }),
    el('span', { text: label }),
  ]);

  resetButton = el('button', {
    type: 'button', class: 'btn btn-danger',
    text: t('ipmap.resetToSetOne'),
    disabled: !!initial.error || !!check.portError,
    onclick: (event) => {
      const choice = factoryResetSelection();
      if (choice.error) { showError(choice.error); return; }
      try {
        confirmLcdFactoryReset(plan, check.portText, choice.setNo);
      } catch (error) {
        showError(error.message);
      }
      event.currentTarget.blur();
    },
  });

  return el('section', { class: 'card corner ip-factory-reset-card' }, [
    el('div', { class: 'ip-factory-reset-head' }, [
      el('div', {}, [
        el('h3', { text: t('ipmap.lcdFactoryResetSection') }),
        el('p', { text: t('ipmap.lcdFactoryResetNote') }),
      ]),
      el('span', { class: 'mono ip-factory-reset-address',
        text: t('ipmap.setOneAddresses') }),
    ]),
    el('fieldset', { class: 'ip-reset-scope' }, [
      el('legend', { class: 'label', text: t('ipmap.devicesSet') }),
      el('div', { class: 'ip-reset-scope-options' }, [
        scopeOption('current', t('ipmap.currentSet', { set: state.setNo })),
        scopeOption('external', t('ipmap.externalSet')),
      ]),
      isExternal ? el('label', {
        class: 'ip-reset-external-set', for: 'ip-lcd-reset-set',
      }, [
        el('span', { class: 'label', text: t('ipmap.externalSetNumber') }),
        el('input', {
          id: 'ip-lcd-reset-set', class: 'field ip-reset-set-field',
          type: 'number', min: '1', max: '254', step: '1',
          value: local.factoryResetSet,
          placeholder: String(state.setNo), inputmode: 'numeric',
          autocomplete: 'off',
          'aria-invalid': String(!!initial.error),
          'aria-describedby': 'ip-lcd-reset-set-error',
          oninput: (event) => {
            local.factoryResetSet = event.target.value.trim();
            const choice = factoryResetSelection();
            showFieldWarning(event.target, warning, choice.error);
            if (resetButton) {
              resetButton.disabled = !!choice.error || !!check.portError;
            }
          },
        }),
      ]) : null,
      isExternal ? warning : null,
    ]),
    el('div', { class: 'ip-factory-reset-actions' }, [
      el('p', {
        text: t('ipmap.lcdFactoryResetPorts', { ports: check.portText }),
      }),
      resetButton,
    ]),
  ]);
}

// The bench flow: one display on one port, one address the operator types.
// It shares nothing with the plan above — there is no DeviceMap row to
// honour, which is the whole point of testing a display before the train it
// belongs to exists. The switch port is still isolated and the MAC still has
// to prove the answer came from it.
function manualAssignCard(data, check) {
  const { plan } = data;
  const warning = el('p', {
    id: 'ip-lcd-manual-error', class: 'ip-field-error', role: 'alert',
    text: '', hidden: true,
  });
  const startButton = el('button', {
    type: 'button', class: 'btn btn-primary',
    text: local.manualBusy ? t('ip.lcdManualBusy') : t('ip.lcdManualStart'),
    disabled: true,
    onclick: () => startManual(plan),
  });

  // Typed into, never redrawn: a render on every keystroke takes focus out
  // of the box (the same reason the port and address fields above do this).
  // `latest` is the freshly validated run when the mask box calls in — the
  // render-time `check` still holds the mask as it was before the keystroke.
  function review(latest = check) {
    const port = String(local.manualPort || '');
    const address = String(local.manualIp || '');
    const portError = port && !parsePorts(port, plan.allowedPorts || [])
      .ports.length ? t('ip.lcdManualPortInvalid') : '';
    const addressError = address && !isIpv4(address)
      ? t('ip.lcdManualIpInvalid') : '';
    warning.textContent = portError || addressError;
    warning.hidden = !(portError || addressError);
    startButton.disabled = local.manualBusy || !port || !address
      || !!portError || !!addressError || !!latest.maskError;
  }

  const field = (id, key, labelKey, extra = {}) => el('label', {
    class: 'setting-row', for: id,
  }, [
    el('span', { class: 'label', text: t(labelKey) }),
    el('input', {
      id, class: 'field ip-medium-field', value: String(local[key] || ''),
      autocomplete: 'off', spellcheck: 'false',
      'aria-describedby': 'ip-lcd-manual-error',
      disabled: local.manualBusy,
      ...extra,
      oninput: (event) => {
        local[key] = event.target.value.trim();
        review();
      },
    }),
  ]);

  // A mask typed on either card decides whether this run can start, so the
  // button is re-checked from there too.
  maskWatchers.push((result) => review(result));

  const card = el('section', { class: 'card corner ip-manual-card' }, [
    el('div', { class: 'ip-factory-reset-head' }, [
      el('div', {}, [
        el('h3', { text: t('ip.lcdManualSection') }),
        el('p', { text: t('ip.lcdManualNote') }),
      ]),
    ]),
    field('ip-lcd-manual-port', 'manualPort', 'ip.lcdManualPort',
          { inputmode: 'numeric' }),
    field('ip-lcd-manual-ip', 'manualIp', 'ip.lcdManualIp'),
    warning,
    // The mask this run writes, editable here. It used to be a sentence
    // pointing at a field on another card — which meant scrolling away from
    // the run you were setting up to change a value that belongs to it.
    // Both boxes hold the same setting (see maskField).
    ...maskField(data, check, () => {}, 'ip-lcd-manual-mask'),
    el('div', { class: 'ip-factory-reset-actions' }, [
      el('p', { text: t('ip.lcdManualHow') }),
      startButton,
    ]),
  ]);
  review();
  return card;
}

function startManual(plan) {
  if (local.manualBusy) return;
  confirmWrite({
    title: t('ip.lcdManualSection'),
    lead: t('confirm.lcdManualLead', {
      port: local.manualPort, ip: local.manualIp,
    }),
    notes: [{ text: t('ip.lcdManualHow') }],
    confirmLabel: t('ip.lcdManualStart'),
    run: () => runManual(plan),
  });
}

async function runManual(plan) {
  local.manualBusy = true;
  patch({ ipState: { ...state.ipState } });
  try {
    const job = await api.ipLcdAssign({
      set: state.setNo,
      switch: plan.switchId,
      groups: plan.groups || [],
      port: String(local.manualPort || ''),
      targetIp: String(local.manualIp || ''),
      targetMask: local.targetMask || '',
      protected: (local.protected && local.protected.ports) || [],
    });
    patch({ queueOpen: true, openJob: job.id });
    if (job.new === false) notify(t('ip.anIpAssignmentJobIs'));
    else showSuccess(t('ip.lcdManualQueued'));
  } finally {
    local.manualBusy = false;
    if (state.view === 'ip' && state.ipState) {
      patch({ ipState: { ...state.ipState } });
    }
  }
}

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
      stopPanels();
      freshnessTick();
      if (live.enabled) {
        refreshRound();                 // read once as soon as it resumes
        protectedRound();               // re-verify the protected ports too
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
          el('p', {
            text: t('ip.reviewTheLivePortStates'),
          }),
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

export function render(root) {
  forgetMaskBoxes();
  const data = state.ipState;
  const check = data ? validateRun(data) : null;
  const header = runHeader(data, check);
  const parts = [header.bar, actionTabs.render(), targetPicker()];
  if (header.runError) parts.push(header.runError);
  if (header.networkLink) parts.push(header.networkLink);

  if (!data) {
    parts.push(el('div', {
      class: local.errorText
        ? 'warning ip-empty-state' : 'info ip-empty-state ip-loading',
      role: local.errorText ? 'alert' : 'status',
      'aria-live': 'polite', 'aria-busy': String(!local.errorText),
    }, [
      local.errorText ? null : el('i', { 'aria-hidden': 'true' }),
      el('span', {
        text: local.errorText || t('ip.preparingPlanLong'),
      }),
    ]));
    fill(root, parts);
    return;
  }

  const { plan, panels } = data;
  parts.push(el('div', { class: 'ip-grid' }, [
    settingsCard(data, check, header),
    panelSection(panels),
  ]));
  // The panels are filled in and their refresh loop started only once the
  // stack node exists (panelSection publishes it as live.stack).
  drawPanels(data);
  // The initial panel request is already in flight. Starting the five-second
  // loop before it finishes can duplicate a slow/unreachable switch read.
  if (!data.panelsLoading) startRefreshing();

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
    notes: [
      { text: t('confirm.ipRunPower'), tone: 'warning' },
      { text: t('confirm.ipRunMask', {
        mask: local.targetMask || plan.targetNetmask || '255.255.255.0',
      }) },
    ],
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
