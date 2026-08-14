// The software installation screen.
//
// The file is chosen PER DEVICE: every row has its own file and target
// version. Two devices in one group need not take the same file; with a
// single "selected file" it was invisible which device got what. If they all
// take the same file, the button at the top writes it to the group in one
// call.
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
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import * as groupBar from '../components/group_bar.js';
import * as actionTabs from '../components/action_tabs.js';
import * as dialog from '../components/dialog.js';
import { showError, showSuccess, notify } from '../components/toast.js';
import { value, fileSize, NONE } from '../core/format.js';
import { t } from '../core/i18n.js';

const COLUMNS = 'minmax(150px,1.1fr) 112px 92px minmax(210px,1.6fr) '
  + '100px minmax(120px,.8fr)';

// The target version in the bulk field is a convenience only: it is written
// to the rows along with the chosen file and is not stored itself. It lives
// here so a redraw does not lose it.
const local = { bulkVersion: '', pickerOpen: false };

let refreshToken = 0;

function groupName() {
  const group = groupBar.currentGroup('fw');
  return group ? group.name : '';
}

export async function refresh() {
  const token = ++refreshToken;
  const setNo = state.setNo;
  try {
    const body = await api.firmware(setNo, groupName());
    if (token !== refreshToken || setNo !== state.setNo) return;
    patch({ firmwareState: body });
  } catch {
    if (token !== refreshToken) return;
    patch({ firmwareState: null });
  }
}

// The rows from the server are the device list itself; they come from
// DeviceMap even without a scan (the version column stays empty then).
function rows() {
  const data = state.firmwareState;
  return (data && data.devices) || [];
}

function selectedCount(list) {
  return list.filter(d => d.file && d.file.selected).length;
}

// How many devices are installed at once — the width of the server's pool.
function concurrency() {
  const data = state.firmwareState;
  return (data && data.concurrency) || 1;
}

// The file type the group's devices expect (.bin / .apk). Because the bar
// shows one group, in practice there is one type; if mixed, both are written
// so the user knows up front what will be selected.
function typeText(list) {
  const types = [...new Set(
    list.filter(d => d.extension).map(d => d.extension))];
  return types.map(t => `.${t}`).join(' / ');
}

export function render(root) {
  const list = rows();
  const selected = selectedCount(list);
  const installable = list.filter(d => d.installable).length;
  const parts = [];

  parts.push(el('div', { class: 'page-head' }, [
    // The heading is the same on all three operation screens: the tab bar
    // below already says which screen this is.
    el('h2', { text: t('nav.operations') }),
    el('div', { class: 'actions' }, [
      el('button', {
        type: 'button', class: 'btn', text: t('firmware.clearTheSelections'),
        disabled: !selected,
        title: t('firmware.removeEveryFileSelectionIn'),
        onclick: () => removeSelection(null),
      }),
      el('button', {
        type: 'button', class: 'btn btn-primary', text: t('firmware.startTheInstall'),
        disabled: !selected,
        title: selected
          ? t('firmware.jobQueuedFor', { count: selected })
          : t('firmware.selectFileFirst'),
        onclick: start,
      }),
    ]),
  ]));

  parts.push(actionTabs.render());
  parts.push(groupBar.picker('fw', () => refresh()));

  // ── bulk selection ──
  // The usual field case: one file for the whole group. It is chosen once;
  // the rows can still be changed one by one.
  const types = typeText(list);
  parts.push(el('section', { class: 'card corner fw-bulk' }, [
    el('div', { class: 'fw-bulk-head' }, [
      el('h3', { text: t('firmware.bulkSelection') }),
    ]),
    el('div', { class: 'fw-bulk-fields' }, [
      el('label', { class: 'fw-field-narrow', for: 'fw-bulk-version' }, [
        el('span', { class: 'label', text: t('firmware.targetVersion') }),
        el('input', {
          id: 'fw-bulk-version', class: 'field', value: local.bulkVersion,
          placeholder: '1.2.6', autocomplete: 'off', spellcheck: 'false',
          oninput: (e) => { local.bulkVersion = e.target.value.trim(); },
        }),
      ]),
      el('button', {
        type: 'button', class: 'btn btn-primary',
        text: local.pickerOpen
          ? t('firmware.selectingFile')
          : (installable
            ? t('firmware.selectAndApply', { count: installable })
            : t('firmware.selectFile')),
        disabled: !installable || local.pickerOpen,
        // The expected file type lives in the tooltip of the button that
        // makes the choice, not as a separate note line.
        title: t('firmware.yourComputersFileDialogOpens')
          + (types ? ` (${types})` : ''),
        onclick: () => pickFile(null, local.bulkVersion),
      }),
    ]),
    el('p', {
      class: 'ip-field-help',
      text: t('firmware.theTargetVersionIsOptional'),
    }),
  ]));

  // ── per-device rows ──
  parts.push(el('div', { class: 'table-wrap' }, [
    el('div', { class: 'table', style: '--table-min:960px' }, [
      el('div', { class: 'table-head', style: `--table-columns:${COLUMNS}` },
        ['col.device', 'col.ip', 'col.currentVersion', 'col.fileToInstall',
         'col.targetVersion', 'col.state']
          .map(key => el('span', { text: t(key) }))),
      ...(list.length
        ? list.map(renderRow)
        : [el('div', {
            class: 'table-empty',
            text: t(state.firmwareState
              ? 'firmware.noDeviceInGroup' : 'firmware.loadingDevices'),
          })]),
    ]),
  ]));

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
        class: 'mono truncate', style: 'font-size:12px', text: device.name,
      }),
    ]),
    el('span', {
      class: 'mono text-bright', style: 'font-size:11.5px', text: device.ip,
    }),
    el('span', {
      class: 'mono text-mid', style: 'font-size:11.5px',
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
            title: t('firmware.selectFileFor', { device: device.name })
              + (device.extension ? ` (.${device.extension})` : ''),
            onclick: () => pickFile([device.deviceId], file.version || ''),
          }),
          file.selected ? el('button', {
            type: 'button', class: 'btn btn-close',
            text: '×', title: t('firmware.removeThisDevicesSelection'),
            'aria-label': t('firmware.removeSelectionFor', { device: device.name }),
            onclick: () => removeSelection([device.deviceId]),
          }) : null,
        ])
      : el('span', {
          class: 'text-dim', style: 'font-size:11.5px',
          text: t('firmware.notSupported'),
        }),
    device.installable
      ? el('input', {
          class: 'field fw-version-field', value: file.version || '',
          placeholder: '—', autocomplete: 'off', spellcheck: 'false',
          'aria-label': t('firmware.targetVersionFor', { device: device.name }),
          disabled: !file.selected,
          title: t(file.selected ? 'firmware.expectedAfterInstall'
            : 'firmware.selectFileForDevice'),
          onchange: (e) => {
            if (file.selected) {
              writeVersion([device.deviceId], e.target.value.trim());
            }
          },
        })
      : el('span', { class: 'text-dim', text: NONE }),
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
async function pickFile(devices, version) {
  if (local.pickerOpen) return;
  local.pickerOpen = true;
  patch({ firmwareState: { ...state.firmwareState } });   // lock the buttons
  try {
    const reply = await api.firmwarePick(
      state.setNo, groupName(), devices, version);
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

async function writeVersion(devices, version) {
  try {
    await api.firmwareVersion(state.setNo, groupName(), devices, version);
    await refresh();
  } catch (e) { showError(e.message); }
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
  dialog.show({
    title: t('firmware.startTheFirmwareInstall'),
    content: el('div', {}, [
      el('p', { class: 'description' }, [
        `A file will be installed on ${list.length} device(s). Once the `
        + 'install finishes, each device\'s version is read back and '
        + 'verified. Announcement equipment restarts during the operation.',
      ]),
      // How many run at once comes from the server; in the field this
      // answers "which devices are about to go dark".
      concurrency() > 1 ? el('p', {
        class: 'info', style: 'margin-top:8px',
        text: t('firmware.concurrency', { count: concurrency() }),
      }) : null,
      el('div', { class: 'fw-confirm-list' }, list.map(device => el('div', {
        class: 'row',
      }, [
        el('span', { class: 'mono truncate', text: device.name }),
        el('b', { class: 'mono truncate', text: device.file.name }),
      ]))),
    ]),
    actions: [
      el('button', {
        type: 'button', class: 'btn', text: t('locked.cancel'),
        onclick: () => dialog.close(),
      }),
      el('button', {
        type: 'button', class: 'btn btn-primary', text: t('firmware.startTheInstall'),
        onclick: async () => {
          dialog.close();
          try {
            const job = await api.firmwareInstall(
              state.setNo, group, list.map(d => d.deviceId));
            patch({ queueOpen: true, openJob: job.id });
            if (job.new === false) {
              notify(t('firmware.thisFirmwareInstallJobIs'));
            } else {
              showSuccess(t('firmware.theFirmwareInstallJobWas'));
            }
          } catch (e) { showError(e.message); }
        },
      }),
    ],
  });
}
