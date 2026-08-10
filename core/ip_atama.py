#!/usr/bin/env python3
"""Otomatik IP atama.

Plan (hangi porta hangi cihaz, hangi IP yazılacak) DeviceMap'ten çıkar.
Koşunun kendisi betikler/intercom_ip_assign.py içindeki
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
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import ayar, betik, kimlik as kimlik_deposu, switch_okuma, yerel_ag
from .device_map import Envanter, coz
from .hata import KimlikHatasi, UlasilamadiHatasi

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
# taranıyor — koşu bitmez. Geniş maskeli kurulumda aranacak yeri
# daraltmanın yolu ağ + maske değil, açık adres aralığı vermektir
# (bkz. aralik_adaylari).
ARAMA_SINIRI = 512


# ARP önbelleğini temizleme yetkisi koşunun tek turda bitmesinin şartı
# (bkz. intercom_ip_assign.arp_unut). Yetki sorgusu `sudo -n` çalıştırdığı
# için her plan isteğinde yeniden sorulmaz.
_ARP_YETKI = {"zaman": 0.0, "deger": False}


def arp_ipucu() -> str:
    """Yetki yoksa kullanıcının ne yapması gerektiği (platforma göre)."""
    try:
        return str(betik.intercom_ip_assign().arp_yetki_ipucu())
    except Exception:
        return ""


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


def aralik_adaylari(bas: str, son: str,
                    sinir: int = ARAMA_SINIRI) -> list[str]:
    """'10.1.1.10' + '10.1.1.60' → aradaki bütün adresler.

    Ağ + maske ikilisinin işe yaramadığı durumun karşılığı: proje maskesi
    /8 olduğunda o ağı açmak 16 milyon adres demek, ama aranacak cihazlar
    bilinen dar bir aralıkta duruyor. Kullanıcı o aralığı doğrudan yazar.
    """
    import ipaddress

    bas, son = str(bas or "").strip(), str(son or "").strip()
    if not (bas and son):
        raise ValueError(
            "Arama aralığının başlangıcı ve sonu birlikte verilmeli")
    try:
        ilk, sonuncu = ipaddress.IPv4Address(bas), ipaddress.IPv4Address(son)
    except ValueError as exc:
        raise ValueError(f"Arama aralığı çözülemedi: {exc}") from exc
    if int(sonuncu) < int(ilk):
        raise ValueError("Arama aralığının sonu başlangıcından küçük olamaz")
    adet = int(sonuncu) - int(ilk) + 1
    if adet > sinir:
        raise ValueError(
            f"Arama aralığı çok geniş ({adet} adres). "
            f"En fazla {sinir} adres taranabilir — aralığı daraltın.")
    return [str(ipaddress.IPv4Address(x))
            for x in range(int(ilk), int(sonuncu) + 1)]


def arama_adaylari(ag: str, maske: str, sinir: int = ARAMA_SINIRI,
                   bas: str = "", son: str = "") -> list[str]:
    """'10.1.1.0' + '255.255.255.0' → ['10.1.1.1', …, '10.1.1.254'].

    Fabrika adresinde olmayan cihazlar için taranacak adresler. Maske
    yerine önek uzunluğu da yazılabilir ("24").

    Başlangıç/bitiş verilirse ağ + maske yerine o aralık kullanılır
    (bkz. aralik_adaylari): geniş maskeli kurulumlarda aranacak yeri
    daraltmanın tek yolu bu.
    """
    import ipaddress

    ag = str(ag or "").strip()
    maske = str(maske or "").strip()
    if str(bas or "").strip() or str(son or "").strip():
        return aralik_adaylari(bas, son, sinir)
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


def fabrika_ip(env: Envanter | None = None) -> str:
    """Yapılandırılmamış cihazların beklendiği adres.

    Sabittir (10.1.1.12) — tren setine göre çözülmez. Cihaz fabrikadan
    hangi sete gideceğini bilmeden çıkıyor; hepsi aynı adreste geliyor.
    `env` yalnız çağrı yerlerini bozmamak için duruyor.
    """
    return ayar.FABRIKA_IP


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


def _switch_verisi(env: Envanter, kimlik_al=None) -> tuple[list, list]:
    """Her switch için MAC öğrenme tablosu ve switch'in kendi MAC'i.

    Paralel okunur: ayakta olmayan switch kendi zaman aşımıyla düşer,
    diğerlerini bekletmez. Döner: ([(sw, tablo, kendi_mac, sorun)], denenen)
    """
    switchler = env.switchler()
    if not switchler:
        return [], []

    # Kısa tutulur: bu arama kullanıcı ekrana bakarken çalışıyor ve
    # ayakta olmayan switch'in zaman aşımını bekletiyor.
    sure = min(ayar.OKUMA_TIMEOUT, 2.5)

    def oku(sw):
        kimlik = kimlik_al(sw) if kimlik_al else None
        try:
            tablo = switch_okuma.mac_tablosu(sw.ip, kimlik, timeout=sure)
        except KimlikHatasi:
            return sw, {}, "", "kullanıcı adı/parola istiyor"
        except UlasilamadiHatasi:
            return sw, {}, "", "ulaşılamadı"
        except Exception:
            return sw, {}, "", "okunamadı"
        # Switch'in KENDİ MAC'i: komşu switch'in tablosunda bunu aramak,
        # iki switch'i birbirine bağlayan portu veriyor.
        try:
            kendi = yerel_ag.normalle(
                switch_okuma.oku(sw.ip, kimlik, timeout=sure).get("mac", ""))
        except Exception:
            kendi = ""
        return sw, tablo, kendi, ""

    havuz = ThreadPoolExecutor(max_workers=min(8, len(switchler)))
    try:
        sonuclar = list(havuz.map(oku, switchler))
    finally:
        havuz.shutdown(wait=True)

    denenen = [{"switchId": sw.id, "ad": sw.ad, "ip": sw.ip,
                "durum": sorun or ("MAC tablosu boş" if not tablo else "okundu")}
               for sw, tablo, _kendi, sorun in sonuclar]
    return sonuclar, denenen


def _port_mac_sayisi(tablo: dict, port: int) -> int:
    return sum(1 for p in tablo.values() if p == port)


def korunan_portlar(env: Envanter, kimlik_al=None) -> dict:
    """Koşunun dokunmaması gereken portların TAMAMI — hiçbiri sorulmaz.

    İki fiziksel gerçek var ve ikisi de elle giriliyordu:

      · Bilgisayar bir switch'in bir portunda.
      · Switch'ler birbirine birer portla bağlı.

    İkisi de switch'lerin MAC öğrenme tablosundan çıkıyor; kullanıcıya
    sormanın gereği yoktu. Yanlış girilen cevap üstelik iki kere zarar
    veriyordu: korunması gereken port korunmuyor, korunmaması gereken
    port koşudan düşüyordu.

    Kural tek ve her switch için aynı: **bilgisayarın MAC'i bir switch'in
    hangi portunda öğrenilmişse, o port o switch'e giden yoldur.**
    Bilgisayarın doğrudan takılı olduğu switch'te bu, bilgisayarın kendi
    portu; diğer switch'lerde ise o switch'e ulaşmak için kullanılan
    uplink. İkisini de kesmek koşunun kendi yolunu kesmek demek, o yüzden
    ikisi de korunur.

    Hangi switch'in bilgisayarı DOĞRUDAN taşıdığı, portta öğrenilmiş MAC
    sayısından anlaşılır: erişim portunda tek cihaz vardır, uplink'te
    switch'in arkasındaki her şey. Sıraya bakmak yanlış olurdu — komşu
    switch de bilgisayarın MAC'ini kendi uplink'inde görüyor.

    Buna ek olarak komşu switch'in KENDİ MAC'i de aranır: bilgisayarın
    yolu üstünde olmayan switch-switch bağlantıları da böyle bulunur.

    Döner:
      {"zaman", "bilgisayar": {...}, "portlar": [...], "denenen": [...],
       "not": ""}
    `portlar` korunacak her portu taşır:
      {"switchId", "switchAd", "port", "tur", "sebep"}
      `tur`: "bilgisayar" | "baglanti"
    Bulunamayan hiçbir şey tahmin edilmez.
    """
    bos_pc = {"switchId": "", "switchAd": "", "port": None, "mac": "",
              "arayuz": "", "yerelIp": "", "kaynak": "yok", "not": ""}
    sonuc = {"zaman": time.time(), "bilgisayar": dict(bos_pc),
             "portlar": [], "denenen": [], "not": ""}

    if not env.switchler():
        return {**sonuc, "not": "Projede switch tanımlı değil"}
    # Arayüz dökümü bir kez okunur; switch başına komut çalıştırmanın
    # anlamı yok.
    arayuzler = yerel_ag.arayuzler()
    if not arayuzler:
        return {**sonuc, "not": "Bilgisayarın ağ arayüzleri okunamadı"}

    sonuclar, denenen = _switch_verisi(env, kimlik_al)
    sonuc["denenen"] = denenen
    okunan = [(sw, t, k) for sw, t, k, sorun in sonuclar if t and not sorun]
    if not okunan:
        sebepler = ", ".join(f"{d['ad']} {d['durum']}" for d in denenen)
        return {**sonuc,
                "not": f"Hiçbir switch'in MAC tablosu okunamadı ({sebepler})"}

    # ── bilgisayarın MAC'i hangi switch'te hangi portta? ──
    bulgular = []
    for sw, tablo, _kendi in okunan:
        yerel = yerel_ag.hedefe_giden_mac(sw.ip, arayuzler)
        # Yönlendirmenin gösterdiği arayüz önce; sonra diğerleri.
        sirali = ([yerel["mac"]] if yerel["mac"] else []) + [
            m for m in yerel["adaylar"] if m != yerel["mac"]]
        mac = next((m for m in sirali if m in tablo), "")
        if not mac:
            continue
        port = int(tablo[mac])
        bulgular.append({"sw": sw, "port": port, "mac": mac,
                         "arayuz": yerel["ad"], "yerelIp": yerel["yerelIp"],
                         "komsu": _port_mac_sayisi(tablo, port)})

    portlar: dict[tuple[str, int], dict] = {}

    def ekle(sw, port, tur, sebep):
        anahtar = (sw.id, int(port))
        # "bilgisayar" daha açıklayıcı; bir port iki sebeple de gelirse o kalır.
        if anahtar in portlar and portlar[anahtar]["tur"] == "bilgisayar":
            return
        portlar[anahtar] = {"switchId": sw.id, "switchAd": sw.ad,
                            "port": int(port), "tur": tur, "sebep": sebep}

    if bulgular:
        # En az MAC öğrenilmiş port = bilgisayarın doğrudan takılı olduğu yer.
        dogrudan = min(bulgular, key=lambda b: b["komsu"])
        sonuc["bilgisayar"] = {
            "switchId": dogrudan["sw"].id, "switchAd": dogrudan["sw"].ad,
            "port": dogrudan["port"], "mac": dogrudan["mac"],
            "arayuz": dogrudan["arayuz"], "yerelIp": dogrudan["yerelIp"],
            "kaynak": "mac", "not": "",
        }
        for b in bulgular:
            if b is dogrudan:
                ekle(b["sw"], b["port"], "bilgisayar", "bilgisayar bu portta")
            else:
                ekle(b["sw"], b["port"], "baglanti",
                     f"{dogrudan['sw'].ad} yönüne giden bağlantı")
    else:
        sonuc["bilgisayar"] = {
            **bos_pc,
            "not": "Bilgisayarın MAC'i okunan switch'lerin hiçbirinde yok — "
                   "kablosu takılı mı?"}

    # ── switch'ler birbirine hangi porttan bağlı? ──
    # Komşunun kendi MAC'i bizim tablomuzda hangi porttaysa, o port o
    # komşuya giden bağlantıdır. Bilgisayarın yolu üstünde olmayan
    # bağlantılar ancak böyle bulunuyor.
    kendi_mac = {sw.id: kendi for sw, _t, kendi in okunan if kendi}
    for sw, tablo, _kendi in okunan:
        for komsu_id, komsu_mac in kendi_mac.items():
            if komsu_id == sw.id or komsu_mac not in tablo:
                continue
            komsu = env.bul(komsu_id)
            ekle(sw, tablo[komsu_mac], "baglanti",
                 f"{komsu.ad if komsu else komsu_id} bağlantısı")

    sonuc["portlar"] = sorted(portlar.values(),
                              key=lambda p: (p["switchAd"], p["port"]))
    return sonuc


def bilgisayar_portu(env: Envanter, kimlik_al=None) -> dict:
    """Yalnız bilgisayarın yeri — `korunan_portlar`ın kısa yolu."""
    return korunan_portlar(env, kimlik_al)["bilgisayar"]


# ──────────────────────────────────────────────────────── ilerleme ────────
# Betik satır satır yazıyor ve o satırların hepsi kuyruğa birer "adım"
# olarak giriyordu: iki yüz satırlık bir yığın, yüzde hep %0 (adım
# satırları sayaçlara girmiyor) ve kullanıcı hangi aşamada olduğunu
# göremiyor.
#
# Betik YENİDEN YAZILMADI. Sahada denenmiş akış bu ve kardeş projeyle
# ortak (bkz. modül başlığı, docs/MIMARI §3); onu ilerleme raporlamak
# için değiştirmek, panelin uğruna sahadaki davranışı riske atmak
# demekti. Bunun yerine çıktısı burada yapıya çevriliyor: koşunun gerçek
# iş birimi PORT, o yüzden her hedef port bir satır ve yüzde
# "biten port / toplam port".
#
# Ham çıktı kaybolmuyor; bir günlük dosyasına yazılıp kuyrukta tek
# satırla açılabiliyor (bkz. panel_api.ip_isi).

# ── betiğin işaretleri ──
# "[OK] Port 11 -> 10.1.1.21". Betik varsayılan olarak doğrulamayı sona
# bıraktığı (--no-defer-verify verilmedikçe) için bu satır çoğu koşuda HİÇ
# yazılmaz; portun bittiğini asıl söyleyen işaret _R_YAZILDI.
_R_PORT_BITTI = re.compile(r"\[OK\]\s*Port\s+(\d+)")
# "[!] Port 11: switch hatası" — iki nokta ŞART: betikte bir de
# "[!] Port 45 sn'de bağlanmadı" var ve oradaki sayı port değil, saniye.
_R_PORT_HATA = re.compile(r"\[!\]\s*Port\s+(\d+):\s*(.*)")
# Başlangıç satırı: "[1/12] Port 11 -> 10.1.1.10 (10011001)".
# Baştaki sayaç ŞART. Betik koşunun en başında planı da yazıyor
# ("   port 11  ->  10.1.1.10") ve sayacı aramayan bir kalıp o on iki
# satırı birer "port başladı" sanıp bütün portları aynı anda
# "çalışıyor"a çeviriyordu.
_R_PORT_BASLADI = re.compile(r"^\s*\[\d+/\d+\]\s*Port\s+(\d+)\s*->\s*(\S+)")
_R_TUR = re.compile(r"===\s*Tur\s+(\d+)")
# Son özet tablosu: "   11  10.1.1.21     OK" / "... EKSİK — cevap yok"
_R_OZET = re.compile(r"^\s*(\d+)\s+(\S+)\s+(OK|EKSİK)\s*(?:—\s*(.*))?$")


# ── aşamalar ──
# Koşunun tamamı ve her aşamanın çubuktaki payı. Paylar süreye göre
# değil, sahadaki ölçüme göre: on iki portluk bir koşuda port turu
# dakikalar sürüyor, son doğrulama on beş saniye. Toplam 1.00 olmalı.
#
# Aşamaların açıkça sayılmasının sebebi: yüzde eskiden yalnız "biten
# port / toplam port" idi ve portlar koşunun ortasında değil, sondaki
# özet tablosunda kapandığı için çubuk baştan sona %0, son saniyede %100
# oluyordu.
ASAMALAR = (
    ("hazirlik",  "Hazırlık — plan okunuyor, switch'e bağlanılıyor", 0.05),
    ("temel",     "Temel tarama — aralık dışındaki cihazlar",        0.07),
    ("atama",     "Port atama",                                      0.70),
    ("geri",      "PoE portları geri açılıyor",                      0.04),
    ("dogrulama", "Son doğrulama — cihazlar yeni adreslerinde mi",   0.14),
)
_ASAMA_SIRA = [a for a, _e, _p in ASAMALAR]
_ASAMA_ETIKET = {a: e for a, e, _p in ASAMALAR}
_ASAMA_PAY = {a: p for a, _e, p in ASAMALAR}
_ASAMA_BAS = {}
_toplam = 0.0
for _ad, _etiket, _pay in ASAMALAR:
    _ASAMA_BAS[_ad] = _toplam
    _toplam += _pay
del _ad, _etiket, _pay, _toplam

# Hangi çıktı satırı hangi aşamayı başlatıyor.
_ASAMA_ISARETI = (
    ("Temel tarama", "temel"),
    ("Aralıktaki tüm portlar tekrar açılıyor", "geri"),
    ("Son doğrulama", "dogrulama"),
    ("Kalıcılık kontrolü", "dogrulama"),
)

# Bir portun kendi içindeki adımlar: hangi çıktı satırı hangi adımı
# bildiriyor, o adıma gelindiğinde portun ne kadarı bitmiş sayılıyor ve
# kullanıcıya ne yazılıyor. Port turu çubuğun %70'i; tek bir port bir
# dakika sürebildiği için çubuk port içinde de ilerlemeli.
PORT_ADIMLARI = (
    ("aralıktaki portlar kapatılıyor", 0.10, "PoE portu açılıyor"),
    ("cihaz aranıyor",                 0.35, "Cihaz aranıyor"),
    ("cihaz bulundu",                  0.60, "Cihaz bulundu"),
    ("IP yazılıyor",                   0.80, "IP yazılıyor"),
    ("doğrulama:",                     0.92, "Doğrulanıyor"),
)

# Portun bittiğini söyleyen satırlar. "yazıldı (reset doğrulandı)" koşunun
# olağan bitiş işareti: betik doğrulamayı sona bıraktığı için port turu
# bittiğinde IP yazılmış ama henüz teyit edilmemiştir (bkz. YAZILDI).
_R_YAZILDI = re.compile(r"yazıldı \(reset doğrulandı\)")
_R_ZATEN_DOGRU = re.compile(r"IP zaten doğru")

# Yazıldı ama son doğrulamada teyit edilmedi. Bilerek "tamam" değil:
# cihaz reset attı, yeni adresinde cevap verdiği ise son doğrulama
# turunda anlaşılıyor. Sayaçlarda "başarılı" görünmez.
YAZILDI = "yazildi"


def port_anahtari(port: int) -> str:
    return f"p{int(port)}"


class Ilerleme:
    """Betiğin satır çıktısını iş kuyruğunun ilerlemesine çevirir.

    Üç şey üretir:

      · Her hedef port için bir SATIR (bekliyor → çalışıyor → yazıldı →
        tamam/hata).
      · O satırın altında, portun kendi ADIM geçmişi: "PoE portu
        açılıyor", "cihaz bulundu: 10.1.1.12", "IP yazılıyor". Arayüz
        bunu satıra basınca açılan kapalı bir akordiyonda gösterir.
      · İşin AŞAMASI ve yüzdesi (bkz. ASAMALAR).

    Tanımadığı satırları sessizce yutar — kuyrukta yalnız anlamı olan şey
    görünsün. `gunluk(satir)` verilirse ham çıktı oraya da gider.
    """

    def __init__(self, is_, plan_satirlari, gunluk=None):
        self._is = is_
        self._gunluk = gunluk
        self._suren: int | None = None
        self._hata_sayisi = 0
        self._portlar = []
        self._durum: dict[int, str] = {}
        self._kesir = 0.0            # süren portun kendi içindeki ilerlemesi
        self._adim_etiketi = "Başlıyor"
        self._asama = "hazirlik"
        self._ozet = 0               # özet tablosunda okunan satır sayısı
        self._tur = 1
        for s in plan_satirlari:
            if not s.get("uygulanabilir"):
                continue
            port = int(s["port"])
            self._portlar.append(port)
            self._durum[port] = "bekliyor"
            is_.ozel_satir(
                port_anahtari(port), f"Port {port} · {s['ad']}",
                durum="bekliyor", not_=f"hedef {s['hedefIp']}",
                sayilir=True)
        self._asama_gec("hazirlik")

    @property
    def hata_sayisi(self) -> int:
        return self._hata_sayisi

    # ---- aşama ve yüzde ----
    def _asama_gec(self, ad: str) -> None:
        """Aşamayı ilerletir. Geri gitmez: 'Tur 2' koşuyu başa almaz."""
        if _ASAMA_SIRA.index(ad) >= _ASAMA_SIRA.index(self._asama):
            if ad != self._asama:
                self._asama = ad
                self._kesir = 0.0
        self._bildir()

    def _biten_port(self) -> int:
        """Port turu açısından kapanmış portlar.

        Hata alan port kapanmış sayılmaz: bir sonraki turda yeniden
        denenecek. Sayı hiç azalmadığı için çubuk da geri gitmez.
        """
        return sum(1 for p in self._portlar
                   if self._durum.get(p) in (YAZILDI, "tamam"))

    def _ic_oran(self) -> float:
        if self._asama == "atama":
            if not self._portlar:
                return 1.0
            return (self._biten_port() + self._kesir) / len(self._portlar)
        if self._asama == "dogrulama":
            if not self._portlar:
                return 1.0
            return self._ozet / len(self._portlar)
        return 0.0

    def _asama_metni(self) -> str:
        toplam = len(self._portlar)
        if self._asama == "atama":
            tur = f"{self._tur}. tur · " if self._tur > 1 else ""
            if self._suren is None:
                return f"{tur}Port atama ({self._biten_port()}/{toplam})"
            adim = self._adim_etiketi
            return (f"{tur}Port {self._suren} · {adim} "
                    f"({self._biten_port()}/{toplam})")
        if self._asama == "dogrulama" and self._ozet:
            return f"{_ASAMA_ETIKET[self._asama]} ({self._ozet}/{toplam})"
        return _ASAMA_ETIKET[self._asama]

    def _bildir(self) -> None:
        oran = _ASAMA_BAS[self._asama] + _ASAMA_PAY[self._asama] * min(
            1.0, max(0.0, self._ic_oran()))
        self._is.ilerleme_yaz(oran)
        self._is.asama_yaz(self._asama_metni())

    # ---- satır ----
    def _yaz(self, port: int, durum: str, not_: str = "",
             adim: str = "") -> None:
        if port not in self._portlar:
            return
        self._durum[port] = durum
        self._is.satir_guncelle(port_anahtari(port), durum, not_)
        if adim:
            self._is.adim_ekle(port_anahtari(port), adim, durum)

    def _adim(self, port: int, metin: str, durum: str = "bilgi") -> None:
        if port in self._portlar:
            self._is.adim_ekle(port_anahtari(port), metin, durum)

    def satir(self, metin: str) -> None:
        ham = metin.rstrip()
        if self._gunluk:
            self._gunluk(ham)
        if not ham.strip():
            return

        for anahtar, asama in _ASAMA_ISARETI:
            if anahtar in ham:
                self._suren = None
                self._asama_gec(asama)
                break

        # Başlangıç: "[1/12] Port 11 -> 10.1.1.10 (10011001)"
        m = _R_PORT_BASLADI.match(ham)
        if m:
            port = int(m.group(1))
            if port in self._portlar:
                self._suren = port
                self._kesir = 0.0
                self._adim_etiketi = "Başlıyor"
                self._yaz(port, "calisiyor", f"{m.group(2)} yazılacak",
                          adim=f"{m.group(2)} yazılacak")
                self._asama_gec("atama")
            return

        m = _R_TUR.search(ham)
        if m:
            self._tur = int(m.group(1))
            self._suren = None
            self._asama_gec("atama")
            return

        m = _R_PORT_BITTI.search(ham)        # "[OK] Port 11 -> ..."
        if m:
            self._bitti(int(m.group(1)), "tamam", "IP yazıldı ve doğrulandı")
            return

        m = _R_PORT_HATA.search(ham)
        if m:
            port, sebep = int(m.group(1)), m.group(2).strip()
            self._hata_sayisi += 1
            self._bitti(port, "hata", sebep or "tamamlanamadı")
            return

        m = _R_OZET.match(ham)
        if m:
            # Son tablo son sözü söyler: tur içinde "hata" görünen bir port
            # sonraki turda tamamlanmış, "yazıldı" görünen bir port ise
            # yeni adresinde cevap vermemiş olabilir.
            port, hedef, durum, sebep = (
                int(m.group(1)), m.group(2), m.group(3), (m.group(4) or ""))
            if port in self._portlar:
                self._ozet += 1
            if durum == "OK":
                self._yaz(port, "tamam", f"{hedef} doğrulandı",
                          adim=f"{hedef} doğrulandı")
            else:
                self._yaz(port, "hata", sebep.strip() or "cevap yok",
                          adim=f"Son doğrulama: {sebep.strip() or 'cevap yok'}")
            self._bildir()
            return

        if self._suren is None or not ham.startswith("    "):
            return

        # ── süren portun altındaki ayrıntı satırları ──
        ayrinti = ham.strip()
        port = self._suren

        if _R_YAZILDI.search(ayrinti):
            # Koşunun olağan bitiş işareti: IP yazıldı, cihaz reset attı.
            # Teyit son doğrulama turunda gelecek.
            self._bitti(port, YAZILDI,
                        "IP yazıldı, son doğrulama bekleniyor")
            return
        if _R_ZATEN_DOGRU.search(ayrinti):
            self._bitti(port, YAZILDI, "IP zaten doğruydu")
            return

        for anahtar, kesir, etiket in PORT_ADIMLARI:
            if anahtar in ayrinti:
                self._kesir = max(self._kesir, kesir)
                self._adim_etiketi = etiket
                self._is.satir_guncelle(port_anahtari(port), "calisiyor",
                                        ayrinti[:160])
                break

        # "[!] 10.1.1.12 bu portta değil (...) — eleniyor" gibi satırlar
        # portu düşürmez ama sebebi anlatan tek kayıttır.
        self._adim(port, ayrinti, "uyari" if ayrinti.startswith("[!]") else "bilgi")
        self._bildir()

    def _bitti(self, port: int, durum: str, not_: str) -> None:
        self._yaz(port, durum, not_, adim=not_)
        if port == self._suren:
            self._suren = None
            self._kesir = 0.0
        self._bildir()

    def bitir(self) -> None:
        """Kalan satırları kapatır ve aşamayı temizler."""
        for port in self._portlar:
            d = self._durum.get(port, "bekliyor")
            if d in ("bekliyor", "calisiyor"):
                self._yaz(port, "atlandi", "Koşu bu porta ulaşmadan bitti",
                          adim="Koşu bu porta ulaşmadan bitti")
            elif d == YAZILDI:
                # Koşu son doğrulamaya varmadan bitti (iptal, çökme):
                # IP yazıldı ama teyit edilmedi — "tamam" demek yanlış olur.
                self._yaz(port, "uyari",
                          "IP yazıldı ama son doğrulama yapılamadı",
                          adim="Son doğrulama yapılamadı")
        # Yüzde ancak koşu kendi sonuna vardıysa doluyor: iptal edilen bir
        # koşuyu %100 göstermek, yarıda kalan işi bitmiş gibi okutur.
        if not self._portlar or self._ozet >= len(self._portlar):
            self._is.ilerleme_yaz(1.0)
        self._is.asama_yaz("")


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
    # Fabrika adresi her zaman açıkça verilir: betiğin kendi varsayılanı
    # şablon (10.n.1.12) ve set numarasıyla çözülüyor; cihazlar ise sete
    # bakmadan hep aynı adresle geliyor.
    fabrika = str(ayarlar.get("fabrikaIp") or "").strip() or fabrika_ip()
    argv += ["--factory-ip", fabrika]

    # Sete göre çözülmüş adres de denenir. Fabrika adresi sabitlenmeden
    # önce koşu cihazı 10.n.1.12'de arıyordu; sahadaki cihazların bir
    # kısmı hâlâ orada duruyor ve yalnız sabit adrese bakmak onları
    # "bulunamadı" yapıyor. Maliyeti tek bir adres, bulamamanın maliyeti
    # bütün koşu.
    ek = []
    set_adresi = coz("10.n.1.12", env.set_no)
    if set_adresi != fabrika:
        ek.append(set_adresi)
    satir_geri(f"[Intercom] Fabrika adresi: {fabrika}"
               + (f" (ayrıca {set_adresi} denenecek)" if ek else ""))

    # Fabrika adresinde olmayan cihazlar için ek aday adresler. Betik
    # zaten fabrika IP'sini ve DeviceMap'teki bütün intercom adreslerini
    # deniyor; buradakiler onların üstüne eklenir.
    arama = arama_adaylari(ayarlar.get("aramaAgi"), ayarlar.get("aramaMaskesi"),
                           bas=ayarlar.get("aramaBas") or "",
                           son=ayarlar.get("aramaSon") or "")
    if arama:
        satir_geri(f"[Intercom] Ek arama ağı: {len(arama)} adres "
                   f"({arama[0]} – {arama[-1]})")
    ek = list(dict.fromkeys(ek + arama))
    if ek:
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
