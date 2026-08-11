#!/usr/bin/env python3
"""Devreye Alma Paneli — sabitler ve yol çözümlemesi.

Burada yalnızca uygulamanın her yerinden okunan değişmez değerler durur.
Kimlik bilgisi (kullanıcı adı / parola) BU DOSYADA YOKTUR ve hiçbir ayar
dosyasından okunmaz — bkz. core/kimlik.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ADI = "Devreye Alma Paneli"
KISA_AD = "DevreyeAlmaPaneli"
APP_VERSION = "0.9.5"

# Kaynaktan çalışırken bu dosyanın bir üstü; PyInstaller ile paketlenince
# veriler geçici klasöre açılır ve yolu sys._MEIPASS ile verilir.
_BURASI = Path(__file__).resolve().parent
KOK = _BURASI.parent
PAKETLI = bool(getattr(sys, "frozen", False))


def kaynak_dizini() -> Path:
    temel = getattr(sys, "_MEIPASS", None)
    return Path(temel) if temel else KOK


def veri_dosyasi(ad: str, *kaynak_yolu: str) -> Path:
    """Uygulamayla gelen veri dosyasının yolu.

    Kaynaktan çalışırken dosya proje ağacındaki yerinde durur (`kaynak_yolu`,
    KOK'a göre; verilmezse KOK/ad). Paketlenince aynı dosya paketin köküne
    konur ve oradan okunur: pakette proje ağacı yoktur, `KOK.parent.parent`
    gibi yollar kurulum dizininin dışına düşer.
    """
    if PAKETLI:
        return kaynak_dizini() / ad
    return KOK.joinpath(*(kaynak_yolu or (ad,)))


STATIC_DIR = kaynak_dizini() / "static"
DEVICE_MAP = Path(os.environ.get("DEVICE_MAP_FILE")
                  or veri_dosyasi("DeviceMap.json"))
EXCEL_SABLON = veri_dosyasi("Yatakli_Saha_Cihaz_Dogrulama.xlsx")


def belgeler_dizini() -> Path:
    """Üretilen dosyaların yazıldığı yer — işletim sisteminin Belgeler'i.

    Uygulama paketlenince kurulum dizini salt okunur olabiliyor, kaynaktan
    çalışınca da çıktılar proje klasörüne karışıyordu. Kullanıcının
    dosyayı aradığı ilk yer Belgeler.
    """
    ozel = os.environ.get("CIKTI_DIZINI")
    if ozel:
        return Path(ozel).expanduser()
    ev = Path.home()
    # Linux'ta klasör adı yerelleştirilmiş olabilir; masaüstü ortamı yolu
    # XDG_DOCUMENTS_DIR ile bildirir.
    xdg = os.environ.get("XDG_DOCUMENTS_DIR")
    if xdg:
        return Path(os.path.expandvars(xdg)).expanduser()
    belgeler = ev / "Documents"
    return belgeler if belgeler.is_dir() else ev


CIKTI_DIZINI = belgeler_dizini()


def veri_dizini() -> Path:
    """Panelin kendi kalıcı verisini yazdığı yer.

    Buraya yalnız kullanıcının panelde ayarladığı değerler yazılır
    (konfigürasyon varsayılanları). PAROLA YAZILMAZ — ne cihaz kimliği ne
    SIP parolası; onlar yalnız bellekte durur (bkz. core/kimlik.py).

    Proje ağacına ya da DeviceMap'in yanına yazılmaz: kurulum dizini salt
    okunur olabiliyor ve DeviceMap klasörü projenin verisidir, panelin
    çalışma dosyası orada birikmemeli.
    """
    ozel = os.environ.get("PANEL_VERI_DIZINI")
    if ozel:
        return Path(ozel).expanduser()
    ev = Path.home()
    if sys.platform == "darwin":
        return ev / "Library" / "Application Support" / KISA_AD
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or (ev / "AppData" / "Roaming")) / KISA_AD
    return Path(os.environ.get("XDG_CONFIG_HOME") or (ev / ".config")) / KISA_AD


# Konfigürasyon ekranında girilen hedef değerler. Uygulama açılışında
# buradan yüklenir; parola alanları dosyaya hiç girmez.
def konfig_varsayilan_dosyasi() -> Path:
    return veri_dizini() / "konfig_varsayilanlari.json"


# ── betikler/ altındaki çalışan motorlar ────────────────────────────────
# Bu panel switch erişimini ve saha betiklerini yeniden yazmaz; çalışma
# anında dosya yolundan içe aktarır (bkz. core/betik.py). Paketlenirken bu
# üç dosya paketin köküne kopyalanır, o yüzden yol çözümü ikisini de bilir.
#
# switch_api.py aslen Switch Yönetim Paneli'nin dosyasıdır (o uygulama
# `syp` branch'inin kökünde yaşar); buradaki kopya panelin çalışması için
# durur ve o branch'le elle eşitlenir.
SWITCH_PANELI = Path(
    os.environ.get("SWITCH_PANEL_API")
    or veri_dosyasi("switch_api.py", "betikler", "switch_api.py"))
DEVICE_VERIFY = Path(
    os.environ.get("DEVICE_VERIFY_BETIGI")
    or veri_dosyasi("device_verify.py", "betikler", "device_verify.py"))
INTERCOM_IP_ASSIGN = Path(
    os.environ.get("IP_ATAMA_BETIGI")
    or veri_dosyasi("intercom_ip_assign.py",
                    "betikler", "intercom_ip_assign.py"))

# ─────────────────────────────────────────────────────────── ağ / portlar ──
KYLAND_PORT = int(os.environ.get("KYLAND_HTTP_PORT", 80))

# Ön panelin fiziksel dizilimi. Sahadaki SICOM3028GPT: 24 PoE + 4 uplink.
# Panel, DeviceMap'te cihazı olan portları değil, cihazın gerçek yüzünü
# çizer; boş portlar da yerinde durur, yoksa harita panele benzemiyor.
SWITCH_POE_PORT = int(os.environ.get("SWITCH_POE_PORT", 24))
SWITCH_UPLINK_PORT = int(os.environ.get("SWITCH_UPLINK_PORT", 4))
VIDEO_PORT = int(os.environ.get("VIDEO_HTTP_PORT", 80))
ANONS_PORT = int(os.environ.get("ARDUINO_HTTP_PORT", 80))
MQTT_PORT = int(os.environ.get("PISCU_MQTT_PORT", 1883))
ADB_PORT = int(os.environ.get("COMPARTMENT_LCD_ADB_PORT", 5555))

# Compartment LCD'de çalışan panel uygulaması. Sürüm bilgisinin doğru
# kaynağı budur: `ro.build.display.id` Android build kimliğidir, uygulama
# sürümü değil (bkz. dumpsys package ... versionName).
ADB_PAKET = os.environ.get("COMPARTMENT_LCD_PAKET", "com.piton.train_lcd_panel")
# SIP kaydını uygulamanın kendi günlüğünden okuyoruz; PBX'te ARI hesabı yok.
ADB_LOG_ETIKET = os.environ.get("COMPARTMENT_LCD_LOG_ETIKET", "AnnounceSip")

MQTT_DEVICE_MAP_TOPIC = os.environ.get("PISCU_DEVICE_MAP_TOPIC", "ALFA/DeviceMap")
MQTT_APP_STATUS_PREFIX = os.environ.get("PISCU_APP_STATUS_PREFIX", "ALFA/AppStatus")
# Cihaz başına SIP dahili numarası: ALFA/SipPort/10.1.1.40 -> {"SipPort": 6001}
MQTT_SIP_PORT_PREFIX = os.environ.get("PISCU_SIP_PORT_PREFIX", "ALFA/SipPort")

# ────────────────────────────────────────────────────────────── süreler ────
# Tam taramada tek cihaz için üst sınır. Kısa tutulur: 30+ cihazlık bir set
# taranırken tek bir sessiz cihaz bütün turu bekletmemeli.
OKUMA_TIMEOUT = float(os.environ.get("OKUMA_TIMEOUT", 5.0))
# Kimlik denemesi kullanıcıyı bekletir; biraz daha cömert.
KIMLIK_TIMEOUT = float(os.environ.get("KIMLIK_TIMEOUT", 6.0))
MQTT_TIMEOUT = float(os.environ.get("MQTT_TIMEOUT", 4.0))
ADB_TIMEOUT = int(os.environ.get("ADB_TIMEOUT", 12))
# APK kurulumu okumadan uzun sürüyor: dosya cihaza itiliyor, sonra paket
# yöneticisi kuruyor. Okuma zaman aşımıyla aynı olamaz.
ADB_KURULUM_TIMEOUT = int(os.environ.get("ADB_KURULUM_TIMEOUT", 180))
TARAMA_WORKER = int(os.environ.get("TARAMA_WORKER", 12))

# Aynı anda kaç cihaza yazılım yüklenir. Tarama kadar yüksek tutulmaz:
# her yükleme cihazı yeniden başlatıyor ve sonrasında sürüm doğrulanana
# kadar bekleniyor; bir switch'in arkasındaki 12 cihazı birden karartmak
# hem PoE bütçesini hem de sahadaki kişinin "ne oluyor" görüşünü zorlar.
# Dördü, 12 intercomluk bir seti sırayla yapmanın dörtte birine indiriyor.
FIRMWARE_WORKER = int(os.environ.get("FIRMWARE_WORKER", 4))

# Aynı anda kaç cihaza konfigürasyon yazılır. Sırayla yürüdüğünde her
# cihazın okuma + yazma + doğrulama beklemesi uç uca ekleniyordu; SIP
# yazılan cihaz bir de yeniden başlıyor. Firmware ile aynı genişlikte
# tutuluyor: yazma cihazı yeniden başlatabildiği için tarama kadar
# geniş olmamalı.
KONFIG_WORKER = int(os.environ.get("KONFIG_WORKER", FIRMWARE_WORKER))

# ──────────────────────────────────────────────────────────── doğrulama ────
BEKLENEN_TZ = os.environ.get("EXPECTED_TIMEZONE", "CST-3:00:00")
BEKLENEN_MASKE = os.environ.get("EXPECTED_SUBNET_MASK", "255.255.0.0")

# Yapılandırılmamış cihazın fabrikadan geldiği adres. Tren setine göre
# DEĞİŞMEZ: cihaz kutudan çıkarken hangi sete gideceğini bilmiyor, hepsi
# aynı adresle geliyor. Şablon (10.n.1.12) çözmek, set 8'de cihazı
# 10.8.1.12'de aratıp hiç bulamamak demekti.
FABRIKA_IP = os.environ.get("INTERCOM_FACTORY_IP", "10.1.1.12")

# Tren seti (IP şablonundaki n). Dışarıdan gelen her set numarası bu
# aralıkta olmak zorunda — istemci ne gönderirse göndersin.
#
# Set numarası doğrudan IP'nin ikinci oktetine giriyor (10.n.1.x), o yüzden
# sınır geçerli oktet aralığıdır. Sahada set numarası sabit bir listeden
# gelmiyor (49, 112 gibi numaralar da kullanılıyor); daha dar bir üst sınır
# yalnız gerçek setleri dışarıda bırakırdı.
SET_MIN, SET_MAX = 1, 254

# API gövdesi üst sınırı. Yerel servis olsa da sınırsız gövde okunmaz.
GOVDE_SINIRI = 64 * 1024

# Hafif yenilemede aynı turda okunacak en fazla cihaz sayısı.
HAFIF_SINIR = 64
# Hafif yenileme kaç cihazı aynı anda okur. Sırayla okumak, arayüzün birkaç
# saniyede bir yenileme isteğini anlamsız kılıyordu: 17 doğrulanmış cihazlık
# bir sette tek turun kendisi yedi saniye sürüyordu. Bu tur yalnız YEŞİL
# cihazlara gider — hepsi cevap veriyor, zaman aşımı beklenmiyor — o yüzden
# taramayla aynı genişlikte olması cihazları taramadan fazla yormaz.
HAFIF_WORKER = int(os.environ.get("HAFIF_WORKER", TARAMA_WORKER))
