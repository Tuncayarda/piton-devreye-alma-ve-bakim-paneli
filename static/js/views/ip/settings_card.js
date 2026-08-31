// The "IP settings" card: everything the operator sets before the run.
//
// One card, but three questions stacked inside it — which switch, which
// ports, and which addresses — and the third differs by target, because a
// Compartment LCD is addressed over ADB and carries an APK step that an
// Intercom does not.
//
// The switch and port areas belong to the screen itself (they redraw it on
// every click) and are handed in rather than imported, the same way
// ./panel.js takes its handlers. That keeps the arrow pointing one way:
// index.js knows about this card, this card does not know about index.js.

import { el } from '../../core/dom.js';
import { api } from '../../core/api.js';
import { showError } from '../../components/toast.js';
import { value } from '../../core/format.js';
import { local, redraw } from './state.js';
import { apkFields } from './apk.js';
import { isCompartmentPlan, softwareRows } from './software.js';
import { maskField, validateRun } from './validation.js';
import { t } from '../../core/i18n.js';


export function optionToggle(pressed, label, title, onToggle, disabled = false) {
  return el('button', {
    type: 'button', class: 'checkbox', 'aria-pressed': String(pressed),
    title: title || null, disabled,
    onclick: () => {
      if (disabled) return;
      onToggle();
      redraw();
    },
  }, [
    el('span', { class: 'box', 'aria-hidden': 'true' }),
    el('span', { text: label }),
  ]);
}
export function lcdAddressingArea(data, check, showActionState) {
  const { plan } = data;
  const sources = softwareRows(plan)
    .map(row => row.sourceIp || row.factoryIp || '')
    .filter(Boolean);
  const sourceRange = !sources.length ? '—'
    : sources.length === 1 ? sources[0]
    : `${sources[0]} – ${sources[sources.length - 1]}`;

  return el('fieldset', { class: 'setting-section ip-lcd-settings' }, [
    el('legend', { class: 'visually-hidden', text: t('ip.lcdAddressing') }),
    el('div', { class: 'ip-sub-head' }, [
      el('span', { class: 'label', text: t('ip.lcdAddressing') }),
    ]),
    el('div', { class: 'ip-lcd-source' }, [
      el('div', { class: 'row' }, [
        el('span', { text: t('ip.lcdSourceRange') }),
        el('b', { class: 'mono', text: sourceRange }),
      ]),
    ]),
    ...maskField(data, check, showActionState),
    optionToggle(
      local.installApk, t('ip.installApkBeforeAssignment'), '',
      () => { local.installApk = !local.installApk; },
      !(plan.software && plan.software.supported)),
    ...(local.installApk ? [apkFields(plan, check)] : []),
  ]);
}
// Factory IP: the address the devices come out of the box on (in the field
// they all show at the same address — five devices at 10.1.1.12 in arp-scan).
// Search network: the addresses to scan for devices configured earlier, i.e.
// not on the factory address.
// The two fields behind "install software before assigning".
//
// The file is chosen in the OPERATING SYSTEM'S dialog and stays on the server;
// the browser never sees or sends a path. Only its name comes back, which is
// all the screen has to show. Same rule as the job log files.
export function preflashFields(plan) {
  const file = (plan && plan.preflashFile) || { name: '' };
  return [
    el('div', { class: 'setting-row' }, [
      el('span', { class: 'label', text: t('ip.preflashFile') }),
      el('span', { class: 'ip-preflash-file' }, [
        el('span', {
          class: file.name ? 'mono' : 'text-dim',
          text: file.name || t('ip.preflashNoFile'),
        }),
        el('button', {
          type: 'button', class: 'btn btn-small',
          text: t('ip.preflashPick'),
          onclick: async () => {
            try {
              const answer = await api.ipPreflashFile();
              if (answer.cancelled) return;
              plan.preflashFile = answer.preflashFile;
              redraw();
            } catch (e) { showError(e.message); }
          },
        }),
        file.name && el('button', {
          type: 'button', class: 'btn btn-small',
          text: t('net.releaseOne'),
          onclick: async () => {
            try {
              const answer = await api.ipPreflashFile(true);
              plan.preflashFile = answer.preflashFile;
              redraw();
            } catch (e) { showError(e.message); }
          },
        }),
      ]),
    ]),
  ];
}
export function addressingArea(data, check, showActionState) {
  const { plan } = data;
  if (isCompartmentPlan(plan)) {
    return lcdAddressingArea(data, check, showActionState);
  }

  const factoryWarning = el('p', {
    id: 'ip-factory-error', class: 'ip-field-error', role: 'alert',
    text: check.factoryError, hidden: !check.factoryError,
  });
  // `ip-medium-field`, the same as the mask below it: two boxes on
  // consecutive rows, both holding a dotted quad, and a bare `.field` is
  // 100% wide while the mask is 148px. They were visibly different lengths
  // for no reason a reader could find.
  const factoryInput = el('input', {
    id: 'ip-factory', class: 'field ip-medium-field', value: check.factoryIp,
    autocomplete: 'off', spellcheck: 'false', inputmode: 'numeric',
    'aria-invalid': String(!!check.factoryError),
    'aria-describedby': 'ip-factory-error',
    oninput: (e) => {
      local.factoryIp = e.target.value.trim();
      const result = validateRun(data);
      showFieldWarning(e.target, factoryWarning, result.factoryError);
      showActionState(result);
    },
  });

  const searchWarning = el('p', {
    id: 'ip-search-error', class: 'ip-field-error', role: 'alert',
    text: check.searchError, hidden: !check.searchError,
  });
  const searchField = (key, id, label, fallback) => el('label', {
    class: 'setting-row', for: id,
  }, [
    el('span', { class: 'label', text: label }),
    el('input', {
      id, class: 'field ip-medium-field',
      value: local[key] ?? fallback ?? '',
      autocomplete: 'off', spellcheck: 'false',
      'aria-describedby': 'ip-search-error',
      oninput: (e) => {
        local[key] = e.target.value.trim();
        const result = validateRun(data);
        showFieldWarning(e.target, searchWarning, result.searchError);
        showActionState(result);
      },
    }),
  ]);

  return el('fieldset', { class: 'setting-section' }, [
    el('legend', { class: 'visually-hidden', text: t('ip.addressing') }),
    el('div', { class: 'ip-sub-head' }, [
      el('span', { class: 'label', text: t('ip.addressing') }),
    ]),
    el('label', { class: 'setting-row', for: 'ip-factory' }, [
      el('span', { class: 'label', text: t('ip.factoryIpAddress') }),
      factoryInput,
    ]),
    factoryWarning,
    ...maskField(data, check, showActionState),
    optionToggle(local.searchOpen, t('ip.searchIfNotFactory'), '',
                 () => { local.searchOpen = !local.searchOpen; }),
    // Flash before assigning. Old intercoms report their version and identity
    // wrongly, and the run is the only moment one of them is reachable alone
    // and still on the factory address.
    optionToggle(local.preflash, t('ip.preflash'), '',
                 () => { local.preflash = !local.preflash; }),
    ...(local.preflash ? preflashFields(plan) : []),
    ...(local.searchOpen ? [
      searchField('searchNetwork', 'ip-search-network',
        t('ip.searchNetwork'), plan.searchNetwork),
      searchField('searchNetmask', 'ip-search-mask',
        t('ip.searchNetmask'), plan.searchNetmask),
      // An explicit range: when the project mask is wide (/8 in the top bar)
      // opening the network means millions of addresses. With a range given,
      // the network/mask pair above is not used.
      searchField('searchFirst', 'ip-search-first', t('ip.rangeStart')),
      searchField('searchLast', 'ip-search-last', t('ip.rangeEnd')),
      searchWarning,
    ] : []),
  ]);
}
export function settingsCard(data, check, header, areas) {
  const { plan } = data;
  return el('details', {
    class: 'card corner ip-settings-card ip-collapsible',
    open: local.openSections.scope,
    ontoggle: (e) => { local.openSections.scope = e.currentTarget.open; },
  }, [
    el('summary', { class: 'ip-card-head ip-collapsible-summary' }, [
      el('h3', { text: t('ip.ipSettings') }),
      header.summaryBadge,
    ]),
    areas.switchArea(plan),
    areas.portArea(data, check, header.showActionState),
    addressingArea(data, check, header.showActionState),

    // ── summary: what happens on which switch ──
    // One line, and it is the one thing the form above does not already
    // state in a box of its own. The mask used to be repeated here, a
    // hundred pixels under the field holding the same value — a summary that
    // reads back the box directly above it is not a summary.
    el('div', { class: 'setting-summary' }, [
      el('div', { class: 'row' }, [
        el('span', { text: t('ip.target') }),
        el('b', {
          text: t('ip.targetSummary', { switch: value(plan.switch),
                                        count: plan.targetCount }),
        }),
      ]),
    ]),
    header.actionBar,
  ]);
}
