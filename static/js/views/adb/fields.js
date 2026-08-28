// The one text-box shape this screen uses.
//
// NO PLACEHOLDERS HERE. Grey example text inside a box reads as content until
// you look twice, and this screen has three boxes and four tables competing
// for the same glance: the boxes were the loudest thing on it and said the
// least, and the example vanished the moment somebody started typing. The
// name of the field now sits in FRONT of the box and stays there — which is
// also the one thing a placeholder could never do.
//
// The `<label>` wraps the box, so the tag is the field's accessible name and
// no `aria-label` is needed beside it. Examples ("10.1.1.45-47") go on the
// field's `title`, where they are there for the asking and not shouting.

import { el } from '../../core/dom.js';
import { t } from '../../core/i18n.js';

export function tagged(key, field) {
  return el('label', { class: 'adb-field' }, [
    el('span', { class: 'adb-field-tag', text: t(key) }),
    field,
  ]);
}
