"""Elevated privileges: the check, asking the user, and restarting.

The panel reads and flushes the ARP cache, writes IPs to devices and manages
switch ports. None of that works reliably as an ordinary user; the most
expensive example was seen in the field: with the ARP entry unflushable,
devices sharing one address hide behind each other and the run reports
"device not found".

If the privilege is missing the panel does not open. Instead a window appears
offering two ways out — restart elevated, or quit. A third way (continue
unprivileged) is deliberately absent: a half-working panel is worse than none.

Elevation happens ONLY through the operating system's own permission dialog;
no password enters this process and nothing is handed to a terminal:

    Windows   ShellExecuteW "runas"  → UAC dialog
    macOS     osascript "with administrator privileges" → system dialog
    Linux     pkexec → polkit dialog
"""

from .flow import require_elevation
from .privileges import (elevate, elevation_plan, is_elevated, log_path,
                         protected_folder)
from .prompt import ask, hide_dock_icon

__all__ = ["ask", "elevate", "elevation_plan", "hide_dock_icon",
           "is_elevated", "log_path", "protected_folder",
           "require_elevation"]
