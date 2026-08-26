// The device list. Clicking a row opens the detail drawer.
//
// Scan progress is not shown in this list; the live step-by-step state lives
// in the job queue. The list always shows a device's last known state.

import { el, fill } from '../core/dom.js';
import { dataTable } from '../components/table.js';
import { state, patch, visibleDevices } from '../core/store.js';
import {
  value, stateLabel, versionOf, uptimeOf, typeLabel,
} from '../core/format.js';
import * as detail from '../components/detail.js';
import { t } from '../core/i18n.js';

// The "Switch · port" column carries the switch's full name (Yataklı_1 · p11);
// left narrow, the text did not fit.
const COLUMNS = 'minmax(180px,1.4fr) minmax(140px,1fr) minmax(150px,1fr) '
  + '120px 100px 120px 96px';

// One entry per column, in the same order as `headings` below: what a click
// on that heading sorts by. An address sorts by its octets, not as text —
// otherwise 10.1.1.100 lands between .1 and .2.
const SORTS = [
  { id: 'name', of: d => (d.name || '').toLowerCase() },
  { id: 'type', of: d => (d.typeLabel || '').toLowerCase() },
  { id: 'port', of: d => (d.portLabel || '').toLowerCase() },
  { id: 'ip', of: d => ipOrder(d.ip) },
  { id: 'version', of: d => (versionOf(d) || '').toLowerCase() },
  { id: 'state', of: d => STATE_ORDER.indexOf((d.result || {}).state) },
  { id: 'uptime', of: d => Number(uptimeOf(d)) || 0 },
];

// Worst first when sorting by state: the reason to sort by it at all is to
// bring what needs attention to the top.
const STATE_ORDER = ['failed', 'auth', 'unknown', 'ok'];

function ipOrder(text) {
  return String(text || '').split('.')
    .reduce((total, part) => (total * 256) + (Number(part) || 0), 0);
}

// Keys, not text — see action_tabs.js: the module loads before the
// catalogue arrives.
const FILTERS = [
  { id: 'all', labelKey: 'group.all' },
  { id: 'active', labelKey: 'devices.reachable' },
  { id: 'problem', labelKey: 'devices.needsReview' },
];

export function render(root) {
  const categories = state.meta ? state.meta.categories : [];
  const category = categories.find(c => c.id === state.category);
  const devices = visibleDevices();
  const categoryTotal = state.category === 'all'
    ? state.devices.length
    : state.devices.filter(d => d.category === state.category).length;

  const parts = [];

  parts.push(el('div', { class: 'page-head' }, [
    el('div', {}, [
      el('h2', { text: t('nav.devices') }),
      el('div', {
        class: 'page-sub',
        text: t('devices.categoryCount', {
          category: category ? category.name : t('devices.allDevices'),
          count: categoryTotal,
        }),
      }),
    ]),
    el('div', { class: 'device-head-actions' }, [
      searchBox(root),
      el('div', {
        class: 'local-tabs',
        role: 'group', 'aria-label': t('devices.stateFilter'),
      }, FILTERS.map(filter => el('button', {
        type: 'button',
        class: 'local-tab',
        'aria-pressed': String(state.filter === filter.id),
        text: t(filter.labelKey),
        onclick: () => patch({ filter: filter.id }),
      }))),
    ]),
  ]));

  // Categories are not top-level screens but a filter over the device list.
  parts.push(el('div', {
    class: 'chip-bar device-category-bar', role: 'group',
    'aria-label': t('devices.deviceCategory'),
  }, [
    el('span', { class: 'label', text: t('checklist.category') }),
    ...categories.map(entry => {
      const count = entry.id === 'all'
        ? state.devices.length
        : state.devices.filter(d => d.category === entry.id).length;
      return el('button', {
        type: 'button', class: 'chip', title: entry.types,
        'aria-pressed': String(state.category === entry.id),
        onclick: () => patch({ category: entry.id, subtype: null }),
      }, [
        el('span', { text: entry.name }),
        el('span', { class: 'count', text: String(count) }),
      ]);
    }),
  ]));

  const headings = ['col.device', 'col.typeSubtypeLower', 'col.switchPort',
    'col.ip', 'col.version', 'col.accessState', 'col.uptime'];

  const rows = sorted(devices).map(device => {
    const result = device.result || {};
    return el('button', {
      type: 'button', class: 'table-row',
      style: `--table-columns:${COLUMNS}`,
      'aria-selected': String(state.detailId === device.id),
      title: result.detail || '',
      onclick: () => detail.open(device.id),
    }, [
      el('span', {
        style: 'display:flex;align-items:center;gap:8px;min-width:0',
      }, [
        el('span', {
          class: 'dot', dataset: { state: result.state },
          'aria-hidden': 'true',
        }),
        el('span', {
          class: 'mono truncate t-base',
          text: device.name,
        }),
      ]),
      el('span', {
        class: 'text-bright truncate t-base',
        text: typeLabel(device.typeLabel),
      }),
      el('span', {
        class: 'mono text-mid truncate t-sm',
        title: device.portLabel, text: device.portLabel,
      }),
      el('span', { class: 'mono t-base', text: device.ip }),
      el('span', {
        // A version the device really reported is worth seeing; the dash
        // that stands in for "not read yet" is not.
        class: versionOf(device)
          ? 'mono truncate t-sm version-read' : 'mono truncate t-sm text-dim',
        text: value(versionOf(device)),
      }),
      el('span', {
        class: 'state-text state-label', dataset: { state: result.state },
        text: stateLabel(result.state, ' '),
      }),
      el('span', {
        class: 'mono text-mid t-sm',
        text: value(uptimeOf(device)),
      }),
    ]);
  });

  parts.push(dataTable({
    template: COLUMNS, minWidth: 960, label: t('nav.devices'),
    columns: headings.map((key, index) => sortHeader(root, key, index)),
    rows,
    empty: t('devices.noDeviceMatchesTheseCriteria'),
  }));

  fill(root, parts);
}

// Typing in a box on the screen SUPPRESSES the application's own render (see
// app.js focusInScreenField) — which is what stops a refresh round wiping
// what somebody is halfway through typing. The list would therefore never
// filter while the box has focus, so this screen redraws itself and puts the
// caret back where it was.
function searchBox(root) {
  return el('input', {
    type: 'search', id: 'device-search', class: 'field device-search',
    value: state.deviceSearch || '',
    placeholder: t('devices.searchPlaceholder'),
    'aria-label': t('devices.searchPlaceholder'),
    autocomplete: 'off', spellcheck: 'false',
    oninput: (event) => {
      const caret = event.target.selectionStart;
      patch({ deviceSearch: event.target.value });
      render(root);
      const again = root.querySelector('#device-search');
      if (!again) return;
      again.focus();
      again.setSelectionRange(caret, caret);
    },
  });
}

function sorted(devices) {
  const chosen = SORTS.find(entry => entry.id === state.deviceSort);
  if (!chosen) return devices;
  const direction = state.deviceSortDesc ? -1 : 1;
  // A copy: `visibleDevices` hands back a filtered array, but sorting the
  // list the caller holds is the kind of thing that bites later.
  return [...devices].sort((one, other) => {
    const left = chosen.of(one);
    const right = chosen.of(other);
    if (left === right) return 0;
    return (left > right ? 1 : -1) * direction;
  });
}

function sortHeader(root, key, index) {
  const entry = SORTS[index];
  const label = key ? t(key) : '';
  if (!entry) return el('span', { role: 'columnheader', text: label });
  const active = state.deviceSort === entry.id;
  return el('span', {
    role: 'columnheader',
    'aria-sort': active ? (state.deviceSortDesc ? 'descending' : 'ascending')
      : 'none',
  }, [
    el('button', {
      type: 'button', class: 'sort-btn', 'aria-pressed': String(active),
      onclick: () => {
        patch(active
          ? { deviceSortDesc: !state.deviceSortDesc }
          : { deviceSort: entry.id, deviceSortDesc: false });
        render(root);
      },
    }, [
      el('span', { text: label }),
      el('span', {
        class: 'sort-mark', 'aria-hidden': 'true',
        text: active ? (state.deviceSortDesc ? '\u25BE' : '\u25B4') : '',
      }),
    ]),
  ]);
}
