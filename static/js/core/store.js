// Application state (single source) and subscriptions.
//
// This object holds NO password and cannot: `patch()` refuses to write keys
// outside the known list. The credential form hands its value straight to the
// API call without passing through here.

const KEYS = new Set([
  'edition', 'mode', 'views', 'projects', 'adminKey',
  'setNo', 'project', 'view', 'category', 'subtype', 'filter',
  'devices', 'counts', 'locked', 'jobs', 'openJob', 'queueOpen',
  'lockedOpen', 'detailId', 'targetGroup', 'version', 'lastScan',
  'scanRunning', 'sidebarOpen', 'piscuIp', 'loading', 'ipState',
  'configState', 'firmwareState', 'mqttState', 'piscuState', 'meta',
  'checklistState', 'checklistCategory', 'historyFilter', 'networkState',
  'autoRefresh', 'deviceSearch', 'deviceSort', 'deviceSortDesc',
]);

const _subscribers = new Set();

export const state = {
  // What this package is, and what it may show. All four arrive together
  // from /api/edition and are re-read after admin mode or the project
  // changes — see app.js:applyEdition.
  edition: null,
  mode: 'field',
  views: [],
  projects: [],
  // The last observation of the service key (/api/admin/key). Never the key
  // itself: what is here is "present", "recognised" and a counter.
  adminKey: null,
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
  // Wide by default: six abstract icons with their names only on hover
  // is a memory tax for anyone who uses the panel now and then. Whoever
  // wants the room back collapses it, and the choice sticks.
  sidebarOpen: true,
  piscuIp: null,
  loading: false,
  ipState: null,
  configState: null,
  firmwareState: null,
  mqttState: null,
  piscuState: null,
  networkState: null,
  checklistState: null,
  checklistCategory: 'all',
  // Free text typed on the devices screen. Lives here rather than in the
  // view so the overview's own navigation can clear it — arriving from a KPI
  // tile with somebody's old search still applied shows an empty list and no
  // reason for it.
  deviceSearch: '',
  // Which column the device list is sorted by, and which way. Null means the
  // order DeviceMap lists them in, which is the wiring order and the one an
  // operator walking the train recognises.
  deviceSort: null,
  deviceSortDesc: false,
  historyFilter: 'all',
  // Automatic rounds on or off. Session-scoped on purpose: it is NOT written
  // to disk. A panel that came back paused the next morning would show a
  // screen full of yesterday's readings with nothing saying why.
  autoRefresh: true,
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
    if (key === 'view' && !viewAllowed(value)) {
      console.warn('state: view not in this edition —', value);
      continue;
    }
    if (state[key] !== value) { state[key] = value; changed.push(key); }
  }
  if (changed.length) publish(changed);
  return changed.length > 0;
}

// The screens this package shows are decided by the edition, and in admin
// mode by the service key (panel/editions/catalogue.py). The check lives
// HERE rather than in the sidebar because the sidebar only decides what is
// DRAWN: a keyboard shortcut, a stale bookmark in the code or a later caller
// all reach `patch({ view })` directly, and hiding a button never stopped
// any of them. The server refuses the data too (panel/api/guard.py); this is
// the half that keeps the empty screen from being opened at all.
//
// An empty list means the edition has not been read yet, and everything is
// allowed: the first paint happens before /api/edition answers.
export function viewAllowed(view) {
  return !state.views.length || state.views.includes(view);
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

// What a device is searched BY. Everything the row already shows, so a
// search that finds nothing is a search whose text is not on the screen —
// there is no hidden field to guess at.
function searchable(device) {
  const result = device.result || {};
  return [
    device.name, device.typeLabel, device.portLabel, device.ip,
    result.version, result.detail,
  ].filter(Boolean).join(' ').toLowerCase();
}

// Visible devices: category + subtype + state filter + free text
export function visibleDevices() {
  const category = state.category;
  const subtype = state.subtype;
  const filter = state.filter;
  // Several words all have to match, in any order and any field: "lcd 44"
  // finds Compartment_Lcd_5 at 10.1.1.44 without anyone having to know which
  // column holds which.
  const words = String(state.deviceSearch || '')
    .toLowerCase().split(/\s+/).filter(Boolean);
  return state.devices.filter(d => {
    if (category !== 'all' && d.category !== category) return false;
    if (subtype) {
      const name = category === 'all' ? d.type : (d.subtype || d.type);
      if (name !== subtype) return false;
    }
    if (words.length) {
      const haystack = searchable(d);
      if (!words.every(word => haystack.includes(word))) return false;
    }
    if (filter === 'active') return d.result.state === 'ok';
    if (filter === 'problem') {
      return d.result.state === 'failed' || d.result.state === 'auth';
    }
    return true;
  });
}
