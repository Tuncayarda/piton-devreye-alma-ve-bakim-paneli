#!/usr/bin/env python3
"""Cihaz hatalarının sınıflandırılması.

Panelin renk mantığı doğrudan bu sınıflara dayanır. "Ulaşılamadı" ile
"kullanıcı adı/parola gerekiyor" ile "cihaz beklenmeyen bir şey döndürdü"
birbirinden ayrılmazsa kullanıcı ne yapacağını bilemez: biri kabloyu,
biri şifreyi, biri de yanlış cihaz/uç anlamına gelir.

Kullanıcıya gösterilen metinlerde parola ASLA bulunmaz; ham yığın izi de
bulunmaz (o yalnız hata ayıklama loguna gider).
"""
from __future__ import annotations


class CihazHatasi(Exception):
    """Tek bir cihazın okunamamasının ortak atası."""

    durum = "kirmizi"
    baslik = "Cihaz okunamadı"


class UlasilamadiHatasi(CihazHatasi):
    """Timeout, bağlantı reddi, DNS/ağ hatası, kopan bağlantı."""

    durum = "kirmizi"
    baslik = "Cihaza ulaşılamadı"


class KimlikHatasi(CihazHatasi):
    """401/403, WWW-Authenticate, oturum açma sayfası dönmesi.

    Cihaz ayakta ve konuşuyor; yalnızca kimlik istiyor. Bu yüzden kırmızı
    değil turuncu: kullanıcının yapması gereken şey kablo değil şifre.
    """

    durum = "turuncu"
    baslik = "Kullanıcı adı / parola gerekiyor"


class DogrulamaHatasi(CihazHatasi):
    """Cihaz cevap verdi ama beklenen veri değil.

    HTTP 200 tek başına başarı sayılmaz: login HTML'i, boş sayfa ya da
    beklenmeyen bir JSON gövdesi de 200 ile gelir.
    """

    durum = "kirmizi"
    baslik = "Cihaz yanıtı doğrulanamadı"


class UygulanmazHatasi(CihazHatasi):
    """Bu cihaz türünde ilgili okuma yöntemi tanımlı değil (N/A)."""

    durum = "gri"
    baslik = "Bu cihazda uygulanmıyor"


def kullanici_mesaji(exc: BaseException) -> str:
    """Teknik hatayı kullanıcının okuyabileceği tek cümleye indirger."""
    if isinstance(exc, CihazHatasi):
        metin = str(exc).strip()
        return metin or exc.baslik

    ad = type(exc).__name__
    if ad in ZAMAN_ASIMI:
        return "Cihaz zaman aşımına uğradı"
    if ad in ULASILAMADI:
        return "Cihaza ulaşılamadı (bağlantı kurulamadı)"
    if ad == "SSLError":
        return "Güvenli bağlantı kurulamadı"
    return "Cihazla iletişimde beklenmeyen bir sorun oluştu"


# Ağ katmanından gelen istisna adları. Liste eksik kalırsa gerçek bir
# timeout "beklenmeyen sorun" diye görünüyor ve kullanıcı kabloya mı
# şifreye mi bakacağını bilemiyor — o yüzden hem requests hem stdlib
# hem subprocess adları burada.
ZAMAN_ASIMI = {
    "ConnectTimeout", "ReadTimeout", "Timeout", "TimeoutError",
    "socket.timeout", "TimeoutExpired", "ConnectTimeoutError",
    "ReadTimeoutError", "MaxRetryError",
}
ULASILAMADI = {
    "ConnectionError", "NewConnectionError", "OSError", "IOError",
    "ConnectionRefusedError", "ConnectionResetError", "ConnectionAbortedError",
    "BrokenPipeError", "gaierror", "herror", "URLError", "ProtocolError",
    "ChunkedEncodingError", "NameResolutionError",
}


def sinifla(exc: BaseException) -> CihazHatasi:
    """Herhangi bir istisnayı panelin bildiği sınıflardan birine çevirir."""
    if isinstance(exc, CihazHatasi):
        return exc
    ad = type(exc).__name__
    if ad in ZAMAN_ASIMI or ad in ULASILAMADI or ad == "SSLError":
        return UlasilamadiHatasi(kullanici_mesaji(exc))
    return DogrulamaHatasi(kullanici_mesaji(exc))
