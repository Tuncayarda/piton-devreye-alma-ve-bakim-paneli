#!/usr/bin/env python3
"""KYLAND switch okuması — Switch Yönetim Paneli'nin çalışan erişimi.

Burada switch'e bağlanan ikinci bir uygulama YOKTUR. Kardeş projedeki
`betikler/switch_api.py` dosyası çalışma anında
içe aktarılır ve onun doğrulanmış çağrıları kullanılır:

    sw_get(ip, "stat/basicInfo", timeout, kimlik=(kullanıcı, parola))

Böylece URL, Basic Auth biçimi, port, timeout, header ve "JSON gelmiyorsa
oturum açılması gerekiyor" kuralı iki panelde birebir aynı olur. Aynı
hesap orada çalışıyorsa burada da çalışır; ayrıştıkları bir yer kalmaz.

`kimlik` her çağrıda açıkça verilir. Verildiği sürece switch_api kendi
modül içi kimlik deposuna hiç bakmaz; bu panelin kimlikleri yalnızca
core/kimlik.py içinde durur.
"""
from __future__ import annotations

from . import ayar, betik
from .hata import (DogrulamaHatasi, KimlikHatasi, UlasilamadiHatasi, sinifla)

# basicInfo cevabında aranan alanlar. Hiçbiri yoksa dönen JSON switch
# verisi değildir — 200 gelmiş olması tek başına yeterli sayılmaz.
BEKLENEN_ALANLAR = ("deviceName", "sysName", "deviceType", "model",
                    "softVer", "softwareVersion", "macAddress", "mac")


def _yukle():
    return betik.switch_api()


def modul():
    """Testlerin ve diğer modüllerin aynı örneğe ulaşması için."""
    return _yukle()


def _bilgi_govdesi(veri):
    """basicInfo cevabından künye sözlüğünü çıkarır."""
    if not isinstance(veri, dict):
        raise DogrulamaHatasi("Switch beklenen künye verisini döndürmedi")
    govde = veri.get("basicInfo", veri)
    if isinstance(govde, list):
        govde = govde[0] if govde and isinstance(govde[0], dict) else {}
    if not isinstance(govde, dict):
        raise DogrulamaHatasi("Switch beklenen künye verisini döndürmedi")
    return govde


def dogrula(veri) -> dict:
    """Cevabın gerçekten switch künyesi olduğunu doğrular.

    HTTP 200 + JSON yetmez: uç değişmiş, başka bir cihaz oturmuş ya da
    vekil sunucu araya girmiş olabilir. Beklenen alanlardan en az biri
    dolu gelmeliyiz.
    """
    govde = _bilgi_govdesi(veri)
    dolu = {k: v for k, v in govde.items()
            if k in BEKLENEN_ALANLAR and str(v).strip()}
    if not dolu:
        raise DogrulamaHatasi(
            "Cihaz yanıt verdi ama switch künyesi değil "
            "(beklenen alanlar yok)")
    return govde


def calisma_saniyesi(govde: dict):
    """Switch'in çalışma süresi — saniye.

    KYLAND tek bir `uptime` alanı vermiyor; süre `operateTime` altında
    parçalı geliyor:

        "operateTime": {"day": "0", "hour": "7", "minute": "30",
                        "second": "39"}

    Tek isim aranınca hiçbir şey bulunamıyor ve sütun boş kalıyordu.
    """
    for ad in ("upTime", "uptime", "systemUptime"):
        if str(govde.get(ad, "")).strip():
            return govde[ad]

    parcali = govde.get("operateTime")
    if not isinstance(parcali, dict):
        return None
    carpan = {"day": 86400, "hour": 3600, "minute": 60, "second": 1}
    toplam, bulundu = 0, False
    for ad, kat in carpan.items():
        deger = parcali.get(ad)
        if deger in (None, ""):
            continue
        try:
            toplam += int(float(deger)) * kat
        except (TypeError, ValueError):
            return None
        bulundu = True
    return toplam if bulundu else None


def oku(ip: str, kimlik: tuple[str, str] | None = None,
        timeout: float | None = None) -> dict:
    """Switch künyesini okur.

    Döner: {"ad", "model", "surum", "mac", "calisma", "ham"}
    Fırlatır: KimlikHatasi / UlasilamadiHatasi / DogrulamaHatasi
    """
    api = _yukle()
    sure = timeout if timeout is not None else ayar.OKUMA_TIMEOUT
    try:
        veri = api.sw_get(ip, "stat/basicInfo", timeout=sure, kimlik=kimlik)
    except api.YetkiHatasi as exc:
        # 401/403, WWW-Authenticate ya da JSON yerine oturum sayfası
        raise KimlikHatasi(str(exc) or "Cihaz kullanıcı adı/parola istiyor")
    except Exception as exc:                       # ağ / HTTP katmanı
        durum = getattr(getattr(exc, "response", None), "status_code", None)
        if durum in (401, 403):
            raise KimlikHatasi("Cihaz kullanıcı adı/parola istiyor")
        raise sinifla(exc)

    govde = dogrula(veri)
    return {
        "ad": govde.get("deviceName") or govde.get("sysName") or "",
        "model": govde.get("deviceType") or govde.get("model") or "",
        "surum": govde.get("softVer") or govde.get("softwareVersion") or "",
        "mac": govde.get("macAddress") or govde.get("mac") or "",
        "calisma": calisma_saniyesi(govde),
        "ham": govde,
    }


def portlar(ip: str, kimlik: tuple[str, str] | None = None,
            timeout: float | None = None) -> list[dict]:
    """Port listesi — IP atama ekranındaki ön panel için.

    Switch Yönetim Paneli'ndeki uçların ve birleştirme sırasının aynısı
    kullanılır (portMode + poePort + poeStatus). Ön panelin renkleri iki
    uygulamada aynı veriden çıksın diye üç uç da okunur: yalnız portMode
    ile "besliyor" ile "bağlı" ayırt edilemiyor.

    PoE uçları her modelde yok; yoksa alanlar boş kalır, uydurulmaz.
    """
    api = _yukle()
    sure = timeout if timeout is not None else ayar.OKUMA_TIMEOUT

    def cek(uc: str):
        try:
            return api.sw_get(ip, uc, timeout=sure, kimlik=kimlik)
        except api.YetkiHatasi as exc:
            raise KimlikHatasi(str(exc) or "Cihaz kullanıcı adı/parola istiyor")
        except Exception as exc:
            raise sinifla(exc)

    pm = cek("stat/portMode")
    liste = pm.get("portMode", []) if isinstance(pm, dict) else []
    if not isinstance(liste, list):
        raise DogrulamaHatasi("Switch port listesi beklenen biçimde değil")

    def istege_bagli(uc: str, anahtar: str) -> dict:
        """PoE uçları modele göre olmayabilir; kimlik hatası yutulmaz."""
        try:
            veri = cek(uc)
        except KimlikHatasi:
            raise
        except Exception:
            return {}
        kayit = veri.get(anahtar, []) if isinstance(veri, dict) else []
        return {int(p["pid"]): p for p in kayit
                if isinstance(p, dict) and str(p.get("pid", "")).isdigit()}

    poe = istege_bagli("stat/poePort", "poePort")
    guc = istege_bagli("stat/poeStatus", "poeStatus")

    cikan = []
    for p in liste:
        if not isinstance(p, dict):
            continue
        pid = int(p.get("pid", 0))
        pp = poe.get(pid, {})
        gs = guc.get(pid, {})
        watt = gs.get("powerUsed")
        cikan.append({
            "pid": pid,
            "tip": p.get("type", ""),
            "acik": bool(p.get("adminStat")),
            "link": p.get("linkStat", ""),
            "poe": pid in poe,
            "poeMod": str(pp.get("poeMode", "")),
            "poeDurum": gs.get("portStatus", ""),
            # Switch gücü on kat büyük tam sayı olarak veriyor.
            "guc": round(int(watt) / 10, 1) if str(watt).isdigit() else None,
        })
    return cikan


def mac_tablosu(ip: str, kimlik: tuple[str, str] | None = None,
                timeout: float | None = None) -> dict[str, int]:
    """Switch'in MAC öğrenme tablosu: {mac: port}.

    Uçlar ve ayrıştırma IP atama betiğinden gelir; koşu bu tabloyu zaten
    okuyup portu doğruluyor (bkz. betikler/intercom_ip_assign.py). İkinci
    bir ayrıştırıcı yazmak, KYLAND cevabının biçimi değiştiğinde ikisinin
    ayrışması demekti — betik sahada, bu panel laboratuvarda kırılırdı.
    HTTP yolu ise panelin kendi yolu: kimlik core/kimlik.py'de duruyor,
    betiğin modül içi deposuna hiç bakılmıyor.

    Switch cevap veriyor ama MAC uçlarının hiçbirini tanımıyorsa boş
    sözlük döner — bu bir hata değil, o modelde tablo yok demek.
    Switch'e HİÇ ulaşılamıyorsa UlasilamadiHatasi fırlatır: "kapalı" ile
    "tabloyu vermiyor" çağıran taraf için bambaşka iki durum (biri
    switch'e, öteki kabloya bakmayı gerektiriyor).
    """
    api = _yukle()
    kosu = betik.intercom_ip_assign()
    sure = timeout if timeout is not None else ayar.OKUMA_TIMEOUT
    # Betiğin özel adları: kasten kullanılıyor, gerekçesi yukarıda.
    uclar = getattr(kosu, "MAC_ENDPOINTS", ["stat/macQuery"])
    ayristir = getattr(kosu, "_parse_mac_table", None)
    if ayristir is None:
        return {}

    son_hata = None
    for uc in uclar:
        try:
            veri = api.sw_get(ip, uc, timeout=sure, kimlik=kimlik)
        except api.YetkiHatasi as exc:
            raise KimlikHatasi(str(exc) or "Switch kullanıcı adı/parola istiyor")
        except Exception as exc:
            hata = sinifla(exc)
            # Ulaşılamayan switch'te kalan uçları denemenin anlamı yok:
            # üç uç × zaman aşımı, arayüzü açan kişiyi yarım dakika
            # bekletiyordu. 404 böyle değil — o uç yok, öteki olabilir.
            if isinstance(hata, UlasilamadiHatasi):
                raise hata
            son_hata = hata
            continue
        son_hata = None                  # switch konuştu; sorun uçta
        tablo = ayristir(veri)
        if tablo:
            return {str(m).lower(): int(p) for m, p in tablo.items()}
    if son_hata is not None:
        raise son_hata
    return {}


__all__ = ["oku", "portlar", "mac_tablosu", "dogrula", "modul",
           "KimlikHatasi", "UlasilamadiHatasi", "DogrulamaHatasi"]
