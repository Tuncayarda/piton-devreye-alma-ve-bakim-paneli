// Diagnostics: the address map and the "return to the factory address" test
// flow.
//
// "Which device is on which address" is the most asked question in the field,
// and until now it could only be answered with outside tools (arp-scan) and
// only at MAC level. Because the device reports its own extension, the panel
// can answer it exactly: "the device at 10.1.1.13 is actually port 22's".

import { el } from '../../core/dom.js';
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
        class: map.arpFlush ? 'info' : 'warning', style: 'margin-top:10px',
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
      el('p', {
        class: 'info', style: 'margin-top:10px',
        text: t('ipmap.lcdFactoryResetHow'),
      }),
      el('p', {
        class: 'warning', style: 'margin-top:10px',
        text: t('ipmap.lcdFactoryResetWarning'),
      }),
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
        class: 'info', style: 'margin-top:10px',
        text: t('ipmap.factoryResetSourceSet', { set: sourceSet }),
      }),
      el('p', {
        class: 'info', style: 'margin-top:10px',
        text: t('ipmap.thisTestToolPreparesThe'),
      }),
      // The only reliable way to reach devices sharing an address in turn is
      // flushing the ARP cache. Without the privilege the operation still
      // runs but waits for the entry to turn over on its own and the result
      // may be incomplete; the user must know before pressing the button.
      plan.arpFlush === false
        ? el('p', {
            class: 'warning', style: 'margin-top:10px',
            text: t('ipmap.theArpCacheCannotBe'),
          })
        : null,
      // The factory address is not resolved per train set (it is always
      // 10.1.1.12). If the computer is on another network the devices become
      // invisible after this write and the run cannot find them — and undoing
      // it also requires reaching the device, so it must be said first.
      el('p', {
        class: 'warning', style: 'margin-top:10px',
        text: t('ipmap.factoryWarning', { factory: factoryIp }),
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
