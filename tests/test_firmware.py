#!/usr/bin/env python3
"""Yazılım yükleme — iki cihaz ailesi.

Buradaki testlerin ortak derdi: hangi cihaza hangi dosyanın gittiği belli
olmalı. Dosya cihaz başına seçiliyor — bir intercom farklı bir
revizyondan olabiliyor ve grubun geri kalanıyla aynı .bin'i almıyor. Tek
bir "seçili dosya" tutulduğunda bu görünmüyor, yanlış imaj sessizce
gidiyordu.

Anons ekipmanı HTTP ile imaj alır, Compartment LCD adb ile APK. İkisinde
de "istek kabul edildi" tek başına başarı sayılmaz: cihaz yeniden okunur
ve sürümün gerçekten değiştiği görülür.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import time

from core import ayar, firmware, isler
from core.hata import DogrulamaHatasi, UygulanmazHatasi

from .ortak import PanelTesti, ServisTesti
from . import sahte


def imaj(ad: str, icerik: bytes = b"BIN") -> str:
    yol = Path(tempfile.mkdtemp(prefix="fw-test-")) / ad
    yol.write_bytes(icerik)
    return str(yol)


class DosyaSecimi(PanelTesti):

    def kur(self, sayi=2):
        cihazlar = [{
            "Name": f"Intercom_{i}", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "Intercom", "Port": str(10 + i),
            "Status": {"NoError": True},
        } for i in range(1, sayi + 1)]
        env = self.kur_harita(sahte.device_map(cihazlar))
        return env, env.tip_ile("Announcement")

    def test_her_cihaz_kendi_imajini_tutar(self):
        _, cihazlar = self.kur()
        a, b = cihazlar[0], cihazlar[1]
        firmware.dosya_sec([a.id], imaj("intercom-1.2.6.bin"), "1.2.6")
        firmware.dosya_sec([b.id], imaj("intercom-1.1.9.bin"), "1.1.9")

        self.assertEqual(firmware.secili_of(a.id)["ad"], "intercom-1.2.6.bin")
        self.assertEqual(firmware.secili_of(a.id)["surum"], "1.2.6")
        self.assertEqual(firmware.secili_of(b.id)["ad"], "intercom-1.1.9.bin")
        self.assertEqual(len(firmware.secilenler()), 2)

    def test_secim_silinebilir(self):
        _, cihazlar = self.kur()
        a, b = cihazlar[0], cihazlar[1]
        firmware.dosya_sec([a.id, b.id], imaj("ortak.bin"))
        self.assertEqual(firmware.sil([a.id]), 1)
        self.assertFalse(firmware.secili_var(a.id))
        self.assertTrue(firmware.secili_var(b.id))
        firmware.temizle()
        self.assertEqual(firmware.secilenler(), {})

    def test_gecersiz_dosya_secilmez(self):
        _, cihazlar = self.kur(1)
        c = cihazlar[0]
        bos = Path(tempfile.mkdtemp(prefix="fw-test-")) / "bos.bin"
        bos.write_bytes(b"")
        for yol, beklenen in (("/yok/olmayan.bin", "bulunamadı"),
                              (str(bos), "boş")):
            with self.assertRaises(ValueError, msg=yol) as t:
                firmware.dosya_sec([c.id], yol)
            self.assertIn(beklenen, str(t.exception))
        # Hiçbiri seçime yazılmamalı.
        self.assertFalse(firmware.secili_var(c.id))

    def test_dosyasi_olmayan_cihaza_yukleme_yapilmaz(self):
        _, cihazlar = self.kur(1)
        with self.assertRaises(ValueError) as t:
            firmware.yukle(cihazlar[0])
        self.assertIn("dosya seçilmedi", str(t.exception))

    def test_yukleme_ucu_olmayan_cihaz_reddedilir(self):
        """Yalnız kendi HTTP ucu olan cihazlarda yükleme var."""
        harita = sahte.device_map([{
            "Name": "Kamera_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Camera", "SubType": "", "Port": "11", "Status": {}}])
        env = self.kur_harita(harita)
        c = env.tip_ile("Camera")[0]
        firmware.dosya_sec([c.id], imaj("x.bin"))
        with self.assertRaises(UygulanmazHatasi):
            firmware.yukle(c)


class Yukleme(PanelTesti):

    def kur(self):
        harita = sahte.device_map([{
            "Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "Intercom", "Port": "11",
            "Status": {"NoError": True}}])
        env = self.kur_harita(harita)
        return env, env.tip_ile("Announcement")[0]

    def test_imaj_cihaza_gonderilir_ve_surum_dogrulanir(self):
        _, c = self.kur()
        firmware.dosya_sec([c.id], imaj("intercom-1.2.6.bin", b"IMAJ-VERISI"),
                           "1.2.6")
        with sahte.anons(yeni_surum="1.2.6") as an:
            ayar.ANONS_PORT = an.port
            sonuc = firmware.yukle(c, dogrula_sure=10.0)
            gonderilen = list(an.yuklenen)

        self.assertEqual(sonuc["yeni"], "1.2.6")
        self.assertEqual(sonuc["onceki"], "1.2.5")
        self.assertTrue(sonuc["degisti"])
        # Cihaza giden gövde gerçekten seçilen dosya.
        self.assertEqual(len(gonderilen), 1)
        self.assertIn(b"IMAJ-VERISI", gonderilen[0])
        self.assertIn(b"intercom-1.2.6.bin", gonderilen[0])
        # İstek cihazın kendi arayüzünün gönderdiğiyle aynı biçimde:
        # alan adı "firmware", parça türü application/macbinary.
        self.assertIn(b'name="firmware"', gonderilen[0])
        self.assertIn(b"application/macbinary", gonderilen[0])

    def test_yukleme_cihazin_kendi_ucuna_gider(self):
        """Uç /api/v1/system/firmware — "update" değil.

        Yanlış adrese giden yükleme cihazda HTTP 404 ile düşüyordu.
        """
        _, c = self.kur()
        firmware.dosya_sec([c.id], imaj("intercom-1.2.6.bin"), "")
        with sahte.anons(yeni_surum="1.2.6") as an:
            ayar.ANONS_PORT = an.port
            firmware.yukle(c, dogrula_sure=10.0)
            yollar = [y for yontem, y in an.gecmis if yontem == "POST"]
        self.assertEqual(yollar, ["/api/v1/system/firmware"])

    def test_beklenen_surum_gelmezse_basarisiz(self):
        """HTTP 200 yeterli değil: cihaz başka sürüm bildiriyorsa hata."""
        from core.hata import DogrulamaHatasi

        _, c = self.kur()
        firmware.dosya_sec([c.id], imaj("intercom-1.3.0.bin"), "1.3.0")
        with sahte.anons(yeni_surum="1.2.6") as an:
            ayar.ANONS_PORT = an.port
            with self.assertRaises(DogrulamaHatasi) as t:
                firmware.yukle(c, dogrula_sure=10.0)
        self.assertIn("1.2.6", str(t.exception))

    def test_secildikten_sonra_silinen_dosya_yakalanir(self):
        _, c = self.kur()
        yol = imaj("gecici.bin")
        firmware.dosya_sec([c.id], yol)
        Path(yol).unlink()
        with self.assertRaises(ValueError) as t:
            firmware.yukle(c)
        self.assertIn("artık yok", str(t.exception))


DUMPSYS_ESKI = "    versionCode=1 minSdk=21 targetSdk=35\n    versionName=0.0.5"
DUMPSYS_YENI = "    versionCode=2 minSdk=21 targetSdk=35\n    versionName=0.0.6"


class SahteAdbKurulum:
    """subprocess.run yerine geçer; adb install akışını taklit eder.

    `install_cikti` ile cihazın yanıtı, `surumler` ile dumpsys'in art
    arda döndüreceği sürümler verilir.
    """

    def __init__(self, install_cikti="Success\n", surumler=None,
                 install_stderr=""):
        self.install_cikti = install_cikti
        self.install_stderr = install_stderr
        self.surumler = list(surumler or [DUMPSYS_ESKI, DUMPSYS_YENI])
        self.cagrilar: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.cagrilar.append(list(args))
        out, err = "", ""
        if "install" in args:
            out, err = self.install_cikti, self.install_stderr
        elif "dumpsys" in args:
            out = (self.surumler.pop(0) if self.surumler
                   else DUMPSYS_YENI)
        elif "connect" in args:
            out = "connected"

        class Sonuc:
            stdout = out
            stderr = err
            returncode = 0
        return Sonuc()

    def komut(self, ad: str) -> list[str] | None:
        return next((c for c in self.cagrilar if ad in c), None)


class ApkKurulumu(PanelTesti):
    """Compartment LCD — imaj değil APK, HTTP değil adb."""

    def kur(self):
        harita = sahte.device_map([{
            "Name": "Compartment_Lcd_1", "IP": "10.n.1.40", "IsActive": True,
            "Type": "LCD", "SubType": "Compartment", "Port": "13",
            "Status": {}}])
        env = self.kur_harita(harita)
        return env, env.tip_ile("LCD")[0]

    def yamala(self, sahte_adb):
        eski = firmware.subprocess.run
        firmware.subprocess.run = sahte_adb
        self.addCleanup(lambda: setattr(firmware.subprocess, "run", eski))
        return sahte_adb

    def test_lcd_apk_bekler(self):
        _, c = self.kur()
        self.assertTrue(firmware.destekli(c))
        self.assertEqual(firmware.uzanti(c), "apk")

    def test_apk_adb_ile_kurulur_ve_surum_dogrulanir(self):
        _, c = self.kur()
        apk = imaj("panel-0.0.6.apk")
        firmware.dosya_sec([c.id], apk, "0.0.6")
        adb = self.yamala(SahteAdbKurulum())

        sonuc = firmware.yukle(c)

        self.assertEqual((sonuc["onceki"], sonuc["yeni"]), ("0.0.5", "0.0.6"))
        self.assertTrue(sonuc["degisti"])
        kur = adb.komut("install")
        self.assertIsNotNone(kur)
        self.assertIn("-r", kur)
        self.assertEqual(kur[-1], apk)
        # Bağlantı açılıp kapatılır; cihazda asılı adb oturumu kalmaz.
        self.assertIsNotNone(adb.komut("connect"))
        self.assertIsNotNone(adb.komut("disconnect"))
        # Sürüm panelin okuma tarafıyla aynı yerden doğrulanır.
        self.assertIsNotNone(adb.komut("dumpsys"))

    def test_kurulum_hatasi_anlasilir_mesaja_donusur(self):
        _, c = self.kur()
        firmware.dosya_sec([c.id], imaj("bozuk.apk"))
        self.yamala(SahteAdbKurulum(
            install_cikti="Failure [INSTALL_FAILED_INVALID_APK]"))
        with self.assertRaises(DogrulamaHatasi) as t:
            firmware.yukle(c)
        self.assertIn("geçerli bir APK değil", str(t.exception))

    def test_surum_dusurme_ikinci_denemede_yapilir(self):
        """Sahada eski sürüme dönmek gerekebiliyor: -d ile yeniden denenir."""
        _, c = self.kur()
        firmware.dosya_sec([c.id], imaj("panel-0.0.4.apk"))

        class Dusurme(SahteAdbKurulum):
            def __init__(self):
                super().__init__(surumler=[DUMPSYS_YENI, DUMPSYS_ESKI])
                self.deneme = 0

            def __call__(self, args, **kwargs):
                if "install" in args:
                    self.deneme += 1
                    self.install_cikti = (
                        "Failure [INSTALL_FAILED_VERSION_DOWNGRADE]"
                        if self.deneme == 1 else "Success")
                return super().__call__(args, **kwargs)

        adb = self.yamala(Dusurme())
        sonuc = firmware.yukle(c)
        self.assertEqual(sonuc["yeni"], "0.0.5")
        kurulumlar = [c_ for c_ in adb.cagrilar if "install" in c_]
        self.assertEqual(len(kurulumlar), 2)
        self.assertNotIn("-d", kurulumlar[0])
        self.assertIn("-d", kurulumlar[1])

    def test_baska_paketin_apk_si_yakalanir(self):
        """Kurulum başarılı ama beklenen paket ortada yok."""
        _, c = self.kur()
        firmware.dosya_sec([c.id], imaj("baska.apk"))
        self.yamala(SahteAdbKurulum(surumler=[DUMPSYS_ESKI, ""]))
        with self.assertRaises(DogrulamaHatasi) as t:
            firmware.yukle(c)
        self.assertIn("sürümü okunamadı", str(t.exception))

    def test_hedef_surum_tutmazsa_hata(self):
        _, c = self.kur()
        firmware.dosya_sec([c.id], imaj("panel-0.0.9.apk"), "0.0.9")
        self.yamala(SahteAdbKurulum())
        with self.assertRaises(DogrulamaHatasi) as t:
            firmware.yukle(c)
        self.assertIn("0.0.6", str(t.exception))

    def test_adb_yoksa_uygulanmaz_hatasi(self):
        _, c = self.kur()
        firmware.dosya_sec([c.id], imaj("panel.apk"))

        def yok(*a, **k):
            raise FileNotFoundError("adb")

        self.yamala(yok)
        with self.assertRaises(UygulanmazHatasi):
            firmware.yukle(c)


class FirmwareUclari(ServisTesti):

    def kur(self, sayi=2):
        cihazlar = [{
            "Name": f"Intercom_{i}", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "Intercom", "Port": str(10 + i),
            "Status": {"NoError": True},
        } for i in range(1, sayi + 1)]
        # Kamera aynı sette: "gruba uygula" onu kapsamamalı.
        cihazlar.append({
            "Name": "Kamera_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Camera", "SubType": "", "Port": "20", "Status": {}})
        env = self.kur_harita(sahte.device_map(cihazlar))
        return env

    def test_grup_listesi_ve_secim_uctan_gorunur(self):
        env = self.kur()
        taban = self.servis_ac()
        cihazlar = env.tip_ile("Announcement")

        kod, y = self.cagir(taban, "/api/firmware?set=1&grup=Intercom")
        self.assertEqual(kod, 200)
        self.assertEqual(len(y["cihazlar"]), 2)
        self.assertTrue(all(c["yuklenebilir"] for c in y["cihazlar"]))
        self.assertEqual(y["seciliSayi"], 0)
        # Tarama yapılmadan sürüm uydurulmaz.
        self.assertEqual(y["cihazlar"][0]["mevcutSurum"], "")

        kod, y = self.cagir(taban, "/api/firmware/dosya", {
            "set": 1, "cihazlar": [cihazlar[0].id],
            "yol": imaj("intercom-1.2.6.bin"), "surum": "1.2.6"})
        self.assertEqual(kod, 200)
        self.assertEqual(y["seciliSayi"], 1)

        kod, y = self.cagir(taban, "/api/firmware?set=1&grup=Intercom")
        secili = {c["cihazId"]: c["dosya"] for c in y["cihazlar"]}
        self.assertTrue(secili[cihazlar[0].id]["secili"])
        self.assertEqual(secili[cihazlar[0].id]["ad"], "intercom-1.2.6.bin")
        self.assertFalse(secili[cihazlar[1].id]["secili"])

    def test_gruba_uygulamak_yalniz_o_grubu_kapsar(self):
        env = self.kur()
        taban = self.servis_ac()
        kod, y = self.cagir(taban, "/api/firmware/dosya", {
            "set": 1, "grup": "Intercom", "yol": imaj("ortak.bin")})
        self.assertEqual(kod, 200)
        self.assertEqual(y["cihazSayisi"], 2)
        # Kamera aynı sette ama Intercom grubunda değil; seçim ona gitmez.
        kamera = env.tip_ile("Camera")[0]
        self.assertFalse(firmware.secili_var(kamera.id))

    def test_yukleme_ucu_olmayan_gruba_dosya_atanmaz(self):
        self.kur()
        taban = self.servis_ac()
        kod, y = self.cagir(taban, "/api/firmware/dosya", {
            "set": 1, "grup": "Kamera", "yol": imaj("ortak.bin")})
        self.assertEqual(kod, 400)
        self.assertIn("yükleme tanımlı değil", y["hata"])

    def test_gecersiz_yol_400_doner(self):
        self.kur()
        taban = self.servis_ac()
        kod, y = self.cagir(taban, "/api/firmware/dosya", {
            "set": 1, "grup": "Intercom", "yol": "/yok/olmayan.bin"})
        self.assertEqual(kod, 400)
        self.assertIn("bulunamadı", y["hata"])

    def test_secim_yokken_yukleme_baslamaz(self):
        self.kur()
        taban = self.servis_ac()
        kod, y = self.cagir(taban, "/api/firmware/yukle",
                            {"set": 1, "grup": "Intercom"})
        self.assertEqual(kod, 400)
        self.assertIn("dosyası seçilmiş cihaz yok", y["hata"])
        self.assertEqual(isler.YONETICI.liste(), [])

    def test_yalniz_dosyasi_olan_cihaz_kuyruga_girer(self):
        env = self.kur()
        cihazlar = env.tip_ile("Announcement")
        with sahte.anons(yeni_surum="1.2.6") as an:
            ayar.ANONS_PORT = an.port
            taban = self.servis_ac()
            self.cagir(taban, "/api/firmware/dosya", {
                "set": 1, "cihazlar": [cihazlar[0].id],
                "yol": imaj("intercom-1.2.6.bin"), "surum": "1.2.6"})
            kod, y = self.cagir(taban, "/api/firmware/yukle",
                                {"set": 1, "grup": "Intercom"})
            self.assertEqual(kod, 200)
            is_ = self.isi_bekle(isler.YONETICI.bul(y["id"]), 40.0)

        satirlar = is_.dto()["satirlar"]
        self.assertEqual(len(satirlar), 1, "dosyasız cihaz kuyruğa girmemeli")
        self.assertEqual(satirlar[0]["durum"], "tamam")
        self.assertIn("intercom-1.2.6.bin", satirlar[0]["not"])

    def test_dosya_seciciden_atanir(self):
        """İmaj yolu istemciden gelmez; işletim sisteminin seçicisinden."""
        from core import dosya

        env = self.kur()
        cihazlar = env.tip_ile("Announcement")
        secilen = imaj("intercom-1.2.6.bin")
        cagri = {}

        def sahte_sec(baslik="", uzantilar=()):
            cagri.update(baslik=baslik, uzantilar=uzantilar)
            return secilen

        eski = dosya.sec
        dosya.sec = sahte_sec
        self.addCleanup(lambda: setattr(dosya, "sec", eski))

        taban = self.servis_ac()
        kod, y = self.cagir(taban, "/api/firmware/sec", {
            "set": 1, "cihazlar": [cihazlar[0].id], "surum": "1.2.6"})
        self.assertEqual(kod, 200)
        self.assertEqual(y["seciliSayi"], 1)
        self.assertEqual(cagri["uzantilar"], ("bin",))
        self.assertIn(cihazlar[0].ad, cagri["baslik"])
        d = firmware.secili_of(cihazlar[0].id)
        self.assertEqual((d["ad"], d["surum"]), ("intercom-1.2.6.bin", "1.2.6"))

    def test_seciciden_vazgecmek_secimi_bozmaz(self):
        from core import dosya

        env = self.kur()
        cihazlar = env.tip_ile("Announcement")
        firmware.dosya_sec([cihazlar[0].id], imaj("onceki.bin"), "1.0.0")

        eski = dosya.sec
        dosya.sec = lambda *a, **k: None          # kullanıcı vazgeçti
        self.addCleanup(lambda: setattr(dosya, "sec", eski))

        taban = self.servis_ac()
        kod, y = self.cagir(taban, "/api/firmware/sec",
                            {"set": 1, "cihazlar": [cihazlar[0].id]})
        self.assertEqual(kod, 200)
        self.assertTrue(y["iptal"])
        self.assertEqual(firmware.secili_of(cihazlar[0].id)["ad"], "onceki.bin")

    def test_secici_acilamazsa_hata_doner(self):
        from core import dosya

        self.kur()
        eski = dosya.sec

        def patlat(*a, **k):
            raise RuntimeError("Dosya seçici bulunamadı")

        dosya.sec = patlat
        self.addCleanup(lambda: setattr(dosya, "sec", eski))

        taban = self.servis_ac()
        kod, y = self.cagir(taban, "/api/firmware/sec",
                            {"set": 1, "grup": "Intercom"})
        self.assertEqual(kod, 500)
        self.assertIn("seçici", y["hata"])

    def test_hedef_surum_dosyaya_dokunmadan_degisir(self):
        env = self.kur()
        cihazlar = env.tip_ile("Announcement")
        firmware.dosya_sec([cihazlar[0].id], imaj("intercom-1.2.6.bin"), "1.2.6")
        taban = self.servis_ac()
        kod, _ = self.cagir(taban, "/api/firmware/surum", {
            "set": 1, "cihazlar": [cihazlar[0].id], "surum": "1.3.0"})
        self.assertEqual(kod, 200)
        d = firmware.secili_of(cihazlar[0].id)
        self.assertEqual((d["ad"], d["surum"]), ("intercom-1.2.6.bin", "1.3.0"))

    def test_yuklemeler_paralel_yurur(self):
        """Cihazlar birbirinden bağımsız; sırayla beklemek gereksiz.

        12 intercomluk bir sette sıralı koşu bütün bekleme sürelerini uç
        uca ekliyordu.
        """
        import threading
        import panel_api

        env = self.kur(sayi=6)
        cihazlar = env.tip_ile("Announcement")
        taban = self.servis_ac()
        self.cagir(taban, "/api/firmware/dosya", {
            "set": 1, "grup": "Intercom", "yol": imaj("ortak.bin")})

        kilit = threading.Lock()
        durum = {"anlik": 0, "enCok": 0}
        eski = firmware.yukle

        def yavas_yukle(cihaz, kimlik=None, **k):
            with kilit:
                durum["anlik"] += 1
                durum["enCok"] = max(durum["enCok"], durum["anlik"])
            time.sleep(0.25)
            with kilit:
                durum["anlik"] -= 1
            return {"onceki": "1.2.5", "yeni": "1.2.6", "degisti": True}

        firmware.yukle = yavas_yukle
        self.addCleanup(lambda: setattr(firmware, "yukle", eski))

        kod, y = self.cagir(taban, "/api/firmware/yukle",
                            {"set": 1, "grup": "Intercom"})
        self.assertEqual(kod, 200)
        is_ = self.isi_bekle(isler.YONETICI.bul(y["id"]), 30.0)

        self.assertEqual(durum["enCok"], ayar.FIRMWARE_WORKER,
                         "havuz genişliği kadar cihaz aynı anda yüklenmeli")
        satirlar = is_.dto()["satirlar"]
        self.assertEqual(len(satirlar), 6)
        self.assertTrue(all(s["durum"] == "tamam" for s in satirlar), satirlar)
        # Ama hepsi birden değil: yükleme cihazı karartıyor, sahadaki
        # kişi neyin kapandığını görebilmeli.
        self.assertLess(durum["enCok"], 6)
        self.assertIs(panel_api.firmware, firmware)

    def test_secim_silme_ucu(self):
        env = self.kur()
        cihazlar = env.tip_ile("Announcement")
        taban = self.servis_ac()
        self.cagir(taban, "/api/firmware/dosya", {
            "set": 1, "grup": "Intercom", "yol": imaj("ortak.bin")})
        kod, y = self.cagir(taban, "/api/firmware/sil",
                            {"set": 1, "cihazlar": [cihazlar[0].id]})
        self.assertEqual(kod, 200)
        self.assertEqual(y["seciliSayi"], 1)
        kod, y = self.cagir(taban, "/api/firmware/sil", {"hepsi": True})
        self.assertEqual(y["seciliSayi"], 0)
