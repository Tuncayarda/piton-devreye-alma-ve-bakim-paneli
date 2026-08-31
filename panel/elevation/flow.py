#!/usr/bin/env python3
"""The whole unprivileged-startup path."""
from __future__ import annotations

import os
import platform

from .. import i18n

from .privileges import (elevate, elevation_plan, explanation, log_path,
                         protected_folder, reasons)
from .prompt import hide_dock_icon, show_failure


def require_elevation(write=print) -> int:
    """Handle an unprivileged start. Returns the process exit code.

    The operating system's own password box is the question, and the only
    one: there is no window of ours asking whether to restart elevated. That
    window used to come first, and it asked something it could not grant —
    the user said yes to us and then yes again to the system, two dialogs for
    one decision.

    0 is returned only when the elevated process started, meaning this process
    handed its work over. Every other path returns 1: the panel does not open
    without the privilege, and no path leads to an unprivileged start.
    """
    # Unattended (CI, a scripted check): the system box would sit there
    # waiting for a password nobody is present to type.
    if os.environ.get("PANEL_ELEVATION_PROMPT") == "0":
        write("[ERROR] " + explanation().replace("\n\n", " "))
        return 1

    plan = elevation_plan()
    hint = ""
    protected = protected_folder()
    if protected:
        # In this folder the elevated process cannot read the app's own files
        # (see PROTECTED_FOLDERS). Said BEFORE the attempt so the password is
        # not asked for nothing.
        # Through the catalogue like every other sentence this flow prints:
        # the person reading this failure is the person the language switch
        # exists for.
        hint = i18n.t("elevate.protectedFolderHint", folder=protected)
    write("[ERROR] " + explanation().replace("\n\n", " "))
    for reason in reasons():
        write(f"        - {reason}")
    if hint:
        write(hint)

    started, error = elevate(plan)
    if started:
        # Only now. The Dock icon has to stay while the password box is up —
        # a system prompt whose application is invisible looks like it came
        # from nowhere — and it has to stay if the attempt fails, or the
        # window explaining why cannot come to the front. From here the old
        # process is only verifying the new one (see new_process_status) and
        # has nothing left to show.
        hide_dock_icon()
        write(i18n.t("elevate.restarting"))
        if platform.system() != "Windows":
            write(i18n.t("elevate.newProcessOutput", path=log_path()))
        return 0

    write(f"[ERROR] {error}")
    show_failure(error or explanation(), hint=hint)
    return 1
