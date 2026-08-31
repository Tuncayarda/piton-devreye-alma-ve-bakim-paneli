#!/usr/bin/env python3
"""Contract tests for the transport-free panel service and its HTTP adapter."""
from __future__ import annotations

import ast
from contextlib import redirect_stderr
import importlib
from io import StringIO
import json
import pkgutil
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from panel import api, config_sync, i18n, settings
from panel.api import lifecycle, routes
from panel.api.routes import GET_ROUTES
from panel.errors import AuthError, DeviceError, NotFoundError

from .support import fakes
from .support.base import ServiceTest


def _topology():
    return fakes.device_map([{
        "Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
        "Type": "Announcement", "SubType": "Intercom", "Port": "11",
        "Status": {"NoError": True},
    }], switch_ip="127.0.0.1")


class PanelServiceContract(ServiceTest):

    def setUp(self):
        super().setUp()
        self.build_map(_topology())

    def test_get_service_and_http_agree(self):
        base = self.start_service()
        for path in ("/api/version", "/api/project?set=1",
                     "/api/state?set=1", "/api/device?set=1&id=missing",
                     "/api/unknown"):
            with self.subTest(path=path):
                status, body = self.call(base, path)
                url = urlparse(path)
                direct = api.call("GET", url.path, query=parse_qs(url.query))
                self.assertEqual(direct.status, status)
                self.assertEqual(direct.body, body)

    def test_post_service_and_http_agree(self):
        base = self.start_service()
        for path, body in (("/api/admin/login", {"password": ""}),
                           ("/api/job/cancel", {"id": "missing"}),
                           ("/api/unknown", {})):
            with self.subTest(path=path):
                status, http_body = self.call(base, path, body)
                direct = api.call("POST", path, body=body)
                self.assertEqual(direct.status, status)
                self.assertEqual(direct.body, http_body)

    def test_bridge_envelope_returns_json_types_only(self):
        ok = api.call_enveloped("GET", "/api/version")
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["status"], 200)
        self.assertIn("version", ok["body"])
        json.dumps(ok, ensure_ascii=False)

        failed = api.call_enveloped("GET", "/api/unknown")
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["status"], 404)
        # Compared against the catalogue, not a literal: the wording is a
        # translation now, and pinning English here would make the test
        # fail on a Turkish machine rather than on a real regression.
        self.assertEqual(failed["body"]["error"],
                         i18n.t("error.unknownPath"))

    def test_start_loads_defaults_only_once(self):
        with patch.object(lifecycle, "_STARTED", False), \
                patch.object(lifecycle, "_LOADED_DEFAULTS", 0), \
                patch.object(config_sync, "load_saved_defaults",
                             return_value=3) as load:
            self.assertEqual(lifecycle.start(), 3)
            self.assertEqual(lifecycle.start(), 3)
            load.assert_called_once_with()

    def test_service_error_mapping(self):
        """Only our own NotFoundError means 404; a bare lookup is a bug.

        The whole LookupError family used to map to 404 — which reported a
        KeyError from a handler bug as a calm "not found" whose body quoted
        a Python key, with no trace anywhere. Now the class our raisers use
        (panel.errors.NotFoundError, always a translated sentence) is the
        only lookup that means "not found"; bare KeyError, IndexError and
        LookupError fall through to the 500 handler, which logs.
        """
        cases = (
            (NotFoundError("missing"), 404, False),
            (ValueError("invalid"), 400, False),
            (AuthError("credentials required"), 401, True),
            (DeviceError("the device could not be read"), 502, False),
        )
        for exc, status, auth in cases:
            with self.subTest(exc=type(exc).__name__), \
                    patch.dict(GET_ROUTES, {"/api/version": _raise(exc)}):
                response = api.call("GET", "/api/version")
                self.assertEqual(response.status, status)
                self.assertEqual(bool(response.body.get("auth")), auth)

        for exc in (RuntimeError("internal detail"),
                    LookupError("internal detail"),
                    KeyError("internal detail"),
                    IndexError("internal detail")):
            stderr = StringIO()
            with self.subTest(exc=type(exc).__name__), \
                    patch.dict(GET_ROUTES, {"/api/version": _raise(exc)}), \
                    redirect_stderr(stderr):
                response = api.call("GET", "/api/version")
                self.assertEqual(response.status, 500)
                self.assertNotIn("internal detail",
                                 json.dumps(response.body, ensure_ascii=False))
                self.assertIn(type(exc).__name__, stderr.getvalue())


def _raise(exc):
    def handler(query):
        raise exc
    return handler


class RouteRegistration(unittest.TestCase):
    """Every route module on disk is wired into the merged tables."""

    def test_every_route_module_on_disk_is_registered(self):
        """Both lists in panel/api/routes/__init__.py, for EVERY module.

        A module imported but left out of `_MODULES` loads cleanly and then
        404s on every path it defines — the file's own documented "long
        afternoon". tests/test_switch_api.py pins this for switch_routes
        alone; this walks the package, so the next module added is covered
        on the day its file appears.
        """
        found = sorted(name for _, name, _ in
                       pkgutil.iter_modules(routes.__path__)
                       if name.endswith("_routes"))
        # Named so the walk cannot pass by finding nothing to check.
        self.assertIn("general_routes", found)
        self.assertEqual(
            sorted(module.__name__.rsplit(".", 1)[-1]
                   for module in routes._MODULES),
            found)
        for name in found:
            module = importlib.import_module(f"panel.api.routes.{name}")
            for table, merged in ((getattr(module, "GET", {}),
                                   routes.GET_ROUTES),
                                  (getattr(module, "POST", {}),
                                   routes.POST_ROUTES)):
                for path, handler in table.items():
                    with self.subTest(module=name, path=path):
                        # Identity, not membership: a path merely PRESENT in
                        # the merged table may be another module's handler
                        # shadowing this one.
                        self.assertIs(merged.get(path), handler)


class LayeringSeams(unittest.TestCase):
    """Two module-boundary rules from the layering rework, pinned as source.

    Both regressions would import and run fine — a re-closed cycle and a
    forked predicate only present their bill later — which is why they are
    pinned by reading the files rather than by exercising them.
    """

    def test_authority_never_imports_the_api_at_module_level(self):
        """panel.authority sits BELOW the API. The unwind it triggers lives
        in panel.api.lifecycle, which REGISTERS a callback
        (`authority.on_leave`) precisely so authority need not import
        upwards; a module-level import of panel.api here would re-close the
        authority <-> api cycle that registration untangled. Lazy imports
        inside functions are the allowed escape and are not counted."""
        source = (settings.ROOT / "panel" / "authority.py").read_text(
            encoding="utf-8")
        offending = [ast.dump(node) for node in ast.parse(source).body
                     if _imports_panel_api(node)]
        self.assertEqual(offending, [])

    def test_jobs_writing_is_the_single_predicate_in_the_api(self):
        """"Is a write in the way?" is answered once, by `jobs.writing()`.

        Three API callers used to scan the queue against WRITING_JOB_KINDS
        themselves and disagreed about QUEUED jobs (the light refresh only
        counted RUNNING). The constant lives in panel.jobs now; the one
        mention left in panel/api is the presenters re-export kept for its
        old importers, and none of the route modules reaches for it.
        """
        holders = {}
        for path in sorted((settings.ROOT / "panel" / "api").rglob("*.py")):
            mentions = [line.split("#")[0].strip()
                        for line
                        in path.read_text(encoding="utf-8").splitlines()
                        if "WRITING_JOB_KINDS" in line.split("#")[0]]
            if mentions:
                holders[path.name] = mentions
        self.assertEqual(
            holders,
            {"presenters.py": ["from ..jobs import WRITING_JOB_KINDS"]})


def _imports_panel_api(node) -> bool:
    """Does this top-level statement import panel.api, in any spelling?"""
    if isinstance(node, ast.Import):
        return any(alias.name == "panel.api"
                   or alias.name.startswith("panel.api.")
                   for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if node.level:                       # relative: from .api / from .
            if module == "api" or module.startswith("api."):
                return True
            return not module and any(alias.name == "api"
                                      for alias in node.names)
        return module == "panel.api" or module.startswith("panel.api.")
    return False


if __name__ == "__main__":
    unittest.main()
