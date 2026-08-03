#!/usr/bin/env python3
"""Sahte KYLAND switch — Switch Yönetim Paneli'ni switch olmadan denemek için.

Gerçek switch'in HTTP API'sini taklit eder: aynı yollar, aynı alan adları,
aynı Basic Auth. Panel karşısında gerçek cihazdan ayırt edemez.

Neleri gerçekten taklit eder:
  • 24 PoE portu (FE) + 2 uplink portu (GE)
  • PoE kapatılınca o porttaki cihazın linki düşer, tüketimi sıfırlanır
  • Port kapatılınca (adminStat) link düşer
  • "Çalışan yapılandırma" ile "kayıtlı yapılandırma" ayrıdır:
    configSave yapmadan yeniden başlatırsan değişiklikler geri alınır
  • Yeniden başlatma sırasında cihaz bir süre cevap vermez
  • Fabrika ayarları her şeyi varsayılana döndürür

Çalıştırma:
    python3 sahte_switch.py                 # 127.0.0.1:8080
    python3 sahte_switch.py --adet 3        # 127.0.0.1, .2, .3
    python3 sahte_switch.py --gecikme 400   # her isteğe 400 ms gecikme
    python3 sahte_switch.py --hata-orani .2 # yazma isteklerinin %20'si patlasın

Panelin bunu bulması için Interface/.env içinde:
    SWITCH_USERNAME=admin
    SWITCH_PASSWORD=admin
    SWITCH_HTTP_PORT=8080
Panelde tarama kutusuna tek IP yaz: 127.0.0.1
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import random
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Cihaz 28 konnektörlü: 24 PoE (4 pinli M12) + 4 uplink (8 pinli M12)
POE_PORT_SAYISI = 24        # FE, PoE veren portlar — 4 pinli
UPLINK_PORT_SAYISI = 4      # GE, uplink — 8 pinli
POE_AD = {"0": "Kapalı", "1": "PoE", "2": "PoE+"}


# --------------------------------------------------------------- durum ----
def varsayilan_yapilandirma(sira: int) -> dict:
    """Fabrika çıkışı + sahada kurulmuş gibi bir başlangıç durumu."""
    portlar = {}
    for pid in range(1, POE_PORT_SAYISI + 1):
        portlar[pid] = {"adminStat": 1, "speed": "100", "autoNego": 1,
                        "duplex": 1, "flowCtrl": 0, "maxLength": "1522",
                        "linkType": "0", "poeMode": "1", "priority": "0",
                        "maxPower": "154"}
    for pid in range(POE_PORT_SAYISI + 1, POE_PORT_SAYISI + UPLINK_PORT_SAYISI + 1):
        portlar[pid] = {"adminStat": 1, "speed": "1000", "autoNego": 1,
                        "duplex": 1, "flowCtrl": 0, "maxLength": "1522",
                        "linkType": "0"}
    return {
        "ad": f"KYLAND-{sira:02d}",
        "model": "SICOM3024P",
        "surum": "V3.6.2",
        "mac": f"00:1E:CD:{sira:02X}:4B:{sira * 7 % 256:02X}",
        "ag": {"method": "manual", "addr": f"127.0.0.{sira}",
               "netmaskLen": "8", "mtu": "1500"},
        "portlar": portlar,
    }


class SahteSwitch:
    """Tek bir switch'in durumu. Her istek bunun üzerinden cevaplanır."""

    def __init__(self, sira: int, takili: set[int]):
        self.sira = sira
        self.takili = takili            # cihaz bağlı PoE portları
        self.calisan = varsayilan_yapilandirma(sira)
        self.kayitli = copy.deepcopy(self.calisan)
        self.kilit = threading.Lock()
        self.kapali_kadar = 0.0         # yeniden başlatma bitiş zamanı
        # her portun tüketimi sabit kalsın ki ekran zıplamasın
        self.tuketim = {pid: random.randint(28, 76) for pid in takili}

    # ------------------------------------------------------- yardımcılar --
    def kapali_mi(self) -> bool:
        return time.time() < self.kapali_kadar

    def link_var_mi(self, pid: int) -> bool:
        """Port fiziksel olarak bağlı görünüyor mu?

        PoE portundaki cihaz gücünü switch'ten alıyor: PoE kapalıysa cihaz
        kapanır, link de düşer. Uplink portu kendi beslendiği için yalnızca
        port kapatılınca düşer.
        """
        p = self.calisan["portlar"][pid]
        if not p["adminStat"]:
            return False
        if pid <= POE_PORT_SAYISI:
            return pid in self.takili and p["poeMode"] != "0"
        # 4 uplinkten yalnızca ikisi kablolu; kalanı boş dursun
        return pid in (POE_PORT_SAYISI + 1, POE_PORT_SAYISI + 2)

    def port_listesi(self) -> list[dict]:
        out = []
        for pid, p in sorted(self.calisan["portlar"].items()):
            up = self.link_var_mi(pid)
            hiz = p["speed"]
            out.append({
                "pid": pid,
                "type": "fe" if pid <= POE_PORT_SAYISI else "ge",
                "adminStat": p["adminStat"],
                "linkStat": "up" if up else "down",
                "linktext": f"{hiz}M Full" if up else "",
                "speed": hiz,
                "autoNego": p["autoNego"],
                "duplex": p["duplex"],
                "flowCtrl": p["flowCtrl"],
                "maxLength": p["maxLength"],
                "linkType": p["linkType"],
            })
        return out

    def poe_listesi(self) -> list[dict]:
        return [{"pid": pid, "poeMode": p["poeMode"], "priority": p["priority"],
                 "maxPower": p["maxPower"]}
                for pid, p in sorted(self.calisan["portlar"].items())
                if pid <= POE_PORT_SAYISI]

    def poe_durum(self) -> list[dict]:
        out = []
        for pid in range(1, POE_PORT_SAYISI + 1):
            besleniyor = self.link_var_mi(pid)
            out.append({
                "pid": pid,
                # gerçek cihaz watt'ın onda biri cinsinden döndürüyor
                "powerUsed": str(self.tuketim.get(pid, 0)) if besleniyor else "0",
                "portStatus": "Delivering Power" if besleniyor else "Searching",
            })
        return out

    # ------------------------------------------------------------ yazma --
    def poe_yaz(self, form: dict) -> list[str]:
        degisen = []
        for pid in range(1, POE_PORT_SAYISI + 1):
            yeni = form.get(f"mode_{pid}", [None])[0]
            if yeni is None:
                continue
            eski = self.calisan["portlar"][pid]["poeMode"]
            if yeni != eski:
                degisen.append(f"port {pid}: {POE_AD.get(eski, eski)} -> "
                               f"{POE_AD.get(yeni, yeni)}")
            self.calisan["portlar"][pid]["poeMode"] = yeni
            for alan, anahtar in (("priority", "priority"),
                                  ("maxPower", "maxPower")):
                v = form.get(f"{alan}_{pid}", [None])[0]
                if v is not None:
                    self.calisan["portlar"][pid][anahtar] = v
        return degisen

    def port_yaz(self, form: dict) -> list[str]:
        """portMode POST'u: adminStat_N yoksa o port KAPALI demektir."""
        degisen = []
        for pid in self.calisan["portlar"]:
            yeni = 1 if f"adminStat_{pid}" in form else 0
            eski = self.calisan["portlar"][pid]["adminStat"]
            if yeni != eski:
                degisen.append(f"port {pid}: "
                               f"{'Açık' if eski else 'Kapalı'} -> "
                               f"{'Açık' if yeni else 'Kapalı'}")
            self.calisan["portlar"][pid]["adminStat"] = yeni
            for alan in ("speed", "maxLength", "linkType"):
                v = form.get(f"{alan}_{pid}", [None])[0]
                if v is not None:
                    self.calisan["portlar"][pid][alan] = v
            for bayrak in ("autoNego", "duplex", "flowCtrl"):
                self.calisan["portlar"][pid][bayrak] = \
                    1 if f"{bayrak}_{pid}" in form else 0
        return degisen

    def ag_yaz(self, form: dict) -> str:
        ag = self.calisan["ag"]
        eski = ag["addr"]
        for k in ("method", "addr", "netmaskLen", "mtu"):
            v = form.get(k, [None])[0]
            if v is not None:
                ag[k] = v
        return f"{eski} -> {ag['addr']}"

    def kaydet(self) -> None:
        self.kayitli = copy.deepcopy(self.calisan)

    def yeniden_baslat(self, sure: float) -> None:
        # kaydedilmemiş değişiklikler uçar — gerçek cihazdaki gibi
        self.calisan = copy.deepcopy(self.kayitli)
        self.kapali_kadar = time.time() + sure

    def fabrika(self, sure: float) -> None:
        self.calisan = varsayilan_yapilandirma(self.sira)
        self.kayitli = copy.deepcopy(self.calisan)
        self.kapali_kadar = time.time() + sure


# ----------------------------------------------------------------- HTTP ---
class Handler(BaseHTTPRequestHandler):
    server_version = "KYLAND/3.6.2"
    sw: SahteSwitch = None          # sunucu kurulurken atanır
    ayar: argparse.Namespace = None

    def log_message(self, *a):      # kendi kaydımızı tutuyoruz
        pass

    def yaz(self, kod: int, govde: dict):
        b = json.dumps(govde).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def kimlik_ok(self) -> bool:
        bek = base64.b64encode(
            f"{self.ayar.kullanici}:{self.ayar.sifre}".encode()).decode()
        return self.headers.get("Authorization", "") == "Basic " + bek

    def hazirla(self) -> bool:
        """Ortak kapılar: kapalı mı, kimlik doğru mu, gecikme, rastgele hata."""
        if self.sw.kapali_mi():
            kalan = self.sw.kapali_kadar - time.time()
            self.kayit(f"(kapalı — {kalan:.0f} sn sonra açılıyor)")
            self.yaz(503, {"error": "device is rebooting"})
            return False
        if not self.kimlik_ok():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="KYLAND"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            self.kayit("401 — kimlik hatalı")
            return False
        if self.ayar.gecikme:
            time.sleep(self.ayar.gecikme / 1000)
        return True

    def kayit(self, not_="") -> None:
        print(f"[{time.strftime('%H:%M:%S')}] "
              f"{self.sw.calisan['ag']['addr']}  {self.command:4} "
              f"{self.path:32} {not_}", flush=True)

    # ------------------------------------------------------------- GET ---
    def do_GET(self):
        if not self.hazirla():
            return
        yol = urllib.parse.urlparse(self.path).path.strip("/")
        sw = self.sw
        with sw.kilit:
            if yol == "stat/basicInfo":
                cevap = {"basicInfo": {
                    "deviceName": sw.calisan["ad"],
                    "deviceType": sw.calisan["model"],
                    "softVer": sw.calisan["surum"],
                    "macAddress": sw.calisan["mac"]}}
            elif yol == "stat/vlanIntfIp":
                cevap = {"vlanIntfIp": dict(sw.calisan["ag"])}
            elif yol == "stat/portMode":
                cevap = {"portMode": sw.port_listesi()}
            elif yol == "stat/poePort":
                cevap = {"poePort": sw.poe_listesi()}
            elif yol == "stat/poeStatus":
                cevap = {"poeStatus": sw.poe_durum()}
            elif yol == "stat/macQuery":
                cevap = {"macQuery": [
                    {"mac": f"AA:BB:CC:00:{pid:02X}:01", "pid": pid, "vlan": "1"}
                    for pid in sorted(sw.takili) if sw.link_var_mi(pid)]}
            else:
                self.kayit("404")
                return self.yaz(404, {"error": "not found"})
        self.kayit()
        self.yaz(200, cevap)

    # ------------------------------------------------------------ POST ---
    def do_POST(self):
        if not self.hazirla():
            return
        n = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(n).decode() if n else "")
        yol = urllib.parse.urlparse(self.path).path.strip("/")
        sw = self.sw

        if self.ayar.hata_orani and random.random() < self.ayar.hata_orani:
            self.kayit("!! rastgele hata (--hata-orani)")
            return self.yaz(500, {"error": "internal error"})

        with sw.kilit:
            if yol == "stat/poePort":
                d = sw.poe_yaz(form)
                self.kayit("PoE: " + (", ".join(d) if d else "değişiklik yok"))
            elif yol == "stat/portMode":
                d = sw.port_yaz(form)
                self.kayit("Port: " + (", ".join(d) if d else "değişiklik yok"))
            elif yol == "stat/vlanIntfIp":
                self.kayit("IP: " + sw.ag_yaz(form))
            elif yol == "stat/configSave":
                sw.kaydet()
                self.kayit("yapılandırma kaydedildi (kalıcı)")
            elif yol == "stat/reboot":
                self.kayit(f"YENİDEN BAŞLIYOR ({self.ayar.acilis} sn)")
                sw.yeniden_baslat(self.ayar.acilis)
            elif yol == "stat/reset":
                self.kayit(f"FABRİKA AYARLARI ({self.ayar.acilis} sn)")
                sw.fabrika(self.ayar.acilis)
            else:
                self.kayit("404")
                return self.yaz(404, {"error": "not found"})
        self.yaz(200, {"retCode": ["success"]})


# ----------------------------------------------------------------- main ---
def env_oku() -> dict:
    """Panelin .env'ini bulup kullanıcı/şifreyi oradan alır (aynı olsun diye)."""
    for klasor in (HERE, *list(HERE.parents)[:3]):
        p = klasor / ".env"
        if p.exists():
            out = {}
            for satir in p.read_text(encoding="utf-8").splitlines():
                satir = satir.strip()
                if satir and not satir.startswith("#") and "=" in satir:
                    k, v = satir.split("=", 1)
                    out[k.strip()] = v.strip().strip('"').strip("'")
            return out
    return {}


def main() -> int:
    # çıktı bir dosyaya/boruya yönlendirilse de anında görünsün
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    env = env_oku()
    ap = argparse.ArgumentParser(
        description="Switch Yönetim Paneli için sahte KYLAND switch")
    ap.add_argument("--adet", type=int, default=1,
                    help="kaç switch (127.0.0.1, .2, .3 …)")
    ap.add_argument("--port", type=int,
                    default=int(env.get("SWITCH_HTTP_PORT", 8080)))
    ap.add_argument("--kullanici", default=env.get("SWITCH_USERNAME", "admin"))
    ap.add_argument("--sifre", default=env.get("SWITCH_PASSWORD", "admin"))
    ap.add_argument("--gecikme", type=int, default=0,
                    help="her isteğe eklenecek gecikme (ms) — yükleme "
                         "göstergelerini denemek için")
    ap.add_argument("--hata-orani", type=float, default=0.0,
                    help="yazma isteklerinin ne kadarı hata dönsün (0-1)")
    ap.add_argument("--acilis", type=float, default=15,
                    help="yeniden başlatmada kaç sn cevapsız kalsın")
    ap.add_argument("--bos-portlar", default="9,10,17,18,19,20,21,22,23,24",
                    help="cihaz TAKILI OLMAYAN PoE portları")
    a = ap.parse_args()

    bos = {int(x) for x in a.bos_portlar.split(",") if x.strip().isdigit()}
    takili = {p for p in range(1, POE_PORT_SAYISI + 1)} - bos

    sunucular = []
    for sira in range(1, a.adet + 1):
        adres = f"127.0.0.{sira}"
        sw = SahteSwitch(sira, set(takili))
        sinif = type("H", (Handler,), {"sw": sw, "ayar": a})
        try:
            srv = ThreadingHTTPServer((adres, a.port), sinif)
        except OSError as e:
            print(f"[!] {adres}:{a.port} açılamadı — {e}")
            if sira > 1:
                print("    macOS'ta ek loopback adresi için:")
                print(f"    sudo ifconfig lo0 alias {adres} up")
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        sunucular.append((adres, sw))

    if not sunucular:
        print("Hiç switch açılamadı.")
        return 1

    print("=" * 66)
    print(f"  Sahte switch çalışıyor — {len(sunucular)} cihaz, port {a.port}")
    for adres, sw in sunucular:
        print(f"    {adres}:{a.port}  {sw.calisan['ad']}  "
              f"{POE_PORT_SAYISI} PoE + {UPLINK_PORT_SAYISI} uplink port")
    print("-" * 66)
    print(f"  Kullanıcı/şifre : {a.kullanici} / {a.sifre}")
    print(f"  .env içinde     : SWITCH_HTTP_PORT={a.port}")
    print(f"  Panelde tara    : "
          f"{'127.0.0.1' if a.adet == 1 else '127.0.0.0/24'}")
    if a.gecikme:
        print(f"  Gecikme         : {a.gecikme} ms")
    if a.hata_orani:
        print(f"  Hata oranı      : %{a.hata_orani * 100:.0f}")
    print("=" * 66)
    print("İstekler aşağıda listelenir. Durdurmak için Ctrl-C.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nKapatıldı.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
