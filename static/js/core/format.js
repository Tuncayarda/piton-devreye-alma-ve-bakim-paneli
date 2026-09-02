// Formatting and labelling.
//
// One marker is used everywhere data is missing: —
// "not applicable on this device" and "could not be read" are different
// texts; merging them tells the user something untrue.

import { t } from './i18n.js';
import { state } from './store.js';

export const NONE = '—';

export function value(v) {
  if (v === null || v === undefined || v === '') return NONE;
  return String(v);
}

export const STATE_LABEL = {
  ok: 'state.ok',
  auth: 'state.auth',
  review: 'state.review',
  failed: 'state.failed',
  unknown: 'state.unknown',
};

export const VERIFICATION_LABEL = {
  verified: 'verify.verified',
  auth_required: 'verify.authrequired',
  unverified: 'verify.unverified',
  not_read: 'verify.notread',
  not_applicable: 'verify.notapplicable',
};

// The type names in DeviceMap are part of the device protocol. This table
// exists for the few that need a friendlier wording on screen;
// product/model names (PISCU, UIC, Intercom) are left alone.
const TYPE_WORDS = {
  Announcement: 'Announcement',
  Camera: 'Camera',
  Compartment: 'Compartment',
  Corridor: 'Corridor',
  Front: 'Front',
  Landing: 'Landing',
};

export function typeLabel(label) {
  return String(label || '')
    .split('/')
    .map(part => part.trim())
    .map(part => TYPE_WORDS[part] || part)
    .join(' / ');
}

export const JOB_STATE_LABEL = {
  queued: 'jobstate.queued',
  running: 'jobstate.running',
  done: 'jobstate.done',
  cancelled: 'jobstate.cancelled',
  failed: 'jobstate.failed',
};

export const JOB_OUTCOME_LABEL = {
  success: 'outcome.success',
  warning: 'outcome.warning',
  failed: 'outcome.failed',
  stopped: 'outcome.stopped',
};

// Domain state -> presentation token. The tokens are the CSS custom
// properties (--ok, --auth, …); this table is the seam that keeps the domain
// vocabulary and the stylesheet independent of each other.
export const JOB_OUTCOME_COLOUR = {
  success: 'ok',
  warning: 'auth',
  failed: 'failed',
  stopped: 'auth',
};

export const ROW_STATE_LABEL = {
  queued: 'rowstate.queued',
  running: 'rowstate.running',
  // An intermediate state in an IP assignment run: written to the device and
  // the device reset, but whether it answers on its new address is only known
  // in the final verification pass. "Done" would be wrong
  // (see panel/ip_assign/progress.py WRITTEN).
  written: 'rowstate.written',
  done: 'rowstate.done',
  auth: 'rowstate.auth',
  // "[!]" lines in the script output: the run continues but something went
  // wrong. Showing them all as a green "Done" hid the real cause in 200 lines
  // of output.
  warning: 'rowstate.warning',
  failed: 'rowstate.failed',
  skipped: 'rowstate.skipped',
};

export const ROW_COLOUR = {
  queued: 'unknown',
  running: 'busy',
  // Same colour as running but without the pulse: the job finished on that
  // row and is awaiting confirmation. Amber was not used — amber means
  // "something went wrong" in this panel, and a written port has not.
  written: 'busy',
  // Most steps under a row are neither success nor failure: they record what
  // was done.
  info: 'unknown',
  done: 'ok',
  auth: 'auth',
  warning: 'auth',
  failed: 'failed',
  skipped: 'unknown',
};

// Device state -> presentation token, same seam as above.
export const STATE_COLOUR = {
  ok: 'ok',
  auth: 'auth',
  failed: 'failed',
  unknown: 'unknown',
};

// One locale for the whole panel, so a machine's regional settings cannot
// change what two people reading the same screen see.
export const LOCALE = 'en-GB';

export function clockTime(ts) {
  if (!ts) return NONE;
  return new Date(ts * 1000).toLocaleTimeString(LOCALE, { hour12: false });
}

export function age(ts) {
  if (!ts) return NONE;
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h`;
}

export function percent(part, total) {
  if (!total) return '0%';
  return `${Math.round((part / total) * 100)}%`;
}

export function fileSize(bytes) {
  if (!bytes) return NONE;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  // Firmware images are megabytes; a USB drive is not, and "30720.00 MB" is
  // not a number anybody checks against the thing in their hand.
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  }
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

// The "version" shown on a device row: left empty when unread, never
// invented.
// The tables above hold message KEYS. These readers turn a domain code into
// text in the language selected right now — a table of ready-made strings
// would have frozen at whatever language was loaded when the module ran.
const lookup = (table) => (code, fallback = '') => (
  table[code] ? t(table[code]) : (fallback || code || ''));

export const stateLabel = lookup(STATE_LABEL);
export const verificationLabel = lookup(VERIFICATION_LABEL);
export const jobStateLabel = lookup(JOB_STATE_LABEL);
export const jobOutcomeLabel = lookup(JOB_OUTCOME_LABEL);
export const rowStateLabel = lookup(ROW_STATE_LABEL);

// HOW THE PANEL TALKS TO THIS DEVICE — KYLAND, ISAPI, HTTP, MQTT, ADB.
//
// The code is on the device DTO only once a read has happened; before that
// it is resolved from the catalogue the meta call hands out
// (`catalog.READ_METHODS`, keyed by the method the DeviceMap resolved for
// the type). The credentials panel and the project's device ledger both ask,
// and they were about to ask in two places.
export function methodCode(device) {
  if (device.readMethodCode) return device.readMethodCode;
  const methods = state.meta && state.meta.readMethods;
  const method = methods && methods[device.readMethod];
  return (method && method.code)
    || String(device.readMethod || '').toUpperCase();
}

export function versionOf(device) {
  const fields = device.result && device.result.fields;
  return (fields && (fields.version || fields.model)) || '';
}

export function uptimeOf(device) {
  const fields = device.result && device.result.fields;
  return (fields && fields.uptime) || '';
}
