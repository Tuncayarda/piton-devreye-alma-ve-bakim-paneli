#!/usr/bin/env python3
"""The whole unprivileged-startup path."""
from __future__ import annotations

import platform

from .. import i18n

from .privileges import (elevate, elevation_plan, explanation, log_path,
                         protected_folder)
from .prompt import ask, hide_dock_icon


def require_elevation(write=print) -> int:
    """Handle an unprivileged start. Returns the process exit code.

    0 is returned only when the elevated process started — meaning this
    process handed over its work. Every other path returns 1: the app did not
    open.
    """
    # There is one way: the system's own permission dialog. No handing over to
    # a terminal — the user grants permission in the dialog, the app has no
    # business with a terminal.
    plan = elevation_plan()
    hint = ""
    protected = protected_folder()
    if protected:
        # In this folder the elevated process cannot read the app's own files
        # (see PROTECTED_FOLDERS). Said BEFORE the attempt so the password is
        # not asked for nothing.
        hint = (f"The application is in the {protected} folder. macOS does "
                "not allow an application in a protected folder to be "
                "started from an administrator prompt: move it out of that "
                "folder.")
    write("[ERROR] " + explanation().replace("\n\n", " "))
    if hint:
        write(hint)
    if ask(can_elevate=bool(plan["kind"]), hint=hint) != "elevate":
        return 1

    # This process now only starts and verifies the new one; it has nothing
    # left on screen. Without removing the icon here it sits next to the new
    # panel as a second app for a few seconds.
    hide_dock_icon()
    started, error = elevate(plan)
    if started:
        write(i18n.t("elevate.restarting"))
        if platform.system() != "Windows":
            write(i18n.t("elevate.newProcessOutput", path=log_path()))
        return 0

    write(f"[ERROR] {error}")
    ask(error or explanation(), can_elevate=False, hint=hint)
    return 1
