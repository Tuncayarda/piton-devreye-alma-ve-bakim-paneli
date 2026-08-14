#!/usr/bin/env python3
"""Static checks on the frontend files.

Covered requirement:
 19. Frontend modules pass a syntax/lint check.

It also catches rule violations at the source: device data must never be
printed with innerHTML, and a password must never reach browser storage.
These checks are cheaper than a runtime test and hard to miss.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest

from panel import settings

JS_DIR = settings.STATIC_DIR / "js"
CSS_DIR = settings.STATIC_DIR / "css"


def _js_files():
    return sorted(JS_DIR.rglob("*.js"))


# An ES module import may span several lines:
#
#     import {
#       a, b,
#     } from './x.js';
#
# A line-by-line scan only ever sees the closing `} from './x.js';` line,
# which does not start with `import`, so the target went unnoticed and its
# module looked unreachable. Match against the whole file instead.
_IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*import\b        # statement start
        (?:(?!['"]).)*?            # bindings (never contain a quote)
        \bfrom\s*                  # ... from
        (['"])(?P<target>[^'"]+)\1 # module specifier
        |                          # or a bare side-effect import
        (?:^|\n)\s*import\s*(['"])(?P<bare>[^'"]+)\2""",
    re.S | re.X)


def _import_targets(path):
    """Relative module specifiers imported by `path`, in file order."""
    text = path.read_text(encoding="utf-8")
    targets = []
    for match in _IMPORT_RE.finditer(text):
        target = match.group("target") or match.group("bare")
        if target and target.startswith("."):
            targets.append(target)
    return targets


def _code(path) -> str:
    """Strips comments and returns the code only.

    Forbidden-API checks must not trip over comments: the "no innerHTML"
    note at the top of a file is the rule, not a violation of it.
    """
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("//"))


class Frontend(unittest.TestCase):

    def test_19_js_modules_pass_lint(self):
        """A real lint+type check when deno is present; skipped otherwise."""
        deno = shutil.which("deno")
        if not deno:
            self.skipTest("deno is not installed — the JS lint check was "
                          "skipped (install: brew install deno)")
        lint = subprocess.run([deno, "lint", str(JS_DIR)],
                              capture_output=True, text=True, timeout=180)
        self.assertEqual(lint.returncode, 0,
                         f"deno lint errors:\n{lint.stderr}")
        check = subprocess.run(
            [deno, "check", "--no-lock", str(JS_DIR / "app.js")],
            capture_output=True, text=True, timeout=180)
        self.assertEqual(check.returncode, 0,
                         f"deno check errors:\n{check.stderr}")

    def test_19b_module_structure_is_consistent(self):
        """Every module is an ES module; imports must resolve to real files."""
        files = _js_files()
        self.assertGreaterEqual(len(files), 15)
        for path in files:
            for target in _import_targets(path):
                resolved = (path.parent / target).resolve()
                self.assertTrue(resolved.is_file(),
                                f"{path.name} -> {target} not found")

    def test_19c_no_unreachable_module(self):
        """Every module must sit in the import tree rooted at `app.js`.

        A file outside the tree is dead code: it costs the reader time and
        makes "is this still used?" a manual grep every time. That question
        was once answered wrongly, which is why the check lives here.
        """
        entry = JS_DIR / "app.js"
        pending, seen = [entry], set()
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            for target in _import_targets(path):
                pending.append((path.parent / target).resolve())

        unreachable = sorted(p.relative_to(JS_DIR).as_posix()
                             for p in _js_files() if p not in seen)
        self.assertEqual(unreachable, [],
                         f"module imported from nowhere: {unreachable}")

    def test_device_data_is_not_printed_with_innerhtml(self):
        """innerHTML / outerHTML / document.write must appear in no module."""
        self._forbidden(("innerHTML", "outerHTML", "insertAdjacentHTML",
                         "document.write", "eval("))

    def test_password_is_not_written_to_browser_storage(self):
        self._forbidden(("localStorage", "sessionStorage", "indexedDB",
                         "document.cookie"))

    def _forbidden(self, banned):
        found = []
        for path in _js_files():
            code = _code(path)
            for item in banned:
                if item in code:
                    found.append(f"{path.name}: {item}")
        self.assertEqual(found, [], f"forbidden call found: {found}")

    def test_password_is_not_kept_in_global_state(self):
        """The store writes no key outside the known set; no password key."""
        text = _code(JS_DIR / "core" / "store.js")
        self.assertIn("KEYS", text)
        for banned in ("password", "credential", "secret"):
            self.assertNotIn(f"'{banned}'", text)

    def test_setinterval_is_not_used(self):
        """Refresh rounds are setTimeout chains (so requests cannot pile up)."""
        self._forbidden(("setInterval",))

    def test_index_html_has_the_required_elements(self):
        html = (settings.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for element_id in ("role-screen", "app", "locked-btn", "queue-btn",
                           "refresh-btn", "locked-panel",
                           "queue-panel", "toast", "set-picker"):
            self.assertIn(f'id="{element_id}"', html, element_id)
        # Refreshing cannot be stopped: there is deliberately no pause button.
        self.assertNotIn('id="pause-btn"', html)
        # Accessibility: icon buttons must not be left without a label
        self.assertIn('aria-label="Job queue"', html)
        self.assertIn('lang="en"', html)
        self.assertIn('<script type="module"', html)

    def test_css_files_exist_and_are_not_empty(self):
        for name in ("base.css", "components.css", "views.css", "ip.css"):
            path = CSS_DIR / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(len(path.read_text(encoding="utf-8")), 500, name)

    def test_responsive_breakpoints_exist(self):
        """The 1440 base design must not overflow on narrow screens."""
        base = (CSS_DIR / "base.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 1080px)", base)
        self.assertIn("@media (max-width: 720px)", base)
        components = (CSS_DIR / "components.css").read_text(encoding="utf-8")
        self.assertIn("overflow-x: auto", components)   # wide tables scroll

    def test_python_sources_compile(self):
        """Every Python source passes a syntax check."""
        import py_compile
        sources = ([settings.ROOT / "app.py"]
                   + sorted((settings.ROOT / "panel").rglob("*.py"))
                   + sorted((settings.ROOT / "field_scripts").glob("*.py"))
                   + sorted((settings.ROOT / "tools").glob("*.py"))
                   + sorted((settings.ROOT / "tests").rglob("*.py")))
        for path in sources:
            with self.subTest(file=path.name):
                py_compile.compile(str(path), doraise=True, cfile=None)


if __name__ == "__main__":
    unittest.main()
