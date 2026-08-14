// The device detail drawer (slides in from the right).
//
// Unread fields show "—", fields that do not apply on that device show
// "not applicable on this device". The two are not the same thing.

import { el, fill, focusTrap, $ } from '../core/dom.js';
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import {
  value, stateLabel, verificationLabel, STATE_COLOUR, clockTime, NONE,
  typeLabel,
} from '../core/format.js';
import { credentialDialog } from './locked.js';
import { showError } from './toast.js';
import { t } from '../core/i18n.js';

let release = null;

export function close() {
  if (release) { release(); release = null; }
  fill($('#detail-slot'), []);
  if (state.detailId) patch({ detailId: null });
}

export async function open(deviceId) {
  patch({ detailId: deviceId });
  try {
    const data = await api.device(state.setNo, deviceId);
    render(data);
  } catch (e) {
    showError(e.message);
    patch({ detailId: null });
  }
}

function block(title, source, rows) {
  return el('div', { class: 'detail-block' }, [
    el('div', { class: 'head' }, [
      el('h4', { text: title }),
      el('span', { style: 'flex:1' }),
      el('span', { class: 'label', text: source || '' }),
    ]),
    ...rows.map(([name, raw, colour]) => el('div', { class: 'detail-row' }, [
      el('span', { class: 'name', text: name }),
      el('span', {
        class: 'value',
        style: colour ? `color:var(--${colour})` : null,
        text: value(raw),
      }),
    ])),
  ]);
}

function render(device) {
  const result = device.result || {};
  const fields = result.fields || {};
  const method = device.readMethodInfo || {};
  const colour = STATE_COLOUR[result.state] || null;

  const actions = [
    el('button', {
      type: 'button', class: 'btn btn-primary', text: t('detail.readNow'),
      onclick: async () => {
        try {
          await api.refresh(state.setNo, [device.id]);
          await open(device.id);
        } catch (e) { showError(e.message); }
      },
    }),
  ];
  if (result.verification === 'auth_required') {
    actions.push(el('button', {
      type: 'button', class: 'btn', text: t('detail.enterCredentials'),
      onclick: () => credentialDialog({
        ...device, detail: result.detail,
        credentialGroup: device.credentialGroup,
      }),
    }));
  }
  if (device.hasCredentials) {
    actions.push(el('button', {
      type: 'button', class: 'btn', text: t('detail.deleteCredentials'),
      onclick: async () => {
        try {
          await api.forgetCredentials(state.setNo, device.id);
          await open(device.id);
        } catch (e) { showError(e.message); }
      },
    }));
  }

  // On the Compartment LCD the version is not the Android build id but the
  // panel app's version (dumpsys package … versionName). Without the package
  // name and the update date it is not clear which build came from where.
  const androidRows = device.readMethod === 'adb' ? [
    ['Application', fields.package],
    ['Version code', fields.versionCode],
    ['Target SDK', fields.targetSdk],
    ['Last updated', fields.updatedAt],
  ] : [];

  const summaryBlock = block(
    'Summary', `Project + ${method.code || device.readMethod}`, [
      ['Device name', device.name],
      ['Type / subtype', typeLabel(device.typeLabel)],
      ['Version', fields.version, fields.version ? 'ok' : null],
      ...androidRows,
      ['Model', fields.model],
      ['Device number', fields.serial],
      [t('detail.accessState'), stateLabel(result.state, NONE), colour],
      [t('detail.checkResult'),
        verificationLabel(result.verification, NONE), colour],
      ['Description', result.detail],
      ['Uptime', fields.uptime],
    ]);

  const networkBlock = block(
    'Network', `Project default ${device.ipTemplate}`, [
      ['IP template', device.ipTemplate],
      ['Expected IP', device.ip],
      ['Reached at',
        result.state === 'ok' ? device.ip : 'No verified access',
        result.state === 'ok' ? 'ok' : 'text-dim'],
      ['Switch · port', device.portLabel],
      ['MAC', fields.mac],
      ['Network / time', fields.networkTime],
      ['Time zone', fields.timezone],
    ]);

  const sipRows = device.pbxExtension ? [
    ['Project PBX IP', device.piscuIp],
    ['Expected SIP extension', device.pbxExtension],
    ['Read SIP extension', fields.sipExtension,
      fields.sipExtension
        ? (String(fields.sipExtension) === String(device.pbxExtension)
          ? 'ok' : 'failed')
        : null],
    ['PBX reported by the device', fields.sipPbx],
    // On ADB devices the registration state comes from the app's own log; it
    // is not a verification asked of the PBX (see MIMARI §12).
    ...(device.readMethod === 'adb'
      ? [['SIP registration state (device log)', fields.sipRegistration,
          String(fields.sipRegistration || '').startsWith('registered')
            ? 'ok' : (fields.sipRegistration ? 'failed' : null)],
         // Did the number come from the device's log or from the broker's
         // announcement? Both should give the same value; hiding the source
         // would present a value never read from the device as though it had
         // been.
         ['Source of the extension', fields.sipExtensionSource],
         ['Source of the PBX address', fields.sipPbxSource]]
      // Gain is a setting separate from the volume (speakerGain / micGain on
      // the device); the two are not shown on one row. The outbound number is
      // the target the device calls, not its own extension.
      : [['SIP outbound number', fields.sipOutbound],
         ['Speaker volume', fields.speakerVolume],
         ['Microphone volume', fields.micVolume],
         ['Speaker gain', fields.speakerGain],
         ['Microphone gain', fields.micGain]]),
  ] : [
    ['Read method', method.code || device.readMethod],
    ['Path', method.path],
    ['Period', method.period ? `${method.period} s` : 'Manual'],
    ['Needs credentials', method.needsAuth ? 'Yes' : 'No'],
    ['Credentials stored this session',
      device.hasCredentials ? 'Yes (this session only)' : 'No'],
  ];

  const box = el('div', {
    class: 'detail', role: 'dialog', 'aria-modal': 'true',
    'aria-label': t('detail.dialogLabel', { device: device.name }),
  }, [
    el('div', { style: 'display:flex;align-items:flex-start;gap:14px' }, [
      el('div', { style: 'flex:1;min-width:0' }, [
        el('div', {
          class: 'eyebrow', text: typeLabel(device.typeLabel),
        }),
        el('h2', { style: 'margin:5px 0 0', text: device.name }),
        el('div', {
          class: 'mono text-mid', style: 'margin-top:5px;font-size:11.5px',
          text: `${device.ip} · ${device.portLabel}`,
        }),
      ]),
      el('button', {
        type: 'button', class: 'btn btn-close', 'aria-label': t('detail.close'),
        onclick: close,
      }, ['×']),
    ]),
    el('div', {
      style: 'display:flex;gap:8px;margin-top:16px;flex-wrap:wrap',
    }, actions),
    el('div', {
      class: 'info', style: 'margin-top:14px',
      text: result.readAt
        ? `Last read: ${clockTime(result.readAt)} · Method: `
          + `${method.code || device.readMethod}`
        : 'This device has not been read yet.',
    }),
    summaryBlock,
    networkBlock,
    device.pbxExtension
      ? block('SIP', method.path || '', sipRows)
      : el('details', { class: 'tech-detail' }, [
          el('summary', { text: t('detail.technicalDetails') }),
          block('Data source', method.path || '', sipRows),
        ]),
  ]);

  const backdrop = el('div', {
    class: 'backdrop right',
    onclick: (e) => { if (e.target === backdrop) close(); },
  }, [box]);

  fill($('#detail-slot'), [backdrop]);
  if (release) release();
  release = focusTrap(backdrop, close);
  const first = box.querySelector('button');
  if (first) first.focus();
}
