#!/usr/bin/env python3
"""HTTP adaptörü ile taşımasız panel servisinin sözleşme testleri."""
from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import panel_api
from core import konfig
from core.hata import CihazHatasi, KimlikHatasi

from . import sahte
from .ortak import ServisTesti


def _harita():
    return sahte.device_map([{
        "Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
        "Type": "Announcement", "SubType": "Intercom", "Port": "11",
        "Status": {"NoError": True},
    }], switch_ip="127.0.0.1")


class PanelServisSozlesmesi(ServisTesti):

    def setUp(self):
        super().setUp()
        self.kur_harita(_harita())

    def test_get_servis_ve_http_ayni_sonucu_verir(self):
        taban = self.servis_ac()
        for yol in ("/api/surum", "/api/proje?set=1",
                    "/api/durum?set=1", "/api/cihaz?set=1&id=yok",
                    "/api/bilinmeyen"):
            with self.subTest(yol=yol):
                kod, govde = self.cagir(taban, yol)
                u = urlparse(yol)
                dogrudan = panel_api.api_cagir(
                    "GET", u.path, query=parse_qs(u.query))
                self.assertEqual(dogrudan.kod, kod)
                self.assertEqual(dogrudan.govde, govde)

    def test_post_servis_ve_http_ayni_sonucu_verir(self):
        taban = self.servis_ac()
        for yol, govde in (("/api/admin/giris", {"parola": ""}),
                           ("/api/is/iptal", {"id": "yok"}),
                           ("/api/bilinmeyen", {})):
            with self.subTest(yol=yol):
                kod, http_govde = self.cagir(taban, yol, govde)
                dogrudan = panel_api.api_cagir("POST", yol, body=govde)
                self.assertEqual(dogrudan.kod, kod)
                self.assertEqual(dogrudan.govde, http_govde)

    def test_bridge_zarfi_yalniz_json_turleri_dondurur(self):
        basarili = panel_api.api_zarfi("GET", "/api/surum")
        self.assertTrue(basarili["ok"])
        self.assertEqual(basarili["status"], 200)
        self.assertIn("surum", basarili["body"])
        json.dumps(basarili, ensure_ascii=False)

        hata = panel_api.api_zarfi("GET", "/api/bilinmeyen")
        self.assertFalse(hata["ok"])
        self.assertEqual(hata["status"], 404)
        self.assertEqual(hata["body"]["hata"], "bilinmeyen yol")

    def test_baslat_yalniz_bir_kez_varsayilan_yukler(self):
        with patch.object(panel_api, "_BASLATILDI", False), \
                patch.object(panel_api, "_BASLATMA_SONUCU", 0), \
                patch.object(konfig, "varsayilanlari_yukle",
                             return_value=3) as yukle:
            self.assertEqual(panel_api.baslat(), 3)
            self.assertEqual(panel_api.baslat(), 3)
            yukle.assert_called_once_with()

    def test_servis_hata_eslemeleri(self):
        durumlar = (
            (LookupError("yok"), 404, False),
            (ValueError("geçersiz"), 400, False),
            (KimlikHatasi("kimlik gerekli"), 401, True),
            (CihazHatasi("cihaz okunamadı"), 502, False),
        )
        for exc, kod, kimlik in durumlar:
            with self.subTest(exc=type(exc).__name__), patch.object(
                    panel_api.SERVIS, "_api_get", side_effect=exc):
                yanit = panel_api.api_cagir("GET", "/api/surum")
                self.assertEqual(yanit.kod, kod)
                self.assertEqual(bool(yanit.govde.get("kimlik")), kimlik)

        stderr = StringIO()
        with patch.object(panel_api.SERVIS, "_api_get",
                          side_effect=RuntimeError("iç ayrıntı")), \
                redirect_stderr(stderr):
            yanit = panel_api.api_cagir("GET", "/api/surum")
        self.assertEqual(yanit.kod, 500)
        self.assertNotIn(
            "iç ayrıntı", json.dumps(yanit.govde, ensure_ascii=False))
        self.assertIn("RuntimeError", stderr.getvalue())


if __name__ == "__main__":
    import unittest
    unittest.main()
