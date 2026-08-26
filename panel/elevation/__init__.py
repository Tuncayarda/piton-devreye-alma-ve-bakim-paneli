"""Elevated privileges: the check, the system prompt, and restarting.

The panel reads and flushes the ARP cache, writes IPs to devices and manages
switch ports. None of that works reliably as an ordinary user; the most
expensive example was seen in the field: with the ARP entry unflushable,
devices sharing one address hide behind each other and the run reports
"device not found".

If the privilege is missing the panel does not open. Starting it goes STRAIGHT
to the operating system's password box — there is no window of ours asking
whether to elevate first. That window used to exist and it asked something it
could not grant: the user answered yes to us, then yes again to the system.

Declining the system box ends the run. A window then says why the panel could
not open — because somebody who double-clicked the app is otherwise left with
an icon that bounced once and did nothing — and offers no way in. Continuing
unprivileged is deliberately absent: a half-working panel is worse than none.

Elevation happens ONLY through the operating system's own permission dialog;
no password enters this process and nothing is handed to a terminal:

    Windows   ShellExecuteW "runas"  → UAC dialog
    macOS     osascript "with administrator privileges" → system dialog
    Linux     pkexec → polkit dialog
"""

from .flow import require_elevation
from .privileges import (elevate, elevation_plan, is_elevated, log_path,
                         protected_folder)
from .prompt import hide_dock_icon, show_failure

__all__ = ["elevate", "elevation_plan", "hide_dock_icon", "is_elevated",
           "log_path", "protected_folder", "require_elevation",
           "show_failure"]
