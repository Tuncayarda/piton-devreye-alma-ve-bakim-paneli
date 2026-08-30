// The session's job history.
//
// This view creates no record of its own and writes nothing to browser
// storage. It only arranges the `jobs` array in global state; when the
// application closes, the history goes with the server's in-memory job list.

import { el, fill } from '../core/dom.js';
import { dataTable } from '../components/table.js';
import { state, patch } from '../core/store.js';
import {
  NONE, jobOutcomeLabel, jobStateLabel, JOB_OUTCOME_COLOUR, LOCALE,
} from '../core/format.js';
import { t } from '../core/i18n.js';

const IN_PROGRESS = new Set(['queued', 'running']);
const FINISHED = new Set(['done', 'cancelled', 'failed']);

const STATE_COLOUR = {
  queued: 'unknown',
  running: 'busy',
  done: 'ok',
  cancelled: 'auth',
  failed: 'failed',
};

// Keyed by the server's stable `kind` value, never by the display title: the
// title carries a switch or device name and gets reworded, and a screen that
// decided by matching it went blank the moment the wording changed.
//
// Keys rather than words, because this table is built when the module loads
// — before the catalogue has arrived.
const KIND_NAME = {
  scan: 'history.kindScan',
  ip: 'history.kindIp',
  ipfactory: 'history.kindIpFactory',
  config: 'history.kindConfig',
  firmware: 'history.kindFirmware',
  checklist: 'history.kindChecklist',
  switchscan: 'history.kindSwitchScan',
};

const COLUMNS = 'minmax(235px,1.7fr) minmax(120px,.8fr) 105px '
  + 'minmax(125px,.8fr) minmax(210px,1.4fr) 105px';

function jobName(job) {
  if (job.kind === 'scan' && job.auto) return t('history.automaticScan');
  if (KIND_NAME[job.kind]) return t(KIND_NAME[job.kind]);
  return String(job.title || t('history.kindUnknown'));
}

// The first part of the server's title is usually the job kind. Because the
// kind is written above in consistent wording, only the scope (switch, ports
// or device count) is shown here.
function jobScope(job) {
  const parts = String(job.title || '').split(' · ').slice(1);
  if (parts[0] === `Set ${job.setNo}`) parts.shift();
  return parts.join(' · ');
}

function timeText(ts) {
  if (!ts) return NONE;
  return new Date(ts * 1000).toLocaleTimeString(LOCALE, {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });
}

function durationText(job) {
  if (!job.startedAt) return t('history.notStarted');
  const end = job.finishedAt || Date.now() / 1000;
  const seconds = Math.max(0, Math.round(end - job.startedAt));
  if (seconds < 60) return t('history.seconds', { count: seconds });
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) {
    return rest
      ? t('history.minutesSeconds', { minutes, seconds: rest })
      : t('history.minutes', { count: minutes });
  }
  const hours = Math.floor(minutes / 60);
  return t('history.hoursMinutes', { hours, minutes: minutes % 60 });
}

function stateText(job) {
  if (job.cancelRequested && IN_PROGRESS.has(job.state)) {
    return t('history.stopping');
  }
  return jobStateLabel(job.state, t('history.unknownState'));
}

function outcomeText(job) {
  if (IN_PROGRESS.has(job.state)) {
    return job.phase || t(job.state === 'queued'
      ? 'history.waitingTurn' : 'jobstate.running');
  }
  if (job.error) return job.error;

  const counts = job.counts || {};
  const ok = Number(counts.ok || 0);
  const auth = Number(counts.auth || 0);
  const failed = Number(counts.failed || 0);
  const skipped = Number(counts.skipped || 0);
  const total = Number(counts.total || 0);
  if (!total) {
    if (job.state === 'cancelled') return t('history.stoppedEarly');
    if (job.state === 'failed') return t('history.couldNotComplete');
    return t('history.finishedWell');
  }

  const parts = [];
  const outcomeLabel = job.outcome ? jobOutcomeLabel(job.outcome) : '';
  if (outcomeLabel) parts.push(outcomeLabel);
  parts.push(t('history.countOk', { count: ok }));
  if (auth) parts.push(t('history.countAuth', { count: auth }));
  if (failed) parts.push(t('history.countFailed', { count: failed }));
  if (skipped) parts.push(t('history.countSkipped', { count: skipped }));
  return parts.join(' · ');
}

function jobRow(job) {
  const percent = Math.round(Number(job.progress || 0) * 100);
  const scope = jobScope(job);
  const colour = STATE_COLOUR[job.state] || 'unknown';
  const outcomeColour = JOB_OUTCOME_COLOUR[job.outcome] || colour;
  const startedAt = job.startedAt || job.createdAt;

  return el('div', {
    class: 'table-row', style: `--table-columns:${COLUMNS}`,
  }, [
    el('span', { class: 'stack gap-1' }, [
      el('span', {
        class: 'text-bright t-base', text: jobName(job),
      }),
      scope ? el('span', {
        class: 'mono text-dim truncate t-xs',
        title: scope, text: scope,
      }) : null,
      job.auto ? el('span', {
        class: 'badge self-start', text: t('history.automatic'),
      }) : null,
    ]),
    el('span', { class: 'row gap-3' }, [
      el('span', {
        class: 'dot', dataset: { state: colour }, 'aria-hidden': 'true',
      }),
      el('span', {
        class: 'state-text t-base', dataset: { state: colour },
                text: IN_PROGRESS.has(job.state)
          ? t('history.stateWithPercent', { state: stateText(job), percent })
          : stateText(job),
      }),
    ]),
    el('span', {
      class: 'mono text-mid t-sm',
      text: t('history.trainSet', { set: job.setNo ?? NONE }),
    }),
    el('span', { class: 'stack gap-1' }, [
      el('span', {
        class: 'mono text-bright t-sm',
        text: timeText(startedAt),
      }),
      el('span', {
        class: 'mono text-dim t-xs',
        text: durationText(job),
      }),
    ]),
    el('span', {
      class: 'state-text t-sm', dataset: { state: outcomeColour },
      style: 'line-height:1.45',
      title: outcomeText(job), text: outcomeText(job),
    }),
    el('button', {
      type: 'button', class: 'btn btn-small', text: t('history.openTheDetails'),
      onclick: () => patch({
        openJob: job.id, queueOpen: true, lockedOpen: false,
      }),
    }),
  ]);
}

function section(title, jobs, emptyText) {
  return el('section', { class: 'mt-5' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: title }),
      el('span', { class: 'badge', text: String(jobs.length) }),
    ]),
    dataTable({
      template: COLUMNS, minWidth: 1040, wrapClass: 'mt-0',
      label: title,
      columns: ['col.job', 'col.state', 'col.trainSet',
                'col.startAndDuration', 'col.outcome', '']
        .map(key => (key ? t(key) : '')),
      rows: jobs.map(jobRow),
      empty: emptyText,
    }),
  ]);
}

function filters(active, finished) {
  const options = [
    { id: 'all',
      label: t('history.filterAll',
        { count: active.length + finished.length }) },
    { id: 'active',
      label: t('history.filterActive', { count: active.length }) },
    { id: 'finished',
      label: t('history.filterFinished', { count: finished.length }) },
  ];
  return el('div', {
    class: 'segmented',
    role: 'group', 'aria-label': t('history.historyFilter'),
  }, options.map(option => el('button', {
    type: 'button', class: 'btn btn-small t-base',
    'aria-pressed': String(state.historyFilter === option.id),
    text: option.label,
    onclick: () => patch({ historyFilter: option.id }),
  })));
}

export function render(root) {
  const eligible = (state.jobs || []).filter(
    job => IN_PROGRESS.has(job.state) || FINISHED.has(job.state));
  const sorted = eligible.slice().sort((a, b) =>
    (b.finishedAt || b.startedAt || b.createdAt || 0)
      - (a.finishedAt || a.startedAt || a.createdAt || 0));
  const active = sorted.filter(job => IN_PROGRESS.has(job.state));
  const finished = sorted.filter(job => FINISHED.has(job.state));

  const parts = [
    el('div', { class: 'page-head' }, [
      el('h2', { text: t('nav.history') }),
      filters(active, finished),
    ]),
  ];

  if (state.historyFilter !== 'finished') {
    parts.push(section(
      t('history.inProgressTitle'),
      active,
      t('history.inProgressEmpty'),
    ));
  }
  if (state.historyFilter !== 'active') {
    parts.push(section(
      t('history.finishedTitle'),
      finished,
      t('history.finishedEmpty'),
    ));
  }

  fill(root, parts);
}
