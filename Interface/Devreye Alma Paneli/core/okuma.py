#!/usr/bin/env python3
"""Cihaz okuma — hangi tip hangi yöntemle okunur.

Tek giriş noktası `cihaz_oku()`. Çağıran taraf (tarama işi, hafif
yenileme, kimlik doğrulama) hangi protokolün konuşulduğunu bilmez;
yalnızca envanterden gelen bir Cihaz nesnesi verir.

Kimlik: kimliği bu modül ARAMAZ, çağıran verir. Böylece kimlik doğrulama
denemesi ile normal okuma aynı kod yolundan geçer — "formda çalıştı ama
taramada çalışmadı" ayrımı doğmaz.
"""
from __future__ import annotations

import re
import subprocess

import requests

from . import ayar, dogrulama, switch_okuma, video_okuma
from .device_map import Cihaz
from .hata import (DogrulamaHatasi, KimlikHatasi, UlasilamadiHatasi,
                   UygulanmazHatasi, sinifla)
from .kategori import YONTEMLER

# Announcement cihazlarının doğrulanmış ucu. intercom_ip_assign.py bu ucu
# kullanıyor; ek uçlar yalnızca varsa okunur, yoksa başarı bozulmaz.
ANONS_ANA = "system/settings"
# Ek uçlar cihaz türüne göre var ya da yok. Handset'te `system/modes`
# gain alanlarını da veriyor; olmayan uç 404 döner ve atlanır.
ANONS_EK = ("system/modes", "system/info", "system/status", "system/sip",
            "system/audio", "system/network")


# ───────────────────────────────────────────────────── alan yardımcıları ──
def duzle(nesne, on: str = "") -> dict:
    """İç içe JSON'u {kucukharf.anahtar: deger} sözlüğüne indirger."""
    cikan: dict = {}
    if isinstance(nesne, dict):
        for k, v in nesne.items():
            anahtar = f"{on}{k}".lower()
            if isinstance(v, (dict, list)):
                cikan.update(duzle(v, f"{anahtar}."))
            else:
                cikan[anahtar] = v
    elif isinstance(nesne, list):
        for i, v in enumerate(nesne):
            cikan.update(duzle(v, f"{on}{i}."))
    return cikan


def _sadele(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def sec(duz: dict, *adaylar, disla=()):
    """Aday anahtar adlarından ilk dolu değeri döndürür.

    Üç aşama: tam ad, son parça, uzun alt dize. Üretici değiştikçe alan
    adları değişiyor; tek isme bağlanmak cihazı "veri vermiyor" gösteriyor.
    """
    def dolu(v):
        return v not in ("", None) and str(v).strip() != ""

    for aday in adaylar:
        v = duz.get(aday.lower())
        if dolu(v):
            return v

    kuyruk = {k: _sadele(k.rsplit(".", 1)[-1]) for k in duz}
    for aday in adaylar:
        na = _sadele(aday)
        for k, v in duz.items():
            if kuyruk[k] == na and dolu(v):
                return v

    kotu = tuple(_sadele(x) for x in disla)
    tam = {k: _sadele(k) for k in duz}
    for aday in adaylar:
        na = _sadele(aday)
        if len(na) < 7:
            continue
        for k, v in duz.items():
            if na in tam[k] and dolu(v) and not any(b in tam[k] for b in kotu):
                return v
    return None


K_SURUM = ("firmwareversion", "firmware", "swversion", "softwareversion",
           "appversion", "fwversion", "version", "buildversion", "build")
K_SERI = ("serialnumber", "serialno", "serial", "sn", "devicesn",
          "deviceserial", "deviceid", "chipid", "uuid")
K_UPTIME = ("uptimeseconds", "uptimesec", "uptime", "systemuptime",
            "runtime", "runningtime")
K_PBX = ("pbxip", "pbx_ip", "sippbx", "sipserver", "pbxserver", "sipproxy",
         "registrar", "serverip", "proxy", "pbx", "server")
K_EXT = ("pbxextension", "pbx_extension", "sipextension", "extension", "ext")
K_SPK = ("speakervolume", "speaker_volume", "speakerlevel", "callvolume",
         "outputvolume", "playvolume", "speaker", "volume")
K_MIC = ("microphonevolume", "microphone_volume", "micvolume", "miclevel",
         "inputvolume", "recordvolume", "microphone", "mic")
# Gain, ses seviyesinden ayrı bir alandır (cihazda speakerGain / micGain).
# Seviye aramasında "gain" elendiği için ikisi birbirine karışmaz.
K_SPK_GAIN = ("speakergain", "speaker_gain", "spkgain", "outputgain",
              "playgain", "amplifiergain")
K_MIC_GAIN = ("microphonegain", "microphone_gain", "micgain", "mic_gain",
              "inputgain", "recordgain")
# SIP Arama No: cihazın çağrı başlattığı hedef (pbxOutExtension). Kendi
# dahili numarasıyla (pbxExtension) karışmaması için ayrı aday listesi.
K_OUT = ("pbxoutextension", "pbx_out_extension", "pbxoutext",
         "outextension", "out_extension", "outext",
         "outboundextension", "outbound_extension", "outboundext",
         "outboundcallextension", "outboundnumber", "outboundcallnumber",
         "calloninput0", "destinationnumber", "dialnumber", "callnumber")


# ────────────────────────────────────────────────────────── okuyucular ────
def anons_oku(ip: str, kimlik=None, timeout: float | None = None) -> dict:
    """Amplifier / Handset / Intercom / UIC — /api/v1 HTTP API."""
    sure = timeout if timeout is not None else ayar.OKUMA_TIMEOUT
    taban = f"http://{ip}:{ayar.ANONS_PORT}/api/v1"
    auth = tuple(kimlik) if kimlik else None

    try:
        r = requests.get(f"{taban}/{ANONS_ANA}", timeout=sure, auth=auth)
    except Exception as exc:
        raise sinifla(exc)
    if r.status_code in (401, 403) or "WWW-Authenticate" in r.headers:
        raise KimlikHatasi("Cihaz kullanıcı adı/parola istiyor")
    if r.status_code >= 400:
        raise DogrulamaHatasi(f"Cihaz HTTP {r.status_code} döndürdü")
    try:
        govde = r.json()
    except ValueError:
        tur = r.headers.get("Content-Type", "?")
        raise DogrulamaHatasi(
            f"Cihaz JSON yerine {tur} döndürdü — beklenen ayar yanıtı değil")
    if not isinstance(govde, dict) or not govde:
        raise DogrulamaHatasi("Cihaz boş / beklenmeyen bir ayar yanıtı döndürdü")

    duz = duzle(govde)
    # Ek uçlar bonus: yoksa da cihaz okunmuş sayılır.
    for uc in ANONS_EK:
        try:
            e = requests.get(f"{taban}/{uc}", timeout=min(sure, 2.5), auth=auth)
            if e.ok:
                duz.update(duzle(e.json()))
        except Exception:
            pass

    return {
        "surum": sec(duz, *K_SURUM) or "",
        "seri": sec(duz, *K_SERI) or "",
        "uptime": sec(duz, *K_UPTIME),
        "sipPbx": sec(duz, *K_PBX) or "",
        "sipDahili": sec(duz, *K_EXT,
                         disla=("outbound", "outext", "pbxout", "dial")) or "",
        "sipArama": sec(duz, *K_OUT) or "",
        "hoparlor": sec(duz, *K_SPK, disla=("gain",)),
        "mikrofon": sec(duz, *K_MIC, disla=("gain",)),
        "hoparlorGain": sec(duz, *K_SPK_GAIN),
        "mikrofonGain": sec(duz, *K_MIC_GAIN),
        "ayarlar": govde,
    }


def paket_bilgisi(ham: str) -> dict:
    """`dumpsys package <paket>` çıktısından uygulama künyesi.

    Aranan satırlar cihazda şu biçimde geliyor:

        versionCode=1 minSdk=21 targetSdk=35
        versionName=0.0.5
        firstInstallTime=2026-07-07 13:13:40

    `versionName` yoksa paket kurulu değildir; çağıran bunu hata sayar.
    """
    def bul(kalip: str) -> str:
        e = re.search(kalip, ham)
        return e.group(1).strip() if e else ""

    return {
        "surum": bul(r"versionName=(\S+)"),
        "surumKodu": bul(r"versionCode=(\d+)"),
        "minSdk": bul(r"minSdk=(\d+)"),
        "hedefSdk": bul(r"targetSdk=(\d+)"),
        "kurulum": bul(r"firstInstallTime=(.+)"),
        "guncelleme": bul(r"lastUpdateTime=(.+)"),
    }


def sip_gunlugu(ham: str) -> dict:
    """AnnounceSip günlüğünden SIP kaydı.

        SIP engine started: sip:6001@10.1.1.1:5060 (UDP)
        Registration state=registered code=200

    Günlük döngüsel tampondadır; en YENİ satır esas alınır. Kayıt satırı
    hiç yoksa alanlar boş döner — bu tek başına hata değildir, tampon
    dönmüş olabilir.
    """
    veri = {"sipDahili": "", "sipPbx": "", "sipPort": "", "sipTasima": "",
            "sipKayit": "", "sipKod": ""}

    uclar = re.findall(r"sip:(\d+)@([\d.]+)(?::(\d+))?(?:\s*\((\w+)\))?", ham)
    if uclar:
        dahili, pbx, port, tasima = uclar[-1]
        veri.update(sipDahili=dahili, sipPbx=pbx, sipPort=port,
                    sipTasima=tasima)

    kayitlar = re.findall(r"Registration state=(\S+)(?:\s+code=(\d+))?", ham)
    if kayitlar:
        durum, kod = kayitlar[-1]
        veri.update(sipKayit=durum, sipKod=kod)
    return veri


def adb_oku(ip: str, timeout: int | None = None) -> dict:
    """Compartment LCD — Android; getprop + dumpsys + logcat.

    Cihazın "aktif" sayılması için adb'ye bağlanmak yetmez: panel
    uygulamasının sürümü de okunabilmelidir. Bağlanıp veri alamadığımız
    cihaz yeşil görünürse kontrol listesi boş sütunlarla "doğrulandı"
    der; sahada bu, kurulmamış uygulamayı kurulmuş göstermek demek.
    """
    sure = timeout or ayar.ADB_TIMEOUT
    hedef = f"{ip}:{ayar.ADB_PORT}"

    def calistir(*args) -> str:
        r = subprocess.run(["adb", "-s", hedef, *args],
                           capture_output=True, text=True, timeout=sure)
        return r.stdout.strip()

    try:
        subprocess.run(["adb", "connect", hedef], capture_output=True,
                       text=True, timeout=sure)
    except FileNotFoundError:
        raise UygulanmazHatasi(
            "adb komutu bulunamadı — Compartment LCD okunamıyor")
    except subprocess.TimeoutExpired:
        raise UlasilamadiHatasi("adb connect zaman aşımına uğradı")

    try:
        seri = calistir("shell", "getprop", "ro.serialno")
        if not seri:
            # adb bağlanamadıysa stdout boş döner; bu bir cihaz erişim
            # sorunudur, "beklenmeyen hata" değil.
            raise UlasilamadiHatasi(
                "Cihaza adb ile bağlanılamadı (5555 portu kapalı olabilir)")
        tz = calistir("shell", "getprop", "persist.sys.timezone")
        ham = calistir("shell", "cat", "/proc/uptime")

        paket = paket_bilgisi(calistir("shell", "dumpsys", "package",
                                       ayar.ADB_PAKET))
        if not paket["surum"]:
            raise DogrulamaHatasi(
                f"{ayar.ADB_PAKET} sürümü okunamadı — uygulama kurulu değil "
                "olabilir (dumpsys package versionName boş)")

        sip = sip_gunlugu(calistir("logcat", "-d", "-s",
                                   f"{ayar.ADB_LOG_ETIKET}:I", "*:S"))

        return {
            "seri": seri,
            "saatDilimi": tz,
            "uptime": ham.split()[0] if ham else None,
            "paket": ayar.ADB_PAKET,
            **paket,
            **sip,
        }
    except subprocess.TimeoutExpired:
        raise UlasilamadiHatasi("adb komutu zaman aşımına uğradı")
    finally:
        try:
            subprocess.run(["adb", "disconnect", hedef], capture_output=True,
                           text=True, timeout=sure)
        except Exception:
            pass


def _telemetriden(cihaz: Cihaz, telemetri) -> dict:
    """MQTT DeviceMap kaydından ortak alanlar."""
    kayit = telemetri.kayit(cihaz.ip) if telemetri else None
    if not kayit:
        raise DogrulamaHatasi(
            "Cihaz canlı DeviceMap telemetrisinde bulunamadı")
    durum = kayit.get("Status") or {}
    if not durum.get("NoError"):
        raise UygulanmazHatasi(
            "Cihaz telemetride pasif bildiriliyor — doğrudan okuma yöntemi yok")
    return {
        "surum": durum.get("Version") or "",
        "seri": kayit.get("SerialNumber") or "",
        "uptime": durum.get("Uptime"),
        "kaynakNot": "Canlı DeviceMap (retained)",
    }


def _appstatusdan(cihaz: Cihaz, telemetri) -> dict:
    """PISCU / HMI — ALFA/AppStatus mesajı.

    AppStatus yükünde çalışma süresi YOK (ClientId, DeviceIP, HWID,
    Status, Version). Uptime aynı cihazın DeviceMap kaydında duruyor;
    ikisi birleştirilmezse bu iki cihazın "Çalışma Süresi" sütunu hep boş
    kalıyor.
    """
    kelime = "PISCU" if cihaz.type == "PISCU" else "MCP"
    kayit = telemetri.uygulama_kaydi(cihaz.ip, kelime) if telemetri else None
    if not kayit:
        raise DogrulamaHatasi(
            f"{ayar.MQTT_APP_STATUS_PREFIX}/... altında {kelime} mesajı yok")
    uptime = kayit.get("Uptime")
    if uptime in (None, "", -1):
        uptime = _harita_uptime(cihaz, telemetri)
    return {
        "surum": kayit.get("Version") or "",
        "seri": kayit.get("HWID") or "",
        "uptime": uptime,
        "kaynakNot": kayit.get("Status") or "",
    }


def _harita_uptime(cihaz: Cihaz, telemetri):
    """Cihazın DeviceMap kaydındaki Uptime (yoksa None).

    Kapalı cihazlarda PISCU son bilinen değeri hatırlıyor ve Uptime -1
    geliyor; -1 çalışma süresi değildir, yazılmaz.
    """
    kayit = telemetri.kayit(cihaz.ip) if telemetri else None
    durum = (kayit or {}).get("Status") or {}
    u = durum.get("Uptime")
    try:
        return u if float(u) >= 0 else None
    except (TypeError, ValueError):
        return None


# ───────────────────────────────────────────────────────── dağıtıcı ───────
def kimlik_grubu(cihaz: Cihaz) -> str | None:
    return YONTEMLER.get(cihaz.yontem, {}).get("grup")


def kimlik_ister(cihaz: Cihaz) -> bool:
    return bool(YONTEMLER.get(cihaz.yontem, {}).get("kimlik_ister"))


def cihaz_oku(cihaz: Cihaz, kimlik=None, telemetri=None,
              timeout: float | None = None,
              beklenen_ntp: str | None = None,
              pbx_ip: str | None = None) -> dogrulama.Sonuc:
    """Bir cihazı okur ve renkli sonuç döndürür. İstisna fırlatmaz."""
    yontem = cihaz.yontem
    try:
        if yontem == "kyland":
            veri = switch_okuma.oku(cihaz.ip, kimlik, timeout)
            # Switch kendi süresini vermezse DeviceMap'teki Uptime'a düşülür.
            calisma = veri["calisma"]
            if calisma in (None, ""):
                calisma = _harita_uptime(cihaz, telemetri)
            return dogrulama.basarili({
                "surum": veri["surum"], "model": veri["model"],
                "mac": veri["mac"], "cihazAdi": veri["ad"],
                "calisma": dogrulama.uptime_metni(calisma),
            }, yontem)

        if yontem == "isapi":
            veri = video_okuma.oku(cihaz.ip, kimlik, timeout,
                                   beklenen_ntp=beklenen_ntp)
            return dogrulama.basarili({
                "surum": veri["surum"], "seri": veri["seri"],
                "model": veri["model"], "agZaman": veri["agZaman"],
            }, yontem)

        if yontem == "http":
            veri = anons_oku(cihaz.ip, kimlik, timeout)
            return dogrulama.basarili({
                "surum": veri["surum"], "seri": veri["seri"],
                "calisma": dogrulama.uptime_metni(veri["uptime"]),
                "sipPbx": veri["sipPbx"], "sipDahili": veri["sipDahili"],
                "sipArama": veri["sipArama"],
                "hoparlor": veri["hoparlor"], "mikrofon": veri["mikrofon"],
                "hoparlorGain": veri["hoparlorGain"],
                "mikrofonGain": veri["mikrofonGain"],
            }, yontem)

        if yontem == "adb":
            veri = adb_oku(cihaz.ip)
            kayit = veri["sipKayit"]
            # Dahili numara cihazın günlüğüne yalnız uygulama açılışında
            # yazılıyor; tampon dönmüşse orada yok. Aynı numara broker'da
            # ALFA/SipPort altında retained duruyor — cihazı yeniden
            # başlatmadan oradan alınır, kaynağı açıkça yazılır.
            dahili, kaynak = veri["sipDahili"], "cihaz günlüğü"
            if not dahili and telemetri is not None:
                dahili = telemetri.sip_dahili(cihaz.ip)
                kaynak = f"{ayar.MQTT_SIP_PORT_PREFIX}/{cihaz.ip}"
            # PBX adresi de aynı günlük satırında; o satır yoksa kayıtlı
            # olduğu PBX setin PISCU'sudur (sette başka registrar yok).
            # Yalnız cihaz "registered" derken yazılır — kayıtlı olmayan
            # cihaza PBX yazmak, olmayan bir bağlantıyı varmış gösterir.
            pbx, pbxKaynak = veri["sipPbx"], "cihaz günlüğü"
            if not pbx and pbx_ip and veri["sipKayit"].startswith("register"):
                pbx, pbxKaynak = pbx_ip, "proje (PISCU)"
            return dogrulama.basarili({
                "surum": veri["surum"], "seri": veri["seri"],
                "saatDilimi": veri["saatDilimi"],
                "calisma": dogrulama.uptime_metni(veri["uptime"]),
                "sipPbx": pbx, "sipDahili": dahili,
                "sipPbxKaynak": pbxKaynak if pbx else "",
                "sipDahiliKaynak": kaynak if dahili else "",
                "sipKayit": (f"{kayit} ({veri['sipKod']})"
                             if kayit and veri["sipKod"] else kayit),
                "paket": veri["paket"], "surumKodu": veri["surumKodu"],
                "hedefSdk": veri["hedefSdk"],
                "guncelleme": veri["guncelleme"],
            }, yontem, f"{ayar.ADB_PAKET} {veri['surum']} okundu")

        if yontem in ("mqtt", "app"):
            if telemetri is None or telemetri.hata:
                sebep = (telemetri.hata if telemetri else
                         "MQTT telemetrisi toplanmadı")
                return dogrulama.okunmadi(yontem, sebep)
            veri = (_appstatusdan(cihaz, telemetri) if yontem == "app"
                    else _telemetriden(cihaz, telemetri))
            return dogrulama.basarili({
                "surum": veri.get("surum", ""), "seri": veri.get("seri", ""),
                "calisma": dogrulama.uptime_metni(veri.get("uptime")),
                "not": veri.get("kaynakNot", ""),
            }, yontem)

        return dogrulama.uygulanmaz(
            yontem, "Bu cihaz türü için tanımlı okuma yöntemi yok")

    except Exception as exc:
        return dogrulama.hatadan(exc, yontem)
