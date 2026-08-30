// The port tables: one for the PoE block, one for the uplinks.
//
// PoE and uplink ports are separated because they answer different questions.
// A PoE port has a power mode and a wattage; an uplink has neither, and a
// column of dashes down four rows is worse than two tables.
//
// THE TWO TABLES SHARE ONE COLUMN TEMPLATE. The uplink table used to have
// four columns of its own, so its state button landed at a different x than
// the PoE table's directly above it — two buttons that do exactly the same
// thing, refusing to line up. The uplink table now uses the same six-column
// template with the last two cells empty.
//
// A CHANGE GOES TO THE SWITCH WHEN IT IS MADE. There is no staging step and
// no apply bar: this screen exists to turn a port off, and putting a second
// click between the operator and that is the wrong trade. Several ports at
// once is what the right-click menu is for (context_menu.js), which sends
// them as one batch.

import { el } from '../../core/dom.js';
import { dataTable } from '../../components/table.js';
import { t } from '../../core/i18n.js';
import { local, poeModes, poePorts, uplinkPorts } from './state.js';

// One template, both tables. The last two columns carry PoE and power, which
// an uplink has not got — its rows leave them empty rather than reflow.
const COLUMNS = '58px 110px minmax(120px,1fr) 96px 118px 84px';

// The dot beside the word. It asks the SAME questions in the SAME order as
// `front_panel.js:liveClass`, because the two are read side by side: a grey
// connector above a row saying "Linked" is the panel arguing with itself.
//
// The states are the panel's own (components.css, `[data-state]`), not this
// screen's. The sibling application coloured these dots with class names of
// its own — `.dot.up`, `.dot.data` — and those rules never came across, so
// every dot fell back to `.dot`'s plain grey whatever the port was doing.
function dotState(port) {
  if (!port.enabled) return 'failed';
  if (Number(port.powerWatts)) return 'ok';
  return port.linkState === 'up' ? 'link' : 'unknown';
}

function linkDot(port) {
  return el('span', { class: 'dot', dataset: { state: dotState(port) } });
}

// "1000M · Full". The switch's own `linktext` when it sent one, because it
// knows things the raw speed does not; the negotiated numbers otherwise.
function speedText(port) {
  if (port.linkState !== 'up') return '—';
  const raw = String(port.linkLabel || '').trim();
  if (raw) return raw;
  const speed = port.speed ? `${port.speed}M` : '—';
  return port.fullDuplex ? `${speed} · ${t('switch.portTableFull')}` : speed;
}

function stateButton(port, actions, busy) {
  const on = !!port.enabled;
  return el('button', {
    type: 'button',
    class: `pill ${on ? 'on' : 'off'}`,
    disabled: busy,
    title: t(on ? 'switch.portTableDisablePort' : 'switch.portTableEnablePort'),
    text: t(on ? 'switch.portTableEnabled' : 'switch.portTableDisabled'),
    onclick: () => actions.setPortEnabled(port.id, !on),
  });
}

function poeSelect(port, actions, busy) {
  const current = String(port.poeMode);
  return el('select', {
    // Only "off" is marked; every other mode is the ordinary look, so there
    // is no `on` class to go with it (there was one, and nothing styled it).
    class: current === '0' ? 'poe off' : 'poe',
    disabled: busy,
    title: t('switch.portTablePoeTitle'),
    'aria-label': t('switch.portTablePoeFor', { port: port.id }),
    onchange: (event) => actions.setPoe(port.id, event.target.value),
  }, poeModes().map(mode => el('option', {
    value: mode.value, selected: mode.value === current,
    text: t(mode.labelKey),
  })));
}

function portRow(port, actions, busy) {
  const poe = port.supportsPoe;
  return el('div', {
    class: 'table-row switch-port-row',
    'aria-selected': String(local.selected.has(port.id)),
    dataset: { portId: port.id },
    style: `--table-columns:${COLUMNS}`,
    onclick: (event) => {
      // A click on a control is that control's; only a click on the row
      // itself changes the selection.
      if (event.target.closest('button, select, input, a')) return;
      actions.clickPort(port.id, event);
    },
    oncontextmenu: (event) => actions.contextPort(port.id, event),
  }, [
    el('span', { class: 'mono', text: String(port.id) }),
    // The dot and the word are one line, not two. `.dot` is a block, so a
    // bare span put the word underneath the square and the whole column read
    // as a ragged second row.
    el('span', { class: 'switch-link-cell' }, [
      linkDot(port),
      port.linkState === 'up'
        ? el('span', { text: t('switch.portTableLinked') })
        : el('span', { class: 'muted', text: '—' }),
    ]),
    el('span', { class: 'mono truncate', text: speedText(port) }),
    stateButton(port, actions, busy),
    // The two an uplink has not got. Kept as cells so the columns above and
    // below them stay in one grid.
    poe ? poeSelect(port, actions, busy) : el('span', { class: 'muted' }),
    poe
      ? el('span', {
          class: 'mono',
          text: port.powerWatts ? `${port.powerWatts} W` : '—',
        })
      : el('span', { class: 'muted' }),
  ]);
}

function table(ports, actions, busy, titleKey) {
  const label = t(titleKey, { count: ports.length });
  return el('div', { class: 'switch-table-block' }, [
    el('h4', { text: label }),
    dataTable({
      // The floor is the sum of the column minimums, the gaps between them
      // and the row's own padding — below it the grid cannot shrink any
      // further and spills past the row's right border instead. It was
      // thirty pixels under it.
      template: COLUMNS, minWidth: 660, label,
      columns: [t('switch.columnPort'), t('switch.columnLink'),
                t('switch.columnSpeed'), t('switch.columnState'),
                t('switch.columnPoe'), t('switch.columnPower')],
      rows: ports.map(port => portRow(port, actions, busy)),
      empty: t('switch.portsNone'),
    }),
  ]);
}

export function portsCard(actions, busy) {
  if (!local.ports.length) return null;
  const poe = poePorts();
  const uplink = uplinkPorts();

  return el('section', { class: 'card corner switch-ports' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('switch.portsTitle') }),
      el('span', { class: 'spacer' }),
      el('span', {
        class: 'label',
        text: t('switch.portsCount', { count: local.ports.length }),
      }),
    ]),
    poe.length ? table(poe, actions, busy, 'switch.portsPoeSection') : null,
    uplink.length
      ? table(uplink, actions, busy, 'switch.portsUplinkSection')
      : null,
  ]);
}
