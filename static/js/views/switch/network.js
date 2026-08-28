// The switch's own management address, and the three operations that end a
// session with it.
//
// ALL FOUR NEED CONFIRMING and for different reasons, so each says what it
// will actually cost:
//
//   · saving the configuration is the only one that is not destructive, and
//     it is the one everything else depends on — without it every change
//     above is gone at the next power cut;
//   · changing the address moves the switch out from under this screen;
//   · a restart drops every link on it for about a minute;
//   · a factory reset is not undoable from here at all, so it asks for the
//     address to be typed back (the server checks that too).

import { el } from '../../core/dom.js';
import { confirmWrite } from '../../components/confirm.js';
import * as dialog from '../../components/dialog.js';
import { t } from '../../core/i18n.js';
import { local } from './state.js';

const PREFIXES = ['8', '16', '24'];

// The switch names its own addressing method, in its own words. Translated
// where we know the word and passed through where we do not: models differ,
// and turning an unrecognised method into a blank would hide the one fact
// the row exists to state.
const METHOD_KEY = {
  manual: 'switch.networkMethodManual',
  static: 'switch.networkMethodManual',
  dhcp: 'switch.networkMethodDhcp',
};

function methodText(method) {
  const key = METHOD_KEY[String(method || '').trim().toLowerCase()];
  return key ? t(key) : (method || '—');
}

export function networkCard(actions) {
  const info = local.info;
  if (!info) return null;
  const network = info.network || {};

  return el('section', { class: 'card corner switch-network' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('switch.networkTitle') }),
    ]),
    el('p', { class: 'description', text: t('switch.networkNote') }),
    el('div', { class: 'switch-network-current' }, [
      field(t('switch.networkCurrentAddress'),
            `${network.address || '—'}/${network.prefix || '—'}`),
      field(t('switch.networkSubnetMask'), network.subnetMask || '—'),
      field(t('switch.networkMtu'), network.mtu || '—'),
      field(t('switch.networkMethod'), methodText(network.method)),
    ]),
    addressForm(actions),
    el('div', { class: 'switch-lifecycle' }, [
      el('button', {
        type: 'button', class: 'btn btn-primary',
        text: t('switch.buttonSaveConfiguration'),
        onclick: () => confirmSave(actions),
      }),
      el('button', {
        type: 'button', class: 'btn',
        text: t('switch.buttonReboot'),
        onclick: () => confirmReboot(actions),
      }),
      el('button', {
        type: 'button', class: 'btn btn-danger',
        text: t('switch.buttonFactoryReset'),
        onclick: () => confirmFactoryReset(actions),
      }),
    ]),
  ]);
}

function field(label, value) {
  return el('div', { class: 'switch-field' }, [
    el('span', { class: 'eyebrow', text: label }),
    el('b', { class: 'mono', text: String(value) }),
  ]);
}

function addressForm(actions) {
  const address = el('input', {
    class: 'field', type: 'text', autocomplete: 'off', spellcheck: 'false',
    inputmode: 'decimal', 'aria-label': t('switch.networkNewAddress'),
    placeholder: '10.1.1.2', value: local.form.address,
    oninput: (event) => { local.form.address = event.target.value; },
  });
  const prefix = el('select', {
    class: 'field', 'aria-label': t('switch.networkPrefix'),
    onchange: (event) => { local.form.prefix = event.target.value; },
  }, PREFIXES.map(value => el('option', {
    value, selected: value === local.form.prefix, text: `/${value}`,
  })));
  const mtu = el('input', {
    class: 'field', type: 'text', autocomplete: 'off', inputmode: 'numeric',
    'aria-label': t('switch.networkMtu'), placeholder: '1500',
    value: local.form.mtu,
    oninput: (event) => { local.form.mtu = event.target.value; },
  });

  return el('form', {
    class: 'switch-network-form',
    onsubmit: (event) => {
      event.preventDefault();
      address.blur();
      mtu.blur();
      confirmAddress(actions, {
        address: address.value, prefix: prefix.value, mtu: mtu.value,
      });
    },
  }, [
    el('div', { class: 'switch-network-fields' }, [address, prefix, mtu]),
    el('button', {
      type: 'submit', class: 'btn',
      text: t('switch.buttonApplyAddress'),
    }),
  ]);
}

function confirmAddress(actions, values) {
  confirmWrite({
    title: t('switch.confirmAddressTitle'),
    lead: t('switch.confirmAddressLead', {
      ip: local.info.ip, address: values.address, prefix: values.prefix,
    }),
    notes: [{ text: t('switch.confirmAddressNote'), tone: 'warning' }],
    items: [{ name: local.info.ip,
              detail: `${values.address}/${values.prefix}` }],
    confirmLabel: t('switch.buttonApplyAddress'),
    run: () => actions.setNetwork(values),
  });
}

function confirmSave(actions) {
  confirmWrite({
    title: t('switch.confirmSaveTitle'),
    lead: t('switch.confirmSaveLead', { ip: local.info.ip }),
    notes: [{ text: t('switch.confirmSaveNote'), tone: 'info' }],
    items: [{ name: local.info.ip, detail: local.info.model || '' }],
    confirmLabel: t('switch.buttonSaveConfiguration'),
    run: () => actions.saveConfiguration(),
  });
}

function confirmReboot(actions) {
  confirmWrite({
    title: t('switch.confirmRebootTitle'),
    lead: t('switch.confirmRebootLead', { ip: local.info.ip }),
    notes: [{ text: t('switch.confirmRebootNote'), tone: 'warning' }],
    items: [{ name: local.info.ip, detail: local.info.model || '' }],
    danger: true,
    confirmLabel: t('switch.buttonReboot'),
    run: () => actions.reboot(),
  });
}

// The one that types the address back. `confirmWrite` cannot do this — its
// question is yes or no — so this builds its own dialog, and the button stays
// disabled until what was typed matches exactly.
function confirmFactoryReset(actions) {
  const ip = local.info.ip;
  const confirmButton = el('button', {
    type: 'button', class: 'btn btn-danger', disabled: true,
    text: t('switch.buttonFactoryReset'),
    onclick: () => { dialog.close(); actions.factoryReset(typed.value); },
  });
  const typed = el('input', {
    class: 'field', type: 'text', autocomplete: 'off', spellcheck: 'false',
    'aria-label': t('switch.confirmResetField'),
    placeholder: ip,
    oninput: (event) => {
      confirmButton.disabled = event.target.value.trim() !== ip;
    },
  });

  dialog.show({
    title: t('switch.confirmResetTitle'),
    width: '460px',
    content: el('div', {}, [
      el('p', { class: 'description',
                text: t('switch.confirmResetLead', { ip }) }),
      el('p', { class: 'warning', text: t('switch.confirmResetNote') }),
      el('p', { class: 'description',
                text: t('switch.confirmResetPrompt', { ip }) }),
      typed,
    ]),
    actions: [
      el('button', {
        type: 'button', class: 'btn', text: t('switch.cancel'),
        onclick: () => dialog.close(),
      }),
      confirmButton,
    ],
  });
}
