// Overview — the system summary, what needs attention, and this session's
// jobs.
//
// Every number comes from the current scan snapshot. With no scan yet the
// numbers do not read zero but "not read": 0 reachable devices and "we have
// not asked yet" are different things.
//
// The same information never appears twice on the page. The old "System
// summary" card repeated the category list under different names (Anons
// chain = Announcement equipment, video system = Video system …); a short check
// summary that names the situations needing action took its place.
//
// Every number on the page is clickable: seeing a number and then hunting for
// the device list behind it was an extra step.

import { el, fill } from '../core/dom.js';
import { state, patch } from '../core/store.js';
import {
  percent, clockTime, age, jobStateLabel, jobOutcomeLabel, NONE,
} from '../core/format.js';
import { t } from '../core/i18n.js';

// The tiles: a big number, what it sits within, and a fill bar. There is no
// caption under the bar and no tooltip on the tile; the name, the number and
// the bar already said it, and a title that reworded the name was one more
// thing to read.
function kpi(name, amount, unit, colour, ratio, go) {
  return el('button', {
    type: 'button', class: 'kpi corner', onclick: go,
  }, [
    el('div', { class: 'name', text: name }),
    el('div', { class: 'value-wrap' }, [
      el('span', {
        class: 'value', style: `color:var(--${colour})`, text: String(amount),
      }),
      unit ? el('span', { class: 'unit', text: unit }) : null,
    ]),
    el('div', { class: 'bar' }, [
      el('i', { style: `width:${ratio};background:var(--${colour})` }),
    ]),
  ]);
}

// Goes to the device list with a given filter.
function goToList(filter) {
  patch({ view: 'devices', category: 'all', subtype: null, filter,
         deviceSearch: '' });
}

export function render(root, refreshNow) {
  const devices = state.devices;
  const total = devices.length;
  const counts = state.counts;
  // How many devices have answered so far. A scan that is still running has
  // already settled some of them, and those answers are real.
  const read = counts.ok + counts.auth + counts.failed;
  // "Read" is therefore not "the sweep finished": it used to be, and for the
  // whole first scan of a session — the minute the operator watches hardest
  // — every tile on this page read "—" while devices were turning green one
  // by one in the queue. A device that has answered is shown from that
  // moment on.
  const scanned = !!state.lastScan || read > 0;
  const withVersion = devices.filter(
    d => d.result.fields && d.result.fields.version).length;

  const parts = [];

  // The scan time in the heading says how fresh every number on the page is;
  // it is the one thing to see before looking at the numbers.
  parts.push(el('div', { class: 'page-head' }, [
    el('div', {}, [
      el('h2', { text: t('overview.systemState') }),
      el('div', {
        class: 'page-sub',
        text: state.lastScan
          ? t('overview.lastScanAgo', {
            time: clockTime(state.lastScan), age: age(state.lastScan),
          })
          : (state.scanRunning
            ? t('overview.scanRunning', { read, total })
            : t('overview.notReadYet')),
      }),
    ]),
    el('div', { class: 'actions' }, [
      el('button', {
        type: 'button', class: 'btn', text: t('nav.verification'),
        onclick: () => patch({ view: 'checklist' }),
      }),
    ]),
  ]));

  parts.push(el('div', { class: 'kpi-grid' }, [
    kpi(t('overview.totalDevices'), total, t('overview.records'),
      'accent', '100%',
      () => goToList('all')),
    kpi(t('devices.reachable'), scanned ? counts.ok : NONE,
      t('overview.outOfTotal', { total }), 'ok',
      percent(counts.ok, total),
      () => goToList('active')),
    kpi(t('state.auth'), scanned ? counts.auth : NONE,
      t('overview.outOfTotal', { total }),
      'auth', percent(counts.auth, total),
      () => patch({ lockedOpen: true, queueOpen: false })),
    kpi(t('devices.needsReview'), scanned ? counts.failed : NONE,
      t('overview.outOfTotal', { total }), 'failed',
      percent(counts.failed, total),
      () => goToList('problem')),
  ]));

  // ── category status + the right-hand column ──
  // Which types a category covers lives in the row's tooltip; written as a
  // separate column on every row, the list became unreadable.
  const categoryCard = el('div', { class: 'card corner' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('overview.categorySummary') }),
      el('span', { style: 'flex:1' }),
      el('span', { class: 'label', text: t('overview.reachableTotal') }),
    ]),
    ...(state.meta ? state.meta.categories : []).map(category => {
      const members = category.id === 'all'
        ? devices
        : devices.filter(d => d.category === category.id);
      const reachable = members.filter(d => d.result.state === 'ok').length;
      const barColour = !members.length ? 'unknown'
        : reachable === members.length ? 'ok'
          : reachable ? 'auth' : 'unknown';
      return el('button', {
        type: 'button', class: 'category-row',
        title: t('overview.categoryTooltip',
                     { category: category.name, types: category.types }),
        onclick: () => patch({
          view: 'devices', category: category.id, subtype: null,
          filter: 'all',
        }),
      }, [
        el('span', { class: 'name', text: category.name }),
        el('span', { class: 'bar' }, [
          el('i', {
            style: `width:${percent(reachable, members.length)};`
              + `background:var(--${barColour})`,
          }),
        ]),
        el('span', {
          class: 'mono text-bright t-sm', style: 'text-align:right',
          text: `${reachable}/${members.length}`,   // numbers only
        }),
      ]);
    }),
  ]);

  // ── check summary ──
  // The card only shows a row when there is work to do; each row leads to
  // where that work is done.
  const stepRow = (colour, name, actionLabel, action) => el('div', {
    class: 'step-row',
  }, [
    el('span', {
      class: 'dot', style: `background:var(--${colour})`,
      'aria-hidden': 'true',
    }),
    el('span', { class: 'text' }, [
      el('span', { class: 'name', text: name }),
    ]),
    el('button', {
      type: 'button', class: 'btn btn-small', text: actionLabel,
      onclick: action,
    }),
  ]);

  // While the sweep runs the card carries its progress — as a BAR, not as a
  // sentence. It used to repeat the page subtitle word for word two hundred
  // pixels below it, and on the first scan of a session that is the whole
  // screen: the same sentence twice, three dashes and an empty category
  // list. That state used to sit behind the role screen; with the role
  // screen gone it is what every launch opens on, so it has to look like a
  // panel waiting rather than a panel broken.
  //
  // The bar is also the only thing on the page that MOVES while the first
  // devices are being waited for — a full sweep costs one timeout per
  // unreachable address, so this can be the view for a minute.
  const progressRow = () => el('div', { class: 'step-row' }, [
    el('span', {
      class: 'dot', style: 'background:var(--accent)', 'aria-hidden': 'true',
    }),
    el('span', { class: 'text' }, [
      // A row whose first line is a bar has nothing to hang on, so the bar
      // keeps a label — one word, not the sentence the page subtitle above
      // already carries.
      el('span', { class: 'name', text: t('topbar.scanning') }),
      el('span', { class: 'scan-progress' }, [
        el('span', {
          class: 'bar', role: 'progressbar',
          'aria-valuemin': '0', 'aria-valuemax': String(total),
          'aria-valuenow': String(read),
          // The sentence the bar replaces, kept where it costs no space: a
          // bar on its own tells a screen reader nothing.
          'aria-label': t('overview.scanRunning', { read, total }),
        }, [el('i', { style: `width:${percent(read, total)}` })]),
        el('span', {
          class: 'mono text-bright t-sm', text: `${read}/${total}`,
        }),
      ]),
    ]),
    el('button', {
      type: 'button', class: 'btn btn-small', text: t('overview.openTheQueue'),
      onclick: () => patch({ queueOpen: true, lockedOpen: false }),
    }),
  ]);

  const steps = [];
  // Without this row the summary claimed "the scan finished" the moment the
  // first few devices came back green.
  if (state.scanRunning) steps.push(progressRow());
  if (!scanned) {
    if (!state.scanRunning) {
      steps.push(stepRow('accent', t('overview.noScanYet'),
        t('overview.scanNow'), () => refreshNow && refreshNow()));
    }
  } else {
    if (counts.auth) {
      steps.push(stepRow('auth',
        t('overview.needCredentials', { count: counts.auth }),
        t('overview.enterCredentials'),
        () => patch({ lockedOpen: true, queueOpen: false })));
    }
    if (counts.failed) {
      steps.push(stepRow('failed',
        t('overview.checkUnfinished', { count: counts.failed }),
        t('overview.openTheList'), () => goToList('problem')));
    }
    if (!steps.length) {
      steps.push(stepRow('ok', t('overview.scanFinished'),
        t('overview.openTheResults'), () => patch({ view: 'checklist' })));
    }
  }

  const stepCard = el('div', { class: 'card corner' }, [
    el('h3', { style: 'margin-bottom:4px', text: t('overview.checkSummary') }),
    ...steps,
    // Reading the version is a separate measure from verification: a device
    // may answer and still not report its version.
    el('div', { class: 'step-footer' }, [
      el('span', { text: t('overview.devicesReportingAVersion') }),
      el('span', {
        class: 'mono text-bright',
        text: scanned ? `${withVersion}/${total}` : `${NONE}/${total}`,
      }),
    ]),
  ]);

  const historyCard = el('div', { class: 'card corner' }, [
    el('h3', {
      style: 'margin-bottom:11px', text: t('overview.recentJobsThisSession'),
    }),
    ...(state.jobs.length
      ? state.jobs.slice(-6).reverse().map(job => el('div', {
          class: 't-xs',
          style: 'display:flex;gap:10px;padding:6px 0;'
            + 'font-family:var(--font-mono);line-height:1.5',
        }, [
          el('span', {
            class: 'text-dim', style: 'flex:none',
            text: clockTime(job.createdAt),
          }),
          el('span', {
            class: 'dot',
            dataset: {
              state: job.state === 'failed' ? 'failed'
                : job.state === 'done' ? 'ok' : 'auth',
            },
            style: 'margin-top:5px',
            'aria-hidden': 'true',
          }),
          el('span', {
            class: 'text-bright',
            text: t('overview.jobOutcome', {
              job: job.title,
              outcome: jobOutcomeLabel(job.outcome,
                                       jobStateLabel(job.state)),
            }),
          }),
        ]))
      : [el('div', {
        class: 'empty-state', text: t('overview.noJobHasRunThis'),
      })]),
  ]);

  // ONE LAYOUT, WHATEVER THE SCAN IS DOING. The check summary used to lead
  // full width until the first device answered and then move into the right
  // column — the reasoning being that before a scan it is the only card with
  // anything to say. But the move happens at the exact moment the numbers
  // start arriving: the card an operator is reading, the one carrying the
  // buttons, jumps across the page while their attention is already going
  // to the tiles. A card that stays where it was put is worth more than a
  // card that is briefly bigger.
  parts.push(el('div', { class: 'overview-grid' }, [
    categoryCard,
    el('div', { class: 'overview-column' }, [stepCard, historyCard]),
  ]));

  fill(root, parts);
}
