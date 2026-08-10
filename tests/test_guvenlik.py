#!/usr/bin/env python3
"""API güvenliği ve parola sızıntısı denetimleri.

Kapsanan gereksinimler:
  9. `.env`, JSON ve diğer dosyalara parola yazılmaz.
 10. API cevapları ve kuyruk satırları parola içermez.
 17. DeviceMap dışından, istemcinin gönderdiği IP'ye bağlantı yapılmaz.
"""
from __future__ import annotations

import json
import secrets
import unittest

from core import ayar, isler, kimlik

from .ortak import ServisTesti
from . import sahte

# Parola her koşuda rastgele üretilir. Sabit yazılsaydı, "ağaçta bu metni
# ara" testi testin kendi kaynak dosyasında takılırdı — üstelik gerçek bir
# sızıntı ile test sabitini ayırt edemezdik.
PAROLA = "gecici-" + secrets.token_hex(12)


def _harita():
    return sahte.device_map([{
        "Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
        "Type": "Announcement", "SubType": "Intercom", "Port": "11",
        "PBXExtension": "2001", "PBXPassword": "2001",
        "Status": {"NoError": True},
    }], switch_ip="127.0.0.1")


class Guvenlik(ServisTesti):

    # ── 10 ────────────────────────────────────────────────────────────
    def test_10_api_cevaplarinda_parola_yok(self):
        env = self.kur_harita(_harita())
        with sahte.kyland(parola=PAROLA) as sw, sahte.anons() as an:
            self.switch_portu(sw.port)
            ayar.ANONS_PORT = an.port
            taban = self.servis_ac()

            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            self.isi_bekle(isler.YONETICI.bul(y["id"]))

            sw_id = env.switchler()[0].id
            kod, _ = self.cagir(taban, "/api/kimlik", {
                "set": 1, "cihazId": sw_id,
                "kullanici": "admin", "parola": PAROLA})
            self.assertEqual(kod, 200)

            yollar = [
                "/api/surum", "/api/proje?set=1", "/api/durum?set=1",
                "/api/cihazlar?set=1", "/api/kilit?set=1", "/api/isler",
                f"/api/is?id={y['id']}", f"/api/cihaz?set=1&id={sw_id}",
                "/api/ip/plan?set=1&grup=Intercom", "/api/firmware",
                "/api/kontrol?set=1",
                "/api/piscu?set=1", "/api/mqtt",
            ]
            for yol in yollar:
                kod, govde = self.cagir(taban, yol)
                metin = json.dumps(govde, ensure_ascii=False)
                self.assertNotIn(PAROLA, metin, f"{yol} parola sızdırdı")
                self.assertNotIn("gizli-parola-devicemap", metin,
                                 f"{yol} DeviceMap parolasını sızdırdı")
                self.assertNotIn("Authorization", metin)
                self.assertNotIn("Basic ", metin)
                for anahtar in ("password", "parola", "Password"):
                    self.assertNotIn(f'"{anahtar}"', metin, yol)

    def test_10b_kuyruk_satirlarinda_parola_yok(self):
        env = self.kur_harita(_harita())
        with sahte.kyland(parola=PAROLA) as sw, sahte.anons() as an:
            self.switch_portu(sw.port)
            ayar.ANONS_PORT = an.port
            taban = self.servis_ac()
            sw_id = env.switchler()[0].id
            self.cagir(taban, "/api/kimlik", {
                "set": 1, "cihazId": sw_id,
                "kullanici": "admin", "parola": PAROLA})
            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            self.isi_bekle(isler.YONETICI.bul(y["id"]))

            kod, tam = self.cagir(taban, f"/api/is?id={y['id']}")
            metin = json.dumps(tam, ensure_ascii=False)
            self.assertNotIn(PAROLA, metin)
            self.assertNotIn("Traceback", metin)
            for satir in tam["satirlar"]:
                # "dosya" yalnız bir bayrak: satırın açılabilir bir dosyayı
                # gösterip göstermediği. Dosyanın yolu ("yol") arayüze hiç
                # gitmez — dosyayı sunucu, iş kaydından okuyarak açar.
                #
                # "adimlar" satırın altındaki akordiyonu besler; içindeki
                # metinler de kullanıcıya gösterilebilir olmalı, çünkü aynı
                # yerden — betiğin çıktısından — geliyorlar.
                self.assertEqual(
                    set(satir) - {"cihazId", "ad", "ip", "yontem", "durum",
                                  "not", "dosya", "adimlar"},
                    set(), "kuyruk satırında beklenmeyen alan")
                self.assertNotIn("yol", satir)
                for adim in satir.get("adimlar", []):
                    self.assertEqual(set(adim), {"metin", "durum", "zaman"})
                    self.assertNotIn(PAROLA, adim["metin"])

    def test_10c_kimlik_ozeti_kullanici_adini_maskeler(self):
        kimlik.ver("d1", "127.0.0.1", "administrator", PAROLA)
        ozet = kimlik.ozet()
        metin = json.dumps(ozet)
        self.assertNotIn(PAROLA, metin)
        self.assertNotIn("administrator", metin)
        self.assertEqual(kimlik.maskele("admin"), "a***n")

    # ── 9 ─────────────────────────────────────────────────────────────
    def test_9_hicbir_dosyaya_parola_yazilmaz(self):
        """Tam akıştan sonra proje ağacında parola metni aranır."""
        env = self.kur_harita(_harita())
        with sahte.kyland(parola=PAROLA) as sw, sahte.anons() as an:
            self.switch_portu(sw.port)
            ayar.ANONS_PORT = an.port
            taban = self.servis_ac()
            sw_id = env.switchler()[0].id
            self.cagir(taban, "/api/kimlik", {
                "set": 1, "cihazId": sw_id, "kullanici": "admin",
                "parola": PAROLA, "grubaUygula": True})
            kod, y = self.cagir(taban, "/api/tarama", {"set": 1})
            self.isi_bekle(isler.YONETICI.bul(y["id"]))
            self.cagir(taban, "/api/konfig/hedef", {
                "set": 1, "cihazId": env.cihazlar[1].id,
                "alan": "sipDahili", "deger": "2001"})

        # Proje ağacındaki hiçbir dosyada parola geçmemeli
        atla = {".venv", ".git", "__pycache__", "node_modules"}
        bakilan = 0
        for yol in ayar.KOK.rglob("*"):
            if not yol.is_file() or any(p in atla for p in yol.parts):
                continue
            if yol.suffix in (".png", ".xlsx", ".svg", ".ico"):
                continue
            bakilan += 1
            try:
                metin = yol.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            self.assertNotIn(PAROLA, metin, f"{yol} parola içeriyor")
        self.assertGreater(bakilan, 10)

        # Geçici DeviceMap dizininde de yeni bir dosya oluşmamalı
        cevre = list(self.harita_yolu.parent.iterdir())
        self.assertEqual([p.name for p in cevre], ["DeviceMap.json"])

        # .env dosyası hiç oluşturulmamalı
        self.assertFalse((ayar.KOK / ".env").exists())

    def test_9b_kimlik_modulunde_dosya_yazma_yok(self):
        """core/kimlik.py kalıcı depoya dokunan hiçbir çağrı içermemeli."""
        kaynak = (ayar.KOK / "core" / "kimlik.py").read_text(encoding="utf-8")
        for yasak in ("open(", "write_text", "json.dump", "pickle",
                      "sqlite3", "keyring", "os.environ["):
            self.assertNotIn(yasak, kaynak,
                             f"kimlik.py '{yasak}' kullanmamalı")

    # ── 17 ────────────────────────────────────────────────────────────
    def test_17_istemcinin_gonderdigi_ip_kullanilmaz(self):
        """Gövdeye ip/host koymak hedefi değiştirmemeli."""
        env = self.kur_harita(_harita())
        with sahte.kyland(parola=PAROLA) as sw:
            self.switch_portu(sw.port)
            taban = self.servis_ac()
            sw_id = env.switchler()[0].id

            kod, y = self.cagir(taban, "/api/kimlik", {
                "set": 1, "cihazId": sw_id,
                "ip": "10.255.255.1",          # yok sayılmalı
                "type": "Camera",              # yok sayılmalı
                "kullanici": "admin", "parola": PAROLA})
            self.assertEqual(kod, 200)
            # Hedef DeviceMap'ten geldi: sahte switch isteği gördü
            self.assertGreater(sw.istek_sayisi, 0)
            self.assertEqual(y["cihaz"]["ip"], "127.0.0.1")

    def test_17b_bilinmeyen_cihaz_kimligi_reddedilir(self):
        self.kur_harita(_harita())
        taban = self.servis_ac()
        for govde in ({"set": 1, "cihazId": "yok-boyle-bir-id",
                       "kullanici": "a", "parola": "b"},
                      {"set": 1, "cihazId": "../../etc/passwd",
                       "kullanici": "a", "parola": "b"}):
            kod, y = self.cagir(taban, "/api/kimlik", govde)
            self.assertEqual(kod, 404, govde)
            self.assertIn("listesinde yok", y["hata"])

    def test_17c_gecersiz_set_numarasi_kabul_edilmez(self):
        self.kur_harita(_harita())
        taban = self.servis_ac()
        for kotu in (0, -3, 999, "abc", None, 1e9):
            kod, y = self.cagir(taban, f"/api/durum?set={kotu}")
            self.assertEqual(kod, 200)
            self.assertTrue(ayar.SET_MIN <= y["setNo"] <= ayar.SET_MAX)

    # ── genel API sertliği ────────────────────────────────────────────
    def test_statik_dosyada_dizin_disina_cikilamaz(self):
        self.kur_harita(_harita())
        taban = self.servis_ac()
        for yol in ("/css/../../panel_api.py",
                    "/js/../../DeviceMap.json",
                    "/css/%2e%2e%2f%2e%2e%2fapp.py",
                    "/js/....//....//app.py"):
            kod, _ = self.cagir(taban, yol)
            self.assertIn(kod, (400, 404), yol)

    def test_govde_boyutu_sinirli(self):
        self.kur_harita(_harita())
        taban = self.servis_ac()
        kod, y = self.cagir(taban, "/api/kimlik", {
            "set": 1, "cihazId": "sw1",
            "kullanici": "a" * 200, "parola": "b"})
        self.assertEqual(kod, 400)

        import urllib.error
        import urllib.request
        buyuk = b'{"set":1,"cihazId":"' + b"a" * (ayar.GOVDE_SINIRI + 10) + b'"}'
        istek = urllib.request.Request(taban + "/api/kimlik", data=buyuk,
                                       method="POST")
        try:
            with urllib.request.urlopen(istek, timeout=10) as y:
                self.fail("büyük gövde kabul edildi")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_cors_acilmaz(self):
        import urllib.request
        self.kur_harita(_harita())
        taban = self.servis_ac()
        with urllib.request.urlopen(taban + "/api/surum", timeout=10) as y:
            self.assertIsNone(y.headers.get("Access-Control-Allow-Origin"))

    def test_sunucu_yalniz_localhoste_baglanir(self):
        import panel_api
        with self.assertRaises(ValueError):
            panel_api.sunucu("0.0.0.0", 0)


if __name__ == "__main__":
    unittest.main()
