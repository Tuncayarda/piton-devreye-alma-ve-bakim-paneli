#!/usr/bin/env python3
"""The message catalogue is complete, consistent and actually reachable.

A translation goes wrong quietly. A key added to the code but not to the
catalogue renders as the key itself; a key translated in one language and not
the other silently falls back; a placeholder renamed on one side only produces
a sentence with `{device}` in the middle of it. None of that raises, and none
of it is visible until someone opens that screen in that language.

These tests are what makes it visible.
"""
from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

from panel import i18n, settings

PLACEHOLDER = re.compile(r"\{(\w+)\}")

# A key is not always written at a `t(...)` call: it also sits in a lookup
# table, on one side of a ternary, or in an HTML attribute. So any literal
# SHAPED like a key of a known area counts as a use — an over-match here is
# harmless, while a miss would report a live key as dead and invite someone
# to delete it.
KEY_LITERAL = re.compile(r"""['"]([a-z][a-zA-Z]*\.[a-zA-Z][\w]*)['"]""")
# Message keys named in an HTML attribute (data-i18n / -title / -aria).
HTML_KEY = re.compile(r'data-i18n(?:-title|-aria)?="([\w.]+)"')


def catalogue(language: str) -> dict:
    path = Path(i18n.MESSAGES_DIR) / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _sources():
    listing = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=settings.ROOT, capture_output=True, text=True, check=True)
    for name in listing.stdout.split("\n"):
        path = settings.ROOT / name
        if not name or not path.is_file():
            continue
        if name.startswith(("panel/", "static/js/", "tests/")) \
                or name == "static/index.html":
            if path.suffix in (".py", ".js", ".html"):
                yield name, path


def used_keys(areas: set[str]) -> set[str]:
    """Every catalogue key the code refers to.

    `areas` are the prefixes the catalogue actually defines. Without that
    filter a file name (`desktop.html`) or a dotted attribute
    (`ro.serialno`) reads as a key. The cost is that a typo inventing a
    brand-new area goes unnoticed; a typo inside a real area — by far the
    likely one — still fails the test.
    """
    keys = set()
    for name, path in _sources():
        if name.startswith("tests/"):
            continue                       # tests may name a key to assert on
        text = path.read_text(encoding="utf-8")
        found = (HTML_KEY.findall(text) if path.suffix == ".html"
                 else KEY_LITERAL.findall(text))
        keys |= {key for key in found if key.split(".")[0] in areas}
    return keys


class Catalogue(unittest.TestCase):

    def setUp(self):
        self.english = catalogue("en")
        self.turkish = catalogue("tr")
        self.areas = {key.split(".")[0] for key in self.english}

    def test_every_language_has_a_catalogue(self):
        for language in i18n.LANGUAGES:
            path = Path(i18n.MESSAGES_DIR) / f"{language}.json"
            self.assertTrue(path.is_file(), language)
            self.assertGreater(len(catalogue(language)), 100, language)

    def test_the_two_catalogues_have_the_same_keys(self):
        """A key in one and not the other falls back without saying so."""
        missing = sorted(set(self.english) - set(self.turkish))
        extra = sorted(set(self.turkish) - set(self.english))
        self.assertEqual(missing, [], f"not translated: {missing}")
        self.assertEqual(extra, [], f"no longer in English: {extra}")

    def test_the_placeholders_match(self):
        """A renamed placeholder leaves `{device}` printed on the screen."""
        wrong = []
        for key, english in self.english.items():
            here = set(PLACEHOLDER.findall(english))
            there = set(PLACEHOLDER.findall(self.turkish[key]))
            if here != there:
                wrong.append(f"{key}: en={sorted(here)} tr={sorted(there)}")
        self.assertEqual(wrong, [], "placeholder mismatch:\n  "
                                    + "\n  ".join(wrong))

    def test_no_message_is_empty(self):
        blank = sorted(key for key, text in self.english.items()
                       if not text.strip())
        blank += sorted(key for key, text in self.turkish.items()
                        if not text.strip())
        self.assertEqual(blank, [], f"empty message: {blank}")

    def test_every_key_used_in_the_code_exists(self):
        """A key with no entry renders as the key — visible, but too late."""
        unknown = sorted(used_keys(self.areas) - set(self.english))
        self.assertEqual(unknown, [], f"key not in the catalogue: {unknown}")

    def test_the_catalogue_has_no_unused_key(self):
        """Dead entries make the file grow and the translation pointless."""
        unused = sorted(set(self.english) - used_keys(self.areas))
        self.assertEqual(unused, [], f"key used nowhere: {unused}")


class Selection(unittest.TestCase):

    def setUp(self):
        # These tests switch language, and one of them WRITES the choice. The
        # cleanup has to put both the process and the file back, or every
        # module that runs afterwards renders in Turkish and compares against
        # English.
        self.addCleanup(self._restore)

    @staticmethod
    def _restore():
        i18n.reset()
        i18n.use("en")

    def test_an_unknown_language_falls_back_to_english(self):
        self.assertEqual(i18n.normalise("de"), "en")
        self.assertEqual(i18n.normalise(""), "en")
        self.assertEqual(i18n.normalise(None), "en")

    def test_a_regional_code_resolves_to_its_language(self):
        self.assertEqual(i18n.normalise("tr_TR"), "tr")
        self.assertEqual(i18n.normalise("en-GB"), "en")

    def test_a_message_renders_in_the_selected_language(self):
        i18n.use("en", persist=False)
        self.assertEqual(i18n.t("role.user"), "User")
        i18n.use("tr", persist=False)
        self.assertEqual(i18n.t("role.user"), "Kullanıcı")

    def test_a_deferred_message_follows_the_language(self):
        """This is why job rows hold a Message and not a string."""
        message = i18n.lazy("topbar.setLoaded", set=3)
        i18n.use("en", persist=False)
        self.assertEqual(str(message), "Train set 3 loaded")
        i18n.use("tr", persist=False)
        self.assertEqual(str(message), "Tren seti 3 yüklendi")

    def test_an_unknown_key_renders_as_itself(self):
        self.assertEqual(i18n.t("nothing.here"), "nothing.here")

    def test_a_missing_placeholder_stays_visible(self):
        """Better a visible gap than the word "undefined" in a sentence."""
        i18n.use("en", persist=False)
        self.assertEqual(i18n.t("topbar.setLoaded"), "Train set {set} loaded")

    def test_the_selection_is_stored_and_read_back(self):
        i18n.use("tr")
        i18n.reset()
        self.assertEqual(i18n.current(), "tr")

    def test_render_walks_a_whole_structure(self):
        i18n.use("en", persist=False)
        body = {"rows": [{"note": i18n.lazy("row.queued"), "n": 1}],
                "title": i18n.lazy("role.admin")}
        self.assertEqual(i18n.render(body),
                         {"rows": [{"note": "Queued", "n": 1}],
                          "title": "Admin"})


if __name__ == "__main__":
    unittest.main()
