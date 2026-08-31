// The switch screen.
//
// A bench and cabinet tool, like the ADB screen, and like it deliberately
// project-free: its devices are switches found by sweeping a network, not
// entries in DeviceMap, and no train set applies. It replaces the separate
// Switch Management Panel that used to be a second application — the whole
// point being that the password entered here also unlocks the IP assignment
// screen, because both now look it up in the same place
// (`panel.switch.device.GROUP`).
//
// SPLIT INTO SEVEN FILES BESIDE THIS ONE, the division the ADB screen settled
// on:
//
//   state.js         selection and the poll's timer
//   session.js       the sign-in dialog — the only place a password appears
//   discovery.js     the sweep and the list of switches it found
//   front_panel.js   the faceplate, interactive
//   ports.js         the PoE and uplink tables
//   context_menu.js  the right-click menu, which writes to several ports
//   network.js       the management address, save, restart, factory reset
//
// The sweep is a queued job and is polled; everything else is a request that
// answers on the spot. Why: `panel/api/routes/switch_routes.py`.

import { el, fill } from '../../core/dom.js';
import { api } from '../../core/api.js';
import { latest } from '../../core/latest.js';
import { poll } from '../../core/poll.js';
import { state, patch } from '../../core/store.js';
import { notify, showError, showSuccess } from '../../components/toast.js';
import { t } from '../../core/i18n.js';
import {
  POLL_INTERVAL, clearSelection, clickPort, forgetAllTyped,
  forgetTypedPassword, local, onScreen, poeModes,
  pruneSelection, scanning, selectedIp, typed,
} from './state.js';
import {
  discoveryCard, seedCidr, startDiscovery, stopDiscovery,
} from './discovery.js';
import { needsCredentials, signIn } from './session.js';
import { frontPanelCard } from './front_panel.js';
import { portsCard } from './ports.js';
import { networkCard } from './network.js';
import * as contextMenu from './context_menu.js';

let root = null;

// ── talking to the server ───────────────────────────────────────────────

// `latest` retires a reload overtaken by a newer one. Deliberately NOT
// set-scoped: like the ADB bench, this screen's switches belong to no train
// set (see the header), so there is no `setNo` to re-check here the way the
// IP and firmware refreshes must.
export const refresh = latest(async (fresh) => {
  try {
    const body = await api.switchScreen();
    if (!fresh()) return;
    patch({ switchState: body });
    seedCidr();
  } catch {
    if (!fresh()) return;
    patch({ switchState: null });
  }
  round.arm();
  draw();
});

// The poll that follows a running sweep, once a second (core/poll.js —
// setTimeout chained after the reply, the house rule). `while` also ends
// the beat: the round that fetches the finished sweep's body finds
// `scanning` false when it re-arms, so the final results land and the poll
// stops itself.
const round = poll({
  run: async () => {
    try {
      const body = await api.switchScreen();
      patch({ switchState: body });
      draw();
    } catch {
      // A failed poll is not worth a message: the next one will say so, and
      // this runs once a second.
    }
  },
  interval: POLL_INTERVAL,
  while: () => onScreen() && scanning(),
});

// Everything about one switch: its identity, its network, and its ports.
// Read together because the screen shows them together — two round trips
// that always happen at once are one request's worth of information.
async function loadSwitch(ip) {
  local.loadingPorts = true;
  draw();
  try {
    const info = await api.switchInfo(ip);
    const ports = await api.switchPorts(ip);
    local.info = info;
    local.ports = ports.ports || [];
    local.form = {
      address: (info.network && info.network.address) || ip,
      prefix: String((info.network && info.network.prefix) || '24'),
      mtu: String((info.network && info.network.mtu) || '1500'),
    };
    pruneSelection();
  } catch (error) {
    local.info = null;
    local.ports = [];
    if (needsCredentials(error)) {
      // Not a fault to shout about — it is the expected first state of every
      // switch, and the answer is already on screen: the row's own boxes.
      // The list redraws with them enabled (the server marks it locked).
      notify(t('switch.errorNeedsCredentials', { ip }));
      refresh();
    } else {
      showError(error.message);
    }
  } finally {
    local.loadingPorts = false;
    draw();
  }
}

// Re-read the ports after a write, so the screen shows what the switch now
// says rather than what it was asked for.
async function reloadPorts() {
  const ip = selectedIp();
  if (!ip) return;
  try {
    const ports = await api.switchPorts(ip);
    local.ports = ports.ports || [];
    pruneSelection();
    contextMenu.refresh();
  } catch (error) {
    if (!needsCredentials(error)) showError(error.message);
  }
  draw();
}

// One wrapper for every write: it holds the busy flag, reports the outcome
// once, writes the log line, and re-reads. Each call site doing that itself
// is how a screen ends up stuck on "working" after one forgotten catch.
async function write(describe, run, { reload = true } = {}) {
  if (state.switchBusy) return;
  patch({ switchBusy: true });
  draw();
  try {
    await run();
    showSuccess(describe);
    if (reload) await reloadPorts();
  } catch (error) {
    if (needsCredentials(error)) {
      notify(t('switch.errorNeedsCredentials', { ip: selectedIp() }));
      refresh();
    } else {
      showError(error.message);
    }
  } finally {
    patch({ switchBusy: false });
    draw();
  }
}

// ── what the cards can ask for ──────────────────────────────────────────

const actions = {
  redraw: () => draw(),

  // The two fields are joined by the form; what arrives here is the
  // expression the server parses (panel/switch/discovery.py).
  discover: (expression) => {
    startDiscovery(expression, () => { round.arm(); draw(); });
  },

  cancelDiscover: () => stopDiscovery(() => { round.arm(); draw(); }),

  // ONE BUTTON FOR BOTH STEPS. Signing in and opening are two things to the
  // server and one to the operator: they typed a password to see the ports.
  // With the boxes empty this is just "open" — which is right, because the
  // account may already be in memory from another switch in the same set.
  connectSwitch: async (ip) => {
    const store = typed(ip);
    if (store.user || store.password) {
      patch({ switchBusy: true });
      draw();
      try {
        await signIn(ip, store.user, store.password);
        await refresh();          // the row stops saying it is locked
      } catch (error) {
        // The switch said no. The password must not wait around for a retry
        // — signIn only erases it on the SUCCESS path, so without this it
        // sat in typed(ip) and in the row's box for the rest of the session.
        // The username stays; draw() rebuilds the row from typed(ip), which
        // is what empties the password input on screen.
        forgetTypedPassword(ip);
        showError(error.message);
        draw();
        return;
      } finally {
        patch({ switchBusy: false });
      }
    }
    actions.openSwitch(ip);
  },

  openSwitch: (ip) => {
    if (ip === selectedIp()) { loadSwitch(ip); return; }
    contextMenu.close();
    // Everything below belongs to the switch that was open. Carrying a
    // selection across would aim the next right-click at the wrong device.
    clearSelection();
    local.info = null;
    local.ports = [];
    patch({ switchSelected: ip });
    loadSwitch(ip);
  },

  clickPort: (id, event) => { clickPort(id, event); draw(); },

  // Right-click opens the port menu on the SELECTION, not just on the port
  // under the cursor — the operator who has just picked ports 5 to 12 means
  // those twelve. A right-click on a port outside the selection replaces it,
  // which is what every file manager does and what the hand expects.
  contextPort: (id, event) => {
    event.preventDefault();
    if (!local.selected.has(id)) {
      local.selected = new Set([id]);
      local.anchor = id;
      draw();
    }
    contextMenu.openMenu([...local.selected].sort((a, b) => a - b),
                         event, actions, poeModes());
  },

  // One port's PoE, written now. A dropdown that changed the screen and not
  // the switch would be a dropdown that lies.
  setPoe: (id, mode) => {
    const ip = selectedIp();
    const chosen = poeModes().find(m => m.value === String(mode));
    const label = chosen ? t(chosen.labelKey) : mode;
    return write(t('switch.logPoeSet', { port: id, mode: label, ip }),
                 () => api.switchPoe(ip, id, String(mode)));
  },

  setPortEnabled: (id, enabled) => {
    const ip = selectedIp();
    return write(
      t(enabled ? 'switch.logPortEnabled' : 'switch.logPortDisabled',
        { port: id, ip }),
      () => api.switchPort(ip, id, { enabled: !!enabled }));
  },

  // What the right-click menu chose, for every port it was opened on. `null`
  // for either half means "leave this one alone". Sent as ONE batch: the
  // switch rewrites its whole port table per write, so twelve separate calls
  // would rewrite twenty-eight ports twelve times.
  applyFromMenu: (ids, poeMode, enabled) => {
    const ip = selectedIp();
    const poe = {};
    const ports = {};
    for (const id of ids) {
      const port = local.ports.find(each => each.id === id);
      if (!port) continue;
      // An uplink has no PoE to set. Skipped rather than refused: the
      // operator selected a block, not each port individually.
      if (poeMode !== null && port.supportsPoe) poe[id] = String(poeMode);
      if (enabled !== null) ports[id] = !!enabled;
    }
    const count = Object.keys(poe).length + Object.keys(ports).length;
    if (!count) return undefined;
    return write(t('switch.logApplied', { count, ip }),
                 () => api.switchBatch(ip, poe, ports));
  },

  setNetwork: (values) => {
    const ip = selectedIp();
    return write(
      t('switch.logAddressChanged', {
        ip, address: values.address, prefix: values.prefix,
      }),
      () => api.switchNetwork(ip, values),
      // The switch has moved; re-reading the old address would only time
      // out. The operator scans again to find it where it now is.
      { reload: false });
  },

  saveConfiguration: () => {
    const ip = selectedIp();
    return write(t('switch.logConfigurationSaved', { ip }),
                 () => api.switchConfigSave(ip), { reload: false });
  },

  reboot: () => {
    const ip = selectedIp();
    return write(t('switch.logRebooted', { ip }),
                 () => api.switchReboot(ip), { reload: false });
  },

  factoryReset: (confirm) => {
    const ip = selectedIp();
    return write(t('switch.logFactoryReset', { ip }),
                 () => api.switchFactoryReset(ip, confirm),
                 { reload: false });
  },
};

// ── drawing ─────────────────────────────────────────────────────────────

function draw() {
  if (!root || !onScreen()) return;
  const busy = state.switchBusy;
  fill(root, [
    el('div', { class: 'page-head' }, [
      el('h2', { text: t('nav.switch') }),
      el('div', { class: 'actions' }, [
        el('button', {
          type: 'button', class: 'btn', disabled: busy,
          text: t('switch.buttonReload'),
          onclick: () => { refresh(); if (selectedIp()) loadSwitch(selectedIp()); },
        }),
      ]),
    ]),
    discoveryCard(actions),
    frontPanelCard(actions, selectedIp(), busy),
    portsCard(actions, busy),
    networkCard(actions),
  ]);
}

// DRAWING ONLY. `app.js` calls this on every store publish — the job queue
// alone republishes once a second — so a fetch in here would be a request per
// second for a screen that is merely on display. The data comes from
// `refresh()`, which `the VIEW_LIFECYCLE table's enter hook` calls once when the screen opens, and
// from the poll below while a sweep runs. (Same division as the ADB screen;
// getting it wrong there is what the note in its render() is about.)
export function render(container) {
  root = container;
  seedCidr();
  draw();
  // The poll owns its timer and stops itself when the sweep ends; it is not
  // rebuilt on every render, or it would never elapse — `active()` first.
  if (scanning() && !round.active()) round.arm();
}

export function stop() {
  round.stop();
  contextMenu.close();
  // Leaving the screen abandons whatever was half-typed into the rows'
  // boxes: the inputs are about to be torn down, and the module copy must
  // not outlive them.
  forgetAllTyped();
}
