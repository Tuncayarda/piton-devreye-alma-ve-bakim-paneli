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
    "kaydet", "kayit", "kimlik", "konfig", "korunan", "kullanici", "kuyruk",
    "masaustu", "okunamadi", "okundu", "olustur", "parametresi", "parola",
    "portlar", "portlari", "portu", "sayfa", "secildi", "secili", "secim",
    "sifre", "sonuc", "surum", "sutun", "tamamlandi", "tarama", "tumu",
    "uyari", "yazildi", "yazilim", "yenile", "yetki", "yukle", "yuklendi",
)
ASCII_WORD = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(TURKISH_WORDS) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE)

# ── allowlist ────────────────────────────────────────────────────────────
# path -> ((fragment that may appear, why it may appear), ...)
# A line is exempt only when it CONTAINS one of that file's fragments.
ALLOWED: dict[str, tuple[tuple[str, str], ...]] = {
    # The panel matches the switch inventory against the customer's live
    # DeviceMap over MQTT. These names are the ones the field devices
    # publish; translating them would stop the match.
    "DeviceMap.json": (
        ("Yataklı", "switch names published by the customer's DeviceMap"),
    ),
    "static/js/views/devices.js": (
        ("Yataklı_1", "example of a real DeviceMap switch name"),
    ),
    # A language names ITSELF in its own language, always: someone looking for
    # Turkish should not have to read English to find it.
    "static/js/components/language.js": (
        ("Türkçe", "endonym — a language is never translated in the picker"),
    ),
    # Proving that a message renders in Turkish means writing the Turkish out.
    "tests/test_i18n.py": (
        ('"Kullanıcı"', "expected Turkish rendering of role.user"),
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
    "tests/test_language.py": (
        ("__self__", "this file lists the very words it searches for"),
    ),
}


# Files that are exempt as a whole, with the reason they have to be.
WHOLE_FILE_EXEMPT = {
    # The word list this test searches for lives here.
    "tests/test_language.py",
    # The Turkish catalogue: being Turkish is its entire job.
    "panel/messages/tr.json",
}


def _allowed(name: str, line: str) -> bool:
    if name in WHOLE_FILE_EXEMPT:
        return True
    for fragment, _reason in ALLOWED.get(name, ()):
        if fragment in line:
            return True
    return False


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
                         "packaging/windows/CommissioningPanel.iss"):
            self.assertIn(required, scanned, required)
        # ...and documentation is genuinely left alone.
        for excluded in ("README.md", "LICENSE", "docs/MIMARI.md"):
            self.assertNotIn(excluded, scanned, excluded)


if __name__ == "__main__":
    unittest.main()
