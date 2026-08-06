#!/usr/bin/env python3
"""Konfigürasyon yazma yolu.

Buradaki testlerin ortak derdi: panel ayarı cihazın gerçekten kabul ettiği
uca, cihazın istediği alanlarla göndermeli. Cihaz tek bir "ayarları yaz"
ucu sunmuyor (ana uç POST'a 405 döner); ses, mod, UIC gain ve SIP ayrı
uçlara gidiyor, bazıları alanların tamamını birlikte istiyor ve SIP yazımı
cihazı yeniden başlatıyor.
"""
from __future__ import annotations

import json

from core import ayar, konfig
from core.hata import DogrulamaHatasi

from .ortak import PanelTesti, ServisTesti
from . import sahte

# UIC'in ana uçta görünen ek alanları (tc/tl gain, eşik, hedefler).
UIC_AYAR = {
    **sahte.ANONS_AYAR, "pbxExtension": "2006", "pbxPassword": "2005",
    "pbxOutExtension": "", "callTimeout": 0,
    "tcSpeakerGain": 1, "tcMicGain": 1, "tlSpeakerGain": 2, "tlMicGain": 1,
    "target1": "2002", "target2": "", "target3": "2002", "target4": "",
    "tcHigh": 5, "tcLow": 2.5, "tlHigh": 5, "tlLow": 2.5,
}

HANDSET_MOD = {"answerMode": 0, "hangupMode": 2, "callMode": 1,
               "pttEnabled": 1, "speakerGain": 1, "micGain": 1, "logLevel": 1}


class KonfigYazma(PanelTesti):

    def setUp(self):
        super().setUp()
        # Cihazın yeniden başlamasını beklemek testleri yavaşlatmasın;
        # bekleme süresi kısaltılır, mantık aynı kalır.
        self._eski_bekleme = konfig.YENIDEN_BASLAMA_BEKLEME
        konfig.YENIDEN_BASLAMA_BEKLEME = 0.5

    def tearDown(self):
        konfig.YENIDEN_BASLAMA_BEKLEME = self._eski_bekleme
        super().tearDown()

    def kur(self, alt="Intercom", **ek):
        harita = sahte.device_map([{
            "Name": f"{alt}_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": alt, "Port": "11",
            "Status": {"NoError": True}, **ek,
        }])
        env = self.kur_harita(harita)
        return env, env.tip_ile("Announcement")[0]

    # ── uçlara dağıtım ───────────────────────────────────────────────
    def test_ses_ve_sip_ayri_uclara_yazilir(self):
        env, c = self.kur("Intercom", PBXExtension="2001", PBXPassword="2001")
        konfig.grup_hedef_yaz("Intercom", "hoparlor", "85", "Intercom")
        konfig.hedef_yaz(c.id, "sipDahili", "2007", "Intercom")
        with sahte.anons() as an:
            ayar.ANONS_PORT = an.port
            sonuc = konfig.uygula(c, env, None, "Intercom")
            yazmalar = sahte.anons_yazmalari(an)
            hal = dict(an.hal)

        self.assertEqual(hal["speakerVolume"], 85)
        self.assertEqual(hal["pbxExtension"], "2007")
        self.assertIn("/api/v1/audio/volume", yazmalar)
        self.assertIn("/api/v1/sip/settings", yazmalar)
        # Ana uç yalnız okumak içindir; oraya yazma denenmemeli.
        self.assertNotIn("/api/v1/system/settings", yazmalar)
        # SIP en sonda yazılır: cihaz o istekten sonra yeniden başlıyor.
        self.assertEqual(yazmalar[-1], "/api/v1/sip/settings")
        self.assertTrue(sonuc["yenidenBaslatildi"])

    def test_zaten_uyusan_ayar_icin_istek_atilmaz(self):
        """Hedef cihazdaki değerle aynıysa cihaza dokunulmaz.

        SIP ucu cihazı yeniden başlatıyor; "hepsini her seferinde yaz"
        davranışı bütün seti boşuna karartırdı.
        """
        env, c = self.kur("Intercom", PBXExtension="2001", PBXPassword="2001")
        konfig.grup_hedef_yaz("Intercom", "hoparlor", "70", "Intercom")
        with sahte.anons() as an:
            ayar.ANONS_PORT = an.port
            sonuc = konfig.uygula(c, env, None, "Intercom")
            yazmalar = sahte.anons_yazmalari(an)

        self.assertEqual(yazmalar, [])
        self.assertEqual(sonuc["yazilanAlanlar"], [])
        self.assertFalse(sonuc["yenidenBaslatildi"])

    def test_sip_ucunun_zorunlu_alanlari_tamamlanir(self):
        """Yalnız dış arama numarası değişse de SIP ucu üçlüyü istiyor.

        pbxIp/pbxExtension/pbxPassword eksikse cihaz "Missing required
        fields" ile reddediyor; eksikler cihazdan okunanla tamamlanır.
        """
        env, c = self.kur("Intercom")
        konfig.hedef_yaz(c.id, "sipArama", "5009", "Intercom")
        with sahte.anons() as an:
            ayar.ANONS_PORT = an.port
            konfig.uygula(c, env, None, "Intercom")
            hal = dict(an.hal)

        self.assertEqual(hal["pbxOutExtension"], "5009")
        # Cihazda duran parola ve dahili numara korunmuş olmalı
        self.assertEqual(hal["pbxPassword"], "2001")
        self.assertEqual(hal["pbxExtension"], "2001")

    def test_handset_modlari_mod_ucuna_dortlu_gider(self):
        env, c = self.kur("Handset")
        konfig.hedef_yaz(c.id, "cevapModu", "1", "Handset")
        with sahte.anons(modlar=HANDSET_MOD) as an:
            ayar.ANONS_PORT = an.port
            konfig.uygula(c, env, None, "Handset")
            yazmalar = sahte.anons_yazmalari(an)
            modlar = dict(an.mod_hali)

        self.assertEqual(yazmalar, ["/api/v1/system/modes"])
        self.assertEqual(modlar["answerMode"], 1)
        # Değişmeyen mod alanları da gönderilmiş olmalı, yoksa cihaz
        # "Missing mode fields" derdi.
        self.assertEqual(modlar["hangupMode"], 2)
        self.assertEqual(modlar["pttEnabled"], 1)

    def test_handset_gaini_ses_ucuna_degil_mod_ucuna_gider(self):
        env, c = self.kur("Handset")
        konfig.hedef_yaz(c.id, "hoparlorGain", "8", "Handset")
        with sahte.anons(modlar=HANDSET_MOD) as an:
            ayar.ANONS_PORT = an.port
            konfig.uygula(c, env, None, "Handset")
            yazmalar = sahte.anons_yazmalari(an)
            modlar = dict(an.mod_hali)

        self.assertEqual(yazmalar, ["/api/v1/system/modes"])
        self.assertEqual(modlar["speakerGain"], 8)

    def test_uic_gainleri_dordu_birlikte_gider(self):
        env, c = self.kur("UIC")
        konfig.hedef_yaz(c.id, "tcHoparlorGain", "4", "UIC")
        with sahte.anons(ayarlar=UIC_AYAR) as an:
            ayar.ANONS_PORT = an.port
            konfig.uygula(c, env, None, "UIC")
            yazmalar = sahte.anons_yazmalari(an)
            hal = dict(an.hal)

        self.assertEqual(yazmalar, ["/api/v1/uic/gains"])
        self.assertEqual(hal["tcSpeakerGain"], 4)
        self.assertEqual(hal["tlSpeakerGain"], 2)   # değişmeyen alan korundu

    def test_uic_esik_ve_hedefleri_sip_ucuna_gider(self):
        env, c = self.kur("UIC")
        konfig.grup_hedef_yaz("UIC", "tcYuksek", "4.5", "UIC")
        konfig.grup_hedef_yaz("UIC", "tlGiden", "2003", "UIC")
        with sahte.anons(ayarlar=UIC_AYAR) as an:
            ayar.ANONS_PORT = an.port
            konfig.uygula(c, env, None, "UIC")
            yazmalar = sahte.anons_yazmalari(an)
            hal = dict(an.hal)

        self.assertEqual(yazmalar, ["/api/v1/sip/settings"])
        self.assertEqual(hal["tcHigh"], 4.5)        # ondalık olarak gitti
        self.assertEqual(hal["target2"], "2003")

    def test_ondalik_esik_float32_yuvarlamasina_takilmaz(self):
        """Cihaz 2.4'ü 2.4000000953674316 olarak geri veriyor.

        Tam eşitlik arandığında yazılmış eşik "cihaz yazmadı" görünüyor,
        bir sonraki uygulamada da boşuna yeniden yazılıp cihaz gereksiz
        yeniden başlıyordu.
        """
        env, c = self.kur("UIC")
        konfig.grup_hedef_yaz("UIC", "tcAlcak", "2.4", "UIC")
        with sahte.anons(ayarlar=UIC_AYAR) as an:
            ayar.ANONS_PORT = an.port
            konfig.uygula(c, env, None, "UIC")          # hata vermemeli
            self.assertNotEqual(an.hal["tcLow"], 2.4)   # float32 gürültüsü
            # İkinci uygulamada aynı eşik yeniden yazılmaz
            ikinci = konfig.uygula(c, env, None, "UIC")
            self.assertEqual(ikinci["yazilanAlanlar"], [])
            # Ekranda gürültü değil, girilen değer görünür
            satir = next(s for s in ikinci["satirlar"]
                         if s["alan"] == "tcAlcak")
            self.assertEqual(satir["mevcut"], "2.4")
            self.assertEqual(satir["sonuc"], "uyuyor")

    def test_devicemapte_parola_yoksa_cihazdaki_korunur(self):
        """UIC/Amplifier kaydında PBXPassword yok; SIP ucu ise zorunlu tutuyor."""
        env, c = self.kur("UIC", PBXExtension="4001")
        self.assertIsNone(c.pbx_password)
        with sahte.anons(ayarlar=UIC_AYAR) as an:
            ayar.ANONS_PORT = an.port
            konfig.uygula(c, env, None, "UIC")
            hal = dict(an.hal)

        self.assertEqual(hal["pbxExtension"], "4001")   # DeviceMap hedefi
        self.assertEqual(hal["pbxPassword"], "2005")    # cihazdaki korundu

    def test_cihaz_alani_sessizce_yok_sayarsa_hata_verir(self):
        """HTTP 200 tek başına başarı değil; yazım okunarak doğrulanır."""
        env, c = self.kur("Intercom")
        konfig.hedef_yaz(c.id, "hoparlor", "85", "Intercom")
        # Cihaz isteği 200 ile kabul edip alanı atar (tanımadığı alanda
        # sahadaki davranışı bu).
        with sahte.anons(yoksay=("speakerVolume",)) as an:
            ayar.ANONS_PORT = an.port
            with self.assertRaises(DogrulamaHatasi) as tutulan:
                konfig.uygula(c, env, None, "Intercom")
            self.assertEqual(an.hal["speakerVolume"], 70)
        self.assertIn("yazmadı", str(tutulan.exception))

    # ── alan tabloları ───────────────────────────────────────────────
    def test_alan_listesi_cihaz_tipine_gore_degisir(self):
        def adlar(alt):
            return {f["alan"] for f in konfig.alan_listesi(alt)}

        amp, ic, hs, uic = (adlar("Amplifier"), adlar("Intercom"),
                            adlar("Handset"), adlar("UIC"))
        # Amplifier'da mikrofon yok
        self.assertNotIn("mikrofon", amp)
        self.assertNotIn("mikrofonGain", amp)
        self.assertIn("hoparlorGain", amp)
        # Dış arama numarası Amplifier ve UIC sayfalarında bulunmuyor
        self.assertIn("sipArama", ic)
        self.assertNotIn("sipArama", amp)
        self.assertNotIn("sipArama", uic)
        # Modlar yalnız Handset'te, eşik/hedefler yalnız UIC'te
        self.assertIn("kapatmaModu", hs)
        self.assertNotIn("kapatmaModu", ic)
        self.assertIn("tcYuksek", uic)
        self.assertIn("tlGelen", uic)
        self.assertNotIn("tcYuksek", hs)
        # Salt okunur alanlar her tipte görünür
        for kume in (amp, ic, hs, uic):
            self.assertIn("surum", kume)

    def test_sip_kaydi_satiri_salt_okunur_gosterilir(self):
        """Dahili no yazıldıktan sonra kaydın tuttuğu buradan görülür.

        Cihaz ayarı kabul etmiş olabilir ama PBX'e kaydolmamış olabilir;
        yazma doğrulaması bunu göstermez.
        """
        env, c = self.kur("UIC")
        with sahte.anons(ayarlar={**UIC_AYAR, "status": "Unregistered"}) as an:
            ayar.ANONS_PORT = an.port
            satir = next(s for s in konfig.cek(c, env)["satirlar"]
                         if s["alan"] == "sipKayit")
        self.assertEqual(satir["mevcut"], "Unregistered")
        self.assertFalse(satir["duzenlenebilir"])

    def test_uclar_cihaz_tipiyle_eslesir(self):
        self.assertEqual(konfig.uc_of("hoparlorGain", "Handset"),
                         konfig.UC_MOD)
        self.assertEqual(konfig.uc_of("hoparlorGain", "Intercom"),
                         konfig.UC_SES)
        self.assertEqual(konfig.uc_of("gunluk", "UIC"), konfig.UC_SES)
        self.assertEqual(konfig.uc_of("tcYuksek", "UIC"), konfig.UC_SIP)
        self.assertIsNone(konfig.uc_of("tcYuksek", "Intercom"))

    # ── değer denetimi ───────────────────────────────────────────────
    def test_gecersiz_deger_girildigi_anda_reddedilir(self):
        _env, c = self.kur("Intercom")
        for alan, deger in (("hoparlor", "150"), ("hoparlor", "abc"),
                            ("hoparlorGain", "3"), ("sipPbx", "10.1.1"),
                            ("sipDahili", "20 01"), ("gunluk", "5")):
            with self.assertRaises(ValueError, msg=f"{alan}={deger}"):
                konfig.hedef_yaz(c.id, alan, deger, "Intercom")
        # UIC eşiği 0–5 V aralığında
        with self.assertRaises(ValueError):
            konfig.hedef_yaz(c.id, "tcYuksek", "9", "UIC")
        # O cihaz tipinde bulunmayan alan da reddedilir
        with self.assertRaises(ValueError):
            konfig.hedef_yaz(c.id, "kapatmaModu", "1", "Intercom")

    def test_gecerli_deger_kabul_edilir(self):
        _env, c = self.kur("Intercom")
        konfig.hedef_yaz(c.id, "hoparlor", "85", "Intercom")
        konfig.hedef_yaz(c.id, "hoparlorGain", "8", "Intercom")
        konfig.hedef_yaz(c.id, "sipPbx", "10.1.1.1", "Intercom")
        self.assertEqual(konfig.hedef_al(c.id),
                         {"hoparlor": "85", "hoparlorGain": "8",
                          "sipPbx": "10.1.1.1"})
        # Boş değer özel hedefi kaldırır
        konfig.hedef_yaz(c.id, "hoparlor", "", "Intercom")
        self.assertNotIn("hoparlor", konfig.hedef_al(c.id))


class DeviceMapKonfigu(PanelTesti):
    """DeviceMap'te tanımlı ayarlar hedef değer olarak yerleşik gelir.

    Kullanıcı hiçbir kutuya dokunmazsa cihaza yazılan budur; alan adı
    cihazın kendi alan adıdır (SpeakerVolume, Target1…), panel ayrıca bir
    eşleme tablosu tutmaz.
    """

    def setUp(self):
        super().setUp()
        self._eski_bekleme = konfig.YENIDEN_BASLAMA_BEKLEME
        konfig.YENIDEN_BASLAMA_BEKLEME = 0.5

    def tearDown(self):
        konfig.YENIDEN_BASLAMA_BEKLEME = self._eski_bekleme
        super().tearDown()

    def kur(self, config=None, cihaz_ek=None, alt="Intercom", ikinci=None):
        cihazlar = [{
            "Name": f"{alt}_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": alt, "Port": "11",
            "Status": {"NoError": True}, **(cihaz_ek or {}),
        }]
        if ikinci:
            cihazlar.append({
                "Name": f"{alt}_2", "IP": "127.0.0.1", "IsActive": True,
                "Type": "Announcement", "SubType": alt, "Port": "12",
                "Status": {"NoError": True}, **ikinci,
            })
        harita = sahte.device_map(cihazlar)
        if config:
            harita["Config"] = config
        env = self.kur_harita(harita)
        return env, env.tip_ile("Announcement")

    def test_tip_config_bloku_hedef_olur(self):
        env, (c,) = self.kur(config={"Announcement": {"SpeakerVolume": 85},
                                     "Announcement/Intercom": {"MicGain": 4}})
        self.assertEqual(konfig.hedef_of(c, env, "hoparlor"), ("85", "proje"))
        self.assertEqual(konfig.hedef_of(c, env, "mikrofonGain"), ("4", "proje"))

    def test_cihaz_kaydi_tip_blogunu_ezer(self):
        env, (c,) = self.kur(config={"Announcement": {"SpeakerVolume": 85}},
                             cihaz_ek={"SpeakerVolume": 60})
        self.assertEqual(konfig.hedef_of(c, env, "hoparlor"), ("60", "proje"))

    def test_kullanici_degeri_devicemapi_ezer(self):
        env, (c,) = self.kur(config={"Announcement": {"SpeakerVolume": 85}})
        konfig.hedef_yaz(c.id, "hoparlor", "42", "Intercom")
        self.assertEqual(konfig.hedef_of(c, env, "hoparlor"), ("42", "cihaz"))

    def test_devicemap_ayari_dokunulmadan_cihaza_yazilir(self):
        env, (c,) = self.kur(config={
            "Announcement/Intercom": {"SpeakerVolume": 85, "MicVolume": 55,
                                      "SpeakerGain": 8, "LogLevel": 0}})
        with sahte.anons() as an:
            ayar.ANONS_PORT = an.port
            sonuc = konfig.uygula(c, env, None, "Intercom")
            hal = dict(an.hal)
        self.assertEqual(
            (hal["speakerVolume"], hal["micVolume"], hal["speakerGain"],
             hal["logLevel"]), (85, 55, 8, 0))
        # Ses ayarları tek uca gitti, SIP'e dokunulmadı (cihaz yeniden
        # başlamadı)
        self.assertFalse(sonuc["yenidenBaslatildi"])

    def test_gecersiz_devicemap_degeri_cihaza_yazilmaz(self):
        """Hatalı proje verisi cihaza gitmez; sebebi satırda görünür."""
        env, (c,) = self.kur(config={"Announcement": {"SpeakerVolume": 150,
                                                      "SpeakerGain": 3}})
        self.assertEqual(konfig.hedef_of(c, env, "hoparlor"), ("", ""))
        _d, _k, uyari = konfig.hedef_detay(c, env, "hoparlor")
        self.assertIn("DeviceMap", uyari)
        self.assertIn("0–100", uyari)
        with sahte.anons() as an:
            ayar.ANONS_PORT = an.port
            satir = next(s for s in konfig.cek(c, env)["satirlar"]
                         if s["alan"] == "hoparlorGain")
            self.assertIn("DeviceMap", satir["uyari"])
            self.assertEqual(an.hal["speakerVolume"], 70)   # değişmedi

    def test_grup_ozeti_ortak_ve_cihaza_gore_degisenleri_ayirir(self):
        """Ortak değer kutuya yerleşir, cihaza göre değişen yerleşmez.

        Dahili numara her cihazda farklı; gruba tek numara yazmak bütün
        cihazlara aynı numarayı verirdi.
        """
        env, cihazlar = self.kur(
            config={"Announcement": {"SpeakerVolume": 85}},
            cihaz_ek={"PBXExtension": "2001"},
            ikinci={"PBXExtension": "2002"})
        ortak, farkli = konfig.grup_proje_ozeti(env, cihazlar)
        self.assertEqual(ortak.get("hoparlor"), "85")
        self.assertIn("sipDahili", farkli)
        self.assertNotIn("sipDahili", ortak)


class KaliciVarsayilanlar(PanelTesti):
    """Girilen değerler dosyaya yazılır, açılışta geri yüklenir.

    Parola dosyaya HİÇ girmez: oturum boyunca bellekte durur.
    """

    PAROLA = "sip-parolasi-4471"

    def kur(self, alt="Intercom"):
        harita = sahte.device_map([{
            "Name": f"{alt}_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": alt, "Port": "11",
            "PBXExtension": "2001", "Status": {"NoError": True},
        }])
        env = self.kur_harita(harita)
        return env, env.tip_ile("Announcement")[0]

    def test_girilen_deger_dosyaya_yazilir_ve_geri_yuklenir(self):
        env, c = self.kur()
        konfig.grup_hedef_yaz("Intercom", "hoparlor", "85", "Intercom")
        konfig.hedef_yaz(c.id, "sipArama", "5009", "Intercom")
        self.assertTrue(ayar.konfig_varsayilan_dosyasi().exists())

        # Uygulama kapanışı: bellek boşalır, dosya kalır.
        konfig.hedefleri_unut()
        self.assertEqual(konfig.grup_hedef_al("Intercom"), {})

        # Yeniden açılış
        self.assertEqual(konfig.varsayilanlari_yukle(), 2)
        self.assertEqual(konfig.grup_hedef_al("Intercom"), {"hoparlor": "85"})
        self.assertEqual(konfig.hedef_al(c.id), {"sipArama": "5009"})
        self.assertEqual(konfig.hedef_of(c, env, "hoparlor", "Intercom"),
                         ("85", "grup"))

    def test_parola_dosyaya_yazilmaz(self):
        _env, c = self.kur()
        konfig.grup_hedef_yaz("Intercom", "sipParola", self.PAROLA, "Intercom")
        konfig.hedef_yaz(c.id, "sipParola", self.PAROLA, "Intercom")
        yol = ayar.konfig_varsayilan_dosyasi()
        # Dosya hiç oluşmamış ya da oluşmuş olsa da parolayı içermiyor
        if yol.exists():
            self.assertNotIn(self.PAROLA, yol.read_text(encoding="utf-8"))
        # Yeniden yüklemede parola geri gelmez, bellekte kalan da silinir
        konfig.hedefleri_unut()
        konfig.varsayilanlari_yukle()
        self.assertEqual(konfig.grup_hedef_al("Intercom"), {})
        self.assertEqual(konfig.hedef_al(c.id), {})

    def test_bos_deger_kayittan_da_silinir(self):
        _env, c = self.kur()
        konfig.grup_hedef_yaz("Intercom", "hoparlor", "85", "Intercom")
        konfig.grup_hedef_yaz("Intercom", "hoparlor", "", "Intercom")
        konfig.hedefleri_unut()
        self.assertEqual(konfig.varsayilanlari_yukle(), 0)

    def test_bozuk_dosya_paneli_durdurmaz(self):
        self.kur()
        yol = ayar.konfig_varsayilan_dosyasi()
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text("{bu geçerli json değil", encoding="utf-8")
        self.assertEqual(konfig.varsayilanlari_yukle(), 0)

    def test_gecersiz_ve_tanimsiz_alan_atlanir(self):
        """Eski ya da elle bozulmuş dosya cihaza yanlış değer yazdırmamalı."""
        self.kur()
        yol = ayar.konfig_varsayilan_dosyasi()
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text(json.dumps({"bicim": 1, "gruplar": {"Intercom": {
            "hoparlor": "150",        # aralık dışı
            "hoparlorGain": "3",      # tanımsız seçim
            "olmayanAlan": "1",       # artık bulunmayan alan
            "mikrofon": "44",         # geçerli
        }}}), encoding="utf-8")
        self.assertEqual(konfig.varsayilanlari_yukle(), 1)
        self.assertEqual(konfig.grup_hedef_al("Intercom"), {"mikrofon": "44"})

    def test_sifirlama_dosyayi_da_siler(self):
        _env, c = self.kur()
        konfig.grup_hedef_yaz("Intercom", "hoparlor", "85", "Intercom")
        konfig.varsayilanlari_sil()
        self.assertFalse(ayar.konfig_varsayilan_dosyasi().exists())
        self.assertEqual(konfig.grup_hedef_al("Intercom"), {})

    def test_veri_dizini_proje_agacinin_disinda(self):
        """Kalıcı dosya ne proje ağacına ne DeviceMap'in yanına yazılır."""
        self.kur()
        yol = ayar.konfig_varsayilan_dosyasi().resolve()
        self.assertFalse(str(yol).startswith(str(ayar.KOK.resolve())))
        self.assertNotEqual(yol.parent, self.harita_yolu.parent)


class HizliAlanUcu(ServisTesti):
    """Grup değişince ekran cihaz okumasını beklemez."""

    def kur(self):
        harita = sahte.device_map([{
            "Name": "Uic", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "UIC", "Port": "3",
            "PBXExtension": "4001", "Status": {"NoError": True},
        }])
        env = self.kur_harita(harita)
        return env, env.tip_ile("Announcement")[0]

    def test_alanlar_ucu_cihaza_hic_gitmez(self):
        _env, c = self.kur()
        with sahte.anons() as an:
            ayar.ANONS_PORT = an.port
            taban = self.servis_ac()
            kod, y = self.cagir(
                taban, f"/api/konfig/alanlar?set=1&id={c.id}&grup=UIC")
            self.assertEqual(kod, 200)
            self.assertEqual(an.istek_sayisi, 0)      # cihaza istek yok
        self.assertTrue(y["okunuyor"])
        self.assertEqual(y["satirlar"], [])
        # Ekranın hemen çizmesi için gereken her şey burada
        adlar = {a["alan"] for a in y["alanlar"]}
        self.assertIn("tcYuksek", adlar)
        self.assertEqual(y["projeHedef"].get("sipDahili"), "4001")

    def test_konfig_okumasi_gereksiz_uc_denemez(self):
        """Cihaz okuması tek istekle biter; Handset'te iki (mod ucu)."""
        _env, c = self.kur()
        with sahte.anons() as an:
            ayar.ANONS_PORT = an.port
            konfig.cek(c, self.kur_harita(sahte.device_map([{
                "Name": "Uic", "IP": "127.0.0.1", "IsActive": True,
                "Type": "Announcement", "SubType": "UIC", "Port": "3",
                "Status": {"NoError": True}}])), None, "UIC")
            self.assertEqual(sahte.anons_yazmalari(an), [])
            self.assertEqual(an.istek_sayisi, 1)


class SipParolasi(ServisTesti):
    """SIP parolası yazılabilir ama hiçbir yanıtta geri dönmez."""

    PAROLA = "sip-parolasi-9713"

    def kur(self):
        harita = sahte.device_map([{
            "Name": "Intercom_1", "IP": "127.0.0.1", "IsActive": True,
            "Type": "Announcement", "SubType": "Intercom", "Port": "11",
            "PBXExtension": "2001", "PBXPassword": "2001",
            "Status": {"NoError": True},
        }])
        env = self.kur_harita(harita)
        return env, env.tip_ile("Announcement")[0]

    def test_parola_hicbir_yanitta_gorunmez(self):
        env, c = self.kur()
        with sahte.anons() as an:
            ayar.ANONS_PORT = an.port
            taban = self.servis_ac()
            kod, y = self.cagir(taban, "/api/konfig/hedef", {
                "set": 1, "cihazId": c.id, "alan": "sipParola",
                "deger": self.PAROLA, "grup": "Intercom", "kapsam": "grup"})
            self.assertEqual(kod, 200)
            self.assertNotIn(self.PAROLA, json.dumps(y, ensure_ascii=False))

            _kod2, y2 = self.cagir(
                taban, f"/api/konfig?set=1&id={c.id}&grup=Intercom")
            self.assertNotIn(self.PAROLA, json.dumps(y2, ensure_ascii=False))
            # Satır yine de durumu bildirir: girilen parola cihazdakinden
            # farklı olduğu için "farklı" görünmeli.
            satir = next(s for s in y2["satirlar"] if s["alan"] == "sipParola")
            self.assertEqual(satir["sonuc"], "farkli")
            self.assertEqual(satir["kaynak"], "grup")
            self.assertEqual(satir["mevcut"], "")
            self.assertTrue(satir["mevcutVar"])
            self.assertIn("sipParola", y2["grupGizli"])
            self.assertEqual(y2["grupHedef"].get("sipParola", ""), "")

    def test_girilen_parola_cihaza_yazilir(self):
        env, c = self.kur()
        konfig.grup_hedef_yaz("Intercom", "sipParola", self.PAROLA, "Intercom")
        eski = konfig.YENIDEN_BASLAMA_BEKLEME
        konfig.YENIDEN_BASLAMA_BEKLEME = 0.5
        self.addCleanup(setattr, konfig, "YENIDEN_BASLAMA_BEKLEME", eski)
        with sahte.anons() as an:
            ayar.ANONS_PORT = an.port
            konfig.uygula(c, env, None, "Intercom")
            self.assertEqual(an.hal["pbxPassword"], self.PAROLA)

    def test_devicemap_parolasi_dto_da_yok(self):
        _env, c = self.kur()
        self.assertEqual(c.pbx_password, "2001")
        self.assertNotIn("2001", json.dumps(
            {k: v for k, v in c.dto().items() if k != "pbxExtension"}))
