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
import { state, patch } from '../../core/store.js';

// The device type IP will be assigned to. The engine supports only Intercom
// today (see panel/ip_assign/runner.py RUNNERS), so the list has one option.
// The picker stays on screen anyway: the user should be able to read from the
// screen which devices IP assignment goes to, and adding a group later is one
// line here with no layout change.
export const IP_TARGETS = [
  { id: 'Intercom', label: 'Intercom', groups: ['Intercom'] },
];

export const local = {
  targetId: IP_TARGETS[0].id,
  portText: null,          // null = the plan's default (the group's ports)
  factoryIp: null,         // null = the plan's default (10.1.1.12)
  searchOpen: false,       // search the network for devices not on the
                           // factory address
  searchNetwork: null,
  searchNetmask: null,
  searchFirst: null,       // an explicit address range — used instead of
  searchLast: null,        // network/mask when given
  // Cycle the power at the end and confirm the setting reached the device's
  // flash. Off by default: it lengthens the run and blacks the devices out
  // again.
  persistenceCheck: false,
  // Protected ports (where the computer is, plus the switch-to-switch links).
  // Not typed in: found from the MAC tables and re-verified at intervals.
  // There is no separate form on screen; the finding shows as an amber port
  // on the front panel and in the run summary.
  protected: null,         // {time, computer, ports[], tried[], note}
  searchingProtected: false,
  switchId: null,          // null = the switch the plan picked itself
  errorText: '',
  openSections: {
    scope: true,
    panels: true,
    plan: null,
    technical: false,
  },
};

export function currentTarget() {
  return IP_TARGETS.find(t => t.id === local.targetId) || IP_TARGETS[0];
}

export function selectedGroups() {
  return currentTarget().groups;
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
  return state.view === 'ip' && !!state.role
    && !!(live.stack && live.stack.isConnected);
}

// ── protected-port discovery ────────────────────────────────────────────
let findingSet = null;         // the train set the finding belongs to

// Is there a usable finding? A search that answered but did not find the
// computer counts as "no": the run cannot start without it.
export function protectedFound() {
  const found = local.protected;
  return !!(found && found.computer && found.computer.port);
}

export function resetProtectedForSet(setNo) {
  if (findingSet !== setNo) {
    findingSet = setNo;
    local.protected = null;
  }
}

async function findProtected() {
  const setNo = state.setNo;
  local.searchingProtected = true;
  try {
    const found = await api.ipProtected(setNo);
    if (setNo !== state.setNo) return;
    local.protected = found;
  } catch (e) {
    if (setNo !== state.setNo) return;
    local.protected = {
      time: Date.now() / 1000, computer: { port: null, source: 'none' },
      ports: [], tried: [], note: e.message,
    };
  } finally {
    local.searchingProtected = false;
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
    return 'Finding the protected ports from the switch MAC tables…';
  }
  const found = local.protected;
  if (!found) return 'The protected ports have not been found yet';
  const hasComputer = !!(found.computer && found.computer.port);
  if (!hasComputer) {
    return found.note || 'The port the computer is attached to was not '
      + 'found — the switch MAC table cannot be read';
  }
  return '';
}
