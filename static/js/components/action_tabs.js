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

/**
 * The tab row, with the open screen's own top-level controls on its right.
 *
 * `actions` is what that screen puts there — its device-type picker, its
 * primary button. They used to sit on two rows of their own above this one,
 * under an `h2` reading "Operations" that all three screens shared: a word
 * the menu rail already says, that the hidden `h1` does not say (it is named
 * by the TAB — see app.js VIEW_NAME), and that therefore named nothing on
 * any of the three. Two rows and a heading came to some ninety pixels at the
 * top of every operation screen, which on the IP screen is the difference
 * between seeing the Start button in the first screenful and not.
 */
export function render(actions = []) {
  const extras = [].concat(actions).filter(Boolean);
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
    extras.length ? el('div', { class: 'action-tab-actions' }, extras) : null,
  ]);
}
