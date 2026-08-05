#!/usr/bin/env python3
"""Kilit akışı ve kimlik bilgilerinin bellekte kalması.

Kapsanan gereksinimler:
  4. 401/403 cihazı kilit listesine düşer.
  5. Doğru bilgi girilince cihaz yeşile döner ve kilit listesinden kalkar.
  6. Yanlış bilgi, önceden çalışan RAM kimliğini ezmez.
  7. Uygulama kapanınca RAM kimlik deposu temizlenir.
  8. Yeni uygulama sürecinde önceki parolalar bulunmaz.
 12. Eski tarama cevabı yeni doğrulama başarısını ezmez.
 15. Kamera/NVR 401 cevabı kilit akışına girer.
 16. Timeout ile yanlış parola farklı hata sınıfları üretir.
"""
from __future__ import annotations

import subprocess
import sys
import unittest

from core import ayar, dogrulama, isler, kimlik, okuma
from core.hata import KimlikHatasi, UlasilamadiHatasi

from .ortak import ServisTesti
from . import sahte

PAROLA = "gizli-Parola-42"


def _switch_haritasi():
    return sahte.device_map([], switch_ip="127.0.0.1", switch_ad="Test_SW")


def _kamera_haritasi():
    return sahte.device_map([{
        "Name": "Corridor_Cam_1", "IP": "127.0.0.1", "IsActive": True,
        "Type": "Camera", "SubType": "Corridor", "Port": "1",
        "Username": "admin", "Password": "devicemap-parolasi",
        "Status": {"NoError": False},
    }])


class KilitAkisi(ServisTesti):

    def test_4_401_alan_cihaz_kilit_listesine_duser(self):
        env = self.kur_harita(_switch_haritasi())
        with sahte.kyland(parola=PAROLA) as sw:
            self.switch_portu(sw.port)
            taban = self.servis_ac()

            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            self.assertEqual(kod, 200)
            self.isi_bekle(isler.YONETICI.bul(y["id"]))

            kod, kilit = self.cagir(taban, "/api/kilit?set=1")
            self.assertEqual(kod, 200)
            adlar = [c["ad"] for c in kilit["cihazlar"]]
            self.assertIn("Test_SW", adlar)
            self.assertEqual(kilit["cihazlar"][0]["kimlikGrubu"], "switch")
            self.assertFalse(kilit["cihazlar"][0]["kimlikVar"])

            kod, durum = self.cagir(taban, "/api/durum?set=1")
            self.assertEqual(durum["sayilar"]["erisimBekleyen"], 1)
            self.assertEqual(durum["kilitSayisi"], 1)

    def test_15_kamera_401_de_ayni_akisa_girer(self):
        env = self.kur_harita(_kamera_haritasi())
        with sahte.kamera(parola=PAROLA) as kam:
            ayar.VIDEO_PORT = kam.port
            taban = self.servis_ac()

            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            self.isi_bekle(isler.YONETICI.bul(y["id"]))

            kod, kilit = self.cagir(taban, "/api/kilit?set=1")
            kameralar = [c for c in kilit["cihazlar"] if c["type"] == "Camera"]
            self.assertEqual(len(kameralar), 1)
            self.assertEqual(kameralar[0]["kimlikGrubu"], "video")

            # Doğru kimlikle yeşile döner
            cid = kameralar[0]["id"]
            kod, y = self.cagir(taban, "/api/kimlik", {
                "set": 1, "cihazId": cid,
                "kullanici": "admin", "parola": PAROLA})
            self.assertEqual(kod, 200)
            self.assertEqual(y["sonuc"], "dogrulandi")
            self.assertEqual(y["cihaz"]["sonuc"]["alanlar"]["surum"], "V5.7.3")

    def test_5_dogru_bilgi_yesile_cevirir_ve_kilitten_cikarir(self):
        env = self.kur_harita(_switch_haritasi())
        with sahte.kyland(parola=PAROLA) as sw:
            self.switch_portu(sw.port)
            taban = self.servis_ac()
            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            self.isi_bekle(isler.YONETICI.bul(y["id"]))

            kod, kilit = self.cagir(taban, "/api/kilit?set=1")
            cid = kilit["cihazlar"][0]["id"]

            kod, y = self.cagir(taban, "/api/kimlik", {
                "set": 1, "cihazId": cid,
                "kullanici": "admin", "parola": PAROLA})
            self.assertEqual(kod, 200)
            self.assertEqual(y["sonuc"], "dogrulandi")

            # Cihaz yeniden okunmuş ve yeşile dönmüş olmalı
            self.assertEqual(y["cihaz"]["sonuc"]["durum"], dogrulama.YESIL)
            self.assertEqual(y["cihaz"]["sonuc"]["alanlar"]["surum"], "F6014")

            # Sayaçlar aynı yanıtta güncel
            self.assertEqual(y["durum"]["sayilar"]["erisimBekleyen"], 0)
            self.assertEqual(y["durum"]["sayilar"]["basarili"], 1)
            self.assertEqual(y["durum"]["kilitSayisi"], 0)

            # Kilit listesi boşalmış
            kod, kilit = self.cagir(taban, "/api/kilit?set=1")
            self.assertEqual(kilit["cihazlar"], [])

            # Tam tarama tekrar gerekmedi: hafif yenileme cihazı okuyabiliyor
            kod, y = self.cagir(taban, "/api/yenile", {"set": 1})
            self.assertEqual(kod, 200)
            self.assertIn(cid, y["yenilenen"])

    def test_6_yanlis_bilgi_calisan_kimligi_ezmez(self):
        env = self.kur_harita(_switch_haritasi())
        with sahte.kyland(parola=PAROLA) as sw:
            self.switch_portu(sw.port)
            taban = self.servis_ac()
            sw_cihaz = env.switchler()[0]

            kod, _ = self.cagir(taban, "/api/kimlik", {
                "set": 1, "cihazId": sw_cihaz.id,
                "kullanici": "admin", "parola": PAROLA})
            self.assertEqual(kod, 200)
            self.assertEqual(kimlik.al(sw_cihaz.id, sw_cihaz.ip),
                             ("admin", PAROLA))

            kod, y = self.cagir(taban, "/api/kimlik", {
                "set": 1, "cihazId": sw_cihaz.id,
                "kullanici": "admin", "parola": "yanlis"})
            self.assertEqual(kod, 401)
            self.assertEqual(y["hata"],
                             "Kullanıcı adı veya parola doğrulanamadı")

            # RAM'deki çalışan kimlik olduğu gibi durur
            self.assertEqual(kimlik.al(sw_cihaz.id, sw_cihaz.ip),
                             ("admin", PAROLA))
            # Cihaz da yeşil kalır — yanlış deneme onu turuncuya çevirmez
            gor = isler.gorunum(1)
            self.assertEqual(gor.al(sw_cihaz.id).durum, dogrulama.YESIL)

    def test_16_timeout_ile_yanlis_parola_ayri_siniflar(self):
        env = self.kur_harita(_switch_haritasi())
        sw_cihaz = env.switchler()[0]

        with sahte.kyland(parola=PAROLA) as sw:
            self.switch_portu(sw.port)
            yanlis = okuma.cihaz_oku(sw_cihaz, kimlik=("admin", "hatali"),
                                     timeout=3)
        self.assertEqual(yanlis.durum, dogrulama.TURUNCU)
        self.assertEqual(yanlis.dogrulama, dogrulama.KIMLIK_BEKLIYOR)

        with sahte.sessiz() as sessiz:
            self.switch_portu(sessiz.port)
            ulasilmaz = okuma.cihaz_oku(sw_cihaz, kimlik=("admin", PAROLA),
                                        timeout=1.0)
        self.assertEqual(ulasilmaz.durum, dogrulama.KIRMIZI)
        self.assertEqual(ulasilmaz.dogrulama, dogrulama.DOGRULANAMADI)
        self.assertNotEqual(yanlis.aciklama, ulasilmaz.aciklama)
        self.assertIn("zaman aşımı", ulasilmaz.aciklama.lower())

    def test_12_eski_tarama_cevabi_yeni_dogrulamayi_ezmez(self):
        """Nesil denetimi: geç gelen eski cevap yenisini geri alamaz."""
        gor = isler.Gorunum(1)

        eski_nesil = isler.sonraki_nesil()
        yeni_nesil = isler.sonraki_nesil()

        yeni = dogrulama.basarili({"surum": "F6014"}, "kyland")
        yeni.nesil = yeni_nesil
        self.assertTrue(gor.yaz("sw1", yeni))

        # Taramadan geç dönen turuncu sonuç (daha ESKİ nesil)
        eski = dogrulama.Sonuc(durum=dogrulama.TURUNCU,
                               dogrulama=dogrulama.KIMLIK_BEKLIYOR,
                               aciklama="şifre istiyor", yontem="kyland",
                               nesil=eski_nesil)
        self.assertFalse(gor.yaz("sw1", eski))
        self.assertEqual(gor.al("sw1").durum, dogrulama.YESIL)

        # Daha yeni bir turuncu ise geçerlidir
        daha_yeni = dogrulama.Sonuc(durum=dogrulama.TURUNCU,
                                    dogrulama=dogrulama.KIMLIK_BEKLIYOR,
                                    yontem="kyland",
                                    nesil=isler.sonraki_nesil())
        self.assertTrue(gor.yaz("sw1", daha_yeni))
        self.assertEqual(gor.al("sw1").durum, dogrulama.TURUNCU)

    def test_7_kapanista_bellek_temizlenir(self):
        env = self.kur_harita(_switch_haritasi())
        sw_cihaz = env.switchler()[0]
        kimlik.ver(sw_cihaz.id, sw_cihaz.ip, "admin", PAROLA,
                   grup="switch", gruba_uygula=True)
        self.assertEqual(kimlik.sayi(), 1)

        import panel_api
        panel_api.temizle()

        self.assertEqual(kimlik.sayi(), 0)
        self.assertIsNone(kimlik.al(sw_cihaz.id, sw_cihaz.ip, grup="switch"))
        self.assertEqual(kimlik.ozet(), {"cihaz": {}, "grup": {}})

    def test_8_yeni_surecte_onceki_parolalar_bulunmaz(self):
        """Ayrı bir Python süreci başlatılır; depo boş olmalı.

        Bu, "aynı testte temizledik" demekten farklı: gerçekten yeni bir
        yorumlayıcıda hiçbir kalıcı kaynaktan kimlik yüklenmediğini
        gösterir.
        """
        env = self.kur_harita(_switch_haritasi())
        sw_cihaz = env.switchler()[0]
        kimlik.ver(sw_cihaz.id, sw_cihaz.ip, "admin", PAROLA,
                   grup="switch", gruba_uygula=True)

        betik = (
            "import sys, json;"
            f"sys.path.insert(0, {str(ayar.KOK)!r});"
            "from core import kimlik;"
            "print(json.dumps({'sayi': kimlik.sayi(),"
            " 'ozet': kimlik.ozet(),"
            f" 'al': kimlik.al({sw_cihaz.id!r}, {sw_cihaz.ip!r},"
            " grup='switch')}))"
        )
        cikti = subprocess.run([sys.executable, "-c", betik],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(cikti.returncode, 0, cikti.stderr)
        veri = __import__("json").loads(cikti.stdout.strip().splitlines()[-1])
        self.assertEqual(veri["sayi"], 0)
        self.assertIsNone(veri["al"])
        self.assertEqual(veri["ozet"], {"cihaz": {}, "grup": {}})
        # Parola metni yeni sürecin çıktısında hiç geçmemeli
        self.assertNotIn(PAROLA, cikti.stdout)

    def test_kimlik_okuma_yolu_tarama_ile_ayni(self):
        """Kimlik denemesi ile tarama aynı okuma kodundan geçer.

        Ayrı yollar olsaydı "formda çalıştı, taramada çalışmadı" durumu
        doğardı; test bunu doğrudan iddia ediyor.
        """
        env = self.kur_harita(_switch_haritasi())
        sw_cihaz = env.switchler()[0]
        with sahte.kyland(parola=PAROLA) as sw:
            self.switch_portu(sw.port)
            a = okuma.cihaz_oku(sw_cihaz, kimlik=("admin", PAROLA))
            kimlik.ver(sw_cihaz.id, sw_cihaz.ip, "admin", PAROLA,
                       grup="switch")
            b = okuma.cihaz_oku(
                sw_cihaz,
                kimlik=kimlik.al(sw_cihaz.id, sw_cihaz.ip, grup="switch"))
        self.assertEqual(a.durum, b.durum)
        self.assertEqual(a.alanlar, b.alanlar)


if __name__ == "__main__":
    unittest.main()
