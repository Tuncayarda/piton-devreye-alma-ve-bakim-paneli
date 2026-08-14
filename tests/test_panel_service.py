#!/usr/bin/env python3
"""Contract tests for the transport-free panel service and its HTTP adapter."""
from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from panel import api, config_sync, i18n
from panel.api import lifecycle
from panel.api.routes import GET_ROUTES
from panel.errors import AuthError, DeviceError

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
        cases = (
            (LookupError("missing"), 404, False),
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

        stderr = StringIO()
        with patch.dict(GET_ROUTES,
                        {"/api/version": _raise(RuntimeError("internal detail"))}), \
                redirect_stderr(stderr):
            response = api.call("GET", "/api/version")
        self.assertEqual(response.status, 500)
        self.assertNotIn(
            "internal detail", json.dumps(response.body, ensure_ascii=False))
        self.assertIn("RuntimeError", stderr.getvalue())


def _raise(exc):
    def handler(query):
        raise exc
    return handler


if __name__ == "__main__":
    import unittest
    unittest.main()
