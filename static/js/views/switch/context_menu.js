// The port right-click menu.
//
// It exists because the faceplate is the fast way to work and a round trip to
// the table below is not: the operator has just selected ports 5 to 12 on the
// panel and wants their PoE off. Right-click puts that one decision under the
// cursor.
//
// The menu SHELL — placing it, dismissing it, redrawing it while open — is
// components/context_menu.js and is shared with the device list. What is here
// is only what a port menu MEANS.
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

import { el } from '../../core/dom.js';
import { t } from '../../core/i18n.js';
import * as menu from '../../components/context_menu.js';
import { compactRange, local, portById } from './state.js';

const POE_KEEP = null;

export const isOpen = menu.isOpen;
export const close = menu.close;

// The menu shows live port state, so a poll that lands while it is open has
// to redraw it — otherwise it reports the switch as it was a minute ago.
export function refresh() {
  if (!local.ports.length) menu.close();
  else menu.refresh();
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
  const ids = portIds.filter(id => portById(id));
  if (!ids.length) return;

  let poeChoice = POE_KEEP;
  let portChoice = POE_KEEP;

  menu.openMenu(event, (redraw) => {
    const ports = ids.map(id => portById(id)).filter(Boolean);
    if (!ports.length) return null;            // the selection went away
    const many = ports.length > 1;
    const poePorts = ports.filter(port => port.supportsPoe);
    const linked = ports.filter(port => port.linkState === 'up').length;

    const rows = [];
    if (poePorts.length) {
      rows.push(menu.menuHeading(t('switch.contextMenuPoeHeading')));
      rows.push(menu.menuItem(t('switch.contextMenuLeaveUnchanged'), {
        selected: poeChoice === POE_KEEP,
        onPick: () => { poeChoice = POE_KEEP; redraw(); },
      }));
      for (const mode of poeModes) {
        rows.push(menu.menuItem(t(mode.labelKey), {
          selected: poeChoice === mode.value,
          onPick: () => { poeChoice = mode.value; redraw(); },
          note: currentNote(
            ports.map(port => ({ ...port, applies: port.supportsPoe })),
            port => String(port.poeMode) === String(mode.value)),
        }));
      }
    }
    rows.push(menu.menuHeading(t('switch.contextMenuPortHeading')));
    rows.push(menu.menuItem(t('switch.contextMenuLeaveUnchanged'), {
      selected: portChoice === POE_KEEP,
      onPick: () => { portChoice = POE_KEEP; redraw(); },
    }));
    rows.push(menu.menuItem(t('switch.portTableEnabled'), {
      selected: portChoice === true,
      onPick: () => { portChoice = true; redraw(); },
      note: currentNote(ports.map(port => ({ ...port, applies: true })),
                        port => !!port.enabled),
    }));
    rows.push(menu.menuItem(t('switch.portTableDisabled'), {
      selected: portChoice === false,
      onPick: () => { portChoice = false; redraw(); },
      note: currentNote(ports.map(port => ({ ...port, applies: true })),
                        port => !port.enabled),
    }));

    const nothingChosen = poeChoice === POE_KEEP && portChoice === POE_KEEP;
    return [
      menu.menuHead(
        many ? t('switch.contextMenuManyTitle', { count: ports.length })
          : t('switch.contextMenuOneTitle', { port: ports[0].id }),
        many
          ? t('switch.contextMenuManySummary', {
            ports: compactRange(ids), poe: poePorts.length,
            uplink: ports.length - poePorts.length, linked,
          })
          : t('switch.contextMenuOneSummary', {
            kind: t(ports[0].supportsPoe ? 'switch.contextMenuPoeType'
              : 'switch.contextMenuUplinkType'),
            state: ports[0].linkState === 'up'
              ? t('switch.stateLinked') : t('switch.stateEmpty'),
          })),
      ...rows,
      menu.menuFoot([
        el('button', {
          type: 'button', class: 'btn btn-small',
          text: t('switch.cancel'), onclick: () => menu.close(),
        }),
        el('button', {
          type: 'button', class: 'btn btn-primary btn-small',
          disabled: nothingChosen,
          text: many
            ? t('switch.contextMenuApplyMany', { count: ports.length })
            : t('switch.contextMenuApply'),
          onclick: () => {
            const targets = [...ids];
            menu.close();
            actions.applyFromMenu(targets, poeChoice, portChoice);
          },
        }),
      ]),
    ];
  });
}
