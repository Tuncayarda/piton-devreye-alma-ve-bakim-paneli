// Application state (single source) and subscriptions.
//
// This object holds NO password and cannot: `patch()` refuses to write keys
// outside the known list. The credential form hands its value straight to the
// API call without passing through here.

const KEYS = new Set([
  'role', 'setNo', 'project', 'view', 'category', 'subtype', 'filter',
  'devices', 'counts', 'locked', 'jobs', 'openJob', 'queueOpen',
  'lockedOpen', 'detailId', 'targetGroup', 'version', 'lastScan',
  'scanRunning', 'sidebarOpen', 'piscuIp', 'loading', 'ipState',
  'configState', 'firmwareState', 'mqttState', 'piscuState', 'meta',
  'checklistState', 'checklistCategory', 'historyFilter',
]);

const _subscribers = new Set();

export const state = {
  role: null,
  setNo: 1,
  project: null,
  meta: null,
  view: 'overview',
  category: 'all',
  subtype: null,
  filter: 'all',
  devices: [],
  counts: { ok: 0, auth: 0, failed: 0, unknown: 0 },
  locked: [],
  jobs: [],
  openJob: null,
  queueOpen: false,
  lockedOpen: false,
  detailId: null,
  targetGroup: 'Intercom',
  version: '',
  lastScan: null,
  scanRunning: false,
  sidebarOpen: false,
  piscuIp: null,
  loading: false,
  ipState: null,
  configState: null,
  firmwareState: null,
  mqttState: null,
  piscuState: null,
  checklistState: null,
  checklistCategory: 'all',
  historyFilter: 'all',
};

// Subscribers are told WHICH keys changed: redrawing the whole UI on every
// change meant rebuilding a 42-row device table for a click that only
// concerned the queue panel.
export function patch(changes) {
  const changed = [];
  for (const [key, value] of Object.entries(changes)) {
    if (!KEYS.has(key)) {
      console.warn('state: unknown key ignored —', key);
      continue;
    }
    if (state[key] !== value) { state[key] = value; changed.push(key); }
  }
  if (changed.length) publish(changed);
  return changed.length > 0;
}

export function subscribe(fn) {
  _subscribers.add(fn);
  return () => _subscribers.delete(fn);
}

// No `changed` means "anything may have changed".
export function publish(changed = null) {
  for (const fn of _subscribers) {
    try { fn(state, changed); } catch (e) { console.error(e); }
  }
}

// Visible devices: category + subtype + state filter
export function visibleDevices() {
  const category = state.category;
  const subtype = state.subtype;
  const filter = state.filter;
  return state.devices.filter(d => {
    if (category !== 'all' && d.category !== category) return false;
    if (subtype) {
      const name = category === 'all' ? d.type : (d.subtype || d.type);
      if (name !== subtype) return false;
    }
    if (filter === 'active') return d.result.state === 'ok';
    if (filter === 'problem') {
      return d.result.state === 'failed' || d.result.state === 'auth';
    }
    return true;
  });
}
