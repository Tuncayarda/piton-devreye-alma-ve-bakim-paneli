#!/usr/bin/env python3
"""The Edit menu, and the timing that decides whether it survives.

The bug this file is about produced NO SYMPTOM except that Cmd-V did
nothing: the menu was either added to a bar that did not exist yet, or added
to one pywebview was about to empty. Both paths returned quietly. So what is
tested here is the ORDER — that nothing is installed before the application
is running, and that once it is, exactly one Edit menu appears.

AppKit is faked. The real one needs a window server and a run loop, and the
question here is not whether Cocoa works.
"""
from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from panel.desktop import editmenu


class FakeMenuItem:
    def __init__(self, title="", separator=False):
        self._title = title
        self.submenu = None
        self.separator = separator
        self.target = None

    def title(self):
        return self._title

    def setTitle_(self, value):
        self._title = value

    def setSubmenu_(self, menu):
        self.submenu = menu

    def setTarget_(self, target):
        self.target = target


class FakeMenu:
    def __init__(self, title=""):
        self._title = title
        self.items = []

    def numberOfItems(self):
        return len(self.items)

    def itemAtIndex_(self, index):
        return self.items[index]

    def insertItem_atIndex_(self, item, index):
        self.items.insert(index, item)

    def addItem_(self, item):
        self.items.append(item)

    def addItemWithTitle_action_keyEquivalent_(self, title, selector, key):
        item = FakeMenuItem(title)
        item.action, item.key = selector, key
        self.items.append(item)
        return item


class FakeApplication:
    def __init__(self, running=False, menu=None):
        self.running = running
        self.menu = menu

    def isRunning(self):
        return self.running

    def mainMenu(self):
        return self.menu


class FakeAppKit:
    def __init__(self, application):
        self.application = application
        self.NSApplication = self
        self.NSMenu = self._menu_factory()
        self.NSMenuItem = self._item_factory()

    def sharedApplication(self):
        return self.application

    @staticmethod
    def _menu_factory():
        class NSMenu:
            @staticmethod
            def alloc():
                class Allocated:
                    @staticmethod
                    def initWithTitle_(title):
                        return FakeMenu(title)
                return Allocated
        return NSMenu

    @staticmethod
    def _item_factory():
        class NSMenuItem:
            @staticmethod
            def alloc():
                class Allocated:
                    @staticmethod
                    def init():
                        return FakeMenuItem()
                return Allocated

            @staticmethod
            def separatorItem():
                return FakeMenuItem(separator=True)
        return NSMenuItem


class TheOperatorsClipboard(unittest.TestCase):
    """Cmd-V under root, where this process cannot see the pasteboard.

    The panel re-launches itself elevated, and the pasteboard is a
    per-session agent the elevated process is not in. So Paste has to fetch
    the operator's clipboard before it forwards `paste:` — the same handback
    `panel.adminkey` does for files.
    """

    def test_a_normal_run_does_not_touch_the_pasteboard(self):
        """Not root: the pasteboard here IS the operator's.

        Rewriting it would drop every flavour that is not plain text, and
        there is nothing to fix.
        """
        with mock.patch.object(editmenu.os, "geteuid", return_value=501):
            self.assertFalse(editmenu.handback_needed())

    def test_root_on_macos_needs_the_handback(self):
        with mock.patch.object(editmenu.platform, "system",
                               return_value="Darwin"), \
             mock.patch.object(editmenu.os, "geteuid", return_value=0):
            self.assertTrue(editmenu.handback_needed())

    def test_root_elsewhere_does_not(self):
        """Only macOS has this session split."""
        for system in ("Linux", "Windows"):
            with mock.patch.object(editmenu.platform, "system",
                                   return_value=system), \
                 mock.patch.object(editmenu.os, "geteuid", return_value=0):
                self.assertFalse(editmenu.handback_needed(), system)

    def test_the_clipboard_is_read_through_the_operators_session(self):
        with mock.patch.object(editmenu.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, stdout=b"K7M2-9QX4", stderr=b"")
            self.assertEqual(editmenu.console_clipboard(), "K7M2-9QX4")
        command = run.call_args[0][0]
        self.assertIn("/usr/bin/pbpaste", command)

    def test_a_clipboard_that_cannot_be_read_is_empty_not_an_error(self):
        """It is called from a menu action; raising there takes the window."""
        cases = [
            subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"nope"),
            OSError("no such binary"),
            subprocess.TimeoutExpired("pbpaste", 2.0),
        ]
        for case in cases:
            with mock.patch.object(editmenu.subprocess, "run") as run:
                if isinstance(case, Exception):
                    run.side_effect = case
                else:
                    run.return_value = case
                self.assertEqual(editmenu.console_clipboard(), "", repr(case))

    def test_an_enormous_clipboard_is_cut_rather_than_carried(self):
        with mock.patch.object(editmenu.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, stdout=b"x" * (editmenu.CLIPBOARD_MAX * 2), stderr=b"")
            self.assertEqual(len(editmenu.console_clipboard()),
                             editmenu.CLIPBOARD_MAX)

    def test_undecodable_bytes_do_not_raise(self):
        with mock.patch.object(editmenu.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, stdout=b"\xff\xfe not utf-8", stderr=b"")
            self.assertIsInstance(editmenu.console_clipboard(), str)


class PastingIntoThePage(unittest.TestCase):
    """Paste writes into the document rather than through the pasteboard.

    The tidy route — put the text back on this process's pasteboard, forward
    `paste:` — fired the menu item and pasted nothing: elevated, the
    pasteboard is not the one the operator copied into, and between that,
    the responder chain and WKWebView there are too many places to lose the
    text quietly. So the characters are handed to the page.
    """

    def setUp(self):
        self._window = editmenu._WINDOW
        self.addCleanup(setattr, editmenu, "_WINDOW", self._window)

    def window(self, answer="inserted"):
        window = mock.Mock()
        window.evaluate_js.return_value = answer
        editmenu._WINDOW = window
        return window

    def test_the_text_reaches_the_page(self):
        window = self.window()
        self.assertTrue(editmenu.paste_into_page("K7M2-9QX4"))
        script = window.evaluate_js.call_args[0][0]
        # Embedded as JSON, so a clipboard holding a quote or a backslash is
        # text rather than the end of the script.
        self.assertIn('"K7M2-9QX4"', script)
        self.assertNotIn("__TEXT__", script)

    def test_a_clipboard_full_of_javascript_is_still_only_text(self):
        window = self.window()
        editmenu.paste_into_page('"); alert(1); //')
        script = window.evaluate_js.call_args[0][0]
        self.assertIn(json.dumps('"); alert(1); //'), script)

    def test_a_page_that_took_the_paste_itself_counts_as_done(self):
        """The session code box claims it and splits it across two halves."""
        self.window(answer="handled")
        self.assertTrue(editmenu.paste_into_page("K7M2-9QX4"))

    def test_nothing_focused_is_not_a_paste(self):
        self.window(answer="no-focus")
        self.assertFalse(editmenu.paste_into_page("K7M2-9QX4"))

    def test_no_window_and_no_text_are_refusals(self):
        editmenu._WINDOW = None
        self.assertFalse(editmenu.paste_into_page("K7M2-9QX4"))
        self.window()
        self.assertFalse(editmenu.paste_into_page(""))

    def test_a_webview_that_will_not_answer_is_a_refusal(self):
        window = self.window()
        window.evaluate_js.side_effect = RuntimeError("no answer")
        self.assertFalse(editmenu.paste_into_page("K7M2-9QX4"))

    def test_the_pasteboard_route_is_taken_when_the_page_will_not_have_it(self):
        """Nothing was written into the page, so the ordinary paste runs.

        Losing the menu item entirely would be worse than a paste that does
        what it always did.
        """
        editmenu._WINDOW = None
        appkit = mock.Mock()
        with mock.patch.object(editmenu, "clipboard_text",
                               return_value="K7M2-9QX4"):
            editmenu._paste(appkit)
        # The fallback is handed to the main queue: AppKit is not to be
        # touched from the worker this runs on.
        queued = appkit.NSOperationQueue.mainQueue.return_value
        self.assertTrue(queued.addOperationWithBlock_.called)

    def test_the_pasteboard_route_is_not_taken_when_the_page_took_it(self):
        self.window(answer="inserted")
        appkit = mock.Mock()
        with mock.patch.object(editmenu, "clipboard_text",
                               return_value="K7M2-9QX4"):
            editmenu._paste(appkit)
        queued = appkit.NSOperationQueue.mainQueue.return_value
        self.assertFalse(queued.addOperationWithBlock_.called)

    def test_an_unreadable_clipboard_does_not_take_the_window_down(self):
        self.window()
        appkit = mock.Mock()
        with mock.patch.object(editmenu, "clipboard_text",
                               side_effect=OSError("nope")):
            editmenu._paste(appkit)      # must not raise


class TheEditMenu(unittest.TestCase):

    def setUp(self):
        editmenu.reset()
        self.addCleanup(editmenu.reset)

    def test_nothing_is_installed_before_the_application_runs(self):
        """The first of the two silent failures.

        pywebview has not built its bar yet, so there is nothing to add to.
        Answering "not yet" is what makes the caller come back.
        """
        appkit = FakeAppKit(FakeApplication(running=False, menu=None))
        self.assertFalse(editmenu._install_now(appkit))

    def test_nothing_is_installed_while_the_bar_is_still_missing(self):
        """The second one: running, but the bar has not been set yet."""
        appkit = FakeAppKit(FakeApplication(running=True, menu=None))
        self.assertFalse(editmenu._install_now(appkit))

    def test_it_is_installed_once_the_application_is_running(self):
        bar = FakeMenu()
        bar.addItem_(FakeMenuItem("dabp"))       # pywebview's own app menu
        appkit = FakeAppKit(FakeApplication(running=True, menu=bar))

        self.assertTrue(editmenu._install_now(appkit))

        titles = [item.title() for item in bar.items]
        self.assertEqual(len(titles), 2)
        # Second: after the application menu, where a Mac user looks.
        edit = bar.items[1]
        self.assertNotEqual(edit.title(), "")
        entries = edit.submenu.items
        selectors = [getattr(item, "action", None) for item in entries]
        self.assertIn(editmenu.PASTE_ACTION, selectors)
        self.assertIn("copy:", selectors)
        self.assertIn("selectAll:", selectors)

    def test_the_paste_item_is_ours_and_keeps_the_shortcut(self):
        """Aimed at us, so the operator's clipboard can be fetched first.

        It still ENDS in the standard `paste:` (see the bridge), which is
        what keeps one menu item working in every field of the window rather
        than in one the code knows about.
        """
        bar = FakeMenu()
        appkit = FakeAppKit(FakeApplication(running=True, menu=bar))
        editmenu._install_now(appkit)
        paste = next(item for item in bar.items[0].submenu.items
                     if getattr(item, "action", None) == editmenu.PASTE_ACTION)
        self.assertEqual(paste.key, "v")
        # A menu item holds its target WEAKLY. Left to the garbage collector
        # the shortcut stops working a moment after it starts, which looks
        # exactly like the timing bug this file already covers.
        self.assertIsNotNone(paste.target)
        self.assertIs(paste.target, editmenu._paste_bridge(appkit))
        # The standard ones stay targetless so they walk the responder chain.
        copy = next(item for item in bar.items[0].submenu.items
                    if getattr(item, "action", None) == "copy:")
        self.assertIsNone(copy.target)

    def test_installing_twice_leaves_one_menu(self):
        bar = FakeMenu()
        appkit = FakeAppKit(FakeApplication(running=True, menu=bar))
        editmenu._install_now(appkit)
        editmenu._install_now(appkit)
        self.assertEqual(bar.numberOfItems(), 1)

    def test_a_bar_that_already_has_one_is_left_alone(self):
        """A second panel window must not add a second Edit menu."""
        from panel import i18n
        bar = FakeMenu()
        bar.addItem_(FakeMenuItem(i18n.t("menu.edit")))
        appkit = FakeAppKit(FakeApplication(running=True, menu=bar))
        editmenu._install_now(appkit)
        self.assertEqual(bar.numberOfItems(), 1)


if __name__ == "__main__":
    unittest.main()
