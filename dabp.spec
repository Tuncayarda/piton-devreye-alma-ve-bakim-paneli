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
  • The panel reads its data files and two field scripts at runtime.
    They are copied to the ROOT of the bundle; panel.settings.data_file()
    looks there when frozen (see panel/settings.py).
  • The window engine's data files (PyObjC / PyQt / pythonnet) are gathered
    with collect_all — otherwise the package unpacks but no window opens.
"""
import hashlib
import importlib.util
import os
import re
import sys
import tempfile
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
#
# BOTH ARE NOW PER EDITION. One program is packaged once per customer, and
# each package carries only that customer's project (see panel/editions).
# Two editions may sit on the same machine, so every file name has to tell
# them apart — "dabp-gdm.exe", "dabp-gaziray.app" — and each needs its own
# Windows AppId so an update lands on itself and never on the other.


def load_editions():
    """The edition table, loaded WITHOUT importing the application.

    This spec deliberately does not import `panel`: that would need
    `requests`, which a build environment need not have (the same reason
    APP_VERSION is read with a regex below). `panel/editions/catalogue.py`
    is written to stand alone for exactly this call.
    """
    path = ROOT / "panel" / "editions" / "catalogue.py"
    spec = importlib.util.spec_from_file_location("dap_editions", path)
    module = importlib.util.module_from_spec(spec)
    # Registered before it is executed: `from __future__ import annotations`
    # makes every dataclass field annotation a string, and dataclasses
    # resolves those through sys.modules. Without this the load dies inside
    # @dataclass with an error that says nothing about what is wrong.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EDITIONS = load_editions()
EDITION_ID = os.environ.get("DAP_EDITION", "").strip().lower()
EDITION = EDITIONS.find(EDITION_ID)
if EDITION is None:
    raise SystemExit(
        "[spec] set DAP_EDITION to the package being built. "
        f"Editions: {', '.join(EDITIONS.IDS)}")

INTERNAL_NAME = EDITIONS.app_name(EDITION.id)
DISPLAY_NAME = EDITION.product_name
ONEFILE = os.environ.get("DAP_ONEFILE") == "1"
BUNDLE_IDENTIFIER = f"com.piton.dabp.{EDITION.id}"
print(f"[spec] edition: {EDITION.id} -> {INTERNAL_NAME}")


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
# The shared checklist template. It sits in `devicemaps/_base/` rather than
# with a project, because it belongs to no single one: every train not
# carrying its own workbook is filled from this file.
DATA_FILES = [
    (ROOT / "devicemaps" / "_base" / "Field_Device_Verification.xlsx",
     "Field_Device_Verification.xlsx"),
    (FIELD_SCRIPTS_DIR / "device_verify.py", "device_verify.py"),
    (FIELD_SCRIPTS_DIR / "intercom_ip_assign.py", "intercom_ip_assign.py"),
]

# ONLY THIS EDITION'S DEVICE LISTS. A customer's package must not carry
# another customer's inventory, addresses and SIP numbering — that is the
# whole reason the packages are separate, and leaving the other maps in
# would make the separation cosmetic.
#
# A project whose map has not been delivered yet is SKIPPED rather than
# fatal: VIP is declared before its DeviceMap exists, and refusing to build
# would hold up the package it is not part of. It is printed, so a
# misspelled file name shows up in the build log instead of quietly
# producing a package with nothing in it.
for project in EDITION.projects:
    source = ROOT.joinpath(*project.source_path)
    if source.exists():
        DATA_FILES.append((source, project.map_name))
        print(f"[spec] device list: {project.label} <- {project.map_name}")
    else:
        print(f"[spec] project not delivered yet, skipped: {project.label}")
    # A project whose devices are not in the shared checklist workbook
    # carries its own (see panel/editions/catalogue.py). Missing, the report
    # comes out with every row empty and nothing says why — so it is fatal
    # here rather than skipped: unlike a DeviceMap, this file is generated
    # from one (`tools/make_checklist_template.py`) and its absence is a
    # step forgotten, not a delivery still to come.
    if project.checklist_name:
        sheet = ROOT.joinpath(*project.checklist_source)
        if not sheet.exists():
            raise SystemExit(
                f"[spec] {project.label} carries its own checklist workbook "
                f"but {sheet} is not there.\n"
                f"        python3 tools/make_checklist_template.py "
                f"{project.key}")
        DATA_FILES.append((sheet, project.checklist_name))
        print(f"[spec] checklist: {project.label} <- "
              f"{project.checklist_name}")

# ── the OTHER customers' projects, sealed ───────────────────────────────
# They ship too, and they ship unreadable. The bytes are encrypted with K —
# the value written on the service key — while this package is built with
# sha256(K) and nothing else, so the package carrying them carries nothing
# that opens them (see panel/adminkey/vault.py). Admin mode with the stick in
# the machine decrypts them into a session directory; a customer running
# their own package cannot list them, and could not read them if they could.
#
# LOADED BARE, like the edition table above and for the same reason: this
# spec must not import `panel`. Both modules are written to stand alone —
# `vault` imports hashlib, hmac and os, and `derive` needs only hashlib.
#
# WITHOUT THE BUILD SECRET NOTHING IS SEALED and nothing is shipped, and that
# is not an error: a fork, or a local build with DAP_ALLOW_NO_ADMIN_KEY, has
# no K to seal with. Such a package behaves the way every package did before
# this existed — its own projects and no others.
def load_bare(relative, name):
    """A stdlib-only module of ours, loaded without importing `panel`."""
    path = ROOT.joinpath(*relative)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_secret():
    """S for this build: the environment, or the checkout's own file.

    The two places a SOURCE run looks (`panel.adminkey.secret`), and a build
    is a source run. The stamp is not consulted — this is what writes it.
    """
    raw = os.environ.get("DAP_ADMIN_KEY_SECRET", "").strip()
    if raw:
        return raw.encode("utf-8")
    path = ROOT / ".adminkey-secret"
    try:
        return (path.read_text(encoding="utf-8").strip() or "").encode(
            "utf-8") or None
    except OSError:
        return None


SEAL_KEY = None
try:
    _secret = load_bare(("panel", "adminkey", "secret.py"), "dap_key_secret")
    _vault = load_bare(("panel", "adminkey", "vault.py"), "dap_vault")
    _S = build_secret()
    SEAL_KEY = _secret.derive(_S) if _S else None
except Exception as error:
    print(f"[spec] sealing unavailable: {error}")

if SEAL_KEY:
    SEAL_DIR = Path(tempfile.mkdtemp(prefix="dabp-sealed-"))
    MINE = {p.key for p in EDITION.projects}

    def seal_into(source, name):
        """Seal one file and add it to the bundle as `<name>.sealed`."""
        target = SEAL_DIR / f"{name}.sealed"
        target.write_bytes(_vault.seal(SEAL_KEY, source.read_bytes()))
        DATA_FILES.append((target, target.name))

    for project in EDITIONS.ALL_PROJECTS:
        if project.key in MINE:
            continue
        source = ROOT.joinpath(*project.source_path)
        if not source.exists():
            print(f"[spec] sealed: {project.label} skipped, not delivered")
            continue
        seal_into(source, project.map_name)
        print(f"[spec] sealed device list: {project.label}")
        if project.checklist_name:
            sheet = ROOT.joinpath(*project.checklist_source)
            if sheet.exists():
                seal_into(sheet, project.checklist_name)
                print(f"[spec] sealed checklist: {project.label}")
else:
    print("[spec] no build secret: other projects are not shipped at all")

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

# The ADB tools. An Android display is reached with `adb` and nothing else,
# and a machine the panel is installed on has no reason to carry Android
# Studio: shipping the executable is the difference between a Compartment LCD
# that can be read on a fresh installation and one that reports "the adb
# command was not found". `panel/adb/binary.py` looks for it here first and
# falls back to PATH.
#
# FATAL WHEN ABSENT, and it used to be a printed note. That note was the
# whole safeguard, and it did not work: CI never fetched the tools, so every
# package it produced shipped without adb and the line went unread. The
# tools are still a third-party download (Google's platform-tools, with its
# own licence beside it) and the source tree still does not carry them —
# CI fetches them now, and a developer who means to build without says so
# with DAP_ALLOW_NO_ADB=1.
PLATFORM_TOOLS = ROOT / "platform-tools"
# The name for THIS build's target. Checked rather than assumed: the archive
# is downloaded per operating system, and unzipping the macOS one on a Windows
# runner leaves a folder that looks right and holds an executable Windows
# cannot run. `panel/adb/binary.py` then finds nothing and falls back to PATH
# — silently, which is the whole problem.
ADB_NAME = "adb.exe" if sys.platform == "win32" else "adb"
ADB_BINARY = PLATFORM_TOOLS / ADB_NAME

data = [("static", "static"), (str(MESSAGES_DIR), "messages")]
if ADB_BINARY.is_file():
    data.append((str(PLATFORM_TOOLS), "platform-tools"))
    print(f"[spec] adb tools: {PLATFORM_TOOLS}")
elif os.environ.get("DAP_ALLOW_NO_ADB") == "1":
    print("[spec] adb tools: NONE (DAP_ALLOW_NO_ADB=1) — an Android display "
          "can only be reached if this machine has adb on PATH")
else:
    # REQUIRED BY DEFAULT, and for the same reason the admin key is: a
    # package that is missing it still builds, still opens, and fails in the
    # field on hardware that is not at fault. A developer build that does not
    # care says so explicitly.
    detail = (f"{PLATFORM_TOOLS} holds no {ADB_NAME}"
              if PLATFORM_TOOLS.is_dir()
              else f"there is no {PLATFORM_TOOLS} folder")
    raise SystemExit(
        f"[spec] {detail}, so this package could not reach an Android "
        "display on a machine without adb installed.\n"
        "        Download the tools for THIS operating system and unzip them "
        "into the repository root:\n"
        "          https://developer.android.com/tools/releases/platform-tools\n"
        "        For a build that deliberately has none (a developer trial): "
        "DAP_ALLOW_NO_ADB=1")
missing = []
for source_path, bundle_name in DATA_FILES:
    if source_path.exists():
        data.append((str(source_path), "."))
    else:
        missing.append(str(source_path))
if missing:
    raise SystemExit("[spec] files to be packaged were not found:\n  "
                     + "\n  ".join(missing))

# ────────────────────────────────────────────────────── the build stamp ──
# What a packaged build knows about itself and cannot be told otherwise:
# which edition it is, and the key material for admin mode.
#
# A GENERATED MODULE, not a data file. It ends up inside the PYZ archive
# rather than sitting readable at the bundle root, which is a meaningfully
# higher bar than a JSON file anyone can open and edit. Nothing here is
# proof against someone rebuilding the package; it is the line between a
# customer using their own product and a customer wandering into another
# customer's.
#
# A CUSTOMER BUILD GETS THE DIGEST AND NEVER THE SECRET. See
# panel/adminkey/secret.py for why the two are not interchangeable: from the
# digest there is no route back to the value a USB stick has to carry, so a
# customer cannot mint a key out of the package they were given.
STAMP = ROOT / "panel" / "editions" / "_stamp.py"
ADMIN_SECRET = os.environ.get("DAP_ADMIN_KEY_SECRET", "").strip()

# Digests to honour BESIDES the one derived from the secret. Two situations
# need this, and both of them arrive without warning:
#
#   ROTATION. Replacing the secret invalidates every stick in the field at
#   once, which cannot be done in an afternoon. Building the new packages
#   with the OLD digest alongside the new secret lets both work until the
#   last laptop is updated.
#
#   A LOST SECRET. The secret cannot be read back out of a CI secret store,
#   and it is the one value nothing else can reproduce. But the digest CAN
#   be recovered — from any surviving stick, which carries the value the
#   digest is of (see docs/BUILD_RELEASE.md). A build made that way still
#   recognises every key already issued; only MINTING new ones is lost,
#   and a stick can be copied.
EXTRA_DIGESTS = [value.strip().lower() for value
                 in os.environ.get("DAP_ADMIN_KEY_DIGESTS", "").split(",")
                 if value.strip()]
for value in EXTRA_DIGESTS:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SystemExit(
            f"[spec] DAP_ADMIN_KEY_DIGESTS holds {value!r}, which is not a "
            "sha256 digest (64 hex characters).")

if (not ADMIN_SECRET and not EXTRA_DIGESTS
        and os.environ.get("DAP_ALLOW_NO_ADMIN_KEY") != "1"):
    raise SystemExit(
        "[spec] neither DAP_ADMIN_KEY_SECRET nor DAP_ADMIN_KEY_DIGESTS is "
        "set, so this package could never open admin mode.\n"
        "        For a build that deliberately has no key (a fork, or a "
        "local trial): DAP_ALLOW_NO_ADMIN_KEY=1")

# A GUESSABLE SECRET IS THE ONE FAILURE NOBODY WOULD NOTICE. The customer's
# package is built with a digest of it, and a digest is something to guess
# AGAINST: every attempt costs 600_000 PBKDF2 rounds, which slows a search
# down but does not stop one over a short or memorable value. The secret is
# never typed by anybody — it lives in a CI secret and a password manager —
# so there is no reason for it to be short, and a length floor is the one
# check that can be made here.
#
#     python3 -c "import secrets; print(secrets.token_urlsafe(32))"
MINIMUM_SECRET = 24
if ADMIN_SECRET and len(ADMIN_SECRET) < MINIMUM_SECRET:
    raise SystemExit(
        f"[spec] DAP_ADMIN_KEY_SECRET is {len(ADMIN_SECRET)} characters; at "
        f"least {MINIMUM_SECRET} are required.\n"
        "        It is never typed by a person, so make it random rather "
        "than memorable:\n"
        "          python3 -c \"import secrets; "
        "print(secrets.token_urlsafe(32))\"")


def key_lines() -> str:
    digests = list(EXTRA_DIGESTS)
    if ADMIN_SECRET:
        proof = hashlib.pbkdf2_hmac(
            "sha256", ADMIN_SECRET.encode("utf-8"), b"dabp-admin-key-v1",
            600_000, dklen=32)
        digests.insert(0, hashlib.sha256(proof).hexdigest())
    # De-duplicated in order: rebuilding with the same secret listed again
    # as a digest should not double the work at verify time.
    digests = list(dict.fromkeys(digests))

    if not digests:
        print("[spec] admin key: NONE (admin mode cannot be opened)")
        return "ADMIN_KEY_DIGESTS = ()\nADMIN_KEY_SECRET = None\n"

    # COUNTS, NEVER VALUES. A build log is not a private place, and the
    # digest is the thing an attacker would search against.
    extra = f" (+{len(digests) - 1} accepted)" if len(digests) > 1 else ""
    # THE DIGEST, NEVER THE SECRET, for every package without exception.
    # The secret is used here to DERIVE the digest and is then dropped; it
    # stays with whoever cuts the build. A package that carried it could
    # mint service keys for every other customer's package, which is the one
    # outcome this whole arrangement exists to prevent — and there is no
    # longer any package that needs to (see panel/editions/catalogue.py).
    print(f"[spec] admin key: digest only{extra} (edition {EDITION.id})")
    return (f"ADMIN_KEY_DIGESTS = {tuple(digests)!r}\n"
            "ADMIN_KEY_SECRET = None\n")


STAMP.write_text(
    '"""Generated by dabp.spec at build time. Not in version control.\n\n'
    "Present only in a packaged build, and read only when frozen — a copy\n"
    "left behind in a developer's tree after a local build must not change\n"
    'what a source run does (see panel/editions/runtime.py).\n"""\n'
    f"EDITION = {EDITION.id!r}\n"
    f"VERSION = {VERSION!r}\n"
    + key_lines(), encoding="utf-8")
print(f"[spec] stamp written: {STAMP.relative_to(ROOT)}")

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
    hiddenimports=["panel.api", "panel.desktop",
                   # Imported behind a try/except (it is absent
                   # from source trees), so static analysis
                   # cannot find it on its own.
                   "panel.editions._stamp"] + extra_hidden_imports,
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
            # The service key is a USB stick, and macOS gates removable
            # volumes behind a permission of their own: without this
            # sentence the system has nothing to show in the prompt, and a
            # denied read looks from inside the panel exactly like an empty
            # slot (see panel/adminkey/keyfile.py).
            "NSRemovableVolumesUsageDescription":
                "The application reads the service key from a USB drive to "
                "open its admin mode.",
            # The UI uses the socketless pywebview bridge. This exception is
            # for the plain-HTTP local endpoints of the train devices.
            "NSAppTransportSecurity": {
                "NSAllowsLocalNetworking": True,
                "NSAllowsArbitraryLoads": True,
            },
        },
    )
