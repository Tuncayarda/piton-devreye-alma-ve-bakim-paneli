#!/usr/bin/env python3
"""Devreye Alma Paneli — masaüstü uygulaması.

Yerel HTTP servisini arka planda başlatır ve arayüzü pywebview
penceresinde açar. Adres çubuğu, sekme ya da tarayıcıya düşme yoktur.

Kapanışta yalnız pencere değil, servisin arkasındaki her şey de temizlenir:
iş kuyruğu durdurulur, MQTT dinleyicisi kapatılır ve bellekteki bütün
cihaz kimlikleri unutulur (bkz. panel_api.temizle).

Çalıştırma:
    python3 app.py
    python3 app.py --tarayici              # pencere yerine tarayıcıda aç
    python3 app.py --admin-parolasi ****   # admin ekranını şifreye bağla
    python3 app.py --self-test             # pencere açmadan doğrula
"""
from __future__ import annotations

import argparse
import os
import platform
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

BURASI = Path(__file__).resolve().parent
sys.path.insert(0, str(BURASI))

ASGARI_PYTHON = (3, 10)
GENISLIK, YUKSEKLIK = 1440, 900

PYWEBVIEW_YOK = (
    "Uygulama penceresi için pywebview gerekli ve kurulu değil.\n\n"
    "Kurulum:\n"
    "    python3 -m pip install -r docs/requirements.txt\n\n"
    "Pencere olmadan denemek için:\n"
    "    python3 app.py --tarayici"
)


def yaz(mesaj: str) -> None:
    try:
        print(mesaj)
    except Exception:
        pass


def bos_port() -> int:
    """İşletim sisteminin verdiği boş bir yerel port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sunucu_bekle(port: int, saniye: float = 5.0) -> bool:
    for _ in range(int(saniye / 0.05)):
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def macos_kimlik(ad: str) -> None:
    """Dock'ta yorumlayıcının adı yerine uygulama adı görünsün."""
    if platform.system() != "Darwin" or getattr(sys, "frozen", False):
        return
    try:
        from Foundation import NSBundle
        bilgi = (NSBundle.mainBundle().localizedInfoDictionary()
                 or NSBundle.mainBundle().infoDictionary())
        if bilgi is not None:
            bilgi["CFBundleName"] = ad
            bilgi["CFBundleDisplayName"] = ad
    except Exception:
        pass


def self_test() -> int:
    """Pencere açmadan paketi doğrular. Ağa çıkmaz, cihaza bağlanmaz."""
    import json
    import urllib.request

    from core import ayar, device_map
    import panel_api

    sonuc = []

    def kontrol(ad: str, kosul: bool, ek: str = "") -> bool:
        yaz(f"  [{'OK  ' if kosul else 'HATA'}] {ad}" + (f" — {ek}" if ek else ""))
        sonuc.append(kosul)
        return kosul

    yaz(f"{ayar.APP_ADI} {ayar.APP_VERSION} — self-test")

    kontrol("DeviceMap bulundu", ayar.DEVICE_MAP.exists(), str(ayar.DEVICE_MAP))
    kontrol("Excel şablonu bulundu", ayar.EXCEL_SABLON.exists())
    for varlik in ("index.html", "css/temel.css", "js/app.js",
                   "piton-logo.svg", "piton-favicon.png"):
        kontrol(f"static/{varlik}", (ayar.STATIC_DIR / varlik).exists())
    # Kardeş projelerdeki üç betik (bkz. core/betik.py). Paketlenmiş
    # uygulamada bunlar paketin içine kopyalanır; biri eksikse switch
    # okuması, IP atama ya da Excel çıktısı sahada çalışmaz — paket
    # üretildiği yerde anlaşılsın.
    for ad, yol in (("Switch Yönetim Paneli backend'i", ayar.SWITCH_PANELI),
                    ("Saha doğrulama betiği", ayar.DEVICE_VERIFY),
                    ("IP atama betiği", ayar.INTERCOM_IP_ASSIGN)):
        kontrol(ad, yol.exists(), str(yol))

    try:
        env = device_map.yukle(1)
        kontrol("DeviceMap okundu", len(env.cihazlar) > 0,
                f"{len(env.cihazlar)} cihaz")
    except Exception as exc:
        kontrol("DeviceMap okundu", False, str(exc))

    port = bos_port()
    srv = panel_api.sunucu("127.0.0.1", port)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        kontrol("Yerel servis açıldı", sunucu_bekle(port))
        for yol in ("/api/surum", "/api/proje?set=1", "/api/durum?set=1"):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}{yol}", timeout=3) as y:
                    veri = json.loads(y.read())
                kontrol(f"GET {yol}", isinstance(veri, dict))
            except Exception as exc:
                kontrol(f"GET {yol}", False, str(exc))
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as y:
                kontrol("Arayüz sunuluyor", b"<!DOCTYPE html>" in y.read(200))
        except Exception as exc:
            kontrol("Arayüz sunuluyor", False, str(exc))
    finally:
        srv.shutdown()
        srv.server_close()
        panel_api.temizle()

    basarili = all(sonuc)
    yaz("SONUÇ: " + ("başarılı" if basarili else "başarısız"))
    return 0 if basarili else 1


def main() -> int:
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if sys.version_info < ASGARI_PYTHON:
        yaz(f"[HATA] Python {ASGARI_PYTHON[0]}.{ASGARI_PYTHON[1]}+ gerekli.")
        return 1

    ap = argparse.ArgumentParser(description="Devreye Alma Paneli")
    ap.add_argument("--tarayici", action="store_true",
                    help="pencere yerine varsayılan tarayıcıda aç")
    ap.add_argument("--port", type=int, default=0,
                    help="yerel servis portu (0 = boş port seç)")
    ap.add_argument("--admin-parolasi", default=None,
                    help="admin ekranı bu şifreyi sorar; hiçbir yere yazılmaz")
    ap.add_argument("--self-test", action="store_true",
                    help="pencere açmadan paketi doğrula")
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args()

    from core import ayar
    if a.version:
        yaz(ayar.APP_VERSION)
        return 0
    if a.self_test:
        return self_test()

    import panel_api
    panel_api.admin_parolasi_ayarla(
        a.admin_parolasi or os.environ.get("PANEL_ADMIN_PAROLASI"))

    port = a.port or bos_port()
    try:
        srv = panel_api.sunucu("127.0.0.1", port)
    except OSError as exc:
        yaz(f"[HATA] Yerel servis açılamadı: {exc}")
        return 1
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if not sunucu_bekle(port):
        srv.shutdown()
        yaz("[HATA] Yerel servis yanıt vermedi.")
        return 1

    url = f"http://127.0.0.1:{port}"
    yaz(f"{ayar.APP_ADI} {ayar.APP_VERSION} — {url}")
    yaz(f"DeviceMap: {ayar.DEVICE_MAP}")
    yaz("Kimlik bilgileri arayüzden istenir, hiçbir yere yazılmaz.")

    try:
        if a.tarayici:
            webbrowser.open(url)
            yaz("Tarayıcı kipi — durdurmak için Ctrl-C")
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                yaz("\nKapatılıyor.")
            return 0

        try:
            import webview
        except ImportError:
            yaz("[HATA] " + PYWEBVIEW_YOK)
            return 1

        macos_kimlik(ayar.APP_ADI)
        webview.create_window(ayar.APP_ADI, url,
                              width=GENISLIK, height=YUKSEKLIK,
                              min_size=(980, 620))
        webview.start()
        return 0
    except Exception:
        yaz("[HATA] Pencere açılamadı:\n" + traceback.format_exc(limit=4))
        return 1
    finally:
        # Pencere kapandı: servis, kuyruk ve bellekteki kimlikler gider.
        yaz("Pencere kapandı, yerel servis durduruluyor.")
        srv.shutdown()
        srv.server_close()
        panel_api.temizle()


if __name__ == "__main__":
    sys.exit(main())
