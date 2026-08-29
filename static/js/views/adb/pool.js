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
import { tagged } from './fields.js';

const COLUMNS = '38px minmax(120px,.8fr) minmax(140px,1.4fr) 190px';

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
        onclick: () => actions.importList(),
      }),
      // Beside the import and disabled on an empty list: a button that
      // writes a file with nothing in it is a button that has to be
      // explained afterwards.
      // And the whole selection at once, beside the other bulk buttons.
      el('button', {
        type: 'button', class: 'btn btn-small btn-danger',
        text: t('adb.rebootSelected'),
        disabled: running() || !chosen.size,
        onclick: () => confirmReboot([...chosen], actions),
      }),
      el('button', {
        type: 'button', class: 'btn btn-small',
        text: local.exporting ? t('adb.exporting') : t('adb.exportList'),
        disabled: local.exporting || !list.length,
        title: list.length ? '' : t('adb.exportEmpty'),
        onclick: () => actions.exportList(),
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
    el('div', { class: 'adb-row-actions' }, [
      // One display, on its own row, without ticking it first. Restarting a
      // single display is the common case and it belongs next to that
      // display — it used to live at the bottom of the operations card,
      // where it worked on the selection and nothing else.
      el('button', {
        type: 'button', class: 'btn btn-small btn-danger',
        text: t('adb.reboot'),
        disabled: running(),
        onclick: () => confirmReboot([entry.ip], actions),
      }),
      el('button', {
        type: 'button', class: 'btn btn-small',
        text: t('adb.remove'),
        disabled: running(),
        onclick: () => removeDevice(entry, actions),
      }),
    ]),
  ]);
}

// The confirmation, shared by the row button and the one above the table.
// A reboot cuts the display off for about a minute; on a train being
// commissioned that is something the person standing next to it should have
// agreed to (the panel's rule — see components/confirm.js).
export function confirmReboot(ips, actions) {
  const labels = new Map(devices().map(entry => [entry.ip, entry.label]));
  confirmWrite({
    title: t('adb.rebootTitle'),
    lead: t('adb.rebootLead', { count: ips.length }),
    notes: [{ text: t('adb.rebootNote'), tone: 'warning' }],
    items: ips.map(ip => ({ name: ip, detail: labels.get(ip) || '' })),
    danger: true,
    confirmLabel: t('adb.reboot'),
    // No pairs: the machine is the target, so the server collapses the
    // addresses to one row each (panel/adb/runner._pairs).
    run: () => actions.run('reboot', {}, ips.map(ip => ({ ip }))),
  });
}

// Removing an address writes nothing to a device, so this asks for the
// operator's sake rather than the display's: the list is typed in by hand and
// an accidental click on a small button in a long row is how it gets lost.
function removeDevice(entry, actions) {
  confirmWrite({
    title: t('adb.removeDeviceTitle'),
    lead: t('adb.removeDeviceLead', { ip: entry.ip }),
    items: [{ name: entry.ip, detail: entry.label || '' }],
    confirmLabel: t('adb.remove'),
    run: () => actions.removeDevice(entry.ip),
  });
}

function addForm(actions) {
  const ipField = el('input', {
    class: 'field adb-ip-field', type: 'text', inputmode: 'decimal',
    autocomplete: 'off', spellcheck: 'false',
    value: local.newIp,
    oninput: (event) => { local.newIp = event.target.value; },
  });
  const labelField = el('input', {
    class: 'field', type: 'text', autocomplete: 'off',
    value: local.newLabel,
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
      tagged('col.ip', ipField),
      tagged('adb.columnLabel', labelField),
      el('button', {
        type: 'submit', class: 'btn btn-primary', text: t('adb.addDevice'),
      }),
    ]),
    warning,
  ]);
}
