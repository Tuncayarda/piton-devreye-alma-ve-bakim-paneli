// What the last run did, and what every run before it did.
//
// TWO TABLES, AND THEY ANSWER DIFFERENT QUESTIONS. The top one is the run on
// screen right now: one row per (device, bundle) pair, filling in while the
// workers move through them. It is watched, not read — the operator wants to
// see the pending rows turn green — so it carries as little as possible.
//
// THE DETAIL COLUMN LEFT IT for that reason. "Installed — version 4.2.1" is
// worth having, but it was the widest column in the table and it was empty in
// every row that had not run yet, which made a four-column table look broken
// for the first ten seconds of every run. The detail is not lost: it is what
// the log below is made of.
//
// THE LOG IS THE AFTERNOON. A bench session is a dozen runs, and the question
// that gets asked afterwards is never about the current one — it is "did 46
// ever come back?" or "which of them did I already install this on?". The
// runner keeps the finished rows (panel/adb/runner.py, LOG_LIMIT) and this
// draws them newest first, in a box twenty rows tall that scrolls. Twenty
// because that is a screen's worth: enough that the answer is usually already
// visible, few enough that the card underneath is still reachable without
// scrolling past somebody's whole afternoon.
//
// The header row is sticky (`.table-head`), so scrolling the log does not
// leave six unlabelled columns.

import { el } from '../../core/dom.js';
import { dataTable } from '../../components/table.js';
import { clockTime } from '../../core/format.js';
import { t } from '../../core/i18n.js';
import { runner } from './state.js';

const RUN_COLUMNS = 'minmax(120px,.8fr) minmax(160px,1.4fr) 120px';
const LOG_COLUMNS = '76px minmax(120px,.9fr) minmax(110px,.7fr) '
  + 'minmax(140px,1.1fr) 100px minmax(160px,1.4fr)';

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
  reboot: 'adb.opReboot',
  connect: 'adb.opConnect',
  restart_server: 'adb.opRestartServer',
  autostart_install: 'adb.opAutostartInstall',
  autostart_remove: 'adb.opAutostartRemove',
};

function operationName(name) {
  return t(OP_LABEL[name] || 'adb.operations');
}

export function statusCard(actions) {
  const current = runner();
  const rows = (current && current.rows) || [];
  const log = (current && current.log) || [];
  const busy = !!(current && current.running);

  return el('section', { class: 'card corner adb-status' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('adb.statusTitle') }),
      el('span', { class: 'spacer' }),
      rows.length
        ? el('span', {
          class: 'eyebrow',
          text: t('adb.runningOperation', {
            operation: operationName(current.operation),
          }),
        })
        : null,
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
    rows.length
      ? dataTable({
        template: RUN_COLUMNS, minWidth: 460, label: t('adb.statusTitle'),
        // The bundle has a column of its own: one run can carry a different
        // package name per device, and without it two rows for one address
        // would be indistinguishable.
        columns: [t('adb.columnAddress'), t('adb.columnPackage'),
                  t('col.state')],
        rows: rows.map(runRow),
        empty: '',
      })
      : el('p', { class: 'info', text: t('adb.noRunYet') }),
    ...history(log),
  ]);
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
  ]);
}

// ── the log ─────────────────────────────────────────────────────────────
// NEWEST FIRST. The server keeps them in the order they happened, which is
// the right order to store and the wrong one to read: the line somebody is
// looking for is nearly always the one that was just written, and a log that
// grows downwards puts it where they have to scroll for it.
function history(log) {
  if (!log.length) return [];
  return [
    el('div', { class: 'adb-log-head' }, [
      el('span', { class: 'eyebrow', text: t('adb.history') }),
      el('span', { class: 'spacer' }),
      el('span', {
        class: 'adb-log-count',
        text: t('adb.historyCount', { count: log.length }),
      }),
    ]),
    dataTable({
      template: LOG_COLUMNS, minWidth: 720, label: t('adb.history'),
      wrapClass: 'adb-log',
      columns: [t('adb.columnTime'), t('adb.columnOperation'),
                t('adb.columnAddress'), t('adb.columnPackage'),
                t('col.state'), t('adb.columnDetail')],
      rows: [...log].reverse().map(logRow),
      empty: t('adb.historyEmpty'),
    }),
  ];
}

function logRow(entry) {
  return el('div', {
    class: 'table-row adb-run-row',
    dataset: { state: ROW_TONE[entry.state] || 'unknown' },
    style: `--table-columns:${LOG_COLUMNS}`,
  }, [
    el('span', { class: 'mono', text: clockTime(entry.at) }),
    el('span', { class: 'truncate', text: operationName(entry.operation) }),
    el('span', { class: 'mono truncate', text: entry.ip }),
    el('span', { class: 'mono truncate', text: entry.package || '—' }),
    el('span', {
      class: 'adb-run-state',
      text: t(ROW_LABEL[entry.state] || 'adb.statePending'),
    }),
    el('span', { class: 'truncate', text: entry.detail || '' }),
  ]);
}
