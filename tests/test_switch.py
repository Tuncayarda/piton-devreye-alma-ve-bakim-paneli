#!/usr/bin/env python3
"""Switch erişimi — Switch Yönetim Paneli ile aynı davranış.

Kapsanan gereksinimler:
  1. Switch Yönetim Paneli'nde çalışan doğru hesap bu panelde de doğrulanır.
  2. Yanlış switch parolası başarı kabul edilmez.
  3. HTTP 200 dönen login HTML'i switch verisi kabul edilmez.
 11. Aynı adlı, farklı IP'li iki switch birbirine karışmaz.
"""
from __future__ import annotations

import unittest

from core import dogrulama, kimlik, okuma, switch_okuma
from core.hata import DogrulamaHatasi, KimlikHatasi

from .ortak import PanelTesti
from . import sahte


class SwitchErisimi(PanelTesti):

    def test_1_dogru_hesap_iki_panelde_de_calisir(self):
        """Aynı hesap hem kardeş backend'de hem burada doğrulanmalı.

        İki uygulama tek koddan geçiyor: switch_api.sw_get. Test bunu
        iddia etmekle kalmıyor, ikisini de aynı sahte switch'e sorup
        sonuçların birebir aynı olduğunu gösteriyor.
        """
        with sahte.kyland(kullanici="admin", parola="123") as sw:
            self.switch_portu(sw.port)
            api = switch_okuma.modul()

            # Switch Yönetim Paneli'nin kendi yolu
            oradaki = api.is_switch("127.0.0.1", timeout=5,
                                    kimlik=("admin", "123"))
            self.assertIsNotNone(oradaki)
            self.assertFalse(oradaki["kilit"])

            # Bu panelin yolu
            buradaki = switch_okuma.oku("127.0.0.1", ("admin", "123"))

            self.assertEqual(oradaki["model"], buradaki["model"])
            self.assertEqual(oradaki["version"], buradaki["surum"])
            self.assertEqual(oradaki["mac"], buradaki["mac"])
            self.assertEqual(buradaki["surum"], "F6014")

    def test_calisma_suresi_operatetime_alanindan_hesaplanir(self):
        """KYLAND tek bir uptime alanı vermiyor; süre parçalı geliyor."""
        hesapla = switch_okuma.calisma_saniyesi
        self.assertEqual(
            hesapla({"operateTime": {"day": "1", "hour": "2",
                                     "minute": "3", "second": "4"}}),
            86400 + 2 * 3600 + 3 * 60 + 4)
        # Tek alanlı cihaz varsa o kullanılır
        self.assertEqual(hesapla({"upTime": 90}), 90)
        # Alan yoksa uydurma değer üretilmez
        self.assertIsNone(hesapla({"deviceName": "SWITCH"}))
        self.assertIsNone(hesapla({"operateTime": "07:30:39"}))

        with sahte.kyland(kullanici="admin", parola="123") as sw:
            self.switch_portu(sw.port)
            veri = switch_okuma.oku("127.0.0.1", ("admin", "123"))
            self.assertEqual(veri["calisma"], 86400 + 2 * 3600 + 3 * 60 + 4)
            sonuc = okuma.cihaz_oku(
                self.kur_harita(sahte.device_map([], switch_ip="127.0.0.1")
                                ).switchler()[0], kimlik=("admin", "123"))
            self.assertEqual(sonuc.alanlar["calisma"], "26:03:04")

    def test_2_yanlis_parola_basari_sayilmaz(self):
        with sahte.kyland(parola="123") as sw:
            self.switch_portu(sw.port)
            with self.assertRaises(KimlikHatasi):
                switch_okuma.oku("127.0.0.1", ("admin", "yanlis"))
            # Kimliksiz de aynı sınıfa düşer
            with self.assertRaises(KimlikHatasi):
                switch_okuma.oku("127.0.0.1", None)

    def test_3_login_html_switch_verisi_sayilmaz(self):
        """Doğru parolayla bile 200 + HTML gelirse başarı yok."""
        with sahte.kyland(giris_sayfasi=True) as sw:
            self.switch_portu(sw.port)
            with self.assertRaises(KimlikHatasi) as tutulan:
                switch_okuma.oku("127.0.0.1", ("admin", "123"))
            self.assertIn("JSON", str(tutulan.exception))

    def test_3b_beklenmeyen_json_da_kabul_edilmez(self):
        """200 + geçerli JSON ama switch künyesi değilse doğrulanmaz."""
        with sahte.bos_json_switch() as sw:
            self.switch_portu(sw.port)
            with self.assertRaises(DogrulamaHatasi):
                switch_okuma.oku("127.0.0.1", ("admin", "123"))

    def test_11_ayni_adli_farkli_ipli_switchler_karismaz(self):
        """İki switch aynı adı taşısa bile kimlikleri ayrı tutulur."""
        harita = sahte.device_map([], switch_ip="127.0.0.1",
                                  switch_ad="Yatakli_1")
        harita["Switches"].append({
            "Name": "Yatakli_1",              # BİLEREK aynı ad
            "IP": "127.0.0.2", "IsActive": True, "Manufacturer": "KYLAND",
            "TrainSet": 1, "Status": {"NoError": True}, "Devices": [],
        })
        env = self.kur_harita(harita)

        birinci, ikinci = env.switchler()
        self.assertEqual(birinci.ad, ikinci.ad)
        self.assertNotEqual(birinci.id, ikinci.id)
        self.assertNotEqual(birinci.ip, ikinci.ip)
        self.assertNotEqual(birinci.anahtar, ikinci.anahtar)

        kimlik.ver(birinci.id, birinci.ip, "admin", "birinci-parola")
        self.assertEqual(kimlik.al(birinci.id, birinci.ip),
                         ("admin", "birinci-parola"))
        # İkincisinin kendi kimliği yok ve birincisininkini DEVRALMAZ
        self.assertIsNone(kimlik.al(ikinci.id, ikinci.ip))

        # Görünümde de ayrı satırlar
        gor_id = {c.id for c in env.cihazlar}
        self.assertEqual(len(gor_id), len(env.cihazlar))

    def test_11b_grup_kimligi_ancak_acikca_istenirse_yayilir(self):
        harita = sahte.device_map([], switch_ip="127.0.0.1", switch_ad="A")
        harita["Switches"].append({
            "Name": "B", "IP": "127.0.0.2", "IsActive": True,
            "TrainSet": 1, "Status": {}, "Devices": [],
        })
        env = self.kur_harita(harita)
        a, b = env.switchler()

        kimlik.ver(a.id, a.ip, "admin", "p1", grup="switch",
                   gruba_uygula=False)
        self.assertIsNone(kimlik.al(b.id, b.ip, grup="switch"))

        kimlik.ver(a.id, a.ip, "admin", "p1", grup="switch",
                   gruba_uygula=True)
        self.assertEqual(kimlik.al(b.id, b.ip, grup="switch"),
                         ("admin", "p1"))

    def test_okuma_katmani_switch_sonucunu_yesile_cevirir(self):
        harita = sahte.device_map([], switch_ip="127.0.0.1")
        env = self.kur_harita(harita)
        sw = env.switchler()[0]
        with sahte.kyland() as s:
            self.switch_portu(s.port)
            sonuc = okuma.cihaz_oku(sw, kimlik=("admin", "123"))
            self.assertEqual(sonuc.durum, dogrulama.YESIL)
            self.assertEqual(sonuc.alanlar["surum"], "F6014")

            yanlis = okuma.cihaz_oku(sw, kimlik=("admin", "yok"))
            self.assertEqual(yanlis.durum, dogrulama.TURUNCU)
            self.assertEqual(yanlis.dogrulama, dogrulama.KIMLIK_BEKLIYOR)


if __name__ == "__main__":
    unittest.main()
