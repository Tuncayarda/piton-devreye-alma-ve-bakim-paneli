#!/usr/bin/env python3
"""Otomatik IP atama.

Plan (hangi porta hangi cihaz, hangi IP yazılacak) DeviceMap'ten çıkar.
Koşunun kendisi YATAKLI_DevreyeAlma/intercom_ip_assign.py içindeki
doğrulanmış akışla yapılır: PoE portlarını sırayla açıp yalnız o an
ayakta olan cihazı bulmak, MAC tablosuyla portu doğrulamak, IP yazıp
reset sonrası teyit etmek — hepsi sahada denenmiş adımlar. Burada ikinci
bir sürümü yazılmaz.

Kimlik: switch kullanıcı adı/parolası bellekteki depodan alınır ve
betiğe süreç içi argüman listesiyle verilir. Gerçek işletim sistemi
komut satırı değişmez (sys.argv'yi değiştirmek `ps` çıktısını
değiştirmez), dosyaya hiçbir şey yazılmaz.

Koşu, açıkça aksi seçilmedikçe DRY-RUN çalışır: ağa yazmaz, yalnız ne
yapacağını söyler.
"""
from __future__ import annotations

import contextlib
import io
import sys
import threading

from . import ayar, betik, kimlik as kimlik_deposu, switch_okuma
from .device_map import Envanter
from .hata import KimlikHatasi

# main() süreç genelindeki sys.stdout/sys.argv'ye dokunduğu için aynı anda
# tek koşu. İş kuyruğu zaten tek iş çalıştırıyor; bu ikinci emniyet.
_KOSU_KILIT = threading.Lock()


def portlar_ayristir(metin: str, izinli: set[int] | None = None) -> list[int]:
    """'11-14, 21 22' -> [11,12,13,14,21,22]. Geçersizse ValueError."""
    cikan: list[int] = []
    for parca in str(metin or "").replace(";", ",").replace(" ", ",").split(","):
        parca = parca.strip()
        if not parca:
            continue
        if "-" in parca:
            a, _, b = parca.partition("-")
            try:
                bas, son = int(a), int(b)
            except ValueError:
                raise ValueError(f"Geçersiz port aralığı: {parca}")
            if son < bas:
                raise ValueError(f"Geçersiz port aralığı: {parca}")
            cikan.extend(range(bas, son + 1))
        else:
            try:
                cikan.append(int(parca))
            except ValueError:
                raise ValueError(f"Geçersiz port: {parca}")
    if izinli is not None:
        disarida = sorted(set(cikan) - izinli)
        if disarida:
            raise ValueError(
                "Bu switch'te tanımlı olmayan port: "
                + ", ".join(str(p) for p in disarida))
    return sorted(set(cikan))


def metin_yap(portlar) -> str:
    """[11,12,13,21] -> '11-13, 21'"""
    p = sorted(set(int(x) for x in portlar))
    if not p:
        return ""
    parca, bas, on = [], p[0], p[0]
    for i in range(1, len(p) + 1):
        simdi = p[i] if i < len(p) else None
        if simdi == on + 1:
            on = simdi
            continue
        parca.append(str(bas) if bas == on else f"{bas}-{on}")
        bas = on = simdi
    return ", ".join(parca)


def izinli_portlar(env: Envanter, switch_id: str) -> list[int]:
    """DeviceMap'te bu switch'e bağlı cihazların portları."""
    p = {int(c.port) for c in env.cihazlar
         if c.switch_id == switch_id and c.port and str(c.port).isdigit()}
    return sorted(p)


def plan(env: Envanter, grup_adi: str, portlar: list[int],
         switch_id: str | None = None) -> dict:
    """Koşu planı — ağa hiç çıkmadan, yalnız DeviceMap'ten.

    Her satır: hangi port, hangi cihaz, fabrika adayı ve yazılacak IP.

    Port numaraları switch'e göredir: iki switch'in de 11. portu vardır.
    `switch_id` verildiğinde plan yalnız o switch'in cihazlarından kurulur;
    yoksa aynı numaralı port başka bir switch'teki cihazı gösterebilirdi.
    """
    from .kategori import grup_bul, grup_eslesir

    g = grup_bul(grup_adi)
    hedefler = [c for c in env.cihazlar if g and grup_eslesir(g, c)]
    if switch_id:
        hedefler = [c for c in hedefler if c.switch_id == switch_id]
    port_ile = {int(c.port): c for c in hedefler
                if c.port and str(c.port).isdigit()}

    satir = []
    for p in portlar:
        c = port_ile.get(p)
        satir.append({
            "port": p,
            "cihazId": c.id if c else None,
            "ad": c.ad if c else "—",
            "tip": c.dto()["tipEtiket"] if c else "",
            "fabrika": fabrika_ip(env),
            "hedefIp": c.ip if c else "—",
            "uygulanabilir": c is not None,
        })
    sw = switch_id or (hedefler[0].switch_id if hedefler else (
        env.switchler()[0].id if env.switchler() else None))
    sw_cihaz = env.bul(sw) if sw else None
    return {
        "switch": sw_cihaz.ad if sw_cihaz else "",
        "switchIp": sw_cihaz.ip if sw_cihaz else "",
        "switchId": sw,
        "satirlar": satir,
        "hedefSayi": sum(1 for s in satir if s["uygulanabilir"]),
        "portMetni": metin_yap(portlar) or "Port seçilmedi",
    }


def fabrika_ip(env: Envanter) -> str:
    """Yapılandırılmamış cihazların beklendiği adres.

    intercom_ip_assign.py ile aynı varsayılan: 10.n.1.12.
    """
    from .device_map import coz
    return coz("10.n.1.12", env.set_no)


def onpanel(env: Envanter, switch_id: str,
            kimlik=None) -> dict:
    """Switch'in port listesi — ön panel çizimi için.

    Switch okunamazsa (kimlik yok / ulaşılamıyor) portlar DeviceMap'ten
    çizilir ve durum bilgisi boş kalır; uydurma link durumu gösterilmez.
    """
    sw = env.bul(switch_id)
    if sw is None:
        return {"portlar": [], "kaynak": "yok", "not": "Switch bulunamadı"}
    tanimli = {int(c.port): c.ad for c in env.cihazlar
               if c.switch_id == switch_id and c.port and str(c.port).isdigit()}
    try:
        canli = {p["pid"]: p for p in switch_okuma.portlar(sw.ip, kimlik)}
        kaynak, not_ = "switch", ""
    except KimlikHatasi:
        canli, kaynak = {}, "devicemap"
        not_ = "Switch kullanıcı adı/parola istiyor — port durumu okunamadı"
    except Exception:
        canli, kaynak = {}, "devicemap"
        not_ = "Switch'e ulaşılamadı — port durumu okunamadı"

    # Panelde cihazın bütün yüzü çizilir: yalnız DeviceMap'te geçen portlar
    # gösterilince harita seyrek bir sayı listesine dönüyordu, hangi portun
    # nerede olduğu okunmuyordu. Beklenenin dışında bir port numarası
    # gelirse (DeviceMap ya da switch) o da listeye eklenir.
    poe_n, uplink_n = ayar.SWITCH_POE_PORT, ayar.SWITCH_UPLINK_PORT
    numaralar = sorted(set(range(1, poe_n + uplink_n + 1))
                       | set(tanimli) | set(canli))
    return {
        "switchId": sw.id,
        "switchAd": sw.ad,
        "switchIp": sw.ip,
        "poeSayisi": poe_n,
        "uplinkSayisi": uplink_n,
        "kaynak": kaynak,
        "not": not_,
        "portlar": [{
            "no": n,
            "poe": n <= poe_n,
            "cihaz": tanimli.get(n, ""),
            "tanimli": n in tanimli,
            "acik": canli[n]["acik"] if n in canli else None,
            "link": canli[n]["link"] if n in canli else "",
        } for n in numaralar],
    }


# ─────────────────────────────────────────────────────────────── koşu ─────
class _Satir(io.TextIOBase):
    """Betiğin çıktısını satır satır geri çağrıya verir."""

    def __init__(self, geri):
        self._geri = geri
        self._tampon = ""

    def write(self, s):
        self._tampon += s
        while "\n" in self._tampon:
            satir, _, self._tampon = self._tampon.partition("\n")
            if satir.strip():
                self._geri(satir.rstrip())
        return len(s)

    def flush(self):
        if self._tampon.strip():
            self._geri(self._tampon.rstrip())
            self._tampon = ""


def kosu(env: Envanter, switch_id: str, portlar: list[int], dry_run: bool,
         satir_geri, pc_port: int | None = None) -> int:
    """IP atama koşusunu çalıştırır. Dönüş: betiğin çıkış kodu.

    `satir_geri(metin)` betiğin her çıktı satırı için çağrılır; arayüz bunu
    iş kuyruğunda gösterir. Parola bu akışa hiç girmez: betik kimliği
    yalnızca isteklerde kullanır, ekrana yazmaz.
    """
    mod = betik.intercom_ip_assign()
    sw = env.bul(switch_id)
    if sw is None:
        raise ValueError("Switch bulunamadı")
    if not portlar:
        raise ValueError("Port seçilmedi")
    if pc_port is not None and pc_port in portlar:
        raise ValueError(
            f"Bilgisayarın bağlı olduğu port ({pc_port}) hedef listesinde — "
            "koşu kendi bağlantısını keserdi")

    hesap = kimlik_deposu.al(sw.id, sw.ip, grup="switch")
    if not hesap:
        raise KimlikHatasi(
            f"{sw.ad} için kullanıcı adı/parola girilmemiş — "
            "önce kilit menüsünden doğrulayın")

    argv = [
        "intercom_ip_assign.py",
        "--ports", *[str(p) for p in portlar],
        "-n", str(env.set_no),
        "--device-map", str(env.kaynak),
        "--switch-ip", sw.ip,
        "--kyland-port", str(ayar.KYLAND_PORT),
        "--kyland-user", hesap[0],
        "--kyland-pass", hesap[1],
        "--arduino-port", str(ayar.ANONS_PORT),
    ]
    if dry_run:
        argv.append("--dry-run")

    with _KOSU_KILIT:
        eski_argv, eski_out = sys.argv, sys.stdout
        akis = _Satir(satir_geri)
        try:
            sys.argv = argv
            with contextlib.redirect_stdout(akis):
                kod = mod.main()
            akis.flush()
            return int(kod or 0)
        finally:
            sys.argv, sys.stdout = eski_argv, eski_out
