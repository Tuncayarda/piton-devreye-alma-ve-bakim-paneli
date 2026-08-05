#!/usr/bin/env python3
"""Testler için sahte cihazlar.

Bunlar TEST altyapısıdır, uygulamanın bir parçası değildir: panel hiçbir
koşulda sahte cihaz üretmez, göstermez ya da bunlara bağlanmaz.

Gerçek cihazların davranışını taklit ederler:
  · KYLAND switch — Basic Auth, /stat/basicInfo, JSON
  · "oturum sayfası" döndüren switch — HTTP 200 + HTML (başarı sayılmamalı)
  · Hikvision kamera — Digest Auth, /ISAPI/System/deviceInfo, XML
  · Announcement cihazı — kimliksiz JSON /api/v1/system/settings
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASIC_INFO = {
    "basicInfo": {
        "deviceName": "Yatakli_Test_SW",
        "deviceType": "SICOM3028GPT",
        "softVer": "F6014",
        "macAddress": "00:11:22:33:44:55",
        # Sahadaki KYLAND tek bir uptime alanı vermiyor; süre parçalı geliyor.
        "operateTime": {"day": "1", "hour": "2", "minute": "3", "second": "4"},
    }
}

PORT_MODE = {"portMode": [
    {"pid": i, "type": "GE", "adminStat": 1, "linkStat": "up" if i < 3 else "down"}
    for i in range(1, 25)
]}

GIRIS_HTML = (b"<!DOCTYPE html><html><head><title>Login</title></head>"
              b"<body><form>Kullanici<input name=user></form></body></html>")

DEVICE_INFO_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema">'
    b'<deviceName>Test Camera</deviceName>'
    b'<model>DS-2CD1023</model>'
    b'<serialNumber>SN-TEST-0001</serialNumber>'
    b'<firmwareVersion>V5.7.3</firmwareVersion>'
    b'</DeviceInfo>')

# Alan adları sahadaki cihazla birebir: /api/v1/system/settings
ANONS_AYAR = {
    "firmwareVersion": "1.2.5",
    "serialNumber": "ANON-0001",
    "uptime": 1234,
    "pbxIp": "10.9.1.1",
    "pbxExtension": "2001",
    "pbxOutExtension": "5001",
    "speakerVolume": 70,
    "microphoneVolume": 60,
    "speakerGain": 4,
    "micGain": 2,
}


class _Sunucu:
    """Arka planda çalışan tek kullanımlık HTTP sunucusu."""

    def __init__(self, handler_sinifi):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_sinifi)
        self.port = self.srv.server_address[1]
        self.istek_sayisi = 0
        handler_sinifi.sunucu = self
        self._t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self._t.start()

    def kapat(self):
        self.srv.shutdown()
        self.srv.server_close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.kapat()


def _temel_handler(ad: str, gonder):
    """İçinde yalnız `gonder(self)` çağıran bir Handler sınıfı üretir."""
    return type(ad, (BaseHTTPRequestHandler,), {
        "sunucu": None,
        "do_GET": lambda self: gonder(self),
        "do_POST": lambda self: gonder(self),
        "log_message": lambda self, *a: None,
        "yaz": _yaz,
    })


def _yaz(self, kod: int, govde: bytes, ctype: str, ek: dict | None = None):
    self.send_response(kod)
    self.send_header("Content-Type", ctype)
    self.send_header("Content-Length", str(len(govde)))
    for k, v in (ek or {}).items():
        self.send_header(k, v)
    self.end_headers()
    self.wfile.write(govde)


# ─────────────────────────────────────────────────────── KYLAND switch ────
def kyland(kullanici="admin", parola="123", giris_sayfasi=False):
    """Basic Auth isteyen KYLAND switch taklidi.

    `giris_sayfasi=True` ise DOĞRU kimlikle bile JSON yerine oturum açma
    HTML'ini 200 ile döndürür — panel bunu başarı saymamalıdır.
    """
    beklenen = "Basic " + base64.b64encode(
        f"{kullanici}:{parola}".encode()).decode()

    def gonder(self):
        self.sunucu.istek_sayisi += 1
        auth = self.headers.get("Authorization")
        if auth != beklenen:
            return self.yaz(401, b'{"error":"auth"}', "application/json",
                            {"WWW-Authenticate": 'Basic realm="switch"'})
        if giris_sayfasi:
            return self.yaz(200, GIRIS_HTML, "text/html")
        yol = self.path.split("?")[0]
        if yol == "/stat/basicInfo":
            return self.yaz(200, json.dumps(BASIC_INFO).encode(),
                            "application/json")
        if yol == "/stat/portMode":
            return self.yaz(200, json.dumps(PORT_MODE).encode(),
                            "application/json")
        return self.yaz(404, b'{"error":"yok"}', "application/json")

    return _Sunucu(_temel_handler("KylandHandler", gonder))


def bos_json_switch():
    """200 ve geçerli JSON döndüren ama switch künyesi OLMAYAN cihaz."""
    def gonder(self):
        self.sunucu.istek_sayisi += 1
        self.yaz(200, json.dumps({"hosgeldiniz": True}).encode(),
                 "application/json")

    return _Sunucu(_temel_handler("BosJsonHandler", gonder))


# ───────────────────────────────────────────────────────── ISAPI kamera ───
def kamera(kullanici="admin", parola="sahte-parola"):
    """Digest Auth isteyen Hikvision ISAPI taklidi."""
    realm, nonce = "IP Camera", "abc123nonce"

    def dogru_mu(auth: str, yontem: str) -> bool:
        if not auth or not auth.lower().startswith("digest "):
            return False
        alanlar = {}
        for parca in auth[7:].split(","):
            if "=" not in parca:
                continue
            k, _, v = parca.partition("=")
            alanlar[k.strip()] = v.strip().strip('"')
        if alanlar.get("username") != kullanici:
            return False
        ha1 = hashlib.md5(
            f"{kullanici}:{realm}:{parola}".encode()).hexdigest()
        ha2 = hashlib.md5(
            f"{yontem}:{alanlar.get('uri', '')}".encode()).hexdigest()
        if alanlar.get("qop"):
            beklenen = hashlib.md5(
                f"{ha1}:{alanlar.get('nonce')}:{alanlar.get('nc')}:"
                f"{alanlar.get('cnonce')}:{alanlar.get('qop')}:{ha2}"
                .encode()).hexdigest()
        else:
            beklenen = hashlib.md5(
                f"{ha1}:{alanlar.get('nonce')}:{ha2}".encode()).hexdigest()
        return alanlar.get("response") == beklenen

    def gonder(self):
        self.sunucu.istek_sayisi += 1
        if not dogru_mu(self.headers.get("Authorization", ""), self.command):
            return self.yaz(
                401, b"<html>401</html>", "text/html",
                {"WWW-Authenticate":
                 f'Digest realm="{realm}", nonce="{nonce}", qop="auth"'})
        yol = self.path.split("?")[0]
        if yol == "/ISAPI/System/deviceInfo":
            return self.yaz(200, DEVICE_INFO_XML, "application/xml")
        return self.yaz(404, b"<html>404</html>", "text/html")

    return _Sunucu(_temel_handler("KameraHandler", gonder))


# ──────────────────────────────────────────────────── Announcement cihaz ──
def anons(ayarlar=None):
    veri = json.dumps(ayarlar or ANONS_AYAR).encode()

    def gonder(self):
        self.sunucu.istek_sayisi += 1
        yol = self.path.split("?")[0]
        if yol == "/api/v1/system/settings":
            return self.yaz(200, veri, "application/json")
        return self.yaz(404, b'{"error":"yok"}', "application/json")

    return _Sunucu(_temel_handler("AnonsHandler", gonder))


def sessiz():
    """Bağlantıyı kabul edip hiç cevap vermeyen cihaz (zaman aşımı üretir)."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    port = s.getsockname()[1]
    dur = threading.Event()

    def dongu():
        tutulan = []
        s.settimeout(0.3)
        while not dur.is_set():
            try:
                baglanti, _ = s.accept()
                tutulan.append(baglanti)      # cevap verilmez, bilerek
            except OSError:
                continue
        for b in tutulan:
            try:
                b.close()
            except OSError:
                pass
        s.close()

    t = threading.Thread(target=dongu, daemon=True)
    t.start()

    class _Sessiz:
        def __init__(self):
            self.port = port

        def kapat(self):
            dur.set()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.kapat()

    return _Sessiz()


# ──────────────────────────────────────────────────────── DeviceMap üret ──
def device_map(cihazlar: list[dict], switch_ip="127.0.0.1",
               switch_ad="Test_SW_1", ikinci_switch: dict | None = None) -> dict:
    """Testler için DeviceMap.json içeriği üretir.

    IP'ler 127.0.0.1 olduğu için 'n' çözümlemesi devreye girmez; her
    cihazın portu sahte sunucunun portudur (bkz. testlerdeki port yamaları).
    """
    harita = {"Screens": None, "Switches": [{
        "Name": switch_ad, "IP": switch_ip, "IsActive": True,
        "Manufacturer": "KYLAND", "TrainSet": 1,
        "Username": "admin", "Password": "gizli-parola-devicemap",
        "Status": {"NoError": True, "Uptime": 10},
        "Devices": cihazlar,
    }]}
    if ikinci_switch:
        harita["Switches"].append(ikinci_switch)
    return harita
