// WHAT A SCREEN PUTS WHERE ITS CONTENT WOULD BE.
//
// Three situations, and they were being written five different ways across
// the screens: a dashed box on two, a table's own empty row, an `.info`
// paragraph on four, and two shapes the IP screen had built for itself. The
// same situation looked different depending on which screen the operator was
// standing on.
//
// They are also three different FACTS, and saying them with one sentence is
// how "the scan found nothing" and "the scan did not run" came to look alike:
//
//   loading()     nothing has arrived yet — a read is in flight
//   emptyState()  nothing is there — the read finished and found none
//   loadFailed()  it could not be read — say so, and say why
//
// A table keeps `dataTable`'s own `empty:` row. Inside a table the empty
// state belongs in the grid, where the columns still line up under their
// headings; putting one of these there instead would break the table in two.
import { el } from '../core/dom.js';

// `text` is always the caller's, from the catalogue: what is being read
// differs enough per screen ("Reading the switch panel", "Reading the
// verification") that one sentence for all of them would say nothing.
export function loading(text) {
  return el('div', {
    class: 'loading', role: 'status',
    'aria-live': 'polite', 'aria-busy': 'true',
  }, [
    el('i', { 'aria-hidden': 'true' }),
    // Left out entirely when there is nothing to say, rather than left
    // empty: an empty label still takes the row's gap and pushes the mark
    // off centre. Some waits are short enough to need no sentence.
    text ? el('span', { text }) : null,
  ]);
}

// `hint` is the second line: what to do about it, where there is something to
// do. Left out where there is not — an invented next step is worse than none.
export function emptyState(title, hint = '', { tall = false } = {}) {
  return el('div', {
    class: tall ? 'empty-state empty-state-tall' : 'empty-state',
  }, [
    el('p', { text: title }),
    hint ? el('p', { class: 'hint', text: hint }) : null,
  ]);
}

// Not an empty state. `role="alert"` because this one interrupts: the screen
// is not showing what the operator asked for and nothing else will say so.
export function loadFailed(text) {
  return el('p', { class: 'warning', role: 'alert', text });
}
