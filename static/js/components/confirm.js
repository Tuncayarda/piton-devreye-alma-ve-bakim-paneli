// The question asked before anything is written to a device.
//
// The rule this enforces: an operation that RESTARTS a device, CHANGES ITS
// ADDRESS or CUTS ITS POWER asks first, and says how many devices and which
// ports it is about to touch.
//
// Before this existed the rule was applied by memory, and memory got it
// backwards. Installing firmware and the factory reset each opened a dialog
// listing the devices; meanwhile "Start IP assignment" — which cycles PoE
// across a whole train and rewrites every address on it — went off a single
// click, and so did "Apply to 12 devices", which reboots each one through the
// SIP endpoint. The two heaviest operations in the panel were the two that
// asked for nothing. Somebody learning the panel would reasonably conclude
// that the dangerous ones are the ones that ask.
//
// The shape is the one the firmware dialog already used, because it was the
// right one: a sentence saying what will happen, any warnings that apply to
// this particular run, the list of what is affected, then Cancel and the
// action. Cancel comes first so it takes focus (see components/dialog.js),
// which means Enter and Escape both mean "no".

import { el } from '../core/dom.js';
import * as dialog from './dialog.js';
import { showError } from './toast.js';
import { t } from '../core/i18n.js';

/**
 * Ask, then run.
 *
 * `lead`      one sentence: what is about to happen, with the counts in it.
 * `notes`     [{ text, tone }] — 'info' for how it works, 'warning' for what
 *             the operator cannot undo. Falsy entries are dropped, so a
 *             conditional warning can be written inline.
 * `items`     [{ name, detail }] — the devices or ports affected, listed so
 *             "12 devices" is not something to take on trust.
 * `danger`    true for anything destructive; paints the confirm button red.
 * `run`       async () => {} — the write itself, plus whatever the caller
 *             does afterwards (queue, toast). Errors are reported here.
 */
export function confirmWrite({ title, lead, notes = [], items = [],
                               danger = false, confirmLabel, run }) {
  const content = el('div', {}, [
    el('p', { class: 'description', text: lead }),
    ...notes.filter(Boolean).map(note => el('p', {
      class: note.tone === 'warning' ? 'warning' : 'info',
      style: 'margin-top:10px', text: note.text,
    })),
    items.length
      ? el('div', { class: 'confirm-list' }, items.map(item => el('div', {
          class: 'row',
        }, [
          el('span', { class: 'mono truncate', text: item.name }),
          item.detail
            ? el('b', { class: 'mono truncate', text: item.detail })
            : null,
        ])))
      : null,
  ]);

  dialog.show({
    title,
    content,
    actions: [
      el('button', {
        type: 'button', class: 'btn', text: t('locked.cancel'),
        onclick: () => dialog.close(),
      }),
      el('button', {
        type: 'button',
        class: `btn ${danger ? 'btn-danger' : 'btn-primary'}`,
        text: confirmLabel,
        onclick: async () => {
          // Closed first: the write can take a moment to be accepted and a
          // dialog sitting there afterwards reads as "it did not go through".
          dialog.close();
          try {
            await run();
          } catch (error) {
            showError(error.message);
          }
        },
      }),
    ],
  });
}
