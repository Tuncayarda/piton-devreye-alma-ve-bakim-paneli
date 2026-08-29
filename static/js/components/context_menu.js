// The right-click menu, for any screen that has one.
//
// It started on the switch faceplate, where a round trip to the table below
// was the slow way to change ports the operator had just selected. The same
// argument applies to the device list — reading one device meant opening the
// drawer first — so the shell moved here and the switch became its first
// caller rather than its owner.
//
// What is generic is everything that was hard: keeping the menu on screen
// when it opens near an edge, closing on an outside click or Escape without
// also closing whatever is behind it, and redrawing in place while it is open
// so a poll landing mid-decision does not leave stale state under the cursor.
//
// What is NOT here is the menu's content or its meaning. The caller builds
// the rows and decides what a pick does; `build` is called again on every
// redraw, so it reads live state each time instead of capturing it.

import { el, fill } from '../core/dom.js';

// Above the screen's own panels, below a modal dialog: a shortcut on top of
// the work, not a question that blocks it. The value lives in the stylesheet
// (`.pm-menu`); this comment is here because that is the decision.
const EDGE = 8;

let open = null;

export function isOpen() {
  return open !== null;
}

export function close() {
  if (!open) return;
  open.node.remove();
  document.removeEventListener('mousedown', open.onOutside, true);
  document.removeEventListener('keydown', open.onKey, true);
  open = null;
}

// Put the menu under the cursor, but never off the edge. A menu opened near
// the bottom right would otherwise hang off it, and the footer — where the
// Apply button is — goes first.
function place(node, event) {
  const box = node.getBoundingClientRect();
  node.style.left = `${Math.max(EDGE, Math.min(
    event.clientX, globalThis.innerWidth - box.width - EDGE))}px`;
  node.style.top = `${Math.max(EDGE, Math.min(
    event.clientY, globalThis.innerHeight - box.height - EDGE))}px`;
}

/**
 * Open a menu at the cursor.
 *
 * `build(redraw)` returns the menu's children, or null when there is nothing
 * left to show — a selection that vanished under a poll, say — in which case
 * the menu closes instead of standing there empty. Call the `redraw` it is
 * handed after changing anything the rows display.
 */
export function openMenu(event, build) {
  close();
  const node = el('div', { class: 'pm-menu', role: 'menu' });

  let live = true;
  const draw = () => {
    const children = build(draw);
    if (!children) { live = false; close(); return; }
    fill(node, children);
  };

  draw();
  if (!live) return;

  document.body.append(node);
  place(node, event);

  const onOutside = (e) => { if (!node.contains(e.target)) close(); };
  const onKey = (e) => {
    if (e.key !== 'Escape') return;
    // Stopped here, or Escape would also close whatever is behind the menu.
    e.stopPropagation();
    close();
  };
  open = { node, draw, onOutside, onKey };
  // Registered on the next tick: the mousedown that opened this menu is still
  // travelling, and it would close it again immediately.
  globalThis.setTimeout(() => {
    document.addEventListener('mousedown', onOutside, true);
    document.addEventListener('keydown', onKey, true);
  });
}

// Redraw an open menu from the outside — for a screen that polls while the
// menu is up. Does nothing when no menu is open.
export function refresh() {
  if (open) open.draw();
}

// ── the pieces a menu is made of ────────────────────────────────────────
// Shared so two screens' menus look like one thing rather than two.

export function menuHead(title, subtitle) {
  return el('div', { class: 'pm-menu-head' }, [
    el('div', { class: 'pm-menu-title', text: title }),
    subtitle
      ? el('div', { class: 'pm-menu-subtitle', text: subtitle })
      : null,
  ]);
}

export function menuHeading(text) {
  return el('div', { class: 'pm-menu-heading', text });
}

// `note` is the right-hand column: what is already true of the selection, so
// the operator can see how uniform it is before changing it.
export function menuItem(label, { selected = false, note = '', disabled = false,
                                  onPick } = {}) {
  return el('button', {
    type: 'button',
    class: `pm-menu-item${selected ? ' is-selected' : ''}`,
    disabled,
    onclick: onPick,
  }, [
    el('i', { class: 'pm-menu-mark', 'aria-hidden': 'true' }),
    el('span', { class: 'pm-menu-label', text: label }),
    note ? el('span', { class: 'pm-menu-state', text: note }) : null,
  ]);
}

export function menuFoot(buttons) {
  return el('div', { class: 'pm-menu-foot' }, buttons);
}
