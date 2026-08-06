# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller yapılandırması — Devreye Alma Paneli.

    pip install -r docs/requirements-build.txt
    pyinstaller DevreyeAlmaPaneli.spec               # klasör (onedir)
    DAP_ONEFILE=1 pyinstaller DevreyeAlmaPaneli.spec # tek dosya (portable)

Windows'ta onefile için:  set DAP_ONEFILE=1 && pyinstaller ...

Çıktı:
    dist/DevreyeAlmaPaneli/            onedir
    dist/DevreyeAlmaPaneli(.exe)       onefile
    dist/Devreye Alma Paneli.app       macOS (yalnız onedir)

Notlar:
  • Sürüm tek yerden gelir: core/ayar.py içindeki APP_VERSION.
  • Panel, projedeki üç veri dosyasını ve kardeş projelerdeki üç betiği
    çalışma anında okur. Bunlar paketin KÖKÜNE kopyalanır; ayar.veri_dosyasi()
    paketlenmiş durumda oraya bakar (bkz. core/ayar.py).
  • Pencere motorunun (PyObjC / PyQt / pythonnet) veri dosyaları collect_all
    ile toplanır — aksi halde paket açılıyor ama pencere açılmıyor.
"""
import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# ───────────────────────────────────────────────────────── build ortamı ──
# Dağıtım build'leri 3.12 ile alınır (bkz. docs/BUILD_RELEASE.md). Başka
# sürümle denemek için DAP_PYTHON_SERBEST=1.
HEDEF_PYTHON = (3, 12)
if (sys.version_info[:2] != HEDEF_PYTHON
        and os.environ.get("DAP_PYTHON_SERBEST") != "1"):
    raise SystemExit(
        f"[spec] Build Python {HEDEF_PYTHON[0]}.{HEDEF_PYTHON[1]} ile "
        f"alınmalı, çalışan sürüm "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n"
        f"        Bilerek başka sürüm kullanıyorsan: "
        f"DAP_PYTHON_SERBEST=1 pyinstaller DevreyeAlmaPaneli.spec")

KOK = Path(SPECPATH)
ADI = "DevreyeAlmaPaneli"
GORUNEN_AD = "Devreye Alma Paneli"
ONEFILE = os.environ.get("DAP_ONEFILE") == "1"


def surum() -> str:
    """Sürümü core/ayar.py'den okur — tek kaynak orası.

    Modülü import etmiyoruz: import requests gerektirir ve build ortamında
    bulunmayabilir. Tek satırlık bir sabit, düz metin olarak okumak yeterli.
    """
    kaynak = (KOK / "core" / "ayar.py").read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', kaynak, re.M)
    if not m:
        raise SystemExit("[spec] core/ayar.py içinde APP_VERSION bulunamadı")
    return m.group(1)


SURUM = surum()
# Windows sürüm kaynağı yalnız sayı kabul eder; "0.9.0-dev" gibi ön sürüm
# ekleri atılır (görünen sürüm metni SURUM olarak kalır).
_SAYILAR = re.findall(r"\d+", SURUM.split("-")[0].split("+")[0])
SURUM_DORTLU = tuple(int(x) for x in (_SAYILAR + ["0", "0", "0", "0"])[:4])

# ────────────────────────────────────── uygulamayla giden veri dosyaları ──
# (kaynaktaki yol, paketteki ad). Paketin köküne konur; eksik olan build'i
# durdurur — sessizce yarım paket üretmek, sahada "DeviceMap bulunamadı"
# diye açılmayan bir uygulama demek.
KARDES = KOK.parent.parent            # depo kökü
VERI_DOSYALARI = [
    (KOK / "DeviceMap.json", "DeviceMap.json"),
    (KOK / "Yatakli_Saha_Cihaz_Dogrulama.xlsx",
     "Yatakli_Saha_Cihaz_Dogrulama.xlsx"),
    (KOK.parent / "Switch Yönetim Paneli" / "switch_api.py", "switch_api.py"),
    (KARDES / "YATAKLI_DevreyeAlma" / "device_verify.py", "device_verify.py"),
    (KARDES / "YATAKLI_DevreyeAlma" / "intercom_ip_assign.py",
     "intercom_ip_assign.py"),
]

veri = [("static", "static")]
eksik = []
for kaynak_yol, paket_adi in VERI_DOSYALARI:
    if kaynak_yol.exists():
        veri.append((str(kaynak_yol), "."))
    else:
        eksik.append(str(kaynak_yol))
if eksik:
    raise SystemExit("[spec] pakete girecek dosyalar bulunamadı:\n  "
                     + "\n  ".join(eksik))

# ────────────────────────────────────────────── platform bağımlılıkları ──
# Pencere motorunun paketleri: yalnız .py dosyaları değil, veri ve ikili
# dosyaları da gerekiyor. collect_all üçünü birden toplar.
ekstra_veri, ekstra_ikili, ekstra_gizli = [], [], []


def topla(paket: str, zorunlu: bool = False) -> None:
    try:
        v, ikili, gizli = collect_all(paket)
    except Exception as exc:                       # paket kurulu değil
        if zorunlu:
            raise SystemExit(f"[spec] '{paket}' gerekli ama toplanamadı: {exc}")
        print(f"[spec] atlandı (kurulu değil): {paket}")
        return
    ekstra_veri.extend(v)
    ekstra_ikili.extend(ikili)
    ekstra_gizli.extend(gizli)


topla("webview", zorunlu=True)
if sys.platform == "darwin":
    for p in ("objc", "Foundation", "AppKit", "WebKit", "Quartz", "Security"):
        topla(p)
elif sys.platform == "win32":
    topla("clr_loader")
    topla("pythonnet")
    ekstra_gizli += ["webview.platforms.winforms",
                     "webview.platforms.edgechromium"]
else:
    for p in ("PyQt6", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineCore"):
        topla(p)
    ekstra_gizli += ["webview.platforms.qt"]

# Çalışma anında içe aktarılan ama koddan görünmeyen paketler. openpyxl
# Excel çıktısı, paho MQTT telemetrisi için; ikisi de yalnız kullanıldığı
# anda import ediliyor, PyInstaller bu yüzden kendiliğinden bulmuyor.
for p in ("openpyxl", "paho"):
    topla(p)

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
    datas=veri + ekstra_veri,
    hiddenimports=["panel_api"] + ekstra_gizli,
    hookspath=[],
    runtime_hooks=[],
    # tests/ pakete girmez: sahaya giden uygulamada test altyapısı ve
    # sahte cihaz sunucuları bulunmaz.
    excludes=["tkinter", "test", "pydoc_data", "tests"],
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
        bundle_identifier="com.piton.devreyealmapaneli",
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
            # Panel tren setindeki cihazları yerel ağda okuyor; macOS 14+ bu
            # izni kullanıcıya sorar ve açıklamayı buradan okur.
            "NSLocalNetworkUsageDescription":
                "Uygulama, tren setindeki cihazları (switch, intercom, kamera, "
                "PISCU) doğrulamak için yerel ağ erişimini kullanır.",
            # Arayüz 127.0.0.1 üzerinden servis ediliyor; cihazlara da düz
            # HTTP ile bağlanılıyor (cihazlar HTTPS sunmuyor).
            "NSAppTransportSecurity": {
                "NSAllowsLocalNetworking": True,
                "NSAllowsArbitraryLoads": True,
            },
        },
    )
