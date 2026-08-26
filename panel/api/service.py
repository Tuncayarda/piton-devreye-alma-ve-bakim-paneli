#!/usr/bin/env python3
"""The panel's use cases. Knows nothing about HTTP or pywebview."""
from __future__ import annotations

import json
import sys
import traceback
from urllib.parse import parse_qs, urlparse

from .. import i18n, settings
from ..errors import AuthError, DeviceError, user_message
from .guard import refusal
from .lifecycle import start
from .response import ApiResponse, respond
from .routes import GET_ROUTES, POST_ROUTES


class PanelService:
    """Dispatches API paths and turns expected errors into status codes."""

    @staticmethod
    def start() -> int:
        return start()

    @staticmethod
    def _validate_body(body) -> dict:
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise ValueError(i18n.t("error.bodyMustBeObject"))
        # Do not let the HTTP adapter's byte limit be bypassed by a direct
        # bridge call. No password is stored outside this transient JSON.
        try:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            raise ValueError(i18n.t("error.bodyNotSerialisable"))
        if len(raw) > settings.BODY_LIMIT:
            raise ValueError(i18n.t("error.bodyTooLarge"))
        return body

    def call(self, method: str, path: str, query=None,
             body=None) -> ApiResponse:
        """Call an API path; map expected errors onto status codes."""
        try:
            self.start()
            if not isinstance(path, str):
                raise ValueError(i18n.t("error.apiPathMustBeText"))
            url = urlparse(path)
            # A full URL cannot be handed to the bridge; only the app's own
            # API path.
            if url.scheme or url.netloc or not url.path.startswith("/api/"):
                return respond(404, {"error": i18n.t("error.unknownPath")})
            resolved_query = query if query is not None else parse_qs(url.query)
            if not isinstance(resolved_query, dict):
                raise ValueError(i18n.t("error.queryMustBeObject"))
            verb = str(method or "").upper()
            if verb == "GET":
                handler = GET_ROUTES.get(url.path)
                if handler is None:
                    return respond(404, {"error": i18n.t("error.unknownPath")})
                # Checked here rather than inside the handlers: one choke
                # point cannot be forgotten by the next route added.
                return refusal(url.path) or handler(resolved_query)
            if verb == "POST":
                handler = POST_ROUTES.get(url.path)
                if handler is None:
                    return respond(404, {"error": i18n.t("error.unknownPath")})
                checked = self._validate_body(body)
                return refusal(url.path, checked) or handler(checked)
            return respond(405, {"error": "unsupported method"})
        except LookupError as exc:
            return respond(404, {"error": str(exc)})
        except ValueError as exc:
            return respond(400, {"error": str(exc)})
        except FileNotFoundError as exc:
            # A DeviceMap that is not there. Not an unexpected fault: a
            # package whose own device list has not been delivered yet is a
            # real state now (see panel.editions), and every screen already
            # knows how to show "DeviceMap not found". Reported as a missing
            # thing rather than as a crash, so the screen says what is wrong
            # instead of "an unexpected problem".
            return respond(404, {"error": str(exc)})
        except AuthError as exc:
            return respond(401, {"error": user_message(exc), "auth": True})
        except DeviceError as exc:
            return respond(502, {"error": user_message(exc)})
        except Exception:
            # The raw trace goes to stderr only; never into the bridge or HTTP
            # body.
            sys.stderr.write(traceback.format_exc())
            return respond(
                500, {"error": i18n.t("error.unexpectedPanelProblem")})

    def call_enveloped(self, method: str, path: str, query=None,
                       body=None) -> dict:
        """A JSON-only safe envelope for the desktop bridge."""
        response = self.call(method, path, query=query, body=body)
        try:
            # Apply the same normalisation HTTP's JSON conversion would, so a
            # Path, bytes or custom object cannot leak to the bridge.
            payload = json.loads(json.dumps(response.body, ensure_ascii=False))
        except Exception:
            sys.stderr.write(traceback.format_exc())
            response = ApiResponse(
                500, {"error": i18n.t("error.unexpectedPanelProblem")})
            payload = response.body
        return {
            "ok": 200 <= response.status < 400,
            "status": response.status,
            "body": payload,
        }


SERVICE = PanelService()


def call(method: str, path: str, query=None, body=None) -> ApiResponse:
    """Shared API entry for non-HTTP adapters."""
    return SERVICE.call(method, path, query=query, body=body)


def call_enveloped(method: str, path: str, query=None, body=None) -> dict:
    """The safe JSON envelope the pywebview bridge can return directly."""
    return SERVICE.call_enveloped(method, path, query=query, body=body)
