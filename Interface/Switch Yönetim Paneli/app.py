#!/usr/bin/env python3
"""Switch Yönetim Paneli — masaüstü uygulaması.

Yerel HTTP servisini arka planda başlatır ve arayüzü pywebview penceresinde
açar. Tarayıcı kullanılmaz: adres çubuğu, sekme, tarayıcıya düşme yoktur.
pywebview kurulu değilse uygulama açılmaz, sebebini söyleyip çıkar.

Platform gereksinimleri (docs/requirements-*.txt):
    Windows : pywebview + WebView2 çalışma zamanı (Edge ile birlikte gelir)
    macOS   : pywebview + pyobjc (WebKit)
    Ubuntu  : pywebview[qt] (PyQt/QtWebEngine)

Çalıştırma:
    python3 app.py
    python3 app.py --switch-port 8080     # switch'ler farklı porttaysa
"""
from __future__ import annotations

import argparse
import ctypes
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import traceback
from http.server import ThreadingHTTPServer
from pathlib import Path

# Paketleme ve çalıştırma için asgari sürüm. 3.9'da pywebview'in Qt ve
# WebView2 tarafları sorun çıkarıyor; dağıtım build'leri 3.12 ile alınır
# (bkz. docs/BUILD_RELEASE.md).
ASGARI_PYTHON = (3, 10)

APP_ADI = "Switch Yönetim Paneli"
KISA_AD = "SwitchYonetimPaneli"          # dosya/dizin adlarında kullanılır
WIDTH, HEIGHT = 1180, 780


# ─────────────────────────────────────────────────────────── konsol güvenliği
# İki ayrı sorun var, ikisi de Windows'ta:
#   1. --noconsole ile paketlenince stdout/stderr None olur; print()
#      AttributeError'a düşer.
#   2. Konsol kod sayfası cp1252 olduğunda Türkçe karakter yazmak
#      UnicodeEncodeError verir (GitHub Actions Windows runner'ında böyle).
#      Bu, log() içinde patladığı için hata yakalayıcıları da çökertiyordu.
# Program açılır açılmaz akışları güvenli hâle getiriyoruz.
def _akislari_bagla() -> None:
    for ad in ("stdout", "stderr"):
        akis = getattr(sys, ad, None)
        if akis is None:
            setattr(sys, ad, open(os.devnull, "w", encoding="utf-8"))
            continue
        try:
            # UTF-8'e çevir; çeviremezsek en azından hataları yut.
            akis.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            try:
                akis.reconfigure(errors="replace")
            except Exception:
                pass          # eski/tuhaf akış — log() zaten koruma altında


_akislari_bagla()


def _yazdir(mesaj: str) -> None:
    """print(), hiçbir kodlama hatasında programı düşürmemeli."""
    try:
        print(mesaj)
    except UnicodeEncodeError:
        # Son çare: hedefin kaldırabileceği karakterlere indirge
        kodlama = getattr(sys.stdout, "encoding", None) or "ascii"
        try:
            print(mesaj.encode(kodlama, "replace").decode(kodlama, "replace"))
        except Exception:
            pass
    except Exception:
        pass


# ───────────────────────────────────────────────────────────────── loglama ──
def log_dizini() -> Path:
    """Log klasörü — uygulama klasörüne asla yazmayız.

    Program dosyaları salt okunur olabilir (Program Files, /Applications,
    imzalı .app paketi); kullanıcının kendi dizini her platformda yazılabilir.
    """
    sistem = platform.system()
    if sistem == "Windows":
        temel = Path(os.environ.get("LOCALAPPDATA")
                     or Path.home() / "AppData" / "Local")
        return temel / KISA_AD / "logs"
    if sistem == "Darwin":
        return Path.home() / "Library" / "Logs" / KISA_AD
    temel = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return temel / KISA_AD


LOG_DOSYASI = log_dizini() / "uygulama.log"
LOG_SINIRI = 512 * 1024          # 512 KB'ı geçince devret
LOG_YEDEK = 2                    # uygulama.log.1, uygulama.log.2
_LOG_KILIT = threading.Lock()


def _log_devret() -> None:
    """Dosya büyüdüyse .1/.2 diye kaydırır, en eskisini siler.

    Uygulama uzun süre açık kalabildiği için log sınırsız büyümemeli.
    Kendi döngümüzü yazıyoruz: logging.RotatingFileHandler tek başına
    fazladan yapılandırma getiriyor, burada tek satırlık ihtiyaç var.
    """
    try:
        if not LOG_DOSYASI.exists() or LOG_DOSYASI.stat().st_size < LOG_SINIRI:
            return
        en_eski = LOG_DOSYASI.with_suffix(f".log.{LOG_YEDEK}")
        if en_eski.exists():
            en_eski.unlink()
        for i in range(LOG_YEDEK - 1, 0, -1):
            kaynak = LOG_DOSYASI.with_suffix(f".log.{i}")
            if kaynak.exists():
                kaynak.replace(LOG_DOSYASI.with_suffix(f".log.{i + 1}"))
        LOG_DOSYASI.replace(LOG_DOSYASI.with_suffix(".log.1"))
    except OSError:
        pass


def log(mesaj: str) -> None:
    """Hem konsola (varsa) hem log dosyasına yazar; asla patlamaz.

    Buradan istisna sızarsa hata yakalayıcıların kendisi çöker — o yüzden
    hem yazdırma hem dosya yazımı tamamen korunuyor.
    """
    _yazdir(mesaj)
    damga = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _LOG_KILIT:
            LOG_DOSYASI.parent.mkdir(parents=True, exist_ok=True)
            _log_devret()
            with LOG_DOSYASI.open("a", encoding="utf-8") as f:
                f.write(f"{damga}  {mesaj}\n")
    except Exception:
        pass          # log yazılamıyorsa uygulama yine de çalışsın


# --self-test gibi otomatik çalışmalarda işletim sistemi diyaloğu açılmamalı;
# hata yalnızca log'a ve çıkış koduna yansır.
SESSIZ = False


def hata_goster(baslik: str, mesaj: str) -> None:
    """Konsol olmayabileceği için hatayı pencereyle bildirir."""
    log(f"[HATA] {baslik}: {mesaj}")
    if SESSIZ:
        return
    sistem = platform.system()
    try:
        if sistem == "Windows":
            ctypes.windll.user32.MessageBoxW(None, mesaj, f"{APP_ADI} — {baslik}",
                                             0x10)
        elif sistem == "Darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display alert "{baslik}" message "{mesaj}" as critical'],
                check=False, capture_output=True)
        else:
            for arac in (["zenity", "--error", "--title", baslik, "--text", mesaj],
                         ["kdialog", "--error", mesaj]):
                try:
                    subprocess.run(arac, check=False, capture_output=True)
                    break
                except FileNotFoundError:
                    continue
    except Exception:
        pass          # bildirim gösterilemese de log dosyasında duruyor


# ─────────────────────────────────────────────────────────────── yerel servis
def bos_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sunucu_baslat(port: int, handler) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    srv.daemon_threads = True          # kapanırken açık istekler asılı kalmasın
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def sunucu_kapat(srv: ThreadingHTTPServer | None) -> None:
    """Dinlemeyi durdurur ve soketi kapatır; iki kez çağrılabilir."""
    if srv is None:
        return
    try:
        srv.shutdown()
        srv.server_close()
    except Exception:
        pass


def sunucu_bekle(port: int, saniye: float = 5.0) -> bool:
    """Servis ayağa kalkana kadar bekler; kalkmazsa False."""
    for _ in range(int(saniye / 0.05)):
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


# ──────────────────────────────────────────────────────────────── macOS adı ──
def macos_kimlik() -> None:
    """Dock ve menü çubuğunda yorumlayıcının adı yerine uygulama adı çıksın.

    Yalnızca kaynaktan çalışırken gerekir: paketlenmiş .app'te bu bilgi
    Info.plist'ten gelir (bkz. SwitchYonetimPaneli.spec). pyobjc yoksa
    sessizce atlanır.
    """
    if platform.system() != "Darwin" or getattr(sys, "frozen", False):
        return
    try:
        from Foundation import NSBundle
    except Exception:
        return
    try:
        bilgi = (NSBundle.mainBundle().localizedInfoDictionary()
                 or NSBundle.mainBundle().infoDictionary())
        if bilgi is not None:
            bilgi["CFBundleName"] = APP_ADI
            bilgi["CFBundleDisplayName"] = APP_ADI
    except Exception:
        pass


# ────────────────────────────────────────────────────────────── self-test ──
# Paketin gerçekten çalışabilir olduğunu pencere açmadan doğrular.
# Yalnızca 127.0.0.1'e bağlanır: switch taraması yapmaz, yerel ağdaki
# cihazlara dokunmaz, internete çıkmaz, kimlik sormaz.
GEREKLI_VARLIKLAR = ("index.html", "app.js", "style.css",
                     "piton-logo.svg", "piton-favicon.png")


def _kontrol(ad: str, kosul: bool, ayrinti: str = "") -> bool:
    isaret = "OK  " if kosul else "HATA"
    log(f"  [{isaret}] {ad}" + (f" — {ayrinti}" if ayrinti else ""))
    return kosul


def self_test() -> int:
    """Bağımlılık + kaynak dosya + yerel sunucu doğrulaması. 0 = başarılı."""
    global SESSIZ
    SESSIZ = True
    log(f"{APP_ADI} — self-test  (python "
        f"{sys.version_info.major}.{sys.version_info.minor}."
        f"{sys.version_info.micro}, "
        f"{'paketlenmiş' if getattr(sys, 'frozen', False) else 'kaynak'})")

    sonuclar: list[bool] = []
    srv = None
    try:
        # 1) Zorunlu bağımlılıklar
        try:
            import webview
            sonuclar.append(_kontrol("pywebview içe aktarıldı", True,
                                     getattr(webview, "__version__", "sürüm ?")))
        except Exception as exc:
            sonuclar.append(_kontrol("pywebview içe aktarıldı", False, str(exc)))
        try:
            import requests
            sonuclar.append(_kontrol("requests içe aktarıldı", True,
                                     requests.__version__))
        except Exception as exc:
            sonuclar.append(_kontrol("requests içe aktarıldı", False, str(exc)))

        # Windows'ta asıl kırılgan yer pencere motorunun .NET köprüsü.
        # Yalnızca "import webview" demek yetmiyor: paket bozuksa ya da
        # Windows dosyaları engellediyse (Zone.Identifier) hata ancak
        # pythonnet/WinForms yüklenirken çıkıyor.
        if platform.system() == "Windows":
            try:
                import clr                                   # noqa: F401
                sonuclar.append(_kontrol("pythonnet (clr) yüklendi", True))
            except Exception as exc:
                sonuclar.append(_kontrol(
                    "pythonnet (clr) yüklendi", False,
                    f"{type(exc).__name__}: {exc}"))
            try:
                import webview.platforms.winforms             # noqa: F401
                sonuclar.append(_kontrol("WinForms pencere motoru yüklendi", True))
            except Exception as exc:
                sonuclar.append(_kontrol(
                    "WinForms pencere motoru yüklendi", False,
                    f"{type(exc).__name__}: {exc}"))
            surum = webview2_surumu()
            sonuclar.append(_kontrol("WebView2 Runtime kurulu",
                                     surum is not None, surum or "bulunamadı"))

        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import switch_api
        except Exception as exc:
            _kontrol("switch_api içe aktarıldı", False, str(exc))
            return 1
        sonuclar.append(_kontrol("switch_api içe aktarıldı", True,
                                 f"sürüm {switch_api.APP_VERSION}"))

        # 2) Arayüz dosyaları — kaynakta da paketlenmiş halde de bulunmalı
        kok = switch_api.STATIC_DIR
        sonuclar.append(_kontrol("static klasörü bulundu", kok.is_dir(), str(kok)))
        for ad in GEREKLI_VARLIKLAR:
            dosya = kok / ad
            sonuclar.append(_kontrol(
                f"static/{ad}", dosya.is_file() and dosya.stat().st_size > 0))

        # 3) Yerel sunucu — rastgele boş portta
        port = bos_port()
        srv = sunucu_baslat(port, switch_api.Handler)
        sonuclar.append(_kontrol("yerel sunucu açıldı", sunucu_bekle(port, 10.0),
                                 f"127.0.0.1:{port}"))

        # 4) HTTP yanıtları ve içerik işareti
        import json
        import urllib.request

        def iste(yol: str):
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{yol}", timeout=5) as r:
                return r.status, r.read()

        try:
            kod, govde = iste("/")
            metin = govde.decode("utf-8", "replace")
            sonuclar.append(_kontrol("GET / → 200", kod == 200, f"{len(govde)} bayt"))
            sonuclar.append(_kontrol(
                "ana sayfa uygulamaya ait", APP_ADI in metin and 'id="detail"' in metin))
            sonuclar.append(_kontrol(
                "varlık adresleri sürümlenmiş", "/app.js?v=" in metin))
        except Exception as exc:
            sonuclar.append(_kontrol("GET /", False, str(exc)))

        try:
            kod, govde = iste("/api/version")
            veri = json.loads(govde.decode("utf-8"))
            sonuclar.append(_kontrol(
                "GET /api/version → sürüm", kod == 200
                and veri.get("version") == switch_api.APP_VERSION,
                str(veri)))
        except Exception as exc:
            sonuclar.append(_kontrol("GET /api/version", False, str(exc)))

        for varlik in ("/app.js", "/style.css"):
            try:
                kod, govde = iste(varlik)
                sonuclar.append(_kontrol(f"GET {varlik} → 200",
                                         kod == 200 and len(govde) > 0))
            except Exception as exc:
                sonuclar.append(_kontrol(f"GET {varlik}", False, str(exc)))

    except Exception:
        log("[HATA] self-test beklenmeyen hata:\n" + traceback.format_exc(limit=5))
        return 1
    finally:
        # Başarılı da olsa hata da alsa sunucu her koşulda kapanır.
        sunucu_kapat(srv)

    basarisiz = sonuclar.count(False)
    log(f"self-test: {len(sonuclar) - basarisiz}/{len(sonuclar)} kontrol geçti")
    return 1 if basarisiz else 0


# ───────────────────────────────────────────────────────────────────── main ─
PYWEBVIEW_YOK = (
    "Uygulama penceresi için pywebview gerekli ve kurulu değil.\n\n"
    "Kurulum (uygulama klasöründe):\n"
    "  Windows : pip install -r docs/requirements-windows.txt\n"
    "  macOS   : pip install -r docs/requirements-macos.txt\n"
    "  Ubuntu  : pip install -r docs/requirements-linux.txt"
)


WEBVIEW2_ANAHTAR = (r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
                    r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")


def webview2_surumu() -> str | None:
    """Kurulu WebView2 Runtime sürümü; kurulu değilse None.

    Tahmin yürütmüyoruz: Microsoft'un resmî ürün kimliğini hem makine hem
    kullanıcı kovanında, 32-bit görünümde arıyoruz (EdgeUpdate oraya yazar).
    """
    if platform.system() != "Windows":
        return None
    try:
        import winreg
    except ImportError:
        return None
    for kovan in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(kovan, WEBVIEW2_ANAHTAR, 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as k:
                surum, _ = winreg.QueryValueEx(k, "pv")
                if surum and surum != "0.0.0.0":
                    return str(surum)
        except OSError:
            continue
    return None


# .NET'in "derleme yüklenemedi" hatası. En sık sebebi, ZIP'ten çıkarılan
# dosyalara Windows'un "internetten indirildi" damgası (Zone.Identifier)
# koyup DLL yüklemesini engellemesi.
DLL_ENGEL_IZLERI = ("0x80131515", "python.runtime",
                    "could not load file or assembly",
                    "dosya veya derleme yüklenemedi")


def pencere_hatasi(iz: str) -> str:
    """Pencere açılamama hatasını kullanıcının anlayacağı dile çevirir.

    Kelime eşleştirerek tahmin yürütmüyoruz — eskiden içinde "clr" ya da
    "edge" geçen her hata "WebView2 yok" diye gösteriliyordu ve kurulu bir
    sistemde insanı yanlış yöne sürüklüyordu. Artık:
      • önce gerçekten engellenmiş dosya izlerine bakıyoruz,
      • sonra WebView2'nin kurulu olup olmadığını registry'den soruyoruz,
      • ikisi de değilse ham izi olduğu gibi veriyoruz.
    Ham yığın izi her hâlükârda log dosyasına yazılır (bkz. hata_goster).
    """
    kucuk = iz.lower()
    sistem = platform.system()

    if sistem == "Windows":
        if any(z in kucuk for z in DLL_ENGEL_IZLERI):
            return ("Windows, uygulama dosyalarının bir kısmını engelliyor.\n\n"
                    "ZIP olarak indirilen dosyalara \"internetten geldi\" "
                    "damgası konduğu için .NET, Python.Runtime.dll dosyasını "
                    "yükleyemiyor.\n\n"
                    "Çözüm — uygulama klasöründe PowerShell açıp:\n"
                    "  Get-ChildItem -Recurse -File | Unblock-File\n\n"
                    "Kalıcı çözüm: ZIP yerine kurulum paketini (Setup.exe) "
                    "kullanın.\n\n"
                    "Ayrıntı log dosyasında:\n" + str(LOG_DOSYASI))

        surum = webview2_surumu()
        if surum is None:
            return ("Microsoft Edge WebView2 çalışma zamanı bulunamadı.\n\n"
                    "Windows 10 21H2 ve sonrasında genelde kuruludur. "
                    "Değilse Microsoft'un ücretsiz \"Evergreen WebView2 "
                    "Runtime\" kurulumunu yapın:\n"
                    "https://developer.microsoft.com/microsoft-edge/webview2/"
                    "\n\nAyrıntı log dosyasında:\n" + str(LOG_DOSYASI))
        # WebView2 kurulu — sorun başka yerde, yanıltmayalım
        return (f"Pencere açılamadı. (WebView2 kurulu: {surum})\n\n"
                "Ayrıntı log dosyasında:\n" + str(LOG_DOSYASI) + "\n\n" + iz)

    if sistem == "Linux" and ("qt" in kucuk or "gtk" in kucuk):
        return ("Pencere motoru yüklenemedi (Qt/GTK).\n\n"
                "Eksik sistem kütüphaneleri olabilir:\n"
                "  sudo apt install libxcb-cursor0 libegl1 libgl1\n\n"
                "Ayrıntı log dosyasında:\n" + str(LOG_DOSYASI))
    return iz


def main() -> int:
    global SESSIZ
    # Otomatik çalışmalarda (CI) hiçbir koşulda diyalog açılmasın.
    if {"--self-test", "--version"} & set(sys.argv[1:]):
        SESSIZ = True

    if sys.version_info < ASGARI_PYTHON:
        hata_goster(
            "Python sürümü yetersiz",
            f"Bu uygulama Python {ASGARI_PYTHON[0]}.{ASGARI_PYTHON[1]} ve "
            f"üzerini gerektiriyor.\nÇalışan sürüm: "
            f"{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}")
        return 1

    ap = argparse.ArgumentParser(description=APP_ADI)
    ap.add_argument("--switch-port", type=int, default=None,
                    help="switch'lerin HTTP portu (varsayılan 80)")
    ap.add_argument("--self-test", action="store_true",
                    help="pencere açmadan paketi doğrula (CI için); "
                         "başarılı 0, başarısız 1 döner")
    ap.add_argument("--version", action="store_true",
                    help="sürümü yazdır ve çık")
    a = ap.parse_args()

    if a.version:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import switch_api
        print(switch_api.APP_VERSION)
        return 0

    if a.self_test:
        return self_test()

    try:
        import webview
    except ImportError:
        hata_goster("Eksik bağımlılık", PYWEBVIEW_YOK)
        return 1

    # Backend'i pencereden sonra değil, önce içe aktarıyoruz ki bir sorun
    # varsa pencere açılmadan anlaşılır bir hata verelim.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import switch_api
    except Exception:
        hata_goster("Başlatılamadı", traceback.format_exc(limit=3))
        return 1

    if a.switch_port:
        switch_api.SWITCH_PORT = a.switch_port

    port = bos_port()
    try:
        srv = sunucu_baslat(port, switch_api.Handler)
    except OSError as exc:
        hata_goster("Başlatılamadı", f"Yerel servis açılamadı: {exc}")
        return 1
    if not sunucu_bekle(port):
        sunucu_kapat(srv)
        hata_goster("Başlatılamadı", "Yerel servis yanıt vermedi.")
        return 1

    url = f"http://127.0.0.1:{port}"
    log(f"{APP_ADI} {switch_api.APP_VERSION} — {url}")
    log(f"Arayüz dosyaları: {switch_api.STATIC_DIR}")
    log(f"Switch'ler {switch_api.SWITCH_PORT} portunda aranacak")
    log(f"Log: {LOG_DOSYASI}")

    # Penceresiz kip: paketlenmiş uygulamanın servis tarafını ekransız
    # ortamda (CI, sunucu) sınamak için. Pencere açılmaz, Ctrl-C ile durur.
    if os.environ.get("SYP_HEADLESS") == "1":
        log("Penceresiz kip — durdurmak için Ctrl-C")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            sunucu_kapat(srv)
        return 0

    macos_kimlik()
    try:
        webview.create_window(APP_ADI, url, width=WIDTH, height=HEIGHT,
                              min_size=(900, 600))
        # Pencere kapanınca webview.start() döner; sunucuyu da o an kapatırız.
        webview.start()
    except Exception:
        # Ham yığın izi her koşulda log'a düşsün: kullanıcıya gösterdiğimiz
        # sadeleştirilmiş mesaj teşhis için yeterli olmayabilir.
        ham = traceback.format_exc()
        log("[İZ] pencere açılamadı:\n" + ham)
        s = webview2_surumu()
        log(f"[BİLGİ] WebView2: {s if s else 'kurulu değil / okunamadı'}")
        hata_goster("Pencere açılamadı", pencere_hatasi(ham))
        return 1
    finally:
        log("Pencere kapandı, yerel servis durduruluyor.")
        sunucu_kapat(srv)
    return 0


if __name__ == "__main__":
    try:
        kod = main()
    except Exception:
        hata_goster("Beklenmeyen hata", traceback.format_exc(limit=5))
        kod = 1
    # Arka planda kalan iş parçacığı varsa süreci kesin olarak sonlandır.
    sys.exit(kod)
