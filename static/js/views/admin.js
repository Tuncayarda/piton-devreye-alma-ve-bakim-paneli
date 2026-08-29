// Project & device list (admin).
//
// A device username/password CANNOT be saved on this screen. The "save
// credentials to a file" / "password stored" fields of older panels are
// deliberately absent; the only thing possible here is forgetting what is in
// memory.

import { el, fill } from '../core/dom.js';
import { dataTable } from '../components/table.js';
import { api } from '../core/api.js';
import { state, publish } from '../core/store.js';
import { showSuccess, showError } from '../components/toast.js';
import { confirmWrite } from '../components/confirm.js';
import { value, fileSize } from '../core/format.js';
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
      class: 'mono text-dim t-xs',
      style: 'margin-top:9px;line-height:1.6',
      text: t('admin.validRange', { min, max }),
    }),
  ]);
}

// ── the service key ─────────────────────────────────────────────────────
// Two ways onto a stick, and they are not the same act.
//
//   Erase and write   wipes the whole drive, lays down FAT32, then writes
//                     the key. This is the one operation in the panel that
//                     destroys data outside its own files, so it names the
//                     drive and its size and asks in red.
//   Write onto        drops the key file onto a drive that is already
//   a prepared drive  mounted. Three hundred bytes, nothing else touched.
//
// Both are wrapped in `confirmWrite` — writing a key is not undoable in any
// useful sense either, because the drive leaves the building. What the
// confirmation says is different in each case, and that is the point.
//
// Neither list is polled: this screen is opened deliberately, and a list
// that reshuffles under the cursor while somebody is reading it is worse
// than one that needs a click.
let volumes = null;
let drives = null;

async function loadVolumes() {
  try {
    volumes = (await api.adminKeyVolumes()).volumes || [];
  } catch (e) {
    volumes = [];
    showError(e.message);
  }
  publish(['edition']);          // redraw this screen with the new list
}

async function loadDrives() {
  try {
    drives = (await api.adminKeyDrives()).drives || [];
  } catch (e) {
    drives = [];
    showError(e.message);
  }
  publish(['edition']);
}

function pickList(rows, empty) {
  return rows.length
    ? el('div', { class: 'pick-list', style: 'margin-top:6px' }, rows)
    : el('p', { class: 'mono text-dim t-xs', style: 'margin-top:6px',
                text: empty });
}

function serviceKeyCard() {
  if (volumes === null) { volumes = []; loadVolumes(); }
  if (drives === null) { drives = []; loadDrives(); }
  const label = el('input', {
    class: 'field', type: 'text', maxlength: '120', autocomplete: 'off',
    'aria-label': t('admin.keyLabel'),
  });

  return el('div', { class: 'card corner' }, [
    el('h4', { text: t('admin.serviceKey') }),
    // One label for both actions: it is a note about the KEY, not about the
    // way it got onto the drive.
    el('label', {
      class: 'label', style: 'display:block;margin-top:12px',
      text: t('admin.keyLabel'),
    }, [label]),

    el('div', { class: 'label', style: 'margin-top:16px',
                text: t('admin.prepareDrive') }),
    el('p', {
      class: 'mono text-dim t-xs', style: 'margin-top:6px;line-height:1.6',
      text: t('admin.prepareDriveNote'),
    }),
    pickList(drives.map(drive => el('button', {
      type: 'button', class: 'pick-item',
      onclick: () => prepareDrive(drive, label.value),
    }, [
      el('span', { class: 'pick-label', text: drive.name }),
      el('span', { class: 'pick-note', text: fileSize(drive.size) }),
    ])), t('admin.noDriveFound')),
    el('button', {
      type: 'button', class: 'btn', style: 'margin-top:10px',
      text: t('admin.refreshDrives'), onclick: loadDrives,
    }),

    el('div', { class: 'label', style: 'margin-top:18px',
                text: t('admin.writeKeySection') }),
    pickList(volumes.map(volume => el('button', {
      type: 'button', class: 'pick-item',
      onclick: () => writeKey(volume, label.value),
    }, [
      el('span', { class: 'pick-label', text: volume.name }),
      el('span', {
        class: 'pick-note',
        text: volume.hasKey ? t('admin.keyAlreadyThere') : '',
      }),
    ])), t('admin.noRemovableVolume')),
    el('button', {
      type: 'button', class: 'btn', style: 'margin-top:10px',
      text: t('admin.refreshVolumes'), onclick: loadVolumes,
    }),
  ]);
}

function prepareDrive(drive, label) {
  confirmWrite({
    title: t('admin.prepareDrive'),
    lead: t('admin.prepareConfirm',
            { drive: drive.name, size: fileSize(drive.size) }),
    notes: [
      // What the operator can still check, said at the moment they can
      // still stop: the panel cannot know which drive is the right one.
      { text: t('admin.prepareConfirmNote'), tone: 'warning' },
      { text: t('admin.writeKeyConfirm', { volume: drive.name }),
        tone: 'info' },
    ],
    danger: true,
    confirmLabel: t('admin.eraseAndWrite'),
    run: async () => {
      await api.adminKeyPrepare(drive.id, label);
      showSuccess(t('admin.drivePrepared', { drive: drive.name }));
      await loadDrives();
      await loadVolumes();
    },
  });
}

function writeKey(volume, label) {
  confirmWrite({
    title: volume.hasKey ? t('admin.replaceKey') : t('admin.writeKey'),
    lead: t('admin.writeKeyConfirm', { volume: volume.name }),
    notes: [volume.hasKey
      ? { text: t('admin.keyAlreadyThere'), tone: 'warning' } : null],
    confirmLabel: volume.hasKey ? t('admin.replaceKey') : t('admin.writeKey'),
    run: async () => {
      await api.adminKeyWrite(volume.path, label);
      showSuccess(t('admin.keyWritten', { volume: volume.name }));
      await loadVolumes();
    },
  });
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
        el('span', { class: 'title-label', text: meta.project }),
        el('span', {
          style: 'margin-left:auto', class: 'label', text: t('admin.loaded'),
        }),
      ]),
      el('div', {
        class: 'mono text-mid t-xs',
        style: 'margin-top:9px;line-height:1.7',
      }, [
        el('div', { text: meta.file }),
        el('div', {
        text: t('admin.broker', { ip: value(meta.brokerIp) }),
      }),
      ]),
    ]),
    el('div', { class: 'card corner' }, [
      el('h4', { text: t('admin.credentials') }),
      el('p', {
        class: 'mono text-mid t-xs',
        style: 'margin-top:9px;line-height:1.7',
        text: t('admin.deviceUsernamesAndPasswordsAre'),
      }),
      el('button', {
        type: 'button', class: 'btn btn-danger', style: 'margin-top:12px',
        text: t('admin.forgetCredentials'),
        // Irreversible for the session: every device drops back to
        // "needs credentials" and each one has to be typed again.
        onclick: () => confirmWrite({
          title: t('admin.forgetCredentials'),
          lead: t('confirm.forgetAllLead'),
          notes: [{ text: t('confirm.forgetAllNote'), tone: 'warning' }],
          danger: true,
          confirmLabel: t('admin.forgetCredentials'),
          run: async () => {
            await api.forgetAllCredentials();
            showSuccess(t('admin.everyCredentialInMemoryWas'));
          },
        }),
      }),
    ]),
    el('div', { class: 'card corner' }, [
      el('h4', { text: t('admin.trainSetN') }),
      setBox(meta, changeSet),
    ]),
    // Minting a key needs the build secret itself rather than the one-way
    // digest of it that every package carries — so this card exists only in
    // a run that holds the secret, which no shipped package does. Answered
    // by the server (`canWriteKey`): it is a property of the BUILD, and
    // nothing on this screen could work it out.
    (state.edition && state.edition.canWriteKey) ? serviceKeyCard() : null,
  ]));

  parts.push(el('div', { class: 'admin-grid' }, [
    el('div', { class: 'card' }, [
      el('div', { class: 'card-head' }, [
        el('h4', { text: t('admin.devicePortMapping') }),
        el('span', { class: 'label', text: t('admin.switchPortIpTemplate') }),
      ]),
      dataTable({
        template: COLUMNS, minWidth: 600, wrapStyle: 'margin-top:0',
        label: t('admin.devicePortMapping'),
        columns: ['col.name', 'col.typeSubtype', 'col.port', 'col.ipTemplate',
                  'col.pbxExtension'].map(key => (key ? t(key) : '')),
        rows: state.devices.map(device => el('div', {
            class: 'table-row', style: `--table-columns:${COLUMNS}`,
          }, [
            el('span', {
              class: 'mono truncate t-sm',
              text: device.name,
            }),
            el('span', {
              class: 'mono text-bright truncate t-sm',
              text: device.typeLabel,
            }),
            el('span', {
              class: 'mono t-sm', style: 'color:var(--auth)',
              text: device.port || '—',
            }),
            el('span', {
              class: 'mono text-mid t-sm',
              text: device.ipTemplate,
            }),
            el('span', {
              class: 'mono t-sm', style: 'color:var(--accent)',
              text: device.pbxExtension || '—',
            }),
          ])),
      }),
    ]),

    el('div', { class: 'card' }, [
      el('h4', { text: t('admin.categoryDefinition') }),
      el('div', { style: 'margin-top:11px' },
        meta.categories.map(category => el('div', {
          class: 't-sm',
          style: 'display:flex;gap:10px;padding:6px 0;'
            + 'border-bottom:1px solid var(--line-soft);'
            + 'font-family:var(--font-mono)',
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
