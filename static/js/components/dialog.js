// Modal dialog plumbing: focus handling, Escape, closing on a backdrop click.
// Focus enters the dialog when it opens and returns to the calling button
// when it closes.
import { el, fill, focusTrap, $ } from '../core/dom.js';

let open = null;

export function close() {
  if (!open) return;
  const { backdrop, release, previousFocus, onClose } = open;
  release();
  backdrop.remove();
  open = null;
  if (previousFocus && document.contains(previousFocus)) previousFocus.focus();
  // A dialog can also be closed with Escape or by clicking the backdrop; the
  // calling screen only learns the dialog closed from here.
  if (onClose) onClose();
}

export function show({ title, content, actions = [], width, onClose }) {
  close();
  const previousFocus = document.activeElement;

  const box = el('div', {
    class: 'dialog', role: 'dialog', 'aria-modal': 'true',
    'aria-labelledby': 'dialog-title',
    style: width ? `width:min(${width},100%)` : null,
  }, [
    el('h3', { id: 'dialog-title', text: title }),
    content,
    actions.length ? el('div', { class: 'actions' }, actions) : null,
  ]);

  const backdrop = el('div', {
    class: 'backdrop',
    onclick: (e) => { if (e.target === backdrop) close(); },
  }, [box]);

  fill($('#dialog-slot'), [backdrop]);
  const release = focusTrap(backdrop, close);
  open = { backdrop, release, previousFocus, onClose };

  const first = box.querySelector('input, button, select, textarea');
  if (first) first.focus();
  return { close };
}

export function isOpen() { return open !== null; }

// ── the two question shapes the panel asks ───────────────────────────────
// `show()` hands control to the buttons; these hand it back to the caller.
// A flow that has to CONTINUE after the answer — enter admin mode, then
// redraw; pick a project, then reload it — reads as a straight line that
// way instead of as a pair of callbacks, and the "closed without choosing"
// case cannot be forgotten: it is the same `false`/`null` as declining.

/** Yes or no. Cancel takes focus, so Enter and Escape both mean no. */
export function ask({ title, body, confirm, cancel }) {
  return new Promise((resolve) => {
    let answer = false;
    show({
      title,
      content: el('p', { class: 'description', text: body }),
      actions: [
        el('button', {
          type: 'button', class: 'btn', text: cancel,
          onclick: () => close(),
        }),
        el('button', {
          type: 'button', class: 'btn btn-primary', text: confirm,
          onclick: () => { answer = true; close(); },
        }),
      ],
      onClose: () => resolve(answer),
    });
  });
}

/**
 * One of several. `options` is [{ value, label, note, disabled }] — a
 * disabled entry is still LISTED, with its note saying why, because leaving
 * it out turns "you cannot have this yet" into "this does not exist".
 * Resolves to null when nothing was chosen.
 */
export function pick({ title, options, cancel }) {
  return new Promise((resolve) => {
    let answer = null;
    show({
      title,
      content: el('div', { class: 'pick-list' }, options.map(option => el(
        'button', {
          type: 'button', class: 'pick-item', disabled: !!option.disabled,
          onclick: () => { answer = option.value; close(); },
        }, [
          el('span', { class: 'pick-label', text: option.label }),
          option.note
            ? el('span', { class: 'pick-note', text: option.note })
            : null,
        ]))),
      actions: [
        el('button', {
          type: 'button', class: 'btn', text: cancel,
          onclick: () => close(),
        }),
      ],
      onClose: () => resolve(answer),
    });
  });
}
