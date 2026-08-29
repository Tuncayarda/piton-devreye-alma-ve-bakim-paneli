#!/usr/bin/env python3
"""Which edition is running, which project is open, and which mode we are in.

`catalogue.py` is the table; this is everything the table cannot answer on
its own because it needs a filesystem, a setting or the running process.

WHERE THE EDITION COMES FROM, in this order:

    1. the build stamp, when the application is FROZEN
    2. --edition, from source
    3. DAP_EDITION, from source
    4. nothing — and that is an error, not a default

Rule 1 is the load-bearing one. In a packaged build the stamp is the ONLY
answer: `--edition gdm` handed to the Gaziray package is rejected outright
rather than ignored, because a flag that silently does nothing invites the
next person to look for the one that works. Admin is reached by the service
key on a USB stick and by nothing else (`panel.adminkey`).

Rule 4 is deliberate too. Running `python3 app.py` bare used to open the one
package that existed; now that there are several, "whichever the source tree
happens to hold" is not an answer anybody meant to give. The run stops and
names the editions instead.

The stamp is read ONLY when frozen. A generated `_stamp.py` left behind in a
developer's tree after a local package build must not quietly change what a
source run does.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from .. import i18n, settings
from .catalogue import (ADMIN_VIEWS, BASE_VIEWS, EDITIONS, IDS,  # noqa: F401
                        Edition, Project, app_name, find)


class EditionError(ValueError):
    """The edition could not be settled on. Always carries a rendered
    sentence: the two callers that raise it (`app.py`, the API) both print it
    straight to a person."""


_LOCK = threading.RLock()
_ACTIVE: Edition | None = None
_PROJECT: str = ""
# Projects delivered on the service key rather than built in. Admin mode only
# (see `panel.adminkey.pack`); cleared when admin mode ends.
_EXTRA: dict[str, Project] = {}
_ADMIN = False


# ── the build stamp ──────────────────────────────────────────────────────
def stamp():
    """The module `dabp.spec` generates into the package, or None.

    Absent from a source tree by design — it is gitignored, and reading it
    outside a frozen build is refused above.
    """
    if not settings.FROZEN:
        return None
    try:
        from . import _stamp                              # noqa: PLC0415
    except ImportError:
        return None
    return _stamp


def stamped_edition() -> str:
    module = stamp()
    return str(getattr(module, "EDITION", "") or "") if module else ""


# ── resolution ───────────────────────────────────────────────────────────
def resolve(requested: str | None = None) -> str:
    """The edition this process runs as. Raises EditionError if unsettled."""
    wanted = str(requested or "").strip().lower()
    baked = stamped_edition()

    if baked:
        if wanted and wanted != baked:
            raise EditionError(i18n.t("error.editionIsBakedIn",
                                      edition=baked, asked=wanted))
        chosen = baked
    else:
        chosen = wanted or str(os.environ.get("DAP_EDITION", "")).strip().lower()

    if not chosen:
        raise EditionError(i18n.t("error.editionRequired",
                                  editions=", ".join(IDS)))
    if find(chosen) is None:
        raise EditionError(i18n.t("error.editionUnknown", edition=chosen,
                                  editions=", ".join(IDS)))
    return chosen


# ── activation ───────────────────────────────────────────────────────────
def activate(edition_id: str, project_key: str = "") -> Edition:
    """Make this edition the running one. Safe to call again."""
    edition = find(edition_id)
    if edition is None:
        raise EditionError(i18n.t("error.editionUnknown", edition=edition_id,
                                  editions=", ".join(IDS)))
    global _ACTIVE, _ADMIN
    with _LOCK:
        _ACTIVE = edition
        _EXTRA.clear()
        settings.set_data_suffix(edition.id)
    _ADMIN = opens_as_admin()
    use_project(project_key or edition.default_project,
                allow_missing=True)
    return edition


def active() -> Edition:
    with _LOCK:
        if _ACTIVE is None:
            raise EditionError(i18n.t("error.editionRequired",
                                      editions=", ".join(IDS)))
        return _ACTIVE


def is_active() -> bool:
    with _LOCK:
        return _ACTIVE is not None


def reset() -> None:
    """Forget the activation. Used by tests, and by nothing else."""
    global _ACTIVE, _PROJECT, _ADMIN
    with _LOCK:
        _ACTIVE = None
        _PROJECT = ""
        _ADMIN = False
        _EXTRA.clear()
        settings.set_data_suffix("")


# ── admin mode ───────────────────────────────────────────────────────────
# The mode lives here rather than in `panel.adminkey` because it is a
# property of the RUN — which edition, which project, which screens — and
# not of the stick. The key module decides whether the door may open; this
# one records that it is.
def opens_as_admin() -> bool:
    """Does this build open in admin mode with nothing plugged in?

    ONLY IF IT HOLDS THE BUILD SECRET, and that is the entire rule now that
    there is no service edition to be one.

    THE SECRET IS THE BOOTSTRAP, and this is the whole reason it is one. The
    first service key cannot be made by inserting a service key, so the
    build secret stands in for the stick that does not exist yet: whoever
    holds it can write the first one.

    NO SHIPPED PACKAGE HOLDS IT. Every package is cut with the one-way
    digest and never the secret (`dabp.spec`), so in the field this is
    always false and the stick is the only way in — which is what the stick
    is for. It is true in one place only: a source run with
    DAP_ADMIN_KEY_SECRET in the environment, which is where keys are
    written.
    """
    # Imported here: `panel.adminkey` reads the edition to decide what to
    # do, so it cannot be imported while this module is still loading.
    from ..adminkey import secret as key_secret            # noqa: PLC0415
    return key_secret.can_write()


def admin() -> bool:
    with _LOCK:
        return _ADMIN


def mode() -> str:
    return "admin" if admin() else "field"


def set_admin(on: bool) -> bool:
    """Enter or leave admin mode. Returns the mode actually in effect.

    NEVER call this straight from a request: the caller must have checked
    that the mode may be entered at all — a recognised service key, or the
    build secret (`panel.api.routes.admin_routes`).

    LEAVING IS ALWAYS ALLOWED, including for a run that opened as admin on
    the secret. It used to be refused there, on the grounds that there was
    nothing to fall back to; there is — the customer's own field view, which
    is what the engineer wants to see when checking what the customer sees.
    Nothing is given up permanently: the secret is still in hand and the
    same run may raise itself again.
    """
    global _ADMIN
    with _LOCK:
        _ADMIN = bool(on)
        if not _ADMIN:
            _EXTRA.clear()
        return _ADMIN


def views() -> tuple[str, ...]:
    """The screens that may be opened right now.

    Read by the sidebar for what to draw AND by `panel.api.guard` for what to
    answer. One list, so hiding a screen and refusing its data can never
    disagree.
    """
    edition = active()
    if admin():
        return tuple(BASE_VIEWS) + tuple(ADMIN_VIEWS)
    return tuple(edition.views)


# ── projects ─────────────────────────────────────────────────────────────
def map_path(project: Project) -> Path:
    """Where this project's DeviceMap is: frozen, from source, or on a key."""
    if project.path:
        return Path(project.path)
    return settings.data_file(project.map_name, *project.source_path)


def checklist_path(project: Project | None = None) -> Path:
    """This project's checklist workbook, or the shared one.

    Most projects are trains built to the same drawing and share the file;
    a project whose devices are not in it (the demonstration stand) carries
    its own, because the workbook fills rows by IP template and would
    otherwise produce an empty report.
    """
    project = project or current_project()
    if project.checklist_name:
        return settings.data_file(project.checklist_name,
                                  *project.checklist_source)
    return Path(settings.EXCEL_TEMPLATE)


def available(project: Project) -> bool:
    """Has this project's DeviceMap actually been delivered?

    Asked of the filesystem rather than of a flag in the table: a map arrives
    as a file, and a project that exists in the table but cannot be opened is
    the failure mode a flag introduces.
    """
    try:
        return map_path(project).is_file()
    except OSError:
        return False


# ── the three service addresses ──────────────────────────────────────────
#
# The broker, the clock source and the PBX. See `Project.broker` for why they
# are not simply "the PISCU" and what went wrong while they were.
#
# THE FALLBACK IS THE PISCU, and it stays: three of the five projects have one
# PISCU that really is all three, and making them repeat their own address in
# the table would be one more thing to keep in step with the map.
#
# `inventory` is passed rather than looked up, because these are asked from
# inside a scan that already holds one and re-resolving it there would read
# the map again on every round.
def _service_address(inventory, template: str) -> str:
    """A project template resolved for this inventory's set, or the PISCU."""
    if template:
        # Imported here, not at module scope: `catalogue` may import nothing
        # but the standard library and this module is its only reader that
        # can. A top-level import would also make `editions` and `inventory`
        # import each other.
        from ..inventory.device_map import resolve_template  # noqa: PLC0415
        return resolve_template(template, inventory.set_no)
    return inventory.piscu_ip() or ""


def broker_ip(inventory) -> str:
    """Where the retained DeviceMap and the AppStatus messages are published."""
    return _service_address(inventory, current_project().broker)


def pbx_ip(inventory) -> str:
    """The PBX every SIP device is expected to report."""
    project = current_project()
    return _service_address(inventory, project.pbx or project.broker)


def ntp_ip(inventory) -> str:
    """The clock source written to devices and expected back from them."""
    project = current_project()
    return _service_address(inventory, project.ntp or project.broker)


def storage_checked() -> bool:
    """Does the open project's video equipment have storage worth asking about?"""
    return bool(current_project().storage)


def fixed_addressing() -> bool:
    """Is this project addressed in fixed form, with no train set to pick?"""
    return bool(current_project().fixed_addressing)


def prefix() -> int:
    """How wide this project's network is, or 0 when it states nothing.

    Settles both the mask written to a device and the width of the alias the
    panel gives itself — see `panel.editions.catalogue.Project.prefix`.

    ZERO IS NOT 24. Unstated means the run leaves whatever mask the device
    already has, which is what the intercom run has always done; a project
    that states one is making a claim the run should enforce.
    """
    return int(current_project().prefix or 0)


def add_extra(project: Project) -> None:
    """Register a project delivered on the service key (admin mode only)."""
    with _LOCK:
        _EXTRA[project.key] = project


def projects() -> tuple[Project, ...]:
    """Every project this process may open, built-in ones first."""
    edition = active()
    with _LOCK:
        extra = tuple(project for project in _EXTRA.values()
                      if project.key not in
                      {built.key for built in edition.projects})
    return tuple(edition.projects) + (extra if admin() else ())


def find_project(key: str) -> Project | None:
    wanted = str(key or "").strip().lower()
    return next((p for p in projects() if p.key == wanted), None)


def is_extra(project: Project) -> bool:
    with _LOCK:
        return project.key in _EXTRA


def current_project() -> Project:
    with _LOCK:
        key = _PROJECT
    return find_project(key) or active().projects[0]


def on_a_stand() -> bool:
    """Is the open project a demonstration stand rather than a train?

    One read depends on it — see `Project.stand` for which and why. Asked of
    the PROJECT rather than of a setting, so a package that carries both a
    train and a stand answers correctly for whichever is open.
    """
    return bool(current_project().stand)


def current_is_extra() -> bool:
    """Is the open project one that came off the service key?

    Asked BEFORE admin mode is given up, because giving it up is what takes
    the key's projects away — after that the question can no longer be
    answered, and the answer is what says whether the panel is about to be
    left looking at a device list this package is not supposed to have. See
    `panel.api.lifecycle.leave_admin`.
    """
    with _LOCK:
        return _PROJECT in _EXTRA


def use_project(key: str, *, allow_missing: bool = False) -> Project:
    """Point the panel at another project's DeviceMap.

    Only the path is set here; the state that belongs to the old project is
    dropped by `panel.api.lifecycle.switch_project`, which is the only caller
    outside activation. Splitting it that way keeps this module free of the
    queue, the credential store and the network.

    A SWITCH refuses a project whose DeviceMap has not been delivered — that
    is the VIP placeholder, and a dead entry in the menu has to say why.
    ACTIVATION does not, and must not: an edition whose own map is still
    missing has to open anyway, show the "DeviceMap not found" state every
    screen already knows how to show, and let `--self-test` name the gap.
    Refusing at activation would mean a package that cannot be started at
    all, which is a far worse way to report a missing file.
    """
    project = find_project(key)
    if project is None:
        raise EditionError(i18n.t("error.projectNotAvailable", project=key))
    if not allow_missing and not available(project):
        raise EditionError(i18n.t("error.projectNotDelivered",
                                  project=project.label))
    global _PROJECT
    with _LOCK:
        _PROJECT = project.key
        # DEVICE_MAP_FILE stays the last word: it is how a field engineer
        # points the panel at a hand-edited map, and an edition must not
        # take that away.
        if not os.environ.get("DEVICE_MAP_FILE"):
            settings.DEVICE_MAP = map_path(project)
    from ..inventory import device_map                     # noqa: PLC0415
    device_map.clear_cache()
    return project
