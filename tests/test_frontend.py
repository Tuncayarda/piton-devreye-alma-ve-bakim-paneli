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
JS_TEST_DIR = settings.ROOT / "tests" / "js"
CSS_DIR = settings.STATIC_DIR / "css"


def _js_files():
    return sorted(JS_DIR.rglob("*.js"))


# ── colour maths, for the contrast gate ─────────────────────────────────
def _colour_tokens() -> dict[str, str]:
    """The literal hex custom properties declared in base.css `:root`.

    Aliases (`--ok-text: var(--ok)`) are resolved one level, which is as deep
    as the token file goes.
    """
    text = (CSS_DIR / "base.css").read_text(encoding="utf-8")
    literal = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", text))
    for name, target in re.findall(
            r"--([a-z0-9-]+):\s*var\(--([a-z0-9-]+)\)\s*;", text):
        if target in literal:
            literal[name] = literal[target]
    return literal


def _luminance(colour: str) -> float:
    channels = [int(colour[index:index + 2], 16) / 255
                for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.03928
              else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(one: str, other: str) -> float:
    first, second = _luminance(one), _luminance(other)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


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
    re.DOTALL | re.VERBOSE)


def _import_targets(path):
    """Relative module specifiers imported by `path`, in file order."""
    text = path.read_text(encoding="utf-8")
    targets = []
    for match in _IMPORT_RE.finditer(text):
        target = match.group("target") or match.group("bare")
        if target and target.startswith("."):
            targets.append(target)
    return targets


# ── the class-name gate ─────────────────────────────────────────────────
# A class in the JS with no rule in the CSS is invisible: the element renders,
# unstyled, and nothing anywhere says so. That is how the switch screen's link
# dots came to be grey whatever the port was doing — the sibling application
# defined `.dot.up`, `.dot.data` and friends in its own stylesheet, the
# JavaScript was carried over and the stylesheet was not.
#
# WHAT THIS SEES: class names written as literals inside the class expression,
# including the branches of a ternary and the fixed parts of a template
# string. WHAT IT DOES NOT SEE: a name computed into a variable first
# (`class: `dot ${kind}`` tells us only about "dot"). The second test below
# closes that particular gap for the one vocabulary that uses it.

# Two kinds of site, checked differently. A `class:` shows the element's WHOLE
# class list, so a modifier can be checked against the compound selector it
# needs (`.pill.ok` is a rule; a lone `.ok` is not). The others show one name
# at a time — `classList.add('view-enter')` cannot reveal the `.view` that
# `.view.view-enter` also requires — so those get the weaker check: the name
# must be styled somewhere.
_CLASS_ATTRIBUTE = re.compile(r"\bclass:")
_CLASS_FRAGMENT = re.compile(
    r"\bclassName\s*\+?=|\bclassList\.(?:add|remove|toggle)\(")
_STRING = re.compile(r"'([^'\\\n]*)'|\"([^\"\\\n]*)\"|`([^`\\]*)`", re.DOTALL)
# `port.link === 'up'` sits inside a class expression but is a comparison, not
# a class. Dropped before the literals are read, or every screen that colours
# by a data value reports its data values as missing rules.
_COMPARISON = re.compile(r"(?:===|!==|==|!=)\s*(['\"])[^'\"]*\1")
_CLASS_TOKEN = re.compile(r"-?[A-Za-z_][\w-]*")


def _class_expression(text: str, start: int) -> str:
    """The class value: from `start` to the comma or line that ends it.

    A balanced walk rather than a regex, because the value may carry a call
    (`.trim()`), a ternary or a template string, and stopping at the first
    comma would cut `t('a', {b: 1})` in half.
    """
    depth, index, out = 0, start, []
    while index < len(text):
        char = text[index]
        if char in "'\"`":
            end = index + 1
            while end < len(text) and text[end] != char:
                end += 2 if text[end] == "\\" else 1
            out.append(text[index:end + 1])
            index = end + 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and (char == ","
                             or (char == "\n" and text[index - 1] not in "?:+")):
            break
        out.append(char)
        index += 1
    return "".join(out)


def _string_tokens(raw: str) -> list[str]:
    """Class names inside one string, interpolations included.

    A `${...}` hole is read rather than skipped, because that is where the
    interesting half usually lives: `poe ${mode === '0' ? 'off' : 'on'}` names
    two classes and neither is outside the braces. Anything in there that is
    not a plain name — `${roles.join(' ')}`, `${t('switch.x')}` — yields
    nothing and is meant to.
    """
    tokens: list[str] = []
    for part in re.split(r"(\$\{[^}]*\})", raw):
        if part.startswith("${"):
            for found in _STRING.finditer(part):
                inner = next(one for one in found.groups() if one is not None)
                tokens.extend(_string_tokens(inner))
        else:
            tokens.extend(part.split())
    return tokens


def _class_sets() -> tuple[dict, dict]:
    """What the JS writes: whole class lists, and lone fragments.

    Returns ({frozenset(names): {file}}, {name: {file}}) — the first from
    `class:` attributes, the second from `classList`/`className` writes.
    """
    whole: dict[frozenset, set[str]] = {}
    fragments: dict[str, set[str]] = {}

    def names(text: str, at: int) -> list[str]:
        value = _COMPARISON.sub(" ", _class_expression(text, at))
        found = []
        for string in _STRING.finditer(value):
            raw = next(one for one in string.groups() if one is not None)
            found += [token for token in _string_tokens(raw)
                      if _CLASS_TOKEN.fullmatch(token)]
        return found

    for path in _js_files():
        text = _code(path)
        for match in _CLASS_ATTRIBUTE.finditer(text):
            written = names(text, match.end())
            if written:
                whole.setdefault(frozenset(written), set()).add(path.name)
        for match in _CLASS_FRAGMENT.finditer(text):
            for name in names(text, match.end()):
                fragments.setdefault(name, set()).add(path.name)
    return whole, fragments


def _css_compounds() -> set[frozenset]:
    """Every class combination the stylesheets have a rule for.

    `.pm-port.feed .shell` contributes two: {pm-port, feed} and {shell}. The
    combination is the point — `.ok` on its own styles nothing, and an element
    that writes only `ok` gets nothing, however many `.something.ok` rules
    exist.
    """
    text = "\n".join(path.read_text(encoding="utf-8")
                     for path in sorted(CSS_DIR.glob("*.css")))
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    compounds = set()
    for block in re.finditer(r"(^|[};])\s*([^{};@]+?)\s*\{", text, re.MULTILINE):
        for selector in block.group(2).split(","):
            # `:not(.x)` and `[data-state="ok"]` are conditions on the element,
            # not classes it must carry.
            pruned = re.sub(r":[a-z-]+\([^)]*\)", " ", selector)
            pruned = re.sub(r"\[[^\]]*\]", " ", pruned)
            for sequence in re.split(r"[\s>+~]+", pruned):
                found = frozenset(
                    re.findall(r"\.(-?[A-Za-z_][\w-]*)", sequence))
                if found:
                    compounds.add(found)
    return compounds


def _uncovered(written: frozenset, compounds: set[frozenset]) -> list[str]:
    """Names in `written` that no applicable rule mentions."""
    return sorted(name for name in written
                  if not any(name in rule and rule <= written
                             for rule in compounds))


# Classes that predate this gate and style nothing. Each is a modifier written
# beside a class that does carry the styling, so nothing is broken today —
# they are listed rather than deleted because removing them means touching six
# screens this gate was not written to change. Adding to this list is a way of
# saying "on purpose"; the default is to give the class a rule or drop it.
CLASSES_WITHOUT_RULES: dict[str, str] = {
    "adb-op-note": "modifier beside .info, which carries the styling",
    "ip-lcd-settings": "modifier beside .setting-section",
    "job-row-box": "wrapper the queue styles through its parent",
    "legend-plain": "modifier beside .legend",
}

# The closed vocabulary of `[data-state]`. `dotState` in the switch port table
# picks from it, and a name it invented instead would paint nothing.
_STATE_DECLARED = re.compile(r'\[data-state="([a-z]+)"\]')
_DOT_STATE_BODY = re.compile(
    r"function dotState\(port\) \{(.*?)\n\}", re.DOTALL)


def _code(path) -> str:
    """Strips comments and returns the code only.

    Forbidden-API checks must not trip over comments: the "no innerHTML"
    note at the top of a file is the rule, not a violation of it.
    """
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("//"))


class Frontend(unittest.TestCase):

    def test_19_js_modules_pass_lint(self):
        """A real lint+type check when deno is present; skipped otherwise."""
        deno = shutil.which("deno")
        if not deno:
            self.skipTest("deno is not installed — the JS lint check was "
                          "skipped (install: brew install deno)")
        # The TEST sources are linted too. They import the production
        # modules, so a rule that holds for one holds for the other, and a
        # test file is exactly where a stray `console.log` survives.
        lint = subprocess.run([deno, "lint", str(JS_DIR), str(JS_TEST_DIR)],
                              capture_output=True, text=True, timeout=180,
                              check=False)
        self.assertEqual(lint.returncode, 0,
                         f"deno lint errors:\n{lint.stderr}")
        check = subprocess.run(
            [deno, "check", "--no-lock", str(JS_DIR / "app.js")],
            capture_output=True, text=True, timeout=180, check=False)
        self.assertEqual(check.returncode, 0,
                         f"deno check errors:\n{check.stderr}")

    def test_19d_the_javascript_unit_tests_pass(self):
        """Run tests/js/ — otherwise nothing does.

        These assert against the real modules under static/js, and until
        now they were listed in the README and run by hand. Reached from
        here rather than as a CI step so that one command still checks
        everything, on every platform the matrix covers.

        `--no-lock`: there is no deno.json or deno.lock in this repository,
        and a lock file appearing would fail the "is the working tree clean"
        step in CI. `--allow-read` is for tests/js/api_transport_test.js,
        which reads the real message catalogue.
        """
        deno = shutil.which("deno")
        if not deno:
            self.skipTest("deno is not installed — the JS unit tests were "
                          "skipped (install: brew install deno)")
        result = subprocess.run(
            [deno, "test", "--no-lock", "--allow-read", str(JS_TEST_DIR)],
            capture_output=True, text=True, timeout=180, check=False,
            cwd=settings.ROOT)
        self.assertEqual(result.returncode, 0,
                         f"deno test failures:\n{result.stdout}\n{result.stderr}")
        # A file whose assertions all sit at module level reports zero tests
        # and would pass this silently. Every test file must register some.
        for path in sorted(JS_TEST_DIR.glob("*_test.js")):
            self.assertIn("Deno.test", path.read_text(encoding="utf-8"),
                          f"{path.name} registers no test with Deno.test, so "
                          "`deno test` reports nothing for it")

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
        for element_id in ("app", "mode-badge", "leave-admin-btn",
                           "locked-btn", "queue-btn", "refresh-btn",
                           "auto-btn", "scan-group",
                           "locked-panel", "queue-panel", "toast",
                           "set-picker"):
            self.assertIn(f'id="{element_id}"', html, element_id)
        # Refreshing cannot be stopped: there is deliberately no pause button.
        self.assertNotIn('id="pause-btn"', html)
        # THERE IS NO ROLE SCREEN AND NO ADMIN PASSWORD. The package decides
        # what the user is (panel/editions), and admin mode is opened with
        # the service key. A password box here would be a second way in.
        for gone in ("role-screen", "role-user", "role-admin", "admin-form",
                     "admin-password"):
            self.assertNotIn(f'id="{gone}"', html, gone)
        self.assertNotIn('type="password"', html)
        # The application is the first thing on screen; nothing stands in
        # front of it waiting to be dismissed. Matched without the closing
        # bracket: the shell carries attributes now (the density the tables
        # read through the cascade), and what this asserts is that the
        # application opens here, not what is written on the tag.
        body = html.split("<body>", 1)[1]
        opening = re.match(r"\s*(?:<!--[\s\S]*?-->\s*)*(<div id=\"app\"[ >])",
                           body)
        self.assertIsNotNone(opening, "#app is not the first thing in the body")
        # Accessibility: icon buttons must not be left without a label
        self.assertIn('aria-label="Job queue"', html)
        self.assertIn('lang="en"', html)
        self.assertIn('<script type="module"', html)

    def test_every_view_has_a_container_and_a_render_function(self):
        """A route with no container renders into nothing, silently.

        `VIEWS` in app.js maps a view id to a selector plus a render call. A
        selector naming an element that is not in index.html produces no
        error — the screen simply stays blank — so the two are checked
        against each other here.
        """
        html = (settings.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        app = (JS_DIR / "app.js").read_text(encoding="utf-8")
        table = app.split("const VIEWS = {")[1].split("\n};")[0]
        views = re.findall(r"^\s*(\w+): \['#([\w-]+)'", table, re.MULTILINE)
        self.assertGreaterEqual(len(views), 12)
        for name, container in views:
            self.assertIn(f'id="{container}"', html, name)
        # The two screens this test was written for, named so the check
        # cannot pass by finding nothing.
        self.assertIn(("adb", "v-adb"), views)
        self.assertIn(("switch", "v-switch"), views)

    def test_every_stylesheet_the_shell_links_is_bundled(self):
        """A stylesheet linked but not listed in the bundler is lost.

        The desktop build inlines the files in its own CSS_FILES list; one
        that is only in index.html loads in `--browser` mode and is simply
        absent from the packaged application, which is the harder bug to
        notice.
        """
        html = (settings.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        builder = (settings.ROOT / "tools" / "build_desktop_bundle.py"
                   ).read_text(encoding="utf-8")
        linked = re.findall(r'<link rel="stylesheet" href="/css/([\w.-]+)"',
                            html)
        self.assertIn("switch.css", linked)
        listed = set(re.findall(r'"css" / "([\w.-]+)"', builder))
        self.assertEqual(sorted(set(linked) - listed), [],
                         "linked in index.html but not bundled")

    def test_every_class_the_js_writes_has_a_css_rule(self):
        """A class with no rule renders nothing and says nothing.

        The switch screen asked for `.poe on` and the ADB screen for
        `.pill ok`; the stylesheets have `.pill.on` and `.pill.off` and
        nothing else, so both came out with the plain look and no error
        anywhere. Checked as COMBINATIONS: `ok` exists in the CSS — inside
        `.pill.ok` — and a check that only asked "is this name styled
        somewhere" would have passed both of them.
        """
        whole, fragments = _class_sets()
        compounds = _css_compounds()
        # Named so the check cannot pass by finding nothing.
        self.assertGreater(len(whole), 300)
        self.assertIn(frozenset({"pm-case"}), whole)

        broken = {}
        for written, files in whole.items():
            for name in _uncovered(written, compounds):
                if name not in CLASSES_WITHOUT_RULES:
                    broken[f"{name} (written as {sorted(written)})"] = files
        # A `classList.add` never shows the rest of the element's classes, so
        # those get the weaker question: is this name styled at all?
        styled = {name for rule in compounds for name in rule}
        for name, files in fragments.items():
            if name not in styled and name not in CLASSES_WITHOUT_RULES:
                broken[name] = files
        self.assertEqual(broken, {}, "class written by the JS with no CSS rule")

        # The allowlist is not allowed to go stale either: an entry that has
        # since been given a rule, or is no longer written anywhere, is a line
        # nobody would think to delete.
        every = {name for written in whole for name in written} | set(fragments)
        for name, reason in CLASSES_WITHOUT_RULES.items():
            self.assertIn(name, every, f"{name}: no longer written ({reason})")
            self.assertNotIn(name, styled, f"{name}: has a rule now ({reason})")

    def test_the_port_table_paints_dots_with_declared_states(self):
        """`dotState` picks from the panel's vocabulary, not one of its own.

        The gate above sees only literal class names, so `dot ${kind}` told it
        nothing about what `kind` could be. This reads the four answers
        `dotState` actually returns and checks each has a `[data-state]` rule.
        """
        components = (CSS_DIR / "components.css").read_text(encoding="utf-8")
        declared = set(_STATE_DECLARED.findall(components))
        self.assertIn("link", declared)   # added for the switch port table

        body = _DOT_STATE_BODY.search(_code(JS_DIR / "views" / "switch"
                                            / "ports.js"))
        self.assertIsNotNone(body, "dotState is gone or has been renamed")
        # `=== 'up'` is the port's data, not a state name.
        source = _COMPARISON.sub(" ", body.group(1))
        returned = set(re.findall(r"'([a-z]+)'", source))
        self.assertEqual(returned, {"failed", "ok", "link", "unknown"})
        self.assertEqual(sorted(returned - declared), [])

    def test_one_front_panel_drawing_serves_both_screens(self):
        """The faceplate must not be drawn in two places again.

        The IP assignment screen and the Switch screen show the front of the
        same switch. They each had their own copy of the connector SVG and the
        grid arithmetic, which is how two panels end up disagreeing about
        where port 7 is. Both now import the one component; this fails if
        either grows its own again.
        """
        component = JS_DIR / "components" / "front_panel.js"
        self.assertTrue(component.is_file())
        users = (JS_DIR / "views" / "ip" / "panel.js",
                 JS_DIR / "views" / "switch" / "front_panel.js")
        for path in users:
            code = _code(path)
            self.assertIn("components/front_panel.js", code, path.name)
            # The two things the component owns. A screen defining either
            # again is a screen that has started drawing its own faceplate.
            self.assertNotIn("'shell'", code, path.name)
            self.assertNotIn("pm-grid", code, path.name)
        # And the component is the only place they live.
        source = _code(component)
        self.assertIn("'shell'", source)
        self.assertIn("pm-grid", source)

    def test_the_shell_carries_its_navigation_landmarks(self):
        """What a screen reader and a keyboard need to move around at all.

        Changing screen used to leave focus on the menu button and say
        nothing: the whole content area swapped underneath without a word.
        These four elements are what `announceView` in js/app.js writes to.
        """
        html = (settings.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("<main class=\"content\" id=\"content\"", html)
        self.assertIn('class="skip-link" href="#content"', html)
        self.assertIn('id="view-title"', html)
        self.assertIn('id="route-status"', html)
        # The live region has to be its own: #toast holds one message at a
        # time and the job queue overwrites it constantly.
        self.assertNotIn('id="route-status" ', html.split('id="toast"')[0])

    def test_css_files_exist_and_are_not_empty(self):
        for name in ("base.css", "components.css", "views.css", "ip.css",
                     "switch.css"):
            path = CSS_DIR / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(len(path.read_text(encoding="utf-8")), 500, name)

    # ── the design system's two measurable promises ──────────────────
    def test_every_text_colour_reaches_the_contrast_floor(self):
        """No text token may drop below 4.5:1 on the grounds it sits on.

        The panel is read standing up in a depot. `--text-dim` shipped at
        3.38:1 for months — carrying timestamps, hints and the footer, almost
        always at the smallest size — and nobody noticed by eye, which is the
        whole argument for measuring it here instead.

        Only the values that carry TEXT are checked. The state fills paint
        dots and edges, where telling four states apart matters more than
        contrast, and they have their own `*-text` variants for words.
        """
        tokens = _colour_tokens()
        grounds = [tokens[name] for name in ("bg", "panel", "panel-2")]
        carries_text = ("text", "text-bright", "text-mid", "text-dim",
                        "brand", "accent", "ok-text", "auth-text",
                        "failed-text", "unknown-text", "danger-text")
        failures = []
        for name in carries_text:
            self.assertIn(name, tokens, f"--{name} is gone from base.css")
            for ground in grounds:
                found = _contrast(tokens[name], ground)
                if found < 4.5:
                    failures.append(f"--{name} on {ground}: {found:.2f}:1")
        self.assertEqual(failures, [], "text below 4.5:1:\n  "
                                       + "\n  ".join(failures))

    def test_a_colour_is_only_ever_chosen_in_base_css(self):
        """Every colour is a token; the literals live in one block.

        The companion of the contrast gate above, and the reason it can be
        trusted: a gate that measures the tokens proves nothing while the
        screens are mixing their own colours beside them. They were — one
        light, `#d6ebff`, appeared at fifteen different alphas of which three
        were tokens, the accent at twelve, and nine greys were hand-mixed in
        hex. Two cards carried different borders and nobody could say why.

        `black` and `transparent` are allowed: the first is only ever a mask
        stencil, the second is the absence of a colour rather than one.
        """
        base = CSS_DIR / "base.css"
        literal = re.compile(r"rgba?\([\d\s,.]+\)|#[0-9a-fA-F]{3,8}\b")
        offenders = []
        for path in sorted(CSS_DIR.glob("*.css")):
            text = path.read_text(encoding="utf-8")
            # base.css declares the palette; only its `:root` block may.
            if path == base:
                text = text.split("\n}\n", 1)[1]
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
            for number, line in enumerate(text.splitlines(), 1):
                if literal.search(line):
                    offenders.append(f"{path.name}: {line.strip()}")
        for path in _js_files():
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if "style:" in line and literal.search(line):
                    name = path.relative_to(JS_DIR).as_posix()
                    offenders.append(f"js/{name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [],
                         "a colour chosen outside base.css:\n  "
                         + "\n  ".join(offenders))

    def test_a_font_size_is_only_ever_chosen_in_the_scale(self):
        """Sizes come from `--fs-*`, in rem, and from nowhere else.

        There were once 125 font-size declarations over 22 values — eleven
        steps inside five pixels — plus 49 more written inline in JavaScript.
        Half-pixel steps carry no meaning on screen; they are just the trace
        of every screen picking a size for itself.
        """
        offenders = []
        for path in sorted(CSS_DIR.glob("*.css")):
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"font-size:\s*[\d.]+(px|pt|%)", line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        for path in _js_files():
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if "font-size" in line:
                    name = path.relative_to(JS_DIR).as_posix()
                    offenders.append(f"js/{name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [],
                         "a size chosen outside the scale:\n  "
                         + "\n  ".join(offenders))

    def test_a_space_is_only_ever_chosen_in_the_scale(self):
        """Margins, paddings and gaps come from `--sp-*` and nowhere else.

        The twin of the font-size gate above, and it was missing for as long
        as the type scale had one: 23 distinct pixel values across the five
        stylesheets, 9 and 10 and 11 all doing the same job. Spacing sets a
        screen's rhythm more than type size does, so a value picked by hand
        here is worth more than one picked by hand there.

        Negative values are left alone. A `-1px` clip or a `-2px` optical
        nudge corrects something the box model did; it is not rhythm, and
        there is no scale step it could come from.
        """
        declaration = re.compile(
            r"(?<![-\w])(?:margin|padding|gap|row-gap|column-gap)"
            r"(?:-(?:top|bottom|left|right))?\s*:\s*[^;}]*")
        # `-4px` is a correction; `var(--sp-1)` and `4px` are not the same
        # thing, so only a bare positive length is an offender.
        positive_px = re.compile(r"(?<![-\w.])\d+(?:\.\d+)?px")
        offenders = []
        for path in sorted(CSS_DIR.glob("*.css")):
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                for found in declaration.finditer(line):
                    if positive_px.search(found.group(0)):
                        offenders.append(f"{path.name}:{number}: "
                                         f"{line.strip()}")
                        break
        self.assertEqual(offenders, [],
                         "a space chosen outside the scale:\n  "
                         + "\n  ".join(offenders))

    def test_layout_is_not_written_inline_in_the_javascript(self):
        """A view may compute a colour or a width; it may not lay itself out.

        The mirror of the class-name gate above. Eighty inline `style:`
        strings were doing layout — margins, displays, gaps, flex settings,
        three grid templates — and a rule written there is invisible from the
        stylesheets: whoever goes looking for a gap cannot find it, and the
        spacing scale cannot reach it either.

        What stays inline is what comes from DATA and could not be written
        ahead of time: the state colour of a row, the width of a progress
        bar, the `--table-columns` a screen computes for its own table.
        """
        layout = re.compile(
            r"(?:^|;|\s)(margin|padding|gap|row-gap|column-gap|display|flex"
            r"|grid|align-items|align-self|align-content|justify-content"
            r"|justify-items|justify-self|order|float)"
            r"(?:-[a-z]+)*\s*:")
        value = re.compile(r"""\bstyle:\s*(?:'([^']*)'|"([^"]*)"|`([^`]*)`)""")
        offenders = []
        for path in _js_files():
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                for found in value.finditer(line):
                    text = next(group for group in found.groups()
                                if group is not None)
                    if layout.search(text):
                        name = path.relative_to(JS_DIR).as_posix()
                        offenders.append(f"js/{name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [],
                         "layout written inline; give it a class:\n  "
                         + "\n  ".join(offenders))

    def test_the_layout_answers_to_three_widths_and_no_others(self):
        """The 1440 base design must not overflow — at three widths only.

        There were six: 620, 720, 900, 1080, 1081 and 1180. Every screen
        with a rail beside its content had picked its own, so narrowing the
        window slowly dropped the application to one column four separate
        times. A rail now collapses at the width its own KIND collapses at
        (see the note in base.css), which leaves three.

        `min-width` counts as its `max-width` neighbour: 901 is the far side
        of 900, not a fourth width.
        """
        base = (CSS_DIR / "base.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 900px)", base)
        self.assertIn("@media (max-width: 620px)", base)
        components = (CSS_DIR / "components.css").read_text(encoding="utf-8")
        self.assertIn("overflow-x: auto", components)   # wide tables scroll

        allowed = {620, 900, 1180}
        found = {}
        for path in sorted(CSS_DIR.glob("*.css")):
            text = path.read_text(encoding="utf-8")
            for kind, width in re.findall(
                    r"\((?:(max)|min)-width:\s*(\d+)px\)", text):
                width = int(width) if kind else int(width) - 1
                found.setdefault(width, set()).add(path.name)
        extra = {width: sorted(names) for width, names in found.items()
                 if width not in allowed}
        self.assertEqual(extra, {}, f"a fourth width: {extra}")

        # And the rails the widths belong to.
        self.assertIn("--rail: 320px", base)
        self.assertIn("--rail-wide: 420px", base)
        # The JS has to agree about when the side panel stops overlaying.
        app = (JS_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("OVERLAY_PANEL_MAX = 900", app)

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
