// The operation bar, the confirmations, and the table the run fills in.
//
// WHICH OPERATIONS ASK FIRST, and why it is not all of them. The panel's rule
// is that an operation which RESTARTS a device, CHANGES ITS ADDRESS or CUTS
// ITS POWER asks (see components/confirm.js). Starting, stopping and
// restarting an application do none of those: they are the bench equivalent
// of touching the screen, they are undone by pressing the other button, and
// putting a dialog in front of them would teach the operator to dismiss
// dialogs without reading them — which is exactly what makes the ones that
// matter useless.
//
// The ones that matter here are three, and they are not equal:
//
//   remove          takes the application off the display.
//   install an APK  overwrites the application that is on it.
//   autostart       WRITES TO THE SYSTEM PARTITION. It survives a factory
//                   reset, it is not removed by uninstalling the app, and on
//                   a device with a verified /system it can stop it booting.
//                   Its dialog names both files by their full path, because
//                   "set up autostart" does not tell anybody what is about to
//                   be left on their hardware. THE PATHS COME FROM THE
//                   SERVER (see panel/adb/autostart.py) rather than being
//                   assembled here from the package name: two copies of that
//                   naming rule would drift, and the dialog would then
//                   promise files that are not the ones written.

import { el } from '../../core/dom.js';
import { dataTable } from '../../components/table.js';
import { confirmWrite } from '../../components/confirm.js';
import { t } from '../../core/i18n.js';
import {
  devices, local, operationTargets, runner, running, selectedIps, untouchedIps,
} from './state.js';

const RUN_COLUMNS =
  'minmax(120px,.7fr) minmax(150px,1.2fr) 110px minmax(180px,1.6fr)';

// Row state -> the status vocabulary the rest of the panel paints with, and
// the label for it. Written out as literal keys rather than built from the
// state name: the catalogue check reads keys out of the source as string
// literals, and a key assembled at run time is a key nothing can verify.
const ROW_TONE = {
  pending: 'unknown',
  running: 'unknown',
  done: 'ok',
  failed: 'failed',
  cancelled: 'unknown',
};
const ROW_LABEL = {
  pending: 'adb.statePending',
  running: 'adb.stateRunning',
  done: 'adb.stateDone',
  failed: 'adb.stateFailed',
  cancelled: 'adb.stateCancelled',
};
const OP_LABEL = {
  start: 'adb.opStart',
  stop: 'adb.opStop',
  restart: 'adb.opRestart',
  uninstall: 'adb.opUninstall',
  install: 'adb.opInstall',
  autostart_install: 'adb.opAutostartInstall',
  autostart_remove: 'adb.opAutostartRemove',
};
const AUTOSTART_LABEL = {
  installed: 'adb.autostartInstalled',
  partial: 'adb.autostartPartial',
  absent: 'adb.autostartAbsent',
};

export function operationsCard(actions) {
  const chosen = selectedIps();
  const busy = running();
  // The pairs, not the devices. See state.operationTargets: a bundle that is
  // not on a device produces no pair, so no command is sent about it.
  const targets = operationTargets();
  const ready = chosen.length > 0 && !busy;
  const withPackage = ready && targets.length > 0;

  return el('section', { class: 'card corner adb-operations' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('adb.operations') }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'eyebrow', text: summary(chosen, targets) }),
    ]),
    el('div', { class: 'adb-op-bar' }, [
      opButton(t('adb.startApp'), withPackage,
               () => actions.run('start', {}, targets)),
      opButton(t('adb.stopApp'), withPackage,
               () => actions.run('stop', {}, targets)),
      opButton(t('adb.restartApp'), withPackage,
               () => actions.run('restart', {}, targets)),
      opButton(t('adb.uninstallApp'), withPackage,
               () => confirmUninstall(targets, actions), 'btn-danger'),
    ]),
    skipped(targets),
    apkRow(chosen, ready, actions),
    autostartRow(targets, ready, actions),
    ...runTable(actions),
  ]);
}

function summary(chosen, targets) {
  if (!chosen.length) return t('adb.selectDeviceFirst');
  if (!local.packages.size) return t('adb.chooseApplicationFirst');
  if (!targets.length) return t('adb.noTargets');
  return t('adb.readyOn', {
    count: targets.length,
    devices: new Set(targets.map(pair => pair.ip)).size,
    packages: new Set(targets.map(pair => pair.package)).size,
  });
}

// Devices the operator selected that no chosen bundle is on. NAMED, not
// dropped quietly: they picked those devices deliberately, and "nothing
// happened on 10.1.1.46" is a question they would otherwise have to ask.
function skipped(targets) {
  if (!targets.length || !local.packages.size) return null;
  const idle = untouchedIps();
  if (!idle.length) return null;
  return el('p', {
    class: 'info adb-op-note',
    text: t('adb.devicesWithoutBundle', { list: idle.join(', ') }),
  });
}

function opButton(label, enabled, onclick, extra = '') {
  return el('button', {
    type: 'button', class: `btn${extra ? ` ${extra}` : ''}`, text: label,
    disabled: !enabled, onclick,
  });
}

// ── the APK ─────────────────────────────────────────────────────────────
// The path is never typed and never travels from the browser: the server
// opens the operating system's own dialog and sends back the file's NAME.
// Same arrangement as the firmware screen, for the same reason — the browser
// sandbox does not reveal a real path.
function apkRow(chosen, ready, actions) {
  const file = local.apk;
  return el('div', { class: 'adb-op-row' }, [
    el('span', { class: 'label', text: t('adb.installApk') }),
    el('span', {
      class: file ? 'mono truncate' : 'adb-op-empty',
      text: file ? file.name : t('adb.noApkChosen'),
    }),
    el('button', {
      type: 'button', class: 'btn btn-small',
      text: local.pickerOpen ? t('adb.choosing') : t('adb.chooseFile'),
      disabled: local.pickerOpen || running(),
      title: t('adb.chooseFileHint'),
      onclick: () => actions.pickApk(),
    }),
    el('button', {
      type: 'button', class: 'btn btn-small btn-primary',
      text: t('adb.install'),
      disabled: !ready || !file,
      onclick: () => confirmInstall(chosen, file, actions),
    }),
  ]);
}

// ── the autostart ───────────────────────────────────────────────────────
function autostartRow(targets, ready, actions) {
  const known = local.autostart;
  const first = targets[0];
  const asked = !!(known && first && known.ip === first.ip
    && known.package === first.package);
  const enabled = ready && targets.length > 0;
  return el('div', { class: 'adb-op-row' }, [
    el('span', { class: 'label', text: t('adb.autostart') }),
    el('span', {
      class: 'adb-op-empty',
      text: asked
        ? t(AUTOSTART_LABEL[known.state] || 'adb.autostartAbsent',
            { ip: known.ip })
        : t('adb.autostartUnknown'),
    }),
    el('button', {
      type: 'button', class: 'btn btn-small',
      text: local.checkingAutostart ? t('adb.checking') : t('adb.check'),
      disabled: !enabled || local.checkingAutostart,
      title: t('adb.checkAutostartHint'),
      onclick: () => actions.checkAutostart(),
    }),
    el('button', {
      type: 'button', class: 'btn btn-small',
      text: t('adb.autostartInstall'),
      disabled: !enabled,
      onclick: () => confirmAutostart(targets, actions, true),
    }),
    el('button', {
      type: 'button', class: 'btn btn-small btn-danger',
      text: t('adb.autostartRemove'),
      disabled: !enabled,
      onclick: () => confirmAutostart(targets, actions, false),
    }),
  ]);
}

// ── the confirmations ───────────────────────────────────────────────────
// A run is a list of (device, bundle) pairs, so the dialog lists pairs. With
// two customers' applications selected across four displays, "12 devices" on
// its own does not say what is about to happen to which of them.
function items(chosen) {
  const labels = new Map(devices().map(entry => [entry.ip, entry.label]));
  return chosen.map(ip => ({ name: ip, detail: labels.get(ip) || '' }));
}

function pairItems(targets) {
  return targets.map(pair => ({ name: pair.ip, detail: pair.package }));
}

function confirmUninstall(targets, actions) {
  confirmWrite({
    title: t('adb.uninstallTitle'),
    lead: t('adb.uninstallLead', {
      count: targets.length,
      devices: new Set(targets.map(pair => pair.ip)).size,
    }),
    notes: [{ text: t('adb.uninstallNote'), tone: 'warning' }],
    items: pairItems(targets),
    danger: true,
    confirmLabel: t('adb.uninstallApp'),
    run: () => actions.run('uninstall', {}, targets),
  });
}

function confirmInstall(chosen, file, actions) {
  confirmWrite({
    title: t('adb.installTitle'),
    lead: t('adb.installLead', { count: chosen.length, name: file.name }),
    notes: [{ text: t('adb.installNote'), tone: 'info' }],
    items: items(chosen),
    confirmLabel: t('adb.install'),
    // No path travels. The server installs the file its own dialog chose.
    run: () => actions.run('install', {}),
  });
}

// The dialog is opened only once the server has said which files it would
// write. Asking first costs one request and removes the possibility of a
// dialog that promises one path while another is written.
async function confirmAutostart(targets, actions, on) {
  // One request per DISTINCT bundle: with two applications selected the
  // dialog has four files to name, not two, and naming only the first
  // bundle's pair would understate what is about to be written.
  const names = [...new Set(targets.map(pair => pair.package))];
  const answers = await Promise.all(
    names.map(name => actions.autostartFiles(name)));
  if (answers.some(paths => !paths)) return;   // the request failed and said so
  const paths = answers.flat();
  confirmWrite({
    title: on ? t('adb.autostartInstallTitle') : t('adb.autostartRemoveTitle'),
    lead: on
      ? t('adb.autostartInstallLead', { count: targets.length })
      : t('adb.autostartRemoveLead', { count: targets.length }),
    notes: [
      { text: t('adb.autostartSystemWarning'), tone: 'warning' },
      on && { text: t('adb.autostartFilesNote'), tone: 'info' },
    ],
    items: [
      ...paths.map(path => ({ name: path, detail: t('adb.systemFile') })),
      ...pairItems(targets),
    ],
    danger: true,
    confirmLabel: on ? t('adb.autostartInstall') : t('adb.autostartRemove'),
    run: () => actions.run(
      on ? 'autostart_install' : 'autostart_remove', {}, targets),
  });
}

// ── what the run is doing ───────────────────────────────────────────────
function runTable(actions) {
  const current = runner();
  if (!current || !(current.rows || []).length) return [];
  const busy = !!current.running;
  return [
    el('div', { class: 'adb-run-head' }, [
      el('span', {
        class: 'eyebrow',
        text: t('adb.runningOperation', {
          operation: t(OP_LABEL[current.operation] || 'adb.operations'),
        }),
      }),
      el('span', { class: 'spacer' }),
      busy
        ? el('button', {
          type: 'button', class: 'btn btn-small',
          text: current.cancelling ? t('adb.cancelling') : t('adb.cancel'),
          disabled: !!current.cancelling,
          title: t('adb.cancelHint'),
          onclick: () => actions.cancel(),
        })
        : null,
    ]),
    dataTable({
      template: RUN_COLUMNS, minWidth: 640, label: t('adb.operations'),
      // The bundle has a column of its own: one run can carry a different
      // package name per device, and without it two rows for one address
      // would be indistinguishable.
      columns: [t('adb.columnAddress'), t('adb.columnPackage'),
                t('col.state'), t('adb.columnDetail')],
      rows: (current.rows || []).map(runRow),
      empty: '',
    }),
  ];
}

function runRow(row) {
  return el('div', {
    class: 'table-row adb-run-row',
    dataset: { state: ROW_TONE[row.state] || 'unknown' },
    style: `--table-columns:${RUN_COLUMNS}`,
  }, [
    el('span', { class: 'mono', text: row.ip }),
    el('span', { class: 'mono truncate', text: row.package || '—' }),
    el('span', {
      class: 'adb-run-state',
      text: t(ROW_LABEL[row.state] || 'adb.statePending'),
    }),
    el('span', { class: 'truncate', text: row.detail || '' }),
  ]);
}
