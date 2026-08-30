// The switch faceplate, interactive.
//
// The drawing and the layout come from `components/front_panel.js`, which the
// IP assignment screen uses too — one faceplate, so the same switch looks the
// same in both places (the reasoning is written at the top of that file).
// What this file adds is what only this screen has: ports are SELECTABLE, and
// a selection is what the PoE and enable/disable actions apply to.
//
// The colour classes are the ones `ip.css` already defines for `.pm-port`, so
// "powering", "linked", "disabled" and "up but unpowered" read identically on
// both screens.

import { el } from '../../core/dom.js';
import { connectorSvg, portGrid } from '../../components/front_panel.js';
import { t } from '../../core/i18n.js';
import {
  clearSelection, local, poePorts, portById, selectAllPorts,
  compactRange, uplinkPorts,
} from './state.js';

// A port's live state, as the class that colours its connector. Same
// distinctions as `views/ip/panel.js:liveClass` — deliberately, because the
// two panels must not disagree about what green means.
export function liveClass(port) {
  if (!port.enabled) return 'off';
  const powering = port.supportsPoe && port.linkState === 'up'
    && Number(port.powerWatts);
  let className = powering ? 'feed' : port.linkState === 'up' ? 'link' : '';
  // Up, but PoE switched off: the line works and there is no power.
  if (port.supportsPoe && String(port.poeMode) === '0') {
    className += ' unpowered';
  }
  return className.trim();
}

function stateText(port) {
  if (!port.enabled) return t('switch.statePortDisabled');
  if (port.supportsPoe && String(port.poeMode) === '0') {
    return t('switch.statePowerOff');
  }
  if (port.linkState !== 'up') return t('switch.stateEmpty');
  return port.powerWatts
    ? t('switch.statePowering', { watts: port.powerWatts })
    : t('switch.stateLinked');
}

function connector(port, actions) {
  const chosen = local.selected.has(port.id);
  const roles = [liveClass(port)];
  if (chosen) roles.push('selected');
  const description = t('switch.portDescription', {
    port: port.id, state: stateText(port),
  });
  return el('button', {
    type: 'button', class: `pm-port ${roles.join(' ')}`.trim(),
    'aria-pressed': String(chosen),
    'aria-label': description,
    title: description,
    dataset: { portId: port.id },
    onclick: (event) => actions.clickPort(port.id, event),
    oncontextmenu: (event) => actions.contextPort(port.id, event),
  }, [
    connectorSvg(port.supportsPoe),
    el('span', { text: String(port.id) }),
  ]);
}

// THE SWITCH'S IDENTITY LIVES IN THIS CARD'S HEAD, and it used to have a
// card of its own. That card held a name, an address and two badges and
// nothing else — a box the width of the screen for one line of text, sitting
// between the switch list and the faceplate. It belongs here: the faceplate
// is what the operator looks at to see which switch they are working on, and
// the name above it answers the same question.
function identity(info, ip) {
  return el('div', { class: 'switch-identity' }, [
    el('h3', { text: (info && info.name) || t('switch.headUnopened') }),
    el('span', { class: 'mono', text: ip }),
  ]);
}


export function frontPanelCard(actions, ip, busy) {
  const poe = poePorts();
  const uplink = uplinkPorts();
  const info = local.info;
  // Nothing is open: the switch list is the whole screen.
  if (!ip) return null;

  const head = el('div', { class: 'card-head' }, [
    identity(info, ip),
    el('span', { class: 'spacer' }),
    info && info.model ? el('span', { class: 'badge', text: info.model })
      : null,
    info && info.version ? el('span', { class: 'badge', text: info.version })
      : null,
    busy ? el('span', { class: 'label', text: t('switch.busy') }) : null,
    ...(local.ports.length ? counters() : []),
  ]);

  // Opened but not read yet — signing in, or the read failed. The card stays
  // so the name does not blink out from under the operator.
  if (!local.ports.length) {
    return el('section', { class: 'card corner switch-panel' }, [
      head,
      el('p', {
        class: 'description',
        text: local.loadingPorts ? t('switch.loadingPorts')
          : t('switch.portsNone'),
      }),
    ]);
  }

  const grid = portGrid({
    poeCount: poe.length,
    uplinkCount: uplink.length,
    // This screen shows one switch across the full width, so the faceplate
    // gets the room: at the IP screen's compact size it sat in the middle of
    // all that space looking like a thumbnail.
    size: 'large',
    cell: (number) => {
      const port = portById(number);
      return port ? connector(port, actions) : null;
    },
  });

  return el('section', { class: 'card corner switch-panel' }, [
    head,
    el('div', { class: 'pm-case' }, [
      el('div', { class: 'pm-wrap' }, [grid]),
      el('div', { class: 'pm-footer' }, [
        el('span', { text: t('switch.poeRange', { count: poe.length }) }),
        el('span', { class: 'grow' }),
        uplink.length
          ? el('span', {
              text: t('switch.uplinkRange', {
                first: poe.length + 1, last: poe.length + uplink.length,
              }),
            })
          : null,
      ]),
    ]),
    selectionBar(actions),
    legend(),
  ]);
}

function counters() {
  const ports = local.ports;
  const linked = ports.filter(port => port.linkState === 'up').length;
  const feeding = ports.filter(port => Number(port.powerWatts)).length;
  const powerOff = ports.filter(
    port => port.supportsPoe && String(port.poeMode) === '0').length;
  const items = [
    [ports.length, t('switch.counterPorts'), ''],
    [linked, t('switch.counterLinked'), 'link'],
    [feeding, t('switch.counterFeeding'), 'feed'],
  ];
  if (powerOff) items.push([powerOff, t('switch.counterPowerOff'), 'nopwr']);
  return items.map(([count, label, className]) => el('span', {
    class: `stat ${className}`.trim(),
  }, [el('b', { text: String(count) }), label]));
}

// What is selected, and the way out of a selection. The hint names the
// modifier for THIS machine: telling a Mac operator to hold Ctrl is worse
// than saying nothing.
function selectionBar(actions) {
  const count = local.selected.size;
  return el('div', {
    class: 'switch-selection', dataset: { empty: count ? '0' : '1' },
  }, [
    el('span', {
      class: 'switch-selection-info',
      text: count === 0 ? '' : t('switch.selectionSummary', {
        count, ports: compactRange(local.selected),
      }),
    }),
    el('span', { class: 'spacer' }),
    el('button', {
      type: 'button', class: 'btn btn-small',
      text: t('switch.buttonSelectAll'),
      onclick: () => { selectAllPorts(); actions.redraw(); },
    }),
    el('button', {
      type: 'button', class: 'btn btn-small', disabled: count === 0,
      text: t('switch.buttonClearSelection'),
      onclick: () => { clearSelection(); actions.redraw(); },
    }),
  ]);
}

// One entry per appearance the faceplate can actually produce. It used to
// name four while `liveClass` drew six: a port that is up with nothing plugged
// into it (no class at all — the plain connector) and one that is linked with
// its PoE switched off (red pins, `.unpowered`) both sat on the panel with
// nothing to say what they were. The sibling application listed both; they
// were lost on the way across and "Selected" was added in their place.
const LEGEND = [
  ['feed', 'switch.legendPowering'],
  ['link', 'switch.legendLinked'],
  // The plain connector: no modifier, because that is exactly how a port with
  // nothing in it is drawn.
  ['', 'switch.legendEmpty'],
  ['nopwr', 'switch.legendPowerOff'],
  ['off', 'switch.legendPortDisabled'],
  ['selected', 'switch.legendSelected'],
];

function legend() {
  return el('div', { class: 'panel-legend' }, LEGEND.map(([kind, key]) =>
    el('span', {}, [
      el('i', { class: kind ? `pm-sample ${kind}` : 'pm-sample' }),
      t(key),
    ])));
}
