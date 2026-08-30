// Project & device list (admin).
//
// WHAT IS LOADED, AND WHAT IT SAYS. The heading names the DeviceMap this
// copy is running; beside the ledger are the things that belong to the
// project rather than to a run of it — what the map holds, which other
// projects can be opened, and the service key on a build that can mint one.
//
// THE LEDGER IS THE SCREEN. A DeviceMap is switches with devices hanging off
// their ports, and this was a flat table of all 110 of them with the switch
// nowhere on it — see views.css. It is grouped by switch now, and the two
// things a reference table of that length cannot do without, a search box
// and a filter, are the search box in the page head and the census in the
// rail.
//
// A device username/password cannot be saved on this screen, and never
// could: the "save credentials to a file" / "password stored" fields of
// older panels are deliberately absent. Nor is there anything here for
// forgetting them — the panel forgets every credential when it closes
// (see panel.api.reset), and a button that repeated what quitting already
// does is not a card's worth of screen.
//
// The train set is not set here either. It is in the top bar, on every
// screen, and a second box for it on one of them meant two controls for one
// number that had to be kept in step by hand.

import { el, fill } from '../core/dom.js';
import { dataTable } from '../components/table.js';
import { api } from '../core/api.js';
import { state, publish } from '../core/store.js';
import { showSuccess, showError } from '../components/toast.js';
import { confirmWrite } from '../components/confirm.js';
import { value, fileSize, methodCode, typeLabel } from '../core/format.js';
import { searchField } from '../components/search_field.js';
import { t } from '../core/i18n.js';

// Port first: it is what the row is looked up by once the rows are read
// against one switch instead of eight, and the digits line up down the edge.
// "Okuma" is new — how the panel talks to the device is a property of the
// MAP, and this is the only screen that describes the map.
const COLUMNS = '56px minmax(180px,1.4fr) minmax(140px,1fr) 112px 84px 84px';

// ── this screen's working set ───────────────────────────────────────────
// Module memory rather than `core/store.js`, the same call the device list
// made for its selection: a filter over a reference table means nothing on
// any other screen, and `state.category` is the DEVICE LIST's filter —
// sharing it would have made cutting this ledger down to the cameras
// silently change what the operator sees when they go back to their list.
let search = '';
let category = 'all';

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
    ? el('div', { class: 'pick-list mt-2' }, rows)
    : el('p', { class: 'mono text-dim t-xs mt-2', text: empty });
}

// Every project that is not the one open, offered where the open one is
// already named. Opening ANOTHER CUSTOMER'S train exists only in admin mode
// and is an engineer's act rather than an operator's, so it belongs here
// rather than on the project name in the top bar — that menu stays what it
// was, a quick switch between the two train types this package was built
// for.
//
// EVERY PROJECT, THE OPEN ONE INCLUDED. Two earlier shapes were both worse:
// listing only the ones admin mode ADDED made this a one-way door —
// switching from Yatakli to the exhibition rack left a card offering GDM,
// Gaziray and the rack, with the package's own trains nowhere on the screen
// the switch had been made from — and then hiding merely the open one left
// the list unable to say where you are. A whole list that marks the current
// row answers both: it is the inventory of what can be opened, and it says
// which one is.
//
// The open row is MARKED, not disabled. Greyed out it would read as "you
// cannot have this", which is the opposite of what is true of it; an
// unavailable project is the one that reads that way, and it does.
//
// Nothing at all when there is nothing to choose between: on a package
// carrying one project whose foreign maps could not be opened — no service
// key in the machine, nothing to decrypt them with — a list of one is a
// heading over a statement of the obvious (see panel/adminkey/sealed.py).
// The list only, without a caption: the card it goes in is titled, and a
// card whose head says "Other projects" over a line saying "Other projects"
// was the same words twice in forty pixels.
function otherProjects(openProject) {
  const all = state.projects || [];
  if (all.length < 2 || !openProject) return null;

  return el('div', {}, [
    pickList(all.map(project => el('button', {
      type: 'button', class: 'pick-item',
      // A project whose device list has not arrived is listed with the
      // reason rather than left out: it exists, and the engineer asking for
      // it deserves to be told why not.
      disabled: !project.available,
      'aria-current': project.current ? 'true' : null,
      onclick: () => openProject(project.key),
    }, [
      el('span', { class: 'pick-label', text: project.label }),
      el('span', {
        class: 'pick-note',
        text: project.current ? t('admin.loaded')
          : (project.available ? '' : t('admin.projectUnavailable')),
      }),
    ])), t('admin.noOtherProject')),
  ]);
}

function serviceKeyCard() {
  if (volumes === null) { volumes = []; loadVolumes(); }
  if (drives === null) { drives = []; loadDrives(); }
  const label = el('input', {
    class: 'field', type: 'text', maxlength: '120', autocomplete: 'off',
    'aria-label': t('admin.keyLabel'),
  });

  return el('div', { class: 'card corner' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('admin.serviceKey') }),
    ]),
    // One label for both actions: it is a note about the KEY, not about the
    // way it got onto the drive.
    el('label', {
      class: 'label field-label mt-4',
      text: t('admin.keyLabel'),
    }, [label]),

    el('div', { class: 'label mt-5', text: t('admin.prepareDrive') }),
    pickList(drives.map(drive => el('button', {
      type: 'button', class: 'pick-item',
      onclick: () => prepareDrive(drive, label.value),
    }, [
      el('span', { class: 'pick-label', text: drive.name }),
      el('span', { class: 'pick-note', text: fileSize(drive.size) }),
    ])), t('admin.noDriveFound')),
    el('button', {
      type: 'button', class: 'btn mt-3',
      text: t('admin.refreshDrives'), onclick: loadDrives,
    }),

    el('div', { class: 'label mt-5', text: t('admin.writeKeySection') }),
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
      type: 'button', class: 'btn mt-3',
      text: t('admin.refreshVolumes'), onclick: loadVolumes,
    }),
  ]);
}

function prepareDrive(drive, label) {
  confirmWrite({
    title: t('admin.prepareDrive'),
    lead: t('admin.prepareConfirm',
            { drive: drive.name, size: fileSize(drive.size) }),
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
    confirmLabel: volume.hasKey ? t('admin.replaceKey') : t('admin.writeKey'),
    run: async () => {
      await api.adminKeyWrite(volume.path, label);
      showSuccess(t('admin.keyWritten', { volume: volume.name }));
      await loadVolumes();
    },
  });
}

// ── the ledger ──────────────────────────────────────────────────────────
//
// The map's own shape, read back off the device list: the loader emits a
// switch and then the devices on its ports, so a group starts wherever a
// `Switch` appears. Grouped by `switchId` rather than by position, because
// a device that arrived without its switch belongs somewhere the eye can
// find it rather than under whichever band happened to be open.
function bySwitch(devices) {
  const groups = [];
  const byId = new Map();
  const group = (id) => {
    let found = byId.get(id);
    if (!found) {
      found = { id, head: null, devices: [] };
      byId.set(id, found);
      groups.push(found);
    }
    return found;
  };
  for (const device of devices) {
    const entry = group(device.switchId || device.id);
    if (device.type === 'Switch') entry.head = device;
    else entry.devices.push(device);
  }
  return groups;
}

// Everything on the row, in the language it is written in on the row: a
// search for "2007" finds the extension, "p11" and "11" both find the port,
// and "ska1_2" finds a whole cabinet.
function matches(device, needle) {
  if (!needle) return true;
  return [
    device.name, device.typeLabel, device.ipTemplate, device.pbxExtension,
    device.switch, device.port, device.port ? `p${device.port}` : '',
    methodCode(device),
  ].some(field => String(field || '').toLowerCase().includes(needle));
}

function inCategory(device) {
  return category === 'all' || device.category === category;
}

// A band is drawn when there is something under it, or when the switch
// ITSELF is what was asked for — filtering to the network category with the
// switches hidden would answer a question about switches with no switches.
function visibleGroups(groups, needle) {
  return groups.map(group => ({
    ...group,
    shown: group.devices.filter(
      device => inCategory(device) && matches(device, needle)),
    headShown: !!group.head && inCategory(group.head)
      && matches(group.head, needle),
  })).filter(group => group.shown.length || group.headShown);
}

function bandRow(group) {
  const head = group.head || {};
  return el('div', { class: 'map-band', role: 'row' }, [
    // ONE CELL, laid out inside itself. `dataTable` marks every direct child
    // of a row as a cell, and a band announced as three cells in a
    // six-column table is three answers to a question nobody asked.
    el('span', { class: 'map-band-line', role: 'cell' }, [
      el('span', { class: 'name', text: group.head ? head.name : group.id }),
      el('span', {
        class: 'meta',
        text: group.head
          ? `${head.ipTemplate} · ${methodCode(head)}` : '',
      }),
      el('span', {
        class: 'ports',
        text: t('admin.portCount', { count: group.shown.length }),
      }),
    ]),
  ]);
}

function deviceRow(device) {
  return el('div', { class: 'table-row', style: `--table-columns:${COLUMNS}` }, [
    el('span', { class: 'map-port', text: device.port ? `p${device.port}` : '' }),
    el('span', { class: 'map-name truncate', text: device.name }),
    el('span', {
      class: 'text-bright truncate t-sm', text: typeLabel(device.typeLabel),
    }),
    el('span', { class: 'mono text-mid t-sm', text: device.ipTemplate }),
    el('span', { class: 'map-method', text: methodCode(device) }),
    // The extension keeps the accent it carries on the PISCU screen — one
    // thing, one colour. Blank rather than a dash where there is none: two
    // devices in three have no extension, and a column of seventy dashes is
    // not the answer to a question anyone asked of this column.
    el('span', {
      class: 'mono t-sm sip-extension', text: device.pbxExtension || '',
    }),
  ]);
}

// ── the census ──────────────────────────────────────────────────────────
// What the map holds, and the filter over it, as one object. The count is
// what the glossary never said, and it is the reason to press the row.
function censusCard(redraw) {
  const categories = (state.meta && state.meta.categories) || [];
  return el('div', { class: 'card corner' }, [
    el('div', { class: 'card-head' }, [
      el('h3', { text: t('admin.categories') }),
    ]),
    ...categories.map(entry => el('button', {
      type: 'button', class: 'census-row',
      'aria-pressed': String(category === entry.id),
      onclick: () => {
        // Pressing the row you are on goes back to the whole map: the same
        // way out the row you came in by.
        category = category === entry.id ? 'all' : entry.id;
        redraw();
      },
    }, [
      el('span', { class: 'name', text: entry.name }),
      el('span', { class: 'types', text: entry.types }),
      el('span', {
        class: 'count',
        text: String(entry.id === 'all'
          ? state.devices.length
          : state.devices.filter(d => d.category === entry.id).length),
      }),
    ])),
  ]);
}

// Typing in a box on the screen SUPPRESSES the application's own render
// (app.js focusInScreenField), which is what stops a refresh round wiping
// what somebody is halfway through typing. The ledger would therefore never
// filter while the box has focus, so this screen redraws itself and puts the
// caret back where it was — the same answer the device list gives.
function searchBox(redraw, root) {
  return searchField({
    id: 'map-search',
    value: search,
    title: t('admin.searchHint'),
    'aria-label': t('admin.searchHint'),
    oninput: (event) => {
      const caret = event.target.selectionStart;
      search = event.target.value;
      redraw();
      const again = root.querySelector('#map-search');
      if (!again) return;
      again.focus();
      again.setSelectionRange(caret, caret);
    },
  }, 'map-search');
}

export function render(root, openProject) {
  const meta = state.meta;
  if (!meta) return;
  const redraw = () => render(root, openProject);
  const parts = [];
  const needle = search.trim().toLowerCase();

  // THE HEADING NAMES THE PROJECT THAT IS OPEN. It read "Project & device
  // list" — the name of the screen, which the menu rail already gives it —
  // while the one fact it exists to state, WHICH DeviceMap this copy is
  // running, was the title of the first card underneath. The dot is what the
  // word "Loaded" beside that title used to say.
  parts.push(el('div', { class: 'page-head' }, [
    el('div', {}, [
      el('h2', { class: 'verdict', dataset: { state: 'ok' } }, [
        el('span', {
          class: 'dot', dataset: { state: 'ok' }, 'aria-hidden': 'true',
        }),
        el('span', { text: meta.project }),
      ]),
      el('div', {
        class: 'page-sub mono',
        text: `${meta.file} · ${t('admin.broker', {
          ip: value(meta.brokerIp),
        })}`,
      }),
    ]),
    el('div', { class: 'actions' }, [searchBox(redraw, root)]),
  ]));

  const groups = visibleGroups(bySwitch(state.devices), needle);
  const shown = groups.reduce(
    (total, group) => total + group.shown.length + (group.headShown ? 1 : 0), 0);

  const rows = [];
  for (const group of groups) {
    rows.push(bandRow(group));
    for (const device of group.shown) rows.push(deviceRow(device));
  }

  // The line beside the title counts the ROWS ON SCREEN once anything has
  // been asked of the ledger, and the map itself when nothing has — the same
  // rule the device list's sub-heading follows, for the same reason: the one
  // number on the screen that could confirm a search worked must move.
  const filtering = !!needle || category !== 'all';
  const cards = [
    censusCard(redraw),
    // On a shipped package there is neither of these, so the rail is the
    // census alone. They used to sit in a row ABOVE the tables, which pushed
    // the ledger off the bottom of the window on the builds that had them.
    otherProjects(openProject) ? el('div', { class: 'card corner' }, [
      el('div', { class: 'card-head' }, [
        el('h3', { text: t('admin.otherProjects') }),
      ]),
      otherProjects(openProject),
    ]) : null,
    (state.edition && state.edition.canWriteKey) ? serviceKeyCard() : null,
  ].filter(Boolean);

  parts.push(el('div', { class: 'admin-grid' }, [
    el('div', { class: 'card corner' }, [
      el('div', { class: 'card-head' }, [
        el('h3', { text: t('admin.devicePortMapping') }),
        el('span', {
          class: 'label',
          text: filtering
            ? t('admin.shownCount', { shown, total: state.devices.length })
            // The two numbers are a BREAKDOWN and they add up: the bands
            // and the rows under them. `meta.total` counts the switches
            // too — it is every device in the map — so reading it out
            // beside the switch count said 8 and 110 for 110 things.
            : t('admin.mapCount', {
                switches: meta.switchCount,
                devices: meta.total - meta.switchCount,
              }),
        }),
      ]),
      dataTable({
        template: COLUMNS, minWidth: 720, wrapClass: 'map-wrap mt-0',
        label: t('admin.devicePortMapping'),
        columns: ['col.port', 'col.name', 'col.typeSubtype', 'col.ipTemplate',
                  'col.readMethod', 'col.pbxExtension'].map(key => t(key)),
        rows,
        empty: t('admin.noDeviceMatches'),
      }),
    ]),
    el('div', { class: 'map-rail' }, cards),
  ]));

  fill(root, parts);
}
