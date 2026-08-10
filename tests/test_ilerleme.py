#!/usr/bin/env python3
"""IP atama koşusunun ilerleme raporu.

Betiğin satır çıktısı kuyruğa olduğu gibi dökülüyordu: iki yüz satır,
yüzde baştan sona %0 ve kullanıcı hangi aşamada olduğunu göremiyor.
Buradaki testler çevirinin (core/ip_atama.Ilerleme) gerçek betik
çıktısıyla ne yaptığını sabitler.

Betik BİLEREK değiştirilmedi (bkz. docs/MIMARI §3); bu yüzden testin
girdisi betiğin gerçekten yazdığı biçimdir — aşağıdaki CIKTI sahada
alınmış bir koşu günlüğünden birebir kısaltılmıştır. İki ayrıntı bütün
davranışı belirliyor:

  · Betik doğrulamayı sona bırakır (varsayılan --defer-verify). Bu yüzden
    bir port bittiğinde "[OK] Port 11" YAZILMAZ; "yazıldı (reset
    doğrulandı)" yazar ve teyit sondaki özet tablosunda gelir.
  · Koşunun en başında plan da yazdırılır ("   port 11  ->  10.1.1.10").
    Bu satırlar port BAŞLANGICI değildir.
"""
from __future__ import annotations

import unittest

from core import ip_atama, isler


PLAN = [
    {"port": 11, "ad": "Intercom_1", "hedefIp": "10.1.1.10",
     "uygulanabilir": True},
    {"port": 12, "ad": "Intercom_2", "hedefIp": "10.1.1.11",
     "uygulanabilir": True},
    {"port": 13, "ad": "Intercom_3", "hedefIp": "10.1.1.12",
     "uygulanabilir": True},
    # Planda cihazı olmayan port: satırı hiç açılmamalı.
    {"port": 14, "ad": "—", "hedefIp": "—", "uygulanabilir": False},
]

# Sahadaki koşunun çıktısı (üç porta indirilmiş). Boşluklar dahil betiğin
# yazdığı biçim; kalıplar buna göre kuruldu.
CIKTI = """\
[Intercom] 11-13 — atama başlıyor
[Intercom] Fabrika adresi: 10.1.1.12
Set no    : 1
Switch    : 10.1.1.101
Portlar   : [11, 12, 13]
   port 11  ->  10.1.1.10      (10011001)
   port 12  ->  10.1.1.11      (10011002)
   port 13  ->  10.1.1.12      (10011003)
Fabrika IP: 10.1.1.12   (bu adreste cevap veren = yapılandırılmamış intercom)
Aday IP'ler: 10.1.1.12, 10.1.1.10, 10.1.1.11
ARP       : önbellek temizlenebiliyor
Temel tarama (aralıktaki portlar kapalı)...
    aralık dışında 0 cihaz açık
[1/3] Port 11 -> 10.1.1.10 (10011001)
    aralıktaki portlar kapatılıyor, 11 açılıyor...
    port bağlandı (6.6 sn) — cihaz aranıyor (en fazla 10 sn)...
    (fabrika IP'si — yapılandırılmamış cihaz)
    cihaz bulundu: 10.1.1.12  [MAC 5c:01:3b:53:2d:ab -> port 11]
    IP yazılıyor: 10.1.1.12 -> 10.1.1.10
    yazıldı (reset doğrulandı), IP kontrolü sona bırakıldı
[2/3] Port 12 -> 10.1.1.11 (10011002)
    aralıktaki portlar kapatılıyor, 12 açılıyor...
    [!] Port 45 sn'de bağlanmadı — kablo/cihaz kontrolü gerekebilir
    [!] Port 12: port bağlanmadı (link up olmadı)
[3/3] Port 13 -> 10.1.1.12 (10011003)
    aralıktaki portlar kapatılıyor, 13 açılıyor...
    port bağlandı (12.1 sn) — cihaz aranıyor (en fazla 10 sn)...
    cihaz bulundu: 10.1.1.12  [MAC 5c:01:3b:53:65:ff -> port 13]
    IP zaten doğru

=== Tur 2 — kalan portlar: [12]  (bekleme: boot 30s / doğrulama 60s) ===

[1/1] Port 12 -> 10.1.1.11 (10011002)
    aralıktaki portlar kapatılıyor, 12 açılıyor...
    port bağlandı (5.2 sn) — cihaz aranıyor (en fazla 15 sn)...
    cihaz bulundu: 10.1.1.12  [MAC 5c:01:3b:53:a4:73 -> port 12]
    IP yazılıyor: 10.1.1.12 -> 10.1.1.11
    yazıldı (reset doğrulandı), IP kontrolü sona bırakıldı

Aralıktaki tüm portlar tekrar açılıyor: [11, 12, 13]

Son doğrulama (15 sn'ye kadar tüm cihazların açılması bekleniyor)...

 port  hedef IP       durum
  --------------------------------------------
   11  10.1.1.10      OK
   12  10.1.1.11      OK
   13  10.1.1.12      EKSİK — cevap yok
"""

SATIRLAR = CIKTI.splitlines()


def _kur():
    is_ = isler.Is("ip", "IP atama · Test_SW", 1)
    return is_, ip_atama.Ilerleme(is_, PLAN)


def _satirlar(is_):
    return {s["cihazId"]: s for s in is_.satirlar()}


def _oynat(ilerleme, satirlar):
    for satir in satirlar:
        ilerleme.satir(satir)


def _kadar(isaret: str) -> list[str]:
    """Çıktının, verilen satır dahil oraya kadarki kısmı."""
    return SATIRLAR[:SATIRLAR.index(isaret) + 1]


class IlerlemeCevirisi(unittest.TestCase):

    def test_her_hedef_port_bir_satir(self):
        """Satır sayısı çıktı satırıyla değil, PORT sayısıyla belirlenir."""
        is_, _ = _kur()
        satir = _satirlar(is_)
        self.assertEqual(sorted(satir), ["p11", "p12", "p13"])
        self.assertNotIn("p14", satir)       # planda cihazı yok
        self.assertEqual(is_.sayilar()["toplam"], 3)
        self.assertEqual(is_.ilerleme(), 0.0)

    def test_plan_dokumu_portlari_baslatmaz(self):
        """Asıl arıza buydu: koşunun başındaki plan dökümü.

        Betik en başta "   port 11  ->  10.1.1.10" diye bütün planı
        yazıyor. Bu satırları port başlangıcı sayan kalıp, koşu daha ilk
        saniyesindeyken on iki portu birden "çalışıyor" gösteriyordu.
        Başlangıcın işareti betiğin sayacı: "[1/3] Port 11 -> ...".
        """
        is_, ilerleme = _kur()
        _oynat(ilerleme, _kadar("    aralık dışında 0 cihaz açık"))
        satir = _satirlar(is_)
        self.assertEqual([s["durum"] for s in satir.values()],
                         ["bekliyor"] * 3)
        self.assertEqual(is_.sayilar()["bekleyen"], 3)

    def test_ayni_anda_tek_port_calisir(self):
        """Koşu portları sırayla işliyor; ekran da öyle göstermeli."""
        is_, ilerleme = _kur()
        for satir in SATIRLAR:
            ilerleme.satir(satir)
            calisan = [s for s in _satirlar(is_).values()
                       if s["durum"] == "calisiyor"]
            self.assertLessEqual(len(calisan), 1, satir)

    def test_port_kosu_icinde_kapanir(self):
        """"yazıldı (reset doğrulandı)" portun bitiş işaretidir.

        Betik doğrulamayı sona bıraktığı için "[OK] Port 11" hiç
        yazılmıyor. Yalnız onu bekleyen sayaç, koşu boyunca hiçbir portu
        kapatmıyordu.
        """
        is_, ilerleme = _kur()
        _oynat(ilerleme, _kadar(
            "    yazıldı (reset doğrulandı), IP kontrolü sona bırakıldı"))
        self.assertEqual(_satirlar(is_)["p11"]["durum"], ip_atama.YAZILDI)

    def test_ip_zaten_dogruysa_port_kapanir(self):
        is_, ilerleme = _kur()
        _oynat(ilerleme, _kadar("    IP zaten doğru"))
        self.assertEqual(_satirlar(is_)["p13"]["durum"], ip_atama.YAZILDI)
        self.assertIn("zaten doğru", _satirlar(is_)["p13"]["not"])

    def test_son_tablo_son_sozu_soyler(self):
        """Turda hata alan port sonraki turda tamamlanmış olabilir; sona
        bırakılan doğrulama ise "yazıldı"yı hem onaylayabilir hem
        çürütebilir."""
        is_, ilerleme = _kur()
        _oynat(ilerleme, SATIRLAR)
        satir = _satirlar(is_)
        self.assertEqual(satir["p11"]["durum"], "tamam")
        self.assertEqual(satir["p12"]["durum"], "tamam")   # 2. turda düzeldi
        self.assertEqual(satir["p13"]["durum"], "hata")    # yazıldı ama yok
        self.assertIn("cevap yok", satir["p13"]["not"])

        say = is_.sayilar()
        self.assertEqual((say["toplam"], say["basarili"], say["hatali"]),
                         (3, 2, 1))

    def test_cihaz_bulunamayinca_hataya_duser(self):
        is_, ilerleme = _kur()
        _oynat(ilerleme, [
            "[1/3] Port 11 -> 10.1.1.10 (10011001)",
            "    aralıktaki portlar kapatılıyor, 11 açılıyor...",
            "    [!] Port 11: cihaz bulunamadı",
        ])
        satir = _satirlar(is_)["p11"]
        self.assertEqual(satir["durum"], "hata")
        self.assertEqual(satir["not"], "cihaz bulunamadı")
        self.assertEqual(ilerleme.hata_sayisi, 1)

    def test_saniye_sayisi_port_numarasi_sanilmaz(self):
        """`[!] Port 45 sn'de bağlanmadı` — 45 saniyedir, port değil."""
        is_, ilerleme = _kur()
        ilerleme.satir("    [!] Port 45 sn'de bağlanmadı — kablo/cihaz")
        self.assertNotIn("p45", _satirlar(is_))
        self.assertEqual(is_.sayilar()["toplam"], 3)

    def test_ayrinti_satirlari_yeni_satir_acmaz(self):
        """Betiğin ara satırları süren portun NOTU olur, ayrı satır değil."""
        is_, ilerleme = _kur()
        _oynat(ilerleme, _kadar("    IP yazılıyor: 10.1.1.12 -> 10.1.1.10"))
        satir = _satirlar(is_)
        self.assertEqual(len(satir), 3)
        self.assertEqual(satir["p11"]["durum"], "calisiyor")
        self.assertIn("IP yazılıyor", satir["p11"]["not"])

    def test_ham_cikti_gunluge_gider(self):
        """Satırlar kuyruktan çıkarıldı ama kaybolmadı."""
        toplanan = []
        is_ = isler.Is("ip", "IP atama · Test_SW", 1)
        ilerleme = ip_atama.Ilerleme(is_, PLAN, gunluk=toplanan.append)
        _oynat(ilerleme, SATIRLAR)
        self.assertEqual(len(toplanan), len(SATIRLAR))
        self.assertIn("   11  10.1.1.10      OK", toplanan)

    def test_dogrulanan_kosuda_ok_satiri_da_calisir(self):
        """--no-defer-verify ile koşulursa bitiş işareti "[OK] Port"tur."""
        is_, ilerleme = _kur()
        _oynat(ilerleme, [
            "[1/3] Port 11 -> 10.1.1.10 (10011001)",
            "    doğrulama: 10.1.1.10 bekleniyor (reset + en fazla 60 sn)...",
            "    [OK] Port 11 -> 10.1.1.10",
        ])
        self.assertEqual(_satirlar(is_)["p11"]["durum"], "tamam")


class Yuzde(unittest.TestCase):
    """Yüzde koşu boyunca ilerlemeli.

    Eski hesap "biten port / toplam port" idi. Portlar koşunun ortasında
    değil, sondaki özet tablosunda kapandığı için çubuk baştan sona %0,
    son saniyede %100 oluyordu. Yeni hesap aşama paylıdır (ASAMALAR).
    """

    def test_asama_paylari_bire_tamamlanir(self):
        self.assertAlmostEqual(sum(p for _a, _e, p in ip_atama.ASAMALAR), 1.0)

    def test_geri_gitmez_ve_araya_yayilir(self):
        is_, ilerleme = _kur()
        gorulen = []
        for satir in SATIRLAR:
            ilerleme.satir(satir)
            gorulen.append(is_.ilerleme())

        self.assertEqual(gorulen, sorted(gorulen))     # hiç geri gitmez
        # Çubuk üç dört yerde değil, koşu boyunca hareket eder.
        self.assertGreater(len(set(gorulen)), 10)

    def test_ilk_port_bitmeden_de_ilerler(self):
        """Tek bir port bir dakika sürebiliyor; çubuk port içinde de kımıldar."""
        is_, ilerleme = _kur()
        _oynat(ilerleme, _kadar("    aralık dışında 0 cihaz açık"))
        temel = is_.ilerleme()
        self.assertGreater(temel, 0.0)

        _oynat(ilerleme, [
            "[1/3] Port 11 -> 10.1.1.10 (10011001)",
            "    aralıktaki portlar kapatılıyor, 11 açılıyor...",
        ])
        acildi = is_.ilerleme()
        ilerleme.satir("    port bağlandı (6.6 sn) — cihaz aranıyor (en fazla 10 sn)...")
        araniyor = is_.ilerleme()
        ilerleme.satir("    cihaz bulundu: 10.1.1.12  [MAC ab -> port 11]")
        bulundu = is_.ilerleme()

        self.assertLess(temel, acildi)
        self.assertLess(acildi, araniyor)
        self.assertLess(araniyor, bulundu)

    def test_ilk_port_bitince_yuzde_belirgin_artar(self):
        is_, ilerleme = _kur()
        _oynat(ilerleme, _kadar(
            "    yazıldı (reset doğrulandı), IP kontrolü sona bırakıldı"))
        # Hazırlık + temel tarama + üç portun biri: yaklaşık %35.
        self.assertGreater(is_.ilerleme(), 0.30)
        self.assertLess(is_.ilerleme(), 0.45)

    def test_son_dogrulamaya_girerken_cogu_bitmis_olur(self):
        is_, ilerleme = _kur()
        _oynat(ilerleme, _kadar(
            "Son doğrulama (15 sn'ye kadar tüm cihazların açılması bekleniyor)..."))
        self.assertGreater(is_.ilerleme(), 0.80)
        self.assertLess(is_.ilerleme(), 1.0)

    def test_kosu_bitince_yuzde_dolar(self):
        is_, ilerleme = _kur()
        _oynat(ilerleme, SATIRLAR)
        ilerleme.bitir()
        self.assertEqual(is_.ilerleme(), 1.0)

    def test_yarida_kesilen_kosu_yuzde_yuz_gostermez(self):
        """İptal edilen koşuyu %100 göstermek yarım işi bitmiş gibi okutur."""
        is_, ilerleme = _kur()
        _oynat(ilerleme, _kadar(
            "    yazıldı (reset doğrulandı), IP kontrolü sona bırakıldı"))
        ilerleme.bitir()
        self.assertLess(is_.ilerleme(), 1.0)
        satir = _satirlar(is_)
        # Yazıldı ama doğrulanmadı: "tamam" demek yanlış olur.
        self.assertEqual(satir["p11"]["durum"], "uyari")
        self.assertEqual(satir["p12"]["durum"], "atlandi")


class Asama(unittest.TestCase):

    def test_asama_metni_kosuyu_izlemeye_yeter(self):
        is_, ilerleme = _kur()
        self.assertIn("Hazırlık", is_.asama)

        ilerleme.satir("Temel tarama (aralıktaki portlar kapalı)...")
        self.assertIn("Temel tarama", is_.asama)

        ilerleme.satir("[1/3] Port 11 -> 10.1.1.10 (10011001)")
        ilerleme.satir("    port bağlandı (6.6 sn) — cihaz aranıyor (en fazla 10 sn)...")
        self.assertIn("Port 11", is_.asama)
        self.assertIn("Cihaz aranıyor", is_.asama)
        self.assertIn("(0/3)", is_.asama)

        ilerleme.satir("=== Tur 2 — kalan portlar: [12] ===")
        self.assertIn("2. tur", is_.asama)

        ilerleme.satir("Aralıktaki tüm portlar tekrar açılıyor: [11, 12, 13]")
        self.assertIn("geri açılıyor", is_.asama)

        ilerleme.satir("Son doğrulama (15 sn'ye kadar bekleniyor)...")
        self.assertIn("Son doğrulama", is_.asama)

        ilerleme.bitir()
        self.assertEqual(is_.asama, "")

    def test_asama_geri_gitmez(self):
        """"Tur 2" koşuyu başa almaz — son doğrulamadan sonra hiç almamalı."""
        is_, ilerleme = _kur()
        ilerleme.satir("Son doğrulama (15 sn'ye kadar bekleniyor)...")
        onceki = is_.ilerleme()
        ilerleme.satir("Temel tarama (aralıktaki portlar kapalı)...")
        self.assertIn("Son doğrulama", is_.asama)
        self.assertGreaterEqual(is_.ilerleme(), onceki)


class Adimlar(unittest.TestCase):
    """Satırın altındaki akordiyon: portun kendi geçmişi."""

    def _adim(self, is_, anahtar):
        return [a["metin"] for a in _satirlar(is_)[anahtar]["adimlar"]]

    def test_port_adimlari_birikir(self):
        is_, ilerleme = _kur()
        _oynat(ilerleme, _kadar(
            "    yazıldı (reset doğrulandı), IP kontrolü sona bırakıldı"))
        adim = self._adim(is_, "p11")
        self.assertIn("aralıktaki portlar kapatılıyor, 11 açılıyor...", adim)
        self.assertIn("cihaz bulundu: 10.1.1.12  [MAC 5c:01:3b:53:2d:ab -> port 11]",
                      adim)
        self.assertIn("IP yazılıyor: 10.1.1.12 -> 10.1.1.10", adim)
        self.assertEqual(adim[-1], "IP yazıldı, son doğrulama bekleniyor")

    def test_adimlar_baska_porta_karismaz(self):
        is_, ilerleme = _kur()
        _oynat(ilerleme, SATIRLAR)
        for anahtar in ("p11", "p12", "p13"):
            self.assertTrue(self._adim(is_, anahtar))
        self.assertNotIn("aralıktaki portlar kapatılıyor, 11 açılıyor...",
                         self._adim(is_, "p12"))

    def test_ikinci_turda_ilk_turun_adimlari_durur(self):
        """Port neden ilk turda düştü sorusunun cevabı burada."""
        is_, ilerleme = _kur()
        _oynat(ilerleme, SATIRLAR)
        adim = self._adim(is_, "p12")
        self.assertIn("port bağlanmadı (link up olmadı)", adim)
        self.assertIn("10.1.1.11 doğrulandı", adim)

    def test_hata_adimi_isaretlenir(self):
        is_, ilerleme = _kur()
        _oynat(ilerleme, SATIRLAR)
        durumlar = {a["metin"]: a["durum"]
                    for a in _satirlar(is_)["p12"]["adimlar"]}
        self.assertEqual(durumlar["port bağlanmadı (link up olmadı)"], "hata")
        self.assertEqual(
            durumlar["[!] Port 45 sn'de bağlanmadı — kablo/cihaz kontrolü gerekebilir"],
            "uyari")

    def test_adim_sayisi_sinirli(self):
        """Adımlar açık işin her yoklamasında arayüze gidiyor."""
        is_, _ = _kur()
        for i in range(isler.ADIM_SINIRI + 20):
            is_.adim_ekle("p11", f"adım {i}")
        adim = _satirlar(is_)["p11"]["adimlar"]
        self.assertEqual(len(adim), isler.ADIM_SINIRI)
        self.assertEqual(adim[-1]["metin"], f"adım {isler.ADIM_SINIRI + 19}")


if __name__ == "__main__":
    unittest.main()
