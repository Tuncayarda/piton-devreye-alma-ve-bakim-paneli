#!/usr/bin/env python3
"""Cihaz kategorileri, işlem grupları ve okuma yöntemi eşlemesi.

Tasarımdaki sol menü ve "hedef grup" şeritleri buradan beslenir. Tek
kaynak burasıdır; arayüz kendi listesini tutmaz, API'den alır.
"""
from __future__ import annotations

# ── sol menüdeki kategoriler ────────────────────────────────────────────
KATEGORILER = [
    {"id": "tum", "ad": "Tüm Cihazlar", "kod": "TUM",
     "tipler": "Switch dahil hepsi", "eslesen": None},
    {"id": "anons", "ad": "Anons Ekipmanları", "kod": "ANONS",
     "tipler": "Announcement", "eslesen": ["Announcement"]},
    {"id": "video", "ad": "Video Sistemi", "kod": "VIDEO",
     "tipler": "Camera · NVR", "eslesen": ["Camera", "NVR"]},
    {"id": "ekran", "ad": "Ekranlar & LED", "kod": "EKRAN",
     "tipler": "LCD · LED", "eslesen": ["LCD", "LED"]},
    {"id": "ag", "ad": "Ağ Altyapısı", "kod": "AG",
     "tipler": "Switch · AP", "eslesen": ["Switch", "AP"]},
    {"id": "kontrol", "ad": "Kontrol Birimleri", "kod": "KONTROL",
     "tipler": "PISCU · HMI · ICU", "eslesen": ["PISCU", "HMI", "ICU"]},
]


def kategori_of(tip: str) -> str:
    for k in KATEGORILER:
        if k["eslesen"] and tip in k["eslesen"]:
            return k["id"]
    return "kontrol"


# ── okuma yöntemleri ────────────────────────────────────────────────────
# `grup`: kimlik bilgisi paylaşılabilecek küme. Kullanıcı "aynı hesabı
# gruba uygula" derse kimlik bu ad altında saklanır (bkz. core/kimlik.py).
YONTEMLER = {
    "kyland": {"kod": "KYLAND", "yol": "/stat/basicInfo", "grup": "switch",
               "kimlik_ister": True, "periyot": 10},
    "isapi": {"kod": "ISAPI", "yol": "/ISAPI/System/deviceInfo", "grup": "video",
              "kimlik_ister": True, "periyot": 10},
    "http": {"kod": "HTTP", "yol": "/api/v1/system/settings", "grup": "anons",
             "kimlik_ister": False, "periyot": 3},
    "app": {"kod": "MQTT", "yol": "ALFA/AppStatus/#", "grup": None,
            "kimlik_ister": False, "periyot": 1},
    "mqtt": {"kod": "MQTT", "yol": "ALFA/DeviceMap (retained)", "grup": None,
             "kimlik_ister": False, "periyot": 1},
    "adb": {"kod": "ADB", "yol": "adb getprop · dumpsys · logcat (5555)",
            "grup": None, "kimlik_ister": False, "periyot": 0},
}


def yontem_of(tip: str, alt: str | None) -> str:
    """Cihaz tipine göre hangi okuyucunun kullanılacağı.

    Bu eşleme YATAKLI_DevreyeAlma/device_verify.py içindeki COLLECTORS
    tablosuyla aynıdır; iki yerde farklı davranmasın diye tek satırlık
    tahminler yerine oradaki çalışan ayrım korunmuştur.
    """
    if tip == "Switch":
        return "kyland"
    if tip in ("Camera", "NVR"):
        return "isapi"
    if tip == "Announcement" and (alt or "") in ("Amplifier", "Handset",
                                                 "Intercom", "UIC"):
        return "http"
    if tip in ("PISCU", "HMI"):
        return "app"
    if tip == "LCD" and (alt or "") == "Compartment":
        return "adb"
    return "mqtt"


# ── işlem yapılabilen cihaz grupları ────────────────────────────────────
# ops: ip = IP atama, cfg = konfigürasyon, fw = firmware, dog = doğrulama
GRUPLAR = [
    {"ad": "Intercom", "tip": "Announcement", "alt": "Intercom", "ops": "ip cfg fw dog"},
    {"ad": "Handset", "tip": "Announcement", "alt": "Handset", "ops": "ip cfg fw dog"},
    {"ad": "Amplifier", "tip": "Announcement", "alt": "Amplifier", "ops": "ip cfg fw dog"},
    {"ad": "UIC", "tip": "Announcement", "alt": "UIC", "ops": "ip cfg fw dog"},
    {"ad": "Compartment LCD", "tip": "LCD", "alt": "Compartment", "ops": "ip dog"},
    {"ad": "Landing LCD", "tip": "LCD", "alt": "Landing", "ops": "ip dog"},
    {"ad": "LED", "tip": "LED", "alt": "Front", "ops": "ip dog"},
    {"ad": "ICU", "tip": "ICU", "alt": "", "ops": "ip dog"},
    {"ad": "Kamera", "tip": "Camera", "alt": "", "ops": "ip dog"},
    {"ad": "NVR", "tip": "NVR", "alt": "", "ops": "ip dog"},
    {"ad": "AP", "tip": "AP", "alt": "", "ops": "ip dog"},
    {"ad": "PISCU", "tip": "PISCU", "alt": "", "ops": "dog"},
    {"ad": "HMI", "tip": "HMI", "alt": "", "ops": "dog"},
    {"ad": "Tümü", "tip": "*", "alt": "", "ops": "dog"},
]


def grup_bul(ad: str) -> dict | None:
    return next((g for g in GRUPLAR if g["ad"] == ad), None)


def grup_eslesir(g: dict, cihaz) -> bool:
    if g["tip"] == "*":
        return cihaz.type != "Switch"
    if cihaz.type != g["tip"]:
        return False
    return (not g["alt"]) or (cihaz.subtype or "") == g["alt"]
