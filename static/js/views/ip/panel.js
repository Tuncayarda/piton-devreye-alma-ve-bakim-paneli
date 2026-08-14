// The switch front panel.
//
// The panel draws the switch's real face: PoE ports column by column bottom to
// top (1-2-3-4 | 5-6-7-8 …), with the uplink column separated by a dashed line
// on the right. The layout matches the Switch Management Panel in the sibling
// project; whoever looks at the same switch in both sees the same arrangement.
//
// The connector drawing matches that project too: a PoE port has 4 pins, an
// uplink 8 with a cross in the middle. The port box looking the same in both
// panels means finding a port without counting.

import { el } from '../../core/dom.js';
import { state } from '../../core/store.js';
import { credentialDialog } from '../../components/locked.js';
import { notify } from '../../components/toast.js';
import { local, live } from './state.js';
import { t } from '../../core/i18n.js';

function pinRing(count, radius) {
  return Array.from({ length: count }, (_, i) => {
    const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
    return [20 + radius * Math.cos(angle), 20 + radius * Math.sin(angle)];
  });
}

function connectorSvg(poe) {
  const pins = pinRing(poe ? 4 : 8, poe ? 6.6 : 7.2);
  const radius = poe ? 2.5 : 1.9;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 40 40');
  svg.setAttribute('aria-hidden', 'true');
  const add = (tag, attributes) => {
    const node = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attributes)) {
      node.setAttribute(key, String(value));
    }
    svg.append(node);
  };
  add('circle', { class: 'shell', cx: 20, cy: 20, r: 18.4 });
  add('circle', { class: 'inner', cx: 20, cy: 20, r: 12.2 });
  if (!poe) add('path', { class: 'cross', d: 'M13 13 L27 27 M27 13 L13 27' });
  add('rect', { class: 'key', x: 18.6, y: 1.6, width: 2.8, height: 4.2 });
  for (const [x, y] of pins) {
    add('circle', { class: 'pin', cx: x.toFixed(2), cy: y.toFixed(2), r: radius });
  }
  return svg;
}

function emptyCell(className) {
  return el('div', { class: className || 'pm-empty' });
}

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

// A single connector. The colour shows the port's current state, the border
// its role in the run: target ports are marked with a blue border. Folding
// both into one colour confused "is this port up" with "is it selected".
function portButton(port, context) {
  const roles = [liveClass(port)];
  const protectedReason = context.protectedPorts.get(port.number);
  if (port.number === context.computerPort) roles.push('pc');
  else if (protectedReason) roles.push('link-port');
  else if (context.targets.has(port.number)) roles.push('selected');
  if (!port.defined) roles.push('empty');

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
    : t(port.defined ? 'ippanel.portDevice' : 'ippanel.portUndefined', {
      port: port.number, device: port.device, state: stateText,
    })
      + (context.active ? ''
        : t('ippanel.switchesTo', { switch: context.switchName }));
  return el('button', {
    type: 'button', class: `pm-port ${roles.join(' ')}`.trim(),
    'aria-pressed': String(context.targets.has(port.number)),
    'aria-label': description,
    'aria-disabled': String(!port.defined || locked),
    disabled: !port.defined,
    title: description,
    onclick: locked ? null : () => context.onPortClick(port.number, context),
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
  const info = (plan.switches || []).find(s => s.id === panel.switchId);
  const groupDevices = info ? info.groupDevices : null;
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
    onPortClick: handlers.onPortClick,
  };

  const byNumber = {};
  for (const port of panel.ports) byNumber[port.number] = port;
  const poeCount = panel.poeCount || 24;
  const uplinkCount = panel.uplinkCount || 4;
  const columns = Math.max(1, Math.ceil(poeCount / 4));

  const grid = el('div', {
    class: 'pm-grid',
    style: `--pm-columns:${columns}`,
  });
  // Physical layout: 4 rows, PoE columns numbered bottom to top, the uplink
  // column on the far right (top to bottom).
  for (let row = 4; row >= 1; row -= 1) {
    for (let column = 0; column < columns; column += 1) {
      const port = byNumber[row + column * 4];
      grid.append(port ? portButton(port, context) : emptyCell());
    }
    grid.append(emptyCell('pm-divider'));
    // The uplink column is numbered top to bottom (28…25) — the same
    // arrangement as the sibling panel.
    const uplink = row <= uplinkCount ? byNumber[poeCount + row] : null;
    grid.append(uplink ? portButton(uplink, context) : emptyCell());
  }

  const guidance = t(groupDevices === 0 ? 'ippanel.noTargetOnSwitch'
    : 'ippanel.clickDefinedPort');

  return el('article', {
    class: 'card corner front-panel', dataset: { active: active ? '1' : '0' },
  }, [
    el('header', { class: 'ip-switch-head' }, [
      el('div', { class: 'ip-switch-identity' }, [
        el('div', { class: 'ip-switch-name' }, [
          el('i', { 'aria-hidden': 'true' }),
          el('h4', { text: panel.switchName || 'Switch' }),
        ]),
        el('span', { class: 'mono', text: panel.switchIp }),
      ]),
      el('div', { class: 'ip-switch-badges' }, [
        // How fresh the data is: with a live read, how many seconds ago it
        // was taken refreshes every second (see writeFreshness).
        panel.source === 'switch' ? el('span', {
          class: 'ip-freshness', dataset: { readAt: panel.readAt || 0 },
          title: t('ippanel.whenThePortStatesWere'),
          text: t('ippanel.sAgo'),
        }) : null,
        el('span', {
          class: panel.source === 'switch'
            ? 'badge ip-source-badge live' : 'badge ip-source-badge',
          text: t(panel.source === 'switch' ? 'ippanel.liveData'
            : 'ippanel.projectDefault'),
          title: t(panel.source === 'switch' ? 'ippanel.readFromSwitch'
            : 'ippanel.readFromDeviceMap'),
        }),
        // Without credentials the run cannot start; this must also be where
        // they are entered.
        panel.hasCredentials === false ? el('button', {
          type: 'button', class: 'btn btn-small ip-credential-btn',
          text: t('detail.enterCredentials'),
          title: t('ippanel.enterCredentialsFor',
                        { switch: panel.switchName }),
          onclick: () => askSwitchCredentials(panel, handlers.onCredentials),
        }) : null,
      ]),
    ]),
    active ? null : el('p', { class: 'ip-switch-guidance', text: guidance }),
    // Why the panel could not be read stays as a single line; a separate box
    // per switch showed the same sentence twice on two switches.
    panel.note
      ? el('p', { class: 'ip-panel-note', text: panel.note })
      : null,
    // The warning only on the active switch: that is where the run will go.
    // On another switch a missing credential is not an obstacle, the "enter
    // credentials" button is enough.
    active && panel.hasCredentials === false
      ? el('p', {
          class: 'ip-panel-note warning-tone',
          text: t('ippanel.ipAssignmentCannotStartWithout'),
        })
      : null,
    el('div', { class: 'pm-case' }, [
      el('div', { class: 'pm-wrap' }, [grid]),
      el('div', { class: 'pm-footer' }, [
        el('span', { text: t('ippanel.poeRange', { count: poeCount }) }),
        el('span', { style: 'flex:1' }),
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
