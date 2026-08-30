#!/usr/bin/env python3
"""The Edit menu macOS needs before Cmd-C and Cmd-V mean anything.

A Cocoa application without a menu bar has no key equivalents, and pywebview
builds only an application menu and a View menu — there is no Edit menu, so
the standard editing shortcuts reach nothing. That is invisible until
somebody is handed a session code by message and finds they cannot paste it.

The items are wired to the STANDARD SELECTORS — `cut:`, `copy:`, `paste:`,
`selectAll:` — rather than to functions of our own. Those travel up the
responder chain to the WebView's text field, which is what makes them work
everywhere in the window at once instead of in the one field somebody
remembered.

Nothing here is required for the panel to run. Every failure is swallowed:
an application that will not open because a menu could not be built is a
much worse outcome than one where Cmd-V does not work.

THE TIMING IS THE WHOLE BUG THIS FILE HAD, and it was silent in both of its
halves. `webview.start(func=...)` runs `func` on a WORKER THREAD the moment
the loop starts, while the menu bar is built on the main thread later, just
before `NSApplication.run()` — pywebview's `first_show` calls
`_clear_main_menu()`, `_add_app_menu()`, `_add_view_menu()` in that order.
Scheduling the build straight away therefore lands in one of two places:

  * before pywebview has a menu bar at all — `mainMenu()` is None, and the
    old code returned right there, so no Edit menu was ever added;
  * after the bar exists but before `_clear_main_menu()` — which then calls
    `removeAllItems()` and takes ours out with the rest.

Either way Cmd-V reached nothing and nothing said so. So the install now
WAITS for the application to be running: `isRunning()` turns true only after
pywebview has finished building its bar, which makes it the one moment when
adding to that bar both works and survives.

AND THEN THE MENU WORKED AND PASTING STILL DID NOT, which is the second half
of this file. THE PANEL RUNS AS ROOT — it re-launches itself through
`osascript ... with administrator privileges` to reach the PoE ports — and
the pasteboard is a per-session LaunchAgent (`gui/<uid>/com.apple.pboard`).
The elevated process is reparented to launchd and is not in that session, so
`NSPasteboard.generalPasteboard()` is not the pasteboard the operator copied
into. `paste:` then fires perfectly and pastes nothing, which on screen is
indistinguishable from a shortcut that is not wired up.

THIS IS THE SAME PROBLEM `panel.adminkey.handback` SOLVES FOR FILES, and it
takes the same answer: hand the read down to the session that owns it with
`launchctl asuser` (`panel.system.files.as_console_user`). So Paste is wired
to an action of ours that fetches the operator's clipboard, puts it on this
process's pasteboard, and only then forwards the standard `paste:` down the
responder chain — which means the shortcut still works in every field of the
window rather than in one the code knows about.

AND THE PASTEBOARD IS NOT TRUSTED TO CARRY IT. Putting the text back on
this process's pasteboard and forwarding `paste:` is the tidy answer and it
was measurably not a reliable one: the menu item fired — the title flashes,
which is macOS acknowledging the key equivalent — and the field stayed
empty. Between an elevated process, a pasteboard it is not the owner of and
a WKWebView deciding what a paste means, there are too many places for the
text to be dropped silently.

So the text is INSERTED INTO THE PAGE instead. The clipboard is read in the
operator's session and handed to the document, which dispatches a real
`paste` event first — so a field that handles pasting itself still does, and
the session code box still splits a code across its two halves — and writes
the characters in only if nothing claimed them. Nothing depends on which
pasteboard this process can see.

OFF THE MAIN THREAD, and that part is not optional: `evaluate_js` waits for
the WebView to answer and the WebView answers on the main run loop, so doing
this from the menu action would park the window on its own paste.

NOT ROOT, NOT TOUCHED — the fallback path, at least. Where there is no
window to write into, the old route is still taken: carry the pasteboard if
this process cannot see the operator's, then forward the standard `paste:`.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import threading
import time

from .. import i18n
from ..system.files import as_console_user

# The window to write into. Set by `install`; None in the tests and on any
# platform that never builds a menu.
_WINDOW = None

# Put the clipboard where the caret is.
#
# THE PASTE EVENT GOES FIRST because some fields mean something by it. The
# session code box takes one pasted code and splits it across two boxes
# (`static/js/app.js`), and a plain insertion would drop half of it into a
# box that only keeps four characters. A handler that claims the paste calls
# `preventDefault`, which is what `dispatchEvent` returning false means, and
# then there is nothing left to do.
INSERT_JS = """
(function (text) {
  var node = document.activeElement;
  if (!node) return 'no-focus';
  var tag = (node.tagName || '').toUpperCase();
  var box = tag === 'INPUT' || tag === 'TEXTAREA';
  if (!box && !node.isContentEditable) return 'not-editable';
  try {
    var carrier = new DataTransfer();
    carrier.setData('text/plain', text);
    var event = new ClipboardEvent('paste', {
      clipboardData: carrier, bubbles: true, cancelable: true,
    });
    if (!node.dispatchEvent(event)) return 'handled';
  } catch (error) { /* no ClipboardEvent here: write it in below */ }
  if (box) {
    var from = node.selectionStart, to = node.selectionEnd;
    if (from === null || from === undefined) { from = to = node.value.length; }
    node.value = node.value.slice(0, from) + text + node.value.slice(to);
    var caret = from + text.length;
    try { node.setSelectionRange(caret, caret); } catch (ignored) {}
  } else {
    document.execCommand('insertText', false, text);
  }
  node.dispatchEvent(new Event('input', { bubbles: true }));
  return 'inserted';
})(__TEXT__)
"""

# Title, Objective-C selector, key equivalent.
PASTE_ACTION = "dabpPasteFromConsole:"

ITEMS = (
    ("menu.undo", "undo:", "z"),
    ("menu.redo", "redo:", "Z"),
    (None, None, None),                      # separator
    ("menu.cut", "cut:", "x"),
    ("menu.copy", "copy:", "c"),
    # Ours rather than `paste:` — see the note at the top of the file.
    ("menu.paste", PASTE_ACTION, "v"),
    ("menu.selectAll", "selectAll:", "a"),
)

# How long the operator's shell is given to hand back their clipboard. It is
# a `pbpaste` in their session; a second is already generous, and going over
# it must mean an ordinary paste rather than a menu that has stopped
# responding.
CLIPBOARD_TIMEOUT = 2.0
# The clipboard is arbitrary text somebody copied. Bounded for the same
# reason every other read in this tree is: a process is a poor place to
# discover that it holds a hundred megabytes.
CLIPBOARD_MAX = 256 * 1024

# How long to keep waiting for the application to come up, and how often to
# look. Generous: a cold start on a slow machine is seconds, and the cost of
# waiting is a background thread doing nothing. Giving up is not an error —
# it is the state the panel was in before this file existed.
TIMEOUT = 30.0
POLL = 0.1

_INSTALLED = threading.Event()


def install(window=None) -> None:
    """Add the Edit menu once the window is up. Safe on any platform.

    Called as `webview.start(func=...)`, so this IS the worker thread and
    blocking in it costs nothing. AppKit is only ever touched inside the
    block handed to the main queue.

    `window` is the pywebview window Paste writes into. Without one the menu
    still works, by the pasteboard route.
    """
    global _WINDOW
    if window is not None:
        _WINDOW = window
    if platform.system() != "Darwin":
        # Windows and Linux get the shortcuts from the WebView itself.
        return
    try:
        import AppKit                                     # noqa: PLC0415
    except Exception:
        return

    done = threading.Event()

    def attempt():
        try:
            if _install_now(AppKit):
                done.set()
        except Exception:
            # A build that cannot be done will not become doable by being
            # retried sixty times.
            done.set()

    deadline = time.monotonic() + TIMEOUT
    while not done.is_set() and time.monotonic() < deadline:
        try:
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(attempt)
        except Exception:
            return
        time.sleep(POLL)


def _install_now(AppKit) -> bool:
    """On the main thread: install if the moment is right.

    False means "not yet" and asks to be called again; True means installed,
    already there, or never going to happen.
    """
    application = AppKit.NSApplication.sharedApplication()
    # THE GATE. Before this is true the bar is either absent or about to be
    # emptied — see the note at the top of the file.
    if not application.isRunning():
        return False
    main = application.mainMenu()
    if main is None:
        return False
    if _INSTALLED.is_set():
        return True
    _build(AppKit, main)
    _INSTALLED.set()
    return True


# ── the operator's clipboard, when this process cannot see it ───────────
def handback_needed() -> bool:
    """Is this process cut off from the pasteboard the operator uses?

    The same test `panel.adminkey.handback.applicable` makes, and for the
    same reason: on macOS as root there is a session in the way.
    """
    return platform.system() == "Darwin" and os.geteuid() == 0


def console_clipboard() -> str:
    """The logged-in operator's clipboard as text, or "" for any failure.

    NEVER RAISES. It is called from a menu action, and a clipboard that
    cannot be fetched has to leave Cmd-V behaving the way it would have
    without any of this — not take the window down.
    """
    try:
        done = subprocess.run(as_console_user(["/usr/bin/pbpaste"]),
                              capture_output=True, timeout=CLIPBOARD_TIMEOUT,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    return done.stdout[:CLIPBOARD_MAX].decode("utf-8", "replace")


def clipboard_text() -> str:
    """What to paste: the operator's clipboard, wherever it lives.

    Under root that is another session's and needs the handback; otherwise
    `pbpaste` in this process reads the one the operator is using.
    """
    return console_clipboard()


def paste_into_page(text: str) -> bool:
    """Write `text` where the caret is. True if the page took it.

    False for every reason a page might not — no window, nothing focused,
    the WebView not answering — and the caller then falls back to the
    pasteboard route rather than leaving the operator with nothing.
    """
    window = _WINDOW
    if window is None or not text:
        return False
    try:
        answer = window.evaluate_js(
            INSERT_JS.replace("__TEXT__", json.dumps(text)))
    except Exception:
        return False
    return answer in ("handled", "inserted")


def _paste(AppKit) -> None:
    """The whole of Paste, on a worker thread. Never raises."""
    try:
        text = clipboard_text()
    except Exception:
        text = ""
    if paste_into_page(text):
        return
    # Nothing was written into the page. Take the ordinary route, on the
    # main thread where AppKit expects to be called.
    def fallback():
        try:
            if handback_needed() and text:
                _carry_clipboard(AppKit, text)
            AppKit.NSApplication.sharedApplication().sendAction_to_from_(
                "paste:", None, None)
        except Exception:
            pass
    try:
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(fallback)
    except Exception:
        pass


def _carry_clipboard(AppKit, text: str = "") -> None:
    """Put the operator's clipboard on this process's pasteboard.

    Only when there is something to carry: an empty answer means the fetch
    failed or the clipboard really is empty, and in both cases wiping what
    is already here would turn a paste that might have worked into one that
    cannot.
    """
    text = text or console_clipboard()
    if not text:
        return
    board = AppKit.NSPasteboard.generalPasteboard()
    board.clearContents()
    board.setString_forType_(text, AppKit.NSPasteboardTypeString)


_BRIDGE = None


def _paste_bridge(AppKit):
    """The object the Paste item is aimed at. Built once and KEPT.

    A menu item holds its target weakly, so an instance left to the garbage
    collector takes the shortcut with it a moment later — and it did, which
    is a bug that looks exactly like the one above.
    """
    global _BRIDGE
    if _BRIDGE is not None:
        return _BRIDGE
    from Foundation import NSObject                       # noqa: PLC0415

    class DabpPasteBridge(NSObject):
        def dabpPasteFromConsole_(self, sender):
            # STRAIGHT OFF THE MAIN THREAD. Reading the clipboard spawns a
            # process and writing it into the page waits for the WebView,
            # which answers on this very run loop — doing either here parks
            # the window on its own paste.
            threading.Thread(target=_paste, args=(AppKit,),
                             daemon=True).start()

    _BRIDGE = DabpPasteBridge.alloc().init()
    return _BRIDGE


def _build(AppKit, main) -> None:
    title = i18n.t("menu.edit")
    for index in range(main.numberOfItems()):
        if main.itemAtIndex_(index).title() == title:
            return                           # already installed

    bridge = _paste_bridge(AppKit)
    menu = AppKit.NSMenu.alloc().initWithTitle_(title)
    for key, selector, shortcut in ITEMS:
        if key is None:
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            continue
        item = menu.addItemWithTitle_action_keyEquivalent_(
            i18n.t(key), selector, shortcut)
        # The standard selectors are left targetless so they walk the
        # responder chain; ours has to be told where to go.
        if selector == PASTE_ACTION and item is not None:
            item.setTarget_(bridge)

    item = AppKit.NSMenuItem.alloc().init()
    item.setTitle_(title)
    item.setSubmenu_(menu)
    # After the application menu, before View: where a Mac user looks for it.
    main.insertItem_atIndex_(item, min(1, main.numberOfItems()))


def reset() -> None:
    """Forget that it was installed. Tests only.

    The bridge goes with it. It is built once and KEPT on purpose (see
    `_paste_bridge`), which is right for a running application and wrong for
    a test file: the first case to build one left it for every case after,
    so a later assertion about the target was answered by an object an
    earlier test had made.
    """
    global _BRIDGE
    _INSTALLED.clear()
    _BRIDGE = None
