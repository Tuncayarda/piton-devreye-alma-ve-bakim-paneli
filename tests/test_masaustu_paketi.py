#!/usr/bin/env python3
"""HTTP'siz tek HTML masaüstü artefaktının üretim denetimleri."""
from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import masaustu_paketi


KOK = Path(__file__).resolve().parent.parent


class MasaustuPaketi(unittest.TestCase):

    def _html(self):
        return masaustu_paketi.CIKTI.read_text(encoding="utf-8")

    def _reddedilir(self, html, desen=None):
        baglam = (self.assertRaisesRegex(masaustu_paketi.PaketHatasi, desen)
                  if desen else self.assertRaises(masaustu_paketi.PaketHatasi))
        with baglam:
            masaustu_paketi.html_dogrula(html)

    def test_artefakt_tek_parca_ve_kisitli(self):
        self.assertTrue(masaustu_paketi.CIKTI.is_file(), "static/masaustu.html yok")
        html = self._html()
        masaustu_paketi.html_dogrula(html)
        self.assertIn('<meta name="dap-transport" content="bridge">', html)
        self.assertIn(
            '<meta name="dap-capability" content="__DAP_CAPABILITY__">', html)
        self.assertNotIn('<script type="module"', html)
        bootstrap = masaustu_paketi.BRIDGE_BOOTSTRAP
        self.assertEqual(html.count(bootstrap), 1)
        for olay in ('"dragenter"', '"dragover"', '"drop"'):
            self.assertIn(olay, bootstrap)
        bootstrap_sonu = html.index(bootstrap) + len(bootstrap)
        self.assertGreater(html.index("(() => {", bootstrap_sonu),
                           bootstrap_sonu)
        self.assertIn("connect-src 'none'", html)
        self.assertIn("'unsafe-eval'", html)
        for yerel in (
            'href="/css/',
            'src="/js/',
            'src="/piton-',
            'href="/piton-',
        ):
            self.assertNotIn(yerel, html)

    def test_deno_yoksa_anlasilir_hata_verir(self):
        with mock.patch.object(masaustu_paketi.shutil, "which", return_value=None):
            with self.assertRaisesRegex(masaustu_paketi.PaketHatasi,
                                        r"Deno 2\.9\.4 bulunamadı"):
                masaustu_paketi.deno_bul()

    def test_deno_surumu_tam_eslesmelidir(self):
        def sonuc(surum):
            return subprocess.CompletedProcess(
                ["/sahte/deno", "--version"], 0,
                f"deno {surum} (stable, release)\n", "")

        with mock.patch.object(masaustu_paketi.shutil, "which",
                               return_value="/sahte/deno"):
            with mock.patch.object(masaustu_paketi, "_komut",
                                   return_value=sonuc("2.9.4")):
                self.assertEqual(masaustu_paketi.deno_bul(), "/sahte/deno")
            for surum in ("2.9.3", "2.9.5", "3.0.0"):
                with self.subTest(surum=surum), \
                        mock.patch.object(masaustu_paketi, "_komut",
                                          return_value=sonuc(surum)):
                    with self.assertRaisesRegex(
                        masaustu_paketi.PaketHatasi, r"2\.9\.4 gerekli"):
                        masaustu_paketi.deno_bul()

    def test_svg_crlf_ve_lf_checkout_ayni_artefakti_uretir(self):
        icerik = '<svg xmlns="http://www.w3.org/2000/svg">\n<path/>\n</svg>\n'
        with tempfile.TemporaryDirectory() as dizin:
            lf = Path(dizin) / "lf.svg"
            crlf = Path(dizin) / "crlf.svg"
            lf.write_bytes(icerik.encode("utf-8"))
            crlf.write_bytes(icerik.replace("\n", "\r\n").encode("utf-8"))
            self.assertEqual(
                masaustu_paketi._veri_uri(lf, "image/svg+xml"),
                masaustu_paketi._veri_uri(crlf, "image/svg+xml"),
            )

    def test_check_crlf_artefakti_bayt_duzeyinde_reddeder(self):
        with tempfile.TemporaryDirectory() as dizin:
            cikti = Path(dizin) / "masaustu.html"
            cikti.write_bytes(b"satir\r\n")
            hata = StringIO()
            with (mock.patch.object(masaustu_paketi, "CIKTI", cikti),
                  mock.patch.object(masaustu_paketi, "KOK", Path(dizin)),
                  mock.patch.object(masaustu_paketi, "artefakt_uret",
                                    return_value="satir\n"),
                  redirect_stderr(hata)):
                self.assertEqual(masaustu_paketi.main(["--check"]), 1)
            self.assertIn("güncel değil", hata.getvalue())

    def test_csp_direktif_ve_token_kumesi_tamdir(self):
        html = self._html()
        bozmalar = (
            ("connect-src 'none'", "connect-src 'none' https:"),
            ("connect-src 'none'", "connect-src 'none' 'none'"),
            ("connect-src 'none'", "connect-src 'none'; connect-src 'none'"),
            ("font-src 'none'", "worker-src 'none'; font-src 'none'"),
            (" 'unsafe-eval'", ""),
        )
        for eski, yeni in bozmalar:
            with self.subTest(yeni=yeni):
                self._reddedilir(html.replace(eski, yeni, 1), r"CSP")

    def test_capability_placeholder_ve_token_sozlesmesi(self):
        html = self._html()
        tokenli = html.replace(masaustu_paketi.CAPABILITY_PLACEHOLDER,
                               "A" * 42 + "_", 1)
        masaustu_paketi.html_dogrula(tokenli)

        for gecersiz in ("A" * 42, "A" * 42 + "="):
            with self.subTest(deger=gecersiz[-3:]):
                self._reddedilir(
                    html.replace(masaustu_paketi.CAPABILITY_PLACEHOLDER,
                                 gecersiz, 1),
                    r"dap-capability",
                )
        self._reddedilir(
            html.replace(
                '<meta name="dap-capability" content="__DAP_CAPABILITY__">\n',
                "", 1),
            r"dap-capability",
        )
        self._reddedilir(
            html.replace(
                '<meta name="dap-capability" content="__DAP_CAPABILITY__">',
                '<meta name="dap-capability" content="__DAP_CAPABILITY__">\n'
                '<meta name="dap-capability" content="__DAP_CAPABILITY__">',
                1),
            r"dap-capability",
        )

    def test_yukleme_yuzeyi_dar_tutulur(self):
        html = self._html()
        ekler = (
            '<meta http-equiv="refresh" content="0; url=https://example.com">',
            '<img srcset="https://example.com/a.png 1x">',
            '<a ping="https://example.com/ping">x</a>',
            '<object data="https://example.com/veri"></object>',
            '<img src="data:text/plain;base64,QQ==">',
        )
        for ek in ekler:
            with self.subTest(ek=ek.split()[0]):
                self._reddedilir(html.replace("<body>", "<body>\n" + ek, 1))

        bozuk_favicon = re.sub(
            r'(<link rel="icon" type="image/png" href=")data:[^"]+',
            r'\1data:image/png;base64,QQ==',
            html,
            count=1,
        )
        self._reddedilir(bozuk_favicon, r"favicon")

    def test_raw_text_kapanis_sinirlari_reddedilir(self):
        for kapanis in ("</script x>", "</script/>"):
            with self.subTest(kapanis=kapanis), self.assertRaisesRegex(
                    masaustu_paketi.PaketHatasi, r"JavaScript paketi"):
                masaustu_paketi.html_uret(f'console.log("{kapanis}");')
        self.assertTrue(
            masaustu_paketi._ham_metin_kapanisi_var("a</style x>b", "style"))
        self.assertTrue(
            masaustu_paketi._ham_metin_kapanisi_var("a</style/>b", "style"))
        self.assertFalse(
            masaustu_paketi._ham_metin_kapanisi_var("a</scriptx>b", "script"))

    def test_artefakt_guncel_ve_uretim_deterministik(self):
        if not shutil.which("deno"):
            self.skipTest("Deno kurulu değil; üretim karşılaştırması atlandı")
        birinci = masaustu_paketi.artefakt_uret()
        ikinci = masaustu_paketi.artefakt_uret()
        self.assertEqual(birinci, ikinci)
        self.assertEqual(
            masaustu_paketi.CIKTI.read_bytes(),
            birinci.encode("utf-8"),
            "static/masaustu.html güncel değil",
        )

        sonuc = subprocess.run(
            [sys.executable, str(KOK / "tools" / "masaustu_paketi.py"), "--check"],
            cwd=KOK,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(sonuc.returncode, 0, sonuc.stderr or sonuc.stdout)
        self.assertIn("güncel ve doğrulandı", sonuc.stdout)


if __name__ == "__main__":
    unittest.main()
