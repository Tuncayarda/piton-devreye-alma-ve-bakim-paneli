#!/usr/bin/env python3
"""Switch Yönetim Paneli — KYLAND switch backend'i.

Tarayıcı doğrudan switch'e gitmez; bu servis araya girer:

    Web arayüzü  ->  bu backend  --Basic Auth-->  KYLAND switch HTTP API

Kimlik bilgisi yalnızca burada (.env) tutulur, frontend'e sızmaz. Her
switch için yazma kilidi vardır; PoE/port POST'ları her zaman güncel GET
üzerine kurulur, sıraya sokulur, paralel çalışmaz.

Çalıştırma:
    python3 switch_api.py                 # http://127.0.0.1:8770 (tarayıcı açılır)
    python3 switch_api.py --port 9000
    python3 switch_api.py --discover 10.1.1.0/24   # tarama aralığı
"""
from __future__ import annotations

import argparse
import sys
import concurrent.futures as cf
import json
import re
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from requests.auth import HTTPBasicAuth

HERE = Path(__file__).resolve().parent

# Uygulama sürümü — alt barda gösterilir. Tek kaynak burası.
APP_VERSION = "1.0.1"

# ------------------------------------------------------------------ ayar --
PREFIX_TO_MASK = {"8": "255.0.0.0", "16": "255.255.0.0", "24": "255.255.255.0"}
POE_MODE = {"0": "Kapalı", "1": "PoE", "2": "PoE+"}
POE_PRIORITY = {"0": "Low", "1": "High", "2": "Critical"}

# switch başına yazma kilidi (aynı switch'e eşzamanlı POST engellenir)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

# Aynı anda tek tarama. Üst üste tarama isteği gelirse ikincisi beklemez,
# hemen reddedilir: yığılan taramalar switch'in web sunucusunu boğuyor.
_SCAN_LOCK = threading.Lock()


def lock_for(ip: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(ip, threading.Lock())


def load_env(path: Path) -> dict:
    """.env'i okur. Aynı anahtar iki kez yazılmışsa son satır geçerli olur —
    bu sessizce yanlış ayarla çalışmaya yol açtığı için uyarı basar."""
    env = {}
    if not path.exists():
        return env
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k in env:
            print(f"[!] {path.name}:{no} — '{k}' birden fazla kez tanımlı, "
                  f"son değer geçerli: {v.strip()}")
        env[k] = v.strip().strip('"').strip("'")
    return env


def find_env() -> Path:
    """.env'i kendi klasöründe, bulamazsa üst klasörlerde arar.

    Uygulama dosyaları "Switch Yönetim Paneli.app" paketinin içinde duruyor;
    kimlik bilgileri paketin dışında (interface/.env) kalsın ki paket açmadan
    düzenlenebilsin.
    """
    for klasor in (HERE, *list(HERE.parents)[:4]):
        aday = klasor / ".env"
        if aday.exists():
            return aday
    return HERE / ".env"


ENV_PATH = find_env()
ENV = load_env(ENV_PATH)
SWITCH_USER = ENV.get("SWITCH_USERNAME", ENV.get("KYLAND_USERNAME", "admin"))
SWITCH_PASS = ENV.get("SWITCH_PASSWORD", ENV.get("KYLAND_PASSWORD", ""))
SWITCH_PORT = int(ENV.get("SWITCH_HTTP_PORT", ENV.get("KYLAND_HTTP_PORT", 80)))
# Her değişiklikten sonra configSave çağrılsın mı?
# Varsayılan KAPALI: kayıt yalnızca kullanıcı "Kaydet"e basınca yapılır.
# Böylece switch'in flash'ı her port dokunuşunda yazılmaz ve yapılan
# değişiklik beğenilmezse yeniden başlatmak eski haline döndürür.
AUTOSAVE = str(ENV.get("AUTOSAVE", "0")).lower() in ("1", "true", "evet")
# Ağ aralığı taramasında TCP ön yoklama süresi (tek IP'de kullanılmaz)
TCP_PROBE_TIMEOUT = float(ENV.get("TCP_PROBE_TIMEOUT", "1.2"))


# ----------------------------------------------------------- switch API ----
class SwitchError(Exception):
    pass


def _auth():
    return HTTPBasicAuth(SWITCH_USER, SWITCH_PASS)


def sw_get(ip: str, endpoint: str, timeout=5):
    r = requests.get(f"http://{ip}:{SWITCH_PORT}/{endpoint}",
                     auth=_auth(), timeout=timeout)
    r.raise_for_status()
    return r.json()


def sw_post(ip: str, endpoint: str, form: dict, timeout=8):
    r = requests.post(f"http://{ip}:{SWITCH_PORT}/{endpoint}",
                      auth=_auth(), data=form,
                      headers={"Content-Type":
                               "application/x-www-form-urlencoded; charset=UTF-8",
                               "X-Requested-With": "XMLHttpRequest"},
                      timeout=timeout)
    r.raise_for_status()
    return r.json()


def is_switch(ip: str, timeout=1.5) -> dict | None:
    """basicInfo dönerse switch'tir; özet bilgi döndürür."""
    try:
        data = sw_get(ip, "stat/basicInfo", timeout=timeout)
    except Exception:
        return None
    info = data.get("basicInfo", data) if isinstance(data, dict) else {}
    if not isinstance(info, dict):
        info = {}
    return {
        "ip": ip,
        "name": info.get("deviceName") or info.get("sysName") or "Switch",
        "model": info.get("deviceType") or info.get("model") or "",
        "version": info.get("softVer") or info.get("softwareVersion") or "",
        "mac": info.get("macAddress") or info.get("mac") or "",
    }


def tcp_open(ip: str, port: int, timeout=0.4) -> bool:
    try:
        with socket.create_connection((ip, port), timeout):
            return True
    except OSError:
        return False


def discover(cidr: str, workers=64) -> dict:
    """Ağı tarayıp switch'leri bulur.

    Tek IP verilirse ("10.1.1.101") doğrudan HTTP ile sorgulanır — TCP ön
    yoklaması yoktur, çünkü orada eleme yapmanın anlamı yok ve yavaş bir
    cihazı yanlışlıkla elemesin.

    Ağ aralığı verilirse önce hafif TCP yoklaması yapılır (254 eşzamanlı
    HTTP+auth isteği switch'in küçük web sunucusunu boğuyor), sonra yalnızca
    cevap veren adreslere basicInfo sorulur. TCP hiç sonuç vermezse yine de
    HTTP denenir; ön yoklama bir hız optimizasyonudur, kapı bekçisi değil.
    """
    cidr = (cidr or "").strip()
    tek = bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+", cidr))

    if tek:
        hosts = [cidr]
        adaylar = hosts                       # doğrudan HTTP
    else:
        m = (re.match(r"(\d+\.\d+\.\d+)\.\d+/\d+", cidr)
             or re.match(r"(\d+\.\d+\.\d+)\.?$", cidr))
        prefix = m.group(1) if m else cidr.rstrip(".")
        hosts = [f"{prefix}.{i}" for i in range(1, 255)]
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            adaylar = [h for h, ok in zip(hosts, pool.map(
                lambda h: tcp_open(h, SWITCH_PORT, TCP_PROBE_TIMEOUT),
                hosts)) if ok]
        if not adaylar:                       # ön yoklama boş -> yine de dene
            adaylar = hosts

    sure = 6.0 if tek else 4.0
    found = []
    with cf.ThreadPoolExecutor(max_workers=min(len(adaylar) or 1, 24)) as pool:
        for res in pool.map(lambda h: is_switch(h, timeout=sure), adaylar):
            if res:
                found.append(res)
    return {"switches": found, "probed": len(hosts), "queried": len(adaylar)}


# ------------------------------------------------------- iş mantığı --------
def get_info(ip: str) -> dict:
    info = is_switch(ip, timeout=4) or {}
    try:
        net = sw_get(ip, "stat/vlanIntfIp?intf=1")
        net = net.get("vlanIntfIp", net) if isinstance(net, dict) else {}
    except Exception:
        net = {}
    info["network"] = {
        "method": net.get("method", "manual"),
        "addr": net.get("addr", ip),
        "netmaskLen": str(net.get("netmaskLen", "")),
        "netmask": PREFIX_TO_MASK.get(str(net.get("netmaskLen", "")), ""),
        "mtu": str(net.get("mtu", "1500")),
    }
    return info


def get_ports(ip: str) -> list[dict]:
    """portMode + poePort + poeStatus tek listede birleştirilir."""
    pm = sw_get(ip, "stat/portMode").get("portMode", [])
    poe = {int(p["pid"]): p for p in sw_get(ip, "stat/poePort").get("poePort", [])}
    try:
        live = {int(p["pid"]): p
                for p in sw_get(ip, "stat/poeStatus").get("poeStatus", [])}
    except Exception:
        live = {}

    out = []
    for p in pm:
        pid = int(p["pid"])
        pp = poe.get(pid, {})
        ls = live.get(pid, {})
        power = ls.get("powerUsed")
        out.append({
            "pid": pid,
            "type": p.get("type", ""),
            "adminStat": bool(p.get("adminStat")),
            "linkStat": p.get("linkStat", ""),
            "linktext": p.get("linktext", ""),
            "speed": str(p.get("speed", "")),
            "autoNego": bool(p.get("autoNego")),
            "duplex": bool(p.get("duplex")),
            "flowCtrl": bool(p.get("flowCtrl")),
            "maxLength": str(p.get("maxLength", "")),
            "linkType": str(p.get("linkType", "")),
            "poe": pid in poe,
            "poeMode": str(pp.get("poeMode", "")),
            "poeModeText": POE_MODE.get(str(pp.get("poeMode", "")), ""),
            "priority": str(pp.get("priority", "0")),
            "priorityText": POE_PRIORITY.get(str(pp.get("priority", "0")), ""),
            "maxPower": str(pp.get("maxPower", "154")),
            "poeStatus": ls.get("portStatus", ""),
            "powerW": round(int(power) / 10, 1) if str(power).isdigit() else None,
        })
    return out


def config_save(ip: str) -> dict:
    """Çalışan yapılandırmayı kalıcı hale getirir.

    Bu çağrılmazsa PoE/port/IP değişiklikleri switch yeniden başlayınca
    kaybolur — RAM'de kalır, flash'a yazılmaz.
    """
    return sw_post(ip, "stat/configSave", {"postOperation": "configSave"},
                   timeout=15)


def _autosave(ip: str, sonuc: dict) -> dict:
    """Değişiklikten sonra kaydeder; kaydedilemezse sonuca not düşer.

    Otomatik kayıt kapalıyken sonuca "saved" alanı hiç konmaz — çünkü
    kaydedilmemiş olması hata değil, beklenen durum. Arayüz bunu
    "kaydedilmemiş değişiklik var" göstergesiyle takip eder.
    """
    if not AUTOSAVE:
        return sonuc
    try:
        config_save(ip)
        sonuc["saved"] = True
    except Exception as exc:
        sonuc["saved"] = False
        sonuc["saveError"] = f"{type(exc).__name__}: {exc}"
    return sonuc


def set_poe(ip: str, port: int, mode: str) -> dict:
    """Tek portun PoE modunu değiştirir (24 portun tamamını okuyup yazar)."""
    with lock_for(ip):
        ports = sw_get(ip, "stat/poePort").get("poePort", [])
        if not any(int(p["pid"]) == port for p in ports):
            raise SwitchError(f"port {port} PoE listesinde yok")
        form = {}
        for p in ports:
            pid = int(p["pid"])
            form[f"mode_{pid}"] = str(mode) if pid == port else str(p["poeMode"])
            form[f"priority_{pid}"] = str(p["priority"])
            form[f"maxPower_{pid}"] = str(p["maxPower"])
        return _autosave(ip, sw_post(ip, "stat/poePort", form))


def _portmode_form(ports: list, admin_over: dict) -> dict:
    """portMode POST gövdesini kurar; admin_over verilen portları ezer.

    Switch tüm portları tek istekte yazdığı için, değişmeyen portların
    mevcut değerleri de aynen geri gönderilmek zorunda.
    """
    form = {}
    for p in ports:
        pid = int(p["pid"])
        admin = admin_over.get(pid, bool(p.get("adminStat")))
        if admin:
            form[f"adminStat_{pid}"] = "1"
        form[f"linkType_{pid}"] = str(p.get("linkType", "0"))
        if p.get("autoNego"):
            form[f"autoNego_{pid}"] = "1"
        form[f"speed_{pid}"] = str(p.get("speed", ""))
        if p.get("duplex"):
            form[f"duplex_{pid}"] = "1"
        if p.get("flowCtrl"):
            form[f"flowCtrl_{pid}"] = "1"
        form[f"maxLength_{pid}"] = str(p.get("maxLength", "1522"))
    return form


def set_port_enabled(ip: str, port: int, enabled: bool,
                     protect_uplink=True) -> dict:
    """Tek portu açar/kapatır (tüm portları okuyup yazar).

    Uplink portu (link'i up olan ve istekte olmayan) yanlışlıkla kapatılırsa
    switch'e erişim kaybedilir; koruma varsayılan açık.
    """
    with lock_for(ip):
        ports = sw_get(ip, "stat/portMode").get("portMode", [])
        if not any(int(p["pid"]) == port for p in ports):
            raise SwitchError(f"port {port} yok")
        return _autosave(ip, sw_post(ip, "stat/portMode",
                                     _portmode_form(ports, {port: enabled})))


def apply_batch(ip: str, poe: dict, portlar: dict) -> dict:
    """Birden çok PoE/port değişikliğini tek yazımda uygular.

    Switch API'si zaten "hepsini oku, hepsini yaz" mantığında. Değişiklikleri
    tek tek göndermek yerine burada birleştiriyoruz: en fazla iki POST
    (poePort + portMode) ve sonda bir kez kayıt. 10 değişiklik için 10 kayıt
    turu yerine 1 tur — hem hızlı hem switch'i yormuyor.
    """
    sonuc = {"retCode": ["success"], "poe": [], "ports": []}
    with lock_for(ip):
        if poe:
            mevcut = sw_get(ip, "stat/poePort").get("poePort", [])
            bilinen = {int(p["pid"]) for p in mevcut}
            eksik = sorted(set(poe) - bilinen)
            if eksik:
                raise SwitchError(f"PoE listesinde olmayan port: {eksik}")
            form = {}
            for p in mevcut:
                pid = int(p["pid"])
                form[f"mode_{pid}"] = str(poe.get(pid, p["poeMode"]))
                form[f"priority_{pid}"] = str(p["priority"])
                form[f"maxPower_{pid}"] = str(p["maxPower"])
            sw_post(ip, "stat/poePort", form)
            sonuc["poe"] = sorted(poe)

        if portlar:
            mevcut = sw_get(ip, "stat/portMode").get("portMode", [])
            bilinen = {int(p["pid"]) for p in mevcut}
            eksik = sorted(set(portlar) - bilinen)
            if eksik:
                raise SwitchError(f"olmayan port: {eksik}")
            sw_post(ip, "stat/portMode", _portmode_form(mevcut, portlar))
            sonuc["ports"] = sorted(portlar)

    return _autosave(ip, sonuc)


def set_port_config(ip: str, port: int, cfg: dict) -> dict:
    """Bir portun hız/dupleks/akış/çerçeve ayarlarını günceller."""
    with lock_for(ip):
        ports = sw_get(ip, "stat/portMode").get("portMode", [])
        if not any(int(p["pid"]) == port for p in ports):
            raise SwitchError(f"port {port} yok")
        form = {}
        for p in ports:
            pid = int(p["pid"])
            cur = cfg if pid == port else {}
            admin = cur.get("adminStat", bool(p.get("adminStat")))
            if admin:
                form[f"adminStat_{pid}"] = "1"
            form[f"linkType_{pid}"] = str(p.get("linkType", "0"))
            auto = cur.get("autoNego", bool(p.get("autoNego")))
            if auto:
                form[f"autoNego_{pid}"] = "1"
            form[f"speed_{pid}"] = str(cur.get("speed", p.get("speed", "")))
            dup = cur.get("duplex", bool(p.get("duplex")))
            if dup:
                form[f"duplex_{pid}"] = "1"
            fc = cur.get("flowCtrl", bool(p.get("flowCtrl")))
            if fc:
                form[f"flowCtrl_{pid}"] = "1"
            form[f"maxLength_{pid}"] = str(
                cur.get("maxLength", p.get("maxLength", "1522")))
        return _autosave(ip, sw_post(ip, "stat/portMode", form))


def set_network(ip: str, addr: str, prefix: str, mtu="1500") -> dict:
    """Switch IP'sini değiştirir. Bağlantı kopması beklenen durumdur."""
    with lock_for(ip):
        form = {"method": "manual", "addr": addr,
                "netmaskLen": str(prefix), "mtu": str(mtu)}
        try:
            sonuc = sw_post(ip, "stat/vlanIntfIp?intf=1", form, timeout=5)
        except requests.RequestException:
            # IP değişince switch eski adresi bırakır, bağlantı kopar — normal
            sonuc = {"retCode": ["success"], "note": "bağlantı koptu (beklenen)"}
        # Kayıt YENİ adresten yapılmalı; switch eski IP'de artık yok
        if AUTOSAVE:
            time.sleep(2)
            try:
                config_save(addr)
                sonuc["saved"] = True
            except Exception:
                sonuc["saved"] = False
                sonuc["saveError"] = (f"{addr} adresinden kaydedilemedi — "
                                      f"yeni adresten bağlanıp Kaydet'e basın")
        return sonuc


def reboot(ip: str) -> dict:
    with lock_for(ip):
        try:
            return sw_post(ip, "stat/reboot",
                           {"postOperation": "reboot"}, timeout=5)
        except requests.RequestException:
            return {"retCode": ["success"], "note": "switch kapanıyor"}


def factory_reset(ip: str) -> dict:
    """Switch'i fabrika ayarlarına döndürür.

    Geri alınamaz: IP dahil bütün yapılandırma silinir, switch varsayılan
    adresine döner ve bu arayüzden bir daha bulunamayabilir. Bu yüzden
    çağrı, gövdede switch IP'sinin yazılı onayını ister (bkz. do_POST).
    """
    with lock_for(ip):
        try:
            return sw_post(ip, "stat/reset",
                           {"postOperation": "reset"}, timeout=10)
        except requests.RequestException:
            # Sıfırlanan switch cevap vermeden bağlantıyı koparabilir
            return {"retCode": ["success"], "note": "switch sıfırlanıyor"}


# --------------------------------------------------------------- HTTP -----
class Handler(BaseHTTPRequestHandler):
    server_version = "SwitchAPI/1.0"

    def _send(self, code, payload, ctype="application/json"):
        body = (json.dumps(payload).encode("utf-8")
                if ctype == "application/json" else payload)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

    def _file(self, name, ctype):
        """Statik dosyayı önbelleğe alınmadan gönderir.

        Önbellek başlığı göndermezsek tarayıcı kendi kestirimiyle dosyayı
        saklıyor; arayüzü güncelledikten sonra pencerede eski sürüm kalıyordu.
        Yerelden okunan birkaç KB için önbelleğin faydası da yok.
        """
        path = HERE / "static" / name
        if not path.exists():
            return self._send(404, {"error": "yok"})
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _index(self):
        """index.html'i varlık adreslerine sürüm ekleyerek gönderir.

        Uygulama penceresi (WKWebView / Chrome --app) eski app.js ve
        style.css'i inatla önbellekte tutabiliyor; arayüz güncellendiği
        halde eski hali görünüyordu. Dosya her değiştiğinde adres de
        değiştiği için önbellek kendiliğinden devre dışı kalır.
        """
        path = HERE / "static" / "index.html"
        if not path.exists():
            return self._send(404, {"error": "yok"})
        html = path.read_text(encoding="utf-8")
        for varlik in ("app.js", "style.css"):
            p = HERE / "static" / varlik
            surum = int(p.stat().st_mtime) if p.exists() else 0
            html = html.replace(f'"/{varlik}"', f'"/{varlik}?v={surum}"')
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    # --------------------------------------------------------- routing ----
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._index()
            if u.path == "/app.js":
                return self._file("app.js", "application/javascript")
            if u.path == "/style.css":
                return self._file("style.css", "text/css")
            if u.path == "/piton-logo.svg":
                return self._file("piton-logo.svg", "image/svg+xml")
            if u.path == "/piton-favicon.png":
                return self._file("piton-favicon.png", "image/png")

            if u.path == "/api/version":
                return self._send(200, {"version": APP_VERSION})
            if u.path == "/api/discover":
                cidr = q.get("cidr", [ENV.get("DISCOVER_CIDR", "10.1.1.0/24")])[0]
                if not _SCAN_LOCK.acquire(blocking=False):
                    return self._send(409, {"error": "tarama zaten sürüyor"})
                try:
                    return self._send(200, discover(cidr))
                finally:
                    _SCAN_LOCK.release()
            if u.path == "/api/switch/info":
                return self._send(200, get_info(q["ip"][0]))
            if u.path == "/api/switch/ports":
                return self._send(200, {"ports": get_ports(q["ip"][0])})
            return self._send(404, {"error": "bilinmeyen yol"})
        except KeyError:
            self._send(400, {"error": "ip parametresi gerekli"})
        except requests.RequestException as e:
            self._send(502, {"error": f"switch'e ulaşılamadı: {e}"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        body = self._json_body()
        ip = body.get("ip")
        try:
            if not ip:
                return self._send(400, {"error": "ip gerekli"})
            if u.path == "/api/switch/poe":
                return self._send(200, set_poe(ip, int(body["port"]),
                                               str(body["mode"])))
            if u.path == "/api/switch/port":
                if "enabled" in body:
                    return self._send(200, set_port_enabled(
                        ip, int(body["port"]), bool(body["enabled"])))
                return self._send(200, set_port_config(
                    ip, int(body["port"]), body.get("config", {})))
            if u.path == "/api/switch/batch":
                poe = {int(k): str(v)
                       for k, v in (body.get("poe") or {}).items()}
                portlar = {int(k): bool(v)
                           for k, v in (body.get("ports") or {}).items()}
                if not poe and not portlar:
                    return self._send(400, {"error": "gönderilecek değişiklik yok"})
                return self._send(200, apply_batch(ip, poe, portlar))
            if u.path == "/api/switch/network":
                return self._send(200, set_network(
                    ip, body["addr"], body["prefix"], body.get("mtu", "1500")))
            if u.path == "/api/switch/config-save":
                return self._send(200, config_save(ip))
            if u.path == "/api/switch/reboot":
                # Kendiliğinden kaydetmiyoruz: kayıt yalnızca kullanıcının
                # işi. Kaydedilmemiş değişiklikler varsa arayüz uyarıyor.
                return self._send(200, reboot(ip))
            if u.path == "/api/switch/factory-reset":
                # Yıkıcı işlem: gövdede switch IP'si onay olarak yazılmalı.
                if str(body.get("confirm", "")).strip() != ip:
                    return self._send(400, {"error": "onay doğrulanmadı"})
                return self._send(200, factory_reset(ip))
            return self._send(404, {"error": "bilinmeyen yol"})
        except (KeyError, ValueError) as e:
            self._send(400, {"error": f"eksik/geçersiz alan: {e}"})
        except SwitchError as e:
            self._send(400, {"error": str(e)})
        except requests.RequestException as e:
            self._send(502, {"error": f"switch'e ulaşılamadı: {e}"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        pass


def main():
    p = argparse.ArgumentParser(description="KYLAND switch yönetim backend'i")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--discover", default=None,
                   help="başlangıçta bu ağı tara (ör. 10.1.1.0/24)")
    p.add_argument("--no-browser", action="store_true",
                   help="tarayıcıyı otomatik açma")
    args = p.parse_args()

    if args.discover:
        print(f"Ağ taranıyor: {args.discover}")
        for s in discover(args.discover)["switches"]:
            print(f"  {s['ip']:<14} {s['model']} v{s['version']}")

    if not SWITCH_PASS:
        print("[!] Switch şifresi yok. Interface/.env içine SWITCH_PASSWORD "
              "ekleyin (veya KYLAND_PASSWORD).")

    url = f"http://{args.host}:{args.port}"
    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print(f"[HATA] {args.port} portu açılamadı: {exc}")
        print(f"       Başka bir kopya çalışıyor olabilir. "
              f"Tarayıcıdan {url} adresini deneyin ya da --port ile "
              f"başka bir port verin.")
        return 1

    print(f"Arayüz: {url}   (durdurmak için Ctrl-C)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatılıyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
