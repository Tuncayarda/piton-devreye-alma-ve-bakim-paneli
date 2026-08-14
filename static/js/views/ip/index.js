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
import { showError, showSuccess, notify } from '../../components/toast.js';
import { value, age } from '../../core/format.js';
import {
  IP_TARGETS, PROTECTED_INTERVAL, REFRESH_INTERVAL, currentTarget, live,
  local, onScreen, protectedFound, protectedPortsFor, protectedWaitText,
  refreshProtected, resetProtectedForSet, selectedGroups, stopPanels,
} from './state.js';
import {
  SEARCH_LIMIT, formatPorts, isIpv4, parsePorts, validateSearch,
} from './ports.js';
import { legend, panelCard, writeFreshness } from './panel.js';
import { searchOptions } from './diagnostics.js';
import { planTable } from './plan_table.js';
import { technicalCard } from './technical.js';
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
  fill(live.stack, data.panels.length
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
      onchange: (e) => {
        if (e.target.value === local.targetId) return;
        // A focused list holds the render back (see app.focusInDropdown);
        // the selection is done, so focus leaves the list.
        e.target.blur();
        local.targetId = e.target.value;
        // The port selection belonged to the old target's devices; while the
        // plan is rebuilt it falls back to the default (the new target's
        // ports).
        local.portText = null;
        local.switchId = null;
        refresh();
      },
    }, IP_TARGETS.map(target => el('option', {
      value: target.id,
      selected: target.id === active.id ? true : null,
      text: target.label,
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
  const protectedError = protectedWaitText();
  const portError = parsed.error || validatePorts(portText, allowed, plan);
  const target = currentTarget();
  const scopeError = !selectedPorts
    ? 'Select at least one target port for IP assignment'
    : !inPlan ? `No ${target.label} on the selected ports` : '';
  // The run connects to the switch with a username/password. Without one the
  // job entered the queue and fell over at the first step; saying so before
  // it starts is better.
  const activePanel = panelById.get(plan.switchId);
  const credentialError = activePanel && activePanel.hasCredentials === false
    ? `No username and password entered for ${activePanel.switchName}.`
    : '';
  const groupError = target.groups.some(
    group => !(plan.groups || []).includes(group))
    ? `No ${target.label} target found` : '';
  const factoryIp = local.factoryIp ?? plan.factoryIp ?? '';
  const factoryError = isIpv4(factoryIp)
    ? '' : 'The factory IP must be a valid IPv4 address';
  const searchError = local.searchOpen
    ? validateSearch(local.searchNetwork ?? plan.searchNetwork,
                     local.searchNetmask ?? plan.searchNetmask,
                     local.searchFirst, local.searchLast)
    : '';
  const error = groupError || factoryError || searchError
    || protectedError || portError || scopeError || credentialError;
  return {
    groupError,
    factoryIp,
    factoryError,
    searchError,
    credentialError,
    protectedError,
    allowed,
    portText,
    selectedPorts,
    inPlan,
    outOfPlan,
    panelById,
    portError: portError || (!selectedPorts ? scopeError : ''),
    error,
    ready: !error,
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
    return `Port ${port} cannot be included in IP assignment — `
      + `${protectedPorts.get(port)}`;
  }
  return '';
}

// The one-line computer summary in the run overview: where it was found and
// how fresh the finding is. The detail (MAC, interface, why a switch could not
// be read) lives in the tooltip so the summary line stays uncluttered.
function computerSummary() {
  const found = local.protected;
  if (!found) {
    return {
      ok: false,
      text: local.searchingProtected ? 'searching…' : '—',
      hint: t('ip.foundFromTheSwitchMac'),
    };
  }
  const computer = found.computer || {};
  if (!computer.port) {
    const tried = (found.tried || [])
      .map(entry => `${entry.name}: ${entry.state}`).join(' · ');
    return {
      ok: false,
      text: t('ip.notFound'),
      hint: [computer.note || found.note, tried].filter(Boolean).join(' — '),
    };
  }
  const when = found.time ? ` · verified ${age(found.time)} ago` : '';
  return {
    ok: true,
    text: `${computer.switchName} · p${computer.port}`,
    hint: `MAC ${computer.mac}`
      + `${computer.interface ? ` · ${computer.interface}` : ''}${when}`,
  };
}

export async function refresh() {
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
    // Each switch's panel comes from its own endpoint; if one cannot be read
    // (no credentials, unreachable) the others are still drawn.
    const panels = await Promise.all(
      (plan.switches || []).map(entry => api.ipPanel(setNo, entry.id)
        .catch(() => null)));
    if (token !== refreshToken || setNo !== state.setNo) return;
    local.errorText = '';
    patch({ ipState: { plan, panels: panels.filter(Boolean) } });
    // The finding is valid per set: another train set has entirely different
    // switches.
    resetProtectedForSet(setNo);
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
    ? check.ready ? 'ready' : 'error'
    : local.errorText ? 'error' : 'waiting';
  const headerText = data
    ? check.ready ? 'The plan is ready' : 'Check the settings'
    : local.errorText ? 'The plan cannot be used' : 'Preparing the plan';
  const readinessText = el('span', { text: headerText });
  const readiness = el('span', {
    class: 'ip-readiness', dataset: { state: headerState },
  }, [el('i', { 'aria-hidden': 'true' }), readinessText]);
  const startButton = el('button', {
    type: 'button', class: 'btn btn-primary ip-start-btn',
    text: t('ip.startIpAssignment'),
    disabled: !data || !check.ready,
    title: check && check.error ? check.error : 'Start the IP assignment job',
    onclick: start,
  });
  const summaryBadge = data ? el('span', {
    class: check.ready ? 'badge ip-ready-badge' : 'badge ip-error-badge',
    text: check.ready ? 'Ready' : 'Needs a check',
  }) : null;
  const runError = data ? el('p', {
    class: 'ip-run-error', role: 'alert', text: check.error,
    hidden: !check.error,
  }) : null;

  function showActionState(result, waitingText = '') {
    const ready = !!result.ready && !waitingText;
    startButton.disabled = !ready;
    startButton.title = result.error || waitingText
      || 'Start the IP assignment job';
    readiness.dataset.state = ready ? 'ready'
      : result.error ? 'error' : 'waiting';
    readinessText.textContent = ready
      ? 'The plan is ready'
      : result.error ? 'Check the settings' : waitingText;
    summaryBadge.className = ready
      ? 'badge ip-ready-badge'
      : result.error ? 'badge ip-error-badge' : 'badge ip-waiting-badge';
    summaryBadge.textContent = ready
      ? 'Ready' : result.error ? 'Needs a check' : 'Waiting for data';
    runError.textContent = result.error || '';
    runError.hidden = !result.error;
  }

  const bar = el('div', { class: 'page-head ip-page-head' }, [
    // The heading is the same on all three operation screens: the tab bar
    // below already says which screen this is.
    el('h2', { text: t('nav.operations') }),
    el('div', { class: 'ip-header-action' }, [readiness, startButton]),
  ]);

  return { bar, summaryBadge, runError, showActionState };
}

function showFieldWarning(input, warning, message) {
  input.setAttribute('aria-invalid', String(!!message));
  warning.textContent = message;
  warning.hidden = !message;
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
    placeholder: '11-14, 18-19, 21', autocomplete: 'off', spellcheck: 'false',
    // While typing only the warning is shown; the screen is not redrawn, or
    // focus would leave the field on every keystroke.
    oninput: (e) => {
      const parsed = parsePorts(e.target.value, allowed);
      const message = validatePorts(e.target.value, allowed, plan)
        || (!parsed.ports.length
          ? 'Select at least one target port for IP assignment' : '');
      e.target.setAttribute('aria-invalid', String(!!message));
      portWarning.textContent = message;
      portWarning.hidden = !message;
      showActionState({ ready: false, error: message },
                      message ? '' : 'Update the plan');
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

// Factory IP: the address the devices come out of the box on (in the field
// they all show at the same address — five devices at 10.1.1.12 in arp-scan).
// Search network: the addresses to scan for devices configured earlier, i.e.
// not on the factory address.
function addressingArea(data, check, showActionState) {
  const { plan } = data;
  const factoryWarning = el('p', {
    id: 'ip-factory-error', class: 'ip-field-error', role: 'alert',
    text: check.factoryError, hidden: !check.factoryError,
  });
  const factoryInput = el('input', {
    id: 'ip-factory', class: 'field', value: check.factoryIp,
    placeholder: plan.factoryIp || '10.1.1.12', autocomplete: 'off',
    spellcheck: 'false', inputmode: 'numeric',
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
  const searchField = (key, id, label, fallback, hint) => el('label', {
    class: 'setting-row', for: id,
  }, [
    el('span', { class: 'label', text: label }),
    el('input', {
      id, class: 'field ip-medium-field',
      value: local[key] ?? fallback ?? '',
      placeholder: hint, autocomplete: 'off', spellcheck: 'false',
      'aria-describedby': 'ip-search-error',
      oninput: (e) => {
        local[key] = e.target.value.trim();
        const result = validateRun(data);
        showFieldWarning(e.target, searchWarning, result.searchError);
        showActionState(result);
      },
    }),
  ]);

  const toggle = (pressed, label, title, onToggle) => el('button', {
    type: 'button', class: 'checkbox', 'aria-pressed': String(pressed),
    title: title || null,
    onclick: () => { onToggle(); patch({ ipState: { ...data } }); },
  }, [
    el('span', { class: 'box', 'aria-hidden': 'true' }),
    el('span', { text: label }),
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
    toggle(local.searchOpen,
           'Search the network if not on the factory address', '',
           () => { local.searchOpen = !local.searchOpen; }),
    // "Written" and "written persistently" are not the same: the device may
    // have taken the setting into memory only and returns to its old address
    // on the first power cut. The check lengthens the run, so it is off by
    // default.
    toggle(local.persistenceCheck,
           'Verify persistence (power cycle at the end)',
           'At the end of the run the ports are power cycled once and the '
           + 'devices are checked to come back on their new addresses. It '
           + 'makes the run longer.',
           () => { local.persistenceCheck = !local.persistenceCheck; }),
    ...(local.searchOpen ? [
      searchField('searchNetwork', 'ip-search-network', 'Search network',
        plan.searchNetwork, '10.1.1.0'),
      searchField('searchNetmask', 'ip-search-mask', 'Search netmask',
        plan.searchNetmask, '255.255.255.0'),
      // An explicit range: when the project mask is wide (/8 in the top bar)
      // opening the network means millions of addresses. With a range given,
      // the network/mask pair above is not used.
      searchField('searchFirst', 'ip-search-first', 'Range start',
        '', '10.1.1.10'),
      searchField('searchLast', 'ip-search-last', 'Range end',
        '', '10.1.1.60'),
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
    ]),
  ]);
}

// One front panel per switch, plus the pause control for their live refresh.
function panelSection(panels) {
  const panelStack = el('div', { class: 'panel-stack' });
  live.stack = panelStack;

  const refreshButton = el('button', {
    type: 'button', class: 'btn btn-small ip-refresh-btn',
    'aria-pressed': String(live.enabled),
    title: live.enabled
      ? 'Pause the automatic refresh of the port states'
      : 'Resume the automatic refresh',
    onclick: (e) => {
      live.enabled = !live.enabled;
      e.currentTarget.setAttribute('aria-pressed', String(live.enabled));
      e.currentTarget.textContent = live.enabled ? 'Refresh on' : 'Paused';
      stopPanels();
      freshnessTick();
      if (live.enabled) {
        refreshRound();                 // read once as soon as it resumes
        protectedRound();               // re-verify the protected ports too
      }
    },
    text: live.enabled ? 'Refresh on' : 'Paused',
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
  const data = state.ipState;
  const check = data ? validateRun(data) : null;
  const header = runHeader(data, check);
  const parts = [header.bar, actionTabs.render(), targetPicker()];
  if (header.runError) parts.push(header.runError);

  if (!data) {
    parts.push(el('div', {
      class: local.errorText
        ? 'warning ip-empty-state' : 'info ip-empty-state ip-loading',
      role: local.errorText ? 'alert' : 'status',
      'aria-live': 'polite', 'aria-busy': String(!local.errorText),
    }, [
      local.errorText ? null : el('i', { 'aria-hidden': 'true' }),
      el('span', {
        text: local.errorText || 'Preparing the IP assignment plan…',
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
  startRefreshing();

  parts.push(technicalCard(plan, check, computerSummary()));
  parts.push(planTable(plan, check));

  fill(root, parts);
}

function togglePort(number, context) {
  const plan = state.ipState && state.ipState.plan;
  if (!plan) return;
  // Clicking a port on another switch moves the run to that switch; the
  // selection there starts with that port.
  if (!context.active) {
    local.switchId = context.switchId;
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

async function start() {
  const data = state.ipState;
  const plan = data && data.plan;
  if (!plan) return;
  const check = validateRun(data);
  if (!check.ready) {
    showError(check.error);
    return;
  }
  try {
    const job = await api.ipRun({
      set: state.setNo,
      switch: plan.switchId,
      groups: plan.groups || [],
      ports: local.portText ?? plan.portText,
      factoryIp: check.factoryIp,
      ...searchOptions(plan),
      persistenceCheck: !!local.persistenceCheck,
      // The server finds the protected ports ITSELF when the run starts; this
      // list is only the last known information should the switch not answer
      // at that moment.
      protected: (local.protected && local.protected.ports) || [],
    });
    patch({ queueOpen: true, openJob: job.id });
    if (job.new === false) {
      notify(t('ip.anIpAssignmentJobIs'));
    } else {
      showSuccess(t('ip.theIpAssignmentJobWas'));
    }
  } catch (e) {
    showError(e.message);
  }
}
