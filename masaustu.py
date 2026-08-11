#!/usr/bin/env python3
"""Soketsiz masaüstü arayüzü ve pywebview API köprüsü.

Bu modül HTTP sunucusu açmaz. Arayüz, derleme sırasında tek HTML'e
paketlenmiş ``static/masaustu.html`` dosyasından belleğe okunur; Python ile
JavaScript arasındaki bütün iletişim, ``Window.expose`` ile yalnız ``invoke``
metodunun açıldığı yerel pywebview köprüsü üzerinden geçer.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import panel_api
from core import ayar
from tools.masaustu_paketi import PaketHatasi, html_dogrula


MASAUSTU_HTML = ayar.STATIC_DIR / "masaustu.html"
KOPRU_ISARETI = '<meta name="dap-transport" content="bridge">'
YETENEK_YERI = "__DAP_CAPABILITY__"
YOL_SINIRI = 4096


def html_yukle(yetenek: str | None = None, yol: Path | None = None) -> str:
    """Takip edilen, tamamen gömülü masaüstü HTML'ini okur.

    Çalışma anında paket üretilmez; Deno ve benzeri geliştirme araçları saha
    bilgisayarında bulunmak zorunda değildir. Kaynaklar değiştiğinde artefakt
    ``python3 tools/masaustu_paketi.py`` ile yenilenir.
    """
    hedef = yol or MASAUSTU_HTML
    try:
        metin = hedef.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Masaüstü arayüz paketi bulunamadı. "
            "tools/masaustu_paketi.py ile yeniden üretin."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Masaüstü arayüz paketi okunamadı: {exc}") from exc

    try:
        html_dogrula(metin)
    except PaketHatasi as exc:
        raise RuntimeError(f"Masaüstü arayüz paketi geçersiz: {exc}") from exc

    if yetenek is not None:
        if not isinstance(yetenek, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{43}", yetenek):
            raise RuntimeError("Masaüstü köprü anahtarı geçersiz")
        if metin.count(YETENEK_YERI) != 1:
            raise RuntimeError("Masaüstü arayüzünde köprü anahtarı alanı yok")
        metin = metin.replace(YETENEK_YERI, yetenek)
        try:
            html_dogrula(metin)
        except PaketHatasi as exc:
            raise RuntimeError(
                f"Masaüstü arayüzüne köprü anahtarı yerleştirilemedi: {exc}"
            ) from exc
    return metin


def _hata(kod: int, mesaj: str) -> dict:
    return {"ok": False, "status": int(kod), "body": {"hata": mesaj}}


class PanelKoprusu:
    """WebView'a açılan dar ve JSON uyumlu yetki yüzeyi.

    Nesnenin kendisi ``js_api`` olarak verilmez. ``app.py`` yalnız ``invoke``
    bağlı metodunu ``Window.expose`` exact-name izin listesine ekler; gizli
    durum ve servis callable'ı WebView nesne ağacına hiç girmez. Yol ayrıca
    servis katmanının sabit API izin listesinden geçer; keyfî Python fonksiyonu
    ya da dosya yolu çalıştırılamaz.
    """

    def __init__(self, cagir=None, yetenek: str | None = None):
        self._cagir = cagir or panel_api.api_zarfi
        self._yetenek = yetenek or secrets.token_urlsafe(32)
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", self._yetenek):
            raise ValueError("Köprü yetenek anahtarı geçersiz")
        self._kosul = threading.Condition()
        self._aktif = 0
        self._kapaniyor = False

    def invoke(self, capability=None, method=None, path=None, body=None, *fazla):
        """Bir GET/POST API çağrısını güvenli sonuç zarfı olarak çalıştır."""
        with self._kosul:
            if self._kapaniyor:
                return _hata(503, "Panel kapatılıyor")
            self._aktif += 1

        try:
            if (not isinstance(capability, str)
                    or not secrets.compare_digest(capability, self._yetenek)):
                return _hata(403, "Masaüstü köprü yetkisi doğrulanamadı")
            if fazla:
                return _hata(400, "Köprü çağrısında fazla argüman var")
            if not isinstance(method, str):
                return _hata(400, "İstek yöntemi geçersiz")
            yontem = method.upper()
            if yontem not in ("GET", "POST"):
                return _hata(405, "İstek yöntemi desteklenmiyor")
            if not isinstance(path, str) or len(path) > YOL_SINIRI:
                return _hata(400, "İstek yolu geçersiz")

            u = urlsplit(path)
            if (u.scheme or u.netloc or u.fragment or
                    not u.path.startswith("/api/")):
                return _hata(400, "Yalnız panel API yolları kullanılabilir")

            if body is None:
                govde = {}
            elif isinstance(body, dict):
                govde = body
            else:
                return _hata(400, "İstek gövdesi bir nesne olmalı")
            try:
                ham = json.dumps(govde, ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError):
                return _hata(400, "İstek gövdesi JSON uyumlu değil")
            if len(ham) > ayar.GOVDE_SINIRI:
                return _hata(400, "İstek gövdesi çok büyük")

            sorgu = parse_qs(u.query, keep_blank_values=True)
            return self._cagir(yontem, u.path, query=sorgu, body=govde)
        except Exception:
            # Python traceback'i JS Promise'ına ve kullanıcı ekranına sızmaz.
            traceback.print_exc(file=sys.stderr)
            return _hata(500, "Panelde beklenmeyen bir sorun oluştu")
        finally:
            with self._kosul:
                self._aktif -= 1
                if self._aktif == 0:
                    self._kosul.notify_all()

    def _kapat(self, saniye: float | None = None) -> bool:
        """Yeni çağrıları keser ve süren köprü çağrılarının bitmesini bekler.

        Üretim kapanışında süre sınırı kullanılmaz. Aksi halde uzun süren bir
        cihaz işlemi devam ederken servis durumunu temizlemek, çalışan çağrının
        altındaki kimlikleri ve kuyrukları yok edebilirdi. ``saniye`` yalnız
        kontrollü test/tanı çağrıları için isteğe bağlı bir üst sınırdır.
        """
        son = (None if saniye is None
               else time.monotonic() + max(0.0, saniye))
        with self._kosul:
            self._kapaniyor = True
            while self._aktif:
                if son is None:
                    self._kosul.wait()
                    continue
                kalan = son - time.monotonic()
                if kalan <= 0:
                    break
                self._kosul.wait(kalan)
            return self._aktif == 0
