// The assignment plan at the bottom of the IP screen.
//
// One row per port on the active switch: which device sits there, the address
// it comes from and the address it will be given. A row outside the target
// group stays in the table rather than being hidden — "why is this port not
// being touched?" is a question the table should answer, not raise.

import { el } from '../../core/dom.js';
import { dataTable } from '../../components/table.js';
import { NONE } from '../../core/format.js';
import { local } from './state.js';
import {
  deviceMapName, perDeviceSource, sourceAddress, usesPhysicalPortDiscovery,
} from './software.js';
import { t } from '../../core/i18n.js';

const COLUMNS = '68px minmax(150px,1.25fr) minmax(104px,.85fr) 112px 112px '
  + 'minmax(150px,1fr)';

const HEADINGS = ['col.port', 'col.targetDevice', 'col.group',
  'col.factoryIp', 'col.ipToAssign', 'col.state'];

export function planRowStateKey(plan, row) {
  if (!row.actionable) return 'ipplan.outsideTargetGroup';
  if (usesPhysicalPortDiscovery(plan) && !row.deviceId) {
    return 'ipplan.automaticDeviceMatch';
  }
  return 'ipplan.inThePlan';
}

function planRow(plan, row, factoryIp) {
  return el('div', {
    class: 'table-row ip-plan-row',
    style: `--table-columns:${COLUMNS}`,
    dataset: { actionable: row.actionable ? '1' : '0' },
  }, [
    el('span', { class: 'ip-port-badge', text: `p${row.port}` }),
    el('span', {
      class: 'mono truncate ip-device-name', text: deviceMapName(row) || NONE,
    }),
    el('span', {
      class: 'mono truncate ip-group-name', text: row.group || NONE,
    }),
    // A shared source can be overridden by the Intercom form. Compartment LCD
    // sources are per device and always come from the server's DeviceMap plan.
    el('span', {
      class: 'mono text-mid ip-address',
      text: sourceAddress(plan, row, factoryIp) || NONE,
    }),
    el('span', {
      class: 'mono ip-address ip-target-ip', text: row.targetIp || NONE,
    }),
    el('span', {
      class: row.actionable
        ? 'ip-state-badge included' : 'ip-state-badge excluded',
      text: t(planRowStateKey(plan, row)),
    }),
  ]);
}

export function planTable(plan, check) {
  const { inPlan, outOfPlan, factoryIp } = check;
  const headings = [...HEADINGS];
  if (perDeviceSource(plan)) headings[3] = 'col.sourceIp';
  return el('details', {
    class: 'ip-plan-section ip-collapsible',
    // Opened by default when something falls outside the plan: that is the
    // case the user has to look at.
    open: local.openSections.plan ?? outOfPlan > 0,
    ontoggle: (e) => { local.openSections.plan = e.currentTarget.open; },
  }, [
    el('summary', { class: 'ip-section-head ip-collapsible-summary' }, [
      el('div', { class: 'ip-section-title' }, [
        el('div', {}, [
          el('h3', { text: t('ipplan.assignmentPlan') }),
        ]),
      ]),
      el('div', { class: 'ip-plan-metrics' }, [
        el('span', { text: t('ipplan.includedCount', { count: inPlan }) }),
        outOfPlan
          ? el('span', {
            text: t('ipplan.outOfScopeCount', { count: outOfPlan }),
          })
          : null,
      ]),
    ]),
    dataTable({
      template: COLUMNS, minWidth: 800, wrapClass: 'ip-plan-table',
      label: t('ipplan.assignmentPlan'),
      columns: headings.map(key => t(key)),
      rows: plan.rows.map(row => planRow(plan, row, factoryIp)),
      empty: t('ipplan.noTargetDeviceOnThe'),
    }),
  ]);
}
