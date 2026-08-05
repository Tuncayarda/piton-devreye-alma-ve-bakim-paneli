#!/usr/bin/env python3
"""Arayüz dosyalarının denetimi.

Kapsanan gereksinim:
 19. Frontend modülleri syntax/lint kontrolünden geçer.

Ayrıca arayüzün kural ihlallerini kaynakta yakalar: cihazdan gelen veri
innerHTML ile basılmamalı, parola tarayıcı deposuna yazılmamalıdır. Bu
denetimler bir çalışma zamanı testinden ucuz ve kaçırması zordur.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest

from core import ayar

JS_DIZIN = ayar.STATIC_DIR / "js"
CSS_DIZIN = ayar.STATIC_DIR / "css"


def _js_dosyalari():
    return sorted(JS_DIZIN.rglob("*.js"))


def _kodu(yol) -> str:
    """Yorum satırlarını atıp yalnız kodu döndürür.

    Yasak API denetimleri yorumlarda takılmamalı: dosyaların başındaki
    "innerHTML kullanılmaz" açıklaması ihlal değil, kuralın kendisidir.
    """
    metin = yol.read_text(encoding="utf-8")
    metin = re.sub(r"/\*.*?\*/", "", metin, flags=re.S)
    return "\n".join(s for s in metin.splitlines()
                     if not s.lstrip().startswith("//"))


class Arayuz(unittest.TestCase):

    def test_19_js_modulleri_lintten_gecer(self):
        """deno varsa gerçek lint+tip denetimi; yoksa test atlanır."""
        deno = shutil.which("deno")
        if not deno:
            self.skipTest("deno kurulu değil — JS lint denetimi atlandı "
                          "(kurulum: brew install deno)")
        lint = subprocess.run([deno, "lint", str(JS_DIZIN)],
                              capture_output=True, text=True, timeout=180)
        self.assertEqual(lint.returncode, 0,
                         f"deno lint hataları:\n{lint.stderr}")
        kontrol = subprocess.run(
            [deno, "check", "--no-lock", str(JS_DIZIN / "app.js")],
            capture_output=True, text=True, timeout=180)
        self.assertEqual(kontrol.returncode, 0,
                         f"deno check hataları:\n{kontrol.stderr}")

    def test_19b_modul_yapisi_tutarli(self):
        """Her modül ES module; içe aktarımlar var olan dosyaları göstermeli."""
        dosyalar = _js_dosyalari()
        self.assertGreaterEqual(len(dosyalar), 15)
        for yol in dosyalar:
            metin = yol.read_text(encoding="utf-8")
            for satir in metin.splitlines():
                s = satir.strip()
                if not s.startswith("import ") or " from " not in s:
                    continue
                hedef = s.split(" from ")[1].strip().strip("';\"")
                if not hedef.startswith("."):
                    continue
                cozulen = (yol.parent / hedef).resolve()
                self.assertTrue(cozulen.is_file(),
                                f"{yol.name} -> {hedef} bulunamadı")

    def test_cihaz_verisi_innerhtml_ile_basilmaz(self):
        """innerHTML / outerHTML / document.write hiçbir modülde olmamalı."""
        self._yasakli_cagri(("innerHTML", "outerHTML", "insertAdjacentHTML",
                             "document.write", "eval("))

    def test_parola_tarayici_deposuna_yazilmaz(self):
        self._yasakli_cagri(("localStorage", "sessionStorage", "indexedDB",
                             "document.cookie"))

    def _yasakli_cagri(self, yasaklar):
        bulunan = []
        for yol in _js_dosyalari():
            kod = _kodu(yol)
            for yasak in yasaklar:
                if yasak in kod:
                    bulunan.append(f"{yol.name}: {yasak}")
        self.assertEqual(bulunan, [], f"yasaklı çağrı bulundu: {bulunan}")

    def test_parola_global_durumda_tutulmaz(self):
        """durum.js bilinen anahtarlar dışına yazmaz; parola anahtarı yok."""
        metin = _kodu(JS_DIZIN / "core" / "durum.js")
        self.assertIn("ANAHTARLAR", metin)
        for yasak in ("parola", "password", "kimlikBilgisi"):
            self.assertNotIn(f"'{yasak}'", metin)

    def test_setinterval_kullanilmaz(self):
        """Yenileme turları setTimeout zinciriyle kurulur (istek birikmesin)."""
        self._yasakli_cagri(("setInterval",))

    def test_index_html_gerekli_ogeleri_icerir(self):
        html = (ayar.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for kimlik_ in ("rol-ekrani", "uygulama", "kilit-btn", "kuyruk-btn",
                        "guncelle-btn", "duraklat-btn", "kilit-panel",
                        "kuyruk-panel", "bildirim", "set-secici"):
            self.assertIn(f'id="{kimlik_}"', html, kimlik_)
        # Erişilebilirlik: ikon düğmelerinin metinsiz kalmaması
        self.assertIn('aria-label="İşlem kuyruğu"', html)
        self.assertIn('lang="tr"', html)
        self.assertIn('<script type="module"', html)

    def test_css_dosyalari_var_ve_bos_degil(self):
        for ad in ("temel.css", "bilesen.css", "ekran.css"):
            yol = CSS_DIZIN / ad
            self.assertTrue(yol.is_file(), ad)
            self.assertGreater(len(yol.read_text(encoding="utf-8")), 500, ad)

    def test_duyarli_yerlesim_kirilma_noktalari_var(self):
        """1440 temel tasarım dar ekranda taşmamalı: medya sorguları şart."""
        temel = (CSS_DIZIN / "temel.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 1080px)", temel)
        self.assertIn("@media (max-width: 720px)", temel)
        bilesen = (CSS_DIZIN / "bilesen.css").read_text(encoding="utf-8")
        self.assertIn("overflow-x: auto", bilesen)   # geniş tablolar kayar

    def test_python_dosyalari_derlenir(self):
        """Bütün Python kaynakları söz dizimi denetiminden geçer."""
        import py_compile
        kaynaklar = ([ayar.KOK / "app.py", ayar.KOK / "panel_api.py"]
                     + sorted((ayar.KOK / "core").glob("*.py"))
                     + sorted((ayar.KOK / "tests").glob("*.py")))
        for yol in kaynaklar:
            with self.subTest(dosya=yol.name):
                py_compile.compile(str(yol), doraise=True, cfile=None)


if __name__ == "__main__":
    unittest.main()
