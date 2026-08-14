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
// caption under the bar; the number and the bar already said the same thing
// and the extra line was only noise.
function kpi(name, amount, unit, colour, ratio, go, hint) {
  return el('button', {
    type: 'button', class: 'kpi corner', title: hint || '', onclick: go,
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
  patch({ view: 'devices', category: 'all', subtype: null, filter });
}

export function render(root, refreshNow) {
  const devices = state.devices;
  const total = devices.length;
  const counts = state.counts;
  const scanned = !!state.lastScan;
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
        text: scanned
          ? t('overview.lastScanAgo', {
            time: clockTime(state.lastScan), age: age(state.lastScan),
          })
          : t('overview.notReadYet'),
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
      () => goToList('all'), t('overview.listEveryDevice')),
    kpi(t('devices.reachable'), scanned ? counts.ok : NONE,
      t('overview.outOfTotal', { total }), 'ok',
      percent(counts.ok, total),
      () => goToList('active'), t('overview.listReachable')),
    kpi(t('state.auth'), scanned ? counts.auth : NONE,
      t('overview.outOfTotal', { total }),
      'auth', percent(counts.auth, total),
      () => patch({ lockedOpen: true, queueOpen: false }),
      t('overview.openLockedDevices')),
    kpi(t('devices.needsReview'), scanned ? counts.failed : NONE,
      t('overview.outOfTotal', { total }), 'failed',
      percent(counts.failed, total),
      () => goToList('problem'), t('overview.listUnfinished')),
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
          class: 'mono text-bright', style: 'font-size:11px;text-align:right',
          text: `${reachable}/${members.length}`,   // numbers only
        }),
      ]);
    }),
  ]);

  // ── check summary ──
  // The card only shows a row when there is work to do; each row leads to
  // where that work is done.
  const stepRow = (colour, name, note, actionLabel, action) => el('div', {
    class: 'step-row',
  }, [
    el('span', {
      class: 'dot', style: `background:var(--${colour})`,
      'aria-hidden': 'true',
    }),
    el('span', { class: 'text' }, [
      el('span', { class: 'name', text: name }),
      note ? el('span', { class: 'note', text: note }) : null,
    ]),
    el('button', {
      type: 'button', class: 'btn btn-small', text: actionLabel,
      onclick: action,
    }),
  ]);

  const steps = [];
  if (!scanned) {
    steps.push(stepRow('accent', t('overview.noScanYet'),
      t('overview.noScanYetNote'),
      t('overview.scanNow'), () => refreshNow && refreshNow()));
  } else {
    if (counts.auth) {
      steps.push(stepRow('auth',
        t('overview.needCredentials', { count: counts.auth }),
        t('overview.credentialsNote'),
        t('overview.enterCredentials'),
        () => patch({ lockedOpen: true, queueOpen: false })));
    }
    if (counts.failed) {
      steps.push(stepRow('failed',
        t('overview.checkUnfinished', { count: counts.failed }),
        t('overview.checkUnfinishedNote'),
        t('overview.openTheList'), () => goToList('problem')));
    }
    if (!steps.length) {
      steps.push(stepRow('ok', t('overview.scanFinished'),
        t('overview.scanFinishedNote'),
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
          style: 'display:flex;gap:10px;padding:6px 0;'
            + 'font-family:var(--font-mono);font-size:10.5px;line-height:1.5',
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

  parts.push(el('div', { class: 'overview-grid' }, [
    categoryCard,
    el('div', { style: 'display:flex;flex-direction:column;gap:18px' },
      [stepCard, historyCard]),
  ]));

  fill(root, parts);
}
