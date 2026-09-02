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
//
// THE PAGE ANSWERS ITS OWN QUESTION IN ITS HEADING. It used to be called
// "System state" — a second name for a screen the menu had already named and
// the hidden `h1` says again — with the answer scattered over four tiles
// underneath. Somebody standing at the train wants one sentence: how much of
// this set is answering. That sentence is now the largest thing on the page,
// and the strip under it is the same sentence drawn.

import { el, fill } from '../core/dom.js';
import { state, patch, stateSpread } from '../core/store.js';
import {
  percent, clockTime, age, jobStateLabel, jobOutcomeLabel,
  JOB_OUTCOME_COLOUR, NONE,
} from '../core/format.js';
import { t } from '../core/i18n.js';
import { emptyState } from '../components/placeholder.js';

// THE FIVE STATES, IN THE ORDER THEY ARE DRAWN — and it is one order, used
// by the strip and by the figures under it, so a colour in the bar and a
// number below it are found in the same place.
//
// Reachable leads because it is the share being watched; "not read" trails
// because it is the part still to come. "Needs inspection" sits between
// amber and red, which is what it is: alive, and still an errand.
const SWEEP = ['ok', 'auth', 'review', 'failed', 'unknown'];

// THE SWEEP STRIP — the whole device list as one bar.
// ──────────────────────────────────────────────────
// A device is in exactly one of the four states and the four add up to the
// list, so a scan is a PARTITION and not four independent shares. It was
// drawn as four separate bars, each a percentage of the total, and the shape
// of the thing was lost: reading "how much is left" meant adding three of
// them up, and the category rows below drew a single amber bar whenever the
// count was anything short of all — six rows, six identical ambers, no way
// to tell 88% from 64%.
//
// One strip, and the same strip again on every category row: the set, and
// then each part of the set, drawn with the same instrument.
function sweepStrip(counts, total) {
  return el('div', {
    class: 'sweep', role: 'img',
    'aria-label': t('overview.sweepBreakdown', {
      ok: counts.ok, auth: counts.auth, review: counts.review || 0,
      failed: counts.failed, unknown: counts.unknown,
    }),
  }, SWEEP.map(name => (counts[name] > 0 ? el('i', {
    class: 'sweep-part', dataset: { state: name },
    style: `width:${percent(counts[name], total)}`,
  }) : null)));
}

// A named figure under the strip: one of the four states, its count, and the
// place that state is dealt with. Four figures, four segments, same order.
//
// The old row carried a fifth tile, "Total devices", with a bar under it
// that was full every time — 128 out of 128 is always the whole — and no
// segment of its own. The heading above the strip carries the total now.
function figure(name, stateName, amount, go) {
  return el('button', {
    type: 'button', class: 'stat',
    // A dash is not a value, so it does not take the state's colour: a green
    // "—" beside an amber one looks like three broken readouts rather than
    // three questions nobody has asked yet.
    dataset: { state: amount === NONE ? 'unknown' : stateName },
    onclick: go,
  }, [
    el('div', { class: 'label', text: name }),
    el('div', { class: 'value', text: String(amount) }),
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
  const read = counts.ok + counts.auth + (counts.review || 0) + counts.failed;
  // "Read" is therefore not "the sweep finished": it used to be, and for the
  // whole first scan of a session — the minute the operator watches hardest
  // — every tile on this page read "—" while devices were turning green one
  // by one in the queue. A device that has answered is shown from that
  // moment on.
  const scanned = !!state.lastScan || read > 0;
  const withVersion = devices.filter(
    d => d.result.fields && d.result.fields.version).length;
  const spread = stateSpread();

  const parts = [];

  // THE HEADING IS THE ANSWER, and the line under it says how old that
  // answer is. Both are one sentence each and they never say the same thing:
  // the heading is the state of the set, the line beneath is the state of
  // the reading.
  const verdict = !total
    ? t('overview.noDeviceList')
    : !scanned
      ? t('overview.notReadYet')
      : counts.ok === total
        ? t('overview.allReachable', { total })
        : t('overview.reachableOfTotal', { ok: counts.ok, total });

  // No line at all before the first scan: "no scan has run yet" is already
  // the check summary's row, and the row is the one with the button on it.
  const freshness = state.scanRunning
    ? t('overview.scanRunning', { read, total })
    : state.lastScan
      ? t('overview.lastScanAgo', {
        time: clockTime(state.lastScan), age: age(state.lastScan),
      })
      : null;

  parts.push(el('div', { class: 'page-head overview-head' }, [
    el('div', {}, [
      el('h2', { text: verdict }),
      freshness ? el('div', { class: 'page-sub', text: freshness }) : null,
    ]),
    el('div', { class: 'actions' }, [
      el('button', {
        type: 'button', class: 'btn', text: t('nav.verification'),
        onclick: () => patch({ view: 'checklist' }),
      }),
    ]),
  ]));

  // The one thing on this page that is not in a box. Everything else the
  // panel draws sits inside a card or a table; the strip runs the width of
  // the content and carries the only large area of colour on the screen,
  // which is what makes it the thing seen from across the workshop.
  parts.push(sweepStrip(spread, total || 1));

  parts.push(el('div', { class: 'stat-grid' }, [
    figure(t('devices.reachable'), 'ok', scanned ? counts.ok : NONE,
      () => goToList('ok')),
    figure(t('state.auth'), 'auth', scanned ? counts.auth : NONE,
      () => patch({ lockedOpen: true, queueOpen: false })),
    // Alive on the network but silent on its protocol — a different errand
    // from red, which now purely means "not there at all".
    figure(t('state.review'), 'review',
      scanned ? (counts.review || 0) : NONE,
      () => goToList('review')),
    figure(t('state.failed'), 'failed', scanned ? counts.failed : NONE,
      () => goToList('failed')),
    // The one figure that is a real number before the first scan: "we have
    // not asked yet" is a count, and it is the whole list.
    figure(t('state.unknown'), 'unknown', spread.unknown,
      () => goToList('unknown')),
  ]));

  // ── category status + the right-hand column ──
  // Which types a category covers is a second line under the name. It used
  // to be the row's `title`, which is a tooltip: invisible to a keyboard, to
  // a touch screen, and to anyone who does not happen to rest the pointer on
  // a row. It is two words — "Camera · NVR" — and it answers the question
  // every one of these names raises, so it is on the row.
  //
  // The catalogue's own "All devices" entry is left out: it is the strip at
  // the top of the page, to the device, and a row repeating it was the first
  // thing under it.
  const categoryCard = el('div', { class: 'card corner' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('overview.categorySummary') }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'label', text: t('overview.reachableTotal') }),
    ]),
    ...(state.meta ? state.meta.categories : [])
      .filter(category => category.id !== 'all')
      .map(category => {
        const members = devices.filter(d => d.category === category.id);
        const inState = name => members.filter(
          d => d.result.state === name).length;
        const share = {
          ok: inState('ok'), auth: inState('auth'), failed: inState('failed'),
        };
        share.unknown = Math.max(
          0, members.length - share.ok - share.auth - share.failed);
        return el('button', {
          type: 'button', class: 'category-row',
          onclick: () => patch({
            view: 'devices', category: category.id, subtype: null,
            filter: 'all',
          }),
        }, [
          el('span', { class: 'category-name' }, [
            el('span', { class: 'name', text: category.name }),
            el('span', { class: 'types', text: category.types }),
          ]),
          sweepStrip(share, members.length || 1),
          el('span', {
            class: 'mono text-bright t-sm category-count',
            text: `${share.ok}/${members.length}`,   // numbers only
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
      class: 'dot', dataset: { state: colour }, 'aria-hidden': 'true',
    }),
    el('span', { class: 'text' }, [
      el('span', { class: 'name', text: name }),
    ]),
    el('button', {
      type: 'button', class: 'btn btn-small', text: actionLabel,
      onclick: action,
    }),
  ]);

  const steps = [];
  // While the sweep runs this row says so and offers the queue. It used to
  // carry a progress bar of its own; the strip at the top of the page is now
  // the thing that MOVES while the first devices are being waited for — it
  // fills out of grey as they answer — and two bars counting the same sweep
  // on one screen is the duplication this file exists to avoid.
  if (state.scanRunning) {
    steps.push(stepRow('busy', t('topbar.scanning'),
      t('overview.openTheQueue'),
      () => patch({ queueOpen: true, lockedOpen: false })));
  }
  if (!scanned) {
    if (!state.scanRunning) {
      steps.push(stepRow('busy', t('overview.noScanYet'),
        t('overview.scanNow'), () => refreshNow && refreshNow()));
    }
  } else {
    if (counts.auth) {
      steps.push(stepRow('auth',
        t('overview.needCredentials', { count: counts.auth }),
        t('overview.enterCredentials'),
        () => patch({ lockedOpen: true, queueOpen: false })));
    }
    if (counts.review) {
      steps.push(stepRow('review',
        t('overview.needsInspection', { count: counts.review }),
        t('overview.openTheList'), () => goToList('review')));
    }
    if (counts.failed) {
      steps.push(stepRow('failed',
        t('overview.checkUnfinished', { count: counts.failed }),
        t('overview.openTheList'), () => goToList('failed')));
    }
    if (!steps.length) {
      steps.push(stepRow('ok', t('overview.scanFinished'),
        t('overview.openTheResults'), () => patch({ view: 'checklist' })));
    }
  }

  const stepCard = el('div', { class: 'card corner' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('overview.checkSummary') }),
    ]),
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

  // THE LAST SIX JOBS, in three columns rather than one sentence each. The
  // row used to read "Configuration · 12 devices — Completed", the outcome
  // glued to the end of a name of any length, so the six outcomes — the only
  // part anybody scans this list for — landed at six different places down
  // the column. They are one column now, at the right edge.
  const historyCard = el('div', { class: 'card corner' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('overview.recentJobsThisSession') }),
    ]),
    ...(state.jobs.length
      ? state.jobs.slice(-6).reverse().map(job => el('div', {
          class: 'overview-job-row',
        }, [
          el('span', { class: 'time', text: clockTime(job.createdAt) }),
          el('span', { class: 'title', text: job.title }),
          el('span', {
            class: 'state-text outcome',
            dataset: {
              state: job.outcome ? JOB_OUTCOME_COLOUR[job.outcome]
                : job.state === 'failed' ? 'failed'
                  : job.state === 'done' ? 'ok' : 'busy',
            },
            text: jobOutcomeLabel(job.outcome, jobStateLabel(job.state)),
          }),
        ]))
      : [emptyState(t('overview.noJobHasRunThis'))]),
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
