#!/usr/bin/env python3
"""The panel's use cases. Knows nothing about HTTP or pywebview."""
from __future__ import annotations

import json
import sys
import traceback
from urllib.parse import parse_qs, urlparse

from .. import settings
from ..errors import AuthError, DeviceError, user_message
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
            raise ValueError("The body must be an object")
        # Do not let the HTTP adapter's byte limit be bypassed by a direct
        # bridge call. No password is stored outside this transient JSON.
        try:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            raise ValueError("The body must be JSON serialisable")
        if len(raw) > settings.BODY_LIMIT:
            raise ValueError("The request body is too large")
        return body

    def call(self, method: str, path: str, query=None,
             body=None) -> ApiResponse:
        """Call an API path; map expected errors onto status codes."""
        try:
            self.start()
            if not isinstance(path, str):
                raise ValueError("The API path must be text")
            url = urlparse(path)
            # A full URL cannot be handed to the bridge; only the app's own
            # API path.
            if url.scheme or url.netloc or not url.path.startswith("/api/"):
                return respond(404, {"error": "unknown path"})
            resolved_query = query if query is not None else parse_qs(url.query)
            if not isinstance(resolved_query, dict):
                raise ValueError("The query must be an object")
            verb = str(method or "").upper()
            if verb == "GET":
                handler = GET_ROUTES.get(url.path)
                if handler is None:
                    return respond(404, {"error": "unknown path"})
                return handler(resolved_query)
            if verb == "POST":
                handler = POST_ROUTES.get(url.path)
                if handler is None:
                    return respond(404, {"error": "unknown path"})
                return handler(self._validate_body(body))
            return respond(405, {"error": "unsupported method"})
        except LookupError as exc:
            return respond(404, {"error": str(exc)})
        except ValueError as exc:
            return respond(400, {"error": str(exc)})
        except AuthError as exc:
            return respond(401, {"error": user_message(exc), "auth": True})
        except DeviceError as exc:
            return respond(502, {"error": user_message(exc)})
        except Exception:
            # The raw trace goes to stderr only; never into the bridge or HTTP
            # body.
            sys.stderr.write(traceback.format_exc())
            return respond(500,
                           {"error": "Something unexpected went wrong in the panel"})

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
                500, {"error": "Something unexpected went wrong in the panel"})
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
