"""HTTP-shaped route tables, gathered from the per-topic modules."""

from . import (admin_routes, checklist_routes, config_routes,
               edition_routes, firmware_routes, general_routes,
               ip_routes, network_routes, session_routes,
               telemetry_routes)

_MODULES = (general_routes, edition_routes, admin_routes, session_routes,
            ip_routes, network_routes, config_routes, firmware_routes,
            checklist_routes, telemetry_routes)

GET_ROUTES: dict = {}
POST_ROUTES: dict = {}
for module in _MODULES:
    GET_ROUTES.update(getattr(module, "GET", {}))
    POST_ROUTES.update(getattr(module, "POST", {}))

__all__ = ["GET_ROUTES", "POST_ROUTES"]
