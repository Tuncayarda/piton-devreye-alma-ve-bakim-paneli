#!/usr/bin/env python3
"""The code base is written in English.

The panel was originally written in Turkish and translated in one pass. A
single pass is not what keeps it translated: the next hurried fix reintroduces
a Turkish label, and nothing notices until someone reads that screen.

This test is the thing that notices. It scans every source file — code,
markup, stylesheets, workflows, packaging scripts, tests — for two kinds of
residue:

  1. Turkish-specific letters (ç ğ ı ö ş ü and their capitals).
  2. Turkish words spelled in plain ASCII, which slip past the first check.

Documentation is DELIBERATELY out of scope: docs/, README.md, LICENSE and the
other Markdown files stay in Turkish, because they are written for the people
who commission the trains.

The allowlist below is deliberately narrow, per file, and every entry carries
the reason it is there. It exists for values that belong to something outside
this code base — a Turkish Windows console, a customer's device inventory —
where translating would break a real behaviour. It is not a place to park a
string that has not been translated yet.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from panel import settings

# ── what is scanned ──────────────────────────────────────────────────────
# Extensions that hold source text. Anything else (images, spreadsheets,
# fonts) is binary as far as this test is concerned.
SOURCE_SUFFIXES = {
    ".py", ".js", ".css", ".html", ".json", ".yml", ".yaml", ".spec",
    ".sh", ".iss", ".toml", ".cfg", ".ini",
}
# Files with no suffix that are still source.
SOURCE_NAMES = {".gitignore", ".gitattributes"}

# Documentation is out of scope — see the module docstring. Only these are
# skipped; no source directory is excluded wholesale.
DOC_PATHS = {"README.md", "LICENSE"}
DOC_PREFIXES = ("docs/",)


def _tracked_files() -> list[Path]:
    """Every file git knows about, tracked or not, minus what git ignores."""
    listing = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=settings.ROOT, capture_output=True, text=True, check=True)
    return [Path(name) for name in listing.stdout.split("\n") if name]


def _in_scope(name: str) -> bool:
    if name in DOC_PATHS or name.startswith(DOC_PREFIXES):
        return False
    if name.endswith(".md"):
        return False
    path = Path(name)
    return path.suffix in SOURCE_SUFFIXES or path.name in SOURCE_NAMES


# ── check 1: Turkish letters ─────────────────────────────────────────────
TURKISH_LETTERS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")

# ── check 2: Turkish words written in ASCII ──────────────────────────────
# Only unambiguous words: nothing that is also an English word, a protocol
# name (PISCU, UIC, MQTT, SIP, PBX, ARP, PoE, Asterisk, DeviceMap) or a
# plausible identifier fragment. A short list that never cries wolf is worth
# more than a long one that gets muted.
TURKISH_WORDS = (
    "acilir", "adresi", "adresleme", "aktif", "arama", "atlandi", "ayarlar",
    "bagli", "baglanti", "baglantisi", "basarili", "basarisiz", "baslat",
    "bekleyen", "besliyor", "betik", "betikler", "bilesen", "bildirim",
    "bilgileri", "bilgisayar", "bilgisi", "bilinmeyen", "bulunamadi",
    "bulundu", "calisiyor", "cihaz", "cihazi", "cihazlar", "dahil", "deger",
    "degeri", "degistir", "diyalog", "dogrulama", "dosya", "dosyalar",
    "durduruldu", "gecmis", "gerekli", "gerekiyor", "gonder", "goster",
    "guncelle", "guvenlik", "hata", "hatasi", "ilerleme", "iptal", "islem",
    "islemi", "islemler", "kapali", "kapat", "katagori", "kategori",
    "kaydet", "kayit", "kimlik", "kod", "konfig", "korunan", "kullanici",
    "kuyruk", "masaustu", "okunamadi", "okundu", "olustur", "parametresi",
    "parola",
    "portlar", "portlari", "portu", "sayfa", "secildi", "secili", "secim",
    "sifre", "sonuc", "surum", "sutun", "tamamlandi", "tarama", "tumu",
    "uyari", "yazildi", "yazilim", "yenile", "yetki", "yukle", "yuklendi",
)
# TURKISH IS AGGLUTINATIVE, so the stem is only the beginning of the word:
# "yenile" is in the list above, but what leaked through was "yenileme", and
# an exact-word match cannot see it — the "me" on the end breaks the word
# boundary. A bounded suffix closes that: five letters covers the endings
# that actually occur ("adresinden", "portunda", "parolasi", "koduyla") and
# stays short enough not to swallow a longer, unrelated word.
#
# Measured before it was adopted: the looser form flagged eight more lines
# across the tree and produced no false positives. Two of the eight were
# user-facing Turkish sentences in a field script that both earlier checks
# had walked past.
ASCII_WORD = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(TURKISH_WORDS) + r")[a-z]{0,5}"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE)

# ── allowlist ────────────────────────────────────────────────────────────
# path -> ((fragment that may appear, why it may appear), ...)
# A line is exempt only when it CONTAINS one of that file's fragments.
ALLOWED: dict[str, tuple[tuple[str, str], ...]] = {
    # The panel matches the switch inventory against the customer's live
    # DeviceMap over MQTT. These names are the ones the field devices
    # publish; translating them would stop the match.
    "devicemaps/yatakli/DeviceMap_Yatakli.json": (
        ("Yataklı", "switch names published by the customer's DeviceMap"),
    ),
    "static/js/views/devices.js": (
        ("Yataklı_1", "example of a real DeviceMap switch name"),
    ),
    # The device search folds Turkish spelling so that an operator typing on
    # an ASCII keyboard still finds the device. The letters ARE the data it
    # folds: removing them would not translate the search, it would break it.
    "static/js/core/store.js": (
        ("const TURKISH =", "the alphabet the device search folds"),
    ),
    # A language names ITSELF in its own language, always: someone looking for
    # Turkish should not have to read English to find it.
    "static/js/components/language.js": (
        ("Türkçe", "endonym — a language is never translated in the picker"),
    ),
    # Proving that a message renders in Turkish means writing the Turkish out.
    "tests/test_i18n.py": (
        ('"Admin modu"', "expected Turkish rendering of topbar.adminMode"),
        ('"Tren seti 3 yüklendi"',
         "expected Turkish rendering of topbar.setLoaded"),
    ),
    # Console tools on a Turkish Windows write in the OEM code page. These
    # comments name the exact character that used to break decoding, so the
    # letter has to be there.
    "panel/system/interfaces.py": (
        ('"ı" in the first line', "names the byte that breaks cp1254"),
    ),
    "field_scripts/intercom_ip_assign.py": (
        ('for "ı" is undefined', "names the byte that breaks cp1254"),
    ),
    # Real `ipconfig /all` and `arp -a` output from a Turkish Windows, kept
    # verbatim: the decoding bug these tests pin down only reproduces with
    # the original bytes.
    "tests/test_switch.py": (
        ('the byte for "ı"', "names the byte that breaks cp1254"),
        ("Windows IP Yapılandırması", "verbatim Turkish `ipconfig` output"),
        ("Ana Bilgisayar Adı", "verbatim Turkish `ipconfig` output"),
        ("Ethernet bağdaştırıcısı", "verbatim Turkish `ipconfig` output"),
        ("DNS Soneki", "verbatim Turkish `ipconfig` output"),
        ("Açıklama. . .", "verbatim Turkish `ipconfig` output"),
        ("Fiziksel Adres", "verbatim Turkish `ipconfig`/`arp` output"),
        ("DHCP Etkin", "verbatim Turkish `ipconfig` output"),
        ("Alt Ağ Maskesi", "verbatim Turkish `ipconfig` output"),
        ("Varsayılan Ağ Geçidi", "verbatim Turkish `ipconfig` output"),
        ("Internet Adresi", "verbatim Turkish `arp -a` output"),
        ("IPv4 Adresi", "verbatim Turkish `ipconfig` output"),
    ),
    # The same verbatim `ipconfig` output, for the other half of the problem:
    # the labels are translated, so the adapter parser must read the numbers
    # by position and never by label.
    "tests/test_network.py": (
        ("Windows IP Yapılandırması", "verbatim Turkish `ipconfig` output"),
        ("Ethernet bağdaştırıcısı", "verbatim Turkish `ipconfig` output"),
        ("Fiziksel Adres", "verbatim Turkish `ipconfig` output"),
        ("Alt Ağ Maskesi", "verbatim Turkish `ipconfig` output"),
        ("Varsayılan Ağ Geçidi", "verbatim Turkish `ipconfig` output"),
        ("IPv4 Adresi", "verbatim Turkish `ipconfig` output"),
    ),
    "tests/test_language.py": (
        ("__self__", "this file lists the very words it searches for"),
    ),
    # The product's own name, as the operators who commission the trains know
    # it. Inside the app this name follows the chosen language ("app.name" in
    # the catalogue); these three are stamped in at BUILD time and cannot,
    # so they are written in the language of the people who install and run
    # it. Every FILE the build produces is still named "dabp".
    # There is one place now: the edition table. `dabp.spec`, the Inno
    # script and the Release title all read the name from there, so it is
    # written once, in the language of the people who install and run it.
    # Every FILE the build produces is still named "dabp-<edition>".
    "panel/editions/catalogue.py": (
        ("Devreye Alma ve Bakım Paneli",
         ("product name: macOS bundle, Windows resource, setup wizard, "
         "Release title")),
        ("Yataklı", "project name as the customer's DeviceMap spells it"),
    ),
    # Kept as the #ifndef fallback, for a build run by hand without /D.
    "packaging/windows/dabp.iss": (
        ("Devreye Alma ve Bakım Paneli",
         "setup wizard, Start menu and uninstall entry"),
    ),
}


# Files that are exempt as a whole, with the reason they have to be.
WHOLE_FILE_EXEMPT = {
    # The word list this test searches for lives here.
    "tests/test_language.py",
    # The Turkish catalogue: being Turkish is its entire job.
    "panel/messages/tr.json",
    # The alphabet the device search folds, and the spellings an operator
    # types looking for it: this test is about those letters, so exempting
    # them one line at a time would exempt most of the file anyway.
    "tests/js/search_fold_test.js",
}


def _allowed(name: str, line: str) -> bool:
    if name in WHOLE_FILE_EXEMPT:
        return True
    for fragment, _reason in ALLOWED.get(name, ()):
        if fragment in line:
            return True
    return False


# ── check 3: screen text must come from the catalogue ────────────────────
# The two checks above look for the WRONG LANGUAGE. This one looks for text
# that has no language at all yet: an English sentence written straight into
# a view, which a language switch cannot touch.
#
# That is not a hypothetical. The first pass at translating the UI stopped
# part-way through most files — `checklist.js` ended up with 29 translated
# strings sitting next to 31 untranslated ones — and nothing noticed, because
# nothing was looking. The panel shipped screens that stayed English however
# the language was set, and it was found by a person using it.
#
# What counts as screen text: a quoted literal that reads like a sentence —
# two or more words with a space between them, starting with a capital. That
# shape catches labels, headings, tooltips and empty-state text wherever they
# sit (a named `text:` property, a positional argument, an array of
# children), while class names, event names, API paths and SVG path data all
# fail it on their own. Placeholders are stripped first, so a template
# literal is judged on its words rather than its `${...}` gaps.
_QUOTED = re.compile(r"""(['"`])((?:[^'"`\\\n]|\\.)*?)\1""")
_PLACEHOLDER = re.compile(r"\$\{[^}]*\}")
_SVG_PATH = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz][-\d\s.,]")
_WORD = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2,}")


def _screen_text(literal: str) -> bool:
    """Does this literal read like something a person is meant to read?"""
    text = _PLACEHOLDER.sub(" ", literal).strip()
    if not text or _SVG_PATH.match(text):
        return False
    # A literal that OPENS WITH A SPACE is usually a sentence fragment glued
    # onto a value — " included", " · powering" — and is judged on its own,
    # because such a fragment is one lowercase word and would fail every
    # rule below. A class name appended the same way (" active") has the
    # very same shape and cannot be told apart here; the three that exist
    # are named in the allowlist.
    if literal[:1].isspace():
        return any(len(word) >= 3 for word in _WORD.findall(text))
    if " " not in text or len(_WORD.findall(text)) < 2:
        return False
    # A literal that merely STARTS with a placeholder keeps its
    # capitalisation rule waived: the sentence begins with the value.
    return text[0].isupper() or literal.lstrip().startswith("${")


def _screen_texts(source: str):
    """Yield (line number, literal) for every screen-looking string."""
    for number, line in enumerate(source.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        for match in _QUOTED.finditer(line):
            literal = match.group(2)
            if _screen_text(literal):
                yield number, literal


# path -> ((fragment that may appear, why), ...). Same rules as ALLOWED
# above: narrow, per file, and every entry says why. This is for text that
# looks like a sentence but is not one a user reads. It is NOT somewhere to
# park a string that has not been translated yet.
SCREEN_TEXT_ALLOWED: dict[str, tuple[tuple[str, str], ...]] = {
    # CSS class names appended to a class list. They open with a space like
    # a sentence fragment does, and nothing in the text can tell the two
    # apart — see _screen_text.
    "static/js/components/action_tabs.js": (
        (" active", "CSS class appended to the tab's class list"),
    ),
    "static/js/views/config.js": (
        (" cfg-inherited", "CSS class appended to the field's class list"),
    ),
    "static/js/views/ip/panel.js": (
        (" unpowered", "CSS class appended to the port's class list"),
    ),
    "static/js/views/switch/front_panel.js": (
        (" unpowered", "CSS class appended to the port's class list"),
    ),
    # The menu shell moved out of the switch screen and is shared now; the
    # drawer's action buttons are built from a list rather than written out,
    # so their class is assembled the same way.
    "static/js/components/context_menu.js": (
        (" is-selected", "CSS class appended to the menu row's class list"),
    ),
    "static/js/components/detail.js": (
        (" btn-primary", "CSS class appended to the action button's class"),
    ),
}


class CodeIsInEnglish(unittest.TestCase):

    def _scan(self, pattern) -> list[str]:
        findings = []
        for relative in _tracked_files():
            name = relative.as_posix()
            if not _in_scope(name):
                continue
            path = settings.ROOT / relative
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                match = pattern.search(line)
                if match and not _allowed(name, line):
                    findings.append(
                        f"{name}:{number}: {match.group(0)!r} in "
                        f"{line.strip()[:90]}")
        return findings

    def test_no_turkish_letters_in_the_code(self):
        findings = self._scan(TURKISH_LETTERS)
        self.assertEqual(findings, [], "Turkish letters found in code:\n  "
                                       + "\n  ".join(findings))

    def test_no_turkish_words_written_in_ascii(self):
        findings = self._scan(ASCII_WORD)
        self.assertEqual(findings, [], "Turkish words found in code:\n  "
                                       + "\n  ".join(findings))

    def test_the_allowlist_is_still_needed(self):
        """A stale entry is worse than none: it hides the next regression.

        Every allowlisted file must exist, and every fragment must still
        appear in it.
        """
        stale = []
        for name, entries in ALLOWED.items():
            if name in WHOLE_FILE_EXEMPT:
                continue
            path = settings.ROOT / name
            if not path.is_file():
                stale.append(f"{name}: the file is gone")
                continue
            text = path.read_text(encoding="utf-8")
            for fragment, reason in entries:
                if fragment not in text:
                    stale.append(f"{name}: {fragment!r} ({reason}) is gone")
        self.assertEqual(stale, [], "stale allowlist entries:\n  "
                                    + "\n  ".join(stale))

    def test_the_scan_actually_covers_the_source_tree(self):
        """A scan that silently matches nothing proves nothing."""
        scanned = [name for name in (p.as_posix() for p in _tracked_files())
                   if _in_scope(name)]
        self.assertGreater(len(scanned), 100)
        for required in ("app.py", "panel/settings.py", "static/index.html",
                         "static/js/app.js", "static/css/base.css",
                         "field_scripts/device_verify.py",
                         "tools/build_desktop_bundle.py",
                         "tests/test_language.py",
                         ".github/workflows/ci.yml",
                         "packaging/appimage.sh",
                         "packaging/windows/dabp.iss"):
            self.assertIn(required, scanned, required)
        # ...and documentation is genuinely left alone.
        for excluded in ("README.md", "LICENSE", "docs/MIMARI.md"):
            self.assertNotIn(excluded, scanned, excluded)


class ScreenTextComesFromTheCatalogue(unittest.TestCase):
    """No sentence a user reads may be written into a view.

    See the block comment above `_screen_text` for what counts and why this
    check exists at all.
    """

    def test_no_view_writes_its_own_screen_text(self):
        findings = []
        for path in sorted((settings.ROOT / "static" / "js").rglob("*.js")):
            name = path.relative_to(settings.ROOT).as_posix()
            exempt = SCREEN_TEXT_ALLOWED.get(name, ())
            for number, literal in _screen_texts(
                    path.read_text(encoding="utf-8")):
                if any(fragment in literal for fragment, _ in exempt):
                    continue
                findings.append(f"{name}:{number}: {literal[:70]!r}")
        self.assertEqual(
            findings, [],
            f"{len(findings)} screen strings are not in the catalogue. "
            "Add a key to panel/messages/en.json and tr.json and render it "
            "with t():\n  " + "\n  ".join(findings))

    def test_the_scan_reaches_the_views(self):
        """A detector that matches nothing would pass this file silently."""
        scanned = sorted((settings.ROOT / "static" / "js").rglob("*.js"))
        self.assertGreater(len(scanned), 20)
        # Proof the detector still fires: a line lifted from the shape of the
        # real thing must be caught, and near-misses must not be.
        self.assertTrue(list(_screen_texts("el('p', { text: 'No scan yet' })")))
        self.assertTrue(list(_screen_texts("`${n} devices in total`")))
        for quiet in ("el('div', { class: 'check-summary-grid' })",
                      "icon('M4 5.5h12M4 10h12M4 14.5h8')",
                      "api.get('/api/state?set=1')",
                      "t('checklist.excelPreview')"):
            self.assertEqual(list(_screen_texts(quiet)), [], quiet)

    def test_the_screen_text_allowlist_is_still_needed(self):
        stale = []
        for name, entries in SCREEN_TEXT_ALLOWED.items():
            path = settings.ROOT / name
            if not path.is_file():
                stale.append(f"{name}: the file is gone")
                continue
            text = path.read_text(encoding="utf-8")
            for fragment, reason in entries:
                if fragment not in text:
                    stale.append(f"{name}: {fragment!r} ({reason}) is gone")
        self.assertEqual(stale, [], "stale allowlist entries:\n  "
                                    + "\n  ".join(stale))


if __name__ == "__main__":
    unittest.main()
