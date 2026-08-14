// The main menu: a narrow icon rail to the left of the content.
//
// The menu started as a 250 pixel column: for five rows it permanently took a
// sixth of the screen. A popover from the corner was tried next; it took no
// room but was hard to find and to use — switching area meant finding the
// button, opening it and waiting for it to unfold.
//
// The rail is the middle ground: 56 pixels, always on screen, one click to
// switch. Area names appear in a bubble beside the icon on hover; whoever
// wants the names permanently widens the rail with the button at the bottom
// (that preference lives in `state.sidebarOpen` and survives the session).
//
// Device categories are not separate targets here. The filters on the devices
// screen do the same job without losing context. The IP, device settings and
// software screens are views of a single "Operations" area too; the menu does
// not behave like a process step and the user can move between those screens
// in any order.

import { el, fill, icon, $ } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { state, patch } from '../core/store.js';

const OPERATION_VIEWS = new Set(['ip', 'config', 'firmware']);

const MAIN_AREAS = [
  {
    labelKey: 'nav.overview', view: 'overview',
    active: v => v === 'overview',
    icon: ['M3 10.5L10 4l7 6.5', 'M5.5 9.5V16h9V9.5'],
  },
  {
    labelKey: 'nav.devices', view: 'devices',
    active: v => v === 'devices',
    icon: ['M4 4.5h12v4H4z', 'M4 11.5h12v4H4z', 'M6.5 6.5h.01M6.5 13.5h.01'],
    patchState: { category: 'all', subtype: null, filter: 'all' },
  },
  {
    labelKey: 'nav.operations', view: 'ip',
    active: v => OPERATION_VIEWS.has(v),
    icon: ['M5 5h10v10H5z', 'M8 8h4M10 6v4'],
  },
  {
    labelKey: 'nav.verification', view: 'checklist',
    active: v => v === 'checklist',
    icon: ['M6 3.5h8v13H6z', 'M8 7h4M8 10h4M8 13h2.5'],
  },
  {
    labelKey: 'nav.history', view: 'history',
    active: v => v === 'history',
    icon: ['M10 4a6 6 0 1 1-5.2 3', 'M3.5 4.5v3h3', 'M10 7v3.5l2.5 1.5'],
  },
];

const ADMIN_AREAS = [
  {
    labelKey: 'nav.piscu', view: 'piscu', admin: true,
    icon: ['M4 6h12v8H4z', 'M7 9h6M7 11.5h3'],
  },
  {
    labelKey: 'nav.mqtt', view: 'mqtt', admin: true,
    icon: ['M4 14a6 6 0 0 1 6-6', 'M4 14a10 10 0 0 1 10-10', 'M4.5 14h.01'],
  },
  {
    labelKey: 'nav.project', view: 'admin', admin: true,
    icon: ['M5 4.5h10v11H5z', 'M7.5 8h5M7.5 11h5'],
  },
];

function areas() {
  return state.role === 'admin'
    ? [...MAIN_AREAS, ...ADMIN_AREAS] : MAIN_AREAS;
}

function isSelected(area) {
  return area.active ? area.active(state.view) : state.view === area.view;
}

// The rail is not rebuilt on every state change. While a scan runs the render
// arrives once a second; recreating the buttons every round reopened the name
// bubble under the cursor from scratch each time (flicker). The structure is
// built once and only the selected marker is updated afterwards.
let built = null;

function menuButton(area) {
  return el('button', {
    type: 'button', class: 'sidebar-item',
    dataset: { admin: area.admin ? '1' : '0' },
    // The name shows as a bubble on the narrow rail; this is also the
    // button's own label for a screen reader.
    'aria-label': t(area.labelKey),
    onclick: () => patch({
      view: area.view,
      ...(area.patchState || {}),
    }),
  }, [
    el('span', { class: 'sidebar-icon' }, [icon(area.icon, 17)]),
    el('span', { class: 'sidebar-name', text: t(area.labelKey) }),
  ]);
}

function build(root) {
  const list = areas();
  const buttons = list.map(menuButton);
  // The admin tools are not part of the field flow; the divider shows that
  // on the narrow rail too.
  const content = [];
  list.forEach((area, i) => {
    if (area.admin && !list[i - 1].admin) {
      content.push(el('span', {
        class: 'sidebar-divider', 'aria-hidden': 'true',
      }));
    }
    content.push(buttons[i]);
  });

  const expandIcon = el('span', { class: 'sidebar-expand-icon' }, [
    icon(['M7.5 5.5L12 10l-4.5 4.5'], 15),
  ]);
  const expand = el('button', {
    type: 'button', class: 'sidebar-expand',
    onclick: () => patch({ sidebarOpen: !state.sidebarOpen }),
  }, [expandIcon]);

  fill(root, [
    el('nav', {
      class: 'sidebar-list', 'aria-label': t('nav.mainAreas'),
    }, content),
    expand,
  ]);
  built = { role: state.role, list, buttons, expand };
}

// Drop the cached structure so the next render rebuilds it — the labels are
// baked into the buttons, so a language switch has to start over.
export function reset() {
  built = null;
}

export function render() {
  const root = $('#sidebar');
  if (!root || !state.meta) return;

  if (!built || built.role !== state.role || !root.firstChild) build(root);

  const wide = !!state.sidebarOpen;
  root.dataset.wide = wide ? '1' : '0';
  built.expand.setAttribute('aria-expanded', String(wide));
  built.expand.setAttribute(
    'aria-label', wide ? t('nav.collapse') : t('nav.expand'));
  built.expand.title = wide ? t('nav.collapse') : t('nav.showNames');

  built.list.forEach((area, i) => {
    const button = built.buttons[i];
    if (isSelected(area)) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
}
