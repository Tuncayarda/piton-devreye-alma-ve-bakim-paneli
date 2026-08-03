# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller yapılandırması — Switch Yönetim Paneli.

    pip install pyinstaller
    pyinstaller SwitchYonetimPaneli.spec              # klasör (onedir)
    SYP_ONEFILE=1 pyinstaller SwitchYonetimPaneli.spec  # tek dosya (portable)

Windows'ta onefile için:  set SYP_ONEFILE=1 && pyinstaller ...

Çıktı:
    dist/SwitchYonetimPaneli/          onedir
    dist/SwitchYonetimPaneli(.exe)     onefile
    dist/Switch Yönetim Paneli.app     macOS (yalnız onedir)

Notlar:
  • Sürüm tek yerden gelir: switch_api.py içindeki APP_VERSION.
  • static/ pakete gömülür, çalışırken sys._MEIPASS altına açılır;
    switch_api.kaynak_dizini() iki durumu da bildiği için kod değişmez.
  • Pencere motorunun (PyObjC / PyQt / pythonnet) veri dosyaları
    collect_all ile toplanır — aksi halde paket açılıyor ama pencere
    açılmıyor.
"""
import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# ───────────────────────────────────────────────────────── build ortamı ──
# Dağıtım build'leri 3.12 ile alınır (bkz. BUILD.md). Başka sürümle
# denemek için SYP_PYTHON_SERBEST=1.
HEDEF_PYTHON = (3, 12)
if (sys.version_info[:2] != HEDEF_PYTHON
        and os.environ.get("SYP_PYTHON_SERBEST") != "1"):
    raise SystemExit(
        f"[spec] Build Python {HEDEF_PYTHON[0]}.{HEDEF_PYTHON[1]} ile "
        f"alınmalı, çalışan sürüm "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n"
        f"        Bilerek başka sürüm kullanıyorsan: "
        f"SYP_PYTHON_SERBEST=1 pyinstaller SwitchYonetimPaneli.spec")

KOK = Path(SPECPATH)
ADI = "SwitchYonetimPaneli"
GORUNEN_AD = "Switch Yönetim Paneli"
ONEFILE = os.environ.get("SYP_ONEFILE") == "1"


def surum() -> str:
    """Sürümü switch_api.py'den okur — tek kaynak orası.

    Modülü import etmiyoruz: import requests gerektirir ve build ortamında
    bulunmayabilir. Tek satırlık bir sabit, düz metin olarak okumak yeterli.
    """
    kaynak = (KOK / "switch_api.py").read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', kaynak, re.M)
    if not m:
        raise SystemExit("[spec] switch_api.py içinde APP_VERSION bulunamadı")
    return m.group(1)


SURUM = surum()
SURUM_DORTLU = tuple(int(x) for x in (SURUM.split(".") + ["0", "0", "0"])[:4])

# ────────────────────────────────────────────── platform bağımlılıkları ──
# Pencere motorunun paketleri: yalnız .py dosyaları değil, veri ve ikili
# dosyaları da gerekiyor. collect_all üçünü birden toplar.
ekstra_veri, ekstra_ikili, ekstra_gizli = [], [], []


def topla(paket: str, zorunlu: bool = False) -> None:
    try:
        veri, ikili, gizli = collect_all(paket)
    except Exception as exc:                       # paket kurulu değil
        if zorunlu:
            raise SystemExit(f"[spec] '{paket}' gerekli ama toplanamadı: {exc}")
        print(f"[spec] atlandı (kurulu değil): {paket}")
        return
    ekstra_veri.extend(veri)
    ekstra_ikili.extend(ikili)
    ekstra_gizli.extend(gizli)


topla("webview", zorunlu=True)
if sys.platform == "darwin":
    for p in ("objc", "Foundation", "AppKit", "WebKit", "Quartz", "Security"):
        topla(p)
elif sys.platform == "win32":
    topla("clr_loader")
    topla("pythonnet")
    ekstra_gizli += ["webview.platforms.winforms", "webview.platforms.edgechromium"]
else:
    for p in ("PyQt6", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineCore"):
        topla(p)
    ekstra_gizli += ["webview.platforms.qt"]

# ─────────────────────────────────────────────────────────────── simgeler ──
ICNS = KOK / "icons" / "app.icns"
ICO = KOK / "icons" / "app.ico"
exe_ikon = str(ICO) if (sys.platform == "win32" and ICO.exists()) else None
if sys.platform == "darwin" and ICNS.exists():
    exe_ikon = str(ICNS)

# ──────────────────────────────────────────── Windows sürüm bilgisi (exe) ──
version_dosyasi = None
if sys.platform == "win32":
    version_dosyasi = KOK / "build" / "version_info.txt"
    version_dosyasi.parent.mkdir(parents=True, exist_ok=True)
    version_dosyasi.write_text(f"""\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={SURUM_DORTLU}, prodvers={SURUM_DORTLU},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041f04b0', [
      StringStruct('CompanyName', 'Piton Technology'),
      StringStruct('FileDescription', '{GORUNEN_AD}'),
      StringStruct('FileVersion', '{SURUM}'),
      StringStruct('InternalName', '{ADI}'),
      StringStruct('OriginalFilename', '{ADI}.exe'),
      StringStruct('ProductName', '{GORUNEN_AD}'),
      StringStruct('ProductVersion', '{SURUM}'),
      StringStruct('LegalCopyright', 'Piton Technology')])]),
    VarFileInfo([VarStruct('Translation', [1055, 1200])])
  ]
)
""", encoding="utf-8")   # 1055 = Türkçe, 1200 = Unicode

# ──────────────────────────────────────────────────────────────── analiz ──
analiz = Analysis(
    ["app.py"],
    pathex=[str(KOK)],
    binaries=ekstra_ikili,
    datas=[("static", "static")] + ekstra_veri,
    hiddenimports=["switch_api"] + ekstra_gizli,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(analiz.pure, analiz.zipped_data)

ORTAK = dict(
    name=ADI,
    debug=False,
    strip=False,
    upx=False,
    console=False,                 # Windows: konsol penceresi açılmasın
    disable_windowed_traceback=False,
    icon=exe_ikon,
    version=str(version_dosyasi) if version_dosyasi else None,
)

if ONEFILE:
    # Tek dosya: taşınabilir ama her açılışta kendini geçici klasöre açar,
    # bu yüzden başlangıç birkaç saniye daha uzun sürer.
    exe = EXE(pyz, analiz.scripts, analiz.binaries, analiz.zipfiles,
              analiz.datas, [], exclude_binaries=False, **ORTAK)
    son = exe
else:
    exe = EXE(pyz, analiz.scripts, [], exclude_binaries=True, **ORTAK)
    son = COLLECT(exe, analiz.binaries, analiz.zipfiles, analiz.datas,
                  strip=False, upx=False, name=ADI)

# macOS'ta .app paketi: Dock'ta uygulama adı ve simgesi düzgün görünsün.
if sys.platform == "darwin" and not ONEFILE:
    app = BUNDLE(
        son,
        name=f"{GORUNEN_AD}.app",
        icon=str(ICNS) if ICNS.exists() else None,
        bundle_identifier="com.piton.switchyonetimpaneli",
        version=SURUM,
        info_plist={
            "CFBundleName": GORUNEN_AD,
            "CFBundleDisplayName": GORUNEN_AD,
            "CFBundleShortVersionString": SURUM,
            "CFBundleVersion": SURUM,
            "NSHighResolutionCapable": True,
            # 11.0 (Big Sur): setup-python'un arm64 derlemeleri ve PyObjC 10
            # bunun altını desteklemiyor. Daha eski bir değer yazmak
            # doğrulanmamış bir söz vermek olurdu.
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "Piton Technology",
            # Uygulama switch'leri yerel ağda arıyor; macOS 14+ bu izni
            # kullanıcıya sorar ve açıklamayı buradan okur.
            "NSLocalNetworkUsageDescription":
                "Uygulama, ağ üzerindeki yönetilebilir switch'leri bulmak ve "
                "yapılandırmak için yerel ağ erişimini kullanır.",
            # Arayüz 127.0.0.1 üzerinden servis ediliyor; switch'lere de
            # düz HTTP ile bağlanılıyor (cihazlar HTTPS sunmuyor).
            "NSAppTransportSecurity": {
                "NSAllowsLocalNetworking": True,
                "NSAllowsArbitraryLoads": True,
            },
        },
    )
