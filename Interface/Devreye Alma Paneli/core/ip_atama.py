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

Koşu ağa yazar: PoE portlarını sırayla açıp kapatır ve cihazlara IP
yazar. Bu yüzden koşuya girmemesi gereken portlar (bilgisayarın bağlı
olduğu port, switch'leri birbirine bağlayan port) baştan reddedilir.
"""
from __future__ import annotations

import contextlib
import io
import sys
import threading
import time

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


def korumali_denetle(portlar, korumali: dict[int, str] | None) -> None:
    """Koşuya girmemesi gereken port hedef listesindeyse ValueError.

    İki yerden çağrılır: istek geldiğinde (kullanıcı anında görsün diye) ve
    koşunun kendisinde (bu işlevi çağırmayan bir yol açılırsa diye).
    """
    hedef = set(portlar)
    for p in sorted(korumali or {}):
        if p in hedef:
            raise ValueError(
                f"Port {p} hedef listesinde ama {korumali[p]} — "
                "koşu kendi bağlantısını keserdi")


def izinli_portlar(env: Envanter, switch_id: str) -> list[int]:
    """DeviceMap'te bu switch'e bağlı cihazların portları."""
    p = {int(c.port) for c in env.cihazlar
         if c.switch_id == switch_id and c.port and str(c.port).isdigit()}
    return sorted(p)


def gruplari_coz(adlar) -> list[dict]:
    """Ad listesini grup tanımlarına çevirir; bilinmeyen ad atılır."""
    from .kategori import grup_bul

    cikan, gorulen = [], set()
    for ad in adlar or []:
        g = grup_bul(str(ad).strip())
        if g and g["ad"] not in gorulen:
            gorulen.add(g["ad"])
            cikan.append(g)
    return cikan


def grup_cihazlari(env: Envanter, gruplar: list[dict],
                   switch_id: str | None = None) -> dict[int, tuple]:
    """Port -> (cihaz, grup adı). Birden çok grup seçiliyse hepsi birleşir.

    Bir cihaz iki gruba birden girebilir (örn. Intercom ve Tümü); satır
    tekrar etmesin diye port anahtarı tek tutulur, ilk eşleşen grup adı
    yazılır.
    """
    from .kategori import grup_eslesir

    port_ile: dict[int, tuple] = {}
    for g in gruplar:
        for c in env.cihazlar:
            if not grup_eslesir(g, c):
                continue
            if switch_id and c.switch_id != switch_id:
                continue
            if not (c.port and str(c.port).isdigit()):
                continue
            port_ile.setdefault(int(c.port), (c, g["ad"]))
    return port_ile


def plan(env: Envanter, grup_adlari, portlar: list[int],
         switch_id: str | None = None) -> dict:
    """Koşu planı — ağa hiç çıkmadan, yalnız DeviceMap'ten.

    Her satır: hangi port, hangi cihaz, hangi grup, fabrika adayı ve
    yazılacak IP.

    `grup_adlari` bir liste (tek ad da verilebilir): birden çok cihaz
    grubu aynı koşuda seçilebiliyor. Her grubun atama betiği ayrı
    olduğundan koşu grup grup yürür (bkz. KOSUCULAR).

    Port numaraları switch'e göredir: iki switch'in de 11. portu vardır.
    `switch_id` verildiğinde plan yalnız o switch'in cihazlarından kurulur;
    yoksa aynı numaralı port başka bir switch'teki cihazı gösterebilirdi.
    """
    if isinstance(grup_adlari, str):
        grup_adlari = [grup_adlari]
    gruplar = gruplari_coz(grup_adlari)
    port_ile = grup_cihazlari(env, gruplar, switch_id)

    satir = []
    for p in portlar:
        c, grup_adi = port_ile.get(p, (None, ""))
        satir.append({
            "port": p,
            "cihazId": c.id if c else None,
            "ad": c.ad if c else "—",
            "tip": c.dto()["tipEtiket"] if c else "",
            "grup": grup_adi,
            "fabrika": fabrika_ip(env),
            "hedefIp": c.ip if c else "—",
            "uygulanabilir": c is not None,
        })
    ilk = next(iter(port_ile.values()), None)
    sw = switch_id or (ilk[0].switch_id if ilk else (
        env.switchler()[0].id if env.switchler() else None))
    sw_cihaz = env.bul(sw) if sw else None
    return {
        "switch": sw_cihaz.ad if sw_cihaz else "",
        "switchIp": sw_cihaz.ip if sw_cihaz else "",
        "switchId": sw,
        "satirlar": satir,
        "hedefSayi": sum(1 for s in satir if s["uygulanabilir"]),
        "portMetni": metin_yap(portlar) or "Port seçilmedi",
        "gruplar": [g["ad"] for g in gruplar],
        # Betiği olmayan gruplar: arayüz koşuyu başlatmadan söyleyebilsin.
        "kosucusuz": [g["ad"] for g in gruplar if g["ad"] not in KOSUCULAR],
    }


# Aday adres listesinin üst sınırı. Sahadaki maske /16 (255.255.0.0)
# olabiliyor; onu açmak 65 bin adres demek ve her port için baştan sona
# taranıyor — koşu bitmez. Aramanın anlamlı olduğu yer cihazların
# bulunduğu /24 ve daha dar ağlar.
ARAMA_SINIRI = 512


# ARP önbelleğini temizleme yetkisi koşunun tek turda bitmesinin şartı
# (bkz. intercom_ip_assign.arp_unut). Yetki sorgusu `sudo -n` çalıştırdığı
# için her plan isteğinde yeniden sorulmaz.
_ARP_YETKI = {"zaman": 0.0, "deger": False}


def arp_yetkisi(ttl: float = 10.0) -> bool:
    simdi = time.time()
    if simdi - _ARP_YETKI["zaman"] > ttl:
        try:
            deger = bool(betik.intercom_ip_assign().arp_silebilir())
        except Exception:
            deger = False
        _ARP_YETKI.update(zaman=simdi, deger=deger)
    return _ARP_YETKI["deger"]


def ipv4_mi(metin) -> bool:
    import ipaddress

    try:
        return ipaddress.ip_address(str(metin).strip()).version == 4
    except ValueError:
        return False


def arama_adaylari(ag: str, maske: str, sinir: int = ARAMA_SINIRI) -> list[str]:
    """'10.1.1.0' + '255.255.255.0' → ['10.1.1.1', …, '10.1.1.254'].

    Fabrika adresinde olmayan cihazlar için taranacak adresler. Maske
    yerine önek uzunluğu da yazılabilir ("24").
    """
    import ipaddress

    ag = str(ag or "").strip()
    maske = str(maske or "").strip()
    if not ag:
        return []
    try:
        net = ipaddress.ip_network(f"{ag}/{maske or '32'}", strict=False)
    except ValueError as exc:
        raise ValueError(f"Arama ağı çözülemedi: {exc}") from exc
    if net.version != 4:
        raise ValueError("Arama ağı IPv4 olmalı")
    adresler = [str(h) for h in net.hosts()] or [str(net.network_address)]
    if len(adresler) > sinir:
        raise ValueError(
            f"Arama ağı çok geniş ({len(adresler)} adres). "
            f"En fazla {sinir} adres taranabilir — daha dar bir maske girin "
            "(örn. 255.255.255.0).")
    return adresler


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
        # Koşu switch'e kullanıcı adı/parola ile bağlanıyor. Kimlik yoksa
        # koşu daha ilk adımda düşer; arayüz bunu baştan söyleyebilsin.
        "kimlikVar": bool(kimlik),
        "poeSayisi": poe_n,
        "uplinkSayisi": uplink_n,
        "kaynak": kaynak,
        "not": not_,
        # Verinin ne zaman okunduğu: ön panel canlı yenilendiği için
        # "kaç saniye önce" arayüzde bu damgadan hesaplanır.
        "okumaZamani": time.time() if kaynak == "switch" else None,
        "portlar": [{
            "no": n,
            # Fiziksel yerleşimde PoE mi uplink mi (panelin sağ sütunu).
            "poe": n <= poe_n,
            "cihaz": tanimli.get(n, ""),
            "tanimli": n in tanimli,
            "acik": canli[n]["acik"] if n in canli else None,
            "link": canli[n]["link"] if n in canli else "",
            # Canlı okuma varsa gücün durumu da gelir: "besliyor" ile
            # "yalnız bağlı"yı ayıran tek şey bu.
            "poeVar": canli[n].get("poe") if n in canli else None,
            "poeMod": canli[n].get("poeMod", "") if n in canli else "",
            "guc": canli[n].get("guc") if n in canli else None,
        } for n in numaralar],
    }


# ─────────────────────────────────────────────────────────────── koşu ─────
class _Satir(io.TextIOBase):
    """Betiğin çıktısını satır satır geri çağrıya verir.

    Aynı zamanda iptalin betiğe ulaştığı yer. Betik süreç içinde
    main() olarak çalışıyor; dışarıdan bir bayrak koymak onu durdurmuyor,
    çünkü bayrağı okuyan kimse yok. Betiğin sürekli yazdığı çıktı ise
    her seferinde buradan geçiyor: iptal istendiğinde bir sonraki
    print'te KeyboardInterrupt atılır.

    KeyboardInterrupt seçilmesi bilinçli: betik zaten onu yakalayıp
    "portlar geri açılıyor" diyerek aralıktaki bütün PoE portlarını
    tekrar açıyor (finally). Yani iptal, Ctrl-C ile aynı yoldan yürür ve
    portlar kapalı kalmaz. BaseException türevi olduğu için betiğin
    içindeki `except Exception` blokları da yutmaz.
    """

    def __init__(self, geri, iptal=None):
        self._geri = geri
        self._iptal = iptal
        self._atildi = False
        self._tampon = ""

    def _iptal_denetle(self):
        # Yalnız bir kez atılır: betik iptali yakalayıp portları geri
        # açarken de yazıyor; her yazımda yeniden atsaydık kendi
        # kurtarma adımını da kesip portları kapalı bırakırdık.
        #
        # Satır ortasında da atılmaz: print önce metni, sonra satır sonunu
        # yazıyor; arada kesince yarım satır tamponda kalıp bir sonrakiyle
        # birleşiyordu.
        if self._tampon or self._atildi:
            return
        if self._iptal is None or not self._iptal():
            return
        self._atildi = True
        raise KeyboardInterrupt

    def write(self, s):
        self._tampon += s
        while "\n" in self._tampon:
            satir, _, self._tampon = self._tampon.partition("\n")
            if satir.strip():
                self._geri(satir.rstrip())
        self._iptal_denetle()
        return len(s)

    def flush(self):
        if self._tampon.strip():
            self._geri(self._tampon.rstrip())
            self._tampon = ""


def _intercom_kosu(env: Envanter, sw, portlar: list[int], hesap,
                   satir_geri, ayarlar: dict, iptal=None) -> int:
    """Intercom grubunun atama betiği (intercom_ip_assign.py).

    Betik portları sırayla tek tek açar: aralıktaki bütün PoE portlarını
    kapatıp yalnız hedef portu açar, o an ayağa kalkan cihazı adaylar
    arasında bulur ve DeviceMap'te o porta yazılı IP'yi yazar.

    Betik yalnız SubType=Intercom kayıtlarıyla çalışıyor; başka bir portta
    "yalnızca Intercom portlarıyla çalışır" deyip çıkıyor. Bu yüzden
    KOSUCULAR tablosunda tek grup var.
    """
    mod = betik.intercom_ip_assign()
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
        # Kalıcılık kontrolü kapalı: betik sonda bütün portların gücünü
        # bir kez kesip açarak ayarın flash'a indiğini doğruluyordu. Sahada
        # bu, işi biten cihazları yeniden karartıyor ve koşuyu uzatıyor.
        # Doğrulama zaten yazma sonrası hedef IP'den cevap alınarak
        # yapılıyor; ikinci bir güç çevrimi istenmiyor.
        "--no-persist-check",
    ]
    fabrika = str(ayarlar.get("fabrikaIp") or "").strip()
    if fabrika:
        argv += ["--factory-ip", fabrika]
    # Fabrika adresinde olmayan cihazlar için ek aday adresler. Betik
    # zaten fabrika IP'sini ve DeviceMap'teki bütün intercom adreslerini
    # deniyor; buradakiler onların üstüne eklenir.
    ek = arama_adaylari(ayarlar.get("aramaAgi"), ayarlar.get("aramaMaskesi"))
    if ek:
        satir_geri(f"[Intercom] Ek arama ağı: {len(ek)} adres "
                   f"({ek[0]} – {ek[-1]})")
        argv += ["--default-ip", *ek]
    return _betigi_calistir(mod, argv, satir_geri, iptal)


def _betik_cfg(fabrika_ip: str, sw_ip: str):
    """Betiğin read_settings/write_ip işlevleri için asgari ayar nesnesi.

    Alan adları ve varsayılanlar betiğin argparse'ıyla aynı; yazma gövdesi
    ve uçlar orada nasılsa öyle kalsın diye ikinci bir istemci yazılmaz.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        arduino_port=ayar.ANONS_PORT,
        write_endpoint="api/v1/network/ip",
        probe_timeout=2.0,
        timeout=8.0,
        netmask=ayar.BEKLENEN_MASKE,
        gateway=sw_ip,
        ntp_ip=None,
        full_net_payload=False,
        dry_run=False,
    )


def fabrikaya_dondur(env: Envanter, switch_id: str, portlar: list[int],
                     gruplar, satir_geri, ayarlar: dict | None = None,
                     iptal=None) -> int:
    """Seçili cihazlara "IP'ni fabrika adresine çevir" isteği gönderir.

    Geliştirme/test akışı: koşuyu baştan denemek için cihazları yeniden
    aynı fabrika adresinde toplar. Yalnızca cihaza IP yazma isteği
    gönderilir — PoE'ye, switch'e, DeviceMap'e dokunulmaz.

    Cihazlar bu işlemden sonra AYNI adreste olur; bu, koşunun beklediği
    başlangıç durumudur ama o ana kadar hepsi birbiriyle çakışır.

    Dönüş: yazılamayan cihaz sayısı.
    """
    mod = betik.intercom_ip_assign()
    sw = env.bul(switch_id)
    if sw is None:
        raise ValueError("Switch bulunamadı")
    secili = gruplari_coz(gruplar)
    if not secili:
        raise ValueError("Cihaz grubu seçilmedi")

    fabrika = str((ayarlar or {}).get("fabrikaIp") or "").strip() \
        or fabrika_ip(env)
    if not ipv4_mi(fabrika):
        raise ValueError("Fabrika IP geçerli değil")

    cfg = _betik_cfg(fabrika, sw.ip)
    port_ile = grup_cihazlari(env, secili, sw.id)
    hedefler = [(p, port_ile[p][0]) for p in sorted(portlar) if p in port_ile]
    if not hedefler:
        raise ValueError("Seçili portlarda bu gruptan cihaz yok")

    satir_geri(f"{len(hedefler)} cihaz {fabrika} adresine döndürülecek "
               f"(yalnız IP yazılır, PoE'ye dokunulmaz)")
    basarisiz = 0
    for port, cihaz in hedefler:
        if iptal and iptal():
            satir_geri("Durduruldu")
            break
        if cihaz.ip == fabrika:
            satir_geri(f"p{port} {cihaz.ad}: zaten {fabrika}")
            continue
        # Bayat ARP kaydı burada da cihazı ulaşılmaz gösteriyor.
        mod.arp_unut([cihaz.ip])
        ayarlar_ = mod.read_settings(cihaz.ip, cfg)
        if ayarlar_ is None:
            basarisiz += 1
            satir_geri(f"[!] p{port} {cihaz.ad}: {cihaz.ip} cevap vermedi")
            continue
        try:
            mod.write_ip(cihaz.ip, ayarlar_, fabrika, cfg)
        except Exception as exc:
            basarisiz += 1
            satir_geri(f"[!] p{port} {cihaz.ad}: yazılamadı "
                       f"({type(exc).__name__})")
            continue
        satir_geri(f"p{port} {cihaz.ad}: {cihaz.ip} -> {fabrika} yazıldı")
    satir_geri("Bitti — cihazlar reset atıp fabrika adresinde toplanacak")
    return basarisiz


# Hangi cihaz grubunun atamasını hangi betik yürütüyor. Her cihaz tipinin
# atama akışı ayrı (PoE sırası, fabrika adresi, yazma ucu farklı), o yüzden
# tek bir "hepsini atayan" betik yok. Yeni betik yazıldıkça buraya eklenir;
# tabloda olmayan grup için koşu başlatılmaz — hiçbir şey yapmayan bir
# koşuyu "tamamlandı" diye göstermek en kötü sonuç olurdu.
KOSUCULAR = {
    "Intercom": _intercom_kosu,
}


def kosucusuz(grup_adlari) -> list[str]:
    """Seçilen gruplardan atama betiği olmayanlar."""
    return [g["ad"] for g in gruplari_coz(grup_adlari)
            if g["ad"] not in KOSUCULAR]


def kosu(env: Envanter, switch_id: str, portlar: list[int],
         satir_geri, korumali: dict[int, str] | None = None,
         gruplar=None, ayarlar: dict | None = None, iptal=None) -> int:
    """IP atama koşusunu çalıştırır. Dönüş: en yüksek çıkış kodu.

    Seçilen her grup kendi betiğiyle, kendi portlarıyla sırayla yürür:
    gruplar tek bir çağrıya karıştırılmaz, çünkü her cihaz tipinin atama
    akışı farklı.

    `satir_geri(metin)` betiğin her çıktı satırı için çağrılır; arayüz bunu
    iş kuyruğunda gösterir. Parola bu akışa hiç girmez: betik kimliği
    yalnızca isteklerde kullanır, ekrana yazmaz.

    `korumali` {port: sebep}: koşunun dokunmaması gereken portlar. Koşu
    PoE'yi sırayla kapatıp açtığı için bilgisayarın bağlı olduğu port ya
    da iki switch'i birbirine bağlayan port listeye girerse koşu kendi
    yolunu keser ve yarıda kalır.
    """
    sw = env.bul(switch_id)
    if sw is None:
        raise ValueError("Switch bulunamadı")
    if not portlar:
        raise ValueError("Port seçilmedi")
    korumali_denetle(portlar, korumali)

    # Grup verilmemişse varsayılan seçilmez: "hangi cihazlara atama
    # yapılacağı" tahmin edilecek bir şey değil.
    secili = gruplari_coz(gruplar)
    if not secili:
        raise ValueError("Cihaz grubu seçilmedi")
    eksik = [g["ad"] for g in secili if g["ad"] not in KOSUCULAR]
    if eksik:
        raise ValueError(
            "Bu grup için IP atama betiği henüz yok: " + ", ".join(eksik))

    hesap = kimlik_deposu.al(sw.id, sw.ip, grup="switch")
    if not hesap:
        raise KimlikHatasi(
            f"{sw.ad} için kullanıcı adı/parola girilmemiş — "
            "switch panelindeki \"Kimlik gir\" ile doğrulayın")

    # Her grup yalnız kendi portlarını alır: bir grubun betiğine başka bir
    # grubun portunu vermek, o betiğin "burada benim cihazım yok" deyip
    # bütün koşuyu düşürmesi demek.
    port_ile = grup_cihazlari(env, secili, sw.id)
    kod = 0
    for g in secili:
        grup_portlari = [p for p in portlar
                         if port_ile.get(p) and port_ile[p][1] == g["ad"]]
        if not grup_portlari:
            satir_geri(f"[{g['ad']}] Seçili portlarda bu gruptan cihaz yok, "
                       "atlandı")
            continue
        satir_geri(f"[{g['ad']}] {metin_yap(grup_portlari)} — atama başlıyor")
        kod = max(kod, KOSUCULAR[g["ad"]](
            env, sw, grup_portlari, hesap, satir_geri, ayarlar or {},
            iptal))
        # İptal edildiyse kalan gruplara geçilmez.
        if iptal and iptal():
            satir_geri("Kalan gruplar iptal edildi")
            break
    return kod


def _betigi_calistir(mod, argv, satir_geri, iptal=None) -> int:
    """Betiği süreç içinde çalıştırır; çıktısını satır satır aktarır.

    main() süreç genelindeki sys.argv/sys.stdout'a dokunduğu için kilit
    altında çalışır (bkz. _KOSU_KILIT).

    İptal edilirse betik kendi KeyboardInterrupt yolundan geçer: portları
    geri açar, sonra buraya döner. Dönüş 130 (Ctrl-C ile aynı) olur ve
    KeyboardInterrupt dışarı sızmaz — iş kuyruğu onu "worker çöktü" diye
    okumamalı.
    """
    with _KOSU_KILIT:
        eski_argv, eski_out = sys.argv, sys.stdout
        akis = _Satir(satir_geri, iptal)
        try:
            sys.argv = argv
            with contextlib.redirect_stdout(akis):
                kod = mod.main()
            akis.flush()
            return int(kod or 0)
        except KeyboardInterrupt:
            akis.flush()
            satir_geri("Koşu durduruldu")
            return 130
        finally:
            sys.argv, sys.stdout = eski_argv, eski_out
