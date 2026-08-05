#!/usr/bin/env python3
"""Yazılım (firmware) yükleme.

Cihazın kendi web arayüzüyle aynı biçim kullanılır: multipart/form-data,
alan adı "firmware", uç /api/v1/system/update. Yükleme sonrası cihaz
yeniden başlar; sürümün gerçekten değiştiği yeniden okunarak doğrulanır.
Yalnızca HTTP 200 gelmesi "yüklendi" sayılmaz.

Dosya kullanıcıdan alınır ve sunucuda yalnızca yolu tutulur — panel
firmware dosyasını kendi dizinine kopyalamaz, saklamaz.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import requests

from . import ayar, okuma
from .device_map import Cihaz
from .hata import DogrulamaHatasi, KimlikHatasi, UygulanmazHatasi, sinifla

YUKLEME_UCU = "api/v1/system/update"
ALAN_ADI = "firmware"
EN_BUYUK = 32 * 1024 * 1024          # 32 MB — bu cihazların imajları çok küçük

_SECILI: dict[str, object] = {"yol": None, "boyut": 0, "surum": ""}
_KILIT = threading.Lock()


def dosya_sec(yol: str, surum: str = "") -> dict:
    """Yüklenecek imajı seçer (yalnızca bellekte tutulur)."""
    p = Path(yol).expanduser()
    if not p.is_file():
        raise ValueError(f"Dosya bulunamadı: {p.name}")
    boyut = p.stat().st_size
    if boyut == 0:
        raise ValueError("Dosya boş")
    if boyut > EN_BUYUK:
        raise ValueError(f"Dosya çok büyük ({boyut // 1024 // 1024} MB)")
    with _KILIT:
        _SECILI.update({"yol": p, "boyut": boyut, "surum": str(surum)[:32]})
    return secili()


def secili() -> dict:
    with _KILIT:
        p = _SECILI["yol"]
        return {
            "ad": p.name if p else "",
            "boyut": _SECILI["boyut"],
            "surum": _SECILI["surum"],
            "secili": p is not None,
        }


def temizle() -> None:
    with _KILIT:
        _SECILI.update({"yol": None, "boyut": 0, "surum": ""})


def yukle(cihaz: Cihaz, kimlik=None, dogrula_sure: float = 45.0) -> dict:
    """Seçili imajı cihaza yükler ve sürümü doğrular."""
    if cihaz.yontem != "http":
        raise UygulanmazHatasi(
            "Bu cihaz türünde yazılım yükleme tanımlı değil")
    with _KILIT:
        yol = _SECILI["yol"]
        beklenen = _SECILI["surum"]
    if yol is None:
        raise ValueError("Önce yüklenecek dosya seçilmeli")

    onceki = ""
    try:
        onceki = okuma.anons_oku(cihaz.ip, kimlik).get("surum", "")
    except KimlikHatasi:
        raise
    except Exception:
        pass

    auth = tuple(kimlik) if kimlik else None
    try:
        with open(yol, "rb") as f:
            r = requests.post(
                f"http://{cihaz.ip}:{ayar.ANONS_PORT}/{YUKLEME_UCU}",
                files={ALAN_ADI: (Path(yol).name, f,
                                  "application/octet-stream")},
                timeout=120, auth=auth)
    except Exception as exc:
        raise sinifla(exc)
    if r.status_code in (401, 403):
        raise KimlikHatasi("Cihaz kullanıcı adı/parola istiyor")
    if r.status_code >= 400:
        raise DogrulamaHatasi(f"Cihaz yüklemeyi reddetti (HTTP {r.status_code})")

    # Cihaz yeniden başlıyor: sürümü ancak geri geldiğinde okuyabiliriz.
    bitis = time.time() + dogrula_sure
    yeni = ""
    while time.time() < bitis:
        time.sleep(2.0)
        try:
            yeni = okuma.anons_oku(cihaz.ip, kimlik,
                                   timeout=2.5).get("surum", "")
            if yeni:
                break
        except Exception:
            continue

    if not yeni:
        raise DogrulamaHatasi(
            "Yükleme gönderildi ama cihaz doğrulama süresi içinde geri "
            "dönmedi — sürüm okunamadı")
    if beklenen and str(yeni).strip() != str(beklenen).strip():
        raise DogrulamaHatasi(
            f"Cihaz {yeni} sürümünü bildiriyor, beklenen {beklenen}")
    return {"onceki": onceki, "yeni": yeni,
            "degisti": bool(onceki) and str(onceki) != str(yeni)}
