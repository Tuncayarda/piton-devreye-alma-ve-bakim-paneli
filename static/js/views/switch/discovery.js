// Finding the switches: the sweep, and the list of what it found.
//
// The sweep is a QUEUED JOB, not an inline request (see
// panel/api/routes/switch_routes.py). A /24 is 254 addresses and runs for
// minutes; done inline it would block the bridge and freeze every other
// screen. So this card starts a job and the screen polls — the same
// arrangement the device scan uses.
//
// The result is kept on the SERVER, so coming back to this screen shows what
// the last sweep found instead of starting another one.

import { el } from '../../core/dom.js';
import { api } from '../../core/api.js';
import { state, patch } from '../../core/store.js';
import { dataTable } from '../../components/table.js';
import { showError } from '../../components/toast.js';
import { t } from '../../core/i18n.js';
import { discovered, local, scanning, selectedIp, typed } from './state.js';

// Address · name · model · version · username · password · connect.
//
// THE CREDENTIALS ARE IN THE ROW, not in a dialog that opens over the screen.
// An operator with six switches on a bench signs into them one after another,
// and a modal for each meant six openings, six closings and the list hidden
// behind every one of them. Here the boxes sit on the row they belong to and
// the whole bench is visible while it is worked through.
const COLUMNS = 'minmax(104px,.6fr) minmax(120px,1fr) minmax(110px,.8fr) '
  + 'minmax(84px,.5fr) minmax(96px,.6fr) minmax(96px,.6fr) 92px';

export function discoveryCard(actions) {
  const found = discovered();
  const busy = scanning();

  return el('section', { class: 'card corner switch-discovery' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('switch.discoveryTitle') }),
      el('span', { class: 'spacer' }),
      el('span', {
        class: 'label',
        text: t('switch.discoveryFoundCount', { count: found.length }),
      }),
    ]),
    scanForm(actions, busy),
    dataTable({
      template: COLUMNS, minWidth: 780, label: t('switch.discoveryTitle'),
      columns: [t('switch.columnAddress'), t('switch.columnName'),
                t('switch.columnModel'), t('switch.columnVersion'),
                t('switch.authUsername'), t('switch.authPassword'), ''],
      rows: found.map(entry => switchRow(entry, actions)),
      empty: busy ? t('switch.discoverySearching')
        : t('switch.discoveryNothingYet'),
    }),
  ]);
}

// TWO FIELDS, NOT ONE. "10.1.1.0-255/24" is one string to the server and two
// separate decisions to the operator: which addresses to knock on, and which
// network they belong to. They are also answered from different places — the
// range comes off the commissioning sheet, the mask off the project — and a
// single box meant retyping the whole thing to change either.
//
// The mask is a list rather than a box: /8, /16 and /24 are the three the
// switch itself accepts (panel/switch/network.py), so anything else typed
// there could only be a mistake.
const PREFIXES = ['8', '16', '24'];

function scanForm(actions, busy) {
  const range = el('input', {
    class: 'field switch-range-field', type: 'text', autocomplete: 'off',
    spellcheck: 'false', inputmode: 'decimal',
    'aria-label': t('switch.discoveryRange'),
    value: local.range,
    oninput: (event) => { local.range = event.target.value; },
  });
  const prefix = el('select', {
    class: 'field switch-prefix-field',
    'aria-label': t('switch.discoveryPrefix'),
    onchange: (event) => { local.prefix = event.target.value; },
  }, PREFIXES.map(value => el('option', {
    value, selected: value === local.prefix, text: `/${value}`,
  })));

  return el('form', {
    class: 'switch-scan-form',
    onsubmit: (event) => {
      event.preventDefault();
      // A focused field holds the whole redraw back (see app.js's
      // focusInScreenField), so the row this starts would never appear.
      range.blur();
      actions.discover(`${range.value.trim()}/${prefix.value}`);
    },
  }, [
    el('label', { class: 'switch-scan-label' }, [
      el('span', { class: 'label', text: t('switch.discoveryRange') }),
      range,
    ]),
    el('label', { class: 'switch-scan-label' }, [
      el('span', { class: 'label', text: t('switch.discoveryPrefix') }),
      prefix,
    ]),
    el('div', { class: 'switch-scan-actions' }, [
      el('button', {
        type: 'submit', class: 'btn btn-primary', disabled: busy,
        text: busy ? t('switch.discoverySearching') : t('switch.buttonScan'),
      }),
      el('button', {
        type: 'button', class: 'btn', disabled: !busy,
        text: t('switch.buttonStopScan'),
        onclick: () => actions.cancelDiscover(),
      }),
    ]),
  ]);
}

function credentialField(entry, key, actions) {
  // A switch already signed into needs no boxes: the account is in memory
  // and the columns say what it told us. An empty pair of inputs beside a
  // switch that is working reads as something still to do.
  if (!entry.locked) return el('span', { class: 'muted', text: '—' });
  const store = typed(entry.ip);
  return el('input', {
    class: 'field switch-credential',
    type: key === 'password' ? 'password' : 'text',
    autocomplete: 'off', spellcheck: 'false',
    'aria-label': t(key === 'password' ? 'switch.authPasswordFor'
      : 'switch.authUsernameFor', { ip: entry.ip }),
    value: store[key],
    oninput: (event) => { store[key] = event.target.value; },
    onkeydown: (event) => {
      // Enter finishes the pair the way a form would; there is no form here
      // because the row is a grid cell, not a container.
      if (event.key !== 'Enter') return;
      event.preventDefault();
      event.target.blur();
      actions.connectSwitch(entry.ip);
    },
  });
}

function switchRow(entry, actions) {
  const open = entry.ip === selectedIp();
  // A locked switch has told us its address and nothing else. The empty
  // columns say that better than a badge crowded in beside the name did.
  const unknown = () => el('span', { class: 'muted', text: '—' });
  return el('div', {
    class: 'table-row switch-row', 'aria-selected': String(open),
    dataset: { selected: open ? '1' : '0', locked: entry.locked ? '1' : '0' },
    style: `--table-columns:${COLUMNS}`,
  }, [
    el('span', { class: 'mono', text: entry.ip }),
    entry.locked ? unknown()
      : el('span', { class: 'truncate', text: entry.name || '—' }),
    entry.locked ? unknown()
      : el('span', { class: 'truncate', text: entry.model || '—' }),
    entry.locked ? unknown()
      : el('span', { class: 'mono truncate', text: entry.version || '—' }),
    credentialField(entry, 'user', actions),
    credentialField(entry, 'password', actions),
    el('button', {
      type: 'button',
      class: open ? 'btn btn-small btn-primary' : 'btn btn-small',
      text: t('switch.buttonConnect'),
      onclick: () => actions.connectSwitch(entry.ip),
    }),
  ]);
}

// Seed the network box from the server's default the first time only: after
// that it is whatever the operator typed, and overwriting it on every poll
// would erase the network they are about to scan.
export function seedCidr() {
  if (local.range) return;
  const body = state.switchState;
  const preset = (body && body.defaultCidr) || '';
  const [range, prefix] = preset.split('/');
  local.range = range || '';
  if (prefix) local.prefix = prefix;
}

export async function startDiscovery(cidr, after) {
  try {
    await api.switchDiscover(cidr);
    patch({ switchState: { ...(state.switchState || {}), scanning: true } });
  } catch (error) {
    showError(error.message);
  }
  if (after) after();
}

export async function stopDiscovery(after) {
  try {
    await api.switchDiscoverCancel();
  } catch (error) {
    showError(error.message);
  }
  if (after) after();
}
