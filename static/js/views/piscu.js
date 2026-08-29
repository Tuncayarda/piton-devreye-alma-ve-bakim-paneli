// The PISCU & Asterisk PBX screen.
//
// The SIP table is not built by asking the PBX but from the values the
// devices report themselves (no ARI account is defined). That is stated
// plainly on screen — showing something as "registered" when it is in fact
// unverified would be fake data.

import { el, fill } from '../core/dom.js';
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import { value, stateLabel } from '../core/format.js';
import { t } from '../core/i18n.js';

export async function refresh() {
  try {
    patch({ piscuState: await api.piscu(state.setNo) });
  } catch {
    patch({ piscuState: null });
  }
}

export function render(root) {
  const data = state.piscuState;
  const parts = [];

  parts.push(el('div', { class: 'page-head' }, [
    el('div', {}, [el('h2', { text: t('piscu.piscuAsteriskPbx') })]),
    el('div', { class: 'actions' }, [
      el('button', {
        type: 'button', class: 'btn', text: t('piscu.refresh'), onclick: refresh,
      }),
    ]),
  ]));

  if (!data) {
    parts.push(el('p', {
      class: 'warning', text: t('piscu.piscuInformationCouldNotBe'),
    }));
    fill(root, parts);
    return;
  }


  const card = (title, rows, emptyText) => el('div', {
    class: 'card corner',
  }, [
    el('h3', { style: 'margin-bottom:12px', text: title }),
    ...(rows.length ? rows : [el('div', {
      class: 'mono text-dim t-sm', text: emptyText,
    })]),
  ]);

  const clients = data.clients.map(client => el('div', {
    class: 't-sm',
    style: 'display:grid;grid-template-columns:minmax(0,1fr) 104px 96px;'
      + 'gap:10px;padding:7px 0;border-bottom:1px solid var(--line-soft);'
      + 'font-family:var(--font-mono)',
  }, [
    el('span', { class: 'truncate', text: client.name }),
    el('span', { class: 'text-mid', text: client.ip }),
    el('span', {
      dataset: { state: client.state }, style: 'color:var(--state-text)',
      title: client.detail || '',
      text: client.version
        ? `v${client.version}`
        : stateLabel(client.state, ' '),
    }),
  ]));

  const extensions = data.extensions.map(entry => el('div', {
    class: 't-sm',
    style: 'display:grid;grid-template-columns:64px minmax(0,1fr) 96px 96px;'
      + 'gap:10px;padding:7px 0;border-bottom:1px solid var(--line-soft);'
      + 'font-family:var(--font-mono)',
  }, [
    el('span', { style: 'color:var(--accent)', text: entry.extension }),
    el('span', { class: 'truncate', text: entry.name }),
    el('span', { class: 'text-mid', text: value(entry.reportedExtension) }),
    el('span', {
      dataset: { state: entry.state }, style: 'color:var(--state-text)',
      text: stateLabel(entry.state, ' '),
    }),
  ]));

  parts.push(el('div', { class: 'overview-grid' }, [
    card(t('piscu.mqttClients'), clients, t('piscu.piscuAndHmiNotRead')),
    card(t('piscu.sipExtensions'), [
      el('div', {
        class: 'label',
        style: 'display:grid;grid-template-columns:64px minmax(0,1fr) 96px 96px;'
          + 'gap:10px;padding-bottom:6px',
      }, [
        el('span', { text: t('piscu.expected') }),
        el('span', { text: t('piscu.device') }),
        el('span', { text: t('piscu.reported') }),
        el('span', { text: t('piscu.state') }),
      ]),
      ...extensions,
    ], t('piscu.noDeviceHasSip')),
  ]));

  fill(root, parts);
}
