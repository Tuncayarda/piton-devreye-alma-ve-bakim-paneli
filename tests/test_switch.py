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
from unittest import mock

from core import dogrulama, ip_atama, kimlik, okuma, switch_okuma, yerel_ag
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


class KorunanPortlar(PanelTesti):
    """Koşunun dokunmaması gereken portlar MAC tablolarından bulunur.

    Ne bilgisayarın yeri ne switch'ler arası bağlantı sorulur: elle
    girildiği sürece yanlış cevap iki kere zarar veriyordu — korunması
    gereken port korunmuyor, korunmaması gereken port koşudan düşüyordu.
    Sahada switch'lerin bir kısmı ayakta olmadığı için "hangisindesin"
    sorusunun cevabını kullanıcı da bilmiyor.
    """

    HESAP = ("admin", "123")

    def _env(self, switch_sayisi=1):
        harita = sahte.device_map([], switch_ip="127.0.0.1")
        for i in range(switch_sayisi - 1):
            harita["Switches"].append({
                "Name": f"Kapali_SW_{i + 2}", "IP": "127.0.0.2",
                "Type": "Switch", "IsActive": True, "Devices": [],
            })
        return self.kur_harita(harita)

    def _kimlik(self, _cihaz):
        return self.HESAP

    def _yerel_maclar(self):
        maclar = [a["mac"] for a in yerel_ag.arayuzler()]
        if not maclar:
            self.skipTest("bu makinede okunabilir ağ arayüzü yok")
        return maclar

    def test_yerel_mac_switch_tablosunda_bulunur(self):
        env = self._env()
        maclar = self._yerel_maclar()
        # Makinenin gerçek MAC'lerinden biri 17. portta duruyormuş gibi.
        tablo = {maclar[0]: 17, "aa:bb:cc:dd:ee:01": 3}
        with sahte.kyland(mac_tablosu=tablo) as s:
            self.switch_portu(s.port)
            k = ip_atama.korunan_portlar(env, self._kimlik)
        pc = k["bilgisayar"]
        self.assertEqual(pc["port"], 17)
        self.assertEqual(pc["kaynak"], "mac")
        self.assertEqual(pc["mac"], maclar[0])
        self.assertEqual(pc["switchId"], env.switchler()[0].id)
        self.assertIn({"switchId": pc["switchId"], "switchAd": pc["switchAd"],
                       "port": 17, "tur": "bilgisayar",
                       "sebep": "bilgisayar bu portta"}, k["portlar"])

    def test_ayakta_olmayan_switch_aramayi_bitirmez(self):
        """Bir switch kapalıysa diğerlerine bakılmaya devam edilir.

        Sahada switch 1 henüz kurulu olmayabiliyor; kullanıcıya hangisine
        bağlı olduğunu sormamanın bütün anlamı bu.
        """
        env = self._env(switch_sayisi=2)
        maclar = self._yerel_maclar()
        # Ulaşılabilen switch listenin İKİNCİSİ; ilki 127.0.0.2'de sessiz.
        env.switchler()[0].ip, env.switchler()[1].ip = "127.0.0.2", "127.0.0.1"
        with sahte.kyland(mac_tablosu={maclar[0]: 5}) as s:
            self.switch_portu(s.port)
            k = ip_atama.korunan_portlar(env, self._kimlik)
        self.assertEqual(k["bilgisayar"]["port"], 5)
        self.assertEqual(k["bilgisayar"]["switchId"], env.switchler()[1].id)

    def _iki_switch(self, tablolar, kendi_macler):
        """switch_okuma'yı IP başına sabit cevaplarla değiştirir.

        İki sahte switch ayrı TCP portlarında dinlerdi ama switch_api tek
        bir global `SWITCH_PORT` kullanıyor; ikisini birden gerçek HTTP
        ile konuşturmanın yolu yok. Buradaki ilgi zaten HTTP değil,
        `korunan_portlar`ın iki tabloyu nasıl yorumladığı.
        """
        env = self._env(switch_sayisi=2)
        a, b = env.switchler()
        a.ip, b.ip = "10.0.0.1", "10.0.0.2"
        eslesme = dict(zip((a.ip, b.ip), tablolar))
        macler = dict(zip((a.ip, b.ip), kendi_macler))
        yamalar = [
            mock.patch.object(ip_atama.switch_okuma, "mac_tablosu",
                              lambda ip, k=None, timeout=None: eslesme[ip]),
            mock.patch.object(ip_atama.switch_okuma, "oku",
                              lambda ip, k=None, timeout=None: {
                                  "mac": macler[ip]}),
        ]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)
        return env, a, b

    def test_uplink_portu_bilgisayarin_portu_sanilmaz(self):
        """Bilgisayarın MAC'i komşu switch'in tablosunda DA görünür.

        Komşu onu kendi uplink'inde öğreniyor. Listedeki sıraya bakmak
        yanlış switch'i seçerdi; ayırt eden, portta öğrenilmiş MAC sayısı
        — erişim portunda tek cihaz vardır, uplink'te switch'in
        arkasındaki her şey.
        """
        pc = self._yerel_maclar()[0]
        # a (liste başı): PC uplink portu 25'te, yanında bir sürü MAC.
        # b: PC doğrudan p7'de, o portta başka MAC yok.
        env, a, b = self._iki_switch(
            [{pc: 25, "aa:bb:cc:00:00:01": 25, "aa:bb:cc:00:00:02": 25},
             {pc: 7, "aa:bb:cc:00:00:09": 11}],
            ["00:11:22:33:44:01", "00:11:22:33:44:02"])

        k = ip_atama.korunan_portlar(env, self._kimlik)

        self.assertEqual(k["bilgisayar"]["switchId"], b.id)
        self.assertEqual(k["bilgisayar"]["port"], 7)
        # a'daki uplink de korunur — koşu oradan geçiyor — ama "bilgisayar
        # portu" değil, "bağlantı" olarak.
        tur = {(p["switchId"], p["port"]): p["tur"] for p in k["portlar"]}
        self.assertEqual(tur[(b.id, 7)], "bilgisayar")
        self.assertEqual(tur[(a.id, 25)], "baglanti")

    def test_switchler_arasi_baglanti_komsu_macinden_bulunur(self):
        """Komşunun KENDİ MAC'i bizim tablomuzda hangi porttaysa, uplink o.

        Bilgisayarın yolu üstünde olmayan switch-switch bağlantıları
        ancak böyle bulunuyor.
        """
        pc = self._yerel_maclar()[0]
        a_mac, b_mac = "00:11:22:33:44:01", "00:11:22:33:44:02"
        # PC doğrudan a'da (p3). a ile b birbirine 26 ↔ 27'den bağlı;
        # b'nin tablosunda PC hiç yok (öğrenmemiş).
        env, a, b = self._iki_switch(
            [{pc: 3, b_mac: 26}, {a_mac: 27}],
            [a_mac, b_mac])

        k = ip_atama.korunan_portlar(env, self._kimlik)

        self.assertEqual(k["bilgisayar"]["switchId"], a.id)
        self.assertEqual(k["bilgisayar"]["port"], 3)
        tur = {(p["switchId"], p["port"]): p["tur"] for p in k["portlar"]}
        self.assertEqual(tur[(a.id, 3)], "bilgisayar")
        self.assertEqual(tur[(a.id, 26)], "baglanti")
        self.assertEqual(tur[(b.id, 27)], "baglanti")

    def test_komsu_cevap_vermezse_baglanti_uydurulmaz(self):
        env = self._env(switch_sayisi=2)
        maclar = self._yerel_maclar()
        env.switchler()[1].ip = "127.0.0.2"     # ikincisi kapalı
        with sahte.kyland(mac_tablosu={maclar[0]: 3, "aa:bb:cc:dd:ee:77": 26},
                          mac="00:11:22:33:44:55") as s:
            self.switch_portu(s.port)
            k = ip_atama.korunan_portlar(env, self._kimlik)
        # Komşu kapalı, kendi MAC'ini veremiyor: p26 bir bağlantı OLABİLİR
        # ama bunu bilmiyoruz — tahmin edilmez.
        self.assertEqual([p["port"] for p in k["portlar"]], [3])
        self.assertEqual(k["portlar"][0]["tur"], "bilgisayar")

    def test_mac_tablosunda_yoksa_port_uydurulmaz(self):
        env = self._env()
        with sahte.kyland(mac_tablosu={"aa:bb:cc:dd:ee:01": 3}) as s:
            self.switch_portu(s.port)
            k = ip_atama.korunan_portlar(env, self._kimlik)
        self.assertIsNone(k["bilgisayar"]["port"])
        self.assertEqual(k["portlar"], [])
        self.assertTrue(k["bilgisayar"]["not"])

    def test_tablo_vermeyen_switch_hata_degil_bulunamadi(self):
        """MAC uçları olmayan switch ekranı kilitlememeli."""
        env = self._env()
        with sahte.kyland() as s:                 # mac_tablosu yok -> 404
            self.switch_portu(s.port)
            k = ip_atama.korunan_portlar(env, self._kimlik)
        self.assertIsNone(k["bilgisayar"]["port"])
        self.assertEqual(k["portlar"], [])

    def test_kimliksiz_switch_sebebi_soyler(self):
        env = self._env()
        with sahte.kyland(mac_tablosu={"aa:bb:cc:dd:ee:01": 3}) as s:
            self.switch_portu(s.port)
            k = ip_atama.korunan_portlar(env, lambda c: None)
        self.assertIsNone(k["bilgisayar"]["port"])
        self.assertIn("okunamadı", k["not"])
        self.assertEqual([d["durum"] for d in k["denenen"]],
                         ["kullanıcı adı/parola istiyor"])

    def test_mac_normalizasyonu_bicimden_bagimsiz(self):
        """Switch büyük harf ve tire ile verse de eşleşme tutmalı."""
        env = self._env()
        maclar = self._yerel_maclar()
        bicimsiz = maclar[0].replace(":", "-").upper()
        with sahte.kyland(mac_tablosu={bicimsiz: 9}) as s:
            self.switch_portu(s.port)
            k = ip_atama.korunan_portlar(env, self._kimlik)
        self.assertEqual(k["bilgisayar"]["port"], 9)


class YerelAg(unittest.TestCase):
    """Arayüz dökümü ayrıştırması — etikete değil, kalıba bakılır."""

    WINDOWS = (
        "Windows IP Yapilandirmasi\n"
        "\n"
        "Ethernet adapter Ethernet:\n"
        "   Fiziksel Adres. . . . . . . . . : 00-11-22-33-44-55\n"
        "   IPv4 Adresi . . . . . . . . . . : 10.1.1.50(Tercih Edilen)\n"
        "\n"
        "Kablosuz LAN adapter Wi-Fi:\n"
        "   Fiziksel Adres. . . . . . . . . : AA-BB-CC-DD-EE-FF\n"
        "   IPv4 Adresi . . . . . . . . . . : 192.168.1.5(Tercih Edilen)\n"
    )
    MACOS = (
        "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n"
        "\tinet 127.0.0.1 netmask 0xff000000\n"
        "en0: flags=8863<UP,BROADCAST> mtu 1500\n"
        "\tether 3c:22:fb:11:22:33\n"
        "\tinet 10.1.1.50 netmask 0xffff0000\n"
        "en5: flags=8863<UP,BROADCAST> mtu 1500\n"
        "\tether 3c:22:fb:44:55:66\n"
        "\tinet 10.1.1.5 netmask 0xffff0000\n"
    )

    def test_windows_turkce_etiketlerle_de_ayristirilir(self):
        bloklar = yerel_ag._bloklar(self.WINDOWS)
        maclar = [yerel_ag._blok_maci(b) for b in bloklar]
        self.assertIn("00:11:22:33:44:55", maclar)
        self.assertIn("aa:bb:cc:dd:ee:ff", maclar)

    def test_ip_eslesmesi_daha_uzun_adrese_takilmaz(self):
        """10.1.1.5 aranırken 10.1.1.50'nin arayüzü seçilmemeli."""
        bloklar = yerel_ag._bloklar(self.MACOS)
        arayuz = [{"mac": yerel_ag._blok_maci(b),
                   "ipler": yerel_ag._blok_ipleri(b)} for b in bloklar]
        eslesen = [a for a in arayuz if "10.1.1.5" in a["ipler"]]
        self.assertEqual(len(eslesen), 1)
        self.assertEqual(eslesen[0]["mac"], "3c:22:fb:44:55:66")

    def test_mac_normalle_bicimleri_tek_hale_getirir(self):
        for ham in ("5c-1-3b-8A-76-43", "5c01.3b8a.7643", "5C:01:3B:8A:76:43"):
            self.assertEqual(yerel_ag.normalle(ham), "5c:01:3b:8a:76:43")
        self.assertEqual(yerel_ag.normalle("yok"), "")
        self.assertEqual(yerel_ag.normalle(None), "")


if __name__ == "__main__":
    unittest.main()
