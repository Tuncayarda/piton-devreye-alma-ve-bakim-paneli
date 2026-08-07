#!/usr/bin/env python3
"""Yazılım yükleme — iki cihaz ailesi, iki yol.

**Anons ekipmanları (HTTP).** Cihazın kendi web arayüzüyle aynı biçim
kullanılır: multipart/form-data, alan adı "firmware", uç
/api/v1/system/firmware. Yükleme sonrası cihaz yeniden başlar.

**Compartment LCD (ADB).** Android; imaj yerine APK kurulur:
`adb install -r`. Yeni sürüm, panelin okuma tarafındaki `dumpsys package`
ile aynı yerden doğrulanır (bkz. okuma.paket_bilgisi).

İki yolda da HTTP 200 / "Success" tek başına başarı sayılmaz: cihaz
yeniden okunur ve uygulamanın gerçekten yeni sürümü bildirdiği görülür.

Dosya CİHAZ BAŞINA seçilir. Aynı gruptaki iki cihaz aynı dosyayı almak
zorunda değil: sahada bir intercom eski donanım revizyonundan olabiliyor
ve grubun geri kalanıyla aynı .bin'i almıyor. Tek bir "seçili dosya"
tutulduğunda bunu görmenin yolu yoktu — yükleme başlıyor, yanlış imaj
gidiyordu. Kolaylık için bir dosya tek çağrıda bütün gruba atanabilir
(bkz. panel_api /api/firmware/sec, `grup` kapsamı).

Dosya kullanıcıdan alınır ve sunucuda yalnızca yolu tutulur — panel
imajı kendi dizinine kopyalamaz, saklamaz. Seçim yalnız bellektedir;
uygulama kapanınca gider (bkz. panel_api.temizle).
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

import requests

from . import ayar, okuma
from .device_map import Cihaz
from .hata import (DogrulamaHatasi, KimlikHatasi, UlasilamadiHatasi,
                   UygulanmazHatasi, sinifla)

# Cihazın kendi arayüzünün kullandığı uç ve parça biçimi; sahadaki
# cihazın tarayıcı isteğinden birebir alındı. Uç "update" değil
# "firmware" — yanlış adrese giden yükleme HTTP 404 ile düşüyordu.
YUKLEME_UCU = "api/v1/system/firmware"
ALAN_ADI = "firmware"
# Parçanın Content-Type'ı da cihazın kendi arayüzündeki gibi bırakıldı.
PARCA_TURU = "application/macbinary"
EN_BUYUK = 32 * 1024 * 1024          # 32 MB — bu cihazların imajları çok küçük

# Yöntem -> beklenen dosya uzantısı. Dosya seçicinin süzgeci ve ekrandaki
# yardım metni buradan gelir; APK bekleyen cihaza .bin seçtirmenin bir
# anlamı yok.
UZANTI = {"http": "bin", "adb": "apk"}


def destekli(cihaz: Cihaz) -> bool:
    """Bu cihaza yazılım yüklenebilir mi?"""
    return cihaz.yontem in UZANTI


def uzanti(cihaz: Cihaz) -> str:
    """Cihazın beklediği dosya uzantısı ("bin" / "apk")."""
    return UZANTI.get(cihaz.yontem, "")

# cihaz kimliği -> {"yol": Path, "boyut": int, "surum": str}
_SECILI: dict[str, dict] = {}
_KILIT = threading.Lock()


def dosya_dogrula(yol: str) -> tuple[Path, int]:
    """Yolu denetler; (yol, boyut) döndürür. Geçersizse ValueError.

    Yükleme anında değil, kullanıcı yolu girer girmez çağrılır: yanlış
    yazılmış bir yolu ancak koşu sırasında öğrenmek, cihazlar sırayla
    yüklenirken en kötü zamanda öğrenmek demek.
    """
    p = Path(str(yol or "").strip()).expanduser()
    if not p.is_file():
        raise ValueError(f"Dosya bulunamadı: {p.name or yol}")
    boyut = p.stat().st_size
    if boyut == 0:
        raise ValueError("Dosya boş")
    if boyut > EN_BUYUK:
        raise ValueError(f"Dosya çok büyük ({boyut // 1024 // 1024} MB)")
    return p, boyut


def dosya_sec(cihaz_idler, yol: str, surum: str = "") -> dict:
    """İmajı verilen cihazlara atar (yalnızca bellekte tutulur).

    Dönüş: atanan cihazların seçim künyesi.
    """
    idler = [str(i) for i in (cihaz_idler or []) if str(i).strip()]
    if not idler:
        raise ValueError("Cihaz seçilmedi")
    p, boyut = dosya_dogrula(yol)
    kayit = {"yol": p, "boyut": boyut, "surum": str(surum or "").strip()[:32]}
    with _KILIT:
        for i in idler:
            _SECILI[i] = dict(kayit)
    return secilenler(idler)


def surum_yaz(cihaz_idler, surum: str) -> dict:
    """Seçili imajın hedef sürümünü değiştirir (dosyaya dokunmadan).

    Hedef sürüm dosyadan okunamıyor, kullanıcı yazıyor; dosyayı yeniden
    seçtirmek için bir sebep değil.
    """
    temiz = str(surum or "").strip()[:32]
    idler = [str(i) for i in (cihaz_idler or [])]
    with _KILIT:
        for i in idler:
            if i in _SECILI:
                _SECILI[i]["surum"] = temiz
    return secilenler(idler)


def sil(cihaz_idler) -> int:
    """Verilen cihazların seçimini kaldırır; kaç tanesi silindi döner."""
    with _KILIT:
        return sum(1 for i in (cihaz_idler or [])
                   if _SECILI.pop(str(i), None) is not None)


def _dto(kayit: dict | None) -> dict:
    if not kayit:
        return {"secili": False, "ad": "", "yol": "", "boyut": 0, "surum": ""}
    return {
        "secili": True,
        "ad": kayit["yol"].name,
        # Tam yol da gider: satırda dosya adı görünür, ipucu metninde
        # nereden geldiği yazar. Servis yalnız 127.0.0.1 dinliyor ve yol
        # kullanıcının kendi seçtiği yol.
        "yol": str(kayit["yol"]),
        "boyut": kayit["boyut"],
        "surum": kayit["surum"],
    }


def secilenler(cihaz_idler=None) -> dict:
    """{cihazId: künye} — id verilmezse seçili olan bütün cihazlar."""
    with _KILIT:
        if cihaz_idler is None:
            return {i: _dto(k) for i, k in _SECILI.items()}
        return {str(i): _dto(_SECILI.get(str(i))) for i in cihaz_idler}


def secili_of(cihaz_id: str) -> dict:
    with _KILIT:
        return _dto(_SECILI.get(str(cihaz_id)))


def secili_var(cihaz_id: str) -> bool:
    with _KILIT:
        return str(cihaz_id) in _SECILI


def temizle() -> None:
    with _KILIT:
        _SECILI.clear()


def yukle(cihaz: Cihaz, kimlik=None, dogrula_sure: float = 45.0) -> dict:
    """Bu cihaz için seçili dosyayı yükler ve sürümü doğrular.

    Yol cihazın yöntemine göre ayrılır: anons ekipmanı HTTP ile imaj
    alır, Compartment LCD adb ile APK.
    """
    if not destekli(cihaz):
        raise UygulanmazHatasi(
            "Bu cihaz türünde yazılım yükleme tanımlı değil")
    with _KILIT:
        kayit = _SECILI.get(str(cihaz.id))
    if kayit is None:
        raise ValueError("Bu cihaz için yüklenecek dosya seçilmedi")
    yol, beklenen = kayit["yol"], kayit["surum"]
    # Dosya seçildikten sonra silinmiş/taşınmış olabilir; koşu ortasında
    # açılamayan dosya yerine önce anlaşılır hata.
    if not Path(yol).is_file():
        raise ValueError(f"Seçilen dosya artık yok: {Path(yol).name}")

    if cihaz.yontem == "adb":
        return _apk_kur(cihaz, yol, beklenen, dogrula_sure)
    return _imaj_yukle(cihaz, yol, beklenen, kimlik, dogrula_sure)


def _imaj_yukle(cihaz: Cihaz, yol, beklenen: str, kimlik,
                dogrula_sure: float) -> dict:
    """Anons ekipmanı — HTTP multipart."""
    onceki = ""
    try:
        onceki = okuma.anons_oku(cihaz.ip, kimlik).get("surum", "")
    except KimlikHatasi:
        raise
    except Exception:
        pass

    auth = tuple(kimlik) if kimlik else None
    try:
        with open(yol, "rb") as f:
            r = requests.post(
                f"http://{cihaz.ip}:{ayar.ANONS_PORT}/{YUKLEME_UCU}",
                files={ALAN_ADI: (Path(yol).name, f, PARCA_TURU)},
                timeout=120, auth=auth)
    except Exception as exc:
        raise sinifla(exc)
    if r.status_code in (401, 403):
        raise KimlikHatasi("Cihaz kullanıcı adı/parola istiyor")
    if r.status_code >= 400:
        raise DogrulamaHatasi(f"Cihaz yüklemeyi reddetti (HTTP {r.status_code})")

    # Cihaz yeniden başlıyor: sürümü ancak geri geldiğinde okuyabiliriz.
    bitis = time.time() + dogrula_sure
    yeni = ""
    while time.time() < bitis:
        time.sleep(2.0)
        try:
            yeni = okuma.anons_oku(cihaz.ip, kimlik,
                                   timeout=2.5).get("surum", "")
            if yeni:
                break
        except Exception:
            continue

    if not yeni:
        raise DogrulamaHatasi(
            "Yükleme gönderildi ama cihaz doğrulama süresi içinde geri "
            "dönmedi — sürüm okunamadı")
    if beklenen and str(yeni).strip() != str(beklenen).strip():
        raise DogrulamaHatasi(
            f"Cihaz {yeni} sürümünü bildiriyor, beklenen {beklenen}")
    return {"onceki": onceki, "yeni": yeni,
            "degisti": bool(onceki) and str(onceki) != str(yeni)}


# ────────────────────────────────────────────────── Compartment LCD (APK) ──
# Cihaz Android; yükleme `adb install -r` ile yapılır. Sürüm okuması
# panelin tarama tarafıyla aynı yerden gelir (dumpsys package →
# okuma.paket_bilgisi), yani "kuruldu" kararı ile ekrandaki sürüm aynı
# kaynaktan doğar.
#
# Kurulum cihazı yeniden başlatmaz; uygulamanın kendisi yeniden kurulur.
# Bu yüzden HTTP yolundaki gibi "cihaz geri gelene kadar bekle" adımı
# yoktur, doğrulama doğrudan yapılır.
def _adb(hedef: str, *args: str, sure: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["adb", *args], capture_output=True, text=True,
                              timeout=sure)
    except FileNotFoundError:
        raise UygulanmazHatasi(
            "adb komutu bulunamadı — Compartment LCD'ye APK kurulamıyor")
    except subprocess.TimeoutExpired:
        raise UlasilamadiHatasi(f"adb {args[0]} zaman aşımına uğradı")


def _apk_surumu(hedef: str, sure: int) -> str:
    r = _adb(hedef, "-s", hedef, "shell", "dumpsys", "package",
             ayar.ADB_PAKET, sure=sure)
    return okuma.paket_bilgisi(r.stdout or "")["surum"]


def _apk_kur(cihaz: Cihaz, yol, beklenen: str, dogrula_sure: float) -> dict:
    hedef = f"{cihaz.ip}:{ayar.ADB_PORT}"
    sure = ayar.ADB_TIMEOUT
    kurulum_suresi = max(int(dogrula_sure), ayar.ADB_KURULUM_TIMEOUT)

    _adb(hedef, "connect", hedef, sure=sure)
    try:
        onceki = _apk_surumu(hedef, sure)
        if not onceki:
            # Uygulama hiç kurulu olmayabilir; bu bir hata değil, ilk
            # kurulum. Ama cihaza hiç bağlanamıyorsak kurulum da
            # çalışmaz — onu install çıktısından anlayacağız.
            onceki = ""

        r = _adb(hedef, "-s", hedef, "install", "-r", str(yol),
                 sure=kurulum_suresi)
        cikti = f"{r.stdout or ''}\n{r.stderr or ''}".strip()
        # Cihazdaki sürüm yenisinden büyükse paket yöneticisi reddeder.
        # Sahada eski sürüme dönmek gereken bir durum; -d ile yeniden
        # denenir (bayrağı her seferinde göndermiyoruz, bazı cihazlarda
        # düşürme kapalı ve komutun tamamı reddediliyor).
        if "INSTALL_FAILED_VERSION_DOWNGRADE" in cikti:
            r = _adb(hedef, "-s", hedef, "install", "-r", "-d", str(yol),
                     sure=kurulum_suresi)
            cikti = f"{r.stdout or ''}\n{r.stderr or ''}".strip()

        if "Success" not in cikti:
            raise DogrulamaHatasi(_kurulum_hatasi(cikti))

        yeni = _apk_surumu(hedef, sure)
        if not yeni:
            raise DogrulamaHatasi(
                f"Kurulum başarılı göründü ama {ayar.ADB_PAKET} sürümü "
                "okunamadı — APK başka bir paket olabilir")
        if beklenen and yeni.strip() != str(beklenen).strip():
            raise DogrulamaHatasi(
                f"Cihaz {yeni} sürümünü bildiriyor, beklenen {beklenen}")
        return {"onceki": onceki, "yeni": yeni,
                "degisti": bool(onceki) and onceki != yeni}
    finally:
        _adb(hedef, "disconnect", hedef, sure=sure)


def _kurulum_hatasi(cikti: str) -> str:
    """adb install çıktısını kullanıcının okuyabileceği tek satıra indirir."""
    bilinen = {
        "INSTALL_FAILED_INVALID_APK": "Dosya geçerli bir APK değil",
        "INSTALL_FAILED_VERSION_DOWNGRADE":
            "Cihazdaki sürüm daha yeni; düşürmeye izin verilmedi",
        "INSTALL_FAILED_UPDATE_INCOMPATIBLE":
            "APK farklı bir imzayla üretilmiş — önce mevcut uygulama "
            "kaldırılmalı",
        "INSTALL_FAILED_INSUFFICIENT_STORAGE": "Cihazda yer kalmamış",
        "INSTALL_PARSE_FAILED": "APK çözümlenemedi",
        "device unauthorized": "Cihaz adb yetkisi vermemiş (ekrandan onay "
                               "gerekiyor olabilir)",
        "device offline": "Cihaz adb'ye bağlı değil",
        "no devices/emulators found": "Cihaza adb ile bağlanılamadı "
                                      "(5555 portu kapalı olabilir)",
    }
    for anahtar, mesaj in bilinen.items():
        if anahtar in cikti:
            return f"APK kurulamadı: {mesaj}"
    ilk = next((s for s in cikti.splitlines() if s.strip()), "")
    return f"APK kurulamadı: {ilk[:160]}" if ilk else "APK kurulamadı"
