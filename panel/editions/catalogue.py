#!/usr/bin/env python3
"""Which product each customer receives — the table, and nothing else.

One program, several packages. The panel is commissioned by different
operators on different trains, and each of them may only see their own
project: a GDM technician opening the device list must not find another
customer's inventory, addresses and SIP extensions in it. The separation is
therefore made where it cannot be undone by a click — at BUILD time. Every
edition is a package of its own, carrying only its own DeviceMap.

What differs between editions is data, not code:

    which projects it can open      `projects`
    what the package is called      `product_name`
    which screens the field user    `views`
    sees

Everything else is shared. There is no per-edition branch anywhere in the
application; a screen that one customer must not see is absent from that
edition's `views`, and both the sidebar and the API guard read the same list
(see `panel.api.guard`).

ADMIN IS A MODE, NOT A ROW, and there is no row that is admin. Every
edition here is a customer's package and opens on that customer's field
screens; the only way to the engineer's screens is the service key on a USB
stick (`panel.adminkey`) — no password, no flag, no hidden click, and no
fourth package that skips the question. That is why `views` describes the
FIELD user only: in admin mode every edition shows
`BASE_VIEWS | ADMIN_VIEWS`.

There WAS a fourth row, an internal "service" package that opened as admin
with nothing plugged in. It is gone: a build that opens itself is one more
thing that can reach a customer's machine, and the bootstrap it existed for
— writing the first key, before any key exists to be inserted — belongs to
whoever holds the build secret and needs no package of its own (see
`runtime.opens_as_admin`).

THIS MODULE IMPORTS NOTHING BUT THE STANDARD LIBRARY, ON PURPOSE.
`dabp.spec` has to read the table to know what to name the executable and
which DeviceMap to bundle, and the spec deliberately does not import `panel`
(it would need `requests`, which is not installed in a build environment).
It loads this file directly with `importlib`. Anything that needs a path, a
setting or a message key lives in `runtime.py` instead, and
`tests/test_editions.py` fails if an import creeps in here.

Loading it standalone takes one non-obvious step — the module has to be put
in `sys.modules` BEFORE it is executed:

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # dataclasses needs this
    spec.loader.exec_module(module)

`from __future__ import annotations` turns every field annotation into a
string, and `dataclasses` resolves those strings through `sys.modules`. Miss
the line and the load dies inside `@dataclass` with an AttributeError that
says nothing about what is wrong.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── the screens ──────────────────────────────────────────────────────────
# View ids as the UI knows them (`static/index.html` declares one container
# per id, `static/js/app.js` maps them to a renderer). Kept here rather than
# in the frontend because the API guard enforces the same list server-side,
# and two copies would drift on the first screen added.
BASE_VIEWS = ("overview", "devices", "ip", "config", "firmware",
              "network", "checklist", "history")
# The engineer's screens. Two kinds sit here for two reasons.
#
# PISCU, MQTT and the project screen expose the project definition itself,
# which is the one thing an edition exists to keep to itself.
#
# THE ADB AND SWITCH SCREENS ARE HERE FOR A DIFFERENT REASON, and they were
# base screens until they were moved: they are the two that write to hardware
# without a device list in front of them. Every other field screen works
# through the project's DeviceMap and can only touch what is in it; these two
# take a typed address and act on whatever answers, which on a shared network
# is any device at all — a switch port turned off, a PoE feed cut, an
# application installed, a display rebooted. The service key is what says the
# person doing that is the one who should be.
ADMIN_VIEWS = ("adb", "switch", "piscu", "mqtt", "admin")


@dataclass(frozen=True)
class Project:
    """One customer project — one DeviceMap.

    `key` addresses it over the API and never changes; `label` is what the
    top bar shows. `label` also has to agree with the name `Inventory`
    derives from the file stem (`panel/inventory/device_map.py`), because
    that derived name is what `panel/video_config/nvr.py` branches on;
    `tests/test_editions.py` holds the two together.

    There is NO `available` flag. Whether a project can be opened is decided
    by whether its file is actually there, and that is answered in
    `runtime.py`. A flag would be a second truth to keep in step: delivering
    a DeviceMap would mean editing this table as well as dropping the file
    in, and forgetting the edit would leave a project that exists but cannot
    be opened.
    """

    key: str
    label: str
    # Name at the root of the frozen bundle. Flat, because PyInstaller data
    # files are placed at the bundle root (see `panel/settings.py:data_file`).
    map_name: str
    # Where the same file lives in the source tree, relative to ROOT.
    source_path: tuple[str, ...]
    # Set only for a project that did not ship with the package: one
    # delivered on the service key (`panel.adminkey.pack`) already sits at a
    # known absolute path, and neither the bundle root nor the source tree
    # can name it. Empty for every row in the table below.
    path: str = ""
    # A DEMONSTRATION STAND rather than a train, and one read changes because
    # of it: a Compartment LCD is not required to be running the panel
    # application (see `panel/probe/android.py`). On a train that application
    # is the reason the display is there and its absence is the fault being
    # looked for; on a stand the hardware is borrowed and every unit carries
    # something different, so demanding one named application turns the whole
    # board red and hides the units that genuinely cannot be reached.
    #
    # ON THE PROJECT, not in an environment variable: the person setting a
    # stand up should not have to remember a flag, and the same package used
    # on a train must not inherit the relaxation.
    stand: bool = False
    # This project's checklist workbook. Same two names as the DeviceMap
    # above: flat at the bundle root, relative in the source tree.
    #
    # EVERY PROJECT IN THE TABLE CARRIES ITS OWN. The workbook matches its
    # rows to devices BY IP TEMPLATE (`panel/checklist/workbook.py`), so a
    # project filled from another's file gets no rows at all — an empty
    # report, with nothing on screen to say why. One shared workbook only
    # ever fitted the trains built to the same drawing, and stopped being
    # true the moment GDM and Gaziray arrived with device kinds and
    # addresses of their own.
    #
    # Empty for a project delivered on the service key and nowhere else
    # (`panel.adminkey.pack`): no workbook was generated for a map that
    # arrived on a stick, so `runtime.checklist_path` falls back to the
    # shared template for it.
    #
    # Built by `tools/make_checklist_template.py`, never by hand.
    checklist_name: str = ""
    checklist_source: tuple[str, ...] = ()

    # ── the three addresses that are a ROLE, not a device ────────────────
    #
    # The MQTT broker, the clock source and the PBX. On a train with one
    # PISCU all three ARE that PISCU, which is why the panel derived them
    # from `Inventory.piscu_ip()` and was right for three projects out of
    # five. Gaziray and GDM broke the assumption: both carry a Master and a
    # Slave PISCU, and neither is the broker (Gaziray answers on 10.n.0.1,
    # GDM on 192.168.201.210 — the PISCUs are .211 and .212).
    #
    # The failure was silent and expensive. MQTT connected to a host that
    # was not the broker, so no live DeviceMap ever arrived; and because the
    # same value was handed out as the expected NTP server and the expected
    # PBX, every device's clock and SIP verification read "does not match"
    # with nothing on screen to say why.
    #
    # IP TEMPLATES, not addresses: `n` is the train set and is substituted
    # where the set is known (`runtime.broker_ip` and friends, through
    # `inventory.device_map.resolve_template`). This module may not import
    # that — see the note at the top about `dabp.spec` loading it bare — so
    # it holds the template and resolves nothing.
    #
    # EMPTY MEANS "THE PISCU", which is the honest default and keeps the
    # three projects it is true for from repeating themselves. `pbx` and
    # `ntp` fall back to `broker` rather than to the PISCU: where they have
    # ever differed from the broker they have differed together.
    broker: str = ""
    pbx: str = ""
    ntp: str = ""
    # Does this project's video equipment have storage to ask about?
    #
    # `video_config.health` asks every camera for its SD card and every NVR
    # for its disk. On Gaziray and GDM that is a real check; on the others
    # the cameras record to the NVR and have no card in them by design, so
    # the question comes back "no SD" for every camera on the train and the
    # checklist fills with a fault nobody can fix. The NVR's buzzer is NOT
    # behind this flag — a buzzer left armed is a fault on any project.
    storage: bool = False
    # Addresses written out rather than templated: GDM's 192.168.201.x and
    # the exhibition rack's 10.1.1.x. The train-set box in the top bar
    # substitutes nothing on such a project, so it is not shown — a control
    # that changes nothing is worse than no control, because the operator
    # believes it worked.
    #
    # DECLARED, NOT DERIVED. "This map happens to contain no `n` today" and
    # "this project is addressed in fixed form" are different claims, and
    # only the second one should hide a control.
    fixed_addressing: bool = False

    # ── the two masks ────────────────────────────────────────────────────
    #
    # `prefix` is HOW WIDE THIS PROJECT'S NETWORK IS, and it settles two
    # things at once: the mask written with a new address
    # (`panel.ip_assign`), and the width of the alias the panel gives itself
    # so it can reach the devices at all (`panel.network.planning`). One
    # number, because they are one fact — a computer whose alias is narrower
    # than the devices' network cannot see half the train.
    #
    # Most projects put every device on one /24, which is the system default
    # and is why this is normally unset. Gaziray does not: the third octet is
    # the CAR (10.n.1.x through 10.n.4.x) and the broker sits on a fifth
    # network at 10.n.0.1, so nothing narrower than a /16 spans the train.
    #
    # ZERO MEANS UNSTATED, and that is not the same as 24. An unstated prefix
    # leaves the device's own mask alone — the long-standing behaviour of the
    # intercom run (`panel.ip_assign.runner`) — while a project that states
    # one is making a claim the run should enforce. It is also what keeps
    # Yatakli and VIP bit-for-bit on the behaviour they have today.
    prefix: int = 0
    #
    # THERE IS NO `expected_mask` BESIDE THIS, and there was briefly. The mask
    # a camera is VERIFIED against is not a constant anybody can write down:
    # Yatakli sits inside one /24, Gaziray needs a /16, and the CCTV
    # commissioning scripts write a /8 to both. Every one of those is correct,
    # and a check demanding one exact value called two of them a fault. The
    # question with a single answer is "is the device's own network wide
    # enough to reach the rest of the project", and the project's reach is
    # computed from the DeviceMap (`Inventory.span`) rather than declared
    # here — see `panel.probe.camera._mask_reaches`.


@dataclass(frozen=True)
class Edition:
    """One package, as it is shipped to one customer."""

    id: str
    # THE ONE TURKISH STRING IN THE CODE BASE, and deliberately so.
    # Stamped into the package at build time — the macOS bundle name, the
    # Windows version resource, the setup wizard and the Release title. It
    # cannot follow the language the user picks, so it is written in the
    # language of the operators who commission the trains (the name INSIDE
    # the app still follows the language: "app.name" in the catalogue).
    product_name: str
    # Inno Setup AppId. Distinct per edition so two editions installed on
    # the same machine update themselves and never each other.
    windows_app_id: str
    projects: tuple[Project, ...]
    default_project: str
    # What the FIELD user sees. Admin mode always adds ADMIN_VIEWS.
    views: tuple[str, ...]


# ── the naming rule ──────────────────────────────────────────────────────
# A PROJECT'S FILES ARE NAMED FROM ITS KEY, and from nothing else:
#
#     folder     devicemaps/<key>/
#     DeviceMap  DeviceMap_<Key>.json
#     workbook   Field_Device_Verification_<Key>.xlsx
#
# `<Key>` is the key with its first letter capitalised. The key is already
# lowercase ASCII — it addresses the project over the API — so the rule needs
# no transliteration table and the code stays free of the label's Turkish
# spelling.
#
# THE CAPITAL IS NOT DECORATION. `Inventory.project` takes the project's name
# from the map's stem (`panel/inventory/device_map.py`), so the file name is
# what the top bar shows and what `panel/video_config/nvr.py` branches on.
# `Project.label` has to agree with it, which `tests/test_editions.py` holds.
#
# DERIVED RATHER THAN WRITTEN OUT, because a rule three of five rows follow
# is not a rule. That is exactly how the maps arrived — `DeviceMap_gdm.json`
# next to `DeviceMap_Fuar.json`, and a bare `DeviceMap.json` for Yatakli —
# and a case-insensitive filesystem hides the mismatch completely: macOS and
# Windows open the file, Linux does not, so the package builds there without
# the device list it was supposed to carry.
MAPS_DIR = "devicemaps"
# The checklist template every generated workbook is built from. Not a
# project, and named without a key on purpose: it belongs to no one project
# and is the one file `tools/make_checklist_template.py` reads rather than
# writes.
BASE_DIR = "_base"
BASE_CHECKLIST = "Field_Device_Verification.xlsx"


def map_file_name(key: str) -> str:
    """What this project's DeviceMap is called, everywhere it appears."""
    return f"DeviceMap_{str(key).capitalize()}.json"


def checklist_file_name(key: str) -> str:
    """What this project's checklist workbook is called."""
    return f"Field_Device_Verification_{str(key).capitalize()}.xlsx"


def project(key: str, label: str, **rest) -> Project:
    """One project, with every path filled in by the rule above.

    The only way a row in the table below is written. Passing a path by hand
    is what the rule exists to prevent.
    """
    folder = (MAPS_DIR, key)
    return Project(key=key, label=label,
                   map_name=map_file_name(key),
                   source_path=(*folder, map_file_name(key)),
                   checklist_name=checklist_file_name(key),
                   checklist_source=(*folder, checklist_file_name(key)),
                   **rest)


# ── the projects ─────────────────────────────────────────────────────────
# One folder per project under `devicemaps/`, holding the two files that have
# to agree: its DeviceMap, and the workbook generated from that DeviceMap.
# Kept together rather than sorted by file kind into two folders, so half a
# delivery is visibly half a folder and a workbook cannot be left behind next
# to another project's.
# One PISCU, and it is the broker, the clock and the PBX. Nothing to state.
YATAKLI = project("yatakli", "Yataklı")
VIP = project("vip", "VIP")
# Four cars, two PISCUs, and a broker that is NEITHER of them. The cameras
# here record to their own cards, so the storage check is real.
# One network holds all 125 devices, but the alias is widened to a /16
# anyway: the panel then reaches the whole 192.168 range while its own
# address still sits inside the devices' /24 (see
# `panel.network.planning.choose_host`), which is what lets a camera on
# a /24 answer it.
GDM = project("gdm", "GDM",
              broker="192.168.201.210", storage=True,
              fixed_addressing=True,
              prefix=16)
GAZIRAY = project("gaziray", "Gaziray", broker="10.n.0.1", storage=True,
                  prefix=16)
# The exhibition rack: one KYLAND switch and the twelve devices shown beside
# it. Not a train, and its map says so — the addresses are literal
# (10.1.1.x) where a train's are templates (10.n.1.x), because there is one
# set and it does not move. Everything downstream still works: the set number
# substitutes nothing and every screen reads the same list.
#
# IT STATES A PREFIX for the same reason Gaziray does, and stating nothing was
# a live fault: the rack's addresses run 10.1.1.x through 10.1.4.x — four /24s,
# like Gaziray's cars — while an unstated prefix left the run writing the /24
# default. The panel therefore configured a device and then reported that same
# device's mask as too narrow to reach the rest of the rack. Both halves of a
# project's width are now the same answer (tests/test_network.py).
FUAR = project("fuar", "Fuar", stand=True, fixed_addressing=True,
               prefix=16)

ALL_PROJECTS = (YATAKLI, VIP, GDM, GAZIRAY, FUAR)


# ── the editions ─────────────────────────────────────────────────────────
EDITIONS = (
    # VIP and Yatakli are the same customer's two train types, so they travel
    # in one package and the user switches between them in the top bar. That
    # switch needs no admin mode: both projects belong to the operator
    # holding this package.
    Edition(
        id="vip-yatakli",
        product_name="Devreye Alma ve Bakım Paneli - VIP ve Yataklı",
        # Inherited from the single-edition build: today's installations are
        # the Yatakli package, and this is the edition that succeeds them, so
        # it must update over them rather than land beside them.
        windows_app_id="{1D33CE96-66C7-41A7-9A7F-4EEC36A3D8A0}",
        projects=(YATAKLI, VIP),
        default_project="yatakli",
        views=BASE_VIEWS,
    ),
    Edition(
        id="gdm",
        product_name="Devreye Alma ve Bakım Paneli - GDM",
        windows_app_id="{BEA834CD-CD5B-4ACF-978E-FF1FE0699919}",
        projects=(GDM,),
        default_project="gdm",
        views=BASE_VIEWS,
    ),
    Edition(
        id="gaziray",
        product_name="Devreye Alma ve Bakım Paneli - Gaziray",
        windows_app_id="{B194E84B-B737-4F9E-8602-FAC3095BE98B}",
        projects=(GAZIRAY,),
        default_project="gaziray",
        views=BASE_VIEWS,
    ),
    # The stand at the exhibition. A package like any other — the rack there
    # is somebody's hardware, shown to people who are not the customer, and
    # a build carrying every customer's device list is exactly what must not
    # be on a laptop in a hall.
    Edition(
        id="fuar",
        product_name="Devreye Alma ve Bakım Paneli - Fuar",
        windows_app_id="{4981AD5D-585F-4221-A5B1-6F3C4ACFEA3A}",
        projects=(FUAR,),
        default_project="fuar",
        views=BASE_VIEWS,
    ),
)

BY_ID = {edition.id: edition for edition in EDITIONS}
IDS = tuple(edition.id for edition in EDITIONS)


def find(edition_id: str):
    """The edition with this id, or None.

    Returns rather than raises: the callers that need a message
    (`app.py`, `dabp.spec`) each phrase it for their own audience, and this
    module has no catalogue to phrase it from.
    """
    return BY_ID.get(str(edition_id or "").strip().lower())


def app_name(edition_id: str) -> str:
    """The name every FILE the build produces is called.

    Short and ASCII so it survives every shell, ZIP and installer it passes
    through — the same reasoning as `settings.APP_SLUG`, which this extends
    rather than replaces.
    """
    return f"dabp-{edition_id}"
