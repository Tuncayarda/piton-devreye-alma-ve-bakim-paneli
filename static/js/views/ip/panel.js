// The switch front panel, on the IP assignment screen.
//
// THE DRAWING IS NOT HERE. The faceplate — the connector graphic and the grid
// that puts port 7 in the right hole — lives in
// `components/front_panel.js` and is shared with the Switch screen, which
// shows the front of the same SICOM3028GPT. It used to be copied into both,
// which is exactly how two panels end up disagreeing about where a port is.
//
// What IS here is what only this screen means by a port: whether DeviceMap
// defines a device on it, whether it is a target of the assignment run,
// whether it is the port the computer is plugged into or the link to the
// other switch. The Switch screen colours the same ports by live PoE state
// instead — one drawing, two readings.

import { el } from '../../core/dom.js';
import { connectorSvg, portGrid } from '../../components/front_panel.js';
import { state } from '../../core/store.js';
import { credentialDialog } from '../../components/locked.js';
import { notify } from '../../components/toast.js';
import { local, live } from './state.js';
import { usesPhysicalPortDiscovery } from './software.js';
import { t } from '../../core/i18n.js';

// A port's LIVE state — the connector's colour. The classes and the
// distinctions match the sibling panel's own state function: whoever looks at
// the same switch from two applications should see the same colour.
//   off       — the port is disabled (no data)
//   feed      — a PoE port is powering (linked + watts readable)
//   link      — the link is up but there is no power / it is not PoE
//   (empty)   — not connected
//   unpowered — the port is up, PoE is off: the link works, there is no power
function liveClass(port) {
  if (port.enabled === null) return '';        // no live read (DeviceMap)
  if (!port.enabled) return 'off';
  let className = (port.hasPoe && port.link === 'up' && port.watts) ? 'feed'
    : port.link === 'up' ? 'link' : '';
  if (port.hasPoe && port.poeMode === '0') className += ' unpowered';
  return className.trim();
}

// Intercom assignment stays tied to ports defined in DeviceMap.  Compartment
// LCD commissioning is different: on a test bench the operator may plug a
// display into any physical PoE port.  Uplinks remain unavailable in both
// cases, and protected ports are handled separately by portButton.
export function portIsSelectable(port, physicalPortMode = false) {
  if (physicalPortMode) return port.poe === true;
  return port.defined === true;
}

// A single connector. The colour shows the port's current state, the border
// its role in the run: target ports are marked with a blue border. Folding
// both into one colour confused "is this port up" with "is it selected".
function portButton(port, context) {
  const roles = [liveClass(port)];
  const protectedReason = context.protectedPorts.get(port.number);
  const selectable = portIsSelectable(port, context.physicalPortMode);
  if (port.number === context.computerPort) roles.push('pc');
  else if (protectedReason) roles.push('link-port');
  else if (context.targets.has(port.number)) roles.push('selected');
  if (!port.defined) {
    roles.push(selectable ? 'physical-target' : 'empty');
  }

  const stateText = port.enabled === null ? ''
    : !port.enabled ? t('ippanel.statePortDisabled')
      : port.hasPoe && port.poeMode === '0' ? t('ippanel.statePowerOff')
        : port.link === 'up'
          ? (port.watts
            ? t('ippanel.statePowering', { watts: port.watts })
            : t('ippanel.stateLinked'))
          : t('ippanel.stateEmpty');
  const locked = !!protectedReason || port.number === context.computerPort;
  const description = locked
    ? t('ippanel.portLocked', {
      port: port.number,
      reason: protectedReason || t('ippanel.computerOnPort'),
    })
    : t(context.physicalPortMode && port.poe && !port.defined
      ? 'ippanel.physicalTargetPort'
      : port.defined ? 'ippanel.portDevice' : 'ippanel.portUndefined', {
        port: port.number, device: port.device, state: stateText,
      })
      + (context.active ? ''
        : t('ippanel.switchesTo', { switch: context.switchName }));
  return el('button', {
    type: 'button', class: `pm-port ${roles.join(' ')}`.trim(),
    'aria-pressed': String(context.targets.has(port.number)),
    'aria-label': description,
    'aria-disabled': String(!selectable || locked),
    disabled: !selectable,
    title: description,
    onclick: locked || !selectable
      ? null : () => context.onPortClick(port.number, context),
  }, [
    connectorSvg(port.poe),
    el('span', { text: String(port.number) }),
  ]);
}

// The switch's username/password can be entered from this screen. The only
// route used to be the lock menu, and a device only dropped in there after a
// full scan. So a user who came to IP assignment without scanning was stuck:
// the run failed with "no credentials" and there was nowhere to enter them.
function askSwitchCredentials(panel, onDone) {
  const device = (state.devices || []).find(d => d.id === panel.switchId);
  if (!device) {
    notify(t('ippanel.theSwitchRecordWasNot'));
    return;
  }
  credentialDialog(device, onDone);
}

export function panelCard(panel, plan, handlers) {
  const active = panel.switchId === plan.switchId;
  const targets = new Set(
    active ? plan.rows.filter(row => row.actionable).map(row => row.port) : []);
  // The protected ports come from the discovery (see state.refreshProtected).
  // The computer's port is marked with the "computer" colour only on the
  // switch it is attached to; on the other switches the port where the same
  // MAC appears is the link towards that switch and is drawn in that colour.
  // There is no separate form on screen — this panel is the only place the
  // discovery's findings are shown.
  const protectedPorts = new Map();
  for (const entry of (local.protected && local.protected.ports) || []) {
    if (entry.switchId === panel.switchId && entry.kind !== 'computer') {
      protectedPorts.set(Number(entry.port), entry.reason);
    }
  }
  const computer = (local.protected && local.protected.computer) || null;
  const context = {
    targets,
    active,
    protectedPorts,
    switchId: panel.switchId,
    switchName: panel.switchName,
    computerPort:
      (computer && computer.switchId === panel.switchId && computer.port)
        ? Number(computer.port) : null,
    physicalPortMode: usesPhysicalPortDiscovery(plan),
    onPortClick: handlers.onPortClick,
  };

  const byNumber = {};
  for (const port of panel.ports) byNumber[port.number] = port;
  const poeCount = panel.poeCount || 24;
  const uplinkCount = panel.uplinkCount || 4;

  // The physical layout is the shared component's; this screen only says
  // what goes in each hole.
  const grid = portGrid({
    poeCount,
    uplinkCount,
    cell: (number) => {
      const port = byNumber[number];
      return port ? portButton(port, context) : null;
    },
  });

  return el('article', {
    class: 'card corner front-panel', dataset: { active: active ? '1' : '0' },
  }, [
    el('header', { class: 'ip-switch-head' }, [
      el('div', { class: 'ip-switch-identity' }, [
        el('div', { class: 'ip-switch-name' }, [
          el('i', { 'aria-hidden': 'true' }),
          el('h3', { text: panel.switchName || 'Switch' }),
        ]),
        el('span', { class: 'mono', text: panel.switchIp }),
      ]),
      el('div', { class: 'ip-switch-badges' }, [
        // How fresh the data is: with a live read, how many seconds ago it
        // was taken refreshes every second (see writeFreshness).
        panel.source === 'switch' ? el('span', {
          class: 'ip-freshness', dataset: { readAt: panel.readAt || 0 },
          text: t('ippanel.sAgo'),
        }) : null,
        el('span', {
          class: panel.source === 'switch'
            ? 'badge ip-source-badge live' : 'badge ip-source-badge',
          text: t(panel.source === 'switch' ? 'ippanel.liveData'
            : 'ippanel.projectDefault'),
        }),
        // Without credentials the run cannot start; this must also be where
        // they are entered.
        panel.hasCredentials === false ? el('button', {
          type: 'button', class: 'btn btn-small ip-credential-btn',
          text: t('detail.enterCredentials'),
          onclick: () => askSwitchCredentials(panel, handlers.onCredentials),
        }) : null,
      ]),
    ]),
    // Why the panel could not be read stays as a single line; a separate box
    // per switch showed the same sentence twice on two switches.
    panel.note
      ? el('p', { class: 'ip-panel-note', text: panel.note })
      : null,
    el('div', { class: 'pm-case' }, [
      el('div', { class: 'pm-wrap' }, [grid]),
      el('div', { class: 'pm-footer' }, [
        el('span', { text: t('ippanel.poeRange', { count: poeCount }) }),
        el('span', { class: 'grow' }),
        el('span', {
          text: t('ippanel.uplinkRange', {
            first: poeCount + 1, last: poeCount + uplinkCount,
          }),
        }),
      ]),
    ]),
  ]);
}

// The legend sits once per section. Repeated on every panel card, six items
// were written twice on two switches and took more room than the panel.
export function legend() {
  return el('div', { class: 'panel-legend' }, [
    el('span', {}, [el('i', { class: 'pm-sample selected' }),
      t('ippanel.legendTargetPort')]),
    el('span', {}, [el('i', { class: 'pm-sample pc' }),
      t('ippanel.legendComputerPort')]),
    el('span', {}, [el('i', { class: 'pm-sample link-port' }),
      t('ippanel.legendSwitchLink')]),
    el('span', {}, [el('i', { class: 'pm-sample feed' }),
      t('ippanel.legendPowering')]),
    el('span', {}, [el('i', { class: 'pm-sample link' }),
      t('ippanel.legendLinked')]),
    el('span', {}, [el('i', { class: 'pm-sample off' }),
      t('ippanel.legendPortDisabled')]),
    el('span', {}, [el('i', { class: 'pm-sample empty' }),
      t('ippanel.legendNoDevice')]),
  ]);
}

// The "x s ago" text in the heading refreshes every second; the screen does
// not need redrawing for that, the text is written directly.
export function writeFreshness() {
  if (!live.stack) return;
  for (const node of live.stack.querySelectorAll('[data-read-at]')) {
    const ts = Number(node.dataset.readAt);
    if (!ts) {
      node.textContent = 'unreadable';
      node.dataset.stale = '1';
      continue;
    }
    const seconds = Math.max(0, Math.round(Date.now() / 1000 - ts));
    node.textContent = `${seconds < 100 ? seconds : '99+'} s ago`;
    node.dataset.stale = seconds > 15 ? '1' : '0';
  }
}
