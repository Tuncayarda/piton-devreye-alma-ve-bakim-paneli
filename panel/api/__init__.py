"""The panel's service layer and its optional HTTP adapter.

The desktop window calls `PanelService` operations directly over the pywebview
bridge; in the default mode no HTTP server and no TCP port is opened.
`http_adapter` is only the adapter for the explicitly requested
browser/diagnostic mode. In both modes only this process talks to devices.

Security assumptions:
  · The HTTP adapter listens on 127.0.0.1 only. No external interface, no CORS.
  · A client can never choose a target by sending an IP or a device type. It
    sends a device id and the target is looked up in DeviceMap, so a hole in
    the UI cannot turn into the panel connecting to an arbitrary address.
  · Train set, device id and job id are validated server-side.
  · POST bodies pass type and size checks.
  · No GET/POST response ever contains a password or an Authorization header.
  · Static file serving cannot escape its directory.
"""

from .lifecycle import (check_admin_password, reset, set_admin_password, start)
from .response import ApiResponse
from .service import PanelService, SERVICE, call, call_enveloped

__all__ = ["ApiResponse", "PanelService", "SERVICE", "call",
           "call_enveloped", "check_admin_password", "reset",
           "set_admin_password", "start"]
