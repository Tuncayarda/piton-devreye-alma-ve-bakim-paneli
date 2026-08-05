#!/usr/bin/env python3
"""DeviceMap.json — topoloji envanteri.

Panelin cihaz listesi TEK kaynaktan gelir: bu dosya. İstemcinin gönderdiği
IP ya da cihaz türü hiçbir zaman bağlantı hedefi olarak kullanılmaz;
istemci yalnızca bir cihaz kimliği (id) gönderir, hedef burada bulunur.

DeviceMap içinde Username/Password alanları da bulunuyor. Bunlar projenin
tanım verisi; panel bunları kimlik olarak KULLANMAZ ve API cevaplarına
KOYMAZ. Kimlik yalnızca kullanıcıdan alınır ve yalnızca bellekte durur
(bkz. core/kimlik.py) — aksi halde "parola dosyada tutulmaz" kuralı
kâğıt üzerinde kalırdı.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import ayar
from .kategori import kategori_of, yontem_of

# DeviceMap'te bulunan ama dışarı asla verilmeyecek alanlar
GIZLI_ALANLAR = {"password", "pbxpassword", "username"}


def coz(sablon: str, set_no) -> str:
    """IP şablonundaki tek başına duran 'n' yerine set numarasını koyar.

    10.n.1.24, set 3 -> 10.3.1.24
    """
    return re.sub(r"(?<![0-9a-zA-Z])n(?![0-9a-zA-Z])", str(set_no),
                  sablon or "")


def sablonla(ip: str, set_no) -> str:
    """Çözülmüş IP'yi şablon biçimine geri döndürür (10.3.1.24 -> 10.n.1.24)."""
    parca = str(ip or "").split(".")
    if len(parca) == 4 and parca[1] == str(set_no):
        parca[1] = "n"
        return ".".join(parca)
    return ip


@dataclass
class Cihaz:
    """Tek bir cihazın değişmeyen künyesi (canlı durum burada tutulmaz).

    `id` DeviceMap içindeki konumdan üretilir ve set numarasından
    bağımsızdır. Aynı adlı iki cihaz farklı id alır; eşleştirme her yerde
    id + ip + type + subtype dörtlüsüyle yapılır.
    """

    id: str
    ad: str
    ip_sablonu: str
    ip: str
    type: str
    subtype: str | None
    switch: str            # bağlı olduğu switch'in adı
    switch_id: str
    port: str | None
    aktif: bool
    kategori: str
    yontem: str
    pbx_extension: str | None = None
    ekstra: dict = field(default_factory=dict)

    @property
    def anahtar(self) -> tuple:
        """Eşleştirme anahtarı — ad değil, dörtlü."""
        return (self.id, self.ip, self.type, self.subtype or "")

    def dto(self) -> dict:
        """Arayüze giden güvenli gösterim. Parola/kullanıcı adı içermez."""
        return {
            "id": self.id,
            "ad": self.ad,
            "ip": self.ip,
            "ipSablonu": self.ip_sablonu,
            "type": self.type,
            "subtype": self.subtype or "",
            "tipEtiket": f"{self.type} / {self.subtype}" if self.subtype else self.type,
            "switch": self.switch,
            "switchId": self.switch_id,
            "port": self.port or "",
            "portEtiket": (f"{self.switch} · Yönetim" if self.type == "Switch"
                           else f"{self.switch} · p{self.port}"),
            "kategori": self.kategori,
            "yontem": self.yontem,
            "pbxExtension": self.pbx_extension or "",
            "aktif": self.aktif,
        }


class Envanter:
    """Bir tren seti için çözülmüş cihaz listesi."""

    def __init__(self, set_no: int, cihazlar: list[Cihaz], proje: str,
                 kaynak: Path):
        self.set_no = set_no
        self.cihazlar = cihazlar
        self.proje = proje
        self.kaynak = kaynak
        self._id_ile = {c.id: c for c in cihazlar}

    def bul(self, cihaz_id: str) -> Cihaz | None:
        """id ile cihaz bulur. İstemciden gelen tek güvenilir alan budur."""
        return self._id_ile.get(str(cihaz_id))

    def tip_ile(self, tip: str, alt: str | None = None) -> list[Cihaz]:
        return [c for c in self.cihazlar
                if c.type == tip and (alt is None or (c.subtype or "") == alt)]

    def switchler(self) -> list[Cihaz]:
        return [c for c in self.cihazlar if c.type == "Switch"]

    def piscu_ip(self) -> str | None:
        p = self.tip_ile("PISCU")
        return p[0].ip if p else None

    def dto(self) -> list[dict]:
        return [c.dto() for c in self.cihazlar]


# ───────────────────────────────────────────────────────── yükleme ────────
_ONBELLEK: dict[tuple, Envanter] = {}
_ONBELLEK_KILIT = threading.Lock()


def _temiz(kayit: dict) -> dict:
    """DeviceMap kaydından kimlik alanlarını ayıklar."""
    return {k: v for k, v in kayit.items()
            if k.lower() not in GIZLI_ALANLAR and k not in ("Devices", "Status")}


def _ham_oku(yol: Path) -> dict:
    if not yol.exists():
        raise FileNotFoundError(f"DeviceMap bulunamadı: {yol}")
    return json.loads(yol.read_text(encoding="utf-8"))


def yukle(set_no: int, yol: Path | None = None,
          onbellek: bool = True) -> Envanter:
    """Verilen tren seti için envanteri kurar.

    Dosya değişirse önbellek kendiliğinden tazelenir (mtime anahtara dahil).
    """
    yol = Path(yol or ayar.DEVICE_MAP)
    imza = (str(yol), int(set_no), yol.stat().st_mtime_ns if yol.exists() else 0)
    if onbellek:
        with _ONBELLEK_KILIT:
            hazir = _ONBELLEK.get(imza)
            if hazir:
                return hazir

    ham = _ham_oku(yol)
    cihazlar: list[Cihaz] = []
    for si, sw in enumerate(ham.get("Switches") or [], start=1):
        sw_id = f"sw{si}"
        sw_ad = sw.get("Name") or f"Switch {si}"
        sw_sablon = sw.get("IP", "")
        cihazlar.append(Cihaz(
            id=sw_id, ad=sw_ad, ip_sablonu=sw_sablon,
            ip=coz(sw_sablon, set_no), type="Switch", subtype=None,
            switch=sw_ad, switch_id=sw_id, port=None,
            aktif=bool(sw.get("IsActive", True)),
            kategori=kategori_of("Switch"), yontem=yontem_of("Switch", None),
            ekstra=_temiz(sw),
        ))
        for di, dv in enumerate(sw.get("Devices") or [], start=1):
            tip = dv.get("Type", "")
            alt = dv.get("SubType") or None
            sablon = dv.get("IP", "")
            cihazlar.append(Cihaz(
                id=f"{sw_id}.d{di}", ad=dv.get("Name", ""),
                ip_sablonu=sablon, ip=coz(sablon, set_no),
                type=tip, subtype=alt, switch=sw_ad, switch_id=sw_id,
                port=str(dv.get("Port")) if dv.get("Port") is not None else None,
                aktif=bool(dv.get("IsActive", True)),
                kategori=kategori_of(tip), yontem=yontem_of(tip, alt),
                pbx_extension=dv.get("PBXExtension") or None,
                ekstra=_temiz(dv),
            ))

    env = Envanter(int(set_no), cihazlar,
                   proje=yol.stem.replace("DeviceMap", "").strip("_- ") or "YATAKLI",
                   kaynak=yol)
    if onbellek:
        with _ONBELLEK_KILIT:
            _ONBELLEK[imza] = env
    return env


def gecerli_set(deger, varsayilan: int = 1) -> int:
    """İstemciden gelen set numarasını doğrular.

    Şablondaki n doğrudan IP'nin ikinci oktetine giriyor; doğrulanmadan
    kabul edilirse istemci istediği ağa bağlantı kurdurabilirdi.
    """
    try:
        n = int(deger)
    except (TypeError, ValueError):
        return varsayilan
    if not (ayar.SET_MIN <= n <= ayar.SET_MAX):
        return varsayilan
    return n


def onbellegi_bosalt() -> None:
    with _ONBELLEK_KILIT:
        _ONBELLEK.clear()
