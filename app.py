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

One program is packaged once per customer, and each package carries only
that customer's project (see panel.editions). A packaged build knows which
edition it is; running from source has to be told, because "whichever
DeviceMap the tree happens to hold" is not an answer anyone meant to give.

Run:
    python3 app.py --edition gdm           # which package this run is
    python3 app.py --edition admin --browser   # in a browser, not a window
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
from panel.elevation import is_elevated              # noqa: E402  (test patch point)

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


def utf8_stdout() -> None:
    """Console output in the encoding the messages are written in.

    The product name and the Turkish catalogue both hold characters cp1252
    cannot encode, and that is what Windows hands a Python process. Without
    this, `--self-test` lines vanish one by one into the `write` above —
    which is worse than a crash, because the step then passes while the
    build's own grep for its output finds nothing.

    Guarded twice: a frozen GUI build may have no stdout at all, and a
    stream that refuses to be reconfigured is not worth an exception here.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
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
    from panel import api, editions, i18n, settings
    from panel.desktop import PanelBridge, load_html
    from panel.inventory import device_map

    outcomes = []

    def check(name: str, condition: bool, extra: str = "") -> bool:
        write(f"  [{'OK  ' if condition else 'FAIL'}] {name}"
              + (f" — {extra}" if extra else ""))
        outcomes.append(condition)
        return condition

    edition = editions.active()
    write(f"{i18n.t('app.name')} {settings.APP_VERSION} — self-test")
    write(f"  edition: {edition.id} ({editions.app_name(edition.id)})")

    # A packaged build must know what it is without being told. From source
    # nothing is stamped in, which is normal and not a finding.
    if settings.FROZEN:
        check("Edition stamped into the package",
              editions.stamped_edition() == edition.id,
              editions.stamped_edition() or "no stamp")

    # Every project this package claims to carry. A package whose OWN
    # project is missing is a broken package, not a pending delivery: it
    # would open on a device list that is not there.
    for project in edition.projects:
        present = editions.available(project)
        if project.key == edition.default_project or present:
            check(f"Device list · {project.label}", present,
                  str(editions.map_path(project)))
        else:
            # A project that is declared but not yet delivered (VIP today).
            # Reported, never failed — the package is still sound.
            write(f"  [ --  ] Device list · {project.label} — "
                  "not delivered yet")

    # THE KEY MATERIAL, stated so CI can read it back off a packaged build.
    # A customer package must hold the digest and NOT the secret: from the
    # digest there is no route to the value a USB stick carries, which is
    # what stops a customer minting their own key. Printed as a fact about
    # the build; the values themselves never appear.
    from panel import adminkey                             # noqa: PLC0415
    holds_secret = adminkey.can_write()
    material = ("secret embedded" if holds_secret
                else "digest only" if adminkey.usable() else "none")
    if settings.FROZEN:
        # THE FAILURE THIS CATCHES IS A LEAK, and only that. Every package
        # is a customer's package now, and one carrying the secret rather
        # than a digest of it would let that customer mint service keys for
        # every other customer's package — the one outcome the whole
        # arrangement exists to prevent. No package may hold it; the secret
        # stays with whoever cuts the builds (see docs/BUILD_RELEASE.md).
        check("Admin key material", not holds_secret, material)
    else:
        # From source the secret comes from the environment, which is a
        # development convenience and says nothing about any package.
        write(f"  [ --  ] Admin key material — {material} (from source)")

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
    # The two field scripts (see panel.script_loader). In a packaged app
    # they are copied into the bundle; if one is missing, IP assignment or
    # the Excel export will not work in the field — better to find out where
    # the package is built.
    for name, path in (("Field verification script",
                        settings.DEVICE_VERIFY_SCRIPT),
                       ("IP assignment script", settings.IP_ASSIGN_SCRIPT)):
        check(name, path.exists(), str(path))

    # THE ADB EXECUTABLE, and in a package this is a failure rather than a
    # note. An Android display is reached with `adb` and nothing else, and a
    # commissioning laptop has no reason to carry Android Studio — which is
    # why the package ships its own (see panel/adb/binary.py). A build that
    # forgot the download step still runs, still opens, and then reports
    # "the Compartment LCD cannot be read" on a display that is perfectly
    # healthy. That is exactly the failure this line exists to move from the
    # field back to the build.
    #
    # From source it is only reported: a developer's machine may have adb on
    # PATH, or no need for one at all.
    from panel.adb import binary as adb_binary

    carried = adb_binary.bundled()
    if settings.FROZEN:
        check("ADB executable (in the package)", carried is not None,
              str(carried) if carried else
              "not bundled — this package cannot reach an Android display")
    elif carried is not None:
        write(f"  [OK  ] ADB executable — {carried}")
    else:
        found = adb_binary.adb_path()
        write(f"  [ --  ] ADB executable — not bundled; from source this "
              f"falls back to {found}")

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
    parser.add_argument("--edition", default=None,
                        help="which package this run is; required from "
                             "source, refused in a packaged build (it is "
                             "already stamped in)")
    parser.add_argument("--self-test", action="store_true",
                        help="verify the package without opening a window")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()

    utf8_stdout()
    from panel import editions, i18n, settings
    # Before anything asks what this build can do: the secret may have been
    # handed to us by the process that put up the password box, because the
    # environment does not survive it (see panel.adminkey.handoff).
    from panel.adminkey import handoff                     # noqa: PLC0415
    handoff.claim()
    if args.version:
        write(settings.APP_VERSION)
        return 0

    # Flag validation first: a misuse must be reported as a misuse, not as a
    # missing edition and not from behind the elevation prompt.
    if args.port is not None and not args.browser:
        write("[ERROR] --port can only be used together with --browser.")
        return 2

    # WHICH EDITION IS THIS? Everything below depends on the answer: which
    # DeviceMap opens, which screens exist, and whether admin mode can be
    # reached at all. It is settled here, before the elevation gate, so that
    # a misuse is reported as a misuse rather than behind a password box —
    # and so CI can check the refusal without being able to elevate.
    try:
        edition_id = editions.resolve(args.edition)
    except editions.EditionError as exc:
        if not args.self_test:
            write(f"[ERROR] {exc}")
            return 2
        # A self-test still has something worth doing: it verifies the
        # package, not the customer. So it falls back to the first edition in
        # the table — said out loud, because a self-test that quietly tests
        # something else than was asked for is worse than one that refuses.
        edition_id = editions.IDS[0]
        write(f"[NOTE] no edition given; verifying as \"{edition_id}\".")
    editions.activate(edition_id)
    # NO KEY MATERIAL AT ALL, so a service key plugged into this build is
    # not ignored on purpose — it cannot be recognised, because nothing
    # tells it which key to accept. A packaged build carries that in its
    # stamp; a source run has to be told. Said here because the symptom
    # otherwise is "I plugged the stick in and nothing happened".
    from panel import adminkey                             # noqa: PLC0415
    if not adminkey.usable():
        write("[NOTE] this build carries no key material, so a service "
              "key will not be recognised.\n"
              "       Register one you already have:\n"
              "         python3 tools/key_digest.py /Volumes/DABP-KEY "
              "--remember\n"
              "       A key written from source registers itself.")

    if args.self_test:
        return self_test()

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
        # THE ENVIRONMENT DOES NOT SURVIVE THE PROMPT. The panel restarts
        # itself through the system's own password box — osascript on macOS,
        # runas on Windows, pkexec on Linux — and every one of those builds
        # a fresh command line under a fresh environment. A secret exported
        # in this shell would simply be gone in the process that actually
        # opens, and the panel would come up in field mode as though the
        # variable had been ignored.
        #
        # So it is handed over rather than lost: written to a file only this
        # user can read, named (never valued) in the command line, and
        # deleted by the process that picks it up. Windows is the exception
        # — `runas` takes no environment of ours — and is told so.
        handed = handoff.stash()
        if handed:
            os.environ[handoff.FILE_VAR] = handed
        elif os.environ.get(handoff.SECRET_VAR):
            # Set, and it will not get through. Said here, while the shell
            # that has it is still the one being talked to.
            write("[NOTE] DAP_ADMIN_KEY_SECRET does not survive the "
                  "privilege prompt on this platform.\n"
                  "       Set it in an administrator shell and start the "
                  "panel from there.")
        return elevation.require_elevation(write)

    from panel import api

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
        from panel.system import files

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
        # The file picker borrows this window on Linux, where there is no
        # native dialog to shell out to unless zenity or kdialog happens to be
        # installed (see panel/system/files.py). Registered here because this
        # is the only place that has a window at all.
        files.use_window(window)
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
