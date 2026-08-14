// The shared local navigation between the operation screens.
//
// This bar is not a progress indicator: during maintenance the user moves
// between the network, device settings and software screens in any order. The
// screen choice is driven by the application's current `view` state.

import { el } from '../core/dom.js';
import { state, patch } from '../core/store.js';
import { t } from '../core/i18n.js';

// The KEY is stored, not the text: this table is built when the module
// loads, which is before the catalogue has arrived, so a resolved label here
// would freeze as the key and never change with the language.
const TABS = [
  { id: 'ip', labelKey: 'tabs.networkAndIp' },
  { id: 'config', labelKey: 'tabs.deviceSettings' },
  { id: 'firmware', labelKey: 'tabs.firmware' },
];

export function render() {
  return el('nav', {
    class: 'action-tabs',
    'aria-label': t('tabs.operationAreas'),
  }, [
    el('div', { class: 'action-tab-list' }, TABS.map(tab => {
      const active = state.view === tab.id;
      return el('button', {
        type: 'button',
        class: `action-tab${active ? ' active' : ''}`,
        dataset: { active: active ? '1' : '0', view: tab.id },
        'aria-current': active ? 'page' : null,
        text: t(tab.labelKey),
        onclick: active ? null : () => patch({ view: tab.id }),
      });
    })),
  ]);
}
