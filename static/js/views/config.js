// The configuration screen: the value on the device ↔ the target value.
//
// Only announcement devices (the Announcement family) are configured; the bar
// already lists only those groups, and the device's read method is "http".
//
// The fields arrive per device type: a Handset's mode fields do not exist on
// an Amplifier, and the UIC's voltage thresholds exist only on a UIC. The
// list comes from the server; this file keeps no field table of its own (see
// panel/config_sync/fields.py ROUTES).
//
// A target value is entered at two levels:
//   · Group  — written once when the same setting goes to the whole group
//   · Device — when it differs on that device; it overrides the group's
//
// The "value on the device" column stays empty (—) when unread. Targets live
// in memory; nothing is written to a file. The SIP password can be entered on
// this screen but is NEVER SHOWN: the server never returns its value, and the
// row shows only whether it matches and where it came from.

import { el, fill } from '../core/dom.js';
import { dataTable } from '../components/table.js';
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import * as groupBar from '../components/group_bar.js';
import * as actionTabs from '../components/action_tabs.js';
import * as dialog from '../components/dialog.js';
import { confirmWrite } from '../components/confirm.js';
import { showError, showSuccess, notify } from '../components/toast.js';
import { value } from '../core/format.js';
import { t } from '../core/i18n.js';
import { loadFailed, loading } from '../components/placeholder.js';

const COLUMNS = 'minmax(150px,1.05fr) minmax(120px,.95fr) minmax(150px,1fr) '
  + '86px 104px';

const COMPARISON_LABEL = {
  match: ['compare.match', 'ok-text'],
  differs: ['compare.differs', 'auth-text'],
  unread: ['compare.unread', 'failed-text'],
  no_target: ['compare.noTarget', 'text-dim'],
};

const SOURCE_LABEL = {
  device: ['source.device', 'accent'],
  group: ['source.group', 'text-mid'],
  project: ['source.project', 'text-dim'],
};

// Section headings, keyed by the server's stable `section` id (see
// panel/config_sync/fields.py). The server also sends `sectionLabel`; this
// table only fills in when an older server does not. It holds the SAME
// catalogue keys the server renders from, so the two cannot drift.
const SECTION_LABEL = {
  sip: 'section.sip',
  audio: 'section.audio',
  mode: 'section.mode',
  thresholds: 'section.thresholds',
  routing: 'section.routing',
  information: 'section.information',
};

// `window`: the open device window ({device, body}) — see openDevice.
const local = {
  deviceId: null, errorText: '', needsCredentials: false, token: 0,
  window: null,
};

function groupName() {
  const group = groupBar.currentGroup('cfg');
  return group ? group.name : '';
}

function targetDevices() {
  const group = groupBar.currentGroup('cfg');
  return group ? groupBar.devicesIn(group) : [];
}

// A two-stage load. The field list, the targets and the DeviceMap values come
// from an endpoint that never touches the device and are drawn AT ONCE; the
// values on the device catch up afterwards. Waiting for a single request made
// changing group show the old group's fields for seconds (a device read is
// slow, and a timeout long if the device is off).
//
// `token`: the user can move to another group while waiting. Every refresh
// gets a sequence number so a late reply cannot overwrite the new selection.
export async function refresh(fast = true) {
  const devices = targetDevices();
  if (!devices.length) { patch({ configState: null }); return; }
  if (!devices.some(d => d.id === local.deviceId)) {
    local.deviceId = devices[0].id;
  }
  const token = (local.token = (local.token || 0) + 1);
  const current = () => token === local.token;
  const id = local.deviceId;
  const group = groupName();

  if (fast) {
    try {
      const preview = await api.configFields(state.setNo, id, group);
      if (!current()) return;
      local.errorText = '';
      local.needsCredentials = false;
      patch({ configState: preview });
    } catch { /* if the fast endpoint fails, the real read reports it */ }
  }

  try {
    const body = await api.config(state.setNo, id, group);
    if (!current()) return;
    local.errorText = body.error || '';
    local.needsCredentials = !!body.auth;
    patch({ configState: body });
  } catch (e) {
    if (!current()) return;
    local.errorText = e.message;
    patch({ configState: { deviceId: id, rows: [] } });
  }
}

export function render(root) {
  const devices = targetDevices();
  const data = state.configState;
  const parts = [];

  // If the open window's device dropped off the list (set/group change) the
  // window is closed; otherwise settings could be written to a device that no
  // longer exists.
  if (local.window && !devices.some(d => d.id === local.window.device.id)) {
    dialog.close();
  }

  // The screen's scope and its one action ride on the tab row — see
  // components/action_tabs.js for what came off the top of this screen.
  parts.push(actionTabs.render([
    groupBar.picker('cfg', () => {
      // The open window belonged to the old group's device; it closes on a
      // group change.
      if (local.window) dialog.close();
      local.deviceId = null;
      refresh();
    }),
    el('button', {
      type: 'button', class: 'btn btn-primary',
      text: devices.length
        ? t('config.applyToCount', { count: devices.length })
        : t('config.applyToDevices'),
      disabled: !devices.length, onclick: applyToGroup,
    }),
  ]));

  if (!devices.length) {
    fill(root, parts);
    return;
  }

  // Before the first read there is nothing to draw and the screen used to
  // draw it anyway: empty boxes with no values in them, which looks like a
  // device that answered with nothing rather than one that has not been
  // asked yet.
  if (!data) {
    parts.push(local.errorText
      ? loadFailed(local.errorText)
      : loading(t('config.readingSettings')));
    fill(root, parts);
    return;
  }

  const rows = (data && data.rows) || [];
  const groupTargets = (data && data.groupTargets) || {};
  // Values defined in DeviceMap that are the same on every device in the
  // group: pre-filled into the boxes so that pressing "apply to group"
  // without touching anything shows what will be written.
  const projectShared = (data && data.projectShared) || {};
  const projectVarying = (data && data.projectVarying) || [];
  // The field list arrives independently of the device: values to be written
  // to the group must be enterable even while the device is unreachable.
  const fields = (data && data.fields) || [];

  parts.push(el('div', { class: 'cfg-grid' }, [
    groupCard(fields, rows, {
      groupTargets, projectShared, projectVarying,
      savedDefaults: (data && data.savedDefaults) || {},
    }),
    el('div', { class: 'cfg-device-area' }, [
      el('div', { class: 'cfg-device-head' }, [
        el('h3', { text: t('config.perDevice') }),
        el('span', {
          class: 'badge',
          text: t('config.deviceCount', { count: devices.length }),
        }),
      ]),
      el('div', { class: 'cfg-device-list' }, devices.map(deviceItem)),
    ]),
  ]));

  fill(root, parts);
  // The window lives outside the screen (in the dialog slot); it has to be
  // refreshed when new data arrives too.
  renderWindow();
}

// ── the device window ───────────────────────────────────────────────────
// Device-specific values are no longer a single row picked from a dropdown:
// the devices are listed and the clicked device's settings are edited in a
// window that opens in the middle. The apply button is in that window too and
// writes to that device only; the selected device can no longer be missed and
// applied to the whole group by accident.
function deviceItem(device) {
  const colour = (device.result && device.result.state) || 'unknown';
  const open = !!local.window && local.window.device.id === device.id;
  return el('button', {
    type: 'button', class: 'cfg-device-item',
    dataset: { open: open ? '1' : '0' },
    onclick: () => openDevice(device),
  }, [
    el('span', {
      class: 'dot', dataset: { state: colour }, 'aria-hidden': 'true',
    }),
    el('span', {
      class: 'mono truncate cfg-item-name', text: device.name,
    }),
    el('span', { class: 'mono text-dim cfg-item-ip', text: device.ip }),
    el('span', { class: 'cfg-item-chevron', 'aria-hidden': 'true', text: '›' }),
  ]);
}

function openDevice(device) {
  local.deviceId = device.id;
  const body = el('div', { class: 'cfg-window-body' });
  const handle = dialog.show({
    title: device.name,
    content: body,
    width: '840px',
    // Clear the list marker when closed with Escape or a backdrop click too.
    onClose: () => { local.window = null; },
    actions: [
      el('button', {
        type: 'button', class: 'btn', text: t('config.readFromTheDevice'),
        onclick: () => refresh(),
      }),
      el('button', {
        type: 'button', class: 'btn btn-primary', text: t('config.applyToThisDevice'),
        onclick: () => applyToDevice(device),
      }),
      el('button', {
        type: 'button', class: 'btn', text: t('detail.close'),
        onclick: () => dialog.close(),
      }),
    ],
  });
  local.window = { device, body, close: handle.close };
  renderWindow();
  refresh();
}

function renderWindow() {
  const win = local.window;
  if (!win || !win.body.isConnected) return;
  const data = state.configState;
  // A late reply belonging to another device is not shown in the window.
  const ours = !!data && data.deviceId === win.device.id;
  const rows = (ours && data.rows) || [];
  // The window is redrawn after every target write; the same field is found
  // again so focus is not lost as the user moves to the next one.
  const previousFocus = document.activeElement;
  const focusLabel = previousFocus && win.body.contains(previousFocus)
    ? previousFocus.getAttribute('aria-label') : null;
  fill(win.body, [
    el('p', { class: 'unit', text: win.device.ip }),
    local.errorText ? el('p', {
      class: local.needsCredentials ? 'info' : 'warning',
      text: local.errorText,
    }) : null,
    dataTable({
      // The floor is the sum of the column minimums, the gaps between them
      // and the row's own padding — below it the grid cannot shrink any
      // further and spills past the row's right border instead. It was
      // six pixels under it.
      template: COLUMNS, minWidth: 680, label: t('tabs.deviceSettings'),
      columns: ['col.setting', 'col.current', 'col.deviceValue', 'col.source',
                'col.state'].map(key => t(key)),
      rows: rows.map(renderRow),
      // Writing "could not be read" while the read is in progress is wrong:
      // the device has not even been tried yet.
      empty: t((!ours || (data && data.reading)) && !local.errorText
        ? 'config.readingDevice' : 'config.couldNotRead'),
    }),
  ]);
  if (focusLabel) {
    const restored = win.body.querySelector(
      `[aria-label="${CSS.escape(focusLabel)}"]`);
    if (restored) restored.focus();
  }
}

// Writing settings sends the SIP block, and the device RESTARTS on it — the
// same class of consequence as a firmware install, which has always asked.
function applyToDevice(device) {
  const group = groupBar.currentGroup('cfg');
  if (!group) return;
  confirmWrite({
    title: t('config.applyToThisDevice'),
    lead: t('confirm.configOneLead', { device: device.name }),
    items: [{ name: device.name, detail: device.ip || '' }],
    confirmLabel: t('config.applyToThisDevice'),
    run: async () => {
      const job = await api.configApply(state.setNo, group.name, [device.id]);
      patch({ queueOpen: true, openJob: job.id });
      if (job.new === false) {
        notify(t('config.applyQueuedFor', { device: device.name }));
      } else {
        showSuccess(t('config.settingsQueuedFor', { device: device.name }));
      }
      dialog.close();
    },
  });
}

// An input element matching the field's kind. The kind comes from the
// device's own UI (dropdown / 0–100 slider / voltage); keeping the same
// limits in the panel rather than a free text box stops a value the device
// would reject from entering the queue.
function input(field, currentValue, onChange, extra = {}) {
  if (field.kind === 'choice') {
    return el('select', {
      class: `field ${extra.class || ''}`,
      'aria-label': `${field.label} · ${extra.aria || ''}`,
      title: extra.title || null,
      onchange: (e) => onChange(e.target.value),
    }, [
      el('option', { value: '', text: extra.emptyLabel || '—' }),
      ...(field.options || []).map(option => el('option', {
        value: option.value, text: option.label,
        selected: String(currentValue) === String(option.value) ? true : null,
      })),
    ]);
  }
  const numeric = field.kind === 'integer' || field.kind === 'decimal';
  return el('input', {
    type: field.secret ? 'password' : (numeric ? 'number' : 'text'),
    class: `field ${extra.class || ''}`,
    value: currentValue || '',
    min: numeric && field.minimum !== null ? field.minimum : null,
    max: numeric && field.maximum !== null ? field.maximum : null,
    step: numeric ? (field.step || 1) : null,
    autocomplete: field.secret ? 'new-password' : 'off', spellcheck: 'false',
    'aria-label': `${field.label} · ${extra.aria || ''}`,
    title: extra.title || null,
    onchange: (e) => onChange(e.target.value),
  });
}

// Values entered once for the group: every field here is written to all the
// group's devices (unless a device-specific value was entered).
//
// The boxes arrive pre-filled with the DeviceMap value; if the user touches
// nothing, that is what is written. For fields that DIFFER per device (the
// extension) the box stays empty (projectVarying): showing a single number
// and having the user change one character would write that number to the
// whole group.
function groupCard(fields, rows, sources) {
  const {
    groupTargets, projectShared, projectVarying, savedDefaults,
  } = sources;
  const rowFor = new Map(rows.map(row => [row.field, row]));
  const writable = fields.filter(f => f.editable)
    // The row data (source/target) goes under the field definition, not over
    // it: on shared keys (label, kind) the definition must win.
    .map(f => ({ ...(rowFor.get(f.field) || {}), ...f }));

  // The sections match the panels on the device's own page; a field list over
  // 20 long (the UIC) was unreadable as one heading-less pile.
  const sections = [];
  for (const field of writable) {
    const last = sections[sections.length - 1];
    if (last && last.name === (field.section || '')) last.fields.push(field);
    else {
      sections.push({
        name: field.section || '', label: field.sectionLabel || '',
        fields: [field],
      });
    }
  }

  return el('section', { class: 'card corner cfg-group-card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('config.sharedSettings') }),
    ]),
    ...(sections.length
      ? sections.flatMap(section => [
        section.name ? el('h4', {
          class: 'cfg-section',
          text: section.label || SECTION_LABEL[section.name] || section.name,
        }) : null,
        ...section.fields.map(field => {
          const entered = field.secret ? '' : (groupTargets[field.field] || '');
          const inherited = !entered && !field.secret
            && !projectVarying.includes(field.field)
            ? (projectShared[field.field] || '') : '';
          return el('label', { class: 'setting-row' }, [
            el('span', { class: 'label', text: field.label }),
            input(field, entered || inherited,
              (v) => writeTarget(field.field, v, 'group'), {
                class: `cfg-field${inherited ? ' cfg-inherited' : ''}`,
                aria: t('config.valueToWriteToThe'),
                emptyLabel: t(inherited ? 'config.default'
                  : 'config.leaveUnchanged'),
                title: field.warning || '',
              }),
          ]);
        }),
      ])
      : [el('p', {
          class: 'mono text-dim t-xs',
          text: t('config.thisDeviceTypeHasNo'),
        })]),
    savedDefaultsFooter(savedDefaults, writable.some(f => f.secret)),
  ]);
}

// Entered values are written to a file and restored when the application
// opens. Without knowing that, the user re-enters them every time wondering
// whether they stick. The password is NEVER written to the file, which is
// said here too — but only for a device type that HAS one. A Compartment LCD
// has a single writable field and no password anywhere near it, so the
// exception would name a setting the screen never showed.
function savedDefaultsFooter(defaults, hasSecret = true) {
  const count = (defaults.groupValues || 0) + (defaults.deviceValues || 0);
  return el('div', { class: 'cfg-defaults' }, [
    el('span', {
      class: 'cfg-saved-note',
      text: (count ? t('config.savedCount', { count })
        : t('config.savedForSet')) + (hasSecret ? t('config.savedSuffix') : ''),
      title: defaults.file || '',
    }),
    count ? el('button', {
      type: 'button', class: 'btn btn-small',
      text: t('config.reset'), onclick: resetDefaults,
    }) : null,
  ]);
}

async function resetDefaults() {
  try {
    const body = await api.configReset(
      state.setNo, local.deviceId, groupName());
    patch({ configState: body });
    showSuccess(t('config.theChangesWereRemovedBack'));
  } catch (e) { showError(e.message); }
}

async function writeTarget(field, newValue, scope) {
  try {
    const body = await api.configTarget(
      state.setNo, local.deviceId, field, newValue, groupName(), scope);
    patch({ configState: body });
  } catch (err) { showError(err.message); }
}

function renderRow(row) {
  const [labelKey, colour] = COMPARISON_LABEL[row.comparison]
    || ['', 'text-dim'];
  const [sourceKey, sourceColour] = SOURCE_LABEL[row.source]
    || ['', 'text-dim'];
  const label = labelKey ? t(labelKey) : '—';
  const sourceName = sourceKey ? t(sourceKey) : '—';
  // A secret field's value on the device never arrives; only "it exists".
  const currentText = row.secret
    ? (row.hasCurrent ? '•••' : '—') : value(row.current);
  return el('div', {
    class: 'table-row', style: `--table-columns:${COLUMNS}`,
  }, [
    el('span', { class: 'mono t-base', text: row.label }),
    el('span', {
      class: 'mono text-mid truncate t-base',
      text: currentText,
    }),
    row.editable
      // The box arrives filled with the VALUE that will be written: with no
      // device-specific value entered, the target inherited from the group or
      // DeviceMap shows, and the dim colour says it was inherited. Emptying
      // the box removes the device-specific value and the target falls back
      // to the inherited one.
      ? input(row, row.secret ? '' : (row.override || row.target || ''),
        (v) => writeTarget(row.field, v, 'device'), {
          class: `t-base field-tight${
            !row.override && row.target ? ' cfg-inherited' : ''}`,
          aria: t('config.valueSpecificToThisDevice'),
          title: row.warning || '',
          // The empty option means "no device-specific value"; the label says
          // where the target will fall back to.
          emptyLabel: t(row.source === 'project' ? 'config.default'
            : (row.source === 'group' ? 'config.sharedSetting'
              : 'config.empty')),
        })
      : el('span', {
          class: 'mono text-dim t-base', text: '—',
        }),
    // If the DeviceMap value is invalid it did not count as a target; the
    // reason shows here, or the field would look silently empty.
    el('span', {
      class: 'mono t-xs',
      style: 'color:var(--'
        + (row.warning ? 'failed-text' : sourceColour) + ')',
      title: row.warning || null,
      text: row.warning
        ? t('config.projectDefaultInvalid')
        : (row.editable ? sourceName : '—'),
    }),
    el('span', {
      class: 'state-label',
      style: `color:var(--${colour})`,
      text: label,
    }),
  ]);
}

function applyToGroup() {
  const group = groupBar.currentGroup('cfg');
  if (!group) return;
  const devices = groupBar.devicesIn(group);
  confirmWrite({
    title: t('config.applyToDevices'),
    lead: t('confirm.configGroupLead', {
      count: devices.length, group: group.label || group.name,
    }),
    items: devices.map(device => ({
      name: device.name, detail: device.ip || '',
    })),
    confirmLabel: t('config.applyToCount', { count: devices.length }),
    run: async () => {
      const job = await api.configApply(state.setNo, group.name, null);
      patch({ queueOpen: true, openJob: job.id });
      if (job.new === false) {
        notify(t('config.applyingTheDeviceSettingsIs'));
      } else {
        showSuccess(t('config.applyingTheDeviceSettingsWas'));
      }
    },
  });
}
