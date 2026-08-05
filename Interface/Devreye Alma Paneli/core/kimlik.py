#!/usr/bin/env python3
"""Cihaz kimlik bilgilerinin bellekte tutulması.

Kural tek cümlede: kullanıcı adı ve parola YALNIZCA çalışan Python
sürecinin belleğinde durur.

Bu dosyada bilerek bulunmayan şeyler:
  · dosyaya yazma (json / .env / sqlite / keychain / plist)
  · ortam değişkenine yazma
  · disk önbelleği, geçici dosya, log satırı

Uygulama kapandığında `hepsini_unut()` çağrılır; süreç ölünce zaten hiçbir
iz kalmaz. Yeni açılışta şifre isteyen her cihaz için kullanıcıdan bilgi
yeniden istenir.

Kimlik "grup" kavramı: aynı hesabın bütün switch'lerde ya da bütün
kameralarda geçerli olması yaygın. Ama varsayılan davranış tek cihazdır;
gruba yayma yalnızca kullanıcı açıkça isterse yapılır (bkz. `ver`).
"""
from __future__ import annotations

import threading

# cihaz anahtarı -> (kullanıcı, parola)
_CIHAZ: dict[str, tuple[str, str]] = {}
# grup adı -> (kullanıcı, parola)   (kullanıcı açıkça "gruba uygula" derse)
_GRUP: dict[str, tuple[str, str]] = {}
_KILIT = threading.RLock()


def anahtar(cihaz_id: str, ip: str) -> str:
    """Kimlik anahtarı.

    Yalnız ad ya da yalnız IP yetmez: aynı adlı iki switch farklı IP'de
    olabiliyor, aynı IP de set değişince başka bir cihaza gidebiliyor.
    """
    return f"{cihaz_id}@{ip}"


def ver(cihaz_id: str, ip: str, kullanici: str, parola: str,
        grup: str | None = None, gruba_uygula: bool = False) -> None:
    """Doğrulanmış kimliği belleğe alır.

    Yalnızca cihazdan gerçekten veri alındıktan sonra çağrılmalıdır —
    formun doldurulmuş olması doğruluk anlamına gelmez.
    """
    with _KILIT:
        _CIHAZ[anahtar(cihaz_id, ip)] = (kullanici, parola)
        if gruba_uygula and grup:
            _GRUP[grup] = (kullanici, parola)


def al(cihaz_id: str, ip: str, grup: str | None = None):
    """Önce cihazın kendi kimliği, yoksa kullanıcının gruba yaydığı çift."""
    with _KILIT:
        k = _CIHAZ.get(anahtar(cihaz_id, ip))
        if k:
            return k
        return _GRUP.get(grup) if grup else None


def var_mi(cihaz_id: str, ip: str, grup: str | None = None) -> bool:
    return al(cihaz_id, ip, grup) is not None


def unut(cihaz_id: str, ip: str) -> None:
    with _KILIT:
        _CIHAZ.pop(anahtar(cihaz_id, ip), None)


def grup_unut(grup: str) -> None:
    with _KILIT:
        _GRUP.pop(grup, None)


def hepsini_unut() -> None:
    """Uygulama kapanırken çağrılır."""
    with _KILIT:
        _CIHAZ.clear()
        _GRUP.clear()


def ozet() -> dict:
    """Arayüze gösterilebilir özet — parola İÇERMEZ.

    Yalnızca "bu cihaz için bellekte bir kimlik var mı" bilgisini ve
    maskelenmiş kullanıcı adını döndürür.
    """
    with _KILIT:
        return {
            "cihaz": {k: maskele(v[0]) for k, v in _CIHAZ.items()},
            "grup": {g: maskele(v[0]) for g, v in _GRUP.items()},
        }


def sayi() -> int:
    with _KILIT:
        return len(_CIHAZ)


def maskele(kullanici: str) -> str:
    """Loglarda ve özetlerde kullanıcı adını kısaltır: admin -> a***n."""
    k = str(kullanici or "")
    if len(k) <= 2:
        return "*" * len(k)
    return f"{k[0]}{'*' * (len(k) - 2)}{k[-1]}"
