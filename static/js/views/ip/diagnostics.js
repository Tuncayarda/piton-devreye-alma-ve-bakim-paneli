// Diagnostics: the address map and the "return to the factory address" test
// flow.
//
// "Which device is on which address" is the most asked question in the field,
// and until now it could only be answered with outside tools (arp-scan) and
// only at MAC level. Because the device reports its own extension, the panel
// can answer it exactly: "the device at 10.1.1.13 is actually port 22's".

import { el, showFieldWarning } from '../../core/dom.js';
import { dataTable } from '../../components/table.js';
import { api } from '../../core/api.js';
import { state, patch } from '../../core/store.js';
import * as dialog from '../../components/dialog.js';
import { showError, showSuccess, notify } from '../../components/toast.js';
import { local, currentTarget, targetLabel } from './state.js';
import { t } from '../../core/i18n.js';

// Keys, not text: this table is built when the module loads, before the
// catalogue has arrived, so the words are looked up at draw time.
const MAP_STATE = {
  empty: ['text-dim', 'ipmap.stateEmpty'],
  expected: ['ok', 'ipmap.stateExpected'],
  foreign: ['auth', 'ipmap.stateForeign'],
  conflict: ['failed', 'ipmap.stateConflict'],
  unknown: ['auth', 'ipmap.stateUnknown'],
};

const MAP_COLUMNS = '120px 1fr 1fr 90px';

function mapRow(row) {
  const [tone, labelKey] = MAP_STATE[row.state] || ['text-dim', ''];
  const label = labelKey ? t(labelKey) : row.state;
  const who = row.found.length
    ? row.found.map(entry => (entry.port
      ? t('ipmap.devicePort', {
        name: entry.name || entry.extension, port: entry.port,
      })
      : t('ipmap.extensionOnly', { extension: entry.extension || '?' })))
      .join(' + ')
    : '—';
  const expected = row.isFactory
    ? t('ipmap.factoryAddress')
    : (row.expectedPort
      ? t('ipmap.devicePort', {
        name: row.expectedName, port: row.expectedPort,
      })
      : '—');
  return el('div', {
    class: 'table-row', style: `--table-columns:${MAP_COLUMNS}`,
  }, [
    el('span', { class: 'mono', text: row.ip }),
    el('span', { class: 'text-dim', text: expected }),
    el('span', { class: row.found.length ? '' : 'text-dim', text: who }),
    el('span', {}, [el('span', { class: `badge ${tone}`, text: label })]),
  ]);
}

export async function showAddressMap(factoryIp) {
  const data = state.ipState;
  const plan = data && data.plan;
  if (!plan) return;
  const body = el('div', {}, [
    el('p', { class: 'description', text: t('ipmap.probingTheAddresses') }),
  ]);
  dialog.show({
    title: t('ipmap.addressMap'),
    content: body,
    actions: [
      el('button', {
        type: 'button', class: 'btn', text: t('detail.close'),
        onclick: () => dialog.close(),
      }),
    ],
  });
  try {
    const map = await api.ipAddressMap(
      state.setNo, plan.switchId,
      (plan.groups || [])[0] || 'Intercom', factoryIp);
    const counts = map.counts || {};
    body.replaceChildren(
      el('p', { class: 'description' }, [
        t('ipmap.counts', {
          devices: counts.devices || 0, expected: counts.expected || 0,
          foreign: counts.foreign || 0, conflict: counts.conflict || 0,
        }),
      ]),
      dataTable({
        template: MAP_COLUMNS, minWidth: 560, label: t('ipmap.addressMap'),
        columns: ['col.address', 'col.whoseInDeviceMap', 'col.whoIsThereNow',
                  'col.state'].map(key => (key ? t(key) : '')),
        rows: (map.rows || []).map(mapRow),
        empty: t('ipmap.stateEmpty'),
      }),
      // A collision does not show in a single probe; how many passes were
      // made and whether the ARP flush worked decide how trustworthy the
      // result is.
      el('p', {
        class: `${map.arpFlush ? 'info' : 'warning'} mt-3`,
        text: t(map.arpFlush ? 'ipmap.arpFlushed'
          : 'ipmap.arpNotFlushed'),
      }),
    );
  } catch (e) {
    body.replaceChildren(el('p', { class: 'warning', text: e.message }));
  }
}

// The search area, shared by the run and the factory-reset flow.
export function searchOptions(plan) {
  return {
    searchNetwork: local.searchOpen
      ? (local.searchNetwork ?? plan.searchNetwork) : '',
    searchNetmask: local.searchOpen
      ? (local.searchNetmask ?? plan.searchNetmask) : '',
    searchFirst: local.searchOpen ? (local.searchFirst || '') : '',
    searchLast: local.searchOpen ? (local.searchLast || '') : '',
  };
}

// ── test flow: put the displays back on their set-1 addresses ───────────
// Not the same operation as the Intercom one above and deliberately not
// dressed as it. Nothing is gathered on a shared address: every Compartment
// LCD keeps its own host octet and goes back to the set-1 form of it
// (10.1.1.40, .41, ...), which is where a display sits before it knows which
// train it belongs to. The server runs the ordinary Android flow with the two
// sets the other way round.
export function confirmLcdFactoryReset(plan, portText, sourceSetNo) {
  const sourceSet = Number(sourceSetNo);
  if (!Number.isInteger(sourceSet) || sourceSet < 1 || sourceSet > 254) {
    throw new Error(t('topbar.setOutOfRange', { min: 1, max: 254 }));
  }
  dialog.show({
    title: t('ipmap.resetToSetOne'),
    content: el('div', {}, [
      el('p', { class: 'description' }, [
        t('ipmap.lcdFactoryResetIntro', { ports: portText, set: sourceSet }),
      ]),
    ]),
    actions: [
      el('button', {
        type: 'button', class: 'btn', text: t('locked.cancel'),
        onclick: () => dialog.close(),
      }),
      el('button', {
        type: 'button', class: 'btn btn-danger',
        text: t('ipmap.resetToSetOne'),
        onclick: async () => {
          dialog.close();
          try {
            const job = await api.ipFactoryReset({
              set: state.setNo,
              switch: plan.switchId,
              groups: plan.groups || [],
              ports: portText,
              sourceSet: String(sourceSet),
            });
            patch({ queueOpen: true, openJob: job.id });
            if (job.new === false) {
              notify(t('ipmap.thereIsAlreadyAJob'));
            } else {
              showSuccess(t('ipmap.theFactoryResetJobWas'));
            }
          } catch (e) {
            showError(e.message);
          }
        },
      }),
    ],
  });
}


// ── test flow: gather the devices on the factory address ────────────────
// Sets up the starting state needed to try the run from scratch. Only an "set
// your IP to this address" request goes to the devices; PoE and the switch are
// untouched. Because they will all end up on the SAME address, confirmation is
// asked.
export async function confirmFactoryReset(factoryIp, resetSetNo = state.setNo) {
  const data = state.ipState;
  const currentPlan = data && data.plan;
  if (!currentPlan) return;
  const sourceSet = Number(resetSetNo);
  if (!Number.isInteger(sourceSet) || sourceSet < 1 || sourceSet > 254) {
    throw new Error(t('topbar.setOutOfRange', { min: 1, max: 254 }));
  }

  // A device brought from another set answers on that set's DeviceMap
  // addresses. Resolve a fresh plan for the source set instead of combining
  // its number with the current set's already-resolved addresses.
  const external = sourceSet !== state.setNo;
  const plan = external ? await api.ipPlan(
    sourceSet,
    (currentPlan.groups || []).join(','),
    local.portText ?? currentPlan.portText,
    currentPlan.switchId,
  ) : currentPlan;
  const targets = plan.rows.filter(row => row.actionable);
  if (!targets.length) {
    showError(t('ipmap.noTargetOnPorts',
                { target: targetLabel(currentTarget()) }));
    return;
  }
  dialog.show({
    title: t('ipmap.resetToTheFactoryIp'),
    content: el('div', {}, [
      el('p', { class: 'description' }, [
        t('ipmap.factoryResetIntro', {
          count: targets.length, factory: factoryIp,
        }),
      ]),
      el('p', {
        class: 'info mt-3',
        text: t('ipmap.factoryResetSourceSet', { set: sourceSet }),
      }),
    ]),
    actions: [
      el('button', {
        type: 'button', class: 'btn', text: t('locked.cancel'),
        onclick: () => dialog.close(),
      }),
      el('button', {
        type: 'button', class: 'btn btn-danger',
        text: t('ipmap.resetToTheFactoryIp'),
        onclick: async () => {
          dialog.close();
          try {
            const job = await api.ipFactoryReset({
              set: sourceSet,
              switch: plan.switchId,
              groups: plan.groups || [],
              ports: plan.portText,
              factoryIp,
              // The device may not be at its DeviceMap address; as in the
              // run, a place to search can be given here too.
              // For an external set the freshly resolved plan supplies the
              // default network; explicit range fields still take priority.
              ...searchOptions(plan),
            });
            patch({ queueOpen: true, openJob: job.id });
            if (job.new === false) {
              notify(t('ipmap.thereIsAlreadyAJob'));
            } else {
              showSuccess(t('ipmap.theFactoryResetJobWas'));
            }
          } catch (e) {
            showError(e.message);
          }
        },
      }),
    ],
  });
}


// ── returning devices to a known address ──────────────────────────────
// The cards for the two reset flows. They sit beside the confirmations
// they open (above): a reset is a diagnostic move — put the devices back
// where a fresh run expects to find them — not a step of commissioning.
// Returning devices to the factory address is a separate, destructive
// maintenance action. It stays visible on the IP page, but outside the primary
// assignment card so it cannot be mistaken for another run option.
export function factoryResetSelection() {
  if (local.factoryResetScope !== 'external') {
    return { setNo: state.setNo, error: '' };
  }
  const raw = String(local.factoryResetSet || '').trim();
  const setNo = Number(raw);
  const error = Number.isInteger(setNo) && setNo >= 1 && setNo <= 254
    ? '' : t('topbar.setOutOfRange', { min: 1, max: 254 });
  return { setNo, error };
}
export function factoryResetCard(data, check) {
  const isExternal = local.factoryResetScope === 'external';
  const initial = factoryResetSelection();
  const warning = el('p', {
    id: 'ip-factory-reset-set-error', class: 'ip-field-error', role: 'alert',
    text: initial.error, hidden: !initial.error,
  });
  let resetButton = null;

  const externalInput = isExternal ? el('input', {
    id: 'ip-factory-reset-set', class: 'field ip-reset-set-field',
    type: 'number', min: '1', max: '254', step: '1',
    value: local.factoryResetSet,
    inputmode: 'numeric',
    autocomplete: 'off',
    'aria-invalid': String(!!initial.error),
    'aria-describedby': 'ip-factory-reset-set-error',
    oninput: (event) => {
      local.factoryResetSet = event.target.value.trim();
      const choice = factoryResetSelection();
      showFieldWarning(event.target, warning, choice.error);
      if (resetButton) {
        resetButton.disabled = !!choice.error || !!check.factoryError;
      }
    },
  }) : null;

  const scopeOption = (scope, label) => el('label', {
    class: 'ip-reset-scope-option',
    dataset: { active: local.factoryResetScope === scope ? '1' : '0' },
  }, [
    el('input', {
      type: 'radio', name: 'ip-factory-reset-scope', value: scope,
      checked: local.factoryResetScope === scope,
      onchange: () => {
        local.factoryResetScope = scope;
        patch({ ipState: { ...data } });
      },
    }),
    el('span', { text: label }),
  ]);

  resetButton = el('button', {
    type: 'button', class: 'btn btn-danger',
    text: t('ipmap.resetToTheFactoryIp'),
    disabled: !!initial.error || !!check.factoryError,
    onclick: async (event) => {
      const choice = factoryResetSelection();
      if (choice.error) { showError(choice.error); return; }
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = t('ipmap.preparingFactoryReset');
      try {
        await confirmFactoryReset(check.factoryIp, choice.setNo);
      } catch (error) {
        showError(error.message);
      } finally {
        if (button.isConnected) {
          button.disabled = !!factoryResetSelection().error
            || !!check.factoryError;
          button.textContent = t('ipmap.resetToTheFactoryIp');
        }
      }
    },
  });

  return el('section', { class: 'card corner ip-factory-reset-card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('ipmap.factoryResetSection') }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'mono ip-factory-reset-address',
        text: check.factoryIp }),
    ]),
    el('fieldset', { class: 'ip-reset-scope' }, [
      el('legend', { class: 'label', text: t('ipmap.devicesSet') }),
      el('div', { class: 'ip-reset-scope-options' }, [
        scopeOption('current', t('ipmap.currentSet', { set: state.setNo })),
        scopeOption('external', t('ipmap.externalSet')),
      ]),
      isExternal ? el('label', {
        class: 'ip-reset-external-set', for: 'ip-factory-reset-set',
      }, [
        el('span', { class: 'label', text: t('ipmap.externalSetNumber') }),
        externalInput,
      ]) : null,
      isExternal ? warning : null,
    ]),
    el('div', { class: 'ip-factory-reset-actions' }, [
      resetButton,
    ]),
  ]);
}
// Putting the displays back where they started. Its own card and its own
// wording rather than a mode of the Intercom one: "factory" means something
// different here. No display is gathered onto a shared address — each keeps
// its own host octet and goes back to the set-1 form of it.
export function lcdFactoryResetCard(data, check) {
  const { plan } = data;
  const isExternal = local.factoryResetScope === 'external';
  const initial = factoryResetSelection();
  const warning = el('p', {
    id: 'ip-lcd-reset-set-error', class: 'ip-field-error', role: 'alert',
    text: initial.error, hidden: !initial.error,
  });
  let resetButton = null;

  const scopeOption = (scope, label) => el('label', {
    class: 'ip-reset-scope-option',
    dataset: { active: local.factoryResetScope === scope ? '1' : '0' },
  }, [
    el('input', {
      type: 'radio', name: 'ip-lcd-reset-scope', value: scope,
      checked: local.factoryResetScope === scope,
      onchange: () => {
        local.factoryResetScope = scope;
        patch({ ipState: { ...data } });
      },
    }),
    el('span', { text: label }),
  ]);

  resetButton = el('button', {
    type: 'button', class: 'btn btn-danger',
    text: t('ipmap.resetToSetOne'),
    disabled: !!initial.error || !!check.portError,
    onclick: (event) => {
      const choice = factoryResetSelection();
      if (choice.error) { showError(choice.error); return; }
      try {
        confirmLcdFactoryReset(plan, check.portText, choice.setNo);
      } catch (error) {
        showError(error.message);
      }
      event.currentTarget.blur();
    },
  });

  return el('section', { class: 'card corner ip-factory-reset-card' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('ipmap.lcdFactoryResetSection') }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'mono ip-factory-reset-address',
        text: t('ipmap.setOneAddresses') }),
    ]),
    el('fieldset', { class: 'ip-reset-scope' }, [
      el('legend', { class: 'label', text: t('ipmap.devicesSet') }),
      el('div', { class: 'ip-reset-scope-options' }, [
        scopeOption('current', t('ipmap.currentSet', { set: state.setNo })),
        scopeOption('external', t('ipmap.externalSet')),
      ]),
      isExternal ? el('label', {
        class: 'ip-reset-external-set', for: 'ip-lcd-reset-set',
      }, [
        el('span', { class: 'label', text: t('ipmap.externalSetNumber') }),
        el('input', {
          id: 'ip-lcd-reset-set', class: 'field ip-reset-set-field',
          type: 'number', min: '1', max: '254', step: '1',
          value: local.factoryResetSet,
          inputmode: 'numeric',
          autocomplete: 'off',
          'aria-invalid': String(!!initial.error),
          'aria-describedby': 'ip-lcd-reset-set-error',
          oninput: (event) => {
            local.factoryResetSet = event.target.value.trim();
            const choice = factoryResetSelection();
            showFieldWarning(event.target, warning, choice.error);
            if (resetButton) {
              resetButton.disabled = !!choice.error || !!check.portError;
            }
          },
        }),
      ]) : null,
      isExternal ? warning : null,
    ]),
    el('div', { class: 'ip-factory-reset-actions' }, [
      el('p', {
        text: t('ipmap.lcdFactoryResetPorts', { ports: check.portText }),
      }),
      resetButton,
    ]),
  ]);
}
