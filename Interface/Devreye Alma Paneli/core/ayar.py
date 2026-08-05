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
APP_VERSION = "0.1.0"

# Kaynaktan çalışırken bu dosyanın bir üstü; PyInstaller ile paketlenince
# veriler geçici klasöre açılır ve yolu sys._MEIPASS ile verilir.
_BURASI = Path(__file__).resolve().parent
KOK = _BURASI.parent


def kaynak_dizini() -> Path:
    temel = getattr(sys, "_MEIPASS", None)
    return Path(temel) if temel else KOK


STATIC_DIR = kaynak_dizini() / "static"
DEVICE_MAP = Path(os.environ.get("DEVICE_MAP_FILE") or (KOK / "DeviceMap.json"))
EXCEL_SABLON = KOK / "Yatakli_Saha_Cihaz_Dogrulama.xlsx"


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

# Switch Yönetim Paneli'nin çalışan backend'i. Switch erişimi orada
# doğrulanmış haliyle kullanılır; burada ikinci bir uygulama yazılmaz.
SWITCH_PANELI = Path(
    os.environ.get("SWITCH_PANEL_API")
    or (KOK.parent / "Switch Yönetim Paneli" / "switch_api.py"))

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
TARAMA_WORKER = int(os.environ.get("TARAMA_WORKER", 12))

# ──────────────────────────────────────────────────────────── doğrulama ────
BEKLENEN_TZ = os.environ.get("EXPECTED_TIMEZONE", "CST-3:00:00")
BEKLENEN_MASKE = os.environ.get("EXPECTED_SUBNET_MASK", "255.255.0.0")

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
