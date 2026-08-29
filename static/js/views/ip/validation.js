// Judging what the operator typed, before a single packet is sent.
//
// The run WRITES to devices, so every field it depends on is checked here
// first and again on the server; this half exists so the answer arrives
// while the user is still typing, not after the job is queued.
//
// The netmask boxes are the reason this is a module and not a function.
// The same mask appears on more than one card, each with its own input and
// its own warning line, and all of them must agree the moment any one of
// them changes — so the boxes register themselves here, and one validation
// pass updates every copy. `forgetMaskBoxes` is called before a redraw:
// the nodes from the previous render are gone, and writing to them would
// silently do nothing.

import { el, showFieldWarning } from '../../core/dom.js';
import { currentTarget, local, protectedWaitText, targetLabel } from './state.js';
import {
  activePanelError, formatPorts, isIpv4, parsePorts, validatePorts,
  validateSearch, validateTargetMask,
} from './ports.js';
import { isCompartmentPlan, missingSoftwareRows } from './software.js';
import { t } from '../../core/i18n.js';

const maskBoxes = [];
const maskWatchers = [];

// Called by a card that shows its own view of the mask result (the manual
// card's review line). A function rather than an exported array: the list is
// this module's business, and a caller that could reach into it would also
// be able to leave a stale node behind.
export function onMaskResult(watcher) {
  maskWatchers.push(watcher);
}


// The single source of validity for every setting on the screen. The status
// text at the top, the start button and the field warnings all use this
// result.
export function validateRun(data) {
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
// Called at the start of every render: the nodes from the previous one are
// detached and writing to them would be writing to nothing.
export function forgetMaskBoxes() {
  maskBoxes.length = 0;
  maskWatchers.length = 0;
}
export function maskField(data, check, showActionState, prefix = 'ip-target-mask') {
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
  ];
}
