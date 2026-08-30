// The three operation cards and the confirmations in front of them.
//
// THREE CARDS, NOT ONE, and the split is the whole point of this file. It was
// one card called "Operations" holding, in a single column: four buttons that
// act on the chosen application, a file picker that overwrites it, an
// autostart pair that writes to /system, and two buttons about the ADB daemon
// on THIS computer. Everything on the screen looked equally important and
// equally aimed at the ticked rows, and the last two were aimed at neither.
// So they are separated by WHAT THEY TOUCH, which is the only division an
// operator can hold in their head:
//
//   applicationCard  the application on the selected displays — start, stop,
//                    restart, remove. Reversible; no dialog.
//   installCard      what is put ON a display — the APK, and the autostart
//                    files. Both write; both ask first.
//   serverCard       this computer's ADB daemon. Ignores the selection.
//
// The run's own table went with them, to `status.js`: it is not an operation,
// it is what the last one did.
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
// The ones that matter here are three, and they are not equal.
// (Rebooting a display is the fourth; it moved to the device list,
// where it can be aimed at one display without ticking it first.)
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
import { confirmWrite } from '../../components/confirm.js';
import { t } from '../../core/i18n.js';
import {
  devices, local, operationTargets, running, selectedIps, untouchedIps,
} from './state.js';

// The check's VERDICT, not its file count. Two files sitting where they were
// written is not evidence that anything runs at boot — three different faults
// leave exactly that picture, and each needs a different fix (see
// panel/adb/autostart.py:state). These are those answers.
const AUTOSTART_LABEL = {
  installed: 'adb.autostartInstalled',
  partial: 'adb.autostartPartial',
  absent: 'adb.autostartAbsent',
  pendingReboot: 'adb.autostartPendingReboot',
  notParsed: 'adb.autostartNotParsed',
  running: 'adb.autostartRunning',
  ranOk: 'adb.autostartRanOk',
  gaveUp: 'adb.autostartGaveUp',
  ranSilently: 'adb.autostartRanSilently',
};
// A verdict that means the operator has something to do about it.
const AUTOSTART_BAD = new Set(['absent', 'partial', 'notParsed', 'gaveUp']);

// What the operator asked for, in the order they reach for it: the four
// buttons that touch the application they have chosen.
export function applicationCard(actions) {
  const chosen = selectedIps();
  // The pairs, not the devices. See state.operationTargets: a bundle that is
  // not on a device produces no pair, so no command is sent about it.
  const targets = operationTargets();
  const withPackage = chosen.length > 0 && !running() && targets.length > 0;

  return el('section', { class: 'card corner adb-actions' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('adb.appActions') }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'label', text: summary(chosen, targets) }),
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
  ]);
}

// PUTTING THE APPLICATION ON THE DISPLAY, which is a different afternoon from
// driving one that is already there. Both rows write to the device and both
// ask first; keeping them together is also what stops the four everyday
// buttons above from being read as five equal things, which is how "uninstall"
// used to sit one gap away from "start".
export function installCard(actions) {
  const chosen = selectedIps();
  const targets = operationTargets();
  const ready = chosen.length > 0 && !running();

  return el('section', { class: 'card corner adb-install' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('adb.installSection') }),
    ]),
    apkRow(chosen, ready, actions),
    autostartRow(targets, ready, actions),
    autostartLog(),
  ]);
}

// THIS COMPUTER, not the bench — the one card on the screen that ignores the
// selection entirely. It is its own card for exactly that reason: sharing a
// heading with the operations above implied it acted on the ticked rows, and
// the operator reaching for it has usually just watched every row fail at
// once, which is the daemon here rather than twelve dead displays.
export function serverCard(actions) {
  const list = devices();
  return el('section', { class: 'card corner adb-server' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('adb.adbServer') }),
    ]),
    connectRow(list, actions),
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
// ── attaching the whole bench ───────────────────────────────────────────
// THE WHOLE LIST, not the selection, and that is the point of it. Every other
// action here works on the devices the operator ticked; this one answers a
// different question — "is my bench actually reachable from this machine?" —
// and the useful answer covers every address they have entered, including the
// ones they have not selected because they had assumed those were fine.
//
// It leaves the transports attached (see panel/adb/apps.py:connect), so
// `adb devices` lists them afterwards and the other tools on this machine can
// reach the same displays. Anything that will not attach becomes a failed row
// in the table below, which is the warning that was asked for.
function connectRow(list, actions) {
  return el('div', { class: 'adb-op-row' }, [
    el('button', {
      type: 'button', class: 'btn btn-small',
      text: t('adb.connectAll'),
      disabled: running() || list.length === 0,
      onclick: () => actions.run(
        'connect', {}, list.map(entry => ({ ip: entry.ip }))),
    }),
    // Enabled with nothing selected and with an empty list, because that is
    // exactly when it is reached for: every address failing at once is the
    // daemon on this computer, not the bench. The panel also tries this by
    // itself after a run where every row failed to connect (see
    // panel/adb/runner.py); the button is for the operator who has not run
    // anything yet, or who wants it done now.
    el('button', {
      type: 'button', class: 'btn btn-small',
      text: t('adb.resetServer'),
      disabled: running(),
      onclick: () => actions.run('restart_server', {}, []),
    }),
  ]);
}

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
  const verdict = asked ? (known.verdict || known.state) : '';
  return el('div', { class: 'adb-op-row' }, [
    el('span', { class: 'label', text: t('adb.autostart') }),
    el('span', {
      class: AUTOSTART_BAD.has(verdict) ? 'adb-op-bad' : 'adb-op-empty',
      text: asked
        ? t(AUTOSTART_LABEL[verdict] || 'adb.autostartAbsent', { ip: known.ip })
        : t('adb.autostartUnknown'),
    }),
    // Whether the application is up RIGHT NOW, which is the question behind
    // the question: an autostart that init ran is only interesting if what
    // it launched is still there.
    asked && known.appRunning
      ? el('span', { class: 'pill ok', text: t('adb.autostartAppUp') })
      : null,
    el('button', {
      type: 'button', class: 'btn btn-small',
      text: local.checkingAutostart ? t('adb.checking') : t('adb.check'),
      disabled: !enabled || local.checkingAutostart,
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

// The script's own log. Shown only once the check has run and only when the
// verdict leaves something to read: "it ran and gave up" is a sentence, but
// the line saying WHICH component it could not start is the fix.
function autostartLog() {
  const known = local.autostart;
  if (!known || !(known.log || []).length) return null;
  return el('div', { class: 'adb-autostart-log' }, [
    el('span', { class: 'label', text: t('adb.autostartLog') }),
    ...known.log.map(line => el('p', { class: 'mono truncate', text: line })),
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
