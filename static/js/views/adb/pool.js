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
        class: 'label',
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
        onclick: () => importList(list, actions),
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
        onclick: () => actions.exportList(),
      }),
      // Emptying the list one row at a time is the twelve rounds of
      // type-tab-type-Enter that `add_many` exists to avoid, run backwards:
      // a bench that has moved on to another train has a whole list to
      // throw away, not four addresses. Disabled while an operation runs,
      // like the row's own Remove — the run's targets are these addresses.
      el('button', {
        type: 'button', class: 'btn btn-small',
        text: t('adb.clearList'),
        disabled: running() || !list.length,
        onclick: () => clearList(list, actions),
      }),
    ]),
    dataTable({
      // The floor is the sum of the column minimums, the gaps between them
      // and the row's own padding — below it the grid cannot shrink any
      // further and spills past the row's right border instead. It was
      // sixteen pixels under it.
      template: COLUMNS, minWidth: 540, label: t('adb.deviceList'),
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

// The whole list at once. It asks for the same reason removing one address
// does — nothing reaches a device either way, and the list was typed in by
// hand — and it names every address it is about to drop, because "12
// addresses" is the number the operator is being asked to take on trust.
function clearList(list, actions) {
  confirmWrite({
    title: t('adb.clearListTitle'),
    lead: t('adb.clearListLead', { count: list.length }),
    items: list.map(entry => ({ name: entry.ip, detail: entry.label || '' })),
    confirmLabel: t('adb.clearList'),
    run: () => actions.clearList(),
  });
}

// An import REPLACES the list (panel/adb/pool.adopt), so it asks the same
// question clearing it does — and for the same reason, since the outcome for
// the addresses already there is the same. Only when there are any: an
// empty list has nothing to lose, and a dialog in front of the ordinary
// first import would be a click asking permission to do nothing.
function importList(list, actions) {
  if (!list.length) {
    actions.importList();
    return;
  }
  confirmWrite({
    title: t('adb.importReplaceTitle'),
    lead: t('adb.importReplaceLead', { count: list.length }),
    items: list.map(entry => ({ name: entry.ip, detail: entry.label || '' })),
    confirmLabel: t('adb.importList'),
    run: () => actions.importList(),
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
