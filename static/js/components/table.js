// The one place a data grid is built.
//
// Nine screens draw a table — devices, firmware, the IP plan, the checklist,
// the Excel preview, the address map, the project inventory, the settings
// window, the job history. Every one of them is a CSS grid made of `div`s,
// because the column widths are tuned per screen and a real `<table>` will
// not do that without a fight.
//
// The cost of that was invisible until somebody listened to it: with no
// `role`, a 42-row by 8-column grid reaches a screen reader as a heap of
// unrelated words. The state of a device is announced with no hint that it
// belongs under the "access state" heading, and there is no way to move by
// row or by column.
//
// So the roles are added here instead of in nine places. `dataTable` marks
// the header cells itself and walks each row it is handed, tagging the row
// and its cells — the caller keeps building rows exactly as before and does
// not have to remember. A cell that already carries a role keeps it.
//
// The markup shape is unchanged on purpose: `.table-wrap` still wraps
// `.table`, one wrapper per grid. `preserveScroll` in core/dom.js matches
// those wrappers BY DOCUMENT ORDER to restore horizontal scroll, so adding
// or removing one silently breaks scrolling on the screen that has two.

import { el } from '../core/dom.js';

function markRow(row) {
  if (!(row instanceof Element)) return row;
  if (!row.hasAttribute('role')) row.setAttribute('role', 'row');
  for (const cell of row.children) {
    if (!cell.hasAttribute('role')) cell.setAttribute('role', 'cell');
  }
  return row;
}

/**
 * A grid with the semantics of a table.
 *
 * `template` is the `grid-template-columns` value (the per-screen column
 * widths); `minWidth` the point below which the grid scrolls sideways inside
 * its own wrapper rather than squashing.
 *
 * `label` names the table for a screen reader — the screen's own heading,
 * not a description. Without it the table is announced as "table" and
 * nothing else, which on a screen holding two of them is no help.
 */
export function dataTable({ template, columns, rows, empty,
                            minWidth = 900, label, wrapClass = '' }) {
  const list = (rows || []).map(markRow);
  return el('div', {
    class: `table-wrap${wrapClass ? ` ${wrapClass}` : ''}`,
  }, [
    el('div', {
      class: 'table', role: 'table', 'aria-label': label || null,
      'aria-rowcount': String(list.length + 1),
      style: `--table-min:${minWidth}px`,
    }, [
      el('div', {
        class: 'table-head', role: 'row',
        style: `--table-columns:${template}`,
      }, (columns || []).map(column => (column instanceof Element
        ? (column.setAttribute('role', 'columnheader'), column)
        : el('span', { role: 'columnheader', text: column || '' })))),
      ...(list.length ? list : [el('div', {
        class: 'table-empty', role: 'row',
      }, [el('span', { role: 'cell', text: empty || '' })])]),
    ]),
  ]);
}
