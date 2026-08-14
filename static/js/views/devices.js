// The device list. Clicking a row opens the detail drawer.
//
// Scan progress is not shown in this list; the live step-by-step state lives
// in the job queue. The list always shows a device's last known state.

import { el, fill } from '../core/dom.js';
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

  const rows = devices.map(device => {
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
          class: 'mono truncate', style: 'font-size:12.5px',
          text: device.name,
        }),
      ]),
      el('span', {
        class: 'text-bright truncate', style: 'font-size:12.5px',
        text: typeLabel(device.typeLabel),
      }),
      el('span', {
        class: 'mono text-mid truncate', style: 'font-size:11px',
        title: device.portLabel, text: device.portLabel,
      }),
      el('span', { class: 'mono', style: 'font-size:12px', text: device.ip }),
      el('span', {
        class: 'mono truncate', style: 'font-size:11.5px'
          + (versionOf(device) ? ';color:var(--ok)' : ';color:var(--text-dim)'),
        text: value(versionOf(device)),
      }),
      el('span', {
        class: 'state-text', dataset: { state: result.state },
        style: 'font-family:var(--font-heading);font-weight:600;font-size:13px;'
          + 'letter-spacing:.08em;text-transform:uppercase',
        text: stateLabel(result.state, ' '),
      }),
      el('span', {
        class: 'mono text-mid', style: 'font-size:11px',
        text: value(uptimeOf(device)),
      }),
    ]);
  });

  parts.push(el('div', { class: 'table-wrap' }, [
    el('div', { class: 'table', style: '--table-min:960px' }, [
      el('div', {
        class: 'table-head', style: `--table-columns:${COLUMNS}`, role: 'row',
      }, headings.map(key => el('span', { text: key ? t(key) : '' }))),
      ...(rows.length ? rows
        : [el('div', {
          class: 'table-empty', text: t('devices.noDeviceMatchesTheseCriteria'),
        })]),
    ]),
  ]));

  fill(root, parts);
}
