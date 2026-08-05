#!/usr/bin/env python3
"""Okuma sonucunun durum/renk karşılığı.

Panelin dört rengi burada tanımlanır ve başka hiçbir yerde yeniden
yorumlanmaz:

    yeşil   Cihaza bağlanıldı ve beklenen veri doğrulandı.
    turuncu Cihaz erişilebilir ama kullanıcı adı/parola gerekiyor.
    kırmızı Timeout, bağlantı reddi, ağ hatası ya da doğrulanamayan yanıt.
    gri     Bu cihazda ilgili yöntem uygulanmıyor ya da henüz okunmadı.

"Uygulanmıyor" ile "okunamadı" bilerek ayrı tutulur: ikisini aynı
göstermek, çalışmayan bir cihazı normalmiş gibi ya da normal bir cihazı
arızalıymış gibi gösterir.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .hata import CihazHatasi, KimlikHatasi, UygulanmazHatasi, sinifla

YESIL, TURUNCU, KIRMIZI, GRI = "yesil", "turuncu", "kirmizi", "gri"

DOGRULANDI = "dogrulandi"
KIMLIK_BEKLIYOR = "kimlik_bekliyor"
DOGRULANAMADI = "dogrulanamadi"
OKUNMADI = "okunmadi"
UYGULANMIYOR = "uygulanmiyor"


@dataclass
class Sonuc:
    """Tek bir cihazın tek bir okumasının sonucu.

    `nesil` aynı cihaz için gelen eski cevabın yenisini ezmesini engeller:
    tarama sürerken kullanıcı şifre girip cihazı yeşile çevirdiğinde,
    daha önce yola çıkmış tarama cevabı geri döndüğünde onu turuncuya
    çevirmemeli. Karşılaştırma zaman değil sayaç üzerinden yapılır —
    saat geri alınabilir, sayaç alınamaz.
    """

    durum: str = GRI
    dogrulama: str = OKUNMADI
    aciklama: str = ""
    alanlar: dict = field(default_factory=dict)
    yontem: str = ""
    zaman: float = 0.0
    nesil: int = 0

    def dto(self) -> dict:
        return {
            "durum": self.durum,
            "dogrulama": self.dogrulama,
            "aciklama": self.aciklama,
            "alanlar": self.alanlar,
            "yontem": self.yontem,
            "okumaZamani": self.zaman or None,
            "nesil": self.nesil,
        }


def basarili(alanlar: dict, yontem: str, aciklama: str = "") -> Sonuc:
    return Sonuc(durum=YESIL, dogrulama=DOGRULANDI,
                 aciklama=aciklama or "Veri okundu ve doğrulandı",
                 alanlar=alanlar or {}, yontem=yontem, zaman=time.time())


def uygulanmaz(yontem: str, aciklama: str) -> Sonuc:
    return Sonuc(durum=GRI, dogrulama=UYGULANMIYOR, aciklama=aciklama,
                 yontem=yontem, zaman=time.time())


def okunmadi(yontem: str, aciklama: str = "Henüz okunmadı") -> Sonuc:
    return Sonuc(durum=GRI, dogrulama=OKUNMADI, aciklama=aciklama,
                 yontem=yontem)


def hatadan(exc: BaseException, yontem: str) -> Sonuc:
    """İstisnayı renkli sonuca çevirir."""
    h: CihazHatasi = sinifla(exc)
    if isinstance(h, UygulanmazHatasi):
        return uygulanmaz(yontem, str(h) or h.baslik)
    dogrulama = (KIMLIK_BEKLIYOR if isinstance(h, KimlikHatasi)
                 else DOGRULANAMADI)
    return Sonuc(durum=h.durum, dogrulama=dogrulama,
                 aciklama=str(h) or h.baslik, yontem=yontem,
                 zaman=time.time())


def kimlik_bekliyor(sonuc: Sonuc) -> bool:
    return sonuc.dogrulama == KIMLIK_BEKLIYOR


def sayilar(sonuclar) -> dict:
    """Bir tarama görüntüsündeki renk dağılımı."""
    say = {YESIL: 0, TURUNCU: 0, KIRMIZI: 0, GRI: 0}
    for s in sonuclar:
        say[s.durum] = say.get(s.durum, 0) + 1
    return {
        "basarili": say[YESIL],
        "erisimBekleyen": say[TURUNCU],
        "hatali": say[KIRMIZI],
        "okunmayan": say[GRI],
    }


def uptime_metni(saniye) -> str:
    """Saniyeyi SS:DD:ss biçimine çevirir; geçersizse boş."""
    try:
        u = int(float(saniye))
    except (TypeError, ValueError):
        return ""
    if u < 0:
        return ""
    return f"{u // 3600:02d}:{(u % 3600) // 60:02d}:{u % 60:02d}"
