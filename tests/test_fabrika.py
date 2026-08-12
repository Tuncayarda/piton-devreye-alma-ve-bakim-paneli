#!/usr/bin/env python3
"""Cihazları fabrika adresinde toplama (core/ip_atama.fabrikaya_dondur).

Sahadaki iki durum bu akışı kilitlemişti; testler ikisini de sabitler:

  · Cihaz DeviceMap'teki adresinde DEĞİL. İşlem bir kez çalıştıktan sonra
    cihazların çoğu zaten fabrika adresindedir; eski adreslerinde kimse
    cevap vermez. Bu bir başarısızlık değildir.
  · İKİ cihaz aynı adreste (arp-scan'de "DUP: 2"). Tek turda o adrese
    yazılan istek yalnız birine ulaşır; ikincisi ancak adres boşalınca
    görünür. Bu yüzden akış tur tur yürür.

Ağ, betiğin (betikler/intercom_ip_assign.py) yerine geçen sahte bir
modülle taklit edilir: gerçek işlevlerin sözleşmesi neyse o — probe_all
cevap veren adresleri, write_ip cihazı taşımayı, host_mac adreste o an
hangi cihazın durduğunu bildirir.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from core import ip_atama, isler, kimlik, switch_okuma

from .ortak import PanelTesti
from . import sahte


def _harita(sayi: int = 3) -> dict:
    """11..(10+sayi) portlarında intercomlar; IP'leri 10.1.1.10, .11, ...

    Dahili numaralar sahadaki gibi porta göre sıralı (2001, 2002, …):
    cihaz kendi dahilisini bildirdiği için satır eşlemesi buradan çıkıyor.
    """
    return sahte.device_map([{
        "Name": f"Intercom_{i}", "IP": f"10.1.1.{9 + i}", "IsActive": True,
        "Type": "Announcement", "SubType": "Intercom", "Port": str(10 + i),
        "PBXExtension": f"200{i}" if i < 10 else f"20{i}",
        "Status": {"NoError": True},
    } for i in range(1, sayi + 1)], switch_ip="10.1.1.101")


class SahteAg:
    """Betiğin ağ işlevlerinin yerine geçen küçük bir dünya.

    `yerlesim`: {ip: [mac, ...]} — aynı adreste birden çok cihaz olabilir,
    sahadaki çakışma tam olarak bu. Adrese giden istek listenin BAŞINDAKİ
    cihaza ulaşır; o taşınınca arkasındaki görünür hale gelir.
    """

    def __init__(self, yerlesim: dict[str, list[str]], sagir: set | None = None,
                 gizli: dict[str, int] | None = None):
        self.yerlesim = {ip: list(m) for ip, m in yerlesim.items()}
        # Yazma isteğini alıp adresinde kalan cihazlar (yazma işlenmedi).
        self.sagir = set(sagir or ())
        # {adres: kaç yoklama boyunca görünmeyecek} — bayat ARP kaydının
        # karşılığı: adreste cihaz var ama işletim sistemi taşınmış bir
        # MAC'e sorduğu için cevap gelmiyor.
        self.gizli = dict(gizli or {})
        self.yazmalar: list[tuple[str, str]] = []
        # Çağrı sırası: "yoklama" mı önce geldi, "arp" mı (bkz.
        # test_once_yoklanir_sonra_arp_temizlenir).
        self.izlem: list[str] = []

    # ---- betiğin sözleşmesi ----
    def read_settings(self, ip, cfg):
        if self.gizli.get(ip, 0) > 0:
            return None
        kuyruk = self.yerlesim.get(ip)
        if kuyruk:
            # Gerçek cihaz gibi: kendi dahilisini de bildirir. Sahte ağda
            # cihazın kimliği ile dahilisi aynı dizedir.
            return {"netmask": "255.255.0.0", "gateway": "10.1.1.101",
                    "ip": ip, "pbxExtension": kuyruk[0]}
        return None

    def probe_all(self, adaylar, cfg):
        self.izlem.append("yoklama")
        bulunan = {ip: s for ip, s in
                   ((ip, self.read_settings(ip, cfg)) for ip in adaylar)
                   if s is not None}
        # Her yoklama, gizli adresi görünürlüğe bir adım yaklaştırır.
        for ip, kalan in list(self.gizli.items()):
            self.gizli[ip] = max(0, kalan - 1)
        return bulunan

    def write_ip(self, ip, settings, yeni_ip, cfg):
        self.yazmalar.append((ip, yeni_ip))
        kuyruk = self.yerlesim.get(ip) or []
        if not kuyruk:
            raise RuntimeError("adreste cihaz yok")
        mac = kuyruk[0]
        if mac in self.sagir:
            return
        kuyruk.pop(0)
        self.yerlesim.setdefault(yeni_ip, []).append(mac)

    def arp_unut(self, ipler, cfg=None):
        self.izlem.append("arp")
        return True

    def host_mac(self, ip):
        kuyruk = self.yerlesim.get(ip) or []
        return kuyruk[0] if kuyruk else None

    def modul(self):
        return SimpleNamespace(
            read_settings=self.read_settings, probe_all=self.probe_all,
            write_ip=self.write_ip, arp_unut=self.arp_unut,
            host_mac=self.host_mac)


class FabrikayaDondurme(PanelTesti):

    def kur(self, yerlesim, sagir=None, sayi=3, arp=True, gizli=None):
        """Sahte ağı kurar.

        `arp`: ARP önbelleği temizlenebiliyor mu. Yetki varsa cevap
        vermeyen adres gerçekten boştur; yoksa akış bekleyip tekrar dener
        (bkz. FABRIKA_BOS_TUR).
        """
        env = self.kur_harita(_harita(sayi))
        ag = SahteAg(yerlesim, sagir, gizli)
        self.ag = ag
        for yama in (mock.patch.object(ip_atama.betik, "intercom_ip_assign",
                                       ag.modul),
                     mock.patch.object(ip_atama, "arp_yetkisi", lambda: arp),
                     # Beklemek testte anlamsız: sahte ağ anında cevap
                     # veriyor, ARP kaydı da dönmüyor.
                     mock.patch.object(ip_atama, "FABRIKA_RESET_BEKLEME", 0.0),
                     mock.patch.object(ip_atama, "FABRIKA_TUR_ARASI", 0.0),
                     mock.patch.object(ip_atama, "FABRIKA_TUR_ARASI_YETKILI",
                                       0.0),
                     mock.patch.object(ip_atama, "FABRIKA_YOKLAMA_ARASI", 0.0),
                     mock.patch.object(ip_atama, "HARITA_TUR_ARASI", 0.0)):
            yama.start()
            self.addCleanup(yama.stop)
        return env

    def calistir(self, env, portlar=(11, 12, 13), iptal=None):
        is_ = isler.Is("ipfab", "Fabrika IP'sine döndür", 1)
        ozet = ip_atama.fabrikaya_dondur(
            env, env.switchler()[0].id, list(portlar), ["Intercom"], is_,
            ayarlar={"fabrikaIp": "10.1.1.12"}, iptal=iptal)
        return is_, ozet

    @staticmethod
    def satirlar(is_):
        return {s["cihazId"]: s for s in is_.satirlar()}

    # ── olağan akış ───────────────────────────────────────────────────
    def test_cihazlar_kendi_adreslerinden_toplanir(self):
        env = self.kur({"10.1.1.10": ["a"], "10.1.1.11": ["b"],
                        "10.1.1.12": ["c"]})
        is_, ozet = self.calistir(env)

        self.assertEqual(self.ag.yerlesim["10.1.1.12"], ["c", "a", "b"])
        self.assertEqual(ozet["yazilan"], 2)
        self.assertEqual(ozet["hatali"], 0)
        satir = self.satirlar(is_)
        self.assertEqual(satir["p11"]["durum"], "tamam")
        self.assertEqual(satir["p12"]["durum"], "tamam")
        # 13. portun DeviceMap adresi zaten fabrika adresi: yazacak bir şey
        # yok ama satır eksik de kalmamalı.
        self.assertEqual(satir["p13"]["durum"], "tamam")
        self.assertEqual(is_.ilerleme(), 1.0)

    def test_yuzde_is_bitmeden_ilerler(self):
        """Eski akışta çubuk baştan sona %0 kalıyordu."""
        env = self.kur({"10.1.1.10": ["a"], "10.1.1.11": ["b"]})
        oranlar = []
        gercek = isler.Is.ilerleme_yaz

        def izle(self_, oran):
            oranlar.append(oran)
            gercek(self_, oran)

        with mock.patch.object(isler.Is, "ilerleme_yaz", izle):
            is_, _ = self.calistir(env)
        ara = [o for o in oranlar if 0.0 < o < 1.0]
        self.assertTrue(ara, "iş sürerken hiç ara oran yazılmadı")
        self.assertEqual(is_.ilerleme(), 1.0)
        self.assertEqual(is_.asama, "")

    # ── aynı adreste iki cihaz ────────────────────────────────────────
    def test_ayni_adresteki_iki_cihaz_da_toplanir(self):
        """Sahadaki hata: 10.1.1.14'te iki cihaz kalıyor ve orada kalıyordu.

        Tek tur yetmez; adres boşaldıktan sonra ikinci cihaz görünür.
        """
        env = self.kur({"10.1.1.10": ["a", "b"]})
        is_, ozet = self.calistir(env)

        self.assertEqual(self.ag.yerlesim.get("10.1.1.10"), [])
        self.assertEqual(self.ag.yerlesim["10.1.1.12"], ["a", "b"])
        self.assertEqual(ozet["yazilan"], 2)
        self.assertEqual(ozet["hatali"], 0)

    def test_bos_tekrarlar_tur_saymaz(self):
        """Aşama metnindeki tur, CİHAZ BULUNAN turdur.

        Cihaz bulunmayan tekrarlar da tur sayılınca, iki cihazlık bir
        çakışmada kullanıcı "8. tur" görüyor ve işin uzadığını sanıyordu;
        oysa iş ikinci turda bitmişti.
        """
        env = self.kur({"10.1.1.10": ["a", "b"]})
        asamalar = []
        gercek = isler.Is.asama_yaz

        def izle(self_, metin):
            asamalar.append(metin)
            gercek(self_, metin)

        with mock.patch.object(isler.Is, "asama_yaz", izle):
            self.calistir(env, portlar=(11,))

        self.assertTrue(any("2. tur" in m for m in asamalar))
        self.assertFalse([m for m in asamalar if "3. tur" in m],
                         "cihaz bulunmayan tekrar tur saymamalı")
        self.assertTrue(any("yeniden bakılıyor" in m for m in asamalar))

    def test_ikinci_cihaz_mac_ile_kendi_satirina_yazilir(self):
        """Switch kimliği varsa bulunan cihaz hangi porttaysa o satıra."""
        env = self.kur({"10.1.1.10": ["a", "b"]})
        sw = env.switchler()[0]
        kimlik.ver(sw.id, sw.ip, "admin", "p", grup="switch")
        with mock.patch.object(switch_okuma, "mac_tablosu",
                               lambda *a, **k: {"a": 11, "b": 12}):
            is_, ozet = self.calistir(env)

        satir = self.satirlar(is_)
        self.assertEqual(satir["p11"]["durum"], "tamam")
        # İkinci cihaz 10.1.1.10'da bulundu ama MAC'i port 12'yi gösteriyor.
        self.assertEqual(satir["p12"]["durum"], "tamam")
        self.assertIn("10.1.1.10", satir["p12"]["not"])
        self.assertEqual(ozet["yazilan"], 2)

    def test_cihaz_dahilisiyle_kendi_satirina_yazilir(self):
        """Sahadaki durum: 10.1.1.13'te oturan cihaz port 22'nin cihazıydı.

        Cihaz kendi dahilisini bildirdiği için doğru satır switch kimliği
        ya da ARP olmadan bulunur.
        """
        env = self.kur({"10.1.1.10": ["2004"]}, sayi=4)
        is_, ozet = self.calistir(env, portlar=(11, 12, 13, 14))

        satir = self.satirlar(is_)
        # 10.1.1.10 DeviceMap'te port 11'in adresi ama oradaki cihaz
        # port 14'ün cihazı (dahili 2004).
        self.assertEqual(satir["p14"]["durum"], "tamam")
        self.assertIn("dahili 2004", satir["p14"]["not"])
        self.assertEqual(satir["p11"]["durum"], "atlandi")
        self.assertEqual(ozet["yazilan"], 1)

    def test_secili_portlarin_disindaki_cihaza_dokunulmaz(self):
        """MAC başka bir portu gösteriyorsa o cihaz bu işin konusu değil."""
        env = self.kur({"10.1.1.10": ["x"]})
        sw = env.switchler()[0]
        kimlik.ver(sw.id, sw.ip, "admin", "p", grup="switch")
        with mock.patch.object(switch_okuma, "mac_tablosu",
                               lambda *a, **k: {"x": 20}):
            _is, ozet = self.calistir(env, portlar=(11,))

        self.assertEqual(self.ag.yazmalar, [])
        self.assertEqual(ozet["yazilan"], 0)

    # ── cevap vermeyen adresler ───────────────────────────────────────
    def test_adresinde_cevap_yoksa_hata_degil(self):
        """İkinci çalıştırmada cihazlar zaten fabrika adresindedir."""
        env = self.kur({"10.1.1.12": ["a", "b", "c"]})
        is_, ozet = self.calistir(env)

        self.assertEqual(ozet["hatali"], 0)
        self.assertEqual(ozet["yazilan"], 0)
        self.assertTrue(ozet["fabrikaCevap"])
        satir = self.satirlar(is_)
        self.assertEqual(satir["p11"]["durum"], "atlandi")
        self.assertIn("zaten", satir["p11"]["not"])
        # Fabrika adresinde cevap var: iş kırmızıya boyanmaz.
        import panel_api
        self.assertIsNone(panel_api._ip_fabrika_hatasi(ozet))

    def test_hicbir_yerde_cevap_yoksa_is_hata_verir(self):
        env = self.kur({})
        _is, ozet = self.calistir(env)

        self.assertFalse(ozet["fabrikaCevap"])
        import panel_api
        self.assertIn("Hiçbir cihaz bulunamadı",
                      panel_api._ip_fabrika_hatasi(ozet))

    # ── ARP önbelleği temizlenemiyorken ───────────────────────────────
    def test_ilk_yoklamada_gorunmeyen_cihaz_bulunur(self):
        """Tek yoklama "burada kimse yok" demeye yetmez.

        Sahada ölçüldü: çözülmüş adres 0.01 sn'de cevap veriyor, ARP kaydı
        yeni silinmiş adres ise yoklamanın zaman aşımı boyunca sessiz
        kalabiliyor. Koşu her turda kaydı sildiği için bu, YETKİ VARKEN de
        oluyor — eski akış tam burada bütün cihazları "cevap yok" sayıp
        hiçbir şey yapmadan bitiyordu.
        """
        # Yetki varken tekrar daha az (temizlik gerçekten çalışıyor),
        # yetki yokken daha çok: ikisinde de ilk yoklama son söz değil.
        for arp, gizli in ((True, 2), (False, 4)):
            with self.subTest(arp=arp):
                env = self.kur({"10.1.1.10": ["a"]}, arp=arp,
                               gizli={"10.1.1.10": gizli})
                _is, ozet = self.calistir(env, portlar=(11,))

                self.assertEqual(ozet["yazilan"], 1)
                self.assertEqual(self.ag.yerlesim["10.1.1.12"], ["a"])

    def test_once_yoklanir_sonra_arp_temizlenir(self):
        """ARP temizliği yoklamadan ÖNCE yapılmaz.

        Kaydı silmek adresi yeniden çözülmeye zorluyor ve çözümleme
        yoklamanın zaman aşımından uzun sürebiliyor. Turun başında bütün
        adayların kaydını silmek, sahada cihazların hepsini birden "cevap
        yok" yapan şeydi. Kayıt ancak cevap gelmediğinde temizlenir.
        """
        env = self.kur({"10.1.1.10": ["a"]})
        self.calistir(env, portlar=(11,))

        self.assertEqual(self.ag.izlem[0], "yoklama",
                         "ilk iş yoklama olmalı, ARP temizliği değil")

    def test_gorunmeyen_cihaz_sonsuza_kadar_beklenmez(self):
        """Tekrar denemenin de bir sonu var: iş takılıp kalmaz."""
        env = self.kur({"10.1.1.10": ["a"]}, gizli={"10.1.1.10": 99})
        _is, ozet = self.calistir(env, portlar=(11,))

        self.assertEqual(ozet["yazilan"], 0)
        self.assertEqual(ozet["atlanan"], 1)

    def test_arp_yetkisi_yokken_ozet_kullaniciyi_uyarir(self):
        """'Cevap yok' sonucu yetkisizken kesin değildir; öyle de denmez."""
        env = self.kur({"10.1.1.12": ["a"]}, arp=False)
        _is, ozet = self.calistir(env, portlar=(11,))

        self.assertFalse(ozet["arpTemizlik"])
        import panel_api
        self.assertIn("yönetici/sudo",
                      panel_api._ip_fabrika_hatasi(ozet))

    def test_yazma_islenmezse_satir_hata_olur(self):
        """Cihaz isteği alıp eski adresinde kalıyorsa bu bir hatadır."""
        env = self.kur({"10.1.1.10": ["a"]}, sagir={"a"})
        is_, ozet = self.calistir(env, portlar=(11,))

        self.assertEqual(ozet["hatali"], 1)
        self.assertEqual(self.satirlar(is_)["p11"]["durum"], "hata")
        import panel_api
        self.assertIn("döndürülemedi", panel_api._ip_fabrika_hatasi(ozet))

    # ── durdurma ──────────────────────────────────────────────────────
    def test_durdurulan_is_yuzde_doldurmaz(self):
        env = self.kur({"10.1.1.10": ["a"], "10.1.1.11": ["b"]})
        is_, ozet = self.calistir(env, iptal=lambda: True)

        self.assertTrue(ozet["durduruldu"])
        self.assertEqual(self.ag.yazmalar, [])
        self.assertLess(is_.ilerleme(), 1.0)
        self.assertEqual(self.satirlar(is_)["p11"]["durum"], "atlandi")


class KalicilikSecenegi(unittest.TestCase):
    """"Yazıldı" ile "kalıcı yazıldı" aynı şey değil.

    Cihaz ayarı yalnız belleğine almış olabilir ve ilk güç kesintisinde
    eski adresine döner. Betiğin kontrolü var ama koşuyu uzattığı için
    varsayılan kapalı; arayüzden açılabiliyor.
    """

    def _argv(self, kalicilik: bool) -> list[str]:
        yakalanan = {}

        def calistir(_mod, argv, _satir, _iptal=None):
            yakalanan["argv"] = argv
            return 0

        with (mock.patch.object(ip_atama.betik, "intercom_ip_assign",
                                lambda: SimpleNamespace(main=lambda: 0)),
              mock.patch.object(ip_atama, "_betigi_calistir", calistir)):
            env = SimpleNamespace(set_no=1, kaynak="DeviceMap.json")
            sw = SimpleNamespace(ip="10.1.1.101")
            ip_atama._intercom_kosu(env, sw, [11], ("admin", "p"),
                                    lambda _s: None, {"kalicilik": kalicilik})
        return yakalanan["argv"]

    def test_varsayilan_kapali(self):
        self.assertIn("--no-persist-check", self._argv(False))

    def test_acikken_betige_birakilir(self):
        self.assertNotIn("--no-persist-check", self._argv(True))


class KimlikDogrulama(FabrikayaDondurme):
    """Koşudan sonra: hedef adreste DOĞRU cihaz mı var?

    Betik cihazı uptime tahminiyle seçiyor ve kim olduğuna bakmıyor; sahada
    bir hedef adreste üç cihaz toplandı, bir cihaz da başka bir portun
    adresine yazılmıştı. Cihaz kendi dahilisini bildirdiği için bu, koşudan
    sonra kesin olarak denetlenebiliyor.
    """

    def dogrula(self, env, portlar=(11, 12, 13), **kw):
        return ip_atama.kimlik_dogrula(
            env, env.switchler()[0].id, list(portlar), ["Intercom"],
            ayarlar={"fabrikaIp": "10.1.1.12"}, **kw)

    @staticmethod
    def satir(sonuc, port):
        return next(s for s in sonuc["satirlar"] if s["port"] == port)

    def test_dogru_cihaz_dogru_adreste(self):
        env = self.kur({"10.1.1.10": ["2001"], "10.1.1.11": ["2002"]}, sayi=3)
        sonuc = self.dogrula(env, tur=1)

        self.assertEqual(self.satir(sonuc, 11)["durum"], "dogru")
        self.assertEqual(self.satir(sonuc, 12)["durum"], "dogru")
        self.assertEqual(sonuc["sayilar"]["dogru"], 2)

    def test_yanlis_cihaza_yazilmissa_yakalanir(self):
        """Koşunun 'tamamlandı' dediği ama karıştırdığı durum."""
        # Port 11'in adresinde port 13'ün cihazı duruyor.
        env = self.kur({"10.1.1.10": ["2003"]}, sayi=3)
        sonuc = self.dogrula(env, tur=1)

        s = self.satir(sonuc, 11)
        self.assertEqual(s["durum"], "yanlis")
        self.assertEqual(s["beklenenDahili"], "2001")
        self.assertEqual(s["bulunan"][0]["ad"], "Intercom_3")
        self.assertEqual(sonuc["sayilar"]["yanlis"], 1)

        import panel_api
        self.assertIn("BAŞKA cihaz", panel_api._kimlik_hatasi(sonuc["sayilar"]))

    def test_ayni_adreste_iki_cihaz_cakisma(self):
        env = self.kur({"10.1.1.10": ["2001", "2002"]}, sayi=3)
        ag = self.ag

        def sirala(*_a, **_k):
            kuyruk = ag.yerlesim.get("10.1.1.10") or []
            if len(kuyruk) > 1:
                kuyruk.append(kuyruk.pop(0))
            return True

        with mock.patch.object(ag, "arp_unut", sirala):
            sonuc = self.dogrula(env, tur=2)

        self.assertEqual(self.satir(sonuc, 11)["durum"], "cakisma")

    def test_cevap_vermeyen_adres_yanlis_sayilmaz(self):
        """Cevapsızlık ayrı bir durum: koşu zaten onu bildiriyor."""
        env = self.kur({}, sayi=3)
        sonuc = self.dogrula(env, tur=1)

        self.assertEqual(sonuc["sayilar"]["cevapsiz"], 3)
        self.assertEqual(sonuc["sayilar"]["yanlis"], 0)

    def test_kimlik_denetimi_hicbir_sey_yazmaz(self):
        env = self.kur({"10.1.1.10": ["2003"]}, sayi=3)
        self.dogrula(env, tur=2)

        self.assertEqual(self.ag.yazmalar, [])


class AdresHaritasi(FabrikayaDondurme):
    """Tanı ekranının verisi: hangi adreste hangi cihaz var.

    Sahada bu soru elle `arp-scan` ile ve yalnız MAC düzeyinde
    cevaplanıyordu; cihazın kendi dahilisi sayesinde panel "bu adresteki
    cihaz aslında şu portun cihazı" diyebiliyor.
    """

    def harita(self, env, **kw):
        return ip_atama.adres_haritasi(
            env, env.switchler()[0].id, ["Intercom"],
            ayarlar={"fabrikaIp": "10.1.1.12"}, **kw)

    @staticmethod
    def satir(h, ip):
        return next(s for s in h["satirlar"] if s["ip"] == ip)

    def test_cihaz_kendi_adresindeyse_yerinde(self):
        env = self.kur({"10.1.1.10": ["2001"]}, sayi=3)
        h = self.harita(env, tur=1)

        s = self.satir(h, "10.1.1.10")
        self.assertEqual(s["durum"], "yerinde")
        self.assertEqual(s["bulunan"][0]["port"], 11)
        self.assertEqual(self.satir(h, "10.1.1.11")["durum"], "bos")

    def test_baska_cihazin_adresindeki_cihaz_isaretlenir(self):
        """Sahadaki tablo: 10.1.1.13'te port 22'nin cihazı oturuyordu."""
        env = self.kur({"10.1.1.10": ["2003"]}, sayi=3)
        h = self.harita(env, tur=1)

        s = self.satir(h, "10.1.1.10")
        self.assertEqual(s["durum"], "yabanci")
        self.assertEqual(s["beklenenPort"], 11)        # adres port 11'in
        self.assertEqual(s["bulunan"][0]["port"], 13)  # oradaki cihaz 13'ün

    def test_ayni_adresteki_iki_cihaz_cakisma_olarak_gorunur(self):
        """Tek yoklama çakışmayı göstermez; tur tur bakılır."""
        env = self.kur({"10.1.1.10": ["2001", "2002"]}, sayi=3)
        # Sahte ağda adrese giden istek listenin başındakine ulaşır; ikinci
        # cihaz ancak sıra değişince görünür (gerçekte ARP kaydının dönmesi).
        ag = self.ag

        def sirala(*_a, **_k):
            kuyruk = ag.yerlesim.get("10.1.1.10") or []
            kuyruk.append(kuyruk.pop(0)) if len(kuyruk) > 1 else None
            return True

        with mock.patch.object(ag, "arp_unut", sirala):
            h = self.harita(env, tur=2)

        s = self.satir(h, "10.1.1.10")
        self.assertEqual(s["durum"], "cakisma")
        self.assertEqual([b["dahili"] for b in s["bulunan"]], ["2001", "2002"])
        self.assertEqual(h["sayilar"]["cakisma"], 1)

    def test_fabrika_adresi_her_zaman_listede(self):
        """Cihazların toplandığı adres haritanın ilk sorusu."""
        env = self.kur({"10.1.1.12": ["2002"]}, sayi=3)
        h = self.harita(env, tur=1)

        s = self.satir(h, "10.1.1.12")
        self.assertTrue(s["fabrikaMi"])
        # Fabrika adresinde kimin durduğu "yanlış" değildir.
        self.assertEqual(s["durum"], "yerinde")
        self.assertEqual(s["bulunan"][0]["ad"], "Intercom_2")

    def test_harita_hicbir_sey_yazmaz(self):
        env = self.kur({"10.1.1.10": ["2001"], "10.1.1.12": ["2003"]}, sayi=3)
        self.harita(env, tur=2)

        self.assertEqual(self.ag.yazmalar, [])


if __name__ == "__main__":
    unittest.main()
