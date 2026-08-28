// The port right-click menu.
//
// It exists because the faceplate is the fast way to work and a round trip to
// the table below is not: the operator has just selected ports 5 to 12 on the
// panel and wants their PoE off. Right-click puts that one decision under the
// cursor.
//
// TWO INDEPENDENT CHOICES, and neither is preselected. PoE mode and port
// on/off are separate rows, each starting at "leave unchanged", so opening
// the menu and pressing Apply without choosing anything is impossible —
// Apply stays disabled until something is actually chosen. A menu that
// defaulted to the current value would make "confirm what is already true"
// one click away from "change it".
//
// IT WRITES. Everything on this screen writes when it is asked to — the
// dropdowns and the on/off buttons in the table do (ports.js), and so does
// this. The menu itself is the review step: it names the ports, says how many
// are already in the state being chosen, and its Apply button is one deliberate
// click away from the right-click that opened it.

import { el, fill } from '../../core/dom.js';
import { t } from '../../core/i18n.js';
import { compactRange, local, portById } from './state.js';

const POE_KEEP = null;
let open = null;

export function isOpen() {
  return open !== null;
}

export function close() {
  if (!open) return;
  open.node.remove();
  document.removeEventListener('mousedown', open.onOutside, true);
  document.removeEventListener('keydown', open.onKey, true);
  open = null;
}

function row(label, selected, onPick, note) {
  return el('button', {
    type: 'button',
    class: `pm-menu-item${selected ? ' is-selected' : ''}`,
    onclick: onPick,
  }, [
    el('i', { class: 'pm-menu-mark', 'aria-hidden': 'true' }),
    el('span', { class: 'pm-menu-label', text: label }),
    note ? el('span', { class: 'pm-menu-state', text: note }) : null,
  ]);
}

// "3/8" when only some of the chosen ports are already in that state, and the
// word for "all of them" when every one is. The operator is about to change a
// block of ports and this is the only place that says how uniform it is.
function currentNote(ports, matches) {
  const applicable = ports.filter(port => port.applies);
  if (!applicable.length) return '';
  const count = applicable.filter(matches).length;
  if (count === 0) return '';
  return count === applicable.length
    ? t('switch.contextMenuCurrent')
    : `${count}/${applicable.length}`;
}

export function openMenu(portIds, event, actions, poeModes) {
  close();
  const ids = portIds.filter(id => portById(id));
  if (!ids.length) return;

  let poeChoice = POE_KEEP;
  let portChoice = POE_KEEP;
  const node = el('div', { class: 'pm-menu', role: 'menu' });

  const draw = () => {
    const ports = ids.map(id => portById(id)).filter(Boolean);
    if (!ports.length) { close(); return; }
    const many = ports.length > 1;
    const poePorts = ports.filter(port => port.supportsPoe);
    const linked = ports.filter(port => port.linkState === 'up').length;

    const parts = [];
    if (poePorts.length) {
      parts.push(el('div', {
        class: 'pm-menu-heading', text: t('switch.contextMenuPoeHeading'),
      }));
      parts.push(row(t('switch.contextMenuLeaveUnchanged'),
                     poeChoice === POE_KEEP,
                     () => { poeChoice = POE_KEEP; draw(); }));
      for (const mode of poeModes) {
        parts.push(row(
          t(mode.labelKey), poeChoice === mode.value,
          () => { poeChoice = mode.value; draw(); },
          currentNote(
            ports.map(port => ({ ...port, applies: port.supportsPoe })),
            port => String(port.poeMode) === String(mode.value))));
      }
    }
    parts.push(el('div', {
      class: 'pm-menu-heading', text: t('switch.contextMenuPortHeading'),
    }));
    parts.push(row(t('switch.contextMenuLeaveUnchanged'),
                   portChoice === POE_KEEP,
                   () => { portChoice = POE_KEEP; draw(); }));
    parts.push(row(
      t('switch.portTableEnabled'), portChoice === true,
      () => { portChoice = true; draw(); },
      currentNote(ports.map(port => ({ ...port, applies: true })),
                  port => !!port.enabled)));
    parts.push(row(
      t('switch.portTableDisabled'), portChoice === false,
      () => { portChoice = false; draw(); },
      currentNote(ports.map(port => ({ ...port, applies: true })),
                  port => !port.enabled)));

    const nothingChosen = poeChoice === POE_KEEP && portChoice === POE_KEEP;
    fill(node, [
      el('div', { class: 'pm-menu-head' }, [
        el('div', {
          class: 'pm-menu-title',
          text: many
            ? t('switch.contextMenuManyTitle', { count: ports.length })
            : t('switch.contextMenuOneTitle', { port: ports[0].id }),
        }),
        el('div', {
          class: 'pm-menu-subtitle',
          text: many
            ? t('switch.contextMenuManySummary', {
                ports: compactRange(ids), poe: poePorts.length,
                uplink: ports.length - poePorts.length, linked,
              })
            : t('switch.contextMenuOneSummary', {
                kind: t(ports[0].supportsPoe ? 'switch.contextMenuPoeType'
                  : 'switch.contextMenuUplinkType'),
                state: ports[0].linkState === 'up'
                  ? t('switch.stateLinked') : t('switch.stateEmpty'),
              }),
        }),
      ]),
      ...parts,
      el('p', { class: 'pm-menu-note', text: t('switch.contextMenuNote') }),
      el('div', { class: 'pm-menu-foot' }, [
        el('button', {
          type: 'button', class: 'btn btn-small',
          text: t('switch.cancel'), onclick: () => close(),
        }),
        el('button', {
          type: 'button', class: 'btn btn-primary btn-small',
          disabled: nothingChosen,
          text: many
            ? t('switch.contextMenuApplyMany', { count: ports.length })
            : t('switch.contextMenuApply'),
          onclick: () => {
            const targets = [...ids];
            close();
            actions.applyFromMenu(targets, poeChoice, portChoice);
          },
        }),
      ]),
    ]);
  };

  draw();
  document.body.append(node);

  // Kept on screen: a menu opened near the right edge or the bottom would
  // otherwise hang off it, and the Apply button is the part that goes first.
  const box = node.getBoundingClientRect();
  const left = Math.max(8, Math.min(event.clientX,
                                    globalThis.innerWidth - box.width - 8));
  const top = Math.max(8, Math.min(event.clientY,
                                   globalThis.innerHeight - box.height - 8));
  node.style.left = `${left}px`;
  node.style.top = `${top}px`;

  const onOutside = (e) => { if (!node.contains(e.target)) close(); };
  const onKey = (e) => {
    if (e.key !== 'Escape') return;
    // Stopped here, or Escape would also close whatever is behind the menu.
    e.stopPropagation();
    close();
  };
  open = { node, onOutside, onKey };
  // Registered on the next tick: the mousedown that opened this menu is
  // still travelling, and it would close it again immediately.
  globalThis.setTimeout(() => {
    document.addEventListener('mousedown', onOutside, true);
    document.addEventListener('keydown', onKey, true);
  });
}

// The menu shows live port state, so a poll that lands while it is open has
// to redraw it — otherwise it reports the switch as it was a minute ago.
export function refresh() {
  if (!open) return;
  const stillThere = local.ports.length > 0;
  if (!stillThere) close();
}
