// The software installation screen.
//
// The file is chosen PER DEVICE: every row has its own file. Two devices in
// one group need not take the same file; with a single "selected file" it was
// invisible which device got what. If they all take the same file, the button
// at the top writes it to the group in one call.
//
// The expected file type varies by device: announcement equipment takes an
// image (.bin), the Compartment LCD an application package (.apk). The type
// comes from the server; the screen keeps no table of its own.
//
// The file is chosen through the operating system's own dialog: the browser
// sandbox does not reveal the real path of an `<input type=file>` choice, and
// the panel does not copy the file into its own directory — it only keeps the
// path. The "Select" button goes to the server, the server opens the picker (see
// panel.system.files.pick_file) and the returned path is assigned to that
// device. The selection lives in memory and is gone when the app closes.
//
// Installing exists only on devices that have a path; the bar already lists
// only those groups, but the `installable` flag from the server is still
// shown on the row. Because devices are independent of each other, the run
// goes in parallel (see panel.api.tasks.firmware_task).

import { el, fill } from '../core/dom.js';
import { dataTable } from '../components/table.js';
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import * as groupBar from '../components/group_bar.js';
import * as actionTabs from '../components/action_tabs.js';
import { confirmWrite } from '../components/confirm.js';
import { showError, showSuccess, notify } from '../components/toast.js';
import { value, fileSize } from '../core/format.js';
import { latest } from '../core/latest.js';
import { t } from '../core/i18n.js';

const COLUMNS = 'minmax(150px,1.1fr) 112px 92px minmax(210px,1.6fr) '
  + 'minmax(120px,.8fr)';

const local = { pickerOpen: false };

function groupName() {
  const group = groupBar.currentGroup('fw');
  return group ? group.name : '';
}

// `latest` retires a reload overtaken by a newer one; the reply is ALSO
// dropped when the train set moved underneath it — the file list is a list
// of device ids, and ids repeat across sets. The catch keeps the token-only
// check it always had: clearing the screen is right whichever set failed.
export const refresh = latest(async (fresh) => {
  const setNo = state.setNo;
  try {
    const body = await api.firmware(setNo, groupName());
    if (!fresh() || setNo !== state.setNo) return;
    patch({ firmwareState: body });
  } catch {
    if (!fresh()) return;
    patch({ firmwareState: null });
  }
});

// The rows from the server are the device list itself; they come from
// DeviceMap even without a scan (the version column stays empty then).
function rows() {
  const data = state.firmwareState;
  return (data && data.devices) || [];
}

function selectedCount(list) {
  return list.filter(d => d.file && d.file.selected).length;
}

// The file type the group's devices expect (.bin / .apk). Because the bar
// shows one group, in practice there is one type; if mixed, both are written
// so the user knows up front what will be selected.
function typeText(list) {
  const types = [...new Set(
    list.filter(d => d.extension).map(d => d.extension))];
  // `type`, not `t`: the obvious one-letter name shadows the translator
  // imported above, and a t('...') added inside this map would fail quietly.
  return types.map(type => `.${type}`).join(' / ');
}

export function render(root) {
  const list = rows();
  const selected = selectedCount(list);
  const installable = list.filter(d => d.installable).length;
  const parts = [];

  // The screen's scope and its actions ride on the tab row — see
  // components/action_tabs.js for what came off the top of this screen.
  parts.push(actionTabs.render([
    groupBar.picker('fw', () => refresh()),
    el('button', {
      type: 'button', class: 'btn', text: t('firmware.clearTheSelections'),
      disabled: !selected,
      onclick: () => removeSelection(null),
    }),
    el('button', {
      type: 'button', class: 'btn btn-primary',
      text: t('firmware.startTheInstall'),
      disabled: !selected,
      onclick: start,
    }),
  ]));

  // ── bulk selection ──
  // The usual field case: one file for the whole group. It is chosen once;
  // the rows can still be changed one by one.
  const types = typeText(list);
  parts.push(el('section', { class: 'card corner fw-bulk' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('firmware.bulkSelection') }),
    ]),
    el('div', { class: 'fw-bulk-fields' }, [
      el('button', {
        type: 'button', class: 'btn btn-primary',
        text: local.pickerOpen
          ? t('firmware.selectingFile')
          : (installable
            ? t('firmware.selectAndApply', { count: installable })
            : t('firmware.selectFile')),
        disabled: !installable || local.pickerOpen,
        // The expected file type is the one thing the tooltip still carries.
        title: types || null,
        onclick: () => pickFile(null),
      }),
    ]),
  ]));

  // ── per-device rows ──
  parts.push(dataTable({
    template: COLUMNS, minWidth: 960, label: t('tabs.firmware'),
    columns: ['col.device', 'col.ip', 'col.currentVersion',
              'col.fileToInstall', 'col.state'].map(key => t(key)),
    rows: list.map(renderRow),
    empty: t(state.firmwareState
      ? 'firmware.noDeviceInGroup' : 'firmware.loadingDevices'),
  }));

  fill(root, parts);
}

function renderRow(device) {
  const file = device.file || { selected: false };
  const path = file.path || '';
  return el('div', {
    class: 'table-row fw-row', style: `--table-columns:${COLUMNS}`,
    dataset: { selected: file.selected ? '1' : '0' },
  }, [
    el('span', { class: 'fw-device' }, [
      el('span', {
        class: 'dot', dataset: { state: stateColour(device) },
        'aria-hidden': 'true',
      }),
      el('span', {
        class: 'mono truncate t-base', text: device.name,
      }),
    ]),
    el('span', {
      class: 'mono text-bright t-sm', text: device.ip,
    }),
    el('span', {
      class: 'mono text-mid t-sm',
      text: value(device.currentVersion),
    }),
    // The file name plus the choose/remove buttons. The path is never typed;
    // the full path lives in the tooltip (there is no room to read it).
    device.installable
      ? el('div', { class: 'fw-file' }, [
          el('span', {
            class: file.selected ? 'mono truncate' : 'mono truncate text-dim',
            title: path || t('firmware.noFileSelectedYet'),
            text: file.selected ? file.name : t('firmware.notSelected'),
          }),
          el('button', {
            type: 'button', class: 'btn btn-small fw-pick-btn',
            text: t(file.selected ? 'firmware.change' : 'firmware.select'),
            disabled: local.pickerOpen,
            title: device.extension ? `.${device.extension}` : null,
            onclick: () => pickFile([device.deviceId]),
          }),
          file.selected ? el('button', {
            type: 'button', class: 'btn btn-close',
            text: '×',
            title: t('firmware.removeSelectionFor', { device: device.name }),
            'aria-label': t('firmware.removeSelectionFor', { device: device.name }),
            onclick: () => removeSelection([device.deviceId]),
          }) : null,
        ])
      : el('span', {
          class: 'text-dim t-sm',
          text: t('firmware.notSupported'),
        }),
    el('span', {
      class: 'truncate fw-state', text: stateText(device, file),
    }),
  ]);
}

// The dot on the row shows the device's last read state; the device list
// comes from the scan and is not in the server's firmware reply.
function stateColour(row) {
  const device = (state.devices || []).find(d => d.id === row.deviceId);
  return (device && device.result && device.result.state) || 'unknown';
}

// The file name already sits in the neighbouring column; rather than repeat
// it, the rest of the selection (its size) is written here.
function stateText(device, file) {
  if (!device.installable) return t('firmware.notSupported');
  if (!file.selected) return t('firmware.noFileSelected');
  return t('firmware.readyToInstall', { size: fileSize(file.size) });
}

// ── actions ─────────────────────────────────────────────────────────────
// When `devices` is null the operation applies to the whole group (the server
// resolves it from the group name); otherwise only to the given devices.

// The file dialog opens on the server, i.e. in the operating system. The
// request lasts until that window closes: every pick button stays locked
// meanwhile, or two windows could open back to back.
async function pickFile(devices) {
  if (local.pickerOpen) return;
  local.pickerOpen = true;
  patch({ firmwareState: { ...state.firmwareState } });   // lock the buttons
  try {
    const reply = await api.firmwarePick(
      state.setNo, groupName(), devices);
    local.pickerOpen = false;
    if (reply.cancelled) { await refresh(); return; }
    await refresh();
    showSuccess(devices
      ? t('firmware.fileSelected')
      : t('firmware.fileSelectedFor', { count: reply.deviceCount }));
  } catch (e) {
    local.pickerOpen = false;
    showError(e.message);
    await refresh();
  }
}

async function removeSelection(devices) {
  try {
    await api.firmwareRemove(state.setNo, groupName(), devices);
    await refresh();
  } catch (e) { showError(e.message); }
}

// Installing restarts the device and can take minutes; there must be no
// button that can be pressed by accident, so confirmation is asked.
function start() {
  const list = rows().filter(d => d.file && d.file.selected);
  if (!list.length) return;
  const group = groupName();
  confirmWrite({
    title: t('firmware.startTheFirmwareInstall'),
    lead: t('confirm.firmwareLead', { count: list.length }),
    items: list.map(device => ({
      name: device.name, detail: device.file.name,
    })),
    confirmLabel: t('firmware.startTheInstall'),
    run: async () => {
      const job = await api.firmwareInstall(
        state.setNo, group, list.map(d => d.deviceId));
      patch({ queueOpen: true, openJob: job.id });
      if (job.new === false) {
        notify(t('firmware.thisFirmwareInstallJobIs'));
      } else {
        showSuccess(t('firmware.theFirmwareInstallJobWas'));
      }
    },
  });
}
