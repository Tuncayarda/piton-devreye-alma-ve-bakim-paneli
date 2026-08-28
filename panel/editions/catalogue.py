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
    # This project's checklist workbook, when it is not the shared one.
    #
    # The workbook matches its rows to devices BY IP TEMPLATE
    # (`panel/checklist/workbook.py`), so a project whose devices are not in
    # the shared file gets no rows filled at all — an empty report, with
    # nothing on screen to say why. Same two names as the DeviceMap above:
    # flat at the bundle root, relative in the source tree.
    #
    # Built by `tools/make_checklist_template.py`, never by hand.
    checklist_name: str = ""
    checklist_source: tuple[str, ...] = ()


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


# ── the projects ─────────────────────────────────────────────────────────
# YATAKLI keeps the unqualified name "DeviceMap.json" at the repository root.
# It is the map the panel was built against, the one the field scripts and
# `tests/` load, and `Inventory.project` derives the string "YATAKLI" from
# that stem. Renaming it would be a rename of a value, not of a file.
YATAKLI = Project("yatakli", "Yataklı", "DeviceMap.json",
                  ("DeviceMap.json",))
VIP = Project("vip", "VIP", "DeviceMap_Vip.json",
              ("devicemaps", "DeviceMap_Vip.json"))
GDM = Project("gdm", "GDM", "DeviceMap_Gdm.json",
              ("devicemaps", "DeviceMap_Gdm.json"))
GAZIRAY = Project("gaziray", "Gaziray", "DeviceMap_Gaziray.json",
                  ("devicemaps", "DeviceMap_Gaziray.json"))
# The exhibition rack: one KYLAND switch and the twelve devices shown beside
# it. Not a train, and its map says so — the addresses are literal
# (10.1.1.x) where a train's are templates (10.n.1.x), because there is one
# set and it does not move. Everything downstream still works: the set number
# substitutes nothing and every screen reads the same list.
FUAR = Project("fuar", "Fuar", "DeviceMap_Fuar.json",
               ("devicemaps", "DeviceMap_Fuar.json"), stand=True,
               checklist_name="Field_Device_Verification_Fuar.xlsx",
               checklist_source=("devicemaps",
                                 "Field_Device_Verification_Fuar.xlsx"))

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
