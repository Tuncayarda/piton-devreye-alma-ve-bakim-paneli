#!/usr/bin/env python3
"""The optional HTTP adapter for browser/diagnostic mode.

Run (opens no window, for debugging):
    python3 -m panel.api --port 8790
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .. import i18n, settings
from .lifecycle import reset, set_admin_password, start
from .service import SERVICE


class Handler(BaseHTTPRequestHandler):
    server_version = f"{settings.APP_SLUG}/1.0"
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, payload,
              content_type="application/json; charset=utf-8"):
        body = (json.dumps(payload, ensure_ascii=False).encode("utf-8")
                if not isinstance(payload, (bytes, bytearray)) else payload)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_body(self) -> dict:
        """Read the POST body through type and size checks."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise ValueError(i18n.t("error.invalidContentLength"))
        if length < 0 or length > settings.BODY_LIMIT:
            raise ValueError(i18n.t("error.bodyTooLarge"))
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            raise ValueError(i18n.t("error.bodyNotJson"))
        if not isinstance(data, dict):
            raise ValueError(i18n.t("error.bodyMustBeObject"))
        return data

    def _serve_file(self, relative: str):
        """Send a file under static/; the directory cannot be escaped."""
        root = settings.STATIC_DIR.resolve()
        try:
            path = (root / unquote(relative).lstrip("/")).resolve()
            path.relative_to(root)
        except (OSError, ValueError):
            return self._send(404, {"error": "yok"})
        if not path.is_file():
            return self._send(404, {"error": "yok"})
        content_type, _ = mimetypes.guess_type(path.name)
        if path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        return self._send(200, path.read_bytes(),
                          content_type or "application/octet-stream")

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                return self._serve_file("index.html")
            if url.path.startswith(("/css/", "/js/")) or url.path in (
                    "/piton-logo.svg", "/piton-favicon.png"):
                return self._serve_file(url.path)
            if not url.path.startswith("/api/"):
                return self._send(
                    404, {"error": i18n.t("error.unknownPath")})
            response = SERVICE.call("GET", url.path,
                                    query=parse_qs(url.query))
            return self._send(response.status, response.body)
        except Exception:
            self._send_error()

    def do_POST(self):
        url = urlparse(self.path)
        try:
            body = self._read_body()
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        try:
            response = SERVICE.call("POST", url.path, body=body)
            return self._send(response.status, response.body)
        except Exception:
            self._send_error()

    def _send_error(self):
        """Adapter failure: a plain reply, detail only on stderr."""
        sys.stderr.write(traceback.format_exc())
        self._send(
            500, {"error": i18n.t("error.unexpectedPanelProblem")})


def serve(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """A server that listens on the local interface only."""
    if host != "127.0.0.1":
        raise ValueError("This service only runs on 127.0.0.1")
    start()
    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description=f"{i18n.t('app.name')} — local API (opens no window)")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--admin-password", default=None,
                        help="when given, the admin screen asks for this "
                             "password; it is never written anywhere")
    args = parser.parse_args()
    set_admin_password(args.admin_password)

    try:
        server = serve("127.0.0.1", args.port)
    except OSError as exc:
        print(f"[ERROR] Could not open port {args.port}: {exc}")
        return 1

    actual_port = int(server.server_address[1])
    print(f"API: http://127.0.0.1:{actual_port}   (Ctrl-C to stop)")
    print(f"DeviceMap: {settings.DEVICE_MAP}")
    print("Credentials are asked for in the UI and written nowhere.")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.shutdown()
        server.server_close()
        reset()
    return 0
