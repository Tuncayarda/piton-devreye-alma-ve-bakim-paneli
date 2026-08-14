// Project & device list (admin).
//
// A device username/password CANNOT be saved on this screen. The "save
// credentials to a file" / "password stored" fields of older panels are
// deliberately absent; the only thing possible here is forgetting what is in
// memory.

import { el, fill } from '../core/dom.js';
import { api } from '../core/api.js';
import { state } from '../core/store.js';
import { showSuccess, showError } from '../components/toast.js';
import { value } from '../core/format.js';
import { t } from '../core/i18n.js';

const COLUMNS = 'minmax(140px,1.3fr) minmax(120px,1fr) 76px 110px 96px';

// In the field the set number does not come from a fixed list (49 and 112
// exist too); instead of a grid of ready-made buttons there is a typed field.
// The server reports the range, because the server does the validation.
function setBox(meta, changeSet) {
  const min = meta.setMin || 1;
  const max = meta.setMax || 254;

  const field = el('input', {
    class: 'field', type: 'number', inputmode: 'numeric',
    min: String(min), max: String(max), step: '1',
    autocomplete: 'off', style: 'width:90px;text-align:center',
    value: String(state.setNo), 'aria-label': t('admin.trainSetNumber'),
  });

  const apply = () => {
    const next = Number(field.value.trim());
    if (!Number.isInteger(next) || next < min || next > max) {
      showError(t('topbar.setOutOfRange', { min, max }));
      field.value = String(state.setNo);
      return;
    }
    if (next !== state.setNo) changeSet(next);
  };
  field.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); apply(); }
  });

  return el('div', { style: 'margin-top:12px' }, [
    el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
      field,
      el('button', {
        type: 'button', class: 'btn', text: t('admin.apply'), onclick: apply,
      }),
    ]),
    el('p', {
      class: 'mono text-dim',
      style: 'margin-top:9px;font-size:10.5px;line-height:1.6',
      text: t('admin.validRange', { min, max }),
    }),
  ]);
}

export function render(root, changeSet) {
  const meta = state.meta;
  if (!meta) return;
  const parts = [];

  parts.push(el('div', { class: 'page-head' }, [
    el('div', {}, [el('h2', { text: t('admin.projectDeviceList') })]),
  ]));

  parts.push(el('div', { class: 'project-grid' }, [
    el('div', { class: 'card corner' }, [
      el('div', { style: 'display:flex;align-items:center;gap:9px' }, [
        el('span', {
          class: 'dot', style: 'background:var(--ok)', 'aria-hidden': 'true',
        }),
        el('span', {
          style: 'font-family:var(--font-heading);font-weight:600;'
            + 'font-size:18px;letter-spacing:.06em;text-transform:uppercase',
          text: meta.project,
        }),
        el('span', {
          style: 'margin-left:auto', class: 'label', text: t('admin.loaded'),
        }),
      ]),
      el('div', {
        class: 'mono text-mid',
        style: 'margin-top:9px;font-size:10.5px;line-height:1.7',
      }, [
        el('div', { text: meta.file }),
        el('div', {
        text: t('admin.piscuBroker', { ip: value(meta.piscuIp) }),
      }),
      ]),
    ]),
    el('div', { class: 'card corner' }, [
      el('h4', { text: t('admin.credentials') }),
      el('p', {
        class: 'mono text-mid',
        style: 'margin-top:9px;font-size:10.5px;line-height:1.7',
        text: t('admin.deviceUsernamesAndPasswordsAre'),
      }),
      el('button', {
        type: 'button', class: 'btn btn-danger', style: 'margin-top:12px',
        text: t('admin.forgetCredentials'),
        onclick: async () => {
          try {
            await api.forgetAllCredentials();
            showSuccess(t('admin.everyCredentialInMemoryWas'));
          } catch (e) { showError(e.message); }
        },
      }),
    ]),
    el('div', { class: 'card corner' }, [
      el('h4', { text: t('admin.trainSetN') }),
      setBox(meta, changeSet),
    ]),
  ]));

  parts.push(el('div', { class: 'admin-grid' }, [
    el('div', { class: 'card' }, [
      el('div', { class: 'card-head' }, [
        el('h4', { text: t('admin.devicePortMapping') }),
        el('span', { class: 'label', text: t('admin.switchPortIpTemplate') }),
      ]),
      el('div', { class: 'table-wrap', style: 'margin-top:0' }, [
        el('div', { class: 'table', style: '--table-min:600px' }, [
          el('div', {
            class: 'table-head', style: `--table-columns:${COLUMNS}`,
          }, ['col.name', 'col.typeSubtype', 'col.port', 'col.ipTemplate',
              'col.pbxExtension']
            .map(key => el('span', { text: key ? t(key) : '' }))),
          ...state.devices.map(device => el('div', {
            class: 'table-row', style: `--table-columns:${COLUMNS}`,
          }, [
            el('span', {
              class: 'mono truncate', style: 'font-size:11px',
              text: device.name,
            }),
            el('span', {
              class: 'mono text-bright truncate', style: 'font-size:11px',
              text: device.typeLabel,
            }),
            el('span', {
              class: 'mono', style: 'font-size:11px;color:var(--auth)',
              text: device.port || '—',
            }),
            el('span', {
              class: 'mono text-mid', style: 'font-size:11px',
              text: device.ipTemplate,
            }),
            el('span', {
              class: 'mono', style: 'font-size:11px;color:var(--accent)',
              text: device.pbxExtension || '—',
            }),
          ])),
        ]),
      ]),
    ]),

    el('div', { class: 'card' }, [
      el('h4', { text: t('admin.categoryDefinition') }),
      el('div', { style: 'margin-top:11px' },
        meta.categories.map(category => el('div', {
          style: 'display:flex;gap:10px;padding:6px 0;'
            + 'border-bottom:1px solid var(--line-soft);'
            + 'font-family:var(--font-mono);font-size:11px',
        }, [
          el('span', { style: 'width:82px;flex:none', text: category.code }),
          el('span', {
            class: 'text-mid', style: 'flex:1', text: category.types,
          }),
        ]))),
    ]),
  ]));

  fill(root, parts);
}
