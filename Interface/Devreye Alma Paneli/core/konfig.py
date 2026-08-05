#!/usr/bin/env python3
"""Konfigürasyon — cihazdaki değerleri okuma ve hedef değerleri yazma.

Ekran iki sütunu yan yana gösterir: cihazdan gerçekten okunan değer ve
yazılacak hedef değer. Okunamayan alan boş (—) kalır; "henüz okunmadı"
yerine varsayılan bir değer gösterilmez — bir alanın cihazda ne olduğunu
bilmeden "uyuşuyor" demek doğrulamayı anlamsızlaştırır.

Hedef değerlerin kaynağı iki türlü olabilir:
  · DeviceMap  — SIP dahili numarası gibi projede tanımlı alanlar
  · elle       — kullanıcının ekranda girdiği değer (bellekte, oturumluk)

Kimlik bilgisi hedef değer olarak KABUL EDİLMEZ: bu ekrandan parola
yazılamaz, kaydedilemez.
"""
from __future__ import annotations

import threading

import requests

from . import ayar, okuma
from .device_map import Cihaz, Envanter
from .hata import DogrulamaHatasi, KimlikHatasi, UygulanmazHatasi, sinifla

# Ekranda gösterilen alanlar: (anahtar, etiket, cihazdaki alan adayları,
# düzenlenebilir mi)
ALANLAR = [
    ("sipPbx", "SIP PBX IP", okuma.K_PBX, True),
    ("sipDahili", "SIP Dahili No", okuma.K_EXT, True),
    ("hoparlor", "Hoparlör Ses Seviyesi", okuma.K_SPK, True),
    ("mikrofon", "Mikrofon Ses Seviyesi", okuma.K_MIC, True),
    ("surum", "Yazılım Sürümü", okuma.K_SURUM, False),
    ("seri", "Cihaz Numarası", okuma.K_SERI, False),
]

# Cihaza yazarken kullanılacak uçlar. Yalnız doğrulanmış uçlar; tahmini
# uç denenmez.
YAZMA_UCU = "api/v1/system/settings"

# Kullanıcının elle girdiği hedef değerler — yalnızca bellekte.
_HEDEF: dict[str, dict] = {}
_KILIT = threading.Lock()


def hedef_yaz(cihaz_id: str, alan: str, deger: str) -> None:
    if alan not in {a[0] for a in ALANLAR}:
        raise ValueError(f"Bilinmeyen alan: {alan}")
    with _KILIT:
        _HEDEF.setdefault(cihaz_id, {})[alan] = str(deger)[:128]


def hedef_al(cihaz_id: str) -> dict:
    with _KILIT:
        return dict(_HEDEF.get(cihaz_id, {}))


def hedefleri_unut() -> None:
    with _KILIT:
        _HEDEF.clear()


def _proje_hedefi(cihaz: Cihaz, env: Envanter, alan: str) -> str:
    """DeviceMap'ten gelen tanım değeri (cihazdan okunan değil)."""
    if alan == "sipDahili":
        return cihaz.pbx_extension or ""
    if alan == "sipPbx":
        return env.piscu_ip() or ""
    return ""


def cek(cihaz: Cihaz, env: Envanter, kimlik=None) -> dict:
    """Cihazdaki mevcut değerleri okur ve hedeflerle karşılaştırır."""
    if cihaz.yontem != "http":
        raise UygulanmazHatasi(
            "Bu cihaz türünde konfigürasyon okuma/yazma tanımlı değil")

    veri = okuma.anons_oku(cihaz.ip, kimlik)
    duz = okuma.duzle(veri.get("ayarlar") or {})
    elle = hedef_al(cihaz.id)

    satir = []
    for anahtar, etiket, adaylar, duzenlenebilir in ALANLAR:
        mevcut = veri.get(anahtar)
        if mevcut in (None, ""):
            mevcut = okuma.sec(duz, *adaylar)
        hedef = elle.get(anahtar) or _proje_hedefi(cihaz, env, anahtar)
        satir.append({
            "alan": anahtar, "etiket": etiket,
            "mevcut": "" if mevcut in (None, "") else str(mevcut),
            "hedef": str(hedef or ""),
            "duzenlenebilir": duzenlenebilir,
            "sonuc": _sonuc(mevcut, hedef),
        })
    return {"cihazId": cihaz.id, "satirlar": satir}


def _sonuc(mevcut, hedef) -> str:
    if hedef in (None, ""):
        return "hedef_yok"
    if mevcut in (None, ""):
        return "okunamadi"
    return "uyuyor" if str(mevcut).strip() == str(hedef).strip() else "farkli"


def uygula(cihaz: Cihaz, env: Envanter, kimlik=None) -> dict:
    """Hedef değerleri cihaza yazar ve yazımı okuyarak doğrular.

    HTTP 200 tek başına başarı sayılmaz: yazımdan sonra ayarlar tekrar
    okunur ve değerin gerçekten değiştiği görülür.
    """
    if cihaz.yontem != "http":
        raise UygulanmazHatasi(
            "Bu cihaz türünde konfigürasyon yazma tanımlı değil")

    elle = hedef_al(cihaz.id)
    gonderilecek = {}
    for anahtar, _etiket, _adaylar, duzenlenebilir in ALANLAR:
        if not duzenlenebilir:
            continue
        deger = elle.get(anahtar) or _proje_hedefi(cihaz, env, anahtar)
        if deger:
            gonderilecek[anahtar] = deger
    if not gonderilecek:
        raise ValueError("Yazılacak hedef değer yok")

    auth = tuple(kimlik) if kimlik else None
    try:
        r = requests.post(f"http://{cihaz.ip}:{ayar.ANONS_PORT}/{YAZMA_UCU}",
                          json=gonderilecek, timeout=ayar.OKUMA_TIMEOUT,
                          auth=auth,
                          headers={"Content-Type": "application/json"})
    except Exception as exc:
        raise sinifla(exc)
    if r.status_code in (401, 403):
        raise KimlikHatasi("Cihaz kullanıcı adı/parola istiyor")
    if r.status_code >= 400:
        raise DogrulamaHatasi(f"Cihaz yazmayı reddetti (HTTP {r.status_code})")
    try:
        govde = r.json()
    except ValueError:
        govde = {}
    if isinstance(govde, dict):
        metin = str(govde).lower()
        if any(k in metin for k in ("error", "fail", "invalid", "reject")):
            raise DogrulamaHatasi("Cihaz yazmayı reddetti")

    return cek(cihaz, env, kimlik)
