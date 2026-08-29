// Which rows a click selects.
//
// Two screens select a list the same way — the switch faceplate picks ports,
// the device list picks devices — and a third would have copied it again. The
// rules are the ones every file manager has, and getting them subtly
// different on two screens is worse than either version.
//
// PURE. It takes the click, the order the rows are in and what was selected;
// it returns what should be selected now. No DOM, no module state, no import
// of a screen — the caller keeps its own set and hands it in. That is also
// what makes it testable without a browser (tests/js/selection_test.js).

const usesCommandKey = /Mac|iPhone|iPad|iPod/.test(
  (typeof navigator !== 'undefined'
    && (navigator.platform || navigator.userAgent)) || '');

// The key the operator holds to add to a selection, spelled the way their
// keyboard spells it.
export const selectionModifier = usesCommandKey ? '⌘' : 'Ctrl';

export function isSelectionModifier(event) {
  return usesCommandKey ? event.metaKey : event.ctrlKey || event.metaKey;
}

/**
 * The selection after a click.
 *
 * `order` is the ids in the order they appear on screen — that is what a
 * shift-click range means, so a sorted or filtered list must hand in the
 * order it is actually showing, not the underlying one.
 *
 * Returns a NEW set and the new anchor; nothing is mutated.
 */
export function clickSelect({ id, event, order, selected, anchor = null }) {
  const chosen = new Set(selected);

  // Shift extends from the anchor. With no anchor, or an anchor that has
  // since left the list, it falls through to a plain click rather than
  // selecting a range from nowhere.
  if (event.shiftKey && anchor !== null && order.includes(anchor)) {
    const from = order.indexOf(anchor);
    const to = order.indexOf(id);
    if (to >= 0) {
      if (!isSelectionModifier(event)) chosen.clear();
      order.slice(Math.min(from, to), Math.max(from, to) + 1)
        .forEach(each => chosen.add(each));
      return { selected: chosen, anchor };
    }
  }

  if (isSelectionModifier(event)) {
    if (chosen.has(id)) chosen.delete(id);
    else chosen.add(id);
    return { selected: chosen, anchor: id };
  }

  // Clicking the only selected row clears it, so a stray click is undone by
  // repeating it rather than by hunting for a "clear" button.
  const onlyThis = chosen.size === 1 && chosen.has(id);
  chosen.clear();
  if (!onlyThis) chosen.add(id);
  return { selected: chosen, anchor: onlyThis ? null : id };
}

// A row that has left the list cannot stay selected — it would be an
// invisible target for the next thing done to the selection.
export function pruneSelection(selected, order) {
  const known = new Set(order);
  return new Set([...selected].filter(id => known.has(id)));
}
