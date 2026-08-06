#!/usr/bin/env python3
"""Konfigürasyon — cihazdaki değerleri okuma ve hedef değerleri yazma.

Ekran iki sütunu yan yana gösterir: cihazdan gerçekten okunan değer ve
yazılacak hedef değer. Okunamayan alan boş (—) kalır; "henüz okunmadı"
yerine varsayılan bir değer gösterilmez — bir alanın cihazda ne olduğunu
bilmeden "uyuşuyor" demek doğrulamayı anlamsızlaştırır.

Hedef değerlerin kaynağı iki türlü olabilir:
  · DeviceMap  — SIP dahili numarası gibi projede tanımlı alanlar
  · elle       — kullanıcının ekranda girdiği değer (bellekte, oturumluk)

CİHAZIN YAZMA UÇLARI
────────────────────
Okuma tek uçtan yapılır (GET api/v1/system/settings) ama YAZMA öyle
değil: o uç POST'a HTTP 405 döner. Cihazın kendi web arayüzü ayarları
konusuna göre ayrı uçlara gönderiyor ve panel de aynısını yapar
(aşağıdaki ROTA tablosu her cihaz tipinin kendi sayfasından birebir
alınmıştır):

  api/v1/audio/volume    ses seviyeleri, gain, günlük — kısmi gövde kabul
  api/v1/system/modes    Handset modları — dört mod alanı birlikte zorunlu
  api/v1/uic/gains       UIC TC/TL gain'leri — dört alan birlikte zorunlu
  api/v1/sip/settings    SIP — pbxIp+pbxExtension+pbxPassword zorunlu,
                         yazıldıktan sonra CİHAZ YENİDEN BAŞLIYOR

Bu yüzden yazma "hepsini tek gövdede gönder" değil: yalnızca cihazdaki
değerden farklı olan alanlar, ait oldukları uçlara ayrı ayrı gider. Zaten
uyuşan bir alan için istek atılmaz — SIP ucuna gereksiz bir istek bütün
cihazları boşuna yeniden başlatırdı.

SIP PAROLASI
────────────
SIP ucu parolayı zorunlu istiyor, dolayısıyla parola olmadan dahili numara
da yazılamaz. Parolanın kaynağı sırayla: kullanıcının bu ekranda girdiği
değer (yalnız bellekte), DeviceMap'teki PBXPassword (projenin tanım
verisi) ve cihazda hâlihazırda duran değer. Bu değer arayüze HİÇ
gönderilmez: satırda yalnız "uyuşuyor/farklı" ve kaynağı görünür. Buradaki
parola cihazın SIP kaydı içindir; panelin cihaza bağlanırken kullandığı
kimlik değildir (o yalnız kullanıcıdan alınır, bkz. core/kimlik.py).
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass

import requests

from . import ayar, okuma
from .device_map import Cihaz, Envanter
from .hata import DogrulamaHatasi, KimlikHatasi, UygulanmazHatasi, sinifla

# ── cihazın uçları ──────────────────────────────────────────────────────
UC_SES = "api/v1/audio/volume"
UC_MOD = "api/v1/system/modes"
UC_UIC = "api/v1/uic/gains"
UC_SIP = "api/v1/sip/settings"

# Yazma sırası: SIP en sonda, çünkü cihaz o istekten sonra yeniden başlıyor
# ve ardından gelen istek bağlantı hatası alırdı.
UC_SIRASI = (UC_SES, UC_MOD, UC_UIC, UC_SIP)
YENIDEN_BASLATAN = {UC_SIP}

# Uç kısmi gövde kabul etmiyorsa bu alanlar her istekte bulunmalı. Eksikse
# cihaz "Missing required fields" / "Missing mode fields" ile reddediyor,
# uic/gains ucu ise bağlantıyı düşürüyor. Değiştirilmeyen zorunlu alanlar
# cihazdan okunan değerle doldurulur.
ZORUNLU = {
    UC_SIP: ("sipPbx", "sipDahili", "sipParola"),
    UC_MOD: ("ptt", "cevapModu", "aramaModu", "kapatmaModu"),
    UC_UIC: ("tcHoparlorGain", "tcMikrofonGain",
             "tlHoparlorGain", "tlMikrofonGain"),
}

# ── seçenek listeleri (cihaz sayfalarındaki açılır listelerle aynı) ─────
GAIN = tuple((str(k), f"{k}x")
             for k in (1, 2, 4, 6, 8, 12, 16, 24, 32, 48, 64))
GUNLUK = (("1", "Info + Error"), ("0", "Yalnız Error"))
CALMA = (("0", "Kapalı"), ("5", "5 sn"), ("10", "10 sn"), ("15", "15 sn"),
         ("20", "20 sn"), ("30", "30 sn"), ("45", "45 sn"), ("60", "1 dk"),
         ("90", "1,5 dk"), ("120", "2 dk"))
ACIK_KAPALI = (("1", "Açık"), ("0", "Kapalı"))
CEVAP = (("0", "Butona basarak"), ("1", "Otomatik cevap"))
ARAMA = (("0", "Tek basış"), ("1", "Uzun basış (3 sn)"))
KAPATMA = (("0", "Tek basış"), ("1", "Çift basış"), ("2", "DTMF"))


@dataclass(frozen=True)
class Alan:
    """Ekranda bir satır, cihazda bir alan.

    `yaz` cihazın gerçek alan adıdır; None ise alan salt okunurdur.
    `oku` okuma adaylarıdır — firmware sürümleri arasında ad değişen eski
    alanlar için geniş tutulmuştur; boşsa `yaz` adı kullanılır.
    """

    etiket: str
    yaz: str | None = None
    bolum: str = ""
    tur: str = "metin"          # metin · ip · numara · tamsayi · ondalik · secim
    secenekler: tuple = ()
    en_az: float | None = None
    en_cok: float | None = None
    adim: float | None = None
    gizli: bool = False         # değeri arayüze hiç gönderilmez
    oku: tuple = ()
    disla: tuple = ()
    ipucu: str = ""

    def okunacak(self) -> tuple:
        return self.oku or ((self.yaz,) if self.yaz else ())


ALANLAR: dict[str, Alan] = {
    # ── SIP ──────────────────────────────────────────────────────────
    "sipPbx": Alan("SIP PBX IP", "pbxIp", "SIP", "ip", oku=okuma.K_PBX),
    "sipDahili": Alan("SIP Dahili No", "pbxExtension", "SIP", "numara",
                      oku=okuma.K_EXT,
                      disla=("outbound", "outext", "pbxout", "dial")),
    "sipParola": Alan("SIP Parolası", "pbxPassword", "SIP", "metin",
                      gizli=True, oku=("pbxPassword",),
                      ipucu="Boş bırakılırsa DeviceMap'teki ya da cihazda "
                            "duran parola korunur"),
    "sipArama": Alan("SIP Dış Arama No", "pbxOutExtension", "SIP", "numara",
                     oku=okuma.K_OUT),
    "calmaSuresi": Alan("Çalma Süresi", "callTimeout", "SIP", "secim",
                        secenekler=CALMA, oku=("callTimeout",)),
    # ── ses ──────────────────────────────────────────────────────────
    "hoparlor": Alan("Hoparlör Ses Seviyesi", "speakerVolume", "Ses",
                     "tamsayi", en_az=0, en_cok=100, oku=okuma.K_SPK,
                     disla=("gain",)),
    "mikrofon": Alan("Mikrofon Ses Seviyesi", "micVolume", "Ses", "tamsayi",
                     en_az=0, en_cok=100, oku=okuma.K_MIC, disla=("gain",)),
    "hoparlorGain": Alan("Hoparlör Gain", "speakerGain", "Ses", "secim",
                         secenekler=GAIN, oku=okuma.K_SPK_GAIN),
    "mikrofonGain": Alan("Mikrofon Gain", "micGain", "Ses", "secim",
                         secenekler=GAIN, oku=okuma.K_MIC_GAIN),
    "gunluk": Alan("Günlük Seviyesi", "logLevel", "Ses", "secim",
                   secenekler=GUNLUK, oku=("logLevel",)),
    # ── Handset modları ──────────────────────────────────────────────
    "ptt": Alan("PTT", "pttEnabled", "Mod", "secim",
                secenekler=ACIK_KAPALI, oku=("pttEnabled",)),
    "cevapModu": Alan("Cevaplama Modu", "answerMode", "Mod", "secim",
                      secenekler=CEVAP, oku=("answerMode",)),
    "aramaModu": Alan("Arama Modu", "callMode", "Mod", "secim",
                      secenekler=ARAMA, oku=("callMode",)),
    "kapatmaModu": Alan("Kapatma Modu", "hangupMode", "Mod", "secim",
                        secenekler=KAPATMA, oku=("hangupMode",)),
    # ── UIC gain'leri ────────────────────────────────────────────────
    "tcHoparlorGain": Alan("TC Hoparlör Gain", "tcSpeakerGain", "Ses",
                           "secim", secenekler=GAIN, oku=("tcSpeakerGain",)),
    "tcMikrofonGain": Alan("TC Mikrofon Gain", "tcMicGain", "Ses", "secim",
                           secenekler=GAIN, oku=("tcMicGain",)),
    "tlHoparlorGain": Alan("TL Hoparlör Gain", "tlSpeakerGain", "Ses",
                           "secim", secenekler=GAIN, oku=("tlSpeakerGain",)),
    "tlMikrofonGain": Alan("TL Mikrofon Gain", "tlMicGain", "Ses", "secim",
                           secenekler=GAIN, oku=("tlMicGain",)),
    # ── UIC gerilim eşikleri (cihaz sayfası: 0–5 V, 0,1 adım) ────────
    "tcYuksek": Alan("TC Üst Eşik (V)", "tcHigh", "Eşik", "ondalik",
                     en_az=0, en_cok=5, adim=0.1, oku=("tcHigh",)),
    "tcAlcak": Alan("TC Alt Eşik (V)", "tcLow", "Eşik", "ondalik",
                    en_az=0, en_cok=5, adim=0.1, oku=("tcLow",)),
    "tlYuksek": Alan("TL Üst Eşik (V)", "tlHigh", "Eşik", "ondalik",
                     en_az=0, en_cok=5, adim=0.1, oku=("tlHigh",)),
    "tlAlcak": Alan("TL Alt Eşik (V)", "tlLow", "Eşik", "ondalik",
                    en_az=0, en_cok=5, adim=0.1, oku=("tlLow",)),
    # ── UIC çağrı yönlendirme (cihaz sayfasındaki sırayla target1..4) ─
    "tcGiden": Alan("TC (3+ 4-) → Giden Dahili", "target1", "Yönlendirme",
                    "numara", oku=("target1",)),
    "tlGiden": Alan("TL (3- 4+) → Giden Dahili", "target2", "Yönlendirme",
                    "numara", oku=("target2",)),
    "tcGelen": Alan("Gelen → TC (3+ 4-)", "target3", "Yönlendirme",
                    "numara", oku=("target3",)),
    "tlGelen": Alan("Gelen → TL (3- 4+)", "target4", "Yönlendirme",
                    "numara", oku=("target4",)),
    # ── salt okunur ──────────────────────────────────────────────────
    # SIP kaydı, dahili numara/parola yazıldıktan sonra bakılacak alan:
    # cihaz ayarı kabul etmiş olabilir ama PBX'e kaydolmamış olabilir
    # (örneğin parola eşleşmiyorsa). Yazma doğrulaması bunu göstermez.
    "sipKayit": Alan("SIP Kaydı", None, "Bilgi",
                     oku=("status", "sipStatus", "registrationState")),
    "surum": Alan("Yazılım Sürümü", None, "Bilgi", oku=okuma.K_SURUM),
    "seri": Alan("Cihaz Numarası", None, "Bilgi", oku=okuma.K_SERI),
}

# Hangi cihaz tipinde hangi alan, hangi uca gider. Her satır o cihazın
# kendi web arayüzünün gönderdiği gövdeyle birebirdir; tahmin edilen alan
# eklenmez, çünkü cihaz tanımadığı alanı sessizce yok sayıyor.
ROTA: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (UC_SES, ("Amplifier",), ("hoparlor", "hoparlorGain", "gunluk")),
    (UC_SES, ("Intercom",), ("hoparlor", "mikrofon", "hoparlorGain",
                             "mikrofonGain", "gunluk")),
    (UC_SES, ("Handset",), ("hoparlor", "mikrofon")),
    (UC_SES, ("UIC",), ("hoparlor", "mikrofon", "gunluk")),
    # Handset'te gain ve günlük ses ucunda değil, mod ucunda.
    (UC_MOD, ("Handset",), ("ptt", "cevapModu", "aramaModu", "kapatmaModu",
                            "hoparlorGain", "mikrofonGain", "gunluk")),
    (UC_UIC, ("UIC",), ("tcHoparlorGain", "tcMikrofonGain",
                        "tlHoparlorGain", "tlMikrofonGain")),
    (UC_SIP, ("Amplifier",), ("sipPbx", "sipDahili", "sipParola")),
    (UC_SIP, ("Intercom",), ("sipPbx", "sipDahili", "sipParola", "sipArama")),
    (UC_SIP, ("Handset",), ("sipPbx", "sipDahili", "sipParola", "sipArama",
                            "calmaSuresi")),
    (UC_SIP, ("UIC",), ("sipPbx", "sipDahili", "sipParola", "calmaSuresi",
                        "tcGiden", "tlGiden", "tcGelen", "tlGelen",
                        "tcYuksek", "tcAlcak", "tlYuksek", "tlAlcak")),
)

# Ekranda görünme sırası — bölümler kendi içinde derli toplu kalsın.
SIRA = ("sipPbx", "sipDahili", "sipParola", "sipArama", "calmaSuresi",
        "tcGiden", "tlGiden", "tcGelen", "tlGelen",
        "hoparlor", "mikrofon", "hoparlorGain", "mikrofonGain",
        "tcHoparlorGain", "tcMikrofonGain", "tlHoparlorGain",
        "tlMikrofonGain", "gunluk",
        "ptt", "cevapModu", "aramaModu", "kapatmaModu",
        "tcYuksek", "tcAlcak", "tlYuksek", "tlAlcak",
        "sipKayit", "surum", "seri")

# Salt okunur alanlar her cihaz tipinde görünür.
SALT_OKUNUR = tuple(ad for ad in SIRA if ALANLAR[ad].yaz is None)

YAZILABILIR = {ad for _uc, _altlar, alanlar in ROTA for ad in alanlar}

# Cihaz yeniden başlatıldıktan sonra ne kadar beklenir. Sahada geri gelmesi
# birkaç saniye sürüyor; süre dolarsa okuma yine denenir ve gerçek hata
# mesajı kullanıcıya çıkar.
YENIDEN_BASLAMA_BEKLEME = float(ayar.OKUMA_TIMEOUT) * 6

# Kullanıcının elle girdiği hedef değerler — yalnızca bellekte.
#
# İki düzey var: gruba yazılan değer (aynı ayar bütün anons cihazlarına
# gidecekse bir kez girilir) ve cihaza özel değer (o cihazda farklı
# olacaksa). Cihaza özel olan grubunkini ezer.
_HEDEF: dict[str, dict] = {}
_GRUP_HEDEF: dict[str, dict] = {}
_KILIT = threading.Lock()


# ── alan tabloları ──────────────────────────────────────────────────────
def uc_of(alan: str, alt: str | None) -> str | None:
    """Alanın bu cihaz tipinde yazıldığı uç (yazılamıyorsa None)."""
    for uc, altlar, alanlar in ROTA:
        if alan in alanlar and (alt or "") in altlar:
            return uc
    return None


def alt_yazilabilir(alt: str | None) -> tuple[str, ...]:
    """Bu cihaz tipinde yazılabilen alanlar — ekran sırasında."""
    varsa = {ad for _uc, altlar, alanlar in ROTA if (alt or "") in altlar
             for ad in alanlar}
    return tuple(ad for ad in SIRA if ad in varsa)


def alt_alanlari(alt: str | None) -> tuple[str, ...]:
    """Bu cihaz tipinde gösterilen bütün alanlar (salt okunur dahil)."""
    yazilir = set(alt_yazilabilir(alt))
    return tuple(ad for ad in SIRA if ad in yazilir or ad in SALT_OKUNUR)


def alan_listesi(alt: str | None = None) -> list[dict]:
    """Ekranın alan tanımları — cihaz okunmasa da bilinir.

    Gruba yazılacak değerler cihazdan bağımsız girilebilmeli: sahada
    cihaza erişilemezken de ayarlar hazırlanıyor. `alt` verilmezse bütün
    tiplerin alanları döner.
    """
    adlar = alt_alanlari(alt) if alt else SIRA
    cikan = []
    for ad in adlar:
        a = ALANLAR[ad]
        cikan.append({
            "alan": ad, "etiket": a.etiket, "bolum": a.bolum,
            "duzenlenebilir": bool(a.yaz),
            "tur": a.tur,
            "secenekler": [{"deger": d, "etiket": e} for d, e in a.secenekler],
            "enAz": a.en_az, "enCok": a.en_cok, "adim": a.adim,
            "gizli": a.gizli, "ipucu": a.ipucu,
        })
    return cikan


# ── hedef değer deposu ──────────────────────────────────────────────────
def _ipv4(d: str) -> bool:
    parca = d.split(".")
    if len(parca) != 4:
        return False
    return all(p.isdigit() and len(p) <= 3 and 0 <= int(p) <= 255
               for p in parca)


def _dogrula(alan: str, deger, alt: str | None = None) -> str:
    """Değeri alanın türüne göre denetler, temizlenmiş halini döndürür.

    Denetim burada yapılır: geçersiz değer bellekte bekleyip yazma anında
    patlarsa kullanıcı hatayı girdiği ekranda değil, kuyrukta görür.
    """
    if alan not in YAZILABILIR:
        raise ValueError(f"Yazılamayan alan: {alan}")
    if alt and alan not in alt_yazilabilir(alt):
        raise ValueError(
            f"{ALANLAR[alan].etiket} alanı {alt} cihazında bulunmuyor")

    a = ALANLAR[alan]
    d = str(deger).strip()
    if not d:
        return ""

    if a.tur == "secim":
        if d not in [x for x, _e in a.secenekler]:
            raise ValueError(f"{a.etiket}: geçersiz seçim ({d})")
    elif a.tur in ("tamsayi", "ondalik"):
        try:
            sayi = float(d.replace(",", "."))
        except ValueError:
            raise ValueError(f"{a.etiket}: sayı olmalı")
        if a.tur == "tamsayi" and not sayi.is_integer():
            raise ValueError(f"{a.etiket}: tam sayı olmalı")
        if (a.en_az is not None and sayi < a.en_az) or \
           (a.en_cok is not None and sayi > a.en_cok):
            raise ValueError(
                f"{a.etiket}: {_kisa(a.en_az)}–{_kisa(a.en_cok)} aralığında "
                "olmalı")
        # Ondalıkta gereksiz sıfır taşınmaz: DeviceMap'te 5 yazan eşik
        # ekranda "5.0" değil "5" görünür, cihazdaki değerle yan yana
        # okunabilsin.
        d = str(int(sayi)) if a.tur == "tamsayi" else f"{sayi:g}"
    elif a.tur == "ip":
        if not _ipv4(d):
            raise ValueError(f"{a.etiket}: geçerli bir IPv4 adresi değil")
    elif a.tur == "numara":
        if not re.fullmatch(r"[0-9*#]{1,32}", d):
            raise ValueError(f"{a.etiket}: yalnız rakam, * ve # olabilir")
    elif len(d) > 64:
        raise ValueError(f"{a.etiket}: en çok 64 karakter")
    return d[:128]


def _kisa(sayi) -> str:
    if sayi is None:
        return "?"
    return str(int(sayi)) if float(sayi).is_integer() else str(sayi)


def hedef_yaz(cihaz_id: str, alan: str, deger: str,
              alt: str | None = None) -> None:
    temiz = _dogrula(alan, deger, alt)
    with _KILIT:
        if temiz:
            _HEDEF.setdefault(cihaz_id, {})[alan] = temiz
        else:                                   # boş = özel değeri kaldır
            _HEDEF.get(cihaz_id, {}).pop(alan, None)
    _kaydet()


def hedef_al(cihaz_id: str) -> dict:
    with _KILIT:
        return dict(_HEDEF.get(cihaz_id, {}))


def grup_hedef_yaz(grup: str, alan: str, deger: str,
                   alt: str | None = None) -> None:
    temiz = _dogrula(alan, deger, alt)
    with _KILIT:
        if temiz:
            _GRUP_HEDEF.setdefault(grup, {})[alan] = temiz
        else:
            _GRUP_HEDEF.get(grup, {}).pop(alan, None)
    _kaydet()


def grup_hedef_al(grup: str) -> dict:
    """Gruba girilen hedefler. Gizli alanlar (parola) değeriyle döner —
    arayüze giden gösterimi `cek`/panel_api maskeler."""
    with _KILIT:
        return dict(_GRUP_HEDEF.get(grup or "", {}))


def grup_hedef_gosterim(grup: str) -> dict:
    """Arayüze verilebilir hâli: gizli alanların değeri yerine "girildi mi"."""
    ham = grup_hedef_al(grup)
    return {ad: ("" if ALANLAR[ad].gizli else d) for ad, d in ham.items()}


def grup_gizli_alanlar(grup: str) -> list[str]:
    return [ad for ad in grup_hedef_al(grup) if ALANLAR[ad].gizli]


def hedefleri_unut() -> None:
    """Bellekteki hedefleri boşaltır — kayıtlı dosyaya dokunmaz."""
    with _KILIT:
        _HEDEF.clear()
        _GRUP_HEDEF.clear()


# ── kalıcı varsayılanlar ────────────────────────────────────────────────
# Konfigürasyon ekranında girilen değerler uygulama kapanınca kaybolmasın
# diye dosyaya yazılır ve açılışta geri yüklenir. PAROLA YAZILMAZ: gizli
# alanlar dosyaya hiç girmez, oturum boyunca yalnız bellekte durur. Bu,
# "parola hiçbir dosyada tutulmaz" kuralının konfigürasyon tarafındaki
# karşılığıdır (bkz. core/kimlik.py).
BICIM = 1


def _yazilabilir_hedefler(depo: dict) -> dict:
    return {anahtar: {ad: d for ad, d in alanlar.items()
                      if ad in ALANLAR and not ALANLAR[ad].gizli}
            for anahtar, alanlar in depo.items()}


def _kaydet() -> None:
    """Hedefleri dosyaya yazar. Yazamamak akışı bozmaz."""
    with _KILIT:
        govde = {
            "bicim": BICIM,
            "gruplar": {k: v for k, v in
                        _yazilabilir_hedefler(_GRUP_HEDEF).items() if v},
            "cihazlar": {k: v for k, v in
                         _yazilabilir_hedefler(_HEDEF).items() if v},
        }
    yol = ayar.konfig_varsayilan_dosyasi()
    try:
        yol.parent.mkdir(parents=True, exist_ok=True)
        gecici = yol.with_suffix(".tmp")
        gecici.write_text(json.dumps(govde, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        gecici.replace(yol)             # yarım dosya bırakmamak için
    except OSError:
        pass


def varsayilanlari_yukle() -> int:
    """Kayıtlı hedefleri belleğe alır; kaç değer yüklendiğini döndürür.

    Dosya bozuksa ya da alan artık tanınmıyorsa o değer atlanır: eski bir
    dosya yüzünden panelin açılmaması ya da tanımsız bir alanın cihaza
    yazılmaya çalışılması istenmez.
    """
    yol = ayar.konfig_varsayilan_dosyasi()
    try:
        govde = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(govde, dict):
        return 0

    sayi = 0
    with _KILIT:
        for kaynak, depo in (("gruplar", _GRUP_HEDEF),
                             ("cihazlar", _HEDEF)):
            blok = govde.get(kaynak)
            if not isinstance(blok, dict):
                continue
            for anahtar, alanlar in blok.items():
                if not isinstance(alanlar, dict):
                    continue
                for ad, deger in alanlar.items():
                    if ad not in ALANLAR or ALANLAR[ad].gizli:
                        continue
                    try:
                        temiz = _dogrula(ad, deger)
                    except ValueError:
                        continue
                    if temiz:
                        depo.setdefault(str(anahtar), {})[ad] = temiz
                        sayi += 1
    return sayi


def varsayilanlari_sil() -> None:
    """Kayıtlı varsayılanları hem bellekten hem dosyadan siler."""
    hedefleri_unut()
    try:
        ayar.konfig_varsayilan_dosyasi().unlink()
    except OSError:
        pass


def varsayilan_ozeti() -> dict:
    """Arayüzün gösterdiği kayıt durumu (değerler değil, sayılar)."""
    with _KILIT:
        grup_sayi = sum(len(v) for v in _yazilabilir_hedefler(
            _GRUP_HEDEF).values())
        cihaz_sayi = sum(len(v) for v in _yazilabilir_hedefler(
            _HEDEF).values())
    yol = ayar.konfig_varsayilan_dosyasi()
    return {"dosya": str(yol), "kayitli": yol.exists(),
            "grupDegeri": grup_sayi, "cihazDegeri": cihaz_sayi}


def _proje_hedefi(cihaz: Cihaz, env: Envanter,
                  alan: str) -> tuple[str, str]:
    """DeviceMap'te tanımlı değer ve (varsa) neden kullanılamadığı.

    DeviceMap anahtarı, cihazın alan adının kendisidir: `SpeakerVolume`,
    `PBXExtension`, `Target1`, `TcHigh`… (büyük/küçük harf önemsiz).
    Böylece yeni bir ayarı projeye tanıtmak için burada tablo tutmak
    gerekmiyor — Envanter.proje_ayarlari() tip/alt tip/cihaz düzeylerini
    birleştirip veriyor.

    Değer geçersizse (aralık dışı, tanımsız seçim) hedef sayılmaz: hatalı
    proje verisini cihaza yazmak, yanlış ayarı "DeviceMap böyle diyor"
    diye kalıcı hâle getirmek olurdu. Sebep çağırana döner ve ekranda
    görünür.
    """
    a = ALANLAR[alan]
    if not a.yaz:
        return "", ""
    if a.gizli:
        # Gizli alan `ekstra` içinde yok (DeviceMap parolaları ayıklanıyor);
        # değeri yalnız cihazın kendi kaydından gelir.
        ham = cihaz.pbx_password if alan == "sipParola" else None
    else:
        ham = env.proje_ayarlari(cihaz).get(a.yaz.lower())
    if ham in (None, "") and alan == "sipPbx":
        # PBX adresi DeviceMap'te ayrıca yazılmadıysa setin PISCU'sudur;
        # sette başka registrar yok.
        ham = env.piscu_ip() or ""
    if ham in (None, ""):
        return "", ""
    try:
        return _dogrula(alan, ham, cihaz.subtype or ""), ""
    except ValueError as exc:
        return "", f"DeviceMap: {exc}"


def hedef_detay(cihaz: Cihaz, env: Envanter, alan: str,
                grup: str | None = None) -> tuple[str, str, str]:
    """Etkin hedef değer, kaynağı ve proje verisiyle ilgili uyarı.

    Sıra: cihaza özel > gruba girilen > DeviceMap'teki proje değeri.
    """
    ozel = hedef_al(cihaz.id).get(alan)
    proje, uyari = _proje_hedefi(cihaz, env, alan)
    if ozel:
        return ozel, "cihaz", uyari
    grubun = grup_hedef_al(grup or "").get(alan)
    if grubun:
        return grubun, "grup", uyari
    return (proje, "proje", uyari) if proje else ("", "", uyari)


def hedef_of(cihaz: Cihaz, env: Envanter, alan: str,
             grup: str | None = None) -> tuple[str, str]:
    """Alanın etkin hedef değeri ve nereden geldiği."""
    deger, kaynak, _uyari = hedef_detay(cihaz, env, alan, grup)
    return deger, kaynak


def grup_proje_ozeti(env: Envanter,
                     cihazlar: list[Cihaz]) -> tuple[dict, list]:
    """Gruptaki cihazların DeviceMap değerleri: ortak olanlar ve olmayanlar.

    Gruba yazılacak değer kutusuna hazır değer koyabilmek için gerekiyor:
    bütün cihazlarda aynı olan ayar (tipin ses seviyesi gibi) kutuya
    yerleşir. Cihaza göre değişen ayar (dahili numara) YERLEŞMEZ — orada
    tek bir değer göstermek, kullanıcı kutuya dokunmadığı sürece doğru
    çalışsa da, bir harf değiştirdiğinde bütün gruba aynı numarayı
    yazdırırdı.
    """
    kumeler: dict[str, set] = {}
    for c in cihazlar:
        if c.yontem != "http":
            continue
        for ad in alt_yazilabilir(c.subtype or ""):
            if ALANLAR[ad].gizli:
                continue
            deger, _uyari = _proje_hedefi(c, env, ad)
            kumeler.setdefault(ad, set()).add(deger)
    ortak = {ad: next(iter(v)) for ad, v in kumeler.items()
             if len(v) == 1 and next(iter(v))}
    farkli = sorted(ad for ad, v in kumeler.items() if len(v) > 1)
    return ortak, farkli


# ── okuma ───────────────────────────────────────────────────────────────
def _duz_oku(cihaz: Cihaz, kimlik=None) -> dict:
    """Cihazın bütün okunabilir alanları — düzleştirilmiş sözlük.

    Handset'in mod alanları ana uçta değil `system/modes` ucundadır;
    okuma katmanı ikisini birleştirdiği için burada tek sözlük görünür.

    Ek uç YALNIZ gereken tipte istenir. Bilinen bütün ek uçları denemek
    ekranı gözle görülür şekilde bekletiyordu: olmayan altı uç için altı
    istek, her biri saniyelerce (cihaz kapalıysa zaman aşımı kadar).
    """
    ek = ("system/modes",) if (cihaz.subtype or "") == "Handset" else ()
    veri = okuma.anons_oku(cihaz.ip, kimlik, ek_uclar=ek)
    return veri.get("duz") or okuma.duzle(veri.get("ayarlar") or {})


def _mevcut(duz: dict, alan: str):
    a = ALANLAR[alan]
    return okuma.sec(duz, *a.okunacak(), disla=a.disla)


def _mevcutlar(duz: dict, alt: str | None) -> dict:
    return {ad: _mevcut(duz, ad) for ad in alt_alanlari(alt)}


def cek(cihaz: Cihaz, env: Envanter, kimlik=None,
        grup: str | None = None) -> dict:
    """Cihazdaki mevcut değerleri okur ve hedeflerle karşılaştırır."""
    if cihaz.yontem != "http":
        raise UygulanmazHatasi(
            "Bu cihaz türünde konfigürasyon okuma/yazma tanımlı değil")

    return _satirlar(cihaz, env, _duz_oku(cihaz, kimlik), grup)


def _satirlar(cihaz: Cihaz, env: Envanter, duz: dict,
              grup: str | None = None) -> dict:
    """Okunmuş değerlerden ekran satırları. Cihaza ikinci kez gidilmez —
    yazma sonrası doğrulama ile ekran verisi aynı okumayı paylaşır."""
    alt = cihaz.subtype or ""
    mevcut = _mevcutlar(duz, alt)
    ozel = hedef_al(cihaz.id)

    satir = []
    for ad in alt_alanlari(alt):
        a = ALANLAR[ad]
        m = mevcut.get(ad)
        hedef, kaynak, uyari = ("", "", "") if not a.yaz \
            else hedef_detay(cihaz, env, ad, grup)
        # Gizli alanın değeri hiçbir sütunda dışarı çıkmaz; karşılaştırma
        # sunucuda yapılır, arayüz yalnız sonucu ve kaynağını görür.
        satir.append({
            "alan": ad, "etiket": a.etiket, "bolum": a.bolum,
            "mevcut": "" if a.gizli else _gosterim(ad, m),
            "mevcutVar": m not in (None, ""),
            "hedef": "" if a.gizli else str(hedef or ""),
            "hedefVar": bool(hedef),
            "kaynak": kaynak,
            "ozel": "" if a.gizli else str(ozel.get(ad, "")),
            "ozelVar": bool(ozel.get(ad)),
            "duzenlenebilir": bool(a.yaz),
            "gizli": a.gizli,
            "uyari": uyari,
            "sonuc": _sonuc(ad, m, hedef),
        })
    return {"cihazId": cihaz.id, "grup": grup or "", "alt": alt,
            "satirlar": satir}


# Ondalık alanlarda cihaz değeri float32 saklıyor: 2.4 yazıldıktan sonra
# 2.4000000953674316 okunuyor. Tam eşitlik arayınca yazılmış bir eşik
# "cihaz yazmadı" görünüyordu; tolerans, adım büyüklüğünün (0,1) çok
# altında kalacak kadar küçük.
ONDALIK_TOLERANS = 1e-3


def _esit(a, b, tur: str | None = None) -> bool:
    """Cihaz sayıyı 100, kullanıcı "100" yazıyor; ikisi aynı değerdir."""
    m, h = str(a).strip(), str(b).strip()
    if m == h:
        return True
    try:
        mf, hf = float(m.replace(",", ".")), float(h.replace(",", "."))
    except ValueError:
        return False
    if tur == "ondalik":
        return abs(mf - hf) <= ONDALIK_TOLERANS
    return mf == hf


def _gosterim(alan: str, deger):
    """Cihazdan okunan değerin ekranda görünecek hâli.

    Ondalık alanlarda float32 gürültüsü kırpılır (2.4000000953674316 →
    2.4); yuvarlama yalnız gösterimdedir, karşılaştırma ham değerle
    yapılır.
    """
    if deger in (None, ""):
        return ""
    if ALANLAR[alan].tur != "ondalik":
        return str(deger)
    try:
        return f"{round(float(deger), 3):g}"
    except (TypeError, ValueError):
        return str(deger)


def _sonuc(alan: str, mevcut, hedef) -> str:
    if hedef in (None, ""):
        return "hedef_yok"
    if mevcut in (None, ""):
        return "okunamadi"
    return "uyuyor" if _esit(mevcut, hedef, ALANLAR[alan].tur) else "farkli"


# ── yazma ───────────────────────────────────────────────────────────────
def _yaz_degeri(alan: str, deger: str):
    """Hedef metnini cihazın beklediği JSON türüne çevirir."""
    a = ALANLAR[alan]
    d = str(deger).strip()
    if a.tur == "ondalik":
        return float(d.replace(",", "."))
    if a.tur in ("tamsayi", "secim"):
        try:
            return int(float(d))
        except ValueError:
            return d
    return d


_KOTU = ("error", "fail", "invalid", "reject", "missing", "not found")


def _istek(cihaz: Cihaz, uc: str, yuk: dict, kimlik=None) -> str:
    auth = tuple(kimlik) if kimlik else None
    try:
        r = requests.post(f"http://{cihaz.ip}:{ayar.ANONS_PORT}/{uc}",
                          json=yuk, timeout=ayar.OKUMA_TIMEOUT, auth=auth,
                          headers={"Content-Type": "application/json"})
    except Exception as exc:
        raise sinifla(exc)
    if r.status_code in (401, 403):
        raise KimlikHatasi("Cihaz kullanıcı adı/parola istiyor")
    # Cevap gövdesi düz metin olabiliyor ("Missing required fields"); hata
    # mesajına eklenir, yoksa kullanıcı hangi alanın eksik olduğunu
    # göremiyor.
    metin = (r.text or "").strip()[:120]
    if r.status_code >= 400:
        raise DogrulamaHatasi(
            f"Cihaz {uc} ucunda yazmayı reddetti (HTTP {r.status_code})"
            + (f": {metin}" if metin else ""))
    if any(k in metin.lower() for k in _KOTU):
        raise DogrulamaHatasi(f"Cihaz {uc} ucunda yazmayı reddetti: {metin}")
    return metin


def _yeniden_baslamayi_bekle(cihaz: Cihaz, kimlik=None,
                             onceki_uptime=None) -> bool:
    """Cihaz yeniden başlayıp cevap verene kadar bekler.

    Yazmadan hemen sonra okunan değer hâlâ eski süreçten gelebilir; bu
    yüzden yalnız "cevap verdi" yetmez, çalışma süresinin geri sarmış
    olması beklenir. Süre dolarsa False döner ve doğrulama yine denenir.
    """
    bitis = time.monotonic() + YENIDEN_BASLAMA_BEKLEME
    time.sleep(min(2.0, YENIDEN_BASLAMA_BEKLEME))
    while time.monotonic() < bitis:
        try:
            duz = _duz_oku(cihaz, kimlik)
        except Exception:
            time.sleep(1.0)
            continue
        u = okuma.sec(duz, *okuma.K_UPTIME)
        try:
            if onceki_uptime is None or float(u) < float(onceki_uptime):
                return True
        except (TypeError, ValueError):
            return True
        time.sleep(1.0)
    return False


def uygula(cihaz: Cihaz, env: Envanter, kimlik=None,
           grup: str | None = None) -> dict:
    """Hedef değerleri cihaza yazar ve yazımı okuyarak doğrular.

    Yalnız cihazdaki değerden FARKLI olan alanlar gönderilir: SIP ucu
    cihazı yeniden başlattığı için, zaten uyuşan bir ayar uğruna cihazı
    karartmak istemiyoruz.

    HTTP 200 tek başına başarı sayılmaz: yazımdan sonra ayarlar tekrar
    okunur ve değerin gerçekten değiştiği görülür. Cihaz tanımadığı bir
    alanı hata vermeden yok sayabiliyor; doğrulama olmadan "yazıldı"
    demek, yazılmamış bir ayarı yazılmış saymak olurdu.
    """
    if cihaz.yontem != "http":
        raise UygulanmazHatasi(
            "Bu cihaz türünde konfigürasyon yazma tanımlı değil")

    alt = cihaz.subtype or ""
    duz = _duz_oku(cihaz, kimlik)
    mevcut = _mevcutlar(duz, alt)
    onceki_uptime = okuma.sec(duz, *okuma.K_UPTIME)

    hedef: dict[str, str] = {}
    for ad in alt_yazilabilir(alt):
        deger, _kaynak = hedef_of(cihaz, env, ad, grup)
        if str(deger).strip():
            hedef[ad] = str(deger).strip()
    if not hedef:
        raise ValueError("Yazılacak hedef değer yok")

    # Cihazda hâlihazırda doğru olan alan gönderilmez.
    degisen = [ad for ad, d in hedef.items()
               if not _esit(mevcut.get(ad), d, ALANLAR[ad].tur)]
    if not degisen:
        return {**_satirlar(cihaz, env, duz, grup), "yazilanAlanlar": [],
                "yazilanUclar": [], "yenidenBaslatildi": False}

    # Değişen alanlar uçlarına dağıtılır; kısmi gövde kabul etmeyen uçların
    # zorunlu alanları hedeften ya da cihazdan tamamlanır.
    kova: dict[str, dict[str, str]] = {}
    for ad in degisen:
        uc = uc_of(ad, alt)
        if uc:
            kova.setdefault(uc, {})[ad] = hedef[ad]

    yazilan_uclar = []
    for uc in UC_SIRASI:
        if uc not in kova:
            continue
        govde = dict(kova[uc])
        for ad in ZORUNLU.get(uc, ()):
            if ad in govde or ad not in alt_yazilabilir(alt):
                continue
            d = hedef.get(ad) or mevcut.get(ad)
            if d in (None, ""):
                raise DogrulamaHatasi(
                    f"{ALANLAR[ad].etiket} bilinmiyor — cihaz {uc} ucunda bu "
                    "alanı zorunlu istiyor")
            govde[ad] = str(d)
        _istek(cihaz, uc,
               {ALANLAR[ad].yaz: _yaz_degeri(ad, d)
                for ad, d in govde.items()}, kimlik)
        yazilan_uclar.append(uc)

    yeniden = any(uc in YENIDEN_BASLATAN for uc in yazilan_uclar)
    if yeniden:
        _yeniden_baslamayi_bekle(cihaz, kimlik, onceki_uptime)

    # Yazımdan sonra tekrar okunur: hangi alanın gerçekten oturduğu
    # ancak böyle bilinir. Tek okuma hem doğrulamayı hem ekran satırlarını
    # besler; 12 intercomlu bir koşuda ikinci tur okuma pahalı.
    son_duz = _duz_oku(cihaz, kimlik)
    sonuc = _satirlar(cihaz, env, son_duz, grup)
    yeni = _mevcutlar(son_duz, alt)
    tutmayan = [ALANLAR[ad].etiket for ad in hedef
                if not _esit(yeni.get(ad), hedef[ad], ALANLAR[ad].tur)]
    if tutmayan:
        raise DogrulamaHatasi(
            "Cihaz bu alanları yazmadı: " + ", ".join(tutmayan))
    return {**sonuc, "yazilanAlanlar": [ALANLAR[ad].etiket for ad in degisen],
            "yazilanUclar": yazilan_uclar, "yenidenBaslatildi": yeniden}
