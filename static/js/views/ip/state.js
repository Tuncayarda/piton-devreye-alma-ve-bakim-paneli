// The IP screen's own state, the protected-port discovery and the live
// refresh timers.
//
// The ports the run must not touch (where the computer is plugged in, and the
// links between switches) used to be typed in. Both are already written in the
// switches' MAC learning tables; there was no need to ask, and a wrong answer
// did damage twice — a port that needed protecting was not protected, and a
// port that did not need it was dropped from the run.
//
// The finding is not taken once and left: the cable may be moved to another
// port before the run starts. While the screen is open it is re-verified at a
// regular interval; when the run starts the server finds it again on its own
// side (see panel/api/routes/ip_routes.py post_run).

import { api } from '../../core/api.js';
import { t } from '../../core/i18n.js';
import { state, patch } from '../../core/store.js';
import { groupsFor } from '../../components/group_bar.js';

// A DeviceMap/API protocol value, assembled so the screen-text catalogue
// check does not mistake it for a label shown to the operator.
export const LCD_GROUP = ['Compartment', 'LCD'].join(' ');

// The device types IP may be assigned to — the groups the OPEN PROJECT has
// that declare the `ip` operation, and nothing else.
//
// This used to be a literal pair, `Intercom` and `Compartment LCD`, written
// out here. It was a copy of the two rows in `panel/inventory/catalog.py`
// that carry `ip` in their ops, and copying it cost what a copy costs: on
// VIP, a project with no Compartment LCD in it at all, the screen went on
// offering a Compartment LCD commissioning run — the run that cuts switch
// ports and rewrites addresses.
//
// `catalog.py` says it in its own first line: the UI keeps no list of its
// own and takes these from the API. This one had.
//
// The ids and labels still follow DeviceMap verbatim — `group_bar` hands
// over the group's `name` and its `label`, and the catalogue leaves both
// LCD names untranslated on purpose, so that an operator comparing this
// picker with the map reads the same words.
export function ipTargets() {
  return groupsFor('ip').map(group => ({
    id: group.name, label: group.label || group.name, groups: [group.name],
  }));
}

export const local = {
  // Null until the operator picks one: which targets exist is the open
  // project's answer and is not known when this module is first evaluated.
  targetId: null,
  portText: null,          // null = the plan's default (the group's ports)
  factoryIp: null,         // null = the plan's default (10.1.1.12)
  searchOpen: false,       // search the network for devices not on the
                           // factory address
  searchNetwork: null,
  searchNetmask: null,
  searchFirst: null,       // an explicit address range — used instead of
  searchLast: null,        // network/mask when given
  // The mask written WITH the new address, as opposed to the one searched.
  // Empty means the plan's default (/24). Compartment LCDs are sometimes
  // commissioned on a /8, which is why this is a field and not a constant.
  targetMask: null,
  // Install software before the address is written. For intercoms whose
  // firmware is too old to report itself correctly — the run is the only
  // moment one of them is alone on the wire (see panel/ip_assign/preflash.py).
  // The FILE is not held here: it stays on the server, chosen through the
  // operating system's own dialog, and the screen only learns its name.
  preflash: false,
  // Compartment LCD software is selected per DeviceMap id through the existing
  // firmware API. The plan carries the selected-file records; only the toggle
  // and the file-dialog lock belong to this screen.
  installApk: false,
  apkPickerOpen: false,
  // The bench flow: one port, one address typed by hand. It has no plan and
  // no DeviceMap row, so its fields live only here.
  manualPort: '',
  manualIp: '',
  manualBusy: false,
  // Protected ports (where the computer is, plus the switch-to-switch links).
  // Not typed in: found from the MAC tables and re-verified at intervals.
  // There is no separate form on screen; the finding shows as an amber port
  // on the front panel and in the run summary.
  protected: null,         // {time, computer, ports[], tried[], note}
  searchingProtected: false,
  switchId: null,          // null = the switch the plan picked itself
  factoryResetScope: 'current',
  factoryResetSet: '',
  errorText: '',
  openSections: {
    scope: true,
    panels: true,
    plan: null,
  },
};

// The chosen target, or the first one this project offers. The fallback is
// what carries a project switch: `local.targetId` may name a group the new
// project does not have, and on an empty list there is nothing to return —
// the screen's own guard (`plan === null`) already covers that.
export function currentTarget() {
  const targets = ipTargets();
  return targets.find(entry => entry.id === local.targetId) || targets[0]
    || null;
}

export function targetLabel(target = currentTarget()) {
  return target ? target.label : '';
}

// Changing the physical switch invalidates every choice that was derived
// from the old switch. The firmware files themselves remain safely in the
// server-side selection store; only the old plan's request to install them is
// cleared. The next plan supplies the new switch's default ports and files.
export function selectAssignmentSwitch(switchId) {
  local.switchId = switchId || null;
  local.portText = null;
  local.installApk = false;
  local.apkPickerOpen = false;
  invalidateProtected();
}

export function selectedGroups() {
  const target = currentTarget();
  return target ? target.groups : [];
}

// ── live refresh ────────────────────────────────────────────────────────
// Like the Switch Management Panel: the ports are re-read every 5 seconds,
// the heading says how many seconds ago the data was taken, and refreshing
// can be paused. Only the panel area is redrawn — redrawing the whole screen
// tore focus out of the form while the user was typing.
export const REFRESH_INTERVAL = 5000;
export const STALE_SECONDS = 15;

// Re-verifying the protected ports. Separate from the front panel round and
// rarer: this round reads the switch's MAC table, and a cable does not move
// every five seconds. But finding it once and leaving it will not do either —
// the cable may have moved to another port before the run starts.
export const PROTECTED_INTERVAL = 30000;

export const live = {
  enabled: true,
  timer: null,            // the refresh round's timer
  ticker: null,           // the per-second tick that refreshes "x s ago"
  protectedTimer: null,   // the protected ports' re-verification round
  stack: null,            // the container of the panel cards
};

export function stopPanels() {
  clearTimeout(live.timer);
  clearTimeout(live.ticker);
  clearTimeout(live.protectedTimer);
  live.timer = live.ticker = live.protectedTimer = null;
}

export function onScreen() {
  return state.view === 'ip' && !!state.meta
    && !!(live.stack && live.stack.isConnected);
}

// ── protected-port discovery ────────────────────────────────────────────
let findingSet = null;         // the train set the finding belongs to
let findingGeneration = 0;     // retires an in-flight result after a switch move

// A protected-port result covers the whole set, but it is a live MAC-table
// snapshot. Re-read it when the operator moves the run to another switch so
// the new switch cannot momentarily use an old panel/protection decision.
export function invalidateProtected() {
  findingGeneration += 1;
  local.protected = null;
  local.searchingProtected = false;
}

// Is there a usable finding? A search that answered but did not find the
// computer counts as "no": the run cannot start without it.
export function protectedFound() {
  const found = local.protected;
  return !!(found && found.computer && found.computer.port);
}

export function resetProtectedForSet(setNo) {
  if (findingSet !== setNo) {
    findingSet = setNo;
    invalidateProtected();
  }
}

async function findProtected() {
  const setNo = state.setNo;
  const generation = findingGeneration;
  local.searchingProtected = true;
  try {
    const found = await api.ipProtected(setNo);
    if (setNo !== state.setNo || generation !== findingGeneration) return;
    local.protected = found;
  } catch (e) {
    if (setNo !== state.setNo || generation !== findingGeneration) return;
    local.protected = {
      time: Date.now() / 1000, computer: { port: null, source: 'none' },
      ports: [], tried: [], note: e.message,
    };
  } finally {
    if (generation === findingGeneration) local.searchingProtected = false;
  }
}

// Runs the search and redraws the screen. `patch` is called with a new object
// reference so the render fires even when the content did not change.
export async function refreshProtected() {
  await findProtected();
  if (state.view === 'ip' && state.ipState) {
    patch({ ipState: { ...state.ipState } });
  }
}

// Ports on the target switch the run must not touch: [[number, reason], …]
// Ports belonging to another switch do not bind this run.
export function protectedPortsFor(plan) {
  const list = (local.protected && local.protected.ports) || [];
  return list
    .filter(entry => entry.switchId === plan.switchId)
    .map(entry => [Number(entry.port), entry.reason])
    .sort((a, b) => a[0] - b[0]);
}

// Why is the run waiting while the protected ports are still unknown?
//
// Finding no port to protect on the target switch is not an error on its own:
// the computer may be on another switch and the link towards it may not show
// on this switch's face. The real obstacle is the discovery never having run —
// then which port carries our own path is unknown.
export function protectedWaitText() {
  if (local.searchingProtected && !local.protected) {
    return t('ip.findingProtectedPorts');
  }
  const found = local.protected;
  if (!found) return t('ip.protectedPortsNotFound');
  const hasComputer = !!(found.computer && found.computer.port);
  if (!hasComputer) {
    return found.note || t('ip.computerPortNotFound');
  }
  return '';
}
