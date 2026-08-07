#!/usr/bin/env python3
"""Yataklı — Intercom IP otomatik atama.

Aynı fabrika IP'siyle gelen intercomlar switch portlarına bağlıyken, PoE
portlarını sırayla tek tek açarak her cihaza DeviceMap'te o porta tanımlı
IP'yi atar.

Akış (her hedef port için):
  1. Aralıktaki bütün PoE portları KAPAT, yalnızca hedef portu AÇ
  2. Cihazın açılmasını bekle, aday IP'lerde /api/v1/system/settings ara
  3. Bulunan cihaz yanlış IP'deyse doğru IP'yi yaz
  4. Cihaz (ESP32) reset atar — hedef IP'de tekrar görünmesini bekle
  5. Sıradaki porta geç
Bitince aralıktaki bütün portlar tekrar açılır.

Kullanım:
    python3 intercom_ip_assign.py --ports 11 12 13 14
    python3 intercom_ip_assign.py --ports 11-14 --default-ip 10.1.1.12
    python3 intercom_ip_assign.py --ports 11-22 -n 2 --dry-run
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HERE = Path(__file__).resolve().parent

POE_ON, POE_OFF = "1", "0"


# --------------------------------------------------------------- yardımcı --
def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def resolve(tmpl: str, set_no) -> str:
    return re.sub(r"(?<![0-9a-zA-Z])n(?![0-9a-zA-Z])", str(set_no), tmpl or "")


def parse_ports(values: list[str]) -> list[int]:
    """['11','12'] veya ['11-14'] -> [11, 12, 13, 14]"""
    ports = []
    for v in values:
        if "-" in v:
            a, b = v.split("-", 1)
            ports.extend(range(int(a), int(b) + 1))
        else:
            ports.append(int(v))
    return sorted(set(ports))


# ------------------------------------------------------------ switch PoE ---
POE_READ_ENDPOINTS = ["stat/poeStatus", "stat/poePort", "stat/portList"]


def switch_request(cfg, method: str, endpoint: str, **kw):
    """Switch'e istek atar; geçici hatalarda tekrar dener.

    KYLAND'ın web sunucusu PoE anahtarlaması sırasında birkaç saniye
    cevap vermeyebiliyor; tek seferlik hata bütün koşuyu düşürmemeli.
    """
    url = f"http://{cfg.switch_ip}:{cfg.kyland_port}/{endpoint}"
    last = None
    for attempt in range(cfg.switch_retries + 1):
        try:
            r = requests.request(method, url,
                                 auth=HTTPBasicAuth(cfg.kyland_user,
                                                    cfg.kyland_pass),
                                 timeout=cfg.timeout, **kw)
            # 4xx kalıcı hatadır (uç yok / yetki yok) — tekrar denemek anlamsız
            if 400 <= r.status_code < 500:
                r.raise_for_status()
            r.raise_for_status()
            return r
        except requests.HTTPError as exc:
            if exc.response is not None and 400 <= exc.response.status_code < 500:
                raise                        # beklemeden çık
            last = exc
        except requests.RequestException as exc:
            last = exc
        if attempt < cfg.switch_retries:
            wait = cfg.switch_retry_wait * (attempt + 1)
            print(f"    (switch cevap vermedi, {wait:.0f} sn sonra "
                  f"tekrar denenecek — {type(last).__name__})")
            time.sleep(wait)
    raise last


MAC_ENDPOINTS = ["stat/macQuery", "stat/macAddress", "stat/fdb"]


def norm_mac(value) -> str | None:
    """5c-1-3b-8A-76-43 / 5c01.3b8a.7643 -> 5c:01:3b:8a:76:43"""
    if not value:
        return None
    hexes = re.findall(r"[0-9a-fA-F]{1,2}", str(value).replace(".", ""))
    if len(hexes) < 6:
        return None
    return ":".join(h.rjust(2, "0").lower() for h in hexes[:6])


def host_mac(ip: str) -> str | None:
    """İşletim sisteminin ARP tablosundan IP'nin MAC'ini okur.

    Cihazla az önce HTTP konuşulduğu için ARP kaydı tazedir.
    """
    for cmd in (["arp", "-n", ip], ["ip", "neigh", "show", ip]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.search(r"(?:[0-9a-fA-F]{1,2}:){5}[0-9a-fA-F]{1,2}", out)
        if m:
            return norm_mac(m.group(0))
    return None


# ─────────────────────────────────────────────────────── ARP önbelleği ────
# Bütün intercomlar aynı fabrika adresiyle (10.n.1.12) geliyor ve her biri
# ayrı MAC taşıyor. Bir cihaza IP yazılıp sıradaki port açıldığında işletim
# sisteminin ARP tablosunda o adres HÂLÂ önceki cihazın MAC'ini gösteriyor:
#
#     ARP tablosu   10.1.1.12 -> 5c:01:3b:53:a4:73   (çoktan .13'e taşındı)
#     gerçek        10.1.1.12 -> 5c:01:3b:53:65:ff
#
# HTTP yoklaması o eski MAC'e gidiyor, cevap gelmiyor ve cihaz "bulunamadı"
# sayılıyor. macOS'ta kayıt 20 dakika yaşıyor; koşunun tur tur uzamasının,
# arp-scan'in cihazı görüp betiğin görememesinin sebebi bu. host_mac() de
# aynı bayat kaydı okuduğu için MAC doğrulaması yanlış portu bildiriyor.
#
# Kayıt silinince çekirdek yeniden ARP sorar ve doğru MAC'i öğrenir.
_ARP_UYARI_VERILDI = False


def arp_silebilir() -> bool:
    """ARP kaydı silme yetkimiz var mı?

    Doğrudan yetkiye bakılır; "sil" denemesinin çıktısına bakmak
    yanıltıyor: kaydı olmayan bir adres yetkisizken de "cannot locate"
    diyor ve mekanizma çalışıyor sanılıyordu.
    """
    try:
        if os.geteuid() == 0:
            return True
    except AttributeError:                 # Windows
        return False
    try:
        # -n hiçbir zaman parola sormaz; zaman damgası tazeyse 0 döner.
        return subprocess.run(["sudo", "-n", "true"], capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def arp_unut(ips, cfg=None) -> bool:
    """Verilen adresleri ARP önbelleğinden siler. Dönüş: silebildi mi.

    Silme yönlendirme soketine yazmak demek, yani root ister. Uygulama
    root değilse `sudo -n` denenir: kullanıcı koşudan önce bir kez
    `sudo -v` çalıştırdıysa bu çalışır ve her başarılı çağrı sudo'nun
    zaman damgasını tazelediği için koşu boyunca yeterlidir.
    """
    global _ARP_UYARI_VERILDI
    if cfg is not None and not getattr(cfg, "arp_flush", True):
        return False
    if not arp_silebilir():
        if not _ARP_UYARI_VERILDI:
            _ARP_UYARI_VERILDI = True
            print("[!] ARP önbelleği temizlenemiyor (root gerekiyor). Aynı "
                  "fabrika adresindeki cihazlar")
            print("    eski MAC'e yazıldığı için 'cihaz bulunamadı' hatası "
                  "verir. Koşudan önce")
            print("    terminalde bir kez: sudo -v    (ya da uygulamayı sudo "
                  "ile başlatın)")
        return False
    kok = os.geteuid() == 0
    for ip in ips:
        for cmd in ([["arp", "-d", ip], ["ip", "neigh", "flush", "to", ip]]
                    if kok else
                    [["sudo", "-n", "arp", "-d", ip],
                     ["sudo", "-n", "ip", "neigh", "flush", "to", ip]]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=5)
            except (OSError, subprocess.SubprocessError):
                continue
            ciktilar = (r.stdout or "") + (r.stderr or "")
            # "cannot locate" / "no entry" = silinecek kayıt yoktu.
            if (r.returncode == 0 or "no entry" in ciktilar
                    or "cannot locate" in ciktilar):
                break
    return True


def _mac_rows(data) -> list[dict]:
    if isinstance(data, dict):
        for value in data.values():
            if (isinstance(value, list) and value
                    and isinstance(value[0], dict)
                    and any("mac" in k.lower() for k in value[0])):
                return value
    return []


_MAC_CACHE = {"endpoint": None, "table": {}, "at": 0.0, "dead": False}


def _find_port(obj):
    """Kayıt içindeki port numarasını iç içe yapılarda da bulur.

    KYLAND {"mac": "...", "portList": [{"pid": 11}]} gibi döndürebiliyor;
    üst seviyede 'pid' aramak yetmiyor.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            k = key.lower()
            if k in ("pid", "port", "portid", "portno", "pname"):
                digits = re.sub(r"\D", "", str(value))
                if digits:
                    return int(digits)
        for value in obj.values():
            if isinstance(value, (dict, list)):
                got = _find_port(value)
                if got is not None:
                    return got
    elif isinstance(obj, list):
        for item in obj:
            got = _find_port(item)
            if got is not None:
                return got
    return None


def _parse_mac_table(data) -> dict:
    table = {}
    for row in _mac_rows(data):
        mac = norm_mac(next((v for k, v in row.items()
                             if "mac" in k.lower()
                             and not isinstance(v, (dict, list))), None))
        port = _find_port(row)
        if mac and port is not None:
            table[mac] = port
    return table


def switch_mac_table(cfg) -> dict:
    """Switch'in MAC tablosu: {mac: port}.

    Çalışan uç bir kez keşfedilip saklanır; PoE değiştiği için tablo kısa
    ömürlüdür (mac_cache_ttl). Hiçbir uç çalışmıyorsa bir daha denenmez.
    """
    if _MAC_CACHE["dead"]:
        return {}
    if (_MAC_CACHE["table"]
            and time.monotonic() - _MAC_CACHE["at"] < cfg.mac_cache_ttl):
        return _MAC_CACHE["table"]

    endpoints = ([_MAC_CACHE["endpoint"]] if _MAC_CACHE["endpoint"]
                 else [cfg.mac_endpoint] if cfg.mac_endpoint else MAC_ENDPOINTS)
    for endpoint in endpoints:
        try:
            table = _parse_mac_table(switch_request(cfg, "GET", endpoint).json())
        except Exception:
            continue
        if table:
            if _MAC_CACHE["endpoint"] != endpoint:
                print(f"    MAC tablosu: {endpoint} ({len(table)} kayıt)")
            _MAC_CACHE.update(endpoint=endpoint, table=table,
                              at=time.monotonic())
            return table

    _MAC_CACHE["dead"] = True
    print("    [!] Switch MAC tablosu okunamadı "
          f"({', '.join(endpoints)}) — MAC doğrulaması kapatıldı, "
          "uptime yöntemine dönülüyor")
    return {}


def verify_port(ip: str, expected_port: int, cfg) -> tuple[bool | None, str]:
    """Bu IP'deki cihaz gerçekten beklenen portta mı?

    Döner: (True doğrulandı / False yanlış port / None doğrulanamadı, açıklama)
    Tahmin yerine kesin bilgi: host ARP -> MAC, switch MAC tablosu -> port.
    """
    if not cfg.verify_mac:
        return None, "mac doğrulama kapalı"
    mac = host_mac(ip)
    if not mac:
        return None, "ARP'ta MAC yok"
    table = switch_mac_table(cfg)
    if not table:
        return None, "switch MAC tablosu okunamadı"
    port = table.get(mac)
    if port is None:
        return None, f"MAC {mac} tabloda yok"
    return port == expected_port, f"MAC {mac} -> port {port}"


def port_link(cfg, port: int):
    """Switch'e göre portun linki ayakta mı? True/False/None (okunamadı).

    Cihazın gerçekten elektriği alıp hattı kurduğunun switch tarafındaki
    kanıtı. HTTP yoklamasından önce buna bakmak, "daha açılmamış cihazı
    aramakla" geçen süreyi ortadan kaldırıyor.
    """
    try:
        r = switch_request(cfg, "GET", "stat/portMode")
        satirlar = r.json().get("portMode", [])
    except Exception:
        return None
    if not isinstance(satirlar, list):
        return None
    for p in satirlar:
        if isinstance(p, dict) and str(p.get("pid")) == str(port):
            return str(p.get("linkStat", "")).lower() == "up"
    return None


def link_bekle(cfg, port: int, sure: float):
    """Port link'i ayağa kalkana kadar bekler. Döner: (durum, geçen sn).

    durum True  — bağlandı
          False — verilen sürede bağlanmadı
          None  — switch link durumunu vermiyor (eski davranışa dönülür)

    Koşunun ilk portunda link zaten ayakta olabilir: o port kapanmamıştı,
    cihaz da yeniden başlamadı. Bu durum geçen süreden (≈0 sn) anlaşılır
    ve çağıran taraf farkı yazdırır.
    """
    basla = time.monotonic()
    ilk = port_link(cfg, port)
    if ilk is None:
        return None, 0.0
    if ilk is True:
        return True, 0.0
    while True:
        if port_link(cfg, port):
            return True, time.monotonic() - basla
        if time.monotonic() - basla >= sure:
            return False, time.monotonic() - basla
        time.sleep(cfg.poll_interval)


def _poe_rows(data) -> list[dict]:
    """Yanıtın içinden 'pid' taşıyan kayıt listesini bulur."""
    if isinstance(data, dict):
        for value in data.values():
            if (isinstance(value, list) and value
                    and isinstance(value[0], dict) and "pid" in value[0]):
                return value
    return []


def poe_read(cfg) -> list[dict]:
    """Switch'ten güncel PoE port durumlarını okur.

    Okuma ve yazma uçları farklı: yazma POST /stat/poePort, okuma ise
    /stat/poeStatus. Firmware'e göre değiştiği için sırayla denenir ve
    retCode yerine gövdedeki veriye bakılır.
    """
    errors = []
    for endpoint in ([cfg.poe_read_endpoint] if cfg.poe_read_endpoint
                     else POE_READ_ENDPOINTS):
        try:
            data = switch_request(cfg, "GET", endpoint).json()
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}")
            continue

        rows = _poe_rows(data)
        if rows:
            if cfg.verbose:
                print(f"    PoE durumu {endpoint} ucundan okundu "
                      f"({len(rows)} port)")
            return [{"pid": int(x["pid"]),
                     "poeMode":  str(x.get("poeMode", x.get("mode", POE_ON))),
                     "priority": str(x.get("priority", "0")),
                     "maxPower": str(x.get("maxPower", "154"))} for x in rows]
        errors.append(f"{endpoint}: retCode={data.get('retCode')!r}, "
                      f"anahtarlar={list(data)[:6]}")

    raise RuntimeError("PoE durumu okunamadı -> " + " | ".join(errors))


def poe_apply(cfg, ports_state: list[dict], enabled_in_range: set[int],
              managed: set[int]) -> None:
    """PoE durumunu yazar.

    Aralık (managed) içindeki portlardan yalnızca enabled_in_range açık olur;
    aralık dışındaki portların mevcut ayarlarına dokunulmaz.
    """
    fields = []
    for p in ports_state:
        pid = int(p["pid"])
        if pid in managed:
            mode = POE_ON if pid in enabled_in_range else POE_OFF
        else:
            mode = str(p.get("poeMode", POE_ON))
        fields.append(f"mode_{pid}={mode}"
                      f"&priority_{pid}={p.get('priority', '0')}"
                      f"&maxPower_{pid}={p.get('maxPower', '154')}")
    payload = "&".join(fields)

    if cfg.dry_run:
        onoff = {pid: (POE_ON if pid in enabled_in_range else POE_OFF)
                 for pid in sorted(managed)}
        print(f"    [dry-run] PoE: {onoff}")
        return

    r = switch_request(cfg, "POST", "stat/poePort",
                       headers={"Content-Type":
                                "application/x-www-form-urlencoded; charset=UTF-8",
                                "X-Requested-With": "XMLHttpRequest"},
                       data=payload)
    ret = r.json().get("retCode")
    if ret not in (["success"], "success"):
        raise RuntimeError(f"poePort yazma başarısız: {ret}")


# ------------------------------------------------------------- intercom ----
def read_settings(ip: str, cfg) -> dict | None:
    """Cihaz ayaklandıysa ayarlarını döndürür, yoksa None."""
    try:
        r = requests.get(
            f"http://{ip}:{cfg.arduino_port}/api/v1/system/settings",
            timeout=cfg.probe_timeout)
        if r.ok:
            return r.json()
    except requests.RequestException:
        pass
    return None


def probe_all(candidates: list[str], cfg) -> dict:
    """Cevap veren adayları döndürür {ip: settings} — paralel."""
    candidates = list(candidates)
    if not candidates:
        return {}
    with cf.ThreadPoolExecutor(max_workers=min(len(candidates), 32)) as pool:
        results = pool.map(lambda ip: (ip, read_settings(ip, cfg)), candidates)
    return {ip: s for ip, s in results if s is not None}


def uptime_of(settings: dict):
    for key in ("uptime", "uptimeSeconds", "upTime"):
        if key in settings:
            try:
                return float(settings[key])
            except (TypeError, ValueError):
                return None
    return None


def find_device(candidates: list[str], cfg, deadline: float,
                baseline: dict | None = None):
    """Portu yeni açılan cihazı bulur.

    Ayırt etme sırası:
      1. UPTIME — port yeni açıldığı için cihazımızın uptime'ı küçüktür.
         Birden fazla cevap gelirse en küçük uptime'lı seçilir. Bu, aynı
         IP'de iki cihaz varken de doğru olanı bulur.
      2. Baseline dışı olmak — uptime alınamıyorsa yedek ölçüt.

    Baseline = aralıktaki portlar kapalıyken cevap verenler; yönetilmeyen
    portlardaki cihazlar oradadır ve onlara dokunulmamalıdır.
    """
    baseline = baseline or {}
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        found = probe_all(candidates, cfg)
        if len(found) > 1:
            print(f"    [!] {len(found)} cihaz cevap verdi: "
                  f"{', '.join(found)} — en yeni açılan seçilecek")

        # Fabrika IP'sindeki cihaz kesinlikle yapılandırılmamış bir
        # intercomdur; ona öncelik verilir. Sonra en küçük uptime.
        factory = getattr(cfg, "factory_ip", None)
        fresh = [(0 if ip == factory else 1, uptime_of(s), ip, s)
                 for ip, s in found.items()
                 if uptime_of(s) is not None
                 and uptime_of(s) <= cfg.fresh_uptime]
        if fresh:
            fresh.sort(key=lambda x: (x[0], x[1]))
            _, _, ip, settings = fresh[0]
            if ip == factory:
                print("    (fabrika IP'si — yapılandırılmamış cihaz)")
            return ip, settings

        # uptime alınamıyorsa bile fabrika IP'si güçlü bir işarettir
        if factory in found and factory not in baseline:
            print("    (fabrika IP'si — yapılandırılmamış cihaz)")
            return factory, found[factory]

        for ip, settings in found.items():          # uptime yoksa baseline
            if ip not in baseline:
                return ip, settings

        time.sleep(cfg.poll_interval)
    return None, None


def wait_gone(ips, cfg, deadline: float) -> list[str]:
    """Verilen IP'ler susana kadar bekler; kalanları döndürür.

    Bir cihaza IP yazıldıktan sonra reset atar ve uptime'ı sıfırlanır.
    Sıradaki porta geçerken bu cihaz hâlâ ayaktaysa 'en taze cihaz'
    sanılıp üzerine yazılır. Bu yüzden önce gerçekten sustuğu doğrulanır.
    """
    ips = list(ips)
    if not ips:
        return []
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        still = [ip for ip in ips if read_settings(ip, cfg) is not None]
        if not still:
            return []
        time.sleep(cfg.poll_interval)
    return [ip for ip in ips if read_settings(ip, cfg) is not None]


def wait_until_quiet(candidates: list[str], cfg, deadline: float) -> dict:
    """Portlar kapatıldıktan sonra cihazların gerçekten sustuğunu bekler.

    PoE kesilse de cihaz birkaç saniye daha cevap verebilir; hemen okunan
    baseline yanlış olur ve o IP'deki cihaz sonradan 'dokunma' listesine
    girip atlanır. Cevap sayısı sabitlenene kadar beklenir.
    """
    end = time.monotonic() + deadline
    last, stable = None, 0
    while time.monotonic() < end:
        now = probe_all(candidates, cfg)
        keys = set(now)
        if keys == last:
            stable += 1
            if stable >= 2:              # üst üste aynı -> oturdu
                return now
        else:
            stable = 0
        last = keys
        time.sleep(cfg.poll_interval)
    return probe_all(candidates, cfg)


def write_ip(ip: str, settings: dict, new_ip: str, cfg) -> None:
    """Cihaza yeni IP yazar — doğrulanmış uç: POST /api/v1/network/ip

    Gövde tam ağ bloğudur; IP dışındaki değerler cihazın mevcut
    ayarlarından korunur (netmask / gateway / ntpIp / useDhcp).
    Yazımdan sonra cihaz yeniden başlayabilir, bağlantı kesilebilir.
    """
    # Cihazın kendi web arayüzü yalnızca bu üç alanı gönderiyor. Fazladan
    # alan göndermek firmware'de sessizce reddedilmeye yol açabiliyor.
    payload = {
        "ip":      new_ip,
        "netmask": settings.get("netmask") or cfg.netmask,
        "gateway": settings.get("gateway") or cfg.gateway or "",
    }
    if cfg.full_net_payload:
        payload["useDhcp"] = bool(settings.get("useDhcp")
                                  or settings.get("usedhcp") or False)
        payload["ntpIp"] = (settings.get("ntpIp") or settings.get("ntpip")
                            or cfg.ntp_ip or "")
    if cfg.dry_run:
        print(f"    [dry-run] {ip} -> POST /{cfg.write_endpoint}: {payload}")
        return
    r = requests.post(f"http://{ip}:{cfg.arduino_port}/{cfg.write_endpoint}",
                      json=payload,
                      headers={"Content-Type": "application/json"},
                      timeout=cfg.timeout)
    r.raise_for_status()

    # HTTP 200 tek başına yetmez; gövdede hata bildirimi olabilir
    try:
        body = r.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        blob = json.dumps(body).lower()
        if any(w in blob for w in ("error", "fail", "invalid", "reject")):
            raise RuntimeError(f"cihaz yazmayı reddetti: {body}")


# ------------------------------------------------------------------- akış --
def parse_args(env):
    p = argparse.ArgumentParser(
        description="Intercom IP otomatik atama (PoE port sırayla açma)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--ports", nargs="+", required=True, metavar="P",
                   help="Hedef port(lar): '11 12 13 14' veya '11-14'")
    p.add_argument("-n", "--set", dest="set_no",
                   default=env.get("TRAIN_SET_NO", "1"),
                   help="Set numarası — IP şablonundaki 'n'")
    p.add_argument("--device-map", type=Path,
                   default=Path(env.get("DEVICE_MAP_FILE")
                                or HERE / "DeviceMap.json"))
    p.add_argument("--switch-ip", default=None,
                   help="Switch IP (varsayılan: DeviceMap'te bu portların "
                        "bağlı olduğu switch)")
    p.add_argument("--factory-ip",
                   default=env.get("INTERCOM_FACTORY_IP", "10.n.1.12"),
                   help="Intercomların fabrika çıkışı beklediği IP. "
                        "'n' set numarasıyla çözülür; sabit bir adres de "
                        "yazılabilir. Bu adreste cevap veren cihaz "
                        "yapılandırılmamış intercom sayılır.")
    p.add_argument("--default-ip", nargs="+", default=[], metavar="IP",
                   help="Ek aday IP'ler. Fabrika IP'si ve DeviceMap'teki "
                        "bütün Intercom adresleri zaten aday listesindedir.")
    p.add_argument("--fresh-uptime", type=float, default=180.0,
                   help="Aynı IP'de iki cihaz varsa, uptime'ı bu değerin "
                        "altındaki 'yeni açılmış' sayılır (sn)")
    p.add_argument("--max-passes", type=int, default=0,
                   help="En fazla kaç tur denensin (0 = sınırsız, "
                        "hepsi tamamlanana kadar)")
    p.add_argument("--stall-limit", type=int, default=2,
                   help="Üst üste hiç ilerleme olmayan tur sayısı bu değere "
                        "ulaşınca durur")
    p.add_argument("--retry-backoff", type=float, default=1.5,
                   help="İlerleme olmayan her turda bekleme sürelerinin "
                        "çarpanı (1.0 = artırma)")
    p.add_argument("--kyland-port", type=int,
                   default=int(env.get("KYLAND_HTTP_PORT", 80)))
    p.add_argument("--kyland-user", default=env.get("KYLAND_USERNAME", "admin"))
    p.add_argument("--kyland-pass", default=env.get("KYLAND_PASSWORD", ""))
    p.add_argument("--arduino-port", type=int,
                   default=int(env.get("ARDUINO_HTTP_PORT", 80)))
    p.add_argument("--write-endpoint", default="api/v1/network/ip",
                   help="Ağ ayarlarının yazıldığı uç")
    p.add_argument("--netmask", default=env.get("EXPECTED_SUBNET_MASK",
                                                "255.255.0.0"),
                   help="Cihaz bildirmezse kullanılacak netmask")
    p.add_argument("--gateway", default=None,
                   help="Cihaz bildirmezse gateway (varsayılan: switch IP)")
    p.add_argument("--ntp-ip", default=None,
                   help="Cihaz bildirmezse NTP IP (varsayılan: PISCU)")
    p.add_argument("--backup-dir", type=Path, default=None,
                   help="Her cihazın ayarlarını yazmadan önce buraya yedekle")
    # ESP32'lerin açılışı en fazla ~10 sn. Aşağıdakiler ÜST SINIR; cihaz
    # cevap verir vermez beklemeden devam edilir. Yavaş bir cihaz çıkarsa
    # --retry-backoff zaten her takılan turda süreleri 1.5 katına çıkarır.
    p.add_argument("--link-wait", type=float, default=25.0,
                   help="Port açıldıktan sonra switch'te link'in ayağa "
                        "kalkmasını bekleme süresi (sn). Cihaz aranmaya "
                        "ancak link kurulunca başlanır.")
    p.add_argument("--find-wait", type=float, default=10.0,
                   help="Link kurulduktan SONRA cihazı arama süresi (sn)")
    p.add_argument("--boot-wait", type=float, default=15.0,
                   help="Link durumu okunamıyorsa cihazı arama süresi (sn) "
                        "— ESP32 açılışı ~10 sn")
    p.add_argument("--confirm-wait", type=float, default=30.0,
                   help="IP yazıldıktan (reset) sonra doğrulama süresi (sn) "
                        "— reset + açılış ~10 sn")
    p.add_argument("--settle", type=float, default=2.0,
                   help="PoE değişikliği sonrası bekleme (sn)")
    p.add_argument("--baseline-wait", type=float, default=12.0,
                   help="Portlar kapatıldıktan sonra cihazların susmasını "
                        "bekleme süresi (sn)")
    p.add_argument("--poll-interval", type=float, default=1.0)
    p.add_argument("--probe-timeout", type=float, default=1.5,
                   help="Tek IP yoklamasının zaman aşımı (sn)")
    p.add_argument("--timeout", type=float, default=8.0,
                   help="Switch/yazma istekleri zaman aşımı (sn)")
    p.add_argument("--switch-retries", type=int, default=3,
                   help="Switch cevap vermezse kaç kez tekrar denensin")
    p.add_argument("--switch-retry-wait", type=float, default=5.0,
                   help="Switch tekrar denemeleri arası bekleme (sn, artar)")
    p.add_argument("--no-verify-mac", dest="verify_mac", action="store_false",
                   help="MAC ile port doğrulamasını kapat (uptime tahminine "
                        "geri dön)")
    p.add_argument("--mac-endpoint", default=None,
                   help=f"Switch MAC tablosu ucu "
                        f"(denenenler: {', '.join(MAC_ENDPOINTS)})")
    p.add_argument("--mac-cache-ttl", type=float, default=4.0,
                   help="MAC tablosunun önbellekte kalma süresi (sn)")
    p.add_argument("--no-defer-verify", dest="defer_verify",
                   action="store_false",
                   help="Her portta reset sonrası doğrulamayı bekle "
                        "(varsayılan: doğrulama sona bırakılır)")
    p.add_argument("--post-write-wait", type=float, default=2.0,
                   help="IP yazdıktan sonra reset beklemeye başlama gecikmesi")
    p.add_argument("--reset-wait", type=float, default=15.0,
                   help="Yazma sonrası cihazın eski IP'den düşmesi için "
                        "beklenecek süre (reset kanıtı)")
    p.add_argument("--full-net-payload", action="store_true",
                   help="Ağ yazımına useDhcp ve ntpIp alanlarını da ekle "
                        "(varsayılan: web arayüzüyle aynı — ip/netmask/gateway)")
    p.add_argument("--no-persist-check", dest="persist_check",
                   action="store_false",
                   help="Sonda güç çevirip ayarların kalıcı olduğunu doğrulama")
    p.add_argument("--no-arp-flush", dest="arp_flush", action="store_false",
                   help="Yoklamadan önce ARP önbelleğini temizleme. Aynı "
                        "fabrika adresindeki cihazlarda temizlik şart: "
                        "kapatılırsa eski MAC'e yazılıp cihaz bulunamaz.")
    p.add_argument("--poe-read-endpoint", default=None,
                   help=f"PoE durumunun okunacağı uç "
                        f"(denenenler: {', '.join(POE_READ_ENDPOINTS)})")
    p.add_argument("--switch-port-count", type=int, default=None,
                   help="Okuma hiç çalışmazsa varsayılan port sayısı (ör. 24)")
    p.add_argument("--dry-run", action="store_true",
                   help="Hiçbir şeye yazma, planı ve adımları göster")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    env = load_env(HERE / ".env")
    cfg = parse_args(env)
    n = cfg.set_no
    ports = parse_ports(cfg.ports)

    dm = json.loads(cfg.device_map.read_text(encoding="utf-8"))

    # Port -> hedef IP eşlemesi (yalnızca Intercom kayıtları)
    plan: dict[int, dict] = {}
    switch_tmpl = None
    for sw in dm.get("Switches", []):
        for dv in sw.get("Devices", []):
            if dv.get("SubType") != "Intercom":
                continue
            try:
                port = int(str(dv.get("Port")).strip())
            except (TypeError, ValueError):
                continue
            if port in ports:
                plan[port] = {"name": dv.get("Name", ""),
                              "target": resolve(dv.get("IP", ""), n)}
                switch_tmpl = sw.get("IP", "")

    missing = [p for p in ports if p not in plan]
    if missing:
        print(f"[HATA] Şu portlarda DeviceMap'te Intercom tanımlı değil: "
              f"{missing}")
        print("       Bu script şimdilik yalnızca Intercom portlarıyla çalışır.")
        return 1

    cfg.switch_ip = cfg.switch_ip or resolve(switch_tmpl, n)
    cfg.gateway = cfg.gateway or cfg.switch_ip
    if not cfg.ntp_ip:
        for sw in dm.get("Switches", []):
            for dv in sw.get("Devices", []):
                if dv.get("Type") == "PISCU":
                    cfg.ntp_ip = resolve(dv.get("IP", ""), n)
    targets = [plan[p]["target"] for p in ports]
    # Aday IP'ler: hedefler + DeviceMap'teki BÜTÜN intercom adresleri +
    # kullanıcının verdiği ekstralar. Cihaz fabrika/eski IP'siyle başka bir
    # intercomun adresinde durabilir; sadece kendi hedefine bakmak yetmez.
    all_intercom = [resolve(dv.get("IP", ""), n)
                    for sw in dm.get("Switches", [])
                    for dv in sw.get("Devices", [])
                    if dv.get("SubType") == "Intercom"]
    cfg.factory_ip = resolve(cfg.factory_ip, n)
    candidates = list(dict.fromkeys(
        [cfg.factory_ip] + targets + all_intercom
        + [resolve(ip, n) for ip in cfg.default_ip]))

    print(f"Set no    : {n}")
    print(f"Switch    : {cfg.switch_ip}")
    print(f"Portlar   : {ports}")
    for p in ports:
        print(f"   port {p:>2}  ->  {plan[p]['target']:<14} ({plan[p]['name']})")
    print(f"Fabrika IP: {cfg.factory_ip}   "
          f"(bu adreste cevap veren = yapılandırılmamış intercom)")
    print(f"Aday IP'ler: {', '.join(candidates)}")

    # ARP temizliği koşunun tek turda bitmesinin şartı; yetki yoksa
    # kullanıcı bunu koşu bitince değil, en başta öğrensin.
    if cfg.arp_flush and not cfg.dry_run:
        if arp_unut([cfg.factory_ip], cfg):
            print("ARP       : önbellek temizlenebiliyor")
    if cfg.dry_run:
        print("\n[dry-run] Hiçbir değişiklik yapılmayacak.\n")

    try:
        state = poe_read(cfg)
    except Exception as exc:
        count = cfg.switch_port_count or (24 if cfg.dry_run else None)
        if count is None:
            print(f"[HATA] Switch PoE durumu okunamadı ({cfg.switch_ip})")
            print(f"       {exc}")
            print( "       Doğru ucu biliyorsan: --poe-read-endpoint stat/xxx")
            print( "       Ya da port sayısını ver: --switch-port-count 24")
            return 1
        print(f"[!] PoE durumu okunamadı, {count} portluk varsayılan "
              f"kullanılıyor ({exc})")
        state = [{"pid": i, "poeMode": POE_ON, "priority": "0",
                  "maxPower": "154"} for i in range(1, count + 1)]
    known_pids = {int(p["pid"]) for p in state}
    unknown = [p for p in ports if p not in known_pids]
    if unknown:
        print(f"[HATA] Switch'te olmayan port: {unknown}")
        return 1
    managed = set(ports)

    def do_port(port: int, baseline: dict, label: str,
                assigned: set[str]) -> tuple[bool, str]:
        target = plan[port]["target"]
        print(f"\n{label} Port {port} -> {target} ({plan[port]['name']})")

        # Aralıktaki portlar kapatılır ve hedef port AYNI yazımda açılır:
        # switch'e tek istek gider, biri kapanırken diğeri açılır.
        print(f"    aralıktaki portlar kapatılıyor, {port} açılıyor...")
        try:
            poe_apply(cfg, state, {port}, managed)
        except Exception as exc:
            return False, f"switch hatası: {type(exc).__name__}"
        if cfg.dry_run:
            return True, ""
        time.sleep(cfg.settle)

        # Yoklamadan ÖNCE ARP önbelleği temizlenir: bu adreslerin kaydı
        # önceki cihazın MAC'ini gösteriyor olabilir (bkz. arp_unut).
        arp_unut({cfg.factory_ip, target}
                 | {plan[p]["target"] for p in ports}, cfg)

        # Körlemesine saymak yerine switch'e sorulur: port bağlandı mı?
        # Link "up" olduğu an cihaz elektriği aldı ve hattı kurdu demektir;
        # arama penceresi ancak o zaman başlar. Eskiden port açılır açılmaz
        # 15 sn'lik pencere işlemeye başlıyor, cihaz daha açılmadan süre
        # tükeniyordu — turların çoğu buradan çıkıyordu.
        bagli, gecen = link_bekle(cfg, port, cfg.link_wait)
        if bagli is True:
            nasil = ("link zaten ayaktaydı" if gecen < 0.5
                     else f"port bağlandı ({gecen:.1f} sn)")
            print(f"    {nasil} — cihaz aranıyor "
                  f"(en fazla {cfg.find_wait:.0f} sn)...")
            arama_suresi = cfg.find_wait
        elif bagli is None:
            print(f"    (link durumu okunamadı) cihaz aranıyor "
                  f"(en fazla {cfg.boot_wait:.0f} sn)...")
            arama_suresi = cfg.boot_wait
        else:
            print(f"    [!] Port {gecen:.0f} sn'de bağlanmadı — kablo/cihaz "
                  f"kontrolü gerekebilir")
            return False, "port bağlanmadı (link up olmadı)"

        # Atanmış IP'ler aday listesinden çıkarılır (fabrika IP'si hariç).
        search = [ip for ip in candidates
                  if ip not in assigned or ip == cfg.factory_ip]

        # MAC doğrulaması: yanlış porttaki cihazlar elenip arama sürdürülür
        blocked, found_ip, settings = [], None, None
        end = time.monotonic() + arama_suresi
        while True:
            kalan = max(1.0, end - time.monotonic())
            ip, st = find_device([c for c in search if c not in blocked],
                                 cfg, kalan, baseline)
            if ip is None:
                return False, "cihaz bulunamadı"
            ok, why = verify_port(ip, port, cfg)
            if ok is False:
                print(f"    [!] {ip} bu portta değil ({why}) — eleniyor")
                blocked.append(ip)
                if time.monotonic() >= end:
                    return False, "doğru porttaki cihaz bulunamadı"
                continue
            found_ip, settings = ip, st
            print(f"    cihaz bulundu: {ip}"
                  + (f"  [{why}]" if ok else f"  ({why})"))
            break

        if found_ip == target:
            print("    IP zaten doğru")
            return True, ""

        if cfg.backup_dir:
            cfg.backup_dir.mkdir(parents=True, exist_ok=True)
            bp = cfg.backup_dir / f"port{port}_{found_ip}.json"
            bp.write_text(json.dumps(settings, ensure_ascii=False, indent=2),
                          encoding="utf-8")
            print(f"    yedek: {bp.name}")

        print(f"    IP yazılıyor: {found_ip} -> {target}")
        try:
            write_ip(found_ip, settings, target, cfg)
        except requests.RequestException as exc:
            print(f"    (yazma yanıtı alınamadı: {exc.__class__.__name__} "
                  f"— reset atmış olabilir, doğrulanıyor)")

        if cfg.defer_verify:
            # Sıradaki porta geçmek bu cihazın gücünü keser. Önce yazının
            # işlendiğine dair kanıt bekleriz: cihaz eski IP'den düşmeli
            # (reset attı demektir). Sadece HTTP 200'e güvenmek yetmez.
            time.sleep(cfg.post_write_wait)
            kalan = wait_gone([found_ip], cfg, cfg.reset_wait)
            if kalan:
                print(f"    [!] {found_ip} hâlâ eski IP'de — yazma "
                      f"işlenmemiş olabilir")
                return False, f"{found_ip} reset atmadı"
            print(f"    yazıldı (reset doğrulandı), IP kontrolü sona bırakıldı")
            return True, ""

        print(f"    doğrulama: {target} bekleniyor "
              f"(reset + en fazla {cfg.confirm_wait:.0f} sn)...")
        # Hedef adresin ARP kaydı da bayat olabilir: cihaz oraya YENİ
        # taşındı, önbellekte ise başka bir cihazın MAC'i durabilir.
        arp_unut([target], cfg)
        ok_ip, _ = find_device([target], cfg, cfg.confirm_wait)
        if ok_ip == target:
            print(f"    [OK] Port {port} -> {target}")
            return True, ""
        return False, f"{target} cevap vermedi"

    done, failed = [], {}
    try:
        # Yönetilen portların hepsi kapalıyken kim cevap veriyor?
        # Bunlar yönetilmeyen portlardaki cihazlar — dokunulmamalı.
        baseline = {}
        if not cfg.dry_run:
            print("\nTemel tarama (aralıktaki portlar kapalı)...")
            poe_apply(cfg, state, set(), managed)
            time.sleep(cfg.settle)
            # PoE kesildikten sonra cihazlar hemen susmaz; oturana kadar bekle
            baseline = wait_until_quiet(candidates, cfg, cfg.baseline_wait)
            print(f"    aralık dışında {len(baseline)} cihaz açık"
                  + (f": {', '.join(baseline)}" if baseline else ""))
            if cfg.factory_ip in baseline:
                print(f"    [!] {cfg.factory_ip} (fabrika IP) aralık dışında "
                      f"cevap veriyor — yapılandırılmamış bir intercom "
                      f"başka bir portta olabilir")

        # Hepsi tamamlanana kadar tur at. Bir turda hiç ilerleme olmazsa
        # bekleme süreleri artırılır; üst üste stall-limit kadar ilerleme
        # olmazsa durulur (sonsuz döngüye girmesin).
        pending = list(ports)
        assigned: set[str] = set()      # tamamlanan hedef IP'ler — dokunulmaz
        turn, stalled = 0, 0
        while pending:
            turn += 1
            if cfg.max_passes and turn > cfg.max_passes:
                print(f"\n[!] Tur sınırına ulaşıldı ({cfg.max_passes}), "
                      f"kalan: {pending}")
                break
            if turn > 1:
                print(f"\n=== Tur {turn} — kalan portlar: {pending}"
                      f"  (bekleme: boot {cfg.boot_wait:.0f}s / "
                      f"doğrulama {cfg.confirm_wait:.0f}s) ===")

            before = len(pending)
            nxt = []
            for i, port in enumerate(pending, start=1):
                ok, err = do_port(port, baseline, f"[{i}/{len(pending)}]",
                                  assigned)
                if ok:
                    done.append(port)
                    assigned.add(plan[port]["target"])
                    failed.pop(port, None)
                else:
                    print(f"    [!] Port {port}: {err}")
                    failed[port] = err
                    nxt.append(port)
            pending = nxt

            if len(pending) < before:
                stalled = 0                      # ilerleme var, devam
                continue
            stalled += 1
            if stalled >= cfg.stall_limit:
                print(f"\n[!] {stalled} turdur ilerleme yok, duruluyor. "
                      f"Kalan: {pending}")
                break
            if cfg.retry_backoff > 1:
                # Arama pencereleri her ilerlemesiz turda uzar; link
                # beklemesi de öyle, çünkü yavaş açılan bir cihaz ikisini
                # de aşabiliyor.
                cfg.boot_wait *= cfg.retry_backoff
                cfg.confirm_wait *= cfg.retry_backoff
                cfg.find_wait *= cfg.retry_backoff
                cfg.link_wait *= cfg.retry_backoff
    except KeyboardInterrupt:
        print("\n\n[İPTAL] Kullanıcı durdurdu — portlar geri açılıyor...")
    finally:
        print(f"\nAralıktaki tüm portlar tekrar açılıyor: {ports}")
        for deneme in range(3):
            try:
                poe_apply(cfg, state, managed, managed)
                break
            except Exception as exc:
                print(f"[!] Portlar geri açılamadı ({deneme + 1}/3): "
                      f"{type(exc).__name__}")
                time.sleep(5)
        else:
            print( "[!] PORTLAR KAPALI KALMIŞ OLABİLİR — elle aç:")
            print(f"    http://{cfg.switch_ip}/poePort.html")

    # ---------------------------------------------------- son doğrulama ----
    if not cfg.dry_run:
        print(f"\nSon doğrulama ({cfg.boot_wait:.0f} sn'ye kadar "
              f"tüm cihazların açılması bekleniyor)...")
        # Portlar yeni açıldı, cihazlar yeni adreslerine oturdu; ARP
        # kayıtlarının hepsi bayat olabilir.
        arp_unut(targets, cfg)
        end = time.monotonic() + cfg.confirm_wait
        seen = {}
        while time.monotonic() < end:
            seen = probe_all(targets, cfg)      # paralel, ~1 sn
            if len(seen) == len(targets):
                break
            time.sleep(cfg.poll_interval)
        # doğrulama sona bırakıldıysa tutmayanlar hâlâ düzeltilebilir
        eksik_port = [p for p in ports if plan[p]["target"] not in seen]
        if eksik_port and cfg.defer_verify:
            print(f"    {len(eksik_port)} port doğrulanamadı, tekrar "
                  f"deneniyor: {eksik_port}")
            for p_ in eksik_port:
                failed.setdefault(p_, "son doğrulamada cevap yok")

        print(f"\n{'port':>5}  {'hedef IP':<14} durum")
        print("  " + "-" * 44)
        for port in ports:
            t = plan[port]["target"]
            if t in seen:
                print(f"{port:>5}  {t:<14} OK")
            else:
                print(f"{port:>5}  {t:<14} EKSİK — {failed.get(port, 'cevap yok')}")

        # ---------------------------------------- kalıcılık kontrolü ----
        # Ayar RAM'e yazılıp flash'a inmemişse cihaz güç kesilince eski
        # IP'sine döner. Tek kesin kanıt: hepsini bir kez güç çevirip
        # tekrar bakmak.
        if cfg.persist_check and seen:
            print("\nKalıcılık kontrolü (portlar bir kez güç çevriliyor)...")
            try:
                poe_apply(cfg, state, set(), managed)
                time.sleep(cfg.settle + 2)
                poe_apply(cfg, state, managed, managed)
            except Exception as exc:
                print(f"    [!] Güç çevrimi yapılamadı: {type(exc).__name__}")
            else:
                end = time.monotonic() + cfg.confirm_wait
                while time.monotonic() < end:
                    seen = probe_all(targets, cfg)
                    if len(seen) == len(targets):
                        break
                    time.sleep(cfg.poll_interval)
                kalici = [p for p in ports if plan[p]["target"] in seen]
                print(f"    güç çevriminden sonra {len(kalici)}/{len(ports)} "
                      f"hedef IP ayakta")
                if len(kalici) < len(ports):
                    print( "    [!] Bazı ayarlar KALICI DEĞİL — cihaz güç "
                           "kesilince eski IP'sine dönüyor.")
                    print( "        Yazma isteği kabul ediliyor ama flash'a "
                           "inmiyor olabilir; --full-net-payload ile deneyin.")

        if cfg.factory_ip not in targets:
            if read_settings(cfg.factory_ip, cfg) is not None:
                print(f"\n[!] {cfg.factory_ip} hâlâ cevap veriyor — "
                      f"yapılandırılmamış bir intercom kaldı")

        eksik = [p for p in ports if plan[p]["target"] not in seen]
        if eksik:
            print(f"\n{len(eksik)} port tamamlanmadı: {eksik}")
            print( "Sonraki adım — yalnızca bunları tekrar dene:")
            print(f"    python3 {Path(__file__).name} --ports "
                  f"{' '.join(map(str, eksik))} --boot-wait 45 --confirm-wait 60")
            print( "Cihaz hiç bulunamıyorsa açık portla birlikte kontrol et:")
            print( "    sudo arp-scan --interface=en6 -l")
            return 1
        print(f"\nHepsi tamam: {len(ports)}/{len(ports)} port")
        return 0

    print(f"\n[dry-run] {len(done)}/{len(ports)} port planlandı")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[İPTAL] Kullanıcı durdurdu.")
        print("Portların açık olduğundan emin ol: "
              "http://10.n.1.101/poePort.html")
        sys.exit(130)
