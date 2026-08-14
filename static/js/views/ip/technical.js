// The "Technical details" disclosure on the IP screen.
//
// Everything here answers "why is the plan what it is": where the targets came
// from, which switch the run goes over, which port the computer is on and
// which ports are kept out of it. Collapsed by default — a field user starting
// a run does not need any of it, and whoever is diagnosing a failure needs all
// of it.
//
// The two test tools live here as well, deliberately far from the start
// button: one only reads, the other writes to devices.

import { el } from '../../core/dom.js';
import { value } from '../../core/format.js';
import { currentTarget, local, protectedPortsFor } from './state.js';
import { confirmFactoryReset, showAddressMap } from './diagnostics.js';
import { t } from '../../core/i18n.js';

function row(label, valueNode, className = '') {
  return el('div', { class: className ? `row ${className}` : 'row' }, [
    el('span', { text: label }),
    valueNode,
  ]);
}

function testTools(factoryIp) {
  return el('div', { class: 'ip-test-area' }, [
    el('span', { class: 'eyebrow', text: t('iptech.testTool') }),
    // Diagnosis comes first: the answer to "what happened" must be
    // obtainable before pressing a button that writes to devices.
    el('button', {
      type: 'button', class: 'btn btn-small',
      text: t('ipmap.addressMap'),
      title: t('iptech.whichDeviceIsOnEach'),
      onclick: () => showAddressMap(factoryIp),
    }),
    el('button', {
      type: 'button', class: 'btn btn-small btn-danger',
      text: t('ipmap.resetToTheFactoryIp'),
      title: t('iptech.factoryResetTitle', { factory: factoryIp }),
      onclick: () => confirmFactoryReset(factoryIp),
    }),
  ]);
}

function switchRows(plan) {
  return (plan.switches || []).map(entry => row(entry.name, el('b', {
    class: entry.id === plan.switchId ? 'accent-text' : 'text-dim',
    text: entry.id === plan.switchId
      ? plan.portText
      : (entry.groupDevices
        ? `${entry.groupDevices} device(s) · not selected`
        : `no ${currentTarget().label}`),
  })));
}

export function technicalCard(plan, check, computer) {
  return el('details', {
    class: 'card corner ip-technical ip-collapsible',
    open: local.openSections.technical,
    ontoggle: (e) => { local.openSections.technical = e.currentTarget.open; },
  }, [
    el('summary', { class: 'ip-technical-summary' }, [
      el('span', { text: t('detail.technicalDetails') }),
      el('span', {
        class: 'text-dim',
        text: t('iptech.planSourceArpAndProtected'),
      }),
    ]),
    el('div', { class: 'ip-technical-body' }, [
      row('Plan source', el('b', {
        title: t('iptech.targetIpsAndPortsCome'),
        text: t('iptech.projectDefaultDevicemap'),
      })),
      testTools(check.factoryIp),
      // Whether the ARP cache can be flushed is no longer written on screen:
      // the application already opens elevated (see app.py) and the wording
      // of the privilege warning differed on every OS. The panel does not
      // speak per operating system.
      row('Switch IP address', el('b', { text: value(plan.switchIp) })),
      ...switchRows(plan),
      row('Computer connection', el('b', {
        class: computer.ok ? '' : 'text-dim',
        title: computer.hint,
        text: computer.text,
      })),
      ...protectedPortsFor(plan).map(([number, reason]) => row(
        `Protected port ${number}`,
        el('b', { class: 'text-dim', text: reason }),
        'protected')),
    ]),
  ]);
}
