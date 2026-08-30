#!/usr/bin/env python3
"""The other customers' projects, shipped sealed and opened in admin mode.

Every package carries every project's device list now, but only its own in
the clear: the rest are sealed with K, the value written on the service key
(`vault.py`). A customer running their own package cannot open them and
cannot list them — `editions.projects()` offers extras only in admin mode,
and the bytes are unreadable either way.

WHAT THIS MODULE DOES is turn "there is a sealed blob in the bundle" into a
`Project` the rest of the panel can open, and it does that by REUSING THE
PATH THE SERVICE KEY ALREADY TOOK. A map delivered on a stick is copied into
a session directory and opened from there (`pack.py`); a sealed map is
decrypted into that same directory and opened the same way. So the decrypted
files live exactly as long as the USB copies do — `pack.clear_session()`
removes both, and `lifecycle.leave_admin` already calls it.

NOTHING IS WRITTEN BACK. The bundle keeps its sealed copy; what lands in the
session directory is a temporary that goes when admin mode does.

FROM SOURCE THERE IS NOTHING TO OPEN. A checkout has every map sitting in
`devicemaps/` in the clear, because that is where they are authored and where
`dabp.spec` reads them to seal them. So a source run in admin mode simply
registers the catalogue's own rows and skips the decryption entirely — same
projects, same labels, no temporary files.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from .. import settings
from ..editions import Project, catalogue
from . import pack, secret, vault

# The suffix a sealed file carries in the bundle. `dabp.spec` writes them.
SUFFIX = ".sealed"


def sealed_name(name: str) -> str:
    return f"{name}{SUFFIX}"


def _key(explicit: bytes | None) -> bytes:
    """K, from whichever of the three places has it.

    Imported late: the watcher imports this module, so reaching for it at
    module level would close a cycle. It is asked SECOND because a caller
    that already has the key in its hand — the watcher, holding the file it
    has just recognised — should not have its answer re-derived from global
    state that may have moved on since.
    """
    if explicit:
        return bytes(explicit)
    try:
        from .watcher import WATCH                         # noqa: PLC0415
        live = WATCH.content_key()
    except Exception:
        live = b""
    if live:
        return bytes(live)
    return secret.content_key() or b""


def foreign_projects() -> tuple[Project, ...]:
    """Every catalogue project that is not this edition's own."""
    from .. import editions                                # noqa: PLC0415
    try:
        mine = {project.key for project in editions.active().projects}
    except Exception:
        return ()
    return tuple(project for project in catalogue.ALL_PROJECTS
                 if project.key not in mine)


def unlock(key: bytes | None = None) -> int:
    """Register every foreign project this run can actually open.

    Returns how many were registered. NEVER RAISES: this is called from the
    watcher's thread and from the path that enters admin mode, and a bundle
    with one unreadable file in it must leave both working.
    """
    registered = 0
    for project in foreign_projects():
        try:
            opened = _resolve(project, key)
        except Exception:
            opened = None
        if opened is None:
            continue
        try:
            from .. import editions                        # noqa: PLC0415
            editions.add_extra(opened)
            registered += 1
        except Exception:
            continue
    return registered


def _resolve(project: Project, key: bytes | None) -> Project | None:
    """This project as something openable, or None if it cannot be opened.

    Three answers, in the order they are cheap:

      * the map is already in the clear (a source tree) — the catalogue row
        is used as it stands, and nothing is decrypted or copied;
      * a sealed blob is in the bundle and K is in hand — decrypted into the
        session directory, and the row is re-pointed at the copy;
      * anything else — None, and the project is simply not offered.
    """
    plain = settings.data_file(project.map_name, *project.source_path)
    try:
        if plain.is_file():
            return project
    except OSError:
        pass

    blob = _sealed_bytes(project.map_name, project.source_path)
    if blob is None:
        return None
    material = _key(key)
    if not material:
        return None
    opened = vault.unseal(material, blob)
    if opened is None:
        return None

    target = pack.session_dir() / project.map_name
    try:
        target.write_bytes(opened)
    except OSError:
        return None

    return dataclasses.replace(
        project,
        path=str(target),
        # Flat, like the bundle root it would have come from: `map_path`
        # prefers `path` and never looks at these, but a row whose two
        # halves disagree is a trap for whoever reads it next.
        source_path=(project.map_name,),
        **_checklist(project, material),
    )


def _checklist(project: Project, material: bytes) -> dict:
    """The workbook fields for a decrypted project.

    Its own workbook when one was sealed beside the map, and the shared
    template otherwise — which is what `runtime.checklist_path` falls back
    to when `checklist_name` is empty. A project filled from another
    project's workbook produces a report with no rows in it (the workbook
    matches by IP template), so guessing here is worse than falling back.
    """
    if not project.checklist_name:
        return {"checklist_name": "", "checklist_source": (),
                "checklist_file": ""}
    blob = _sealed_bytes(project.checklist_name, project.checklist_source)
    opened = vault.unseal(material, blob) if blob is not None else None
    if opened is None:
        return {"checklist_name": "", "checklist_source": (),
                "checklist_file": ""}
    target = pack.session_dir() / project.checklist_name
    try:
        target.write_bytes(opened)
    except OSError:
        return {"checklist_name": "", "checklist_source": (),
                "checklist_file": ""}
    return {"checklist_name": project.checklist_name,
            "checklist_source": (project.checklist_name,),
            "checklist_file": str(target)}


def _sealed_bytes(name: str, source_path) -> bytes | None:
    """The sealed blob for a file, from the bundle or from the tree."""
    for candidate in _sealed_paths(name, source_path):
        try:
            if not candidate.is_file():
                continue
            if candidate.stat().st_size > vault.MAX_BYTES + vault.HEADER:
                continue
            return candidate.read_bytes()
        except OSError:
            continue
    return None


def _sealed_paths(name: str, source_path) -> tuple[Path, ...]:
    """Where a sealed file could be: beside the bundle's copy, or the tree's.

    Both are tried rather than branching on `settings.FROZEN`, because the
    sealed files are also written into a source tree by the packaging tests
    and by `tools/seal_projects.py`, and a branch would make the tests
    exercise a path the field never takes.
    """
    sealed = sealed_name(name)
    paths = [settings.resource_dir() / sealed]
    if source_path:
        tail = (*source_path[:-1], sealed_name(source_path[-1]))
        paths.append(settings.ROOT.joinpath(*tail))
    return tuple(dict.fromkeys(paths))
