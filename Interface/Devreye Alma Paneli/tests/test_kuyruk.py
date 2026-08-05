#!/usr/bin/env python3
"""İş kuyruğu davranışı.

Kapsanan gereksinimler:
 13. Güncelle'ye çift tıklama iki iş oluşturmaz.
 14. Aynı setin aktif taraması varken ikinci tarama başlamaz.
 18. Tarama iptali çalışan işi kontrollü biçimde sonlandırır.
"""
from __future__ import annotations

import threading
import time
import unittest

from core import dogrulama, isler

from .ortak import ServisTesti
from . import sahte


def _harita(cihaz_sayisi=6):
    cihazlar = [{
        "Name": f"Intercom_{i}", "IP": "127.0.0.1", "IsActive": True,
        "Type": "Announcement", "SubType": "Intercom", "Port": str(10 + i),
        "PBXExtension": str(2000 + i), "Status": {"NoError": True},
    } for i in range(1, cihaz_sayisi + 1)]
    return sahte.device_map(cihazlar, switch_ip="127.0.0.1")


class Kuyruk(ServisTesti):

    def test_13_cift_tiklama_iki_is_olusturmaz(self):
        self.kur_harita(_harita())
        with sahte.kyland() as sw, sahte.anons() as an:
            self.switch_portu(sw.port)
            from core import ayar
            ayar.ANONS_PORT = an.port
            taban = self.servis_ac()

            yanitlar = []
            engel = threading.Barrier(2)

            def tikla():
                engel.wait()
                yanitlar.append(self.cagir(taban, "/api/tarama", {"set": 1}))

            t1 = threading.Thread(target=tikla)
            t2 = threading.Thread(target=tikla)
            t1.start(); t2.start(); t1.join(10); t2.join(10)

            self.assertEqual(len(yanitlar), 2)
            idler = {y[1]["id"] for y in yanitlar}
            self.assertEqual(len(idler), 1, "iki ayrı iş oluşturulmamalı")
            yeniler = [y[1]["yeni"] for y in yanitlar]
            self.assertCountEqual(yeniler, [True, False])

            kod, liste = self.cagir(taban, "/api/isler")
            taramalar = [j for j in liste["isler"] if j["tur"] == "tarama"]
            self.assertEqual(len(taramalar), 1)

            self.isi_bekle(isler.YONETICI.bul(idler.pop()))

    def test_14_aktif_tarama_varken_ikincisi_baslamaz(self):
        self.kur_harita(_harita())
        with sahte.kyland() as sw, sahte.anons() as an:
            self.switch_portu(sw.port)
            from core import ayar
            ayar.ANONS_PORT = an.port
            taban = self.servis_ac()

            kod, ilk = self.cagir(taban, "/api/tarama", {"set": 1})
            self.assertEqual(kod, 200)
            self.assertTrue(ilk["yeni"])

            kod, ikinci = self.cagir(taban, "/api/tarama", {"set": 1})
            self.assertEqual(kod, 202, "yeni iş açılmamalı, mevcut iş dönmeli")
            self.assertFalse(ikinci["yeni"])
            self.assertEqual(ikinci["id"], ilk["id"])

            self.isi_bekle(isler.YONETICI.bul(ilk["id"]))

            # Bittikten SONRA yeni tarama açılabilmeli
            kod, ucuncu = self.cagir(taban, "/api/tarama", {"set": 1})
            self.assertEqual(kod, 200)
            self.assertNotEqual(ucuncu["id"], ilk["id"])
            self.isi_bekle(isler.YONETICI.bul(ucuncu["id"]))

    def test_14b_farkli_setler_ayri_islerdir(self):
        self.kur_harita(_harita(2))
        with sahte.kyland() as sw, sahte.anons() as an:
            self.switch_portu(sw.port)
            from core import ayar
            ayar.ANONS_PORT = an.port
            taban = self.servis_ac()
            kod, bir = self.cagir(taban, "/api/tarama", {"set": 1})
            kod, iki = self.cagir(taban, "/api/tarama", {"set": 2})
            self.assertNotEqual(bir["id"], iki["id"])
            self.isi_bekle(isler.YONETICI.bul(bir["id"]))
            self.isi_bekle(isler.YONETICI.bul(iki["id"]))

    def test_18_iptal_calisan_isi_kontrollu_bitirir(self):
        """Sessiz cihazlar: iş uzun sürer, ortasında iptal edilir."""
        self.kur_harita(_harita(12))
        with sahte.sessiz() as sessiz:
            self.switch_portu(sessiz.port)
            from core import ayar
            ayar.ANONS_PORT = sessiz.port
            taban = self.servis_ac()

            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            is_ = isler.YONETICI.bul(y["id"])
            time.sleep(0.5)

            kod, iptal = self.cagir(taban, "/api/is/iptal", {"id": y["id"]})
            self.assertEqual(kod, 200)
            self.assertTrue(iptal["iptal"])

            self.isi_bekle(is_, sure=25)
            self.assertEqual(is_.durum, isler.IPTAL)

            # İptal edilen iş kuyruktan silinebilmeli
            kod, silme = self.cagir(taban, "/api/is/sil", {"id": y["id"]})
            self.assertEqual(kod, 200)
            self.assertTrue(silme["silindi"])

    def test_18b_calisan_is_silinemez(self):
        self.kur_harita(_harita(12))
        with sahte.sessiz() as sessiz:
            self.switch_portu(sessiz.port)
            from core import ayar
            ayar.ANONS_PORT = sessiz.port
            taban = self.servis_ac()
            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            kod, silme = self.cagir(taban, "/api/is/sil", {"id": y["id"]})
            self.assertEqual(kod, 409)
            self.assertFalse(silme["silindi"])
            self.cagir(taban, "/api/is/iptal", {"id": y["id"]})
            self.isi_bekle(isler.YONETICI.bul(y["id"]), sure=25)

    def test_hafif_yenileme_yalniz_yesil_cihazlari_okur(self):
        """Yenileme, taramada yeşile düşen cihazlarla sınırlıdır.

        Ulaşılamayan cihaz her turda yeniden denenirse tur, cevap
        vermeyen cihazın zaman aşımı kadar uzuyor; yenileme de bunu
        beklerken çalışan cihazların verisi bayatlıyor.
        """
        import socket
        from core import ayar

        # Kapalı port: kamera bağlantısı anında reddedilir, kırmızı olur.
        p = socket.socket()
        p.bind(("127.0.0.1", 0))
        kapali = p.getsockname()[1]
        p.close()

        harita = sahte.device_map([
            {"Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
             "Type": "Announcement", "SubType": "Intercom", "Port": "11",
             "PBXExtension": "2001", "Status": {"NoError": True}},
            {"Name": "Cam_1", "IP": "127.0.0.1", "IsActive": True,
             "Type": "Camera", "SubType": "Corridor", "Port": "12",
             "Status": {"NoError": True}},
        ], switch_ip="127.0.0.1")
        env = self.kur_harita(harita)
        kamera = env.tip_ile("Camera")[0]

        with sahte.kyland() as sw, sahte.anons() as an:
            self.switch_portu(sw.port)
            ayar.ANONS_PORT = an.port
            ayar.VIDEO_PORT = kapali
            taban = self.servis_ac()

            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            self.isi_bekle(isler.YONETICI.bul(y["id"]), sure=30)

            kod, d = self.cagir(taban, "/api/durum?set=1")
            renk = {c["id"]: c["sonuc"]["durum"] for c in d["cihazlar"]}
            yesiller = [i for i, r in renk.items() if r == dogrulama.YESIL]
            self.assertEqual(renk[kamera.id], dogrulama.KIRMIZI)
            self.assertTrue(yesiller)

            kod, yenile = self.cagir(taban, "/api/yenile", {"set": 1})
            self.assertEqual(kod, 200)
            self.assertCountEqual(yenile["yenilenen"], yesiller)
            self.assertNotIn(kamera.id, yenile["yenilenen"])

            # Kırmızı cihaz açıkça istense bile yenilenmez.
            istek = self.cagir(taban, "/api/yenile",
                               {"set": 1, "cihazlar": [kamera.id]})[1]
            self.assertEqual(istek["yenilenen"], [])

    def test_tam_tarama_sirasinda_hafif_yenileme_reddedilir(self):
        self.kur_harita(_harita(12))
        with sahte.sessiz() as sessiz:
            self.switch_portu(sessiz.port)
            from core import ayar
            ayar.ANONS_PORT = sessiz.port
            taban = self.servis_ac()
            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})

            kod, yenile = self.cagir(taban, "/api/yenile", {"set": 1})
            self.assertEqual(kod, 409)
            self.assertTrue(yenile["beklemede"])

            self.cagir(taban, "/api/is/iptal", {"id": y["id"]})
            self.isi_bekle(isler.YONETICI.bul(y["id"]), sure=25)

    def test_is_satirlari_bastan_olusur(self):
        """Satırlar tarama başlamadan önce hazır olmalı."""
        self.kur_harita(_harita(4))
        with sahte.sessiz() as sessiz:
            self.switch_portu(sessiz.port)
            from core import ayar
            ayar.ANONS_PORT = sessiz.port
            taban = self.servis_ac()
            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            kod, tam = self.cagir(taban, f"/api/is?id={y['id']}")
            # 4 cihaz + switch; sayaçlar ilerleme satırlarını içermez
            self.assertEqual(tam["sayilar"]["toplam"], 5)
            self.assertGreaterEqual(len(tam["satirlar"]), 5)
            for s in tam["satirlar"]:
                self.assertIn("ad", s)
                self.assertIn("ip", s)
                self.assertIn("yontem", s)

            self.cagir(taban, "/api/is/iptal", {"id": y["id"]})
            self.isi_bekle(isler.YONETICI.bul(y["id"]), sure=25)

    def test_kapatilan_kuyruk_yeni_is_kabul_etmez_ve_acilabilir(self):
        """Kapanış sonrası kuyruk sessizce yutmaz; açılınca yine çalışır.

        Eskiden kapatılan yönetici yeni işleri sıraya alıyor ama dağıtıcı
        iş parçacığı ölü olduğu için hiçbiri başlamıyordu: kullanıcı
        sonsuza kadar "Bekliyor" görürdü.
        """
        yonetici = isler.Yonetici()
        try:
            bitti = threading.Event()
            is_ = isler.Is("test", "deneme", 1, anahtar="t:1")
            yonetici.ekle(is_, lambda j: bitti.set())
            self.assertTrue(bitti.wait(5), "iş çalışmalıydı")

            yonetici.kapat()
            self.assertTrue(yonetici.kapali_mi())
            with self.assertRaises(RuntimeError):
                yonetici.ekle(isler.Is("test", "ikinci", 1, anahtar="t:2"),
                              lambda j: None)

            yonetici.ac()
            ikinci_bitti = threading.Event()
            yonetici.ekle(isler.Is("test", "ucuncu", 1, anahtar="t:3"),
                          lambda j: ikinci_bitti.set())
            self.assertTrue(ikinci_bitti.wait(5),
                            "açılan kuyruk yeniden çalışmalı")
        finally:
            yonetici.kapat()

    def test_eski_is_sonucu_yeni_gorunumu_ezmez(self):
        """İş kaydı ile cihaz görünümü ayrı yerlerde tutulur."""
        gor = isler.gorunum(7)
        s = dogrulama.basarili({"surum": "1.2.5"}, "http")
        s.nesil = isler.sonraki_nesil()
        gor.yaz("d1", s)

        eski_is = isler.Is("tarama", "eski", 7)
        eski_is.ozel_satir("d1", "Eski iş satırı", durum="hata",
                           not_="Yanıt yok")
        # İş satırı değişti ama cihaz görünümü aynı kaldı
        self.assertEqual(gor.al("d1").durum, dogrulama.YESIL)
        self.assertEqual(eski_is.satirlar()[0]["durum"], "hata")


if __name__ == "__main__":
    unittest.main()
