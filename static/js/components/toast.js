// The message strip at the bottom of the screen.
//
// It used to be one element holding one message for a few seconds. Two things
// were wrong with that, and both cost the operator information they had asked
// for:
//
//   · A SECOND message overwrote the first. The job queue polls every second
//     and announces itself, so an error could be wiped by an unrelated "job
//     queued" before anyone had read it.
//   · ERRORS disappeared after six seconds and could not be brought back.
//     Roughly half the call sites report a write that was REJECTED — the
//     firmware install that did not start, the settings value that was not
//     saved, the run that refused. The queue keeps the errors of JOBS; an
//     error from a file picker or a validation refusal was kept nowhere.
//
// So: successes and notices still fade, because they confirm something the
// user just did and watched happen. Errors stay until they are dismissed, and
// stack rather than replace. Nothing is ever silently lost.

import { el, fill, svg, $ } from '../core/dom.js';
import { t } from '../core/i18n.js';

// WHAT KIND OF MESSAGE THIS IS, SAID TWICE — a mark and a colour.
//
// The strip used to say it in colour alone, and it said it by painting the
// whole sentence: two lines of red for an error, which is heavier to read
// than the same words in the panel's ordinary text and tells somebody who
// cannot separate the two greens nothing at all. The colour is now a band
// down the left edge and a glyph in front, the same two things a row in any
// of the panel's lists is read by, and the sentence is left legible.
const MARK = {
  error: ['M10 3.6a6.4 6.4 0 1 0 0 12.8a6.4 6.4 0 0 0 0-12.8',
          'M10 6.9v4.3', 'M10 13.6h.01'],
  success: ['M4.9 10.3 8.4 13.8 15.1 6.6'],
  info: ['M10 3.6a6.4 6.4 0 1 0 0 12.8a6.4 6.4 0 0 0 0-12.8',
         'M10 13.1V9.4', 'M10 6.6h.01'],
};

// The panel's own state vocabulary, so the band and the glyph take their
// colour from the same two tokens every other state on every other screen
// does (see components.css `[data-state]`).
const STATE = { error: 'failed', success: 'ok', info: 'busy' };

function mark(kind) {
  return svg({
    width: 15, height: 15, fill: 'none', stroke: 'currentColor',
    'stroke-width': '1.5', 'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
  }, (MARK[kind] || MARK.info).map(d => ['path', { d }]));
}

// How many can be on screen at once. Past this the oldest goes; the strip is
// a notice board, not a log.
const MAX_VISIBLE = 3;
const DEFAULT_MS = 4200;

let nextId = 0;
const shown = [];        // [{ id, text, kind, timer }]

function draw() {
  const box = $('#toast');
  if (!box) return;
  box.hidden = shown.length === 0;
  // `alert` interrupts a screen reader, `status` waits its turn. An error
  // that stays on screen has earned the interruption; a success has not.
  box.setAttribute('role',
                   shown.some(item => item.kind === 'error') ? 'alert'
                     : 'status');
  fill(box, shown.map(item => el('div', {
    class: 'toast-item',
    dataset: {
      kind: item.kind, state: STATE[item.kind] || 'busy',
      // Only what has just arrived slides in. Every message is rebuilt on
      // every draw, so without this the whole strip would replay its
      // entrance each time one more was added to it.
      enter: item.fresh ? '1' : '0',
    },
  }, [
    el('span', { class: 'toast-mark', 'aria-hidden': 'true' }, [mark(item.kind)]),
    el('span', { class: 'toast-text', text: item.text }),
    item.kind === 'error'
      ? el('button', {
          type: 'button', class: 'btn btn-close toast-close',
          'aria-label': t('toast.dismiss'), text: '×',
          onclick: () => dismiss(item.id),
        })
      : null,
  ])));
  for (const item of shown) item.fresh = false;
}

function dismiss(id) {
  const index = shown.findIndex(item => item.id === id);
  if (index < 0) return;
  clearTimeout(shown[index].timer);
  shown.splice(index, 1);
  draw();
}

export function notify(text, kind = 'info', duration = DEFAULT_MS) {
  const message = String(text || '').trim();
  if (!message) return;
  // The same message arriving twice in a row is one message. A refresh round
  // that keeps failing would otherwise fill the strip with copies of itself.
  const twin = shown.find(item => item.text === message && item.kind === kind);
  if (twin) {
    clearTimeout(twin.timer);
    if (duration) twin.timer = setTimeout(() => dismiss(twin.id), duration);
    return;
  }

  const item = { id: (nextId += 1), text: message, kind, timer: null,
                 fresh: true };
  shown.push(item);
  while (shown.length > MAX_VISIBLE) dismiss(shown[0].id);
  if (duration) item.timer = setTimeout(() => dismiss(item.id), duration);
  draw();
}

// `duration: 0` — an error stays until it is dismissed. It reports something
// that did NOT happen, and the reason is often the only copy there is.
export const showError = (m) => notify(m, 'error', 0);
export const showSuccess = (m) => notify(m, 'success');
