#!/usr/bin/env python3
"""Bu bilgisayarın ağ kimliği — hangi arayüz, hangi MAC.

IP atama koşusu, bilgisayarın takılı olduğu switch portuna dokunmamalı:
o portun PoE'sini kapatmak koşunun kendi yolunu kesiyor. Port numarası
şimdiye kadar elle giriliyordu; buradaki işler onu switch'in MAC
tablosundan bulmak için gereken yarıyı üretir (diğer yarısı
`core.switch_okuma.mac_tablosu`).

Parola, kimlik ya da kullanıcıya ait başka hiçbir bilgi okunmaz; yalnız
yerel arayüz adı, IP'si ve MAC'i.

Neden işletim sistemi komutu: Python'un standart kütüphanesi arayüz
MAC'ini vermiyor (`uuid.getnode()` tek ve rastgele olabilen bir değer
döndürüyor, çok arayüzlü makinede hangi kartı verdiği belli değil).
Ek bağımlılık (psutil) tek bir alan için ağır kalıyordu.

Çıktı ETİKETE GÖRE ayrıştırılmaz. `ipconfig /all` Türkçe Windows'ta
"Fiziksel Adres", İngilizce'de "Physical Address" yazıyor; etiket
aramak yerel ayara bağlı bir arayüz demekti. Onun yerine çıktı arayüz
bloklarına bölünüp her blokta MAC KALIBI ve aranan IP'nin kendisi
aranıyor — ikisi de dile bağlı değil.
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys

# Hem 00:11:22:33:44:55 hem 00-11-22-33-44-55 (Windows) biçimi.
_MAC_KALIBI = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")

_IPV4_KALIBI = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")

# Yerel yönetimli / anlamsız MAC'ler: bir port eşleşmesi üretemezler.
_BOS_MAC = {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"}

KOMUT_TIMEOUT = 4.0

# Komut çıktısı BAYT alınıp burada çözülür; `text=True` kullanılmaz.
#
# `text=True` çözümü Python'a bırakıyor, Python da Windows'ta ANSI kod
# sayfasını seçiyor (Türkçe kurulumda cp1254). Oysa konsol araçları OEM
# kod sayfasıyla yazıyor (cp857). `ipconfig /all` çıktısının ilk
# satırındaki "Yapılandırması" kelimesinin "ı" harfi cp857'de 0x8d ve o
# bayt cp1254'te TANIMSIZ: UnicodeDecodeError.
#
# Bu hata ne OSError ne SubprocessError; aşağıdaki `except` onu
# yakalamıyordu ve istisna /api/ip/korunan ucuna kadar çıkıp 500
# veriyordu. Sonuç: Windows'ta bilgisayarın switch portu hiç bulunamıyor,
# korunacak portlar boş kalıyordu. macOS/Linux'ta hem çıktı hem tercih
# edilen kod sayfası UTF-8 olduğu için sorun hiç görünmedi.
#
# Aranan her şey ASCII (MAC kalıbı, IPv4, arayüz adı); yanlış çözülmüş
# bir Türkçe harf ayrıştırmayı etkilemez. Bu yüzden errors="replace"
# burada kayıpsızdır ve "çözemedim" diye bir durum kalmaz.
_KOD_SAYFASI = "oem" if sys.platform == "win32" else "utf-8"

# Konsolsuz (pencereli) Windows derlemesinde her komut için bir konsol
# penceresi açılıp kapanıyor: hem göze çarpıyor hem kullanıcının odağını
# çalıyor. Arayüz dökümü switch başına değil tur başına okunsa da
# görünüyordu.
_PENCERESIZ = ({"creationflags": 0x08000000}      # CREATE_NO_WINDOW
               if sys.platform == "win32" else {})


def coz(ham: bytes) -> str:
    """Komut çıktısını metne çevirir — hiçbir kod sayfasında patlamaz."""
    try:
        return (ham or b"").decode(_KOD_SAYFASI, errors="replace")
    except LookupError:               # kod sayfası bu Python'da yoksa
        return (ham or b"").decode("latin-1", errors="replace")


def normalle(deger) -> str:
    """5c-1-3B-8A-76-43 / 5c01.3b8a.7643 -> 5c:01:3b:8a:76:43"""
    if not deger:
        return ""
    onaltilik = re.findall(r"[0-9a-fA-F]{1,2}", str(deger).replace(".", ""))
    if len(onaltilik) < 6:
        return ""
    return ":".join(h.rjust(2, "0").lower() for h in onaltilik[:6])


def yerel_ip(hedef_ip: str) -> str:
    """`hedef_ip`'ye giderken kullanılan yerel adres.

    UDP soketi bağlamak paket göndermez; çekirdeğin yönlendirme tablosuna
    "bu adrese hangi arayüzden çıkarım" diye sormanın taşınabilir yolu.
    """
    if not hedef_ip:
        return ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect((str(hedef_ip), 9))
            return s.getsockname()[0]
    except OSError:
        return ""


def _komut(argv: list[str]) -> str:
    try:
        sonuc = subprocess.run(argv, capture_output=True,
                               timeout=KOMUT_TIMEOUT, **_PENCERESIZ)
    except (OSError, subprocess.SubprocessError):
        return ""
    return coz(sonuc.stdout)


def _cikti() -> str:
    """Platformun arayüz dökümü. İlk dolu cevap kullanılır."""
    if sys.platform == "win32":
        adaylar = [["ipconfig", "/all"]]
    else:
        # ifconfig birçok Linux dağıtımında artık kurulu değil; `ip` varsa
        # o kullanılır. macOS'ta yalnız ifconfig var.
        adaylar = [["ifconfig", "-a"], ["ip", "-o", "addr"], ["ifconfig"]]
    for argv in adaylar:
        metin = _komut(argv)
        if metin.strip():
            return metin
    return ""


def _bloklar(metin: str) -> list[str]:
    """Çıktıyı arayüz bloklarına böler.

    Üç biçimde de yeni arayüz, girintisiz bir satırla başlar:
      ifconfig : "en0: flags=8863<UP,...> mtu 1500"
      ip -o    : "2: eth0    inet 10.1.1.50/16 ..."  (her satır kendi bloğu)
      ipconfig : "Ethernet adapter Ethernet:"
    """
    bloklar: list[list[str]] = []
    for satir in metin.splitlines():
        if satir.strip() and not satir[0].isspace():
            bloklar.append([satir])
        elif bloklar:
            bloklar[-1].append(satir)
    return ["\n".join(b) for b in bloklar]


def _blok_maci(blok: str) -> str:
    for eslesme in _MAC_KALIBI.findall(blok):
        mac = normalle(eslesme)
        if mac and mac not in _BOS_MAC:
            return mac
    return ""


def _blok_ipleri(blok: str) -> list[str]:
    return _IPV4_KALIBI.findall(blok)


def arayuzler() -> list[dict]:
    """[{"ad", "mac", "ipler"}] — MAC'i okunabilen bütün yerel arayüzler.

    Bir kez çağrılıp elde tutulması beklenir: her çağrı bir işletim
    sistemi komutu çalıştırıyor, birden çok switch sorgulanırken bunu
    switch başına yapmanın anlamı yok.
    """
    cikan, gorulen = [], set()
    for blok in _bloklar(_cikti()):
        mac = _blok_maci(blok)
        if not mac or mac in gorulen:
            continue
        gorulen.add(mac)
        cikan.append({
            "ad": blok.splitlines()[0].split(":")[0].strip(),
            "mac": mac,
            "ipler": _blok_ipleri(blok),
        })
    return cikan


def hedefe_giden_mac(hedef_ip: str, hepsi: list[dict] | None = None) -> dict:
    """`hedef_ip`'ye çıkan arayüzün MAC'i.

    `hepsi` verilirse arayüz dökümü yeniden okunmaz (bkz. arayuzler).

    Döner: {"mac", "ad", "yerelIp", "adaylar"}. `mac` boşsa arayüz
    saptanamamıştır; `adaylar` yine de bütün yerel MAC'leri taşır —
    switch'in MAC tablosunda hepsi denenebilir, biri tutarsa port yine
    bulunur. Uydurma bir değer döndürülmez.
    """
    hepsi = arayuzler() if hepsi is None else hepsi
    adaylar = [a["mac"] for a in hepsi]
    ip = yerel_ip(hedef_ip)
    if ip:
        # Karşılaştırma tam eşitlik: "10.1.1.5" ararken "10.1.1.50"
        # tutmasın diye metin içinde arama yapılmıyor.
        for a in hepsi:
            if ip in a["ipler"]:
                return {"mac": a["mac"], "ad": a["ad"], "yerelIp": ip,
                        "adaylar": adaylar}
    return {"mac": "", "ad": "", "yerelIp": ip, "adaylar": adaylar}
