#!/usr/bin/env python3
"""Kamera / NVR okuması — Hikvision ISAPI.

Uçlar ve ayrıştırma YATAKLI_DevreyeAlma/device_verify.py içindeki
`fetch_isapi` ile aynıdır; oradaki çalışan davranış korunmuştur.

Fark: burada kimlik `.env`'den değil kullanıcıdan gelir ve yalnızca
bellekte durur. Kimlik yoksa istek kimliksiz atılır — cihaz 401 döner,
cihaz "erişim bekliyor" (turuncu) olarak kilit menüsüne düşer.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth
import urllib3

from . import ayar
from .hata import DogrulamaHatasi, KimlikHatasi, sinifla

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _etiket(kok, ad):
    for el in kok.iter():
        if el.tag.rsplit("}", 1)[-1] == ad:
            return (el.text or "").strip()
    return None


def _istek(ip: str, yol: str, kimlik, sure: float):
    auth = HTTPDigestAuth(*kimlik) if kimlik else None
    return requests.get(f"http://{ip}:{ayar.VIDEO_PORT}/ISAPI/{yol}",
                        auth=auth, timeout=sure, verify=False)


def _xml(r, ip: str):
    """Yanıtı XML'e çevirir; kimlik sorunlarını KimlikHatasi'na dönüştürür.

    Hikvision cihazları kimliksiz istekte 401 döner. Bazı sürümler ise
    200 ile HTML oturum sayfası döndürüyor — XML ayrıştırılamadığında da
    başarı saymıyoruz.
    """
    if r.status_code in (401, 403) or "WWW-Authenticate" in r.headers:
        raise KimlikHatasi("Cihaz kullanıcı adı/parola istiyor")
    if r.status_code >= 400:
        raise DogrulamaHatasi(f"Cihaz HTTP {r.status_code} döndürdü")
    try:
        return ET.fromstring(r.content)
    except ET.ParseError:
        tur = r.headers.get("Content-Type", "?")
        raise DogrulamaHatasi(
            f"Cihaz XML yerine {tur} döndürdü — beklenen ISAPI yanıtı değil")


def oku(ip: str, kimlik: tuple[str, str] | None = None,
        timeout: float | None = None, beklenen_ntp: str | None = None) -> dict:
    """Cihaz künyesi + ağ/zaman denetimi.

    Künye alınamazsa hata fırlatır. Zaman/maske denetimleri isteğe bağlı
    ektir: alınamazsa cihaz yine de "okundu" sayılır, ilgili alan boş kalır.
    """
    sure = timeout if timeout is not None else ayar.OKUMA_TIMEOUT
    try:
        r = _istek(ip, "System/deviceInfo", kimlik, sure)
    except Exception as exc:
        raise sinifla(exc)

    kok = _xml(r, ip)
    surum = _etiket(kok, "firmwareVersion")
    seri = _etiket(kok, "serialNumber")
    model = _etiket(kok, "model") or _etiket(kok, "deviceType")
    if not (surum or seri or model):
        raise DogrulamaHatasi(
            "Cihaz yanıt verdi ama ISAPI künyesi boş "
            "(firmwareVersion / serialNumber yok)")

    sorun: list[str] = []
    for yol, etiket, beklenen, ad in (
            ("System/time", "timeZone", ayar.BEKLENEN_TZ, "Saat"),
            ("System/time/ntpServers/1", "ipAddress", beklenen_ntp, "NTP")):
        if beklenen is None:
            continue
        try:
            deger = _etiket(_xml(_istek(ip, yol, kimlik, sure), ip), etiket)
            if deger != beklenen:
                sorun.append(ad)
        except KimlikHatasi:
            raise
        except Exception:
            sorun.append(ad)

    maske = _maske(ip, kimlik, sure)
    if maske is not None and maske != ayar.BEKLENEN_MASKE:
        sorun.append("Maske")

    return {
        "surum": surum or "",
        "seri": seri or "",
        "model": model or "",
        "maske": maske or "",
        "agZaman": "Uygun" if not sorun else ", ".join(sorun),
        "ham": {"firmwareVersion": surum, "serialNumber": seri, "model": model},
    }


def _maske(ip: str, kimlik, sure: float) -> str | None:
    """10.x ağındaki arayüzün subnet maskesi; okunamazsa None."""
    try:
        kok = _xml(_istek(ip, "System/Network/interfaces", kimlik, sure), ip)
    except KimlikHatasi:
        raise
    except Exception:
        return None
    for el in kok.iter():
        if el.tag.rsplit("}", 1)[-1] != "IPAddress":
            continue
        adres = alt = None
        for ch in el:
            etiket = ch.tag.rsplit("}", 1)[-1]
            if etiket == "ipAddress":
                adres = (ch.text or "").strip()
            elif etiket == "subnetMask":
                alt = (ch.text or "").strip()
        if adres and adres.startswith("10."):
            return alt
    return None
