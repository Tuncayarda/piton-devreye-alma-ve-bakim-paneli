// The lock menu: devices waiting for a username/password, and the credential
// dialog.
//
// A password is NEVER written to the application store (core/store.js). The
// dialog's input value goes straight into the API call; the moment the reply
// arrives — success or failure — the field is cleared.
//
// The server makes the verification decision: a filled-in form is not enough,
// the device must really return the expected data.

import { el, fill, $ } from '../core/dom.js';
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import { value, typeLabel, methodCode } from '../core/format.js';
import * as dialog from './dialog.js';
import { showSuccess } from './toast.js';
import { t } from '../core/i18n.js';
import { emptyState } from './placeholder.js';

let onAccepted = () => {};

export function onCredentialsAccepted(fn) { onAccepted = fn; }

// Same reasoning as the queue panel: the list is only rebuilt when it changed.
let lastSignature = null;

// Same reasoning as queue.reset(): a language switch changes the words, not
// the data, and an open panel would otherwise keep the old catalogue's rows.
export function reset() {
  lastSignature = null;
}

export function render() {
  const list = $('#locked-list');
  if (!list) return;
  const devices = state.locked || [];

  const badge = $('#locked-count');
  if (badge) {
    badge.textContent = String(devices.length);
    badge.hidden = devices.length === 0;
  }
  const button = $('#locked-btn');
  if (button) button.setAttribute('aria-expanded', String(!!state.lockedOpen));
  $('#locked-panel').hidden = !state.lockedOpen;
  if (!state.lockedOpen) { lastSignature = null; return; }

  const signature = JSON.stringify(devices);
  if (signature === lastSignature) return;
  lastSignature = signature;

  // An empty list used to render as an empty grey box, which is worse than
  // it sounds: the IP screen tells the operator to enter credentials for a
  // switch, they open this panel, and it is blank. This list only holds
  // devices that ANSWERED a scan with "authentication required", while a
  // switch that does not answer at all never appears here.
  if (!devices.length) {
    const box = emptyState(t('locked.noneNeedCredentials'));
    // The panel moves focus here when it opens with nothing in it, so the
    // box has to be able to take it.
    box.tabIndex = -1;
    fill(list, [box]);
    return;
  }

  fill(list, devices.map(device => el('button', {
    type: 'button', class: 'locked-row',
    onclick: () => credentialDialog(device),
  }, [
    el('span', { class: 'name', text: device.name }),
    el('span', { class: 'badge', text: methodCode(device) }),
    el('span', { class: 'sub' }, [
      `${device.ip} · ${typeLabel(device.typeLabel)}`,
      el('br'),
      device.credentialGroup
        ? t('locked.accountGroup', { group: device.credentialGroup })
        : t('locked.ownAccount'),
      el('br'),
      detailOf(device),
    ]),
  ])));
}

// The detail text and the method code come from the read result inside the
// device DTO; the lock list is not fed by a separate endpoint, so it is
// resolved here.
function detailOf(device) {
  return (device.result && device.result.detail) || device.detail || '';
}

// `onDone` is called when the verification succeeds, so the screen that
// opened the dialog can refresh its own data (the IP assignment screen
// re-reads the switch panel). Without it only the general refresh runs.
export function credentialDialog(device, onDone = null) {
  const usernameField = el('input', {
    class: 'field', type: 'text', id: 'credential-username',
    autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false',
    value: '',
  });
  const passwordField = el('input', {
    class: 'field', type: 'password', id: 'credential-password',
    autocomplete: 'new-password',
  });
  const warning = el('p', { class: 'warning', role: 'alert', hidden: true });

  let applyToGroup = false;
  const groupButton = device.credentialGroup ? el('button', {
    type: 'button', class: 'checkbox', 'aria-pressed': 'false',
    onclick: (e) => {
      applyToGroup = !applyToGroup;
      e.currentTarget.setAttribute('aria-pressed', String(applyToGroup));
    },
  }, [
    el('span', { class: 'box', 'aria-hidden': 'true' }),
    el('span', {
      text: t('locked.applyToGroup', { group: device.credentialGroup }),
    }),
  ]) : null;

  const submit = el('button', {
    type: 'submit', class: 'btn btn-primary', text: t('locked.verifyAccess'),
  });

  const form = el('form', {
    onsubmit: async (e) => {
      e.preventDefault();
      warning.hidden = true;
      submit.disabled = true;
      submit.textContent = t('locked.verifying');

      const username = usernameField.value.trim();
      const password = passwordField.value;
      try {
        const reply = await api.tryCredentials(
          state.setNo, device.id, username, password, applyToGroup);
        // Not held in memory even on success.
        passwordField.value = '';
        usernameField.value = '';
        applyState(reply.state);
        dialog.close();
        showSuccess(t(reply.appliedToGroup
          ? 'locked.accessVerifiedGroup' : 'locked.accessVerified',
        { device: device.name }));
        onAccepted();
        if (onDone) onDone();
      } catch (err) {
        // A wrong password does not overwrite the working credential in
        // memory (server side).
        passwordField.value = '';
        warning.textContent = err.message || t('locked.notVerified');
        warning.hidden = false;
        passwordField.focus();
        if (err.body && err.body.state) applyState(err.body.state);
      } finally {
        submit.disabled = false;
        submit.textContent = t('locked.verifyAccess');
      }
    },
  }, [
    el('p', { class: 'description' }, [
      `${device.ip} · ${typeLabel(device.typeLabel)} · ${methodCode(device)}`,
      el('br'),
      value(detailOf(device)),
    ]),
    el('label', { class: 'field-label mb-3' }, [
      el('span', { class: 'label', text: t('locked.username') }),
      usernameField,
    ]),
    el('label', { class: 'field-label' }, [
      el('span', { class: 'label', text: t('locked.password') }),
      passwordField,
    ]),
    groupButton ? el('div', { class: 'mt-4' }, [groupButton]) : null,
    warning,
    el('div', { class: 'actions mt-4' }, [
      el('button', {
        type: 'button', class: 'btn', text: t('locked.cancel'),
        onclick: () => dialog.close(),
      }),
      submit,
    ]),
  ]);

  dialog.show({
    title: t('locked.dialogTitle', { device: device.name }), content: form,
  });
}

// Applies the full state snapshot from the server (the counters update at
// once).
export function applyState(data) {
  if (!data) return;
  patch({
    devices: data.devices || [],
    counts: data.counts || state.counts,
    lastScan: data.lastScan ?? state.lastScan,
    scanRunning: !!data.scanRunning,
    locked: (data.devices || []).filter(
      device => device.result.verification === 'auth_required'),
  });
}

export function toggle() {
  patch({ lockedOpen: !state.lockedOpen, queueOpen: false });
  if (state.lockedOpen) {
    // The empty state is a focus target too, so opening an empty panel still
    // moves the reader somewhere that says something.
    const first = $('#locked-list .locked-row')
      || $('#locked-list .empty-state');
    if (first) first.focus();
  }
}
