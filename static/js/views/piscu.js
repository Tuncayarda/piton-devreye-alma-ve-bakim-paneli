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

  // THE HEADING IS THE ANSWER, and on this screen the answer is the SIP
  // table: the extensions the devices report against the ones the project
  // says they should have. The name of the screen is on the menu rail and in
  // the hidden `h1`; what nobody could see without reading four columns of a
  // list was whether any of them disagree.
  const extensionRows = (data && data.extensions) || [];
  const wrong = extensionRows.filter(entry => entry.state !== 'ok').length;
  const verdict = !data ? t('piscu.piscuAsteriskPbx')
    : !extensionRows.length ? t('piscu.noDeviceHasSip')
      : wrong ? t('piscu.extensionsWrong',
                  { count: wrong, total: extensionRows.length })
        : t('piscu.extensionsAllMatch', { total: extensionRows.length });
  parts.push(el('div', { class: 'page-head' }, [
    el('h2', {
      class: 'verdict',
      dataset: { state: !data ? 'unknown' : wrong ? 'failed' : 'ok' },
    }, [
      el('span', {
        class: 'dot',
        dataset: { state: !data ? 'unknown' : wrong ? 'failed' : 'ok' },
        'aria-hidden': 'true',
      }),
      el('span', { text: verdict }),
    ]),
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
    el('div', { class: 'card-head' }, [el('h3', { text: title })]),
    ...(rows.length ? rows : [el('div', {
      class: 'mono text-dim t-sm', text: emptyText,
    })]),
  ]);

  // `.state-text` rather than a colour written into the row: it is the same
  // token, said once, in the one place the panel keeps it.
  const clients = data.clients.map(client => el('div', {
    class: 't-sm piscu-row piscu-clients',
  }, [
    el('span', { class: 'truncate', title: client.name, text: client.name }),
    el('span', { class: 'text-mid', text: client.ip }),
    el('span', {
      class: 'state-text truncate', dataset: { state: client.state },
      title: client.detail || '',
      text: client.version
        ? `v${client.version}`
        : stateLabel(client.state, ' '),
    }),
  ]));

  const extensions = data.extensions.map(entry => el('div', {
    class: 't-sm piscu-row piscu-extensions',
  }, [
    el('span', { class: 'sip-extension', text: entry.extension }),
    el('span', { class: 'truncate', title: entry.name, text: entry.name }),
    el('span', { class: 'text-mid', text: value(entry.reportedExtension) }),
    el('span', {
      class: 'state-text truncate', dataset: { state: entry.state },
      text: stateLabel(entry.state, ' '),
    }),
  ]));

  // THE TABLE WITH FOUR COLUMNS TAKES THE WIDE SIDE. It was the other way
  // round: the three-column client list had nine hundred pixels of it, most
  // of them empty, and the extensions — four columns, and the reason to open
  // this screen at all — were folded into a four-hundred pixel rail where
  // the device names ran into the numbers beside them.
  parts.push(el('div', { class: 'overview-grid' }, [
    card(t('piscu.sipExtensions'), [
      el('div', { class: 'label piscu-head piscu-extensions' }, [
        el('span', { text: t('piscu.expected') }),
        el('span', { text: t('piscu.device') }),
        el('span', { text: t('piscu.reported') }),
        el('span', { text: t('piscu.state') }),
      ]),
      ...extensions,
    ], t('piscu.noDeviceHasSip')),
    // A caption over these three too. One list had a line naming its columns
    // and the one beside it did not, so the same object was drawn two ways
    // on one screen.
    card(t('piscu.mqttClients'), [
      el('div', { class: 'label piscu-head piscu-clients' }, [
        el('span', { text: t('piscu.device') }),
        el('span', { text: t('col.ip') }),
        el('span', { text: t('piscu.state') }),
      ]),
      ...clients,
    ], t('piscu.piscuAndHmiNotRead')),
  ]));

  fill(root, parts);
}
