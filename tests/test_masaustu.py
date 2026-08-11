#!/usr/bin/env python3
"""Soketsiz masaüstü başlangıcı ve pywebview köprüsü regresyonları."""
from __future__ import annotations

import sys
import threading
import time
import types
import unittest
from unittest import mock

import app
from core import ayar
from masaustu import KOPRU_ISARETI, PanelKoprusu, YETENEK_YERI, html_yukle


class MasaustuHtmlTesti(unittest.TestCase):
    def test_kopru_isaretli_tek_parca_html_okunur(self):
        metin = html_yukle("A" * 43)
        self.assertIn(KOPRU_ISARETI, metin)
        self.assertNotIn(YETENEK_YERI, metin)
        self.assertIn("A" * 43, metin)

    def test_harici_script_isteyen_artefakt_reddedilir(self):
        from core import ayar
        kaynak = (ayar.STATIC_DIR / "masaustu.html").read_text(encoding="utf-8")
        bozuk = kaynak.replace(
            "</body>", '<script src="https://example.com/a.js"></script></body>')
        with mock.patch("pathlib.Path.read_text", return_value=bozuk):
            with self.assertRaisesRegex(RuntimeError, "geçersiz"):
                html_yukle("A" * 43)


class KopruTesti(unittest.TestCase):
    def test_get_sorgusu_ve_post_govdesi_servise_ayrilir(self):
        cagrilar = []

        def cagir(method, yol, query=None, body=None):
            cagrilar.append((method, yol, query, body))
            return {"ok": True, "status": 200, "body": {"tamam": True}}

        kopru = PanelKoprusu(cagir, yetenek="A" * 43)
        self.assertTrue(kopru.invoke("A" * 43, "GET", "/api/proje?set=2", {})["ok"])
        self.assertTrue(kopru.invoke(
            "A" * 43, "POST", "/api/tarama", {"set": 2})["ok"])
        self.assertEqual(cagrilar, [
            ("GET", "/api/proje", {"set": ["2"]}, {}),
            ("POST", "/api/tarama", {}, {"set": 2}),
        ])

    def test_keyfi_url_yontem_ve_buyuk_govde_reddedilir(self):
        cagir = mock.Mock()
        kopru = PanelKoprusu(cagir, yetenek="A" * 43)
        for method, yol, body, kod in (
                ("GET", "https://example.com/api/surum", {}, 400),
                ("DELETE", "/api/isler", {}, 405),
                ("POST", "/api/tarama", {"x": "a" * (ayar.GOVDE_SINIRI + 1)}, 400)):
            zarf = kopru.invoke("A" * 43, method, yol, body)
            self.assertFalse(zarf["ok"])
            self.assertEqual(zarf["status"], kod)
        cagir.assert_not_called()

    def test_yalniz_invoke_public_callable_olarak_acilir(self):
        kopru = PanelKoprusu(lambda *a, **k: {}, yetenek="A" * 43)
        acik = sorted(ad for ad in dir(kopru)
                      if not ad.startswith("_") and callable(getattr(kopru, ad)))
        self.assertEqual(acik, ["invoke"])

    def test_kapanis_yeni_cagriyi_reddeder(self):
        kopru = PanelKoprusu(lambda *a, **k: {
            "ok": True, "status": 200, "body": {}}, yetenek="A" * 43)
        self.assertTrue(kopru._kapat())
        self.assertEqual(
            kopru.invoke("A" * 43, "GET", "/api/surum", {})["status"], 503)

    def test_kapanis_surmekte_olan_cagri_bitmeden_durumu_temizlemez(self):
        basladi = threading.Event()
        bitir = threading.Event()

        def cagir(*args, **kwargs):
            basladi.set()
            bitir.wait(2)
            return {"ok": True, "status": 200, "body": {}}

        kopru = PanelKoprusu(cagir, yetenek="A" * 43)
        istek = threading.Thread(
            target=kopru.invoke,
            args=("A" * 43, "GET", "/api/surum", {}),
        )
        istek.start()
        self.assertTrue(basladi.wait(1))

        kapandi = threading.Event()

        def kapat():
            kopru._kapat()
            kapandi.set()

        kapanis = threading.Thread(target=kapat)
        kapanis.start()
        time.sleep(0.02)
        self.assertFalse(kapandi.is_set())
        bitir.set()
        kapanis.join(1)
        istek.join(1)
        self.assertTrue(kapandi.is_set())

    def test_yanlis_yetenek_anahtari_servise_ulasmaz(self):
        cagir = mock.Mock()
        kopru = PanelKoprusu(cagir, yetenek="A" * 43)
        zarf = kopru.invoke("B" * 43, "GET", "/api/surum", {})
        self.assertEqual(zarf["status"], 403)
        cagir.assert_not_called()

    def test_eksik_ve_fazla_arguman_traceback_yerine_zarf_dondurur(self):
        cagir = mock.Mock()
        kopru = PanelKoprusu(cagir, yetenek="A" * 43)
        self.assertEqual(kopru.invoke()["status"], 403)
        self.assertEqual(kopru.invoke("A" * 43)["status"], 400)
        self.assertEqual(
            kopru.invoke("A" * 43, "GET", "/api/surum", {}, "fazla")[
                "status"],
            400,
        )
        cagir.assert_not_called()


class MasaustuBaslangicTesti(unittest.TestCase):
    def test_port_sifir_da_tarayici_kipi_olmadan_reddedilir(self):
        with (mock.patch.object(sys, "argv", ["app.py", "--port", "0"]),
              mock.patch("panel_api.admin_parolasi_ayarla"),
              mock.patch("app.yaz") as yaz):
            self.assertEqual(app.main(), 2)
        yaz.assert_called_with(
            "[HATA] --port yalnız --tarayici ile kullanılabilir.")

    def test_varsayilan_kip_http_sunucusu_acmaz(self):
        sahte = types.ModuleType("webview")
        sahte.settings = {}
        sahte.pencere = None
        sahte.baslangic = None
        sahte.acilan_fonksiyonlar = []

        def create_window(*args, **kwargs):
            sahte.pencere = (args, kwargs)
            return types.SimpleNamespace(
                expose=lambda *f: sahte.acilan_fonksiyonlar.extend(f))

        def start(**kwargs):
            sahte.baslangic = kwargs

        sahte.create_window = create_window
        sahte.start = start

        html = f"<!doctype html><head>{KOPRU_ISARETI}</head>"
        with (mock.patch.dict(sys.modules, {"webview": sahte}),
              mock.patch.object(sys, "argv", ["app.py"]),
              mock.patch("app.platform.system", return_value="Windows"),
              mock.patch("app.macos_kimlik"),
              mock.patch("masaustu.html_yukle", return_value=html),
              mock.patch("panel_api.baslat"),
              mock.patch("panel_api.temizle"),
              mock.patch("panel_api.sunucu") as sunucu):
            self.assertEqual(app.main(), 0)

        sunucu.assert_not_called()
        self.assertIsNotNone(sahte.pencere)
        _, secenek = sahte.pencere
        self.assertNotIn("url", secenek)
        self.assertNotIn("js_api", secenek)
        self.assertEqual(secenek["html"], html)
        self.assertEqual(
            [f.__name__ for f in sahte.acilan_fonksiyonlar], ["invoke"])
        self.assertIsInstance(
            sahte.acilan_fonksiyonlar[0].__self__, PanelKoprusu)
        self.assertEqual(sahte.baslangic,
                         {"gui": "edgechromium", "http_server": False})
        self.assertFalse(sahte.settings["ALLOW_FILE_URLS"])
        self.assertFalse(sahte.settings["ALLOW_DOWNLOADS"])


if __name__ == "__main__":
    unittest.main()
