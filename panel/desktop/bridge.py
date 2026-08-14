#!/usr/bin/env python3
"""The pywebview bridge — the only surface exposed to the WebView.

This module opens no HTTP server. The UI is read into memory from the
single-file ``static/desktop.html`` built at packaging time, and every
exchange between Python and JavaScript goes through the local pywebview
bridge, where only ``invoke`` is exposed via ``Window.expose``.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
import threading
import time
import traceback
from urllib.parse import parse_qs, urlsplit

from .. import settings
from ..api import call_enveloped
from .. import i18n

PATH_LIMIT = 4096


def _error(status: int, message: str) -> dict:
    return {"ok": False, "status": int(status), "body": {"error": message}}


class PanelBridge:
    """A narrow, JSON-safe permission surface open to the WebView.

    The object itself is not handed over as ``js_api``. ``app.py`` adds only
    the bound ``invoke`` method to ``Window.expose``'s exact-name allowlist;
    hidden state and the service callable never enter the WebView object
    graph. The path also passes the service layer's fixed API allowlist, so no
    arbitrary Python function or file path can be run.
    """

    def __init__(self, dispatch=None, capability: str | None = None):
        self._dispatch = dispatch or call_enveloped
        self.capability = capability or secrets.token_urlsafe(32)
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", self.capability):
            raise ValueError(i18n.t("error.bridgeCapabilityInvalid"))
        self._condition = threading.Condition()
        self._in_flight = 0
        self._closing = False

    def invoke(self, capability=None, method=None, path=None, body=None,
               *extra):
        """Run one GET/POST API call as a safe result envelope."""
        with self._condition:
            if self._closing:
                return _error(503, "The panel is shutting down")
            self._in_flight += 1

        try:
            if (not isinstance(capability, str)
                    or not secrets.compare_digest(capability,
                                                  self.capability)):
                return _error(403, "The desktop bridge capability could not be verified")
            if extra:
                return _error(400, "Too many arguments in the bridge call")
            if not isinstance(method, str):
                return _error(400, "The request method is invalid")
            verb = method.upper()
            if verb not in ("GET", "POST"):
                return _error(405, "The request method is not supported")
            if not isinstance(path, str) or len(path) > PATH_LIMIT:
                return _error(400, "The request path is invalid")

            url = urlsplit(path)
            if (url.scheme or url.netloc or url.fragment
                    or not url.path.startswith("/api/")):
                return _error(400, "Only panel API paths may be used")

            if body is None:
                payload = {}
            elif isinstance(body, dict):
                payload = body
            else:
                return _error(400, "The request body must be an object")
            try:
                raw = json.dumps(payload, ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError):
                return _error(400, "The request body is not JSON serialisable")
            if len(raw) > settings.BODY_LIMIT:
                return _error(400, "The request body is too large")

            query = parse_qs(url.query, keep_blank_values=True)
            return self._dispatch(verb, url.path, query=query, body=payload)
        except Exception:
            # A Python traceback never leaks into the JS promise or onto the
            # user's screen.
            traceback.print_exc(file=sys.stderr)
            return _error(500, "Something unexpected went wrong in the panel")
        finally:
            with self._condition:
                self._in_flight -= 1
                if self._in_flight == 0:
                    self._condition.notify_all()

    def _close(self, timeout: float | None = None) -> bool:
        """Stop new calls and wait for the in-flight ones to finish.

        Underscore-prefixed on purpose: `invoke` must stay the ONLY
        public callable on this object (a regression test asserts it), so
        that nothing else can be reached should the instance ever end up
        in the WebView object graph.

        Production shutdown uses no time limit. Otherwise, clearing service
        state while a long device operation was still running could destroy
        the credentials and queues underneath it. ``timeout`` is an optional
        ceiling for controlled test/diagnostic calls only.
        """
        deadline = (None if timeout is None
                    else time.monotonic() + max(0.0, timeout))
        with self._condition:
            self._closing = True
            while self._in_flight:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._in_flight == 0
