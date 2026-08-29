// Finding the applications by a word or two, and saying honestly what was
// found.
//
// The operator does not know the bundle id and should not have to. They type
// a word out of the name — "gebze" — and the devices are asked which of their
// packages contain it. SEVERAL WORDS, comma separated, because a bench rarely
// holds one kind of display: four devices running three customers'
// applications is the ordinary case, and one search that finds all three
// beats three searches.
//
// SEVERAL ANSWERS CAN BE CHOSEN, for the same reason. The operation bar then
// works on (device, bundle) pairs — see state.operationTargets — so
// "restart the application on all of them" means a different package name on
// each device and still one run.
//
// WHAT THIS SCREEN REFUSES TO HIDE. Several displays are searched at once and
// they need not agree: three have the application and the fourth does not,
// because somebody has not installed it yet. The obvious presentation — one
// list of package names — makes that fourth display invisible, and the
// operator finds out about it by pressing "start" and watching one row fail
// for no visible reason. So every result carries the devices it was found on,
// and the ones it is missing from are named.
//
// A device that could not be READ is a third thing again and is listed
// separately: "the application is not installed here" and "this address did
// not answer" have different fixes.

import { el } from '../../core/dom.js';
import { t } from '../../core/i18n.js';
import { local, running, selectedIps } from './state.js';
import { tagged } from './fields.js';

export function packagesCard(actions) {
  const answer = local.found;
  const chosen = selectedIps();

  const keywordField = el('input', {
    class: 'field adb-keyword', type: 'text', autocomplete: 'off',
    spellcheck: 'false', value: local.keyword,
    oninput: (event) => { local.keyword = event.target.value; },
  });

  return el('section', { class: 'card corner adb-packages' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('adb.application') }),
    ]),
    el('form', {
      class: 'adb-search',
      onsubmit: (event) => {
        event.preventDefault();
        // Focus has to leave the box or the results never draw: a focused
        // field holds the render back (see app.focusInScreenField).
        keywordField.blur();
        actions.search(keywordField.value);
      },
    }, [
      tagged('adb.keyword', keywordField),
      el('button', {
        type: 'submit', class: 'btn btn-primary',
        text: local.searching ? t('adb.searching') : t('adb.search'),
        disabled: local.searching || !chosen.length || running(),
        title: chosen.length ? '' : t('adb.selectDeviceFirst'),
      }),
    ]),
    ...results(answer, actions),
  ]);
}

function results(answer, actions) {
  if (!answer) return [];
  const found = answer.packages || [];
  const failed = answer.failed || [];
  const parts = [];

  if (!found.length) {
    parts.push(el('p', {
      class: 'info',
      text: t('adb.noPackageMatched',
              { word: (answer.keywords || []).join(', ') }),
    }));
  } else {
    parts.push(el('div', { class: 'adb-package-list' },
                 found.map(entry => packageRow(entry, actions))));
  }

  for (const row of failed) {
    parts.push(el('p', {
      class: 'warning',
      text: t('adb.deviceNotRead', { ip: row.ip, error: row.error }),
    }));
  }
  return parts;
}

// THE ADDRESSES IT IS ON, not the ones it is not. Naming the gaps was the
// first attempt and it reads backwards: the operator is choosing what to work
// on, so the useful list is the one the run will actually reach. When some
// devices are missing it, the line still says so — as a count, which is the
// part that matters — and the row keeps its warning colour.
function packageRow(entry, actions) {
  const on = local.packages.has(entry.name);
  const present = entry.present || [];
  const missing = entry.missing || [];
  return el('button', {
    type: 'button', class: 'checkbox adb-package',
    'aria-pressed': String(on),
    onclick: () => actions.choosePackage(entry.name),
  }, [
    el('span', { class: 'box', 'aria-hidden': 'true' }),
    el('span', { class: 'adb-package-text' }, [
      el('span', { class: 'mono truncate', text: entry.name }),
      el('span', {
        class: missing.length ? 'adb-package-warn' : 'adb-package-note',
        text: missing.length
          ? t('adb.presentOnSomeDevices', {
            list: present.join(', '), missing: missing.length,
          })
          : t('adb.presentOnAllDevices', { list: present.join(', ') }),
      }),
    ]),
  ]);
}
