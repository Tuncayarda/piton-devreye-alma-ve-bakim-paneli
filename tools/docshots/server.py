#!/usr/bin/env python3
"""The panel, running against demo readings, so the guides can be illustrated.

This is DOCUMENTATION scaffolding, not part of the application — the same
standing as `tests/support/fakes.py`, and it borrows that module's fakes
rather than growing its own. The panel never creates or shows a demo reading;
nothing here is imported by `panel` or by `app.py`.

It runs the documented no-window mode (`panel.api.http_adapter`, the same
server `python3 -m panel.api` opens) with three substitutions:

  * `panel.probe.reader.read_device` — the single entry point every caller
    uses (the scan job, the light refresh, a credential check). Replacing it
    is enough to give every screen plausible content, and it is replaced with
    a DETERMINISTIC function: the same device always reads the same way, so a
    figure recaptured next month is the same figure.
  * a fake KYLAND switch from `tests/support/fakes.py`, on loopback, so the
    Switch screen has a real device to talk to (admin / 123).
  * `tests/support/adb.FakeAdb` in place of the adb binary, so the ADB screen
    has displays to list.

The environment is pinned the way the test suite pins it (tests/__init__.py):
the operator's real settings are not written, no IP alias is put on this
machine's interface, and the build secret opens admin mode so the engineer
screens can be captured too.

Run:
    python3 tools/docshots/server.py [edition] [port]

Then capture with tools/docshots/capture.py. Ctrl-C to stop.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

EDITION = sys.argv[1] if len(sys.argv) > 1 else "vip-yatakli"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8845

# Set before `panel` is imported: several of these are read once, at import
# (panel/network/aliases.py reads PANEL_NETWORK_WRITES exactly once), which
# is the ordering hole tests/__init__.py documents.
os.environ["PANEL_DATA_DIR"] = tempfile.mkdtemp(prefix="dabp-docshots-data-")
os.environ["DAP_ADMIN_KEY_STORE"] = tempfile.mkdtemp(
    prefix="dabp-docshots-key-")
os.environ["PANEL_NETWORK_WRITES"] = "0"
os.environ["DAP_EDITION"] = EDITION
os.environ.setdefault("DAP_ADMIN_KEY_SECRET", "a-build-secret-for-the-docs")

from panel import editions, i18n, settings  # noqa: E402

editions.activate(editions.resolve(EDITION))
# The guides are Turkish; so are the figures in them.
i18n.use("tr", persist=False)

from panel import status  # noqa: E402
from panel.errors import AuthError, UnreachableError  # noqa: E402
from panel.probe import reader, result as probe_result  # noqa: E402

# ─────────────────────────────────────────────────────── demo readings ────

# The mix a set in commissioning actually shows: most of the equipment
# answers, a few units still want their credentials, one or two cannot be
# reached and are what the operator is there to look at.
#
# A THRESHOLD ON THE HASH, not a modulus. `read_device` is handed one device
# and never sees the set, so the proportion has to hold per device — and a
# modulus does not: `hash % 13 == 3` over a 42-device map produced no
# unreachable device at all, and the figure then showed a state the guide
# spends a section explaining as an empty column.
SPREAD = 1 << 16
FAILED_BELOW = int(SPREAD * 0.07)    # ~7% cannot be reached
AUTH_BELOW = int(SPREAD * 0.17)      # ~10% want a username/password


def _number(device) -> int:
    digest = hashlib.md5(device.id.encode("utf-8")).digest()
    return digest[0] << 8 | digest[1]


def _bucket(device) -> str:
    number = _number(device)
    if number < FAILED_BELOW:
        return status.FAILED
    if number < AUTH_BELOW:
        return status.AUTH
    return status.OK


def _serial(device, prefix: str) -> str:
    return prefix + hashlib.md5(
        device.id.encode("utf-8")).hexdigest()[:10].upper()


def _uptime(device) -> str:
    return probe_result.uptime_text(3600 * 6 + _number(device) % (3600 * 40))


def _fields(device, method: str) -> dict:
    """Plausible values, in the shape `reader` really returns per method."""
    if method == "kyland":
        return {"version": "F6014", "model": "SICOM3028GPT",
                "mac": "00:11:22:33:44:55", "deviceName": device.name,
                "uptime": _uptime(device)}
    if method == "isapi":
        return {"version": "V5.7.15 build 230425",
                "serial": _serial(device, "DS-2CD"),
                "model": ("DS-7616NI-K2" if device.type == "NVR"
                          else "DS-2CD2T47G2-L"),
                "networkTime": "10.1.1.10"}
    if method == "http":
        return {"version": "1.2.6", "serial": _serial(device, "AN"),
                "uptime": _uptime(device), "sipPbx": "10.1.1.10",
                "sipExtension": device.pbx_extension or "",
                "sipOutbound": "10.1.1.10", "speakerVolume": "80",
                "micVolume": "60", "speakerGain": "4", "micGain": "2"}
    if method == "adb":
        return {"version": "1.4.2", "serial": _serial(device, "LCD"),
                "timezone": "Europe/Istanbul", "uptime": _uptime(device),
                "sipPbx": "10.1.1.10",
                "sipExtension": device.pbx_extension or "",
                "sipPbxSource": i18n.t("probe.deviceLog"),
                "sipExtensionSource": i18n.t("probe.deviceLog"),
                "sipRegistration": "registered (200)",
                "package": settings.ADB_PACKAGE, "versionCode": "142",
                "targetSdk": "31", "updatedAt": "2026-08-14"}
    return {"version": "2.0.1", "serial": _serial(device, "PS"),
            "uptime": _uptime(device), "note": ""}


def demo_read(device, credentials=None, telemetry=None, timeout=None,
              expected_ntp=None, pbx_ip=None, project_span=""):
    method = device.read_method
    if not method:
        return probe_result.not_applicable(method,
                                           i18n.t("error.noReadMethod"))
    state = _bucket(device)
    if state == status.OK:
        return probe_result.success(_fields(device, method), method)
    # The panel's own wording for the two failures, reached the way a real
    # failure reaches it — not a sentence written here.
    failure = (AuthError(i18n.t("error.probeAuth")) if state == status.AUTH
               else UnreachableError(i18n.t("error.noConnection")))
    return probe_result.from_error(failure, method)


reader.read_device = demo_read

# ─────────────────────────────────────────────────── a switch to talk to ────

sys.path.insert(0, str(ROOT / "tests"))
from support import fakes  # noqa: E402
from support.adb import FakeAdb  # noqa: E402

# 24 PoE + 4 uplink, which is the real SICOM3028GPT's faceplate.
FAKE_SWITCH = fakes.kyland(username="admin", password="123", uplinks=4,
                           mac_table={f"00:11:22:33:44:{n:02x}": n
                                      for n in range(1, 25)})
from panel import credentials, switch as switch_pkg  # noqa: E402

switch_pkg.CLIENT.port = FAKE_SWITCH.port

# EVERY switch address answers, not just the one on loopback. The IP
# assignment screen reads the MAC table of the switches in the DeviceMap
# (10.1.1.100, 10.1.1.101 …), and without this it draws its "no switch's MAC
# table could be read" banner over the figure. The rewrite is on the pooled
# session, which is the one place every switch request goes through.
_session = switch_pkg.CLIENT._session
_send = _session.request


def _to_loopback(method, url, *args, **rest):
    return _send(method, re.sub(r"//[^/:]+:", "//127.0.0.1:", str(url)),
                 *args, **rest)


_session.request = _to_loopback

# And the account for them, so no screen opens with a login box across it.
credentials.remember("switch", "*", "admin", "123", group="switch",
                     share_with_group=True)

# THIS COMPUTER, as the figures should show it — and NOT as it is.
#
# Two reasons. The network screen prints the machine's own addresses, and the
# IP screen protects the port the machine is plugged into by looking its MAC
# up in the switch's table. Left alone, the first puts whichever laptop took
# the screenshots into a document that goes to customers, and the second
# finds nothing on a bench and lays a red "the computer's port could not be
# found" band across the figure.
#
# One seam covers both: `interfaces.dump()` is where every adapter answer in
# the panel comes from. A canned ifconfig block replaces the machine, and the
# MAC in it is one of the ones the fake switch has learned (port 2), so the
# IP screen shows the protected port the guide describes.
DEMO_DUMP = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 00:11:22:33:44:02
\tinet 10.1.1.9 netmask 0xffffff00 broadcast 10.1.1.255
\tmedia: autoselect (1000baseT <full-duplex>)
\tstatus: active
"""
from panel.system import interfaces as system_interfaces  # noqa: E402

system_interfaces.dump = lambda: DEMO_DUMP
system_interfaces.local_address_for = lambda target_ip="": "10.1.1.9"

# ──────────────────────────────────────────────────── displays for ADB ────

FAKE_ADB = FakeAdb({
    "10.1.1.41": {"packages": [settings.ADB_PACKAGE, "com.android.settings"]},
    "10.1.1.42": {"packages": [settings.ADB_PACKAGE, "com.android.settings"]},
    "10.1.1.43": {"packages": [settings.ADB_PACKAGE, "com.android.settings"]},
    "10.1.1.44": {"packages": [settings.ADB_PACKAGE]},
})
from panel.adb import client as adb_client  # noqa: E402

# ONLY THIS MODULE'S VIEW of subprocess is replaced. Setting `.run` on the
# real module object redirects every subprocess call in the process —
# `ifconfig -a` included, which broke the scan the first time this was tried.
_shim = types.SimpleNamespace(**{name: getattr(__import__("subprocess"), name)
                                 for name in dir(__import__("subprocess"))
                                 if not name.startswith("__")})
_shim.run = lambda *args, **rest: FAKE_ADB(*args, **rest)
adb_client.subprocess = _shim

# The ADB screen's address list is server-side and expected to survive a
# restart (panel/adb/pool.py). Seeded so the screen has a bench to show.
from panel.adb import pool as adb_pool  # noqa: E402

adb_pool.replace_all([
    {"ip": "10.1.1.41", "label": "Kompartıman 1 · LCD"},
    {"ip": "10.1.1.42", "label": "Kompartıman 2 · LCD"},
    {"ip": "10.1.1.43", "label": "Kompartıman 3 · LCD"},
    {"ip": "10.1.1.44", "label": "Koridor · LCD"},
])

# ─────────────────────────────────────────────────────────────── serve ────

from panel.api import http_adapter  # noqa: E402


def main() -> int:
    try:
        server = http_adapter.serve("127.0.0.1", PORT)
    except OSError as error:
        # The everyday one is a docshots server left running in another
        # terminal — and a stack trace out of socketserver says nothing about
        # which of the two answers to do about it.
        print(f"port {PORT} will not open: {error}\n"
              f"another docshots server still running? stop it, or take a "
              f"different port:\n"
              f"    python3 tools/docshots/server.py {EDITION} {PORT + 1}\n"
              f"    python3 tools/docshots/capture.py "
              f"http://127.0.0.1:{PORT + 1}/")
        FAKE_SWITCH.close()
        return 2
    print(f"fake KYLAND on 127.0.0.1:{FAKE_SWITCH.port}  (admin / 123)")
    print(f"panel:      http://127.0.0.1:{PORT}   ({EDITION}, admin mode)")
    print(f"DeviceMap:  {settings.DEVICE_MAP}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.shutdown()
        server.server_close()
        FAKE_SWITCH.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
