"""One program, one package per customer.

The panel is commissioned by several operators on several trains, and each of
them may only see their own project. That separation is made at BUILD time
rather than behind a login: every edition is packaged on its own and carries
only its own DeviceMap, so another customer's device list, addresses and SIP
extensions are not merely hidden — they are not in the file.

`catalogue` holds the table (stdlib only, because `dabp.spec` reads it too).
`runtime` answers everything the table cannot: which edition this process is,
which project is open, whether admin mode is on, and where a DeviceMap
actually lives. `_stamp` is written into the package by the build and exists
nowhere else.

Admin is a MODE, not an account. There is no role screen and no password: the
`admin` edition opens as admin, and every other edition is raised by the
service key on a USB stick (`panel.adminkey`).
"""

from .catalogue import (ADMIN_VIEWS, BASE_VIEWS, EDITIONS, IDS, Edition,
                        Project, app_name, find)
from .runtime import (EditionError, activate, active, add_extra, admin,
                      available, broker_ip, checklist_path, current_is_extra,
                      current_project, fixed_addressing,
                      ntp_ip, on_a_stand, pbx_ip, prefix, storage_checked,
                      find_project, is_active, is_extra, map_path, mode,
                      opens_as_admin, projects, reset, resolve,
                      set_admin, stamp, stamped_edition, use_project,
                      views)

__all__ = [
                        "ADMIN_VIEWS",
                        "BASE_VIEWS",
                        "EDITIONS",
                        "IDS",
                        "Edition",
                        "EditionError",
                        "Project",
                        "activate",
                        "active",
                        "add_extra",
                        "admin",
                        "app_name",
                        "available",
                        "broker_ip",
                        "checklist_path",
                        "current_is_extra",
                        "current_project",
                        "find",
                        "find_project",
                        "fixed_addressing",
                        "is_active",
                        "is_extra",
                        "map_path",
                        "mode",
                        "ntp_ip",
                        "on_a_stand",
                        "opens_as_admin",
                        "pbx_ip",
                        "prefix",
                        "projects",
                        "reset",
                        "resolve",
                        "set_admin",
                        "stamp",
                        "stamped_edition",
                        "storage_checked",
                        "use_project",
                        "views",
]
