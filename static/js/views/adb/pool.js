// The address list: adding, removing, importing, and choosing what to work on.
//
// THIS IS THE FIRST MULTI-SELECT LIST IN THE PANEL. Everywhere else a screen
// works on one device, on a group, or on "everything in the set" — all three
// answerable with a picker. Here the operator has four displays on a bench
// and wants three of them, so the row itself has to be selectable.
//
// It reuses the idiom the panel already has rather than inventing one: the
// `.checkbox` + `.box` mark from the credential dialog, and `aria-selected`
// on the row, which `button.table-row[aria-selected="true"]` already paints.
// A real `<input type=checkbox>` would have been a fifth form control style
// to maintain for a control the design system does not otherwise use.

import { el } from '../../core/dom.js';
import { dataTable } from '../../components/table.js';
import { confirmWrite } from '../../components/confirm.js';
import { t } from '../../core/i18n.js';
import { local, devices, running, selectedIps } from './state.js';

const COLUMNS = '38px minmax(120px,.8fr) minmax(140px,1.4fr) 96px';

export function poolCard(actions) {
  const list = devices();
  const chosen = new Set(selectedIps());
  const allOn = list.length > 0 && chosen.size === list.length;

  return el('section', { class: 'card corner adb-pool' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('adb.deviceList') }),
      el('span', { class: 'spacer' }),
      el('span', {
        class: 'eyebrow',
        text: t('adb.selectedOfTotal',
                { selected: chosen.size, total: list.length }),
      }),
    ]),
    el('p', { class: 'description', text: t('adb.deviceListNote') }),
    addForm(actions),
    el('div', { class: 'adb-pool-tools' }, [
      el('button', {
        type: 'button', class: 'btn btn-small',
        text: allOn ? t('adb.selectNone') : t('adb.selectAll'),
        disabled: !list.length,
        onclick: () => actions.selectAll(!allOn),
      }),
      el('button', {
        type: 'button', class: 'btn btn-small',
        text: local.importing ? t('adb.importing') : t('adb.importList'),
        disabled: local.importing,
        title: t('adb.importHint'),
        onclick: () => actions.importList(),
      }),
    ]),
    dataTable({
      template: COLUMNS, minWidth: 520, label: t('adb.deviceList'),
      columns: ['', t('adb.columnAddress'), t('adb.columnLabel'), ''],
      rows: list.map(entry => deviceRow(entry, chosen, actions)),
      empty: t('adb.noDeviceYet'),
    }),
  ]);
}

function deviceRow(entry, chosen, actions) {
  const on = chosen.has(entry.ip);
  return el('div', {
    class: 'table-row adb-row', 'aria-selected': String(on),
    dataset: { selected: on ? '1' : '0' },
    style: `--table-columns:${COLUMNS}`,
  }, [
    el('button', {
      type: 'button', class: 'checkbox adb-tick', 'aria-pressed': String(on),
      // The row is a grid cell, so the label the row cannot show goes here.
      'aria-label': t('adb.selectDevice', { ip: entry.ip }),
      onclick: () => actions.toggle(entry.ip),
    }, [el('span', { class: 'box', 'aria-hidden': 'true' })]),
    el('span', { class: 'mono', text: entry.ip }),
    el('span', { class: 'truncate', text: entry.label || '—' }),
    el('button', {
      type: 'button', class: 'btn btn-small',
      text: t('adb.remove'),
      disabled: running(),
      onclick: () => removeDevice(entry, actions),
    }),
  ]);
}

// Removing an address writes nothing to a device, so this asks for the
// operator's sake rather than the display's: the list is typed in by hand and
// an accidental click on a small button in a long row is how it gets lost.
function removeDevice(entry, actions) {
  confirmWrite({
    title: t('adb.removeDeviceTitle'),
    lead: t('adb.removeDeviceLead', { ip: entry.ip }),
    notes: [{ text: t('adb.removeDeviceNote'), tone: 'info' }],
    items: [{ name: entry.ip, detail: entry.label || '' }],
    confirmLabel: t('adb.remove'),
    run: () => actions.removeDevice(entry.ip),
  });
}

function addForm(actions) {
  const ipField = el('input', {
    class: 'field adb-ip-field', type: 'text', inputmode: 'decimal',
    autocomplete: 'off', spellcheck: 'false',
    'aria-label': t('adb.columnAddress'),
    placeholder: '10.1.1.40', value: local.newIp,
    oninput: (event) => { local.newIp = event.target.value; },
  });
  const labelField = el('input', {
    class: 'field', type: 'text', autocomplete: 'off',
    'aria-label': t('adb.columnLabel'),
    placeholder: t('adb.labelPlaceholder'), value: local.newLabel,
    oninput: (event) => { local.newLabel = event.target.value; },
  });
  const warning = el('p', {
    class: 'warning', role: 'alert', hidden: !local.addError,
    text: local.addError,
  });

  return el('form', {
    class: 'adb-add',
    onsubmit: (event) => {
      event.preventDefault();
      // A FOCUSED FIELD HOLDS THE WHOLE RENDER BACK (see
      // app.focusInScreenField — it is what stops a refresh round wiping
      // out what somebody is typing). Submitting with Enter leaves focus in
      // the box, so without this the new row never appears and neither does
      // the warning under it. The entry is finished, so focus leaves.
      ipField.blur();
      labelField.blur();
      actions.addDevice(ipField.value, labelField.value);
    },
  }, [
    el('div', { class: 'adb-add-fields' }, [
      ipField, labelField,
      el('button', {
        type: 'submit', class: 'btn btn-primary', text: t('adb.addDevice'),
      }),
    ]),
    warning,
  ]);
}
