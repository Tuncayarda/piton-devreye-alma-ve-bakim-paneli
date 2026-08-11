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

    def test_cihaza_yazan_kosu_sirasinda_hafif_yenileme_reddedilir(self):
        """Koşu sürerken cihaz okunmaz.

        Tam tarama kuyruğa girdiği için koşuyla zaten çakışamaz; hafif
        yenileme ise isteği karşılayan iş parçacığında okuduğundan
        kuyruğun dışında kalır. Koşu sırasında cihaz yeniden başlıyor ya
        da PoE portu kapalı oluyor — o geçici hâl kalıcı sonuç diye
        yazılmamalı.
        """
        self.kur_harita(_harita(4))
        with sahte.sessiz() as sessiz:
            self.switch_portu(sessiz.port)
            from core import ayar
            ayar.ANONS_PORT = sessiz.port
            taban = self.servis_ac()

            birak = threading.Event()
            is_ = isler.Is("fw", "Yazılım yükleme · 2 cihaz", 1)
            isler.YONETICI.ekle(is_, lambda j: birak.wait(20))
            try:
                for _ in range(100):        # işin başlamasını bekle
                    if is_.durum == isler.CALISIYOR:
                        break
                    time.sleep(0.05)
                self.assertEqual(is_.durum, isler.CALISIYOR)

                kod, yenile = self.cagir(taban, "/api/yenile", {"set": 1})
                self.assertEqual(kod, 409)
                self.assertTrue(yenile["beklemede"])
            finally:
                birak.set()
                self.isi_bekle(is_, sure=25)

    def test_otomatik_taramalar_kuyruk_gecmisini_doldurmaz(self):
        """Dakikalık tarama, kullanıcının iş kayıtlarını dışarı itmemeli.

        Otomatik tarama normal geçmiş sınırına girseydi yirmi dakikada IP
        atama / konfigürasyon / yazılım yükleme kayıtlarının hepsi
        kuyruktan düşerdi. Bitmiş otomatik taramadan yalnız en yenisi
        tutulur; elle başlatılan işler olduğu gibi kalır.
        """
        elle = isler.Is("fw", "Yazılım yükleme · 1 cihaz", 1)
        isler.YONETICI.ekle(elle, lambda j: None)
        self.isi_bekle(elle, sure=10)

        for _ in range(5):
            oto = isler.Is("tarama", "Otomatik tarama · Set 1", 1,
                           anahtar="tarama:1", otomatik=True)
            isler.YONETICI.ekle(oto, lambda j: None)
            self.isi_bekle(oto, sure=10)

        liste = isler.YONETICI.liste()
        otomatikler = [j for j in liste if j.otomatik]
        # Budama ekleme sırasında çalışıyor: o an eklenen iş henüz
        # bitmediği için elenmez. Sayı bu yüzden ikiyi geçmez ve tur
        # sayısıyla BÜYÜMEZ — asıl istenen bu.
        self.assertLessEqual(len(otomatikler), 2, "otomatik taramalar birikmiş")
        self.assertIn(elle.id, [j.id for j in liste],
                      "elle başlatılan iş geçmişte durmalı")

    def test_otomatik_tarama_isareti_yanitta_gelir(self):
        """Arayüz otomatik turu elle başlatılandan ayırabilmeli."""
        self.kur_harita(_harita(2))
        with sahte.sessiz() as sessiz:
            self.switch_portu(sessiz.port)
            from core import ayar
            ayar.ANONS_PORT = sessiz.port
            taban = self.servis_ac()

            kod, y = self.cagir(taban, "/api/tarama",
                                {"set": 1, "otomatik": True})
            self.assertEqual(kod, 200)
            self.assertTrue(y["otomatik"])
            self.assertIn("Otomatik tarama", y["baslik"])
            self.cagir(taban, "/api/is/iptal", {"id": y["id"]})
            self.isi_bekle(isler.YONETICI.bul(y["id"]), sure=25)

            kod, y2 = self.cagir(taban, "/api/tarama", {"set": 1})
            self.assertFalse(y2["otomatik"])
            self.assertIn("Tam tarama", y2["baslik"])
            self.cagir(taban, "/api/is/iptal", {"id": y2["id"]})
            self.isi_bekle(isler.YONETICI.bul(y2["id"]), sure=25)

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

    def test_kapanis_calisan_is_guvenlik_temizligini_bitirene_dek_bekler(self):
        """Daemon iş, kapanışta donanımı güvenli bırakmadan kesilmemeli."""
        yonetici = isler.Yonetici()
        basladi = threading.Event()
        temizlige_girdi = threading.Event()
        temizligi_bitir = threading.Event()
        kapandi = threading.Event()
        kapanis_sonucu = []

        def govde(is_):
            basladi.set()
            is_.iptal.wait(2)
            temizlige_girdi.set()
            temizligi_bitir.wait(2)

        try:
            yonetici.ekle(
                isler.Is("ip", "PoE güvenlik denemesi", 1, anahtar="ip:1"),
                govde,
            )
            self.assertTrue(basladi.wait(1))

            def kapat():
                kapanis_sonucu.append(yonetici.kapat())
                kapandi.set()

            kapanis = threading.Thread(target=kapat)
            kapanis.start()
            self.assertTrue(temizlige_girdi.wait(1))
            self.assertFalse(kapandi.is_set())
            temizligi_bitir.set()
            kapanis.join(1)
            self.assertTrue(kapandi.is_set())
            self.assertEqual(kapanis_sonucu, [True])
        finally:
            temizligi_bitir.set()
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


class CokenIsKuyrugu(unittest.TestCase):
    """Çöken bir iş kuyruğu kilitlememeli.

    Sahada görülen zincir: IP atama koşusu çöküyor, iş sonsuza kadar
    "çalışıyor" kalıyor ve o iş "yazan iş" sayıldığı için hem hafif
    yenileme hem tam tarama 409 ile reddediliyor — koşudan sonra bütün
    ekranlar tazelenmeyi bırakıyordu.
    """

    def setUp(self):
        self.y = isler.Yonetici()
        self.addCleanup(self.y.kapat)

    def _bekle(self, is_, sure=5.0):
        son = time.time() + sure
        while time.time() < son:
            if is_.durum in (isler.TAMAM, isler.IPTAL, isler.HATA):
                return True
            time.sleep(0.02)
        return False

    def _kosturt(self, patlat):
        is_ = isler.Is("ip", "IP atama · Test", 1)
        self.y.ekle(is_, patlat)
        self.assertTrue(self._bekle(is_), f"iş kapanmadı: {is_.durum}")
        return is_

    def test_systemexit_isi_calisiyor_birakmaz(self):
        """argparse geçersiz argümanda sys.exit() çağırıyor; bu bir
        Exception DEĞİL ve eski `except Exception` onu kaçırıyordu."""
        def patlat(is_):
            raise SystemExit(2)

        is_ = self._kosturt(patlat)
        self.assertEqual(is_.durum, isler.HATA)
        self.assertIn("2", is_.hata)

    def test_coken_isten_sonra_kuyruk_calismaya_devam_eder(self):
        """Dağıtıcı iş parçacığı ölmemeli: asıl zarar burada."""
        self._kosturt(lambda is_: (_ for _ in ()).throw(SystemExit(1)))

        sonraki = isler.Is("tarama", "Sonraki iş", 1)
        calisti = threading.Event()
        self.y.ekle(sonraki, lambda is_: calisti.set())
        self.assertTrue(calisti.wait(5.0), "kuyruk durmuş")
        self.assertTrue(self._bekle(sonraki))
        self.assertEqual(sonraki.durum, isler.TAMAM)

    def test_yazan_is_takili_kalmaz(self):
        """Kilidin kaynağı: `aktif`/`CALISIYOR` sorgusu takılı işi görüyordu."""
        is_ = self._kosturt(lambda is_: (_ for _ in ()).throw(SystemExit(1)))
        self.assertIsNone(self.y.aktif(is_.anahtar))
        self.assertEqual(
            [j for j in self.y.liste() if j.durum == isler.CALISIYOR], [])

    def test_govdesiz_is_kapanir(self):
        is_ = isler.Is("tarama", "Gövdesiz", 1)
        self.y.ekle(is_, lambda j: None)
        self.y._is_govde.pop(is_.id, None)          # budanmış gibi
        self.assertTrue(self._bekle(is_))
        self.assertEqual(is_.durum, isler.HATA)

    def test_olagan_hata_eskisi_gibi_raporlanir(self):
        is_ = self._kosturt(
            lambda j: (_ for _ in ()).throw(ValueError("Port seçilmedi")))
        self.assertEqual(is_.durum, isler.HATA)
        self.assertEqual(is_.hata, "Port seçilmedi")


class IpOzetHatasi(unittest.TestCase):
    """Kısmen tamamlanan koşu ne yazmalı.

    "IP atama betiği 1 koduyla bitti" kullanıcıya hiçbir şey söylemiyordu:
    on iki portun onu tamamlanmış olsa da aynı cümle çıkıyordu.
    """

    def _ozet(self, basarili, hatali, atlanan=0, kod=1):
        import panel_api

        return panel_api._ip_ozet_hatasi(
            {"toplam": basarili + hatali + atlanan, "basarili": basarili,
             "hatali": hatali, "atlanan": atlanan}, kod)

    def test_kismi_basarida_sayilar_yazilir(self):
        metin = self._ozet(basarili=10, hatali=2)
        self.assertIn("10/12", metin)
        self.assertIn("2 port", metin)
        self.assertNotIn("koduyla", metin)

    def test_hicbiri_bitmediyse_ayri_cumle(self):
        self.assertIn("Hiçbir port", self._ozet(basarili=0, hatali=12))

    def test_eksik_yoksa_cikis_koduna_duser(self):
        """Port satırları temizse söylenecek tek şey çıkış kodudur."""
        self.assertIn("2 koduyla", self._ozet(basarili=12, hatali=0, kod=2))

    def test_atlanan_portlar_da_eksik_sayilir(self):
        metin = self._ozet(basarili=8, hatali=1, atlanan=3)
        self.assertIn("8/12", metin)
        self.assertIn("4 port", metin)


if __name__ == "__main__":
    unittest.main()
