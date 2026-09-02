// The device list. Clicking a row opens the detail drawer.
//
// Scan progress is not shown in this list; the live step-by-step state lives
// in the job queue. The list always shows a device's last known state.

import { el, fill } from '../core/dom.js';
import { api } from '../core/api.js';
import { dataTable } from '../components/table.js';
import { state, patch, visibleDevices, stateSpread } from '../core/store.js';
import {
  value, stateLabel, versionOf, uptimeOf, typeLabel,
} from '../core/format.js';
import * as detail from '../components/detail.js';
import * as menu from '../components/context_menu.js';
import { clickSelect, isSelectionModifier, pruneSelection }
  from '../core/selection.js';
import { searchField } from '../components/search_field.js';
import { showError, showSuccess } from '../components/toast.js';
import { t } from '../core/i18n.js';

// The "Switch · port" column carries the switch's full name (Yataklı_1 · p11);
// left narrow, the text did not fit. The access state gets 140 rather than
// 120 because "Credentials needed" wrapped onto a second line at 120 — two
// rows in fourteen were a third taller than the rest, which is the one thing
// a list of forty must not do.
const COLUMNS = 'minmax(180px,1.4fr) minmax(140px,1fr) minmax(150px,1fr) '
  + '120px 100px 140px 96px';

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
const STATE_ORDER = ['failed', 'review', 'auth', 'unknown', 'ok'];

function ipOrder(text) {
  return String(text || '').split('.')
    .reduce((total, part) => (total * 256) + (Number(part) || 0), 0);
}

// ── the selection ───────────────────────────────────────────────────────
//
// A plain click still opens the drawer: that is what the list has always done
// and it is the common case. Ctrl/⌘ and Shift build a selection instead, and
// the right-click menu then works on all of it — reading twelve devices was
// twelve trips through the drawer before this.
//
// Module memory rather than `core/store.js`, the same call the switch screen
// made (views/switch/state.js): it is one screen's working set, it means
// nothing on any other screen, and nothing is written anywhere from it.
let selected = new Set();
let anchor = null;

// A device the filter, the search or a new scan took off the list cannot stay
// selected — it would be an invisible target for the next menu.
function prune(order) {
  const kept = pruneSelection(selected, order);
  if (kept.size !== selected.size) selected = kept;
  if (anchor !== null && !order.includes(anchor)) anchor = null;
}

function clearSelection() {
  selected = new Set();
  anchor = null;
}

// Read one device or twelve. The endpoint takes a list either way, and it
// reads on the request's own thread — so a scan or a write already running
// answers 409 and the message it sends is what the operator sees.
async function readDevices(ids, root) {
  try {
    await api.refresh(state.setNo, ids);
    if (ids.length > 1) showSuccess(t('devices.readCount', { count: ids.length }));
    render(root);
  } catch (e) { showError(e.message); }
}

// What the menu acts on: the whole selection when the click landed inside it,
// otherwise just the row under the cursor. Right-clicking outside a selection
// does not throw it away — the same rule every file manager has.
function menuTargets(device) {
  return selected.has(device.id) && selected.size > 1
    ? [...selected]
    : [device.id];
}

function openRowMenu(device, event, root) {
  event.preventDefault();
  const targets = menuTargets(device);
  const many = targets.length > 1;
  menu.openMenu(event, () => {
    const rows = [menu.menuItem(
      many ? t('devices.readCount', { count: targets.length })
        : t('detail.readNow'),
      { onPick: () => { menu.close(); readDevices(targets, root); } })];

    // Credentials are one device's business: which device the dialog would
    // be for is not answerable for a selection of twelve, so those two rows
    // appear only on a single-row menu. `deviceActions` decides which of
    // them apply from the same DTO the drawer uses.
    if (!many) {
      for (const action of detail.deviceActions(device, () => render(root))) {
        if (action.label === t('detail.readNow')) continue;   // already above
        rows.push(menu.menuItem(action.label, {
          onPick: () => { menu.close(); action.run(); },
        }));
      }
      rows.push(menu.menuItem(t('devices.openDetails'), {
        onPick: () => { menu.close(); detail.open(device.id); },
      }));
    }

    return [
      menu.menuHead(
        many ? t('devices.selectedCount', { count: targets.length })
          : device.name,
        many ? '' : `${device.ip} · ${device.portLabel}`),
      ...rows,
    ];
  });
}

// ONE FILTER PER STATE, AND THE STATE'S OWN NAME ON IT.
//
// There were three buckets — all, "reachable", "needs review" — and the
// middle one of those was two states at once (see core/store.js). The
// overview's four figures link straight in here, so a bucket that holds two
// of them means the number that was clicked and the number of rows that
// arrive are different. Four states, four filters, four counts, and they are
// the same five the overview's strip is drawn from.
//
// Keys, not text — see action_tabs.js: the module loads before the catalogue
// arrives.
const FILTERS = [
  { id: 'all', labelKey: 'group.all' },
  { id: 'ok', labelKey: 'state.ok' },
  { id: 'auth', labelKey: 'state.auth' },
  { id: 'review', labelKey: 'state.review' },
  { id: 'failed', labelKey: 'state.failed' },
  { id: 'unknown', labelKey: 'state.unknown' },
];

export function render(root) {
  const categories = state.meta ? state.meta.categories : [];
  const category = categories.find(c => c.id === state.category);
  const devices = visibleDevices();
  const categoryTotal = state.category === 'all'
    ? state.devices.length
    : state.devices.filter(d => d.category === state.category).length;

  const parts = [];

  // The line under the heading counts the ROWS ON SCREEN, not the category.
  // It said "All devices · 128 device(s)" while a search was showing twelve
  // of them, so the one number on the screen that could have confirmed the
  // search had worked was the one number that never moved.
  const shown = devices.length;
  const categoryName = category ? category.name : t('devices.allDevices');
  parts.push(el('div', { class: 'page-head' }, [
    el('div', {}, [
      el('h2', { text: t('nav.devices') }),
      el('div', {
        class: 'page-sub',
        text: shown === categoryTotal
          ? t('devices.categoryCount',
              { category: categoryName, count: categoryTotal })
          : t('devices.shownOfTotal',
              { category: categoryName, shown, total: categoryTotal }),
      }),
    ]),
    // Nothing but the search box lives up here now. The state filter used to
    // sit beside it as a tab strip, which put a full-width underline in the
    // middle of the header and set two filters in two different shapes on
    // one screen; both filters are chip bars below, in one language.
    el('div', { class: 'device-head-actions' }, [
      // Only there when there is a selection to say something about. A
      // permanent "0 selected" would be one more thing to read on every
      // visit for the sake of the minority of visits that select anything.
      selected.size ? el('div', { class: 'device-selection' }, [
        el('span', { text: t('devices.selectedCount', { count: selected.size }) }),
        el('button', {
          type: 'button', class: 'btn btn-small',
          text: t('devices.clearSelection'),
          onclick: () => { clearSelection(); render(root); },
        }),
      ]) : null,
      searchBox(root),
    ]),
  ]));

  // TWO AXES, ONE SHAPE. A chip carries a name and how many are behind it,
  // and that is what both of these rows are: what kind of device, and what
  // the last scan found. The word in front of each row is what tells them
  // apart — see `.chip-bar .label`.
  const chipBar = (label, ariaKey, entries) => el('div', {
    class: 'chip-bar', role: 'group', 'aria-label': t(ariaKey),
  }, [
    el('span', { class: 'label', text: label }),
    ...entries.map(entry => el('button', {
      type: 'button', class: 'chip', title: entry.title || null,
      'aria-pressed': String(entry.on),
      onclick: entry.go,
    }, [
      el('span', { text: entry.name }),
      el('span', { class: 'count', text: String(entry.count) }),
    ])),
  ]);

  // Categories are not top-level screens but a filter over the device list.
  parts.push(chipBar(t('checklist.category'), 'devices.deviceCategory',
    categories.map(entry => ({
      name: entry.name,
      title: entry.types,
      count: entry.id === 'all'
        ? state.devices.length
        : state.devices.filter(d => d.category === entry.id).length,
      on: state.category === entry.id,
      go: () => patch({ category: entry.id, subtype: null }),
    }))));

  // The same five states the overview's strip is drawn from, with the same
  // counts, so the figure that was clicked over there and the number of rows
  // that arrive here are one number.
  const spread = stateSpread();
  // A choice read back from an older session may name a filter that no longer
  // exists (the two buckets these five replaced). `visibleDevices` already
  // shows everything in that case; the row has to agree, or the screen sits
  // there with every chip unpressed and no way to tell why.
  const chosen = FILTERS.some(entry => entry.id === state.filter)
    ? state.filter : 'all';
  parts.push(chipBar(t('devices.state'), 'devices.stateFilter',
    FILTERS.map(filter => ({
      name: t(filter.labelKey),
      count: filter.id === 'all' ? state.devices.length : spread[filter.id],
      on: chosen === filter.id,
      go: () => patch({ filter: filter.id }),
    }))));

  const headings = ['col.device', 'col.typeSubtypeLower', 'col.switchPort',
    'col.ip', 'col.version', 'col.accessState', 'col.uptime'];

  const order = sorted(devices);
  prune(order.map(device => device.id));

  const rows = order.map(device => {
    const result = device.result || {};
    return el('button', {
      type: 'button', class: 'table-row',
      style: `--table-columns:${COLUMNS}`,
      // THE ROW'S OWN LEFT EDGE CARRIES THE STATE. The same strip the
      // verification list is read by (see views.css), and it is what makes a
      // list of forty scannable: the pattern of what needs attention is in
      // the gutter, so it is found without reading a word. It replaces the
      // seven-pixel dot that used to sit in front of the name — a marker
      // that small, halfway across the row, is not something an eye finds
      // standing up in a depot.
      dataset: { state: result.state },
      // Selected, or the drawer is open on it: both mean "this is the row
      // being worked on", and the list never shows the two at once.
      'aria-selected': String(selected.has(device.id)
        || (!selected.size && state.detailId === device.id)),
      title: result.detail || '',
      // A plain click opens the drawer, as it always has. The modifiers build
      // a selection instead — nothing is opened, so a mis-modified click
      // costs a click rather than a screen.
      onclick: (event) => {
        if (!event.shiftKey && !isSelectionModifier(event)) {
          detail.open(device.id);
          return;
        }
        const result_ = clickSelect({
          id: device.id, event, order: order.map(each => each.id),
          selected, anchor,
        });
        selected = result_.selected;
        anchor = result_.anchor;
        render(root);
      },
      oncontextmenu: (event) => openRowMenu(device, event, root),
    }, [
      el('span', { class: 'mono truncate t-base', text: device.name }),
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
      // The word, quietly. It used to be set in the heading face, upper
      // case and letter-spaced — the loudest thing on a screen full of
      // device names, saying "REACHABLE" nine times down a column that the
      // strip on the left already answers. The strip is what the list is
      // scanned by; this is what confirms it, and what a colour on its own
      // could never say to somebody who cannot tell the two greens apart.
      el('span', {
        class: 'state-text truncate t-sm', dataset: { state: result.state },
        text: stateLabel(result.state, ' '),
      }),
      el('span', {
        // Same rule as the version beside it: a reading is worth seeing, the
        // dash standing in for "not read yet" is not.
        class: uptimeOf(device)
          ? 'mono truncate t-sm text-mid' : 'mono truncate t-sm text-dim',
        text: value(uptimeOf(device)),
      }),
    ]);
  });

  parts.push(dataTable({
    template: COLUMNS, minWidth: 1000, label: t('nav.devices'),
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
  return searchField({
    id: 'device-search',
    value: state.deviceSearch || '',
    title: t('devices.searchHint'),
    'aria-label': t('devices.searchHint'),
    oninput: (event) => {
      const caret = event.target.selectionStart;
      patch({ deviceSearch: event.target.value });
      render(root);
      const again = root.querySelector('#device-search');
      if (!again) return;
      again.focus();
      again.setSelectionRange(caret, caret);
    },
  }, 'device-search');
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
