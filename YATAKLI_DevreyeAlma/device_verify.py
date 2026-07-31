#!/usr/bin/env python3
"""Yataklı — saha cihaz doğrulama.

Excel şablonunu kopyalar, sahadaki cihazlardan toplanan verilerle
"YAZILIM KONTROL" sütunlarını doldurur ve yeni bir dosya olarak kaydeder.
Şablon dosyaya asla yazılmaz.

Veri kaynakları (CIHAZ_ENDPOINTLERI.md):
  MQTT  ALFA/DeviceMap     -> bütün cihazlar için ortak alanlar
  MQTT  ALFA/AppStatus/#   -> PISCU ve HMI sürüm + donanım kimliği
  HTTP  /api/v1/system/... -> Announcement (Amplifier / Handset / Intercom)
  ISAPI /System/...        -> Camera, NVR
  HTTP  /stat/basicInfo    -> KYLAND switch
  ADB   getprop            -> LCD / Compartment

Kullanım:
    python3 device_verify.py                       # .env değerleriyle
    python3 device_verify.py -n 3                  # set no 3
    python3 device_verify.py --only Camera NVR     # sadece bu tipler
    python3 device_verify.py --dry-run             # ağa çıkma, planı göster
    python3 device_verify.py --list                # hedef IP listesini bas
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
import xml.etree.ElementTree as ET
from pathlib import Path

import openpyxl
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HERE = Path(__file__).resolve().parent

# Excel'de doldurulacak sütunların başlıkları (satır 4'ten okunur)
FILLABLE = [
    "Cihaz İsmi", "Bağlantı Bilgisi", "Versiyon", "Cihaz Numarası",
    "Durum Açıklaması", "Çalışma Süresi", "Hoparlör Ses Seviyesi",
    "Mikrofon Ses Seviyesi", "Hoparlör Gain", "Mikrofon Gain",
    "SIP PBX IP", "SIP Dahili No", "SIP Arama No",
    "Saat Dilimi", "Ağ/Zaman Kontrolü",
]
HEADER_ROW = 4
COL_IP_TEMPLATE = "IP Şablonu"
NA_FILL = "FFE7E6E6"

# cihaz yanıtlarındaki alan adları üreticiye göre değişiyor;
# pick() bu adayları sırayla dener (tam ad -> son parça eşleşmesi).
K_VERSION = ("firmwareversion", "firmware", "swversion", "softwareversion",
             "appversion", "fwversion", "version", "buildversion", "build")
K_SERIAL = ("serialnumber", "serialno", "serial", "sn", "devicesn",
            "deviceserial", "deviceid", "chipid", "uuid")
K_UPTIME = ("uptimeseconds", "uptimesec", "uptime", "systemuptime",
            "runtime", "runningtime")
K_SPEAKER = ("speakervolume", "speaker_volume", "speakerlevel", "spkvolume",
             "callvolume", "call_volume_out1", "outputvolume", "playvolume",
             "speaker", "volume")
K_MIC = ("microphonevolume", "microphone_volume", "micvolume", "mic_volume",
         "miclevel", "inputvolume", "recordvolume", "microphone", "mic")
K_SPEAKER_GAIN = ("speakergain", "speaker_gain", "spkgain", "outputgain",
                  "playgain", "amplifiergain")
K_MIC_GAIN = ("microphonegain", "microphone_gain", "micgain", "mic_gain",
              "inputgain", "recordgain")
K_OUTBOUND = ("pbxoutextension", "pbx_out_extension", "pbxoutext",
              "outextension", "out_extension", "outext",
              "outboundextension", "outbound_extension", "outboundext",
              "outbound_ext", "outboundcallextension", "outboundnumber",
              "outbound_number", "outboundcallnumber", "outboundcall",
              "call_on_input_0", "calloninput0", "destinationnumber",
              "destination", "dialnumber", "targetnumber", "callnumber",
              "callext", "outbound", "pbxout")

# Announcement cihazlarında denenecek API uçları (JSON dönen hepsi birleştirilir)
ANNOUNCEMENT_ENDPOINTS = [
    "system/settings", "system/modes", "system/info", "system/status",
    "system/sip", "system/network", "system/audio",
    "sip", "sip/settings", "sip/config", "sip/status",
    "settings", "config", "network", "audio", "status", "info",
]
K_PBX = ("pbxip", "pbx_ip", "sippbx", "sip_pbx", "pbxserver", "sipserver",
         "pbxaddress", "pbxhost", "serverip", "sipserverip", "sipproxy",
         "registrar", "proxy", "pbx", "server", "host")
K_EXTENSION = ("pbxextension", "pbx_extension", "sipextension",
               "sip_extension", "extension", "ext")


# --------------------------------------------------------------- yardımcı --
def load_env(path: Path) -> dict:
    """Basit .env okuyucu (harici bağımlılık yok)."""
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


def resolve(ip_template: str, set_no) -> str:
    """IP şablonundaki 'n' yerine set numarasını koyar.

    10.n.1.24, set 3  ->  10.3.1.24
    """
    return re.sub(r"(?<![0-9a-zA-Z])n(?![0-9a-zA-Z])", str(set_no),
                  ip_template or "")


def flatten(obj, prefix="") -> dict:
    """İç içe JSON'u {kucukharfli.anahtar: deger} sözlüğüne indirger."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}".lower()
            if isinstance(v, (dict, list)):
                out.update(flatten(v, f"{key}."))
            else:
                out[key] = v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}{i}."))
    return out


def _norm(s: str) -> str:
    """sip_outbound-Extension -> sipoutboundextension"""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def pick(flat: dict, *candidates, exclude=()):
    """Aday anahtar adlarından ilk eşleşen değeri döndürür.

    Üç aşama, gevşeyerek:
      1. tam anahtar eşleşmesi          pbxIp            -> pbxip
      2. son parça eşleşmesi            sip.pbxIp        -> pbxip
      3. alt dize eşleşmesi (>=7 harf)  data.sipOutboundExtension -> outboundextension

    `exclude` içindeki parçaları taşıyan anahtarlar 3. aşamada elenir; böylece
    "extension" araması yanlışlıkla "outboundExtension" değerini almaz.
    """
    def ok(v):
        return v not in ("", None) and str(v).strip() != ""

    for cand in candidates:                                   # 1
        v = flat.get(cand.lower())
        if ok(v):
            return v

    tails = {k: _norm(k.rsplit(".", 1)[-1]) for k in flat}
    for cand in candidates:                                   # 2
        nc = _norm(cand)
        for k, v in flat.items():
            if tails[k] == nc and ok(v):
                return v

    bad = tuple(_norm(x) for x in exclude)
    full = {k: _norm(k) for k in flat}
    for cand in candidates:                                   # 3
        nc = _norm(cand)
        if len(nc) < 7:
            continue
        for k, v in flat.items():
            nk = full[k]
            if nc in nk and ok(v) and not any(b in nk for b in bad):
                return v
    return None


def pct(v):
    if v in (None, ""):
        return None
    try:
        return f"{int(float(v))}%"
    except (TypeError, ValueError):
        return str(v)


def num(v):
    """Gain gibi sayısal alanlar — Excel'e sayı olarak yazılır (0 dahil)."""
    if v in (None, ""):
        return None
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return str(v)


def status_text(status: dict | None) -> str:
    """Aktif / Pasif. Arıza bayrakları ayrıştırılmaz.

    DeviceMap'teki 'Has Network Failure' ve 'Has Power Failure' bayrakları
    tutarlı doldurulmuyor (kapalı cihazların bir kısmında set, bir kısmında
    değil), o yüzden parantezli sebep yazmıyoruz.
    """
    if not status:
        return ""
    return "Aktif" if status.get("NoError") else "Pasif"


def uptime_text(seconds) -> str:
    """Saniyeyi SS:DD:ss biçimine çevirir (örn. 03:25:41)."""
    try:
        u = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if u < 0:
        return ""
    return f"{u // 3600:02d}:{(u % 3600) // 60:02d}:{u % 60:02d}"


def xml_tag(root, tag):
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag:
            return (el.text or "").strip()
    return None


# cihazlardan gelen ham alan adları (--debug-fields ile dosyaya yazılır)
RAW: dict = {}

# ALFA/AppStatus/... altındaki retained uygulama durumu mesajları
APP_STATUS: dict = {}          # ClientId -> payload


# ------------------------------------------------------------ toplayıcılar --
def fetch_device_map(broker: str, port: int, topic: str, timeout: float):
    """PISCU üzerindeki retained ALFA/DeviceMap mesajını okur."""
    try:
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion
    except ImportError:
        print("  [!] paho-mqtt kurulu değil, canlı DeviceMap atlanıyor "
              "(pip install paho-mqtt)")
        return None

    box, deadline = {}, timeout
    cl = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="vip_saha_dogrulama")
    cl.on_connect = lambda c, u, f, rc, p=None: c.subscribe(topic)
    cl.on_message = lambda c, u, msg: box.setdefault("payload", msg.payload)
    try:
        cl.connect(broker, port, keepalive=10)
        cl.loop_start()
        for _ in range(int(deadline * 10)):
            if "payload" in box:
                break
            time.sleep(0.1)
        cl.loop_stop()
        cl.disconnect()
    except Exception as exc:
        print(f"  [!] MQTT: {exc}")
        return None
    if "payload" not in box:
        print(f"  [!] MQTT: '{topic}' retained mesajı gelmedi")
        return None
    return json.loads(box["payload"])


def fetch_app_status(broker: str, port: int, prefix: str, timeout: float) -> dict:
    """ALFA/AppStatus/# altındaki retained uygulama mesajlarını toplar.

    Örnek yük: {"ClientId": "ClientManager_PISCU_YATAKLI_1", "DeviceIP": ...,
                "HWID": ..., "Status": ..., "Version": "1.2.7"}
    """
    try:
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion
    except ImportError:
        print("  [!] paho-mqtt kurulu değil, AppStatus okunamıyor")
        return {}


    found = {}

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload)
        except ValueError:
            return
        key = data.get("ClientId") or msg.topic.rsplit("/", 1)[-1]
        found[key] = data

    cl = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="vip_appstatus")
    cl.on_connect = lambda c, u, f, rc, p=None: c.subscribe(f"{prefix}/#")
    cl.on_message = on_message
    try:
        cl.connect(broker, port, keepalive=10)
        cl.loop_start()
        time.sleep(timeout)               # retained mesajlar hemen düşer
        cl.loop_stop()
        cl.disconnect()
    except Exception as exc:
        print(f"  [!] AppStatus MQTT: {exc}")
        return {}
    return found


def app_status_for(ip: str, keyword: str) -> dict | None:
    """Cihazın AppStatus kaydını bulur.

    Önce DeviceIP eşleşmesi. Anahtar kelimeye (ClientId) düşmek yalnızca
    mesajda DeviceIP hiç yoksa geçerli — aksi halde başka bir setin
    (ör. 10.1.1.4) kaydı bu setin satırına yazılırdı.
    """
    for data in APP_STATUS.values():
        if str(data.get("DeviceIP", "")).strip() == ip:
            return data
    kw = keyword.lower()
    for key, data in APP_STATUS.items():
        if kw in str(key).lower() and not str(data.get("DeviceIP", "")).strip():
            return data
    return None


def read_http_api(ip: str, cfg, tag: str) -> dict:
    """Cihazın /api/v1/... uçlarını gezip dönen tüm JSON'ları birleştirir.

    Bu API'yi Announcement cihazları da PISCU da sunuyor (versiyon 1.2.x).
    """
    base = f"http://{ip}:{cfg.arduino_port}/api/v1"
    endpoints = cfg.announcement_endpoints or ANNOUNCEMENT_ENDPOINTS
    flat, seen, first_error = {}, {}, None
    for endpoint in endpoints:
        try:
            r = requests.get(f"{base}/{endpoint}", timeout=cfg.timeout)
            if not r.ok:
                continue
            part = flatten(r.json())
            seen[endpoint] = part
            flat.update(part)
        except Exception as exc:
            if first_error is None:
                first_error = exc
    if not flat:                     # hiçbir uç cevap vermedi
        raise first_error or RuntimeError(f"{tag} API yanıt vermedi")
    RAW.setdefault(ip, {})[tag] = seen
    return flat


def common_http_fields(flat: dict) -> dict:
    """Her cihazda aynı olan üç alan: versiyon, seri no, uptime."""
    return {
        "Versiyon":                  pick(flat, *K_VERSION),
        "Cihaz Numarası":            pick(flat, *K_SERIAL),
        "Çalışma Süresi": uptime_text(pick(flat, *K_UPTIME)),
    }


def fetch_announcement(ip: str, cfg) -> dict:
    """Amplifier / Handset / Intercom — Arduino tabanlı HTTP API."""
    flat = read_http_api(ip, cfg, "announcement")
    return {
        "Versiyon":                  pick(flat, *K_VERSION),
        "Cihaz Numarası":            pick(flat, *K_SERIAL),
        "Çalışma Süresi": uptime_text(pick(flat, *K_UPTIME)),
        # "gain" ve "level" alanları ses seviyesiyle karışmasın diye elenir
        "Hoparlör Ses Seviyesi":     pct(pick(flat, *K_SPEAKER, exclude=("gain",))),
        "Mikrofon Ses Seviyesi":     pct(pick(flat, *K_MIC, exclude=("gain",))),
        "Hoparlör Gain":             num(pick(flat, *K_SPEAKER_GAIN)),
        "Mikrofon Gain":             num(pick(flat, *K_MIC_GAIN)),
        "SIP PBX IP":                pick(flat, *K_PBX),
        # "extension" araması outboundExtension'a kaymasın diye elemeli
        "SIP Dahili No":             pick(flat, *K_EXTENSION,
                                          exclude=("outbound", "outext",
                                                   "pbxout", "dial", "target")),
        "SIP Arama No":              pick(flat, *K_OUTBOUND),
    }


def fetch_isapi(ip: str, cfg) -> dict:
    """Camera / NVR — Hikvision ISAPI (digest auth, XML)."""
    auth = HTTPDigestAuth(cfg.video_user, cfg.video_pass)
    base = f"http://{ip}:{cfg.video_port}/ISAPI"
    out, problems = {}, []

    r = requests.get(f"{base}/System/deviceInfo", auth=auth,
                     timeout=cfg.timeout, verify=False)
    root = ET.fromstring(r.content)
    out["Versiyon"] = xml_tag(root, "firmwareVersion")
    out["Cihaz Numarası"] = xml_tag(root, "serialNumber")

    try:
        r = requests.get(f"{base}/System/time", auth=auth,
                         timeout=cfg.timeout, verify=False)
        if xml_tag(ET.fromstring(r.content), "timeZone") != cfg.expected_tz:
            problems.append("Saat")
    except Exception:
        problems.append("Saat")

    try:
        r = requests.get(f"{base}/System/time/ntpServers/1", auth=auth,
                         timeout=cfg.timeout, verify=False)
        if xml_tag(ET.fromstring(r.content), "ipAddress") != cfg.ntp_ip:
            problems.append("NTP")
    except Exception:
        problems.append("NTP")

    try:
        r = requests.get(f"{base}/System/Network/interfaces", auth=auth,
                         timeout=cfg.timeout, verify=False)
        root = ET.fromstring(r.content)
        mask = None
        for el in root.iter():
            if el.tag.rsplit("}", 1)[-1] == "IPAddress":
                addr = sub = None
                for ch in el:
                    tag = ch.tag.rsplit("}", 1)[-1]
                    if tag == "ipAddress":
                        addr = (ch.text or "").strip()
                    elif tag == "subnetMask":
                        sub = (ch.text or "").strip()
                if addr and addr.startswith("10."):
                    mask = sub
                    break
        if mask != cfg.expected_mask:
            problems.append("Maske")
    except Exception:
        problems.append("Maske")

    out["Ağ/Zaman Kontrolü"] = "Uygun" if not problems else ", ".join(problems)
    return out


def fetch_switch(ip: str, cfg) -> dict:
    """KYLAND switch — HTTP basic auth."""
    r = requests.get(f"http://{ip}:{cfg.kyland_port}/stat/basicInfo",
                     auth=HTTPBasicAuth(cfg.kyland_user, cfg.kyland_pass),
                     timeout=cfg.timeout)
    r.raise_for_status()
    try:
        flat = flatten(r.json())
    except ValueError:                       # JSON değilse ham metni ayrıştır
        flat = flatten(dict(re.findall(r'"?([A-Za-z_]+)"?\s*[:=]\s*"?([^",\n}]+)',
                                       r.text)))
    RAW.setdefault(ip, {})["switch"] = flat
    out = common_http_fields(flat)
    out.pop("Cihaz Numarası", None)      # switch seri no'su toplanmıyor (gri)
    return out


def app_status_fields(ip: str, cfg, keyword: str) -> dict:
    """ALFA/AppStatus mesajından yazılım sürümü ve donanım kimliği.

    Uygulama çalıştıran cihazlar (PISCU, HMI) kendi durumlarını buraya
    yayınlıyor:
      ClientManager_PISCU_YATAKLI_1  ip=10.n.1.1  v=1.2.7  hwid=604A17F3
      ClientManager_MCP_YATAKLI_1    ip=10.n.1.4  v=1.2.5  hwid=34DA8534
    """
    rec = app_status_for(ip, keyword)
    if not rec:
        raise RuntimeError(f"{cfg.app_status_prefix}/... altında {keyword} "
                           f"mesajı bulunamadı")
    RAW.setdefault(ip, {})[f"appstatus_{keyword.lower()}"] = rec
    return {
        "Versiyon":       rec.get("Version"),
        "Cihaz Numarası": rec.get("HWID"),
    }


def fetch_piscu(ip: str, cfg) -> dict:
    """PISCU — ClientManager_PISCU_* uygulama durumu."""
    return app_status_fields(ip, cfg, "PISCU")


def fetch_hmi(ip: str, cfg) -> dict:
    """HMI — ClientManager_MCP_* uygulama durumu (SSH gerekmiyor)."""
    return app_status_fields(ip, cfg, "MCP")


def _adb(target: str, *args, timeout: int) -> str:
    r = subprocess.run(["adb", "-s", target, *args],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def fetch_compartment_lcd(ip: str, cfg) -> dict:
    """LCD / Compartment — Android, ADB üzerinden."""
    target = f"{ip}:{cfg.adb_port}"
    subprocess.run(["adb", "connect", target], capture_output=True,
                   text=True, timeout=cfg.adb_timeout)
    try:
        # NOT: "Versiyon" şimdilik toplanmıyor — şablonda gri.
        # ro.build.display.id Android build kimliği (C33P-V1.5-...),
        # DeviceMap Status.Version ise doğru kaynak değil. Uygulama
        # sürümünün nereden okunacağı netleşince buraya eklenecek.
        out = {
            "Cihaz Numarası": _adb(target, "shell", "getprop", "ro.serialno",
                                   timeout=cfg.adb_timeout),
            "Saat Dilimi":    _adb(target, "shell", "getprop", "persist.sys.timezone",
                                   timeout=cfg.adb_timeout),
        }
        raw = _adb(target, "shell", "cat", "/proc/uptime", timeout=cfg.adb_timeout)
        if raw:
            out["Çalışma Süresi"] = uptime_text(raw.split()[0])
        return {k: v for k, v in out.items() if v}
    finally:
        subprocess.run(["adb", "disconnect", target], capture_output=True,
                       text=True, timeout=cfg.adb_timeout)


# hangi tip hangi toplayıcıyı kullanır (DeviceMap dışı ek sorgu)
COLLECTORS = {
    ("Switch", None):              fetch_switch,
    ("PISCU", None):               fetch_piscu,
    ("HMI", None):                 fetch_hmi,
    ("Announcement", "Amplifier"): fetch_announcement,
    ("Announcement", "Handset"):   fetch_announcement,
    ("Announcement", "Intercom"):  fetch_announcement,
    ("Camera", "Corridor"):        fetch_isapi,
    ("Camera", "Landing"):         fetch_isapi,
    ("NVR", None):                 fetch_isapi,
    ("LCD", "Compartment"):        fetch_compartment_lcd,
}
# yalnızca DeviceMap'ten beslenenler: PISCU, ICU, HMI, AP, LED, LCD/Landing, UIC


# ------------------------------------------------------------------- akış --
def build_index(device_map: dict) -> dict:
    """IP şablonu -> cihaz kaydı."""
    idx = {}
    for sw in device_map.get("Switches", []) or []:
        idx.setdefault("__trainset__", sw.get("TrainSet"))
        idx[sw.get("IP", "")] = {
            "Name": sw.get("Name", ""), "Type": "Switch", "SubType": None,
            "Status": sw.get("Status", {}), "SerialNumber": sw.get("SerialNumber", ""),
            "PBXExtension": None,
        }
        for dv in sw.get("Devices", []) or []:
            idx[dv.get("IP", "")] = {
                "Name": dv.get("Name", ""), "Type": dv.get("Type", ""),
                "SubType": dv.get("SubType") or None,
                "Status": dv.get("Status", {}),
                "SerialNumber": dv.get("SerialNumber", ""),
                "PBXExtension": dv.get("PBXExtension") or None,
            }
    return idx


def map_train_set(index: dict):
    """DeviceMap'in hangi sete ait olduğunu döndürür (yoksa None)."""
    return index.get("__trainset__")


def devices_only(index: dict) -> dict:
    return {k: v for k, v in index.items() if k != "__trainset__"}


def remove_file(path: Path, tries: int = 4) -> bool:
    """Dosyayı ısrarla siler. Açık dosyayı silmeyen sistemlerde önce
    yeniden adlandırıp öyle siler; başarısızsa boyutunu sıfırlar."""

    for attempt in range(tries):
        if not path.exists():
            return True
        try:
            path.unlink()
            return True
        except OSError:
            pass
        try:                                  # kilitli dosyayı kenara al
            tmp = path.with_name(f"{path.name}.eski{os.getpid()}{attempt}")
            path.rename(tmp)
            try:
                tmp.unlink()
            except OSError:
                pass
            return True
        except OSError:
            time.sleep(0.3)
    try:                                      # son çare: içeriği boşalt
        with open(path, "wb"):
            pass
        return True
    except OSError:
        return False


def clear_output(cfg, out_path: Path) -> bool:
    """Çıktıyı ve varsa ofis kilit dosyalarını temizler."""
    for lock in (out_path.with_name(f".~lock.{out_path.name}#"),
                 out_path.with_name(f"~${out_path.name}")):
        if lock.exists():
            remove_file(lock)
    if remove_file(out_path):
        return True
    print(f"\n[HATA] Eski çıktı silinemedi: {out_path.name}")
    print( "       Dosya Excel / LibreOffice'te açık olabilir.")
    print( "       Kapatıp scripti tekrar çalıştır.")
    return False


def prepare_output(cfg, n) -> Path | None:
    """Çıktı yolunu belirler ve eski dosyayı baştan siler.

    Ağa çıkmadan önce çağrılır — dosya silinemiyorsa 3 dakika bekleyip
    en sonda hata almak yerine hemen anlaşılır.
    """
    out_path = cfg.output or cfg.template.with_name(
        f"{cfg.template.stem}_set{n}{cfg.template.suffix}")
    if cfg.dry_run or cfg.list:
        return out_path
    return out_path if clear_output(cfg, out_path) else None


def parse_args(env: dict):
    p = argparse.ArgumentParser(
        description="Yataklı saha cihaz doğrulama — Excel doldurucu",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    g = p.add_argument_group("dosyalar")
    g.add_argument("--template", type=Path,
                   default=HERE / "Yatakli_Saha_Cihaz_Dogrulama.xlsx",
                   help="Şablon Excel (asla üzerine yazılmaz)")
    g.add_argument("--output", type=Path, default=None,
                   help="Çıktı dosyası (varsayılan: şablon_set<N>.xlsx, "
                        "varsa üzerine yazılır)")
    g.add_argument("--device-map", type=Path,
                   default=Path(env.get("DEVICE_MAP_FILE") or HERE / "DeviceMap.json"),
                   help="Yerel DeviceMap.json")
    g.add_argument("--sheet", default="Kontrol Listesi")

    g = p.add_argument_group("set / ağ")
    g.add_argument("-n", "--set", dest="set_no",
                   default=env.get("TRAIN_SET_NO", "1"),
                   help="Set numarası — IP şablonundaki 'n' (2. oktet)")
    g.add_argument("--piscu-ip", default=None,
                   help="MQTT broker IP (varsayılan: DeviceMap'teki PISCU)")
    g.add_argument("--mqtt-port", type=int, default=int(env.get("PISCU_MQTT_PORT", 1883)))
    g.add_argument("--mqtt-topic", default=env.get("PISCU_DEVICE_MAP_TOPIC", "ALFA/DeviceMap"))
    g.add_argument("--app-status-prefix",
                   default=env.get("PISCU_APP_STATUS_PREFIX", "ALFA/AppStatus"),
                   help="Uygulama durumu topic öneki")
    g.add_argument("--app-status-timeout", type=float, default=3.0)
    g.add_argument("--no-mqtt", action="store_true",
                   help="Canlı DeviceMap çekme, yerel dosyayı kullan")

    g = p.add_argument_group("portlar / kimlik")
    g.add_argument("--arduino-port", type=int, default=int(env.get("ARDUINO_HTTP_PORT", 80)))
    g.add_argument("--video-port", type=int, default=int(env.get("VIDEO_HTTP_PORT", 80)))
    g.add_argument("--kyland-port", type=int, default=int(env.get("KYLAND_HTTP_PORT", 80)))
    g.add_argument("--adb-port", type=int, default=int(env.get("COMPARTMENT_LCD_ADB_PORT", 5555)))
    g.add_argument("--video-user", default=env.get("VIDEO_USERNAME", "admin"))
    g.add_argument("--video-pass", default=env.get("VIDEO_PASSWORD", ""))
    g.add_argument("--kyland-user", default=env.get("KYLAND_USERNAME", "admin"))
    g.add_argument("--kyland-pass", default=env.get("KYLAND_PASSWORD", ""))

    g = p.add_argument_group("beklenen değerler")
    g.add_argument("--expected-tz", default=env.get("EXPECTED_TIMEZONE", "CST-3:00:00"),
                   help="Kamera/NVR saat dilimi")
    g.add_argument("--ntp-ip", default=None,
                   help="Beklenen NTP sunucusu (varsayılan: PISCU IP)")
    # Yataklı cihazları 255.255.0.0 bildiriyor (Gaziray'da 255.0.0.0 idi).
    g.add_argument("--expected-mask",
                   default=env.get("EXPECTED_SUBNET_MASK", "255.255.0.0"),
                   help="Kamera/NVR için beklenen subnet mask")

    g = p.add_argument_group("çalışma")
    g.add_argument("--timeout", type=float, default=5.0, help="HTTP zaman aşımı (sn)")
    g.add_argument("--adb-timeout", type=int, default=15)
    g.add_argument("--mqtt-timeout", type=float, default=5.0)
    g.add_argument("--workers", type=int, default=12, help="Eşzamanlı sorgu sayısı")
    g.add_argument("--only", nargs="+", metavar="TIP",
                   help="Sadece bu Type değerleri sorgulansın (örn. Camera NVR)")
    g.add_argument("--skip", nargs="+", metavar="TIP", default=[],
                   help="Bu Type değerleri atlansın")
    g.add_argument("--dry-run", action="store_true", help="Ağa çıkma, planı göster")
    g.add_argument("--list", action="store_true", help="Hedef IP listesini bas ve çık")
    g.add_argument("--debug-fields", action="store_true",
                   help="Cihazlardan gelen ham alan adlarını JSON olarak kaydet")
    g.add_argument("--announcement-endpoints", nargs="+", metavar="YOL",
                   default=None,
                   help="Announcement cihazlarında denenecek /api/v1/<yol> "
                        f"uçları (varsayılan: {' '.join(ANNOUNCEMENT_ENDPOINTS)})")

    return p.parse_args()
def main() -> int:
    env = load_env(HERE / ".env")
    env.update({k: v for k, v in os.environ.items() if k in env})
    cfg = parse_args(env)

    if not cfg.template.exists():
        print(f"[HATA] Şablon bulunamadı: {cfg.template}")
        return 1
    if not cfg.device_map.exists():
        print(f"[HATA] DeviceMap bulunamadı: {cfg.device_map}")
        return 1

    n = cfg.set_no
    local_map = json.loads(cfg.device_map.read_text(encoding="utf-8"))
    index = build_index(local_map)
    map_is_live = False              # telemetri bu sete mi ait?

    # PISCU / NTP varsayılanları
    piscu_tmpl = next((ip for ip, d in devices_only(index).items()
                       if d["Type"] == "PISCU"), None)
    cfg.piscu_ip = cfg.piscu_ip or (resolve(piscu_tmpl, n) if piscu_tmpl else None)
    cfg.ntp_ip = cfg.ntp_ip or cfg.piscu_ip

    print(f"Set no           : {n}")
    print(f"PISCU / broker   : {cfg.piscu_ip}")
    print(f"Şablon           : {cfg.template.name}")
    print(f"DeviceMap        : {cfg.device_map.name}  "
          f"({len(devices_only(index))} kayıt, set "
          f"{map_train_set(index) or '?'})")

    # Çıktı dosyasını en baştan hazırla — açıksa boşuna ağa çıkma
    out_path = prepare_output(cfg, n)
    if out_path is None:
        return 1
    if not (cfg.dry_run or cfg.list):
        print(f"Çıktı            : {out_path.name}")

    # 1) canlı DeviceMap
    if not cfg.no_mqtt and not cfg.dry_run and not cfg.list and cfg.piscu_ip:
        print("\n[1/3] Canlı DeviceMap (MQTT)...")
        live = fetch_device_map(cfg.piscu_ip, cfg.mqtt_port,
                                cfg.mqtt_topic, cfg.mqtt_timeout)
        if live:
            index = build_index(live)
            ts = map_train_set(index)
            print(f"  -> {len(devices_only(index))} kayıt alındı "
                  f"(set {ts or '?'})")
            if ts is not None and str(ts) != str(n):
                print(f"  [!] Broker set {ts} bildiriyor, istenen {n}. "
                      f"Telemetri kullanılmayacak.")
            else:
                map_is_live = True
        else:
            print("  -> canlı telemetri yok")

        APP_STATUS.update(fetch_app_status(cfg.piscu_ip, cfg.mqtt_port,
                                           cfg.app_status_prefix,
                                           cfg.app_status_timeout))
        print(f"  AppStatus: {len(APP_STATUS)} uygulama mesajı "
              f"({cfg.app_status_prefix}/#)")
        for key, data in sorted(APP_STATUS.items()):
            print(f"    · {key:<34} ip={data.get('DeviceIP', '—'):<12} "
                  f"v={data.get('Version', '—'):<8} "
                  f"hwid={data.get('HWID', '—'):<12} {data.get('Status', '')}")

    # 2) Şablonu belleğe al — dosyaya ancak en sonda dokunulur
    wb = openpyxl.load_workbook(cfg.template)
    ws = wb[cfg.sheet]

    col = {ws.cell(HEADER_ROW, c).value: c
           for c in range(1, ws.max_column + 1) if ws.cell(HEADER_ROW, c).value}
    missing = [h for h in FILLABLE + [COL_IP_TEMPLATE] if h not in col]
    if missing:
        print(f"[HATA] Şablonda bulunamayan sütun: {missing}")
        return 1

    # 3) hedefleri çıkar
    targets = []
    for row in range(HEADER_ROW + 1, ws.max_row + 1):
        tmpl = ws.cell(row, col[COL_IP_TEMPLATE]).value
        if not tmpl or not str(tmpl).startswith("10."):
            continue
        dev = index.get(str(tmpl))
        if not dev:
            continue
        typ, sub = dev["Type"], dev["SubType"]
        if cfg.only and typ not in cfg.only:
            continue
        if typ in cfg.skip:
            continue
        targets.append((row, str(tmpl), resolve(str(tmpl), n), dev))

    if cfg.list or cfg.dry_run:
        print(f"\nHedefler ({len(targets)}):")
        for row, tmpl, ip, dev in targets:
            fn = COLLECTORS.get((dev["Type"], dev["SubType"]))
            src = fn.__name__.replace("fetch_", "") if fn else "sadece DeviceMap"
            kind = f"{dev['Type']}/{dev['SubType'] or '-'}"
            print(f"  satır {row:>3}  {ip:<14} {kind:<26} "
                  f"{dev['Name']:<22} <- {src}")
        print(f"\nÇıktı olacaktı: {out_path.name}")
        return 0

    # 4) ortak alanlar (DeviceMap) + türe özel sorgular
    print(f"\n[2/3] {len(targets)} cihaz sorgulanıyor "
          f"({cfg.workers} eşzamanlı)...")

    def work(target):
        row, tmpl, ip, dev = target
        # Cihaz İsmi kimlik bilgisidir, her zaman yazılır.
        values = {"Cihaz İsmi": dev["Name"]}

        # Status alanları YALNIZCA telemetri bu sete aitse yazılır.
        # Aksi halde başka bir setin (ör. 10.1.1.x) verisi 10.2.1.x
        # satırlarına sızar.
        if map_is_live:
            status = dev.get("Status") or {}
            values["Durum Açıklaması"] = status_text(status)
            # PISCU, kapalı cihazların SON BİLİNEN sürüm/seri/uptime
            # değerlerini hatırlar. Bunlar o anki gerçeği yansıtmadığı için
            # yalnızca cihaz Aktif'ken yazılır — aksi halde bağlı olmayan
            # bir intercom sürüm bildiriyormuş gibi görünür.
            if status.get("NoError"):
                values.update({
                    "Bağlantı Bilgisi": ip,
                    "Cihaz Numarası":   dev.get("SerialNumber") or "",
                    "Çalışma Süresi":   uptime_text(status.get("Uptime")),
                    "Versiyon":         status.get("Version") or "",
                })
        # NOT: DeviceMap'teki PBXExtension bir *tanım* değeridir, cihazdan
        # okunmuş değer değil. Şablonda "Beklenen SIP Dahili No" sütununda
        # durur; buraya yalnızca cihazın kendi bildirdiği değer yazılır.
        fn = COLLECTORS.get((dev["Type"], dev["SubType"]))
        err = None
        if fn:
            try:
                got = fn(ip, cfg) or {}
                if any(v not in (None, "") for v in got.values()):
                    values["Bağlantı Bilgisi"] = ip     # cihaz gerçekten cevapladı
                for k, v in got.items():
                    if v not in (None, ""):
                        values[k] = v
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
        return row, ip, dev, values, err

    results, errors = [], []
    with cf.ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        for row, ip, dev, values, err in pool.map(work, targets):
            results.append((row, values))
            if err:
                errors.append((ip, dev["Name"], err))

    # 5) Excel'e yaz — yalnızca o tür için geçerli sütunlara
    written = 0
    for row, values in results:
        for header, value in values.items():
            if header not in FILLABLE or value in (None, ""):
                continue
            cell = ws.cell(row, col[header])
            if (cell.fill and cell.fill.fgColor
                    and cell.fill.fgColor.rgb == NA_FILL):
                continue                     # gri = bu tür için geçersiz alan
            cell.value = value
            written += 1

    # 6) ağ taraması — eşleşmeyen cihazlar
    # 6) yazmadan hemen önce dosyayı tekrar sil, sonra sıfırdan oluştur
    if not clear_output(cfg, out_path):
        return 1
    wb.save(out_path)

    if cfg.debug_fields:
        dbg = out_path.with_suffix(".alanlar.json")
        dbg.write_text(json.dumps(RAW, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        print(f"  ham alan adları -> {dbg.name}")

    print(f"\n[3/3] Kaydedildi: {out_path.name}")
    print(f"  {len(results)} satır, {written} hücre dolduruldu")
    if errors:
        print(f"  {len(errors)} cihaza ulaşılamadı:")
        for ip, name, err in errors:
            print(f"    - {ip:<14} {name:<22} {err[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
