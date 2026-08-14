// The "target group" bar — the shared picker at the top of the IP assignment,
// configuration, firmware and checklist screens.
import { el } from '../core/dom.js';
import { state, patch } from '../core/store.js';
import { t } from '../core/i18n.js';

export function groupsFor(op) {
  const meta = state.meta;
  if (!meta) return [];
  return meta.groups.filter(g => g.ops.split(' ').includes(op));
}

export function devicesIn(group) {
  if (group.type === '*') {
    return state.devices.filter(d => d.type !== 'Switch');
  }
  return state.devices.filter(
    d => d.type === group.type
      && (!group.subtype || (d.subtype || '') === group.subtype));
}

// If the selected group is not valid for this operation, fall back to the
// first valid one.
export function currentGroup(op) {
  const list = groupsFor(op);
  if (!list.length) return null;
  return list.find(g => g.name === state.targetGroup) || list[0];
}

// On the operation screens the target is a single choice. A horizontal chip
// bar took up too much room and needed scrolling once the options grew; a
// compact dropdown shows the same scope more calmly and directly. Device
// counts are not added to the option name: the count is already visible in
// the operation's own table.
export function picker(op, onSelect = () => {}) {
  const list = groupsFor(op);
  const active = currentGroup(op);
  return el('label', { class: 'target-picker' }, [
    el('span', { class: 'label', text: t('groupbar.deviceType') }),
    el('select', {
      class: 'field',
      'aria-label': t('groupbar.targetDeviceType'),
      disabled: !list.length,
      onchange: (e) => {
        const group = list.find(g => g.name === e.target.value);
        if (!group) return;
        // The selection is done: focus leaves the list. Because a focused
        // list counts as open and holds the render back (see
        // app.focusInDropdown), without this the new group's fields never
        // reached the screen.
        e.target.blur();
        patch({ targetGroup: group.name });
        onSelect(group);
      },
    }, list.map(g => el('option', {
      value: g.name,
      selected: active && active.name === g.name ? true : null,
      text: g.label || g.name,
    }))),
  ]);
}

// When the bar does not fit, its right edge fades out (see the .chip-bar
// mask). At the end, or when everything fits, no fade is needed — and that
// can only be known by measuring.
function markEdge(container) {
  const update = () => {
    // The measurement is only meaningful once the element is in the page; it
    // is not attached yet where this is called.
    if (!container.isConnected) return;
    const atEnd = container.scrollLeft + container.clientWidth
      >= container.scrollWidth - 2;
    container.dataset.atEnd = atEnd ? '1' : '0';
  };
  container.addEventListener('scroll', update, { passive: true });
  // Not requestAnimationFrame: while the window is not painting (in the
  // background, minimised) it never runs and the bar stays faded forever.
  setTimeout(update, 0);
  return container;
}

// With `options.multi` the bar becomes a multi-select: the selected names are
// held by the calling screen (state.targetGroup carries a single name, so the
// other screens' behaviour is unchanged) and a click only goes to the
// callback.
export function render(op, onSelect = () => {}, options = {}) {
  const { multi = false, selected = null } = options;
  const list = groupsFor(op);
  const active = currentGroup(op);
  const isSelected = (g) => (multi
    ? !!selected && selected.includes(g.name)
    : !!active && active.name === g.name);
  return markEdge(el('div', {
    class: 'chip-bar', role: 'group',
    'aria-label': t(multi ? 'groupbar.targetGroups' : 'groupbar.targetGroup'),
  }, [
    el('span', {
      class: 'label',
      text: multi ? 'Target groups' : 'Target group',
    }),
    ...list.map(g => el('button', {
      type: 'button', class: 'chip',
      'aria-pressed': String(isSelected(g)),
      onclick: () => {
        if (!multi) patch({ targetGroup: g.name });
        onSelect(g);
      },
    }, [
      el('span', { text: g.label || g.name }),
      el('span', { class: 'count', text: String(devicesIn(g).length) }),
    ])),
  ]));
}
