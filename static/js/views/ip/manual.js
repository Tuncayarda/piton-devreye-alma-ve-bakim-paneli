// The bench flow: one display, one port, one address the operator types.
//
// It shares nothing with the plan the rest of this screen is built on —
// there is no DeviceMap row to honour, which is the whole point of testing a
// display before the train it belongs to exists. What it does keep are the
// safeguards: the switch port is still isolated for the write, and the MAC
// address still has to prove the answer came from that port.

import { el } from '../../core/dom.js';
import { api } from '../../core/api.js';
import { state, patch } from '../../core/store.js';
import { confirmWrite } from '../../components/confirm.js';
import { showSuccess, notify } from '../../components/toast.js';
import { local } from './state.js';
import { isIpv4, parsePorts } from './ports.js';
import { maskField, onMaskResult } from './validation.js';
import { t } from '../../core/i18n.js';


// The bench flow: one display on one port, one address the operator types.
// It shares nothing with the plan above — there is no DeviceMap row to
// honour, which is the whole point of testing a display before the train it
// belongs to exists. The switch port is still isolated and the MAC still has
// to prove the answer came from it.
export function manualAssignCard(data, check) {
  const { plan } = data;
  const warning = el('p', {
    id: 'ip-lcd-manual-error', class: 'ip-field-error', role: 'alert',
    text: '', hidden: true,
  });
  const startButton = el('button', {
    type: 'button', class: 'btn btn-primary',
    text: local.manualBusy ? t('ip.lcdManualBusy') : t('ip.lcdManualStart'),
    disabled: true,
    onclick: () => startManual(plan),
  });

  // Typed into, never redrawn: a render on every keystroke takes focus out
  // of the box (the same reason the port and address fields above do this).
  // `latest` is the freshly validated run when the mask box calls in — the
  // render-time `check` still holds the mask as it was before the keystroke.
  function review(latest = check) {
    const port = String(local.manualPort || '');
    const address = String(local.manualIp || '');
    const portError = port && !parsePorts(port, plan.allowedPorts || [])
      .ports.length ? t('ip.lcdManualPortInvalid') : '';
    const addressError = address && !isIpv4(address)
      ? t('ip.lcdManualIpInvalid') : '';
    warning.textContent = portError || addressError;
    warning.hidden = !(portError || addressError);
    startButton.disabled = local.manualBusy || !port || !address
      || !!portError || !!addressError || !!latest.maskError;
  }

  const field = (id, key, labelKey, extra = {}) => el('label', {
    class: 'setting-row', for: id,
  }, [
    el('span', { class: 'label', text: t(labelKey) }),
    el('input', {
      id, class: 'field ip-medium-field', value: String(local[key] || ''),
      autocomplete: 'off', spellcheck: 'false',
      'aria-describedby': 'ip-lcd-manual-error',
      disabled: local.manualBusy,
      ...extra,
      oninput: (event) => {
        local[key] = event.target.value.trim();
        review();
      },
    }),
  ]);

  // A mask typed on either card decides whether this run can start, so the
  // button is re-checked from there too.
  onMaskResult((result) => review(result));

  const card = el('section', { class: 'card corner ip-manual-card' }, [
    el('div', { class: 'ip-factory-reset-head' }, [
      el('div', {}, [
        el('h3', { text: t('ip.lcdManualSection') }),
        el('p', { text: t('ip.lcdManualNote') }),
      ]),
    ]),
    field('ip-lcd-manual-port', 'manualPort', 'ip.lcdManualPort',
          { inputmode: 'numeric' }),
    field('ip-lcd-manual-ip', 'manualIp', 'ip.lcdManualIp'),
    warning,
    // The mask this run writes, editable here. It used to be a sentence
    // pointing at a field on another card — which meant scrolling away from
    // the run you were setting up to change a value that belongs to it.
    // Both boxes hold the same setting (see maskField).
    ...maskField(data, check, () => {}, 'ip-lcd-manual-mask'),
    el('div', { class: 'ip-factory-reset-actions' }, [
      el('p', { text: t('ip.lcdManualHow') }),
      startButton,
    ]),
  ]);
  review();
  return card;
}
export function startManual(plan) {
  if (local.manualBusy) return;
  confirmWrite({
    title: t('ip.lcdManualSection'),
    lead: t('confirm.lcdManualLead', {
      port: local.manualPort, ip: local.manualIp,
    }),
    notes: [{ text: t('ip.lcdManualHow') }],
    confirmLabel: t('ip.lcdManualStart'),
    run: () => runManual(plan),
  });
}
export async function runManual(plan) {
  local.manualBusy = true;
  patch({ ipState: { ...state.ipState } });
  try {
    const job = await api.ipLcdAssign({
      set: state.setNo,
      switch: plan.switchId,
      groups: plan.groups || [],
      port: String(local.manualPort || ''),
      targetIp: String(local.manualIp || ''),
      targetMask: local.targetMask || '',
      protected: (local.protected && local.protected.ports) || [],
    });
    patch({ queueOpen: true, openJob: job.id });
    if (job.new === false) notify(t('ip.anIpAssignmentJobIs'));
    else showSuccess(t('ip.lcdManualQueued'));
  } finally {
    local.manualBusy = false;
    if (state.view === 'ip' && state.ipState) {
      patch({ ipState: { ...state.ipState } });
    }
  }
}
