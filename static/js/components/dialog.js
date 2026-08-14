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
