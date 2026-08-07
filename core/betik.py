#!/usr/bin/env python3
"""betikler/ altındaki çalışan motorları içe aktarma.

Bu panel, sahada denenmiş üç betiğin iş mantığını yeniden yazmaz; çalışma
anında dosya yolundan içe aktarıp kullanır:

    betikler/switch_api.py           switch erişimi
    betikler/device_verify.py        alan ayıklama + Excel
    betikler/intercom_ip_assign.py   IP atama akışı

Neden import: aynı işi ikinci kez yazmak, iki uygulamanın zamanla
ayrışması demek. Switch'te çalışan bir hesabın burada "doğrulanamadı"
demesi tam olarak böyle oluyor.

switch_api.py aslen Switch Yönetim Paneli'nin dosyasıdır; o uygulama
`syp` branch'inin kökünde yaşar, buradaki kopya onunla elle eşitlenir.

Betikler paket ağacının dışında olduğu için normal `import` yetmez; her
biri tek seferlik yüklenip önbelleğe alınır. Bulunamayan betik sessizce
atlanmaz — çağıran taraf anlaşılır bir hata alır.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

from . import ayar

_KILIT = threading.Lock()
_YUKLU: dict[str, object] = {}


def yukle(ad: str, yol: Path, aciklama: str):
    """Dosya yolundaki modülü bir kez yükler ve döndürür."""
    with _KILIT:
        hazir = _YUKLU.get(ad)
        if hazir is not None:
            return hazir
        if not Path(yol).exists():
            raise RuntimeError(f"{aciklama} bulunamadı: {yol}")
        spec = importlib.util.spec_from_file_location(ad, str(yol))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"{aciklama} içe aktarılamadı: {yol}")
        modul = importlib.util.module_from_spec(spec)
        sys.modules[ad] = modul
        spec.loader.exec_module(modul)
        _YUKLU[ad] = modul
        return modul


def switch_api():
    """Switch Yönetim Paneli backend'i — switch erişiminin tek kaynağı."""
    modul = yukle("syp_switch_api", ayar.SWITCH_PANELI,
                  "Switch Yönetim Paneli backend'i (switch_api.py)")
    modul.SWITCH_PORT = ayar.KYLAND_PORT
    return modul


def device_verify():
    """Saha doğrulama betiği — alan ayıklama yardımcıları ve Excel şeması.

    openpyxl gerektirir; bu yüzden yalnızca gerçekten kullanılacağı anda
    çağrılır (tarama sırasında değil, alan ayıklarken ve Excel üretirken).
    """
    return yukle("yatakli_device_verify", ayar.DEVICE_VERIFY,
                 "Saha doğrulama betiği (device_verify.py)")


def intercom_ip_assign():
    """IP atama betiği — PoE ile port açma/kapama ve cihaza IP yazma."""
    return yukle("yatakli_ip_assign", ayar.INTERCOM_IP_ASSIGN,
                 "IP atama betiği (intercom_ip_assign.py)")


def var_mi(hangi: str) -> bool:
    """Betik yüklenebiliyor mu — arayüzde özelliği gri göstermek için."""
    try:
        {"switch": switch_api, "verify": device_verify,
         "ip": intercom_ip_assign}[hangi]()
        return True
    except Exception:
        return False
