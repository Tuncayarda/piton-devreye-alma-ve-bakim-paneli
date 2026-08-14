#!/usr/bin/env python3
"""Commissioning and Maintenance Panel — desktop application.

In normal desktop mode the UI is loaded into memory as a single HTML file and
Python talks to JavaScript over pywebview's direct bridge. No local HTTP
server, TCP port or loopback connection is opened, so network filters like
Npcap/WFP cannot affect the app's own UI traffic.

HTTP starts only when ``--browser`` is asked for explicitly, for
development/diagnostics. On shutdown the job queue stops, the MQTT listener
closes and every device credential in memory is forgotten (see
panel.api.reset).

The app runs elevated; reading the network interface, the ARP cache and switch
ports requires it. Without the privilege the panel does not open — instead the
user gets a window offering to restart elevated or quit (see panel.elevation).

Run:
    python3 app.py
    python3 app.py --browser               # open in a browser, not a window
    python3 app.py --admin-password ****   # protect the admin screen
    python3 app.py --self-test             # verify without opening a window
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from panel import elevation                          # noqa: E402
from panel.elevation import is_elevated              # noqa: F401,E402  (test patch point)

MINIMUM_PYTHON = (3, 10)
WIDTH, HEIGHT = 1440, 900

PYWEBVIEW_MISSING = (
    "pywebview is required for the application window and is not installed."
    "\n\n"
    "Install it with:\n"
    "    python3 -m pip install -r docs/requirements.txt\n\n"
    "To try it without a window:\n"
    "    python3 app.py --browser"
)


def write(message: str) -> None:
    try:
        print(message)
    except Exception:
        pass


def http_ready(url: str, seconds: float = 5.0) -> bool:
    """Confirm the browser-mode HTTP adapter really answers."""
    import json
    import time
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with opener.open(f"{url}/api/version", timeout=0.5) as response:
                data = json.loads(response.read())
            if (response.status == 200 and isinstance(data, dict)
                    and isinstance(data.get("version"), str)):
                return True
        except (OSError, ValueError):
            time.sleep(0.05)
    return False


def set_macos_identity(name: str) -> None:
    """Show the app's name in the Dock instead of the interpreter's."""
    if platform.system() != "Darwin" or getattr(sys, "frozen", False):
        return
    try:
        from Foundation import NSBundle
        info = (NSBundle.mainBundle().localizedInfoDictionary()
                or NSBundle.mainBundle().infoDictionary())
        if info is not None:
            info["CFBundleName"] = name
            info["CFBundleDisplayName"] = name
    except Exception:
        pass


def self_test() -> int:
    """Verify the production desktop path without a window or a socket."""
    from panel import api, i18n, settings
    from panel.desktop import PanelBridge, load_html
    from panel.inventory import device_map

    outcomes = []

    def check(name: str, condition: bool, extra: str = "") -> bool:
        write(f"  [{'OK  ' if condition else 'FAIL'}] {name}"
              + (f" — {extra}" if extra else ""))
        outcomes.append(condition)
        return condition

    write(f"{i18n.t('app.name')} {settings.APP_VERSION} — self-test")

    check("DeviceMap found", settings.DEVICE_MAP.exists(),
          str(settings.DEVICE_MAP))
    check("Excel template found", settings.EXCEL_TEMPLATE.exists())
    # The message catalogue is DATA sitting next to a package, so it is
    # carried into the bundle by hand (see dabp.spec). Missing, the panel
    # still opens — with every label showing its raw key instead of text.
    for language in i18n.LANGUAGES:
        check(f"messages/{language}.json", bool(i18n.catalogue(language)),
              str(i18n.MESSAGES_DIR))
    for asset in ("index.html", "desktop.html", "css/base.css", "js/app.js",
                  "piton-logo.svg", "piton-favicon.png"):
        check(f"static/{asset}", (settings.STATIC_DIR / asset).exists())
    # The three field scripts (see panel.script_loader). In a packaged app
    # they are copied into the bundle; if one is missing, switch reads, IP
    # assignment or the Excel export will not work in the field — better to
    # find out where the package is built.
    for name, path in (("Switch Management Panel backend",
                        settings.SWITCH_API_SCRIPT),
                       ("Field verification script",
                        settings.DEVICE_VERIFY_SCRIPT),
                       ("IP assignment script", settings.IP_ASSIGN_SCRIPT)):
        check(name, path.exists(), str(path))

    try:
        inventory = device_map.load(1)
        check("DeviceMap read", len(inventory.devices) > 0,
              f"{len(inventory.devices)} devices")
    except Exception as exc:
        check("DeviceMap read", False, str(exc))

    bridge = None
    try:
        bridge = PanelBridge()
        html = load_html(bridge.capability)
        check("The desktop UI is a single file", "dap-transport" in html)
        api.start()
        for path in ("/api/version", "/api/project?set=1", "/api/state?set=1"):
            envelope = bridge.invoke(bridge.capability, "GET", path, {})
            check(f"Bridge GET {path}",
                  envelope.get("ok") is True
                  and isinstance(envelope.get("body"), dict),
                  str(envelope.get("body", {}).get("error", "")))
    except Exception as exc:
        check("Socketless desktop bridge", False, str(exc))
    finally:
        if bridge is not None:
            bridge._close()
        api.reset()

    passed = all(outcomes)
    write("RESULT: " + ("passed" if passed else "failed"))
    return 0 if passed else 1


def browser_mode(port: int) -> int:
    """Run the optional development/diagnostic server."""
    import threading
    import time
    import webbrowser

    from panel import api, i18n, settings
    from panel.api.http_adapter import serve

    try:
        # Port 0 goes straight to the real listener. Picking a port on a
        # separate socket and closing it raced with other processes on
        # Windows.
        server = serve("127.0.0.1", port)
    except (OSError, ValueError, OverflowError) as exc:
        write(f"[ERROR] Could not start the browser service: {exc}")
        return 1

    actual_port = int(server.server_address[1])
    url = f"http://127.0.0.1:{actual_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="panel-http")
    thread.start()
    try:
        if not http_ready(url):
            write("[ERROR] The browser service gave no HTTP response.")
            return 1
        write(f"{i18n.t('app.name')} {settings.APP_VERSION} — "
              "browser diagnostic mode")
        write(f"Address: {url}")
        write("Press Ctrl-C to stop")
        webbrowser.open(url)
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            write("\nShutting down.")
        return 0
    finally:
        server.shutdown()
        server.server_close()
        api.reset()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if sys.version_info < MINIMUM_PYTHON:
        write(f"[ERROR] Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}+ "
              "is required.")
        return 1

    parser = argparse.ArgumentParser(
        description="Commissioning and Maintenance Panel")
    parser.add_argument("--browser", action="store_true",
                        help="open the HTTP development/diagnostic mode in a "
                             "browser")
    parser.add_argument("--port", type=int, default=None,
                        help="port for --browser mode only (0 = automatic)")
    parser.add_argument("--admin-password", default=None,
                        help="the admin screen asks for this password; it is "
                             "never written anywhere")
    parser.add_argument("--self-test", action="store_true",
                        help="verify the package without opening a window")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()

    from panel import i18n, settings
    if args.version:
        write(settings.APP_VERSION)
        return 0
    if args.self_test:
        return self_test()

    # Argument validation before the privilege check: a misuse must not hide
    # behind the elevation warning.
    if args.port is not None and not args.browser:
        write("[ERROR] --port can only be used together with --browser.")
        return 2

    # The Dock identity is set BEFORE the privilege check: the elevation
    # window is this app's window too. Without it a separate icon appeared in
    # the Dock under the interpreter's name ("Python") and the panel looked
    # like a SECOND application.
    set_macos_identity(i18n.t("app.name"))

    # The privilege check comes after package verification (--self-test,
    # --version) but before the service is set up: those two modes never touch
    # a device or the network, so they need no elevation.
    #
    # Without the privilege the panel still does not open; but the user sees
    # why in a window and can restart elevated from there.
    if not is_elevated():
        return elevation.require_elevation(write)

    from panel import api
    api.set_admin_password(
        args.admin_password or os.environ.get("PANEL_ADMIN_PASSWORD"))

    if args.browser:
        return browser_mode(0 if args.port is None else args.port)

    bridge = None
    try:
        try:
            import webview
        except ImportError:
            write("[ERROR] " + PYWEBVIEW_MISSING)
            return 1

        from panel.desktop import PanelBridge, load_html

        api.start()
        bridge = PanelBridge()
        html = load_html(bridge.capability)
        # In pywebview 6.x file URLs may be enabled by default on some
        # platforms. The UI lives in memory so neither is needed; disabling
        # them explicitly also stops a mispackaged build from working
        # silently.
        webview.settings["ALLOW_FILE_URLS"] = False
        webview.settings["ALLOW_DOWNLOADS"] = False
        # If a target=_blank link is ever added to the UI, it must not
        # navigate inside the privileged WebView; send it to the OS browser.
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["REMOTE_DEBUGGING_PORT"] = None

        window = webview.create_window(
            i18n.t("app.name"), html=html,
            width=WIDTH, height=HEIGHT,
            min_size=(980, 620),
            background_color="#101820",
        )
        # js_api=object is not used: pywebview's low-level call dispatcher
        # leaves a name-addressable surface onto the object's private members.
        # Only this one function, which checks the session key, joins the
        # exact-name allowlist; the bridge's state never enters the WebView.
        window.expose(bridge.invoke)
        # The title bar is painted by the operating system, outside the
        # WebView: the redraw that follows a language switch cannot reach it,
        # so it is told separately. Everything else on screen is rebuilt from
        # the catalogue the switch hands back.
        i18n.on_change(lambda _language: window.set_title(i18n.t("app.name")))
        write(f"{i18n.t('app.name')} {settings.APP_VERSION} — "
              "socketless desktop mode")
        write(f"DeviceMap: {settings.DEVICE_MAP}")
        write("Credentials are asked for in the UI and written nowhere.")
        if platform.system() == "Windows":
            # No silent fallback to the old MSHTML engine: WebView2 is
            # required for modern module and security behaviour.
            webview.start(gui="edgechromium", http_server=False)
        else:
            webview.start(http_server=False)
        return 0
    except Exception:
        write("[ERROR] The window could not be opened:\n"
              + traceback.format_exc(limit=4))
        return 1
    finally:
        # The window closed: new bridge calls are cut off, and the queue, MQTT
        # and in-memory credentials are cleared. There is no HTTP server to
        # close here.
        if bridge is not None:
            bridge._close()
        write("Stopping background work.")
        api.reset()


def _exit_now(code: int) -> None:
    """End the interpreter directly.

    The window engine (pywebview → Cocoa/GTK) can keep the process alive after
    its event loop closes: after starting an elevated process from the
    privilege window, the OLD process did not exit on its own and stayed up
    until killed from outside. Two copies of the panel looking at the same
    switch and the same DeviceMap is exactly what we avoid.

    `main()` has already returned, so nothing is left to close: the bridge and
    services were shut down in its `finally` block. Only flushing the output
    buffers remains.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(int(code))


if __name__ == "__main__":
    _exit_now(main())
