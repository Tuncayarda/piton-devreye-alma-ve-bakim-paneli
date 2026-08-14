// The job queue panel.
//
// Job rows show only the safe text the server produced: a password, a header
// or a raw stack trace never reaches here.

import { el, fill, icon, $ } from '../core/dom.js';
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import {
  jobStateLabel, jobOutcomeLabel, JOB_OUTCOME_COLOUR, rowStateLabel,
  ROW_COLOUR, clockTime,
} from '../core/format.js';
import { notify, showError } from './toast.js';
import { t } from '../core/i18n.js';

const JOB_COLOUR = {
  queued: 'unknown', running: 'busy', done: 'ok',
  cancelled: 'auth', failed: 'failed',
};

// The list is only rebuilt when it really changed. The device read refreshes
// the state every few seconds; the queue was redrawn on those rounds even
// when unchanged, and the dozens of rows of an open job were recreated every
// time.
let lastSignature = null;

// Rows whose steps are expanded — `${jobId}:${rowId}`. CLOSED BY DEFAULT: an
// IP assignment run has twelve ports with eight to ten steps under each; all
// open, the queue would be a hundred-row dump. When the user wonders where a
// port got to, they press that row.
const expandedRows = new Set();

function toggleRow(key) {
  if (expandedRows.has(key)) expandedRows.delete(key);
  else expandedRows.add(key);
  render();
  // The list is rebuilt: the pressed button disappears, a new one takes its
  // place and focus fell to the body. Someone navigating by keyboard was sent
  // back to the top of the list after expanding a row.
  const rebuilt = $(`[data-row-key="${CSS.escape(key)}"]`);
  if (rebuilt) rebuilt.focus();
}

export function render() {
  const list = $('#queue-list');
  if (!list) return;
  const jobs = state.jobs || [];

  const active = jobs.filter(
    j => j.state === 'queued' || j.state === 'running');
  const badge = $('#queue-count');
  if (badge) {
    badge.textContent = String(active.length);
    badge.hidden = active.length === 0;
  }
  const button = $('#queue-btn');
  if (button) button.setAttribute('aria-expanded', String(!!state.queueOpen));
  $('#queue-panel').hidden = !state.queueOpen;

  // While the panel is closed the list is never built; it is built on open.
  if (!state.queueOpen) { lastSignature = null; return; }

  const signature = `${state.openJob || ''}`
    + `|${[...expandedRows].sort().join(',')}`
    + `|${JSON.stringify(jobs)}`;
  if (signature === lastSignature) return;
  lastSignature = signature;

  fill(list, jobs.slice().reverse().map(jobCard));
}

function jobCard(job) {
  const expanded = state.openJob === job.id;
  const counts = job.counts || {};
  const percent = Math.round((job.progress || 0) * 100);
  const active = job.state === 'queued' || job.state === 'running';
  // Stopping is not instant: the worker may be waiting out a device timeout.
  // In that gap the status reads "Durduruluyor…" and the button is disabled —
  // otherwise the user thinks nothing happened and presses again.
  const stopping = active && job.cancelRequested;
  const outcomeColour = JOB_OUTCOME_COLOUR[job.outcome];
  const colour = stopping ? 'auth'
    : (!active && outcomeColour
      ? outcomeColour
      : (JOB_COLOUR[job.state] || 'unknown'));
  const label = stopping
    ? 'Durduruluyor…'
    : (active
      ? `${jobStateLabel(job.state)} · %${percent}`
      : (jobOutcomeLabel(job.outcome, jobStateLabel(job.state))));

  return el('div', { class: 'job-card', dataset: { state: job.state } }, [
    el('div', { class: 'job-card-head' }, [
      el('button', {
        type: 'button', class: 'job-head',
        'aria-expanded': String(expanded),
        onclick: () => patch({ openJob: expanded ? null : job.id }),
      }, [
        el('span', {
          class: 'dot', dataset: { state: colour },
          'aria-hidden': 'true',
        }),
        el('span', { style: 'min-width:0;flex:1' }, [
          el('span', { class: 'name', text: job.title }),
          el('span', {
            class: 'sub', dataset: { state: colour },
            style: 'color:var(--state-colour)',
            text: label,
          }),
          // The phase: a percentage alone does not answer "where am I".
          // "Port 14 running (3/6)" read next to "50%" makes the run
          // followable.
          active && job.phase
            ? el('span', { class: 'job-phase', text: job.phase })
            : null,
        ]),
        el('span', {
          class: 'job-counts',
          'aria-label': t('queue.countsLabel', {
            ok: counts.ok ?? 0, auth: counts.auth ?? 0,
            failed: counts.failed ?? 0,
          }),
        }, [
          el('span', {
            style: 'color:var(--ok)', text: String(counts.ok ?? 0),
          }),
          el('span', {
            style: 'color:var(--auth)', text: String(counts.auth ?? 0),
          }),
          el('span', {
            style: 'color:var(--failed)', text: String(counts.failed ?? 0),
          }),
        ]),
      ]),
      active
        ? el('button', {
            type: 'button', class: 'btn btn-close',
            disabled: stopping,
            title: t(stopping ? 'queue.stoppingShort'
              : 'queue.stopJobShort'),
            'aria-label': stopping
              ? t('queue.stoppingJob', { job: job.title })
              : t('queue.stopJob', { job: job.title }),
            onclick: async () => {
              try {
                await api.jobCancel(job.id);
                notify(t('queue.stopping', { job: job.title }));
              } catch (e) { showError(e.message); }
            },
          }, ['⏹'])
        : el('button', {
            type: 'button', class: 'btn btn-close',
            title: t('queue.removeFromTheQueue'),
            'aria-label': t('queue.removeJob', { job: job.title }),
            onclick: async () => {
              try {
                await api.jobRemove(job.id);
              } catch (e) { showError(e.message); }
            },
          }, ['×']),
    ]),

    // The progress bar: "how much is left" visible without reading a number.
    active ? el('div', { class: 'job-bar' }, [
      el('i', { style: `width:${percent}%`, dataset: { state: colour } }),
    ]) : null,

    job.error ? el('div', {
      class: 'warning', style: 'margin:8px 11px', text: job.error,
    }) : null,

    expanded ? el('div', { class: 'job-rows' },
      (job.rows || []).map(row => renderRow(row, job.id))) : null,
  ]);
}

function renderRow(row, jobId) {
  const colour = ROW_COLOUR[row.state] || 'unknown';
  const steps = row.steps || [];
  const key = `${jobId}:${row.deviceId}`;
  const expanded = steps.length > 0 && expandedRows.has(key);

  // The sub-line carries the IP only. An error reason ("timed out", "adb
  // connect reddedildi") made the queue unreadable; the detail lives in the
  // device detail and in the row's title.
  //
  // On a file row (the generated Excel) the sub-line is not the IP but the
  // two buttons that open the file: there is no reason to leave the user on
  // the screen that produced the file and send them hunting in Finder.
  const body = [
    el('span', {
      class: 'dot', dataset: { state: colour }, 'aria-hidden': 'true',
    }),
    el('span', { class: 'job-row-body' }, [
      el('span', { class: 'name', text: row.name }),
      row.file
        ? el('span', { class: 'file-actions' }, [
            fileButton(t('queue.openTheFile'), jobId, row.deviceId, false),
            fileButton(t('queue.showInFolder'), jobId, row.deviceId, true),
          ])
        : (row.ip ? el('span', { class: 'sub', text: row.ip }) : null),
    ]),
    el('span', {
      class: 'state', dataset: { state: colour },
      style: 'color:var(--state-colour)',
      text: rowStateLabel(row.state),
    }),
  ];

  // A row with no steps (a file row, a device scan) stays flat as before:
  // turning a row that contains buttons into a button would produce invalid
  // HTML, and there is nothing to expand anyway.
  if (!steps.length) {
    return el('div', {
      class: 'job-row', dataset: { rowState: row.state },
      title: row.note || '',
    }, body);
  }

  return el('div', { class: 'job-row-box' }, [
    el('button', {
      type: 'button', class: 'job-row job-row-btn',
      dataset: { rowState: row.state, expanded: String(expanded), rowKey: key },
      title: row.note || '',
      'aria-expanded': String(expanded),
      // The button overrides its own text content, so the state is repeated:
      // without it a screen reader would read the row as "Port 11 · 8 steps"
      // and never say what state it is in.
      'aria-label': `${row.name} · ${rowStateLabel(row.state)}`
        + ` — ${t('queue.stepCount', { name: '', steps: steps.length })}`,
      onclick: () => toggleRow(key),
    }, [...body, el('span', { class: 'job-chevron', 'aria-hidden': 'true' })]),
    expanded
      ? el('div', { class: 'job-steps' }, steps.map(renderStep))
      : null,
  ]);
}

// A single step under a row: "device found: 10.1.1.12", "writing the IP". The
// time is written too — where a port got stuck is usually clear from how long
// passed between two steps.
function renderStep(step) {
  return el('div', {
    class: 'job-step', dataset: { rowState: step.state || 'info' },
  }, [
    el('span', {
      class: 'dot', dataset: { state: ROW_COLOUR[step.state] || 'unknown' },
      'aria-hidden': 'true',
    }),
    el('span', { class: 'job-step-text', text: step.text }),
    el('span', { class: 'job-step-time', text: clockTime(step.at) }),
  ]);
}

// The icons are drawn from geometry; a font glyph or an emoji would show
// three different things on three operating systems.
const ICONS = {
  open: ['M4 10.5v4.5h12v-4.5', 'M10 3.5v8', 'M7 8.5l3 3 3-3'],
  folder: ['M3 5.5h5l1.4 2H17v8H3z'],
};

function fileButton(label, jobId, rowId, reveal) {
  return el('button', {
    type: 'button', class: 'btn btn-small file-btn',
    title: label, 'aria-label': label,
    onclick: async () => {
      try {
        await api.jobFile(jobId, rowId, reveal);
      } catch (e) { showError(e.message); }
    },
  }, [
    icon(reveal ? ICONS.folder : ICONS.open, 13),
    el('span', { text: reveal ? 'Folder' : 'Open' }),
  ]);
}

export function toggle() {
  patch({ queueOpen: !state.queueOpen, lockedOpen: false });
}

// The "added to the queue" news. Because the panel does not open, the only
// place the news can show is the button itself: the badge already carries the
// count, and this is a short flash that draws the eye there. One timer:
// pressed repeatedly the flash restarts rather than stacking.
let flashTimer = null;

export function flash() {
  const button = $('#queue-btn');
  if (!button) return;
  clearTimeout(flashTimer);
  button.removeAttribute('data-flash');
  // Putting the attribute straight back does not restart the animation; a
  // layout calculation has to be forced in between. requestAnimationFrame
  // would do it too, but it never runs while the window is not painting —
  // feedback must not depend on a paint.
  void button.offsetWidth;
  button.setAttribute('data-flash', '1');
  flashTimer = setTimeout(() => button.removeAttribute('data-flash'), 2600);
}

// `refreshed`: how many devices the light refresh reached. Written in the
// footer when no job is running — seeing the number makes it clear that the
// refresh only reads verified devices.
export function summaryText(refreshed = 0) {
  const job = (state.jobs || []).find(
    j => j.state === 'running' || j.state === 'queued');
  if (job && job.cancelRequested) {
    return t('queue.jobStopping', { job: job.title });
  }
  if (!job) {
    // "No scan yet" is no longer a gap but a few seconds of transition: the
    // scan starts on its own at start-up.
    if (!state.lastScan) return t('queue.waitingFirstScan');
    const fresh = t('queue.lastScan', { time: clockTime(state.lastScan) });
    return refreshed
      ? t('queue.lastScanReread', { scan: fresh, count: refreshed })
      : t('queue.lastScanNoReread', { scan: fresh });
  }
  return t('queue.jobProgress', {
    job: job.title, percent: Math.round((job.progress || 0) * 100),
  });
}
