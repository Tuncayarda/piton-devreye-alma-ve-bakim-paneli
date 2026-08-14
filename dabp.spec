# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration — Commissioning and Maintenance Panel.

    pip install -r docs/requirements-build.txt
    pyinstaller dabp.spec               # folder (onedir)
    DAP_ONEFILE=1 pyinstaller dabp.spec           # single file (portable)

On Windows, for onefile:  set DAP_ONEFILE=1 && pyinstaller ...

Output:
    dist/dabp/                                  onedir
    dist/dabp(.exe)                             onefile
    dist/dabp.app                               macOS (onedir only)

Notes:
  • The version comes from one place: APP_VERSION in panel/settings.py.
  • The panel reads three data files and three field scripts at runtime.
    They are copied to the ROOT of the bundle; panel.settings.data_file()
    looks there when frozen (see panel/settings.py).
  • The window engine's data files (PyObjC / PyQt / pythonnet) are gathered
    with collect_all — otherwise the package unpacks but no window opens.
"""
import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# ────────────────────────────────────────────────────── build environment ──
# Distribution builds are made with 3.12 (see docs/BUILD_RELEASE.md). To try
# another version, set DAP_ALLOW_ANY_PYTHON=1.
TARGET_PYTHON = (3, 12)
if (sys.version_info[:2] != TARGET_PYTHON
        and os.environ.get("DAP_ALLOW_ANY_PYTHON") != "1"):
    raise SystemExit(
        f"[spec] the build must use Python "
        f"{TARGET_PYTHON[0]}.{TARGET_PYTHON[1]}, running version is "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n"
        f"        If another version is intentional: "
        f"DAP_ALLOW_ANY_PYTHON=1 pyinstaller dabp.spec")

ROOT = Path(SPECPATH)
# Two names, on purpose. INTERNAL_NAME names FILES — the exe, the dist
# folder, the .app bundle, every release asset — so it is short and ASCII and
# survives every shell, ZIP and installer it passes through. DISPLAY_NAME is
# read by people (the Dock, the Windows file properties) and may be worded
# freely; it is never part of a path.
#
# DISPLAY_NAME is stamped into the package at BUILD time, so unlike every
# other visible name it cannot follow the language the user picks (that one
# is "app.name" in panel/messages/*.json). It is written in the language of
# the operators who commission the trains.
INTERNAL_NAME = "dabp"
DISPLAY_NAME = "Devreye Alma ve Bakım Paneli"
ONEFILE = os.environ.get("DAP_ONEFILE") == "1"
BUNDLE_IDENTIFIER = "com.piton.dabp"


def read_version() -> str:
    """Reads the version from panel/settings.py — the single source.

    The module is not imported: that would need `requests`, which may not be
    installed in the build environment. Reading one constant as plain text
    is enough.
    """
    source_text = (ROOT / "panel" / "settings.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']',
                      source_text, re.M)
    if not match:
        raise SystemExit("[spec] APP_VERSION not found in panel/settings.py")
    return match.group(1)


VERSION = read_version()
# The Windows version resource accepts numbers only; pre-release suffixes
# such as "0.9.0-dev" are dropped (the visible version text stays VERSION).
_VERSION_NUMBERS = re.findall(r"\d+", VERSION.split("-")[0].split("+")[0])
VERSION_QUAD = tuple(int(x) for x in (_VERSION_NUMBERS + ["0"] * 4)[:4])

# ───────────────────────────────────────── data files shipped with the app ──
# (path in the source tree, name inside the bundle). Placed at the bundle
# root; a missing one stops the build — quietly producing a half package
# means an app that will not open in the field with "DeviceMap not found".
FIELD_SCRIPTS_DIR = ROOT / "field_scripts"   # engines loaded at runtime
DATA_FILES = [
    (ROOT / "DeviceMap.json", "DeviceMap.json"),
    (ROOT / "Field_Device_Verification.xlsx",
     "Field_Device_Verification.xlsx"),
    (FIELD_SCRIPTS_DIR / "switch_api.py", "switch_api.py"),
    (FIELD_SCRIPTS_DIR / "device_verify.py", "device_verify.py"),
    (FIELD_SCRIPTS_DIR / "intercom_ip_assign.py", "intercom_ip_assign.py"),
]

# The message catalogue: EVERY visible string in the panel, in both
# languages. It is data sitting next to a Python package, and PyInstaller
# collects packages by their .py files only — left out, the app opens with
# every label showing its raw key. panel.i18n looks for it at "messages"
# in the bundle (panel/settings.py:data_file).
MESSAGES_DIR = ROOT / "panel" / "messages"
catalogues = sorted(path.name for path in MESSAGES_DIR.glob("*.json"))
if not catalogues:
    raise SystemExit(f"[spec] no message catalogue under {MESSAGES_DIR}")
print(f"[spec] message catalogues: {', '.join(catalogues)}")

data = [("static", "static"), (str(MESSAGES_DIR), "messages")]
missing = []
for source_path, bundle_name in DATA_FILES:
    if source_path.exists():
        data.append((str(source_path), "."))
    else:
        missing.append(str(source_path))
if missing:
    raise SystemExit("[spec] files to be packaged were not found:\n  "
                     + "\n  ".join(missing))

# ──────────────────────────────────────────────── platform dependencies ──
# Packages of the window engine: not only .py files, but data and binary
# files too. collect_all gathers all three at once.
extra_data, extra_binaries, extra_hidden_imports = [], [], []


def collect_package(package: str, required: bool = False) -> None:
    try:
        collected_data, binaries, hidden = collect_all(package)
    except Exception as exc:                       # package is not installed
        if required:
            raise SystemExit(
                f"[spec] '{package}' is required but could not be "
                f"collected: {exc}")
        print(f"[spec] skipped (not installed): {package}")
        return
    extra_data.extend(collected_data)
    extra_binaries.extend(binaries)
    extra_hidden_imports.extend(hidden)


collect_package("webview", required=True)
if sys.platform == "darwin":
    for package_name in ("objc", "Foundation", "AppKit", "WebKit", "Quartz",
                         "Security"):
        collect_package(package_name)
elif sys.platform == "win32":
    collect_package("clr_loader")
    collect_package("pythonnet")
    extra_hidden_imports += ["webview.platforms.winforms",
                             "webview.platforms.edgechromium"]
else:
    for package_name in ("PyQt6", "PyQt6.QtWebEngineWidgets",
                         "PyQt6.QtWebEngineCore"):
        collect_package(package_name)
    extra_hidden_imports += ["webview.platforms.qt"]

# Packages imported at runtime but invisible to static analysis. openpyxl is
# for the Excel output, paho for MQTT telemetry; both are imported only at
# the moment they are used, so PyInstaller does not find them on its own.
for package_name in ("openpyxl", "paho"):
    collect_package(package_name)

# ─────────────────────────────────────────────────────────────────── icons ──
ICNS = ROOT / "icons" / "app.icns"
ICO = ROOT / "icons" / "app.ico"
exe_icon = str(ICO) if (sys.platform == "win32" and ICO.exists()) else None
if sys.platform == "darwin" and ICNS.exists():
    exe_icon = str(ICNS)

# ─────────────────────────────────────────── Windows version resource (exe) ──
version_file = None
if sys.platform == "win32":
    version_file = ROOT / "build" / "version_info.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(f"""\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={VERSION_QUAD}, prodvers={VERSION_QUAD},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041f04b0', [
      StringStruct('CompanyName', 'Piton Technology'),
      StringStruct('FileDescription', '{DISPLAY_NAME}'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', '{INTERNAL_NAME}'),
      StringStruct('OriginalFilename', '{INTERNAL_NAME}.exe'),
      StringStruct('ProductName', '{DISPLAY_NAME}'),
      StringStruct('ProductVersion', '{VERSION}'),
      StringStruct('LegalCopyright', 'Piton Technology')])]),
    VarFileInfo([VarStruct('Translation', [1055, 1200])])
  ]
)
""", encoding="utf-8")   # 1055 = tr-TR, 1200 = Unicode

# ────────────────────────────────────────────────────────────── analysis ──
analysis = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=extra_binaries,
    datas=data + extra_data,
    hiddenimports=["panel.api", "panel.desktop"] + extra_hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    # tests/ stays out of the package: the application shipped to the field
    # carries no test scaffolding and no fake device servers.
    excludes=["tkinter", "test", "pydoc_data", "tests"],
    noarchive=False,
)
pyz = PYZ(analysis.pure, analysis.zipped_data)

COMMON = dict(
    name=INTERNAL_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,                 # Windows: do not open a console window
    # On Windows an administrator request is embedded in the application
    # manifest: on a double click the UAC prompt appears FIRST and the panel
    # opens elevated straight away. The panel clears the ARP cache and writes
    # IP addresses to devices; with ordinary user rights those silently did
    # half their job. That is not the only safeguard: on every unelevated
    # start path (running from a script, an old shortcut) app.py shows the
    # user a window offering to elevate (see panel/elevation/). Ignored off
    # Windows.
    uac_admin=True,
    disable_windowed_traceback=False,
    icon=exe_icon,
    version=str(version_file) if version_file else None,
)

if ONEFILE:
    # Single file: portable, but it unpacks itself into a temporary folder on
    # every launch, so startup takes a few seconds longer.
    exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.zipfiles,
              analysis.datas, [], exclude_binaries=False, **COMMON)
    final = exe
else:
    exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, **COMMON)
    final = COLLECT(exe, analysis.binaries, analysis.zipfiles, analysis.datas,
                    strip=False, upx=False, name=INTERNAL_NAME)

# The .app bundle on macOS: so the name and icon look right in the Dock.
if sys.platform == "darwin" and not ONEFILE:
    app = BUNDLE(
        final,
        name=f"{INTERNAL_NAME}.app",
        icon=str(ICNS) if ICNS.exists() else None,
        bundle_identifier=BUNDLE_IDENTIFIER,
        version=VERSION,
        info_plist={
            "CFBundleName": DISPLAY_NAME,
            "CFBundleDisplayName": DISPLAY_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            # 11.0 (Big Sur): setup-python's arm64 builds and PyObjC 10 do
            # not support anything below it. Writing an older value would be
            # an unverified promise.
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "Piton Technology",
            # The panel reads the devices of a train set on the local
            # network; macOS 14+ asks the user for this permission and shows
            # this description.
            "NSLocalNetworkUsageDescription":
                "The application uses local network access to verify the "
                "devices of a train set (switch, intercom, camera, PISCU).",
            # The UI uses the socketless pywebview bridge. This exception is
            # for the plain-HTTP local endpoints of the train devices.
            "NSAppTransportSecurity": {
                "NSAllowsLocalNetworking": True,
                "NSAllowsArbitraryLoads": True,
            },
        },
    )
