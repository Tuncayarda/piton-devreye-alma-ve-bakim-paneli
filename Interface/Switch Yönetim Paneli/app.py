#!/usr/bin/env python3
"""Switch Yönetim Paneli — masaüstü uygulaması.

Arka planda yerel servisi başlatır ve arayüzü kendi penceresinde açar.
Tarayıcı adres çubuğu, sekme, URL yazma yok.

Pencere seçimi (sırayla denenir):
  1. pywebview  -> gerçek native pencere (macOS WKWebView)
  2. Chrome/Edge --app modu -> çerçevesiz uygulama penceresi
  3. varsayılan tarayıcı -> son çare

Çalıştırma:
    "Switch Yönetim Paneli.app" dosyasına çift tıkla
    python3 app.py                 (geliştirme için)
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import switch_api  # noqa: E402

TITLE = "Switch Yönetim Paneli"
WIDTH, HEIGHT = 1180, 780

# Dock simgesi paketin içinden okunur
ICON_PNG = (HERE / "Switch Yönetim Paneli.app" / "Contents" / "Resources"
            / "AppIcon.png")


def macos_kimlik() -> None:
    """Dock ve menü çubuğunda "Python" yerine uygulama adı/simgesi görünsün.

    pywebview penceresi Python süreci üzerinden açıldığı için macOS
    uygulamayı yorumlayıcının adıyla gösterebiliyor. Paket bilgisini ve
    Dock simgesini çalışma anında düzeltiyoruz. pyobjc yoksa sessizce
    atlanır — uygulama yine çalışır.
    """
    try:
        from Foundation import NSBundle
        from AppKit import NSApplication, NSImage
    except Exception:
        return
    try:
        bundle = NSBundle.mainBundle()
        bilgi = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if bilgi is not None:
            bilgi["CFBundleName"] = TITLE
            bilgi["CFBundleDisplayName"] = TITLE
        if ICON_PNG.exists():
            img = NSImage.alloc().initWithContentsOfFile_(str(ICON_PNG))
            if img:
                NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), switch_api.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # ayağa kalkmasını bekle
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                return srv
        except OSError:
            time.sleep(0.05)
    return srv


def open_native(url: str) -> bool:
    """pywebview varsa gerçek uygulama penceresi açar."""
    try:
        import webview
    except ImportError:
        return False
    macos_kimlik()
    webview.create_window(TITLE, url, width=WIDTH, height=HEIGHT,
                          min_size=(900, 600))
    webview.start()
    return True


CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def open_app_window(url: str) -> subprocess.Popen | None:
    """Chrome tabanlı bir tarayıcıyı --app modunda açar.

    Adres çubuğu ve sekme çubuğu olmayan, ayrı bir pencere gelir.
    """
    profile = HERE / ".appwindow"
    for path in CHROME_PATHS:
        if Path(path).exists():
            return subprocess.Popen(
                [path, f"--app={url}",
                 f"--user-data-dir={profile}",
                 f"--window-size={WIDTH},{HEIGHT}",
                 f"--class={TITLE}",
                 "--no-first-run", "--no-default-browser-check"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=TITLE)
    ap.add_argument("--switch-port", type=int, default=None,
                    help="switch'lerin HTTP portu (varsayılan .env'den). "
                         "Sahte switch'le denemek için: --switch-port 8080")
    a = ap.parse_args()
    if a.switch_port:
        switch_api.SWITCH_PORT = a.switch_port

    if not switch_api.SWITCH_PASS:
        print("[!] Switch şifresi yok. Interface/.env içine SWITCH_PASSWORD "
              "ekleyin.")

    port = free_port()
    start_server(port)
    url = f"http://127.0.0.1:{port}"
    print(f"{TITLE} çalışıyor — {url}")
    print(f"Arayüz dosyaları: {HERE / 'static'}")
    print(f"Switch'ler {switch_api.SWITCH_PORT} portunda aranacak "
          f"(kullanıcı: {switch_api.SWITCH_USER})")

    # 1) gerçek native pencere
    if open_native(url):
        print("Pencere: pywebview (native)")
        return 0

    # 2) çerçevesiz uygulama penceresi
    proc = open_app_window(url)
    if proc is not None:
        print("Pencere: Chrome --app")
        print("Uygulama penceresi açıldı. Pencereyi kapatınca sonlanır.")
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
        return 0

    # 3) son çare
    print("Native pencere için:  pip install pywebview")
    import webbrowser
    webbrowser.open(url)
    print("Kapatmak için Ctrl-C.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
