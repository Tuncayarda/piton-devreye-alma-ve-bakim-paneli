// The checklist — a preview of what will be written to Excel.
//
// The point is to see the output in advance: the columns are the template's
// columns and all of them are here. If the template changes, the list changes;
// no separate column list is kept in the code.
//
// A grey (N/A) cell means "not used on this device type"; "—" means "not read
// yet". The two are shown differently.

import { el, fill, $ } from '../core/dom.js';
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import { showError, showSuccess } from '../components/toast.js';
import * as detail from '../components/detail.js';
import * as dialog from '../components/dialog.js';
import { NONE, clockTime, age, stateLabel } from '../core/format.js';
import { t } from '../core/i18n.js';

// Column widths, keyed by the server's stable column id (see
// panel/checklist/columns.py) rather than by the heading in the sheet: a
// reworded heading must not silently drop a width.
const WIDTHS = {
  section: 88,
  switch: 104,
  port: 52,
  deviceDefinition: 164,
  ipTemplate: 104,
  expectedIp: 104,
  expectedVersion: 112,
  expectedSipExtension: 124,
  deviceName: 164,
  connectionInfo: 116,
  version: 88,
  deviceNumber: 124,
  statusDescription: 112,
  uptime: 100,
};
const DEFAULT_WIDTH = 112;

// Matching a read value against the expected value from the template: the
// left column is read from the device, the right one is expected. Matching
// shows green, mismatching red — so whoever looks at the table sees the
// deviation without reading it.
const COMPARE_WITH = {
  connectionInfo: 'expectedIp',
  version: 'expectedVersion',
  sipExtension: 'expectedSipExtension',
};

// Columns that carry a value from the template, not from a device.
const EXPECTED_COLUMNS = new Set([
  'expectedIp', 'expectedVersion', 'expectedSipExtension',
]);

// The value written into the status column when the device answered.
const STATUS_ACTIVE = 'active';

// The comparison must not trip over formatting: leading/trailing space and
// case carry no meaning.
const normalise = (v) => String(v).trim().toLowerCase().replace(/\s+/g, ' ');

// How long before the data counts as "stale". In the field, producing the
// Excel from a read taken ten minutes ago is useless: devices get restarted,
// IPs change and cables get pulled in the meantime.
const STALE_SECONDS = 120;

// In daily use only the deviations are shown. The Excel preview is a separate
// local tab for whoever wants to see every column of the template.
let reportTab = 'deviations';

const DEVIATION_COLUMNS =
  'minmax(170px,1.1fr) 112px minmax(260px,1.7fr) 150px';

const isEmpty = (v) => v === null || v === undefined || String(v).trim() === '';

function rowValues(row, columns) {
  const values = new Map();
  row.cells.forEach((cell, i) => {
    if (!cell.notApplicable && columns[i] && columns[i].id) {
      values.set(columns[i].id, cell.value);
    }
  });
  return values;
}

// The user's chosen definition of healthy: reachability + IP + the SIP
// extension where there is one. Version and the other configuration fields
// still appear in the report but do not decide whether the device passed its
// basic checks.
function evaluate(row, columns) {
  const values = rowValues(row, columns);
  const problems = [];

  if (row.state !== 'ok') {
    const code = row.state === 'auth' ? 'auth'
      : row.state === 'unknown' ? 'unread' : 'reach';
    const text = code === 'auth' ? t('verify.authrequired')
      : code === 'unread' ? t('verify.notread')
        : (row.detail || t('checklist.notReachable'));
    problems.push({ code, text });
    return { problems, values, passed: false };
  }

  const expectedIp = values.get('expectedIp');
  const readIp = values.get('connectionInfo');
  if (!isEmpty(expectedIp)
      && (isEmpty(readIp) || normalise(readIp) !== normalise(expectedIp))) {
    problems.push({
      code: 'ip',
      text: isEmpty(readIp)
        ? t('checklist.ipUnverified', { expected: expectedIp })
        : t('checklist.ipMismatch',
          { expected: expectedIp, read: readIp }),
    });
  }

  const expectedSip = values.get('expectedSipExtension');
  const readSip = values.get('sipExtension');
  if (!isEmpty(expectedSip)
      && (isEmpty(readSip) || normalise(readSip) !== normalise(expectedSip))) {
    problems.push({
      code: 'sip',
      text: isEmpty(readSip)
        ? t('checklist.sipUnread', { expected: expectedSip })
        : t('checklist.sipMismatch',
          { expected: expectedSip, read: readSip }),
    });
  }

  return { problems, values, passed: problems.length === 0 };
}

function summaryCard(name, amount, colour, note) {
  return el('div', { class: 'check-summary-card' }, [
    el('span', { class: 'name', text: name }),
    el('strong', { style: `color:var(--${colour})`, text: String(amount) }),
    el('span', { class: 'note', text: note }),
  ]);
}

function deviationTable(rows, columns) {
  const deviations = rows
    .map(row => ({ row, result: evaluate(row, columns) }))
    .filter(entry => !entry.result.passed);

  if (!deviations.length) {
    return el('div', { class: 'empty-state empty-state-success' }, [
      el('strong', { text: t('checklist.theBasicChecksFoundNothing') }),
      el('span', {
        text: t('checklist.withinTheSelectedScopeAccess'),
      }),
    ]);
  }

  return el('div', { class: 'table-wrap' }, [
    el('div', { class: 'table', style: '--table-min:820px' }, [
      el('div', {
        class: 'table-head', style: `--table-columns:${DEVIATION_COLUMNS}`,
        role: 'row',
      }, ['col.device', 'col.expectedIp', 'col.finding', 'col.accessState']
        .map(key => el('span', { text: key ? t(key) : '' }))),
      ...deviations.map(({ row, result }) => el('button', {
        type: 'button', class: 'table-row check-deviation-row',
        style: `--table-columns:${DEVIATION_COLUMNS}`,
        title: t('checklist.openDetails', { device: row.name }),
        onclick: () => { if (row.deviceId) detail.open(row.deviceId); },
      }, [
        el('span', { class: 'device-summary' }, [
          el('span', {
            class: 'dot', dataset: { state: row.state },
            'aria-hidden': 'true',
          }),
          el('span', { class: 'mono truncate', text: row.name || NONE }),
        ]),
        el('span', { class: 'mono', text: row.ip || NONE }),
        el('span', {
          class: 'deviation-text',
          text: result.problems.map(p => p.text).join(' · '),
        }),
        el('span', {
          class: 'state-text', dataset: { state: row.state },
          text: stateLabel(row.state, NONE),
        }),
      ])),
    ]),
  ]);
}

function excelPreview(rows, data) {
  const template = data.columns
    .map(column => `${WIDTHS[column.id] || DEFAULT_WIDTH}px`)
    .join(' ');
  const minimum = data.columns
    .reduce((total, column) => total + (WIDTHS[column.id] || DEFAULT_WIDTH),
            0)
    + data.columns.length * 10;

  return [
    el('div', {
      class: 'info check-excel-note', text: t('checklist.excelNote'),
    }),
    el('div', { class: 'table-wrap' }, [
      el('div', { class: 'table', style: `--table-min:${minimum}px` }, [
        el('div', {
          class: 'table-head', style: `--table-columns:${template}`,
          role: 'row',
        }, data.columns.map(column => el('span', {
          class: 'truncate', title: column.name, text: column.name,
        }))),
        ...(rows.length
          ? rows.map(row => renderRow(row, data.columns, template))
          : [el('div', {
              class: 'table-empty', text: t('checklist.noDeviceInThisCategory'),
            })]),
      ]),
    ]),
    el('div', { class: 'legend legend-plain' }, [
      el('span', {}, [el('i', { style: 'background:var(--auth)' }),
        t('checklist.legendAmber')]),
      el('span', {}, [el('i', { style: 'background:var(--ok)' }),
        t('checklist.legendGreen')]),
      el('span', {}, [el('i', { style: 'background:var(--failed)' }),
        t('checklist.legendRed')]),
      el('span', {}, [el('i', { style: 'background:#2a3339' }),
        t('checklist.legendGrey')]),
      el('span', {
        style: 'margin-left:auto',
        text: t('checklist.rowsColumns', {
          rows: rows.length, columns: data.columns.length,
        }),
      }),
    ]),
  ];
}

export async function refresh() {
  try {
    patch({ checklistState: await api.checklist(state.setNo) });
  } catch (e) {
    showError(e.message);
    patch({ checklistState: null });
  }
}

// ── freshness indicator ─────────────────────────────────────────────────
// The "37 s ago" text refreshes itself every second. That does not need a
// full screen render — the text is written directly (same route as ip.js).
let tickTimer = null;

function onScreen() {
  return state.view === 'checklist' && !!state.role;
}

function writeFreshness() {
  const node = $('#check-freshness');
  if (!node) return;
  const ts = Number(node.dataset.readAt) || 0;
  if (!ts) {
    node.textContent = t('checklist.noScanYet');
    node.dataset.stale = '1';
    return;
  }
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - ts));
  node.textContent = t('checklist.lastScanAgo',
    { time: clockTime(ts), age: age(ts) });
  node.dataset.stale = seconds > STALE_SECONDS ? '1' : '0';
}

// The tick stops by itself on leaving the screen: when `onScreen()` turns
// false the next round is not scheduled (same route as ip.js).
function startTicker() {
  clearTimeout(tickTimer);
  if (!onScreen()) return;
  writeFreshness();
  tickTimer = setTimeout(startTicker, 1000);
}

// The age of the data — the Excel confirmation uses this too.
function lastScanAt() {
  const data = state.checklistState;
  return (data && data.lastScan) || state.lastScan || 0;
}

// The action that pulls the scan forward comes from app.js: it also resets
// the minute timer (see app.refreshNow). Writing a second /api/scan call here
// would mean the automatic round firing right after the button too.
let pullScanForward = () => {};

export function render(root, refreshNow) {
  if (refreshNow) pullScanForward = refreshNow;
  const data = state.checklistState;
  const parts = [];

  parts.push(el('div', { class: 'page-head' }, [
    el('div', {}, [
      el('h2', { text: t('nav.verification') }),
      // The list refreshes on its own; how fresh it is written here. The
      // Excel confirmation shows the same stamp.
      el('div', {
        id: 'check-freshness', class: 'page-sub check-freshness',
        dataset: { readAt: lastScanAt() || 0 },
      }),
    ]),
    el('div', { class: 'actions' }, [
      el('button', {
        type: 'button', class: 'btn', text: t('topbar.scanNow'),
        disabled: state.scanRunning,
        // Same job as "Scan now" in the top bar: pulls the next scan
        // forward, the queue panel does not open, the news appears on the
        // queue button.
        onclick: () => pullScanForward(),
      }),
      el('button', {
        type: 'button', class: 'btn btn-primary', text: t('checklist.generateExcel'),
        onclick: confirmExport,
      }),
    ]),
  ]));

  if (!data) {
    parts.push(el('p', {
      class: 'info',
      text: t('checklist.theVerificationDataCouldNot'),
    }));
    fill(root, parts);
    return;
  }

  // ── local view and category filter ──
  parts.push(el('div', {
    class: 'local-tabs report-tabs', role: 'tablist',
    'aria-label': t('checklist.reportView'),
  }, [
    ['deviations', 'checklist.tabDeviations'],
    ['excel', 'checklist.tabExcel'],
  ].map(([id, labelKey]) => el('button', {
    type: 'button', class: 'local-tab', role: 'tab',
    'aria-selected': String(reportTab === id),
    'aria-pressed': String(reportTab === id),
    text: t(labelKey),
    onclick: () => { reportTab = id; render(root); },
  }))));

  const categories = state.meta ? state.meta.categories : [];
  const allRows = data.sections.flatMap(section => section.rows);
  const deviceCategory = new Map(
    state.devices.map(device => [device.id, device.category]));

  const selected = state.checklistCategory || 'all';
  const countFor = (id) => (id === 'all'
    ? allRows.length
    : allRows.filter(
      row => deviceCategory.get(row.deviceId) === id).length);

  parts.push(el('div', {
    class: 'chip-bar', role: 'group', 'aria-label': t('checklist.categoryFilter'),
  }, [
    el('span', { class: 'label', text: t('checklist.category') }),
    ...categories.map(category => el('button', {
      type: 'button', class: 'chip',
      'aria-pressed': String(selected === category.id),
      title: category.types,
      onclick: () => patch({ checklistCategory: category.id }),
    }, [
      el('span', { text: category.name }),
      el('span', { class: 'count', text: String(countFor(category.id)) }),
    ])),
  ]));

  const rows = selected === 'all'
    ? allRows
    : allRows.filter(row => deviceCategory.get(row.deviceId) === selected);

  const results = rows.map(row => evaluate(row, data.columns));
  const passed = results.filter(r => r.passed).length;
  const reachIssues = results.filter(r => r.problems.some(
    p => ['reach', 'auth', 'unread'].includes(p.code))).length;
  const ipIssues = results.filter(
    r => r.problems.some(p => p.code === 'ip')).length;
  const sipIssues = results.filter(
    r => r.problems.some(p => p.code === 'sip')).length;

  parts.push(el('div', { class: 'check-criteria' }, [
    el('span', { class: 'label', text: t('checklist.basicCheckCriteria') }),
    el('span', { text: t('checklist.accessIpSipExtension') }),
  ]));
  parts.push(el('div', { class: 'check-summary-grid' }, [
    summaryCard(t('checklist.passedBasicChecks'), passed, 'ok',
      t('checklist.devicesInTotal', { count: rows.length })),
    summaryCard(t('checklist.accessProblems'), reachIssues,
      reachIssues ? 'failed' : 'ok',
      t('checklist.accessProblemsNote')),
    summaryCard(t('checklist.ipDeviations'), ipIssues,
      ipIssues ? 'failed' : 'ok', t('checklist.ipDeviationsNote')),
    summaryCard(t('checklist.sipDeviations'), sipIssues,
      sipIssues ? 'failed' : 'ok', t('checklist.sipDeviationsNote')),
  ]));

  if (reportTab === 'excel') {
    parts.push(...excelPreview(rows, data));
  } else {
    parts.push(el('div', { class: 'section-head' }, [
      el('div', {}, [
        el('h3', { text: t('checklist.devicesToReview') }),
      ]),
      el('span', {
        class: 'badge',
        text: t('checklist.deviceCount', { count: rows.length - passed }),
      }),
    ]));
    parts.push(deviationTable(rows, data.columns));
  }

  fill(root, parts);
  startTicker();
}

// Shows the age of the data before producing the Excel.
//
// The reason comes from the field: when a file was produced, nobody knew
// which moment it belonged to. Producing an Excel from a snapshot read ten
// minutes ago hands whoever signs that file a wrong "this is how it is right
// now" document. The confirmation is therefore not an info box but a decision
// point: when the data is not fresh it offers to pull the scan forward first.
function confirmExport() {
  const ts = lastScanAt();
  const seconds = ts ? Math.round(Date.now() / 1000 - ts) : null;
  const stale = seconds === null || seconds > STALE_SECONDS;
  const counts = (state.checklistState && state.checklistState.counts)
    || state.counts || {};

  const line = (name, amount, colour) => el('div', {
    class: 'summary-row',
  }, [
    el('span', { text: name }),
    el('span', {
      style: colour ? `color:${colour}` : null, text: String(amount),
    }),
  ]);

  const content = el('div', {}, [
    el('p', { class: 'description' }, [
      ts
        ? t('checklist.builtFromLastScan', { time: clockTime(ts) })
        : t('checklist.builtEmpty'),
    ]),
    el('div', { class: 'summary-box' }, [
      line(t('checklist.dataAge'),
        ts ? t('checklist.agoValue', { age: age(ts) }) : NONE,
        stale ? 'var(--auth)' : 'var(--ok)'),
      line(t('devices.reachable'), `${counts.ok ?? 0}`, 'var(--ok)'),
      line(t('state.auth'), `${counts.auth ?? 0}`, 'var(--auth)'),
      line(t('devices.needsReview'), `${counts.failed ?? 0}`,
        'var(--failed)'),
    ]),
    stale ? el('p', {
      class: 'warning', style: 'margin-top:12px',
      text: t('checklist.theDataMayBeOut'),
    }) : el('p', {
      class: 'info', style: 'margin-top:12px',
      text: t('checklist.theDataIsCurrentThe'),
    }),
  ]);

  const produce = async () => {
    dialog.close();
    try {
      const job = await api.checklistExport(state.setNo);
      patch({ queueOpen: true, openJob: job.id });
      showSuccess(t('checklist.theExcelGenerationJobWas'));
    } catch (e) { showError(e.message); }
  };

  dialog.show({
    title: t('checklist.generateExcel'),
    content,
    actions: [
      el('button', {
        type: 'button', class: 'btn', text: t('locked.cancel'),
        onclick: () => dialog.close(),
      }),
      el('button', {
        type: 'button', class: 'btn', text: t('checklist.scanFirst'),
        disabled: state.scanRunning,
        title: t(state.scanRunning ? 'checklist.scanAlreadyRunning'
          : 'checklist.scanThenGenerate'),
        onclick: () => { dialog.close(); pullScanForward(); },
      }),
      el('button', {
        type: 'button', class: 'btn btn-primary',
        text: t(stale ? 'checklist.generateAnyway'
          : 'checklist.generateExcel'),
        onclick: produce,
      }),
    ],
  });
}

// A cell's text colour and tooltip.
//
// The colour follows what the cell says: expected (template) values amber,
// values read from the device compared with the expected one and shown green
// or red, reachability green/red. With no expected value to compare against,
// the old neutral colours are kept.
function cellHighlight(column, cell, values) {
  const text = cell.value === null || cell.value === undefined
    ? '' : String(cell.value);
  if (text === '') {
    return { colour: 'var(--text-faint)', hint: t('probe.notReadYet') };
  }

  if (EXPECTED_COLUMNS.has(column)) {
    return {
      colour: 'var(--auth)',
      hint: t('checklist.expectedValue', { value: text }),
    };
  }

  if (column === 'statusDescription') {
    const active = normalise(text) === STATUS_ACTIVE;
    return {
      colour: active ? 'var(--ok)' : 'var(--failed)',
      hint: t(active ? 'checklist.deviceWasReached'
        : 'checklist.deviceNotReached'),
    };
  }

  const expected = String(values.get(COMPARE_WITH[column]) || '');
  if (expected) {
    return normalise(text) === normalise(expected)
      ? {
          colour: 'var(--ok)',
          hint: t('checklist.matchesExpected', { value: text }),
        }
      : {
          colour: 'var(--failed)',
          hint: t('checklist.expectedRead',
                  { expected, read: text }),
        };
  }

  return {
    colour: cell.source === 'probe' ? 'var(--text)' : 'var(--text-bright)',
    hint: text,
  };
}

function renderRow(row, columns, template) {
  // To compare a read cell against the expected one, the row's values are
  // indexed by column heading.
  const values = rowValues(row, columns);

  return el('button', {
    type: 'button', class: 'table-row',
    style: `--table-columns:${template}`,
    dataset: { state: row.state },
    title: `${row.name} · ${row.ip} — ${row.detail}`,
    onclick: () => { if (row.deviceId) detail.open(row.deviceId); },
  }, row.cells.map((cell, i) => {
    if (cell.notApplicable) {
      // A cell greyed out in the template: a field invalid on this device
      // type. No text is written — seeing "N/A" in half of 23 columns made
      // the table unreadable. The grey ground already carries the meaning,
      // and the explanation lives in the tooltip and the legend.
      return el('span', {
        class: 'na-cell', title: t('checklist.notUsedOnThisDevice'),
        'aria-label': t('checklist.notUsedOnThisDevice'),
      });
    }
    const empty = cell.value === '' || cell.value === null;
    if (i === 0) {
      // The first column carries the row's state colour too
      return el('span', {
        style: 'display:flex;align-items:center;gap:7px;min-width:0',
      }, [
        el('span', {
          class: 'dot', dataset: { state: row.state }, 'aria-hidden': 'true',
        }),
        el('span', {
          class: 'mono truncate', style: 'font-size:11px',
          text: empty ? NONE : String(cell.value),
        }),
      ]);
    }
    const column = columns[i] || {};
    const name = column.name || '';
    const { colour, hint } = cellHighlight(column.id || '', cell, values);
    return el('span', {
      class: 'mono truncate',
      style: `font-size:11px;color:${colour}`,
      title: `${name}${name ? ' — ' : ''}${hint}`,
      text: empty ? NONE : String(cell.value),
    });
  }));
}
