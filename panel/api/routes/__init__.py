"""HTTP-shaped route tables, gathered from the per-topic modules."""

from . import (adb_routes, admin_routes, checklist_routes, config_routes,
               edition_routes, firmware_routes, general_routes,
               ip_routes, network_routes, remote_routes, session_routes,
               switch_routes, telemetry_routes)

# BOTH LISTS, ALWAYS. The import above is what makes the module load; this
# tuple is what makes its routes reachable. A module added to one and not the
# other fails silently — the paths simply 404 — which is a long afternoon.
_MODULES = (general_routes, edition_routes, admin_routes, remote_routes,
            session_routes, ip_routes, network_routes, config_routes,
            firmware_routes, checklist_routes, telemetry_routes, adb_routes,
            switch_routes)

GET_ROUTES: dict = {}
POST_ROUTES: dict = {}
for module in _MODULES:
    GET_ROUTES.update(getattr(module, "GET", {}))
    POST_ROUTES.update(getattr(module, "POST", {}))

__all__ = ["GET_ROUTES", "POST_ROUTES"]
