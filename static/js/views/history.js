// The session's job history.
//
// This view creates no record of its own and writes nothing to browser
// storage. It only arranges the `jobs` array in global state; when the
// application closes, the history goes with the server's in-memory job list.

import { el, fill } from '../core/dom.js';
import { state, patch } from '../core/store.js';
import {
  NONE, jobOutcomeLabel, JOB_OUTCOME_COLOUR, LOCALE,
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

const STATE_TEXT = {
  queued: 'Queued',
  running: 'Running',
  done: 'Finished',
  cancelled: 'Stopped',
  failed: 'Failed',
};

// Keyed by the server's stable `kind` value, never by the display title: the
// title carries a switch or device name and gets reworded, and a screen that
// decided by matching it went blank the moment the wording changed.
const KIND_NAME = {
  scan: 'System scan',
  ip: 'IP assignment',
  ipfactory: 'Reset to the factory IP',
  config: 'Apply device settings',
  firmware: 'Firmware install',
  checklist: 'Generate the Excel report',
};

const UNKNOWN_KIND = 'Job';

const COLUMNS = 'minmax(235px,1.7fr) minmax(120px,.8fr) 105px '
  + 'minmax(125px,.8fr) minmax(210px,1.4fr) 105px';

function jobName(job) {
  if (job.kind === 'scan' && job.auto) return 'Automatic system scan';
  return KIND_NAME[job.kind] || String(job.title || UNKNOWN_KIND);
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
  if (!job.startedAt) return 'Not started yet';
  const end = job.finishedAt || Date.now() / 1000;
  const seconds = Math.max(0, Math.round(end - job.startedAt));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

function stateText(job) {
  if (job.cancelRequested && IN_PROGRESS.has(job.state)) return 'Stopping…';
  return STATE_TEXT[job.state] || 'Unknown';
}

function outcomeText(job) {
  if (IN_PROGRESS.has(job.state)) {
    return job.phase || (job.state === 'queued'
      ? 'Waiting its turn' : 'Running');
  }
  if (job.error) return job.error;

  const counts = job.counts || {};
  const ok = Number(counts.ok || 0);
  const auth = Number(counts.auth || 0);
  const failed = Number(counts.failed || 0);
  const skipped = Number(counts.skipped || 0);
  const total = Number(counts.total || 0);
  if (!total) {
    if (job.state === 'cancelled') return 'Stopped before it finished';
    if (job.state === 'failed') return 'The job could not be completed';
    return 'The job finished successfully';
  }

  const parts = [];
  const outcomeLabel = job.outcome ? jobOutcomeLabel(job.outcome) : '';
  if (outcomeLabel) parts.push(outcomeLabel);
  parts.push(`${ok} successful`);
  if (auth) parts.push(`${auth} device(s) need credentials`);
  if (failed) parts.push(`${failed} failed`);
  if (skipped) parts.push(`${skipped} skipped`);
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
    el('span', {
      style: 'display:flex;flex-direction:column;gap:3px;min-width:0',
    }, [
      el('span', {
        class: 'text-bright', style: 'font-size:12.5px', text: jobName(job),
      }),
      scope ? el('span', {
        class: 'mono text-dim truncate', style: 'font-size:10.5px',
        title: scope, text: scope,
      }) : null,
      job.auto ? el('span', {
        class: 'badge', style: 'align-self:flex-start', text: t('history.automatic'),
      }) : null,
    ]),
    el('span', {
      style: 'display:flex;align-items:center;gap:8px;min-width:0',
    }, [
      el('span', {
        class: 'dot', dataset: { state: colour }, 'aria-hidden': 'true',
      }),
      el('span', {
        class: 'state-text', dataset: { state: colour },
        style: 'font-size:12px',
        text: IN_PROGRESS.has(job.state)
          ? `${stateText(job)} · %${percent}` : stateText(job),
      }),
    ]),
    el('span', {
      class: 'mono text-mid', style: 'font-size:11px',
      text: t('history.trainSet', { set: job.setNo ?? NONE }),
    }),
    el('span', {
      style: 'display:flex;flex-direction:column;gap:3px',
    }, [
      el('span', {
        class: 'mono text-bright', style: 'font-size:11px',
        text: timeText(startedAt),
      }),
      el('span', {
        class: 'mono text-dim', style: 'font-size:10px',
        text: durationText(job),
      }),
    ]),
    el('span', {
      class: 'state-text', dataset: { state: outcomeColour },
      style: 'font-size:11.5px;line-height:1.45',
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

function section(title, description, jobs, emptyText) {
  return el('section', { style: 'margin-top:20px' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: title }),
      el('span', { class: 'badge', text: String(jobs.length) }),
      el('span', { class: 'page-sub', style: 'margin:0', text: description }),
    ]),
    el('div', { class: 'table-wrap', style: 'margin-top:0' }, [
      el('div', { class: 'table', style: '--table-min:1040px' }, [
        el('div', {
          class: 'table-head', style: `--table-columns:${COLUMNS}`,
          role: 'row',
        }, ['col.job', 'col.state', 'col.trainSet', 'col.startAndDuration',
            'col.outcome', '']
          .map(key => el('span', { text: key ? t(key) : '' }))),
        ...(jobs.length
          ? jobs.map(jobRow)
          : [el('div', { class: 'table-empty', text: emptyText })]),
      ]),
    ]),
  ]);
}

function filters(active, finished) {
  const options = [
    { id: 'all', label: `All (${active.length + finished.length})` },
    { id: 'active', label: `In progress (${active.length})` },
    { id: 'finished', label: `Finished (${finished.length})` },
  ];
  return el('div', {
    style: 'display:flex;gap:2px;border:1px solid var(--line-strong)',
    role: 'group', 'aria-label': t('history.historyFilter'),
  }, options.map(option => el('button', {
    type: 'button', class: 'btn btn-small',
    style: 'border:0;letter-spacing:.02em;text-transform:none;'
      + 'font-family:var(--font-body);font-size:12.5px'
      + (state.historyFilter === option.id
        ? ';background:var(--accent);color:var(--deep)' : ''),
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
      'Jobs in progress',
      'Jobs waiting in the queue and the one running now',
      active,
      'No job is in progress right now.',
    ));
  }
  if (state.historyFilter !== 'active') {
    parts.push(section(
      'Finished jobs',
      'Jobs that completed, were stopped or ended in an error',
      finished,
      'No job has finished this session yet.',
    ));
  }

  fill(root, parts);
}
