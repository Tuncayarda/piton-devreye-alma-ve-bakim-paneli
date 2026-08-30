// The one search box.
//
// NO PLACEHOLDER. Grey example text inside a box reads as content until you
// look twice, it vanishes the moment somebody starts typing, and it is gone
// for good once the box holds a word — which is exactly when somebody coming
// back to the screen wants to know what the box does. The ADB screen settled
// this for its own fields by putting the name in FRONT of the box and
// leaving it there (see views/adb/fields.js); this is the same answer for
// the one field whose name is a picture in every application ever written.
//
// So: a magnifier at the left edge, inside the box, that does not move and
// does not go away. The sentence a placeholder would have carried goes on
// the field's `title` and its `aria-label`, where it is there for the asking
// and for a screen reader, and is not shouting at anyone who already knows
// what a magnifier is.
//
// Both of the panel's search boxes are built here — the device list's, which
// filters as it is typed, and the ADB package search, which is submitted —
// so they cannot drift apart.

import { el, icon } from '../core/dom.js';

// The glass and its handle, drawn in the same 20×20 space as the menu rail's
// icons so it sits at the weight of everything else the panel draws.
const GLASS = [
  'M8.6 3.6a5 5 0 1 0 0 10a5 5 0 0 0 0-10',
  'M12.3 12.3 16.4 16.4',
];

/**
 * A search box.
 *
 * `attributes` go to the `input` — `value`, `oninput`, `title`, `aria-label`
 * and anything else the caller needs; the type and the class are fixed here.
 * `wrapClass` is how the calling screen gives the box its width, because the
 * wrapper is what is laid out, not the input inside it.
 *
 * Returns the wrapper. A caller that needs the field itself — the ADB search
 * blurs it on submit — reads it back with `.querySelector('input')`.
 */
export function searchField(attributes = {}, wrapClass = '') {
  return el('div', {
    class: wrapClass ? `search-field ${wrapClass}` : 'search-field',
  }, [
    el('span', { class: 'search-glass', 'aria-hidden': 'true' },
       [icon(GLASS)]),
    el('input', {
      autocomplete: 'off', spellcheck: 'false',
      ...attributes,
      // `type=search` for the browser's own clear button: a box that filters
      // a list wants a one-click way back to the whole list.
      type: 'search', class: 'search-input field',
    }),
  ]);
}
