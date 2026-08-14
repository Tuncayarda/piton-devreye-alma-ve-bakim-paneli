// The message catalogue on the browser side.
//
// The catalogue is NOT bundled into the UI: it arrives from the server (see
// `/api/language`, panel/i18n.py), which reads the very same JSON file to
// translate its own errors and queue rows. One file, one wording — a
// separate copy here would drift on the first hurried fix and leave half a
// screen in the other language.
//
// Nothing renders before `applyCatalogue()` has run once: `app.js` fetches
// the catalogue before the first paint, so no screen is ever drawn with keys
// showing.

const PLACEHOLDER = /\{(\w+)\}/g;

let current = 'en';
let available = ['en'];
let messages = {};

export function applyCatalogue(payload) {
  if (!payload || typeof payload !== 'object') return;
  if (typeof payload.language === 'string') current = payload.language;
  if (Array.isArray(payload.languages)) available = payload.languages.slice();
  if (payload.messages && typeof payload.messages === 'object') {
    messages = payload.messages;
  }
}

export function language() {
  return current;
}

export function languages() {
  return available.slice();
}

// An unknown key renders as the key itself: a visible, greppable marker beats
// an empty label, and tests/test_i18n.py fails the build if one exists.
export function t(key, params) {
  const text = Object.prototype.hasOwnProperty.call(messages, key)
    ? messages[key]
    : key;
  if (!params) return text;
  return String(text).replace(
    PLACEHOLDER,
    // A placeholder nobody passed stays visible rather than turning into
    // "undefined": that way the gap is noticed instead of shipped.
    (whole, name) => (
      Object.prototype.hasOwnProperty.call(params, name)
        ? String(params[name])
        : whole),
  );
}
