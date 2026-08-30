// Application state (single source) and subscriptions.
//
// This object holds NO password and cannot: `patch()` refuses to write keys
// outside the known list. The credential form hands its value straight to the
// API call without passing through here.

const KEYS = new Set([
  'edition', 'mode', 'views', 'projects', 'adminKey', 'remote',
  'setNo', 'project', 'view', 'category', 'subtype', 'filter',
  'devices', 'counts', 'locked', 'jobs', 'openJob', 'queueOpen',
  'lockedOpen', 'detailId', 'targetGroup', 'version', 'lastScan',
  'scanRunning', 'sidebarOpen', 'loading', 'ipState',
  'configState', 'firmwareState', 'mqttState', 'piscuState', 'meta',
  'checklistState', 'checklistCategory', 'historyFilter', 'networkState',
  'autoRefresh', 'deviceSearch', 'deviceSort', 'deviceSortDesc',
  'adbState', 'adbBusy',
  'switchState', 'switchSelected', 'switchBusy',
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
  // The last observation of the remote service session
  // (/api/admin/remote). Never the code in full and never a signature.
  remote: null,
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
  loading: false,
  ipState: null,
  configState: null,
  firmwareState: null,
  mqttState: null,
  piscuState: null,
  networkState: null,
  // The ADB screen: its address list plus whatever its runner is doing.
  adbState: null,
  // Is that screen writing to a device right now? Kept as a flag of its own
  // rather than read out of `adbState` on every tick, because the two
  // automatic refresh rounds consult it (core/schedule.js) and they must not
  // have to know the shape of another screen's data. It is the browser half
  // of the lock; the server refuses the round as well
  // (panel/api/routes/session_routes.py).
  adbBusy: false,
  // The switch screen: the server's body for it, which switch is open, and
  // whether a write to that switch is in flight. The password that unlocked
  // it is NOT here and cannot be — `patch()` refuses any key not listed
  // above, and the sign-in form hands its value straight to the API call.
  switchState: null,
  switchSelected: null,
  switchBusy: false,
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
  // Automatic rounds on or off.
  //
  // OFF WHEN THE PANEL OPENS. Reading a device is not free — a Compartment
  // LCD is read over adb, and the rounds take that connection out from under
  // whoever is working on the display. The panel is opened far more often to
  // do ONE thing to ONE device (write an address, install an APK, restart an
  // application on the bench) than to watch a whole train set, and starting
  // in the middle of a scan meant that one thing was being done against a
  // background of traffic nobody had asked for.
  //
  // Nothing is hidden by this: the top bar says "paused" from the first
  // paint, "Scan now" still works and is not gated on this flag, and one
  // click starts the rounds and pulls the first one forward immediately.
  //
  // Still session-scoped and NOT written to disk — the choice a user makes
  // during a session is theirs for that session, and a panel that came back
  // in yesterday's mode would show a screen full of yesterday's readings
  // with nothing saying why.
  autoRefresh: false,
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

// Folded so that Turkish spelling is not something the operator has to
// reproduce in the search box. NEITHER PLAIN NOR LOCALE LOWERCASING WORKS
// HERE, and they fail in opposite directions: plain `toLowerCase` leaves the
// dotted capital I as an i carrying a combining dot, which matches nothing
// anyone can type, while `toLocaleLowerCase('tr')` lowercases the ASCII I of
// "VIP" to a dotless i, so that typing "vip" stops finding it. Mapping the
// letters onto their ASCII base before lowercasing settles both, and it also
// makes the search forgiving in the direction it is actually used: a name
// typed on an ASCII keyboard finds the device that carries the real letters.
// The letters, and what each one folds to, in step. Two aligned strings
// rather than a table of twelve pairs, so that the letters occupy one line:
// this file is scanned for Turkish letters (tests/test_language.py), and the
// exemption that lets these through should cover as little as possible.
const TURKISH = 'İıŞşĞğÜüÖöÇç';
const ASCII = 'iissgguuoocc';
// Derived, so the two cannot drift: a letter added above is matched here
// without anyone having to remember this line as well.
const FOLDABLE = new RegExp(`[${TURKISH}]`, 'g');

// Both sides of the comparison go through this, or it is not a comparison.
export function fold(text) {
  return String(text || '')
    .replace(FOLDABLE, ch => ASCII[TURKISH.indexOf(ch)])
    .toLowerCase();
}

// What a device is searched BY. Everything the row already shows, so a
// search that finds nothing is a search whose text is not on the screen —
// there is no hidden field to guess at.
function searchable(device) {
  const result = device.result || {};
  return fold([
    device.name, device.typeLabel, device.portLabel, device.ip,
    result.version, result.detail,
  ].filter(Boolean).join(' '));
}

// Visible devices: category + subtype + state filter + free text
export function visibleDevices() {
  const category = state.category;
  const subtype = state.subtype;
  const filter = state.filter;
  // Several words all have to match, in any order and any field: "lcd 44"
  // finds Compartment_Lcd_5 at 10.1.1.44 without anyone having to know which
  // column holds which.
  const words = fold(state.deviceSearch).split(/\s+/).filter(Boolean);
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
    // ONE FILTER PER STATE, named after the state itself. There used to be
    // two buckets — `active` (ok) and `problem` (failed OR auth) — and the
    // overview links into them: "Needs review 18" landed on a list of 32
    // rows because the bucket also held the devices waiting on credentials.
    // A filter that shows a different number from the figure that opened it
    // is a filter nobody can trust. Anything unrecognised shows everything,
    // so an old choice read back from a session cannot empty the list.
    if (STATE_FILTERS.has(filter)) return d.result.state === filter;
    return true;
  });
}

const STATE_FILTERS = new Set(['ok', 'auth', 'failed', 'unknown']);

// The four states, always summing to the device list.
//
// `unknown` is worked out rather than read off the snapshot: a device the
// scan has not reached yet has no result to be tallied, so the server's four
// numbers can come to less than the list. The overview's strip and the
// devices screen's filters both need the four to add up, and they must not
// each do this sum their own way.
export function stateSpread() {
  const counts = state.counts;
  const settled = counts.ok + counts.auth + counts.failed;
  return {
    ok: counts.ok, auth: counts.auth, failed: counts.failed,
    unknown: Math.max(0, state.devices.length - settled),
  };
}
