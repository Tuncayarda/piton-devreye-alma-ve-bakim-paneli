// The computer's own network.
//
// Every other screen assumes the devices can be reached. That assumption
// broke in the field: an unconfigured intercom answers on 10.1.1.12 whatever
// train set it belongs to, and a computer sitting on 10.17.1.222/24 has no
// route there at all. The run was not at fault — the packets never left the
// machine — but the only clue on screen was "device not found" on every port.
//
// The panel now adds the missing addresses itself, before a run or a scan
// starts. This screen is where that becomes visible and reversible: which
// adapter it used, which networks it decided were needed, which addresses it
// added, and the one decision it cannot make reliably on its own — WHICH
// adapter, when the computer is on a foreign network and there is no route
// to follow.
//
// Nothing here edits or removes an address the panel did not add.

import { el, fill } from '../core/dom.js';
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import { showError, showSuccess } from '../components/toast.js';
import { confirmWrite } from '../components/confirm.js';
import { t } from '../core/i18n.js';

// Shown in the explanation until the server answers. Fixed, not resolved per
// set: a device leaves the factory without knowing which set it joins, so
// they all arrive on the same address (see panel/settings.py FACTORY_IP).
const FACTORY_FALLBACK = '10.1.1.12';

// One request at a time. Every button here rewrites the machine's network
// configuration and the answer carries the new state; two in flight would
// race to patch it.
let busy = false;

// Opening the screen PREPARES; it does not just report.
//
// There is no "prepare the network" button and there should not be one. The
// people who commission these trains are not network engineers, and a screen
// that lists what is missing and then waits to be told to fix it is a screen
// that gets read as broken. Everything else already prepares on its own — a
// run, a scan, a change of train set — so the one place that only looked was
// the odd one out.
//
// Preparing is safe to repeat: an address that is already there is not in
// `required`, so a second visit adds nothing (see planning.required_networks).
export async function refresh() {
  try {
    patch({ networkState: await api.networkPrepare(state.setNo) });
  } catch {
    // Falling back to the read-only view: the screen must still be able to
    // say what it sees when preparing itself failed.
    try {
      patch({ networkState: await api.network(state.setNo) });
    } catch {
      patch({ networkState: null });
    }
  }
}

async function act(call) {
  if (busy) return null;
  busy = true;
  try {
    const data = await call();
    patch({ networkState: data });
    return data;
  } catch (e) {
    showError(e.message);
    return null;
  } finally {
    busy = false;
  }
}

function stateText(adapter) {
  if (!adapter) return '';
  if (adapter.up === true) return t('net.stateUp');
  if (adapter.up === false) return t('net.stateDown');
  return t('net.stateUnknown');
}

function addressText(adapter) {
  if (!adapter || !adapter.addresses.length) return t('net.noAddress');
  return adapter.addresses.join(', ');
}

function row(label, valueNode, hint = '') {
  return el('div', { class: 'net-row' }, [
    el('span', { class: 'net-label' }, [
      el('span', { text: label }),
      hint && el('span', { class: 'net-hint', text: hint }),
    ]),
    typeof valueNode === 'string'
      ? el('b', { class: 'mono', text: valueNode })
      : valueNode,
  ]);
}

// ── the chosen adapter, and the picker ──────────────────────────────────
//
// The panel picks an adapter only when it can point at a FACT: one that
// already holds an address on the devices' network. It used to fall back to a
// ranking (carrier, wired, addressed) and on a laptop tethered to a phone it
// picked the phone — an adapter with nothing on the far end. So when there is
// no fact to go on, this card asks instead of guessing, and the question is
// the loudest thing on the screen.
function adapterCard(data) {
  const chosen = data.adapter;
  const usable = (data.adapters || []).filter(
    entry => !entry.virtual && entry.handle);
  const pinned = data.preferences.adapter;

  const picker = el('select', {
    class: 'net-input',
    onchange: async (event) => {
      const result = await act(
        () => api.networkSettings({ adapter: event.target.value,
          set: state.setNo }));
      // Choosing prepares in the same request; say what it did rather than
      // leaving the user to notice the list changed.
      if (result && result.added && result.added.length) {
        showSuccess(t('net.preparedCount', { count: result.added.length }));
      }
    },
  }, [
    el('option', { value: '', text: t('net.adapterAuto'), selected: !pinned }),
    ...usable.map(entry => el('option', {
      value: entry.name,
      selected: pinned === entry.name,
      text: `${entry.name} — ${addressText(entry)}`,
    })),
  ]);

  if (data.needsAdapter) {
    return el('div', { class: 'card corner net-card net-ask' }, [
      el('span', { class: 'eyebrow', text: t('net.pickAdapter') }),
      el('p', { class: 'net-note', text: t('net.pickAdapterWhy') }),
      row(t('net.adapterPick'), picker),
    ]);
  }

  return el('div', { class: 'card corner net-card' }, [
    el('span', { class: 'eyebrow', text: t('net.connection') }),
    row(t('net.adapter'), el('b', {
      class: chosen ? 'net-accent' : 'text-dim',
      text: chosen ? `${chosen.name} · ${stateText(chosen)}`
        : t('net.noUsableAdapter'),
    })),
    row(t('net.addresses'), addressText(chosen)),
    // The actual address, spelled out. Working it back from a "last octet"
    // field is not something anyone should have to do to answer "what is this
    // computer's address on the device network".
    data.baseAddress && row(t('net.baseAddress'), data.baseAddress,
                            t('net.baseAddressHint', {
                              set: data.setNo,
                              octet: data.preferences.octet,
                            })),
    row(t('net.adapterPick'), picker),
  ]);
}

// ── which networks are needed, and which addresses were added ───────────
//
// `required` is what the computer CANNOT reach; the server drops a network
// the moment an address of ours falls inside it. So an address added here
// leaves the required list on the next answer, and the two never contradict
// each other.
function requiredCard(data) {
  const required = data.required || [];
  const added = data.aliases || [];
  const children = [el('span', { class: 'eyebrow', text: t('net.required') })];

  if (!required.length && !added.length) {
    children.push(el('p', { class: 'net-note',
      text: t('net.nothingRequired') }));
  }

  for (const entry of required) {
    // Rendered from the KEY, not from the sentence the server already
    // rendered: a language switch redraws every screen from the catalogue
    // without refetching, and the ready-made sentence would stay behind in
    // the old language.
    const reason = entry.reasonKey ? t(entry.reasonKey) : entry.reason;
    children.push(el('div', { class: 'net-row' }, [
      el('span', { class: 'net-label' }, [
        el('b', { class: 'mono', text: entry.network }),
        el('span', { class: 'net-hint',
          text: entry.target
            ? `${reason} · ${t('net.for', { target: entry.target })}`
            : reason }),
      ]),
      el('span', { class: 'badge', text: t('net.stateMissing') }),
    ]));
  }

  if (added.length) {
    children.push(el('span', { class: 'eyebrow', text: t('net.added') }));
    for (const entry of added) {
      children.push(el('div', { class: 'net-row' }, [
        el('span', { class: 'net-label' }, [
          el('b', { class: 'mono', text: `${entry.ip}/${entry.prefix}` }),
          el('span', { class: 'net-hint', text: entry.adapter }),
        ]),
        el('span', { class: 'net-actions' }, [
          el('span', { class: 'badge', text: t('net.stateReady') }),
          el('button', {
            type: 'button', class: 'btn btn-small',
            text: t('net.releaseOne'),
            onclick: () => act(() => api.networkRelease(state.setNo, entry.ip)),
          }),
        ]),
      ]));
    }
  } else if (required.length) {
    children.push(el('p', { class: 'net-note', text: t('net.noneAdded') }));
  }

  // A network still missing after the screen has prepared means something
  // went wrong, and the reason is the only useful thing to show. Without it
  // the user is left with "no address" and nowhere to go.
  for (const failure of (data.failed || [])) {
    children.push(el('p', { class: 'warning',
      text: t('net.failedLine', { network: failure.network || '—',
        detail: failure.error }) }));
  }

  // Three paragraphs explaining how this works, folded away. They are worth
  // having — how the addresses appear, that they are session-only, what the
  // conflict check does and does not cover — but they were unconditional and
  // took up more of the screen than the addresses did. The one question
  // somebody opens this screen to answer is at the top now (see
  // `readinessLine`); the explanation is a click away for whoever wants it.
  children.push(el('details', { class: 'net-explainer' }, [
    el('summary', { text: t('net.howItWorks') }),
    el('p', { class: 'net-note', text: t('net.automaticNote') }),
    el('p', { class: 'net-note', text: t('net.sessionOnly') }),
    el('p', { class: 'net-note', text: t('net.collisionNote') }),
  ]));

  // Undo only. There is no "prepare" button: opening this screen, starting a
  // run, scanning or changing train set all prepare on their own, so a button
  // for it would only ever be pressed after something had already done it.
  children.push(el('div', { class: 'net-actions' }, [
    el('button', {
      type: 'button', class: 'btn',
      disabled: !added.length,
      text: t('net.release'),
      // Taking every address back can leave this computer with no route to
      // the devices at all — the run then fails the way dead hardware does.
      onclick: () => confirmWrite({
        title: t('net.release'),
        lead: t('confirm.releaseAllLead', { count: added.length }),
        notes: [{ text: t('confirm.releaseAllNote'), tone: 'warning' }],
        items: added.map(entry => ({
          name: `${entry.ip}/${entry.prefix}`, detail: entry.adapter,
        })),
        danger: true,
        confirmLabel: t('net.release'),
        run: async () => {
          const result = await act(() => api.networkRelease(state.setNo));
          if (result) {
            showSuccess(t('net.releasedCount', { count: result.released }));
          }
        },
      }),
    }),
  ]));

  return el('div', { class: 'card corner net-card' }, children);
}

// The one line somebody opens this screen for: is the computer ready to
// reach the devices, or is something missing? It used to be a sentence
// buried in the fourth paragraph of a card.
function readinessLine(data) {
  const required = (data.required || []).length;
  const added = (data.aliases || []).length;
  const failed = (data.failed || []).length;
  const state_ = failed ? 'failed' : required ? 'auth' : 'ok';
  const text = failed
    ? t('net.stateFailed', { count: failed })
    : required
      ? t('net.stateMissingCount', { count: required })
      : added
        ? t('net.stateReadyWith', { count: added })
        : t('net.stateReadyPlain');
  return el('div', { class: 'net-readiness', dataset: { state: state_ } }, [
    el('span', { class: 'dot', dataset: { state: state_ },
      'aria-hidden': 'true' }),
    el('span', { text }),
  ]);
}

export function render(root) {
  const data = state.networkState;
  const parts = [
    el('div', { class: 'page-head' }, [
      el('div', {}, [
        el('h2', { text: t('net.title') }),
        el('p', { class: 'net-note', text: t('net.intro', {
          factory: (data && data.factoryIp) || FACTORY_FALLBACK,
        }) }),
      ]),
      data ? readinessLine(data) : null,
    ]),
  ];

  if (!data) {
    parts.push(el('div', { class: 'card corner net-card' }, [
      el('p', { class: 'net-note', text: t('net.noAdapter') }),
    ]));
    fill(root, parts);
    return;
  }

  if (!data.supported) {
    parts.push(el('p', { class: 'warning',
      text: t('net.unsupported', { system: data.system }) }));
  }

  parts.push(adapterCard(data), requiredCard(data));
  fill(root, parts);
}
