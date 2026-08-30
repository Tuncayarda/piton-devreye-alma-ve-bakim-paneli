// The "target group" — the shared picker at the top of the IP assignment,
// configuration and firmware screens.
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
