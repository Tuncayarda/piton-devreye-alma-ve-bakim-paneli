#!/usr/bin/env python3
"""Devreye Alma Paneli — yerel HTTP servisi.

Tarayıcı ya da uygulama penceresi burayla konuşur; cihazlara yalnızca bu
süreç bağlanır.

Güvenlik kabulleri:
  · Yalnız 127.0.0.1 dinlenir. Dış ağ arayüzlerine açılmaz, CORS açılmaz.
  · İstemci hiçbir zaman bir IP ya da cihaz türü göndererek hedef
    seçemez. Yalnızca cihaz kimliği (id) gönderir; hedef DeviceMap'ten
    bulunur. Böylece arayüzdeki bir açık, panelin rastgele bir adrese
    bağlanmasına dönüşemez.
  · Tren seti, cihaz kimliği ve iş kimliği sunucu tarafında doğrulanır.
  · POST gövdeleri tip ve boyut denetiminden geçer.
  · Hiçbir GET/POST cevabında parola ya da Authorization başlığı bulunmaz.
  · Statik dosya servisinde dizin dışına çıkılamaz.

Çalıştırma (pencere açmaz, hata ayıklama için):
    python3 panel_api.py --port 8790
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import secrets
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from core import (ayar, device_map, dogrulama, dosya, excel, firmware,
                  ip_atama, isler, kategori, kimlik as kimlik_deposu, konfig,
                  kontrol, okuma, piscu)
from core.hata import CihazHatasi, KimlikHatasi, kullanici_mesaji

# Admin şifresi: uygulama başlatılırken verilirse sorulur, verilmezse
# admin ekranı şifresiz açılır. Hiçbir yere yazılmaz, yalnız bellekte.
_ADMIN_PAROLA: str | None = None

# Cihaza YAZAN iş türleri — okuyan (tarama, hafif yenileme) türlerden ayrı
# tutulur, çünkü bunlar sürerken cihazdan okunan şey geçicidir.
YAZAN_ISLER = ("ip", "ipfab", "cfg", "fw")


def admin_parolasi_ayarla(parola: str | None) -> None:
    global _ADMIN_PAROLA
    _ADMIN_PAROLA = parola or None


def admin_dogrula(parola: str) -> bool:
    if not _ADMIN_PAROLA:
        return True
    return secrets.compare_digest(str(parola), _ADMIN_PAROLA)


# ───────────────────────────────────────────────────────── yardımcılar ────
def _env(set_no) -> device_map.Envanter:
    return device_map.yukle(device_map.gecerli_set(set_no))


def _cihaz(env: device_map.Envanter, cihaz_id):
    """Cihazı YALNIZCA envanterden bulur.

    İstemcinin gönderdiği id dışındaki hiçbir alanı (ip, tip) hedef
    seçiminde kullanmıyoruz.
    """
    if not isinstance(cihaz_id, str) or len(cihaz_id) > 64:
        raise ValueError("Geçersiz cihaz kimliği")
    c = env.bul(cihaz_id)
    if c is None:
        raise LookupError("Cihaz bu tren setinin listesinde yok")
    return c


def _kimlik(cihaz):
    """Cihaz için bellekteki kimlik (varsa)."""
    return kimlik_deposu.al(cihaz.id, cihaz.ip, grup=okuma.kimlik_grubu(cihaz))


def _telemetri(env: device_map.Envanter) -> piscu.Telemetri:
    return piscu.Telemetri(env.piscu_ip()).topla(beklenen_set=env.set_no)


# Telemetri önbelleği (set başına).
#
# `Telemetri.topla()` üç ayrı MQTT bağlantısı açıp retained mesaj bekliyor;
# sahada ölçülen süresi ~9 saniye. Hafif yenileme bunu her turda yeniden
# topladığı için turun KENDİSİ dokuz saniye sürüyordu — cihazlar
# milisaniyeler içinde cevap verirken. Arayüzün birkaç saniyede bir
# yenilemesinin bu yüzden bir karşılığı yoktu.
#
# Değerler broker'da retained duruyor ve dakikalık keşif turu zaten
# topluyor; hafif turlar için o görüntü yeterince tazedir. TTL keşif
# aralığından uzun tutulur, böylece normal çalışan bir panelde hafif tur
# önbelleği hep dolu bulur ve MQTT'ye hiç gitmez.
TELEMETRI_TTL = 90.0
_telemetri_onbellek: dict[int, tuple[float, piscu.Telemetri]] = {}
_telemetri_kilit = threading.Lock()


def _telemetri_yaz(set_no: int, tel: piscu.Telemetri) -> None:
    # Hatalı görüntü de saklanır: MQTT gerçekten ulaşılamıyorsa hafif turun
    # her seferinde dokuz saniye harcayıp aynı hatayı bulmasının anlamı yok.
    # Telemetriye bağlı cihazlar zaten yeşil olmadıkları için hafif turun
    # hedefine girmezler.
    with _telemetri_kilit:
        _telemetri_onbellek[int(set_no)] = (time.monotonic(), tel)


def _telemetri_onbellekten(set_no: int) -> piscu.Telemetri | None:
    with _telemetri_kilit:
        kayit = _telemetri_onbellek.get(int(set_no))
    if kayit is None or time.monotonic() - kayit[0] > TELEMETRI_TTL:
        return None
    return kayit[1]


def _mevcut_surum(sonuc) -> str:
    """Cihazdan okunan sürüm; okunmadıysa boş (uydurulmaz)."""
    return str((sonuc.alanlar.get("surum") if sonuc else "") or "")


def _cihaz_dto(cihaz, sonuc) -> dict:
    veri = cihaz.dto()
    veri["sonuc"] = (sonuc.dto() if sonuc is not None
                     else dogrulama.okunmadi(cihaz.yontem).dto())
    veri["kimlikGrubu"] = okuma.kimlik_grubu(cihaz) or ""
    veri["kimlikVar"] = _kimlik(cihaz) is not None
    return veri


def _durum_govdesi(env: device_map.Envanter) -> dict:
    # Cihaz listesi her zaman "son bilinen durum"u gösterir; adım adım
    # tarama ilerlemesi işlem kuyruğunda (/api/is) durur. İki yerde birden
    # göstermek listeyi tarama süresince okunmaz hale getiriyordu.
    gor = isler.gorunum(env.set_no)
    sonuclar = gor.hepsi()
    cihazlar = [_cihaz_dto(c, sonuclar.get(c.id)) for c in env.cihazlar]
    kilitli = [c for c in cihazlar
               if c["sonuc"]["dogrulama"] == dogrulama.KIMLIK_BEKLIYOR]
    return {
        "setNo": env.set_no,
        "cihazlar": cihazlar,
        "sayilar": gor.sayilar(),
        "kilitSayisi": len(kilitli),
        "sonTarama": gor.son_tarama,
        "aktifTarama": bool(isler.YONETICI.aktif(f"tarama:{env.set_no}")),
    }


# ───────────────────────────────────────────────────────── iş gövdeleri ───
def tarama_isi(env: device_map.Envanter):
    """Tam tarama işi gövdesi."""
    def govde(is_: isler.Is):
        # Telemetri toplama birkaç saniye sürüyor ve bu sırada hiçbir cihaz
        # satırı hareket etmiyor. Ne beklendiğini kuyrukta gösteriyoruz;
        # aksi halde tarama donmuş gibi görünüyor.
        is_.ozel_satir("telemetri", "Canlı MQTT telemetrisi",
                       durum=isler.CALISIYOR,
                       not_=f"{env.piscu_ip() or 'PISCU'} okunuyor",
                       ip=env.piscu_ip() or "")
        telemetri = None
        try:
            telemetri = _telemetri(env)
        except Exception:
            telemetri = piscu.Telemetri(env.piscu_ip())
            telemetri.hata = "MQTT telemetrisi alınamadı"
        # Hafif yenileme turları bu görüntüyü kullanır; kendileri toplamaz.
        _telemetri_yaz(env.set_no, telemetri)
        is_.ozel_satir(
            "telemetri", "Canlı MQTT telemetrisi",
            durum="hata" if telemetri.hata else "tamam",
            not_=telemetri.hata or f"{len(telemetri.harita)} kayıt alındı",
            ip=env.piscu_ip() or "")

        ntp = env.piscu_ip()

        def oku(cihaz):
            return okuma.cihaz_oku(cihaz, kimlik=_kimlik(cihaz),
                                   telemetri=telemetri, beklenen_ntp=ntp,
                                   pbx_ip=env.piscu_ip())

        isler.cihaz_turu(is_, env.cihazlar, oku)

    return govde


def ip_fabrika_isi(env, switch_id, portlar, gruplar, ayarlar):
    """Test akışı: seçili cihazları fabrika adresine döndürür."""
    def govde(is_: isler.Is):
        adim = {"n": 0}

        def satir(metin: str):
            adim["n"] += 1
            is_.ozel_satir(f"adim{adim['n']}", metin,
                           durum=_ip_satir_durumu(metin))

        kalan = ip_atama.fabrikaya_dondur(
            env, switch_id, portlar, gruplar, satir,
            ayarlar=ayarlar, iptal=is_.iptal.is_set)
        if kalan:
            is_.hata = f"{kalan} cihaza fabrika IP'si yazılamadı"

    return govde


def _ip_satir_durumu(metin: str) -> str:
    """Betik çıktısının satırını kuyruk rengine çevirir.

    Koşu iki yüz satır yazıyor; hepsi yeşil "Tamam" görününce bir portun
    neden tamamlanmadığı gözden kaçıyordu. Betiğin kendi işaretleri
    kullanılır: "[HATA]" ve "EKSİK —" başarısızlık, "[!]" uyarıdır.
    """
    if "PORTLAR KAPALI KALMIŞ" in metin or "[HATA]" in metin:
        return "hata"
    if "EKSİK —" in metin or "tamamlanmadı" in metin:
        return "hata"
    if "[!]" in metin:
        return "uyari"
    return "tamam"


def ip_isi(env, switch_id, portlar, korumali, gruplar, ayarlar):
    """IP atama koşusu — ilerleme PORT başına raporlanır.

    Betiğin her çıktı satırı kuyruğa bir "adım" olarak giriyordu: iki yüz
    satırlık okunmaz bir yığın, üstelik o satırlar sayaçlara girmediği
    için yüzde baştan sona %0. Artık koşunun gerçek iş birimi olan port
    başına bir satır var (bkz. ip_atama.Ilerleme) ve ham çıktı, kuyrukta
    tek satırla açılabilen bir günlük dosyasına yazılıyor.
    """
    def govde(is_: isler.Is):
        # Betik portları geri açamazsa cihazlar sahada kapalı kalır. Bu,
        # kuyruk satırları arasında kaybolacak bir uyarı değil; işin
        # hatasına çıkar ki kullanıcı elle açması gerektiğini görsün.
        acik_kalmadi = {"var": False}
        plan = ip_atama.plan(env, gruplar, portlar, switch_id)
        gunluk_yolu = dosya.gunluk_yolu(f"ip-atama-set{env.set_no}")
        gunluk = gunluk_yolu.open("w", encoding="utf-8")

        ilerleme = ip_atama.Ilerleme(
            is_, plan["satirlar"],
            gunluk=lambda s: (gunluk.write(s + "\n"), gunluk.flush()))

        def satir(metin: str):
            if "PORTLAR KAPALI KALMIŞ" in metin:
                acik_kalmadi["var"] = True
            ilerleme.satir(metin)

        try:
            # İptal bayrağı betiğe kadar gider: kullanıcı durdurunca betik
            # kendi Ctrl-C yolundan geçip PoE portlarını geri açar.
            kod = ip_atama.kosu(env, switch_id, portlar, satir,
                                korumali=korumali, gruplar=gruplar,
                                ayarlar=ayarlar, iptal=is_.iptal.is_set)
        finally:
            ilerleme.bitir()
            gunluk.close()
            # Ham çıktı kaybolmuyor, yalnız yolundan çekiliyor: satır
            # olarak değil, açılabilir bir dosya olarak duruyor.
            is_.ozel_satir("gunluk", gunluk_yolu.name, durum="tamam",
                           not_="Koşunun ham çıktısı", yol=str(gunluk_yolu))

        sw = env.bul(switch_id)
        if acik_kalmadi["var"]:
            is_.hata = (
                "PoE portları geri açılamadı — cihazlar hâlâ kapalı olabilir. "
                f"Switch arayüzünden elle açın: http://{sw.ip if sw else ''}"
                "/poePort.html")
        elif kod and kod != 130:      # 130 = kullanıcı durdurdu
            is_.hata = f"IP atama betiği {kod} koduyla bitti"

    return govde


def _konfig_alanlari(env, c, grup: str) -> dict:
    """Ekranın alan tanımları, gruba girilen hedefler ve DeviceMap değerleri.

    Cihaz okunamadığında da dönmeli: gruba yazılacak değerler sahada
    cihaza erişilemezken hazırlanıyor. Alanlar cihaz tipine göre değişir —
    Handset'in mod alanları Amplifier'da yok, UIC'in eşikleri yalnız
    UIC'te var. Gizli alanın (SIP parolası) değeri arayüze gönderilmez;
    yalnız "girildi mi" bilgisi gider.

    `projeHedef`, gruptaki bütün cihazlarda aynı olan DeviceMap değerleri;
    ekran bunları kutulara hazır yazar. `projeFarkli` cihaza göre değişen
    alanların listesi — o kutular boş kalır.
    """
    gr = kategori.grup_bul(grup)
    hedefler = [x for x in env.cihazlar
                if gr and kategori.grup_eslesir(gr, x)] or [c]
    ortak, farkli = konfig.grup_proje_ozeti(env, hedefler)
    return {
        "alanlar": konfig.alan_listesi(c.subtype or ""),
        "grupHedef": konfig.grup_hedef_gosterim(grup),
        "grupGizli": konfig.grup_gizli_alanlar(grup),
        "projeHedef": ortak,
        "projeFarkli": farkli,
        "varsayilan": konfig.varsayilan_ozeti(),
    }


def konfig_isi(env, cihazlar, grup=""):
    """Konfigürasyon yazımı — cihazlar PARALEL işlenir.

    Sırayla yürüyordu ve bekleme süreleri uç uca ekleniyordu: her cihazda
    okuma + yazma + doğrulama okuması var, SIP yazılan cihazda bir de
    yeniden başlatma bekleniyor. On iki intercomluk bir sette bu, tek
    başına dakikalar demekti — üstelik beklemenin çoğu ağ cevabı,
    panelin işi değil.

    Genişlik firmware ile aynı (`ayar.KONFIG_WORKER`), taramadan dar:
    yazma cihazı yeniden başlatabiliyor ve aynı anda bir switch'in
    arkasındaki her şeyi karartmak sahadaki kişinin görüşünü de zorlar.
    """
    def govde(is_: isler.Is):
        for c in cihazlar:
            is_.satir_kur(c)

        def tek(c):
            if is_.iptal.is_set():
                is_.satir_guncelle(c.id, "atlandi", "İptal edildi")
                return
            is_.satir_guncelle(c.id, isler.CALISIYOR, "Uygulanıyor")
            try:
                sonuc = konfig.uygula(c, env, _kimlik(c), grup)
                yazilan = sonuc.get("yazilanAlanlar") or []
                # Zaten uyuşan cihaza istek atılmıyor; satır bunu açıkça
                # söylemeli, yoksa "yazıldı" diyen bir satırın arkasında
                # hiçbir istek olmadığı görünmez.
                is_.satir_guncelle(c.id, "tamam", (
                    f"Yazıldı ve doğrulandı: {', '.join(yazilan)}"
                    + (" · cihaz yeniden başlatıldı"
                       if sonuc.get("yenidenBaslatildi") else "")
                ) if yazilan else "Ayarlar zaten uyuşuyor — yazılmadı")
            except KimlikHatasi as exc:
                is_.satir_guncelle(c.id, "kimlik", kullanici_mesaji(exc))
            except Exception as exc:
                is_.satir_guncelle(c.id, "hata", kullanici_mesaji(exc))

        if not cihazlar:
            return
        havuz = ThreadPoolExecutor(
            max_workers=min(ayar.KONFIG_WORKER, len(cihazlar)))
        try:
            list(havuz.map(tek, cihazlar))
        finally:
            havuz.shutdown(wait=True)

    return govde


def firmware_isi(env, cihazlar):
    """Yükleme işi — cihazlar paralel yüklenir.

    Cihazlar birbirinden bağımsız: her biri kendi dosyasını alıyor, kendi
    yeniden başlamasını bekliyor. Sırayla yapmak 12 intercomluk bir sette
    bekleme sürelerini uç uca ekliyordu. Aynı anda kaç tanesinin
    yükleneceği `ayar.FIRMWARE_WORKER` (varsayılan 4).
    """
    def govde(is_: isler.Is):
        for c in cihazlar:
            is_.satir_kur(c)

        def tek(c):
            # İptal her cihazdan ÖNCE denetlenir: sıradakilere hiç
            # dokunulmaz, o an süren yükleme kendi zaman aşımı kadar
            # sürebilir — yarıda kesilen bir firmware yazımı cihazı
            # kullanılamaz bırakır.
            if is_.iptal.is_set():
                is_.satir_guncelle(c.id, "atlandi", "İptal edildi")
                return
            # Hangi dosyanın gittiği satırda yazar: cihaz başına ayrı
            # dosya seçilebildiği için "yüklendi" tek başına yetmiyor.
            dosya_adi = firmware.secili_of(c.id)["ad"]
            is_.satir_guncelle(c.id, isler.CALISIYOR,
                               f"Yükleniyor · {dosya_adi}")
            try:
                sonuc = firmware.yukle(c, _kimlik(c))
                is_.satir_guncelle(c.id, "tamam",
                                   f"{dosya_adi} yüklendi · "
                                   f"sürüm {sonuc['yeni']}")
            except KimlikHatasi as exc:
                is_.satir_guncelle(c.id, "kimlik", kullanici_mesaji(exc))
            except Exception as exc:
                is_.satir_guncelle(c.id, "hata", kullanici_mesaji(exc))

        havuz = ThreadPoolExecutor(
            max_workers=max(1, min(ayar.FIRMWARE_WORKER, len(cihazlar))))
        try:
            list(havuz.map(tek, cihazlar))
        finally:
            havuz.shutdown(wait=True)

    return govde


def excel_isi(env):
    def govde(is_: isler.Is):
        sonuclar = isler.gorunum(env.set_no).hepsi()
        yol = excel.uret(env, sonuclar)
        is_.ozel_satir("excel", yol.name, durum="tamam", not_=str(yol),
                       yol=str(yol))

    return govde


# ────────────────────────────────────────────────────────────── HTTP ──────
class Handler(BaseHTTPRequestHandler):
    server_version = "DevreyeAlmaPaneli/1.0"
    protocol_version = "HTTP/1.1"

    # ---- alt yapı ----
    def _gonder(self, kod: int, yuk, ctype="application/json; charset=utf-8"):
        govde = (json.dumps(yuk, ensure_ascii=False).encode("utf-8")
                 if not isinstance(yuk, (bytes, bytearray)) else yuk)
        self.send_response(kod)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(govde)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _govde(self) -> dict:
        """POST gövdesini okur; tip ve boyut denetiminden geçirir."""
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise ValueError("Content-Length geçersiz")
        if n < 0 or n > ayar.GOVDE_SINIRI:
            raise ValueError("İstek gövdesi çok büyük")
        if not n:
            return {}
        try:
            veri = json.loads(self.rfile.read(n))
        except ValueError:
            raise ValueError("Gövde geçerli JSON değil")
        if not isinstance(veri, dict):
            raise ValueError("Gövde bir nesne olmalı")
        return veri

    def _dosya(self, gorece: str):
        """static/ altındaki dosyayı gönderir; dizin dışına çıkılamaz.

        Yol çözüldükten (`resolve`) sonra static kökünün altında olduğu
        denetlenir: '..', sembolik bağ ya da yüzde kodlaması ile dışarı
        çıkma denemesi bu denetimde takılır.
        """
        temel = ayar.STATIC_DIR.resolve()
        try:
            yol = (temel / unquote(gorece).lstrip("/")).resolve()
            yol.relative_to(temel)
        except (OSError, ValueError):
            return self._gonder(404, {"hata": "yok"})
        if not yol.is_file():
            return self._gonder(404, {"hata": "yok"})
        tur, _ = mimetypes.guess_type(yol.name)
        if yol.suffix == ".js":
            tur = "text/javascript; charset=utf-8"
        elif yol.suffix == ".css":
            tur = "text/css; charset=utf-8"
        elif yol.suffix == ".html":
            tur = "text/html; charset=utf-8"
        return self._gonder(200, yol.read_bytes(), tur or "application/octet-stream")

    def log_message(self, fmt, *args):
        pass

    # ---- GET ----
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        yol = u.path
        try:
            if yol in ("/", "/index.html"):
                return self._dosya("index.html")
            if yol.startswith(("/css/", "/js/")) or yol in (
                    "/piton-logo.svg", "/piton-favicon.png"):
                return self._dosya(yol)
            if yol.startswith("/api/"):
                return self._api_get(yol, q)
            return self._gonder(404, {"hata": "bilinmeyen yol"})
        except Exception:
            self._hata_yanit()

    def _api_get(self, yol: str, q: dict):
        tek = lambda ad, vars=None: (q.get(ad) or [vars])[0]     # noqa: E731

        if yol == "/api/surum":
            return self._gonder(200, {
                "surum": ayar.APP_VERSION, "ad": ayar.APP_ADI,
                "adminParolaGerekli": bool(_ADMIN_PAROLA),
            })

        if yol == "/api/proje":
            env = _env(tek("set", 1))
            return self._gonder(200, {
                "proje": env.proje,
                "setNo": env.set_no,
                # Set numarası elle giriliyor; arayüze hazır liste değil,
                # kabul edilen aralık gönderilir.
                "setMin": ayar.SET_MIN,
                "setMax": ayar.SET_MAX,
                "dosya": env.kaynak.name,
                "toplam": len(env.cihazlar),
                "switchSayisi": len(env.switchler()),
                "kategoriler": kategori.KATEGORILER,
                "gruplar": kategori.GRUPLAR,
                "yontemler": kategori.YONTEMLER,
                "piscuIp": env.piscu_ip(),
                "adminParolaGerekli": bool(_ADMIN_PAROLA),
            })

        if yol == "/api/cihazlar":
            return self._gonder(200, _durum_govdesi(_env(tek("set", 1))))

        if yol == "/api/durum":
            return self._gonder(200, _durum_govdesi(_env(tek("set", 1))))

        if yol == "/api/kilit":
            env = _env(tek("set", 1))
            gor = isler.gorunum(env.set_no)
            liste = []
            for c in env.cihazlar:
                s = gor.al(c.id)
                if s is None or not dogrulama.kimlik_bekliyor(s):
                    continue
                liste.append({
                    **c.dto(),
                    "kimlikGrubu": okuma.kimlik_grubu(c) or "",
                    "aciklama": s.aciklama,
                    "yontemKod": kategori.YONTEMLER.get(c.yontem, {}).get("kod", ""),
                    "kimlikVar": _kimlik(c) is not None,
                })
            return self._gonder(200, {"setNo": env.set_no, "cihazlar": liste})

        if yol == "/api/isler":
            return self._gonder(200, {
                "isler": [j.dto(satir=False) for j in isler.YONETICI.liste()]})

        if yol == "/api/is":
            is_ = isler.YONETICI.bul(str(tek("id", "")))
            if is_ is None:
                return self._gonder(404, {"hata": "iş bulunamadı"})
            return self._gonder(200, is_.dto())

        if yol == "/api/cihaz":
            env = _env(tek("set", 1))
            c = _cihaz(env, tek("id"))
            s = isler.gorunum(env.set_no).al(c.id)
            return self._gonder(200, {
                **_cihaz_dto(c, s),
                "yontemBilgi": kategori.YONTEMLER.get(c.yontem, {}),
                "piscuIp": env.piscu_ip(),
            })

        if yol == "/api/ip/plan":
            env = _env(tek("set", 1))
            # Birden çok grup seçilebilir: "gruplar=Intercom,Kamera".
            # Tek gruplu eski biçim (grup=…) da kabul edilir.
            adlar = [a for a in (tek("gruplar") or tek("grup", "")).split(",")
                     if a.strip()]
            gruplar = ip_atama.gruplari_coz(adlar) or [kategori.GRUPLAR[0]]
            hedefler = [c for c in env.cihazlar
                        if c.port and any(kategori.grup_eslesir(g, c)
                                          for g in gruplar)]
            # Hedef grupların cihazları hangi switch'teyse plan o switch içindir.
            sw = tek("switch") or (hedefler[0].switch_id if hedefler else
                                   (env.switchler()[0].id if env.switchler() else ""))
            izinli = set(ip_atama.izinli_portlar(env, sw))
            metin = tek("portlar", "")
            if metin:
                portlar = ip_atama.portlar_ayristir(metin, izinli)
            else:
                # Varsayılan: yalnız seçili gruplarda cihazı olan portlar.
                # Boş portları da seçili göstermek kullanıcıyı yanıltıyor.
                portlar = sorted(
                    {int(c.port) for c in hedefler
                     if c.switch_id == sw and str(c.port).isdigit()} & izinli)
            adlar = [g["ad"] for g in gruplar]
            return self._gonder(200, {
                **ip_atama.plan(env, adlar, portlar, sw),
                "izinliPortlar": sorted(izinli),
                # Arayüzde önerilecek varsayılanlar: cihazların fabrika
                # çıkışı beklediği adres ve setin kendi ağı.
                "fabrikaIp": ip_atama.fabrika_ip(env),
                "aramaAgi": device_map.coz("10.n.1.0", env.set_no),
                "aramaMaskesi": "255.255.255.0",
                # Aranacak yer aralıkla da verilebiliyor; sınırı arayüz de
                # bilsin (bkz. ip_atama.ARAMA_SINIRI).
                "aramaSiniri": ip_atama.ARAMA_SINIRI,
                # Cihazlar aynı fabrika adresinde geldiği için koşu, her
                # port değişiminde ARP önbelleğini temizlemek zorunda;
                # yetki yoksa kullanıcı bunu koşudan önce bilsin.
                "arpTemizlik": ip_atama.arp_yetkisi(),
                # grupCihaz: o switch'te seçili gruplardan kaç cihaz var.
                # Arayüz, gruba ait cihazı olmayan switch'in panelini buna
                # bakarak işaretler; kullanıcı boşuna port aramaz.
                "switchler": [{"id": s.id, "ad": s.ad, "ip": s.ip,
                               "grupCihaz": sum(1 for c in hedefler
                                                if c.switch_id == s.id)}
                              for s in env.switchler()],
            })

        if yol == "/api/ip/panel":
            env = _env(tek("set", 1))
            sw_id = tek("switch") or (env.switchler()[0].id if env.switchler() else "")
            sw = _cihaz(env, sw_id)
            return self._gonder(200, ip_atama.onpanel(env, sw.id, _kimlik(sw)))

        if yol == "/api/ip/korunan":
            # Koşunun dokunmaması gereken portların tamamı. İstemci hiçbir
            # şey seçmez: bilgisayarın yeri de switch'ler arası bağlantılar
            # da MAC öğrenme tablolarından çıkar. Ayakta olmayan switch
            # kendi zaman aşımıyla düşer, diğerlerini bekletmez.
            env = _env(tek("set", 1))
            return self._gonder(
                200, ip_atama.korunan_portlar(env, kimlik_al=_kimlik))

        if yol == "/api/konfig/alanlar":
            # Cihaza HİÇ gitmeyen hızlı uç: alan listesi, hedefler ve
            # DeviceMap değerleri. Grup değiştirilince ekran bunu bekler,
            # cihaz okumasını değil — okuma saniyeler sürebiliyor ve o
            # sürede kart eski grubun alanlarını gösteriyordu.
            env = _env(tek("set", 1))
            c = _cihaz(env, tek("id"))
            grup = tek("grup", "")
            return self._gonder(200, {
                "cihazId": c.id, "grup": grup, "alt": c.subtype or "",
                "satirlar": [], "okunuyor": True,
                **_konfig_alanlari(env, c, grup)})

        if yol == "/api/konfig":
            env = _env(tek("set", 1))
            c = _cihaz(env, tek("id"))
            grup = tek("grup", "")
            try:
                return self._gonder(200, {
                    **konfig.cek(c, env, _kimlik(c), grup),
                    **_konfig_alanlari(env, c, grup),
                })
            except CihazHatasi as exc:
                return self._gonder(200, {
                    "cihazId": c.id, "grup": grup, "satirlar": [],
                    "alt": c.subtype or "",
                    **_konfig_alanlari(env, c, grup),
                    "hata": kullanici_mesaji(exc),
                    "kimlik": isinstance(exc, KimlikHatasi)})

        if yol == "/api/kontrol":
            env = _env(tek("set", 1))
            gor = isler.gorunum(env.set_no)
            return self._gonder(200, {
                **kontrol.onizleme(env, gor.hepsi()),
                "setNo": env.set_no,
                "sayilar": gor.sayilar(),
                "sonTarama": gor.son_tarama,
            })

        if yol == "/api/firmware":
            # İmaj cihaz başına seçiliyor; ekran hangi cihazda hangi
            # dosyanın durduğunu buradan öğrenir. Grup verilmezse yalnız
            # seçili olanlar döner (yükleme düğmesi bunu sayar).
            env = _env(tek("set", 1))
            grup = kategori.grup_bul(str(tek("grup", "") or ""))
            hedef = [c for c in env.cihazlar
                     if grup is None or kategori.grup_eslesir(grup, c)]
            gor = isler.gorunum(env.set_no)
            return self._gonder(200, {
                "setNo": env.set_no,
                "grup": grup["ad"] if grup else "",
                "enBuyuk": firmware.EN_BUYUK,
                "cihazlar": [{
                    "cihazId": c.id,
                    "ad": c.ad,
                    "ip": c.ip,
                    # Yükleme yolu olmayan cihazları ekran "uygulanmıyor"
                    # diye göstersin; olanlarda hangi dosyanın beklendiği
                    # de belli olsun (anons .bin, Compartment LCD .apk).
                    "yuklenebilir": firmware.destekli(c),
                    "uzanti": firmware.uzanti(c),
                    "mevcutSurum": _mevcut_surum(gor.al(c.id)),
                    "dosya": firmware.secili_of(c.id),
                } for c in hedef],
                "seciliSayi": len(firmware.secilenler()),
                "esZamanli": ayar.FIRMWARE_WORKER,
            })

        if yol == "/api/piscu":
            return self._gonder(200, self._piscu(_env(tek("set", 1))))

        if yol == "/api/mqtt":
            return self._gonder(200, piscu.DINLEYICI.durum())

        return self._gonder(404, {"hata": "bilinmeyen yol"})

    def _piscu(self, env) -> dict:
        """PISCU & PBX ekranı — yalnızca gerçekten okunan veriler."""
        gor = isler.gorunum(env.set_no)
        sonuclar = gor.hepsi()

        def sonuc_of(c):
            return sonuclar.get(c.id)

        piscu_c = env.tip_ile("PISCU")
        hmi_c = env.tip_ile("HMI")
        sip_cihaz = [c for c in env.cihazlar if c.pbx_extension]

        istemciler = []
        for c in piscu_c + hmi_c:
            s = sonuc_of(c)
            istemciler.append({
                "ad": c.ad, "ip": c.ip,
                "durum": s.durum if s else dogrulama.GRI,
                "surum": (s.alanlar.get("surum", "") if s else ""),
                "aciklama": s.aciklama if s else "Henüz okunmadı",
            })

        sipler = []
        for c in sip_cihaz:
            s = sonuc_of(c)
            sipler.append({
                "no": c.pbx_extension, "ad": c.ad, "ip": c.ip,
                "durum": s.durum if s else dogrulama.GRI,
                "cihazinBildirdigi": (s.alanlar.get("sipDahili", "") if s else ""),
                "pbx": (s.alanlar.get("sipPbx", "") if s else ""),
            })

        return {
            "brokerIp": env.piscu_ip(),
            "istemciler": istemciler,
            "sipler": sipler,
            "not": ("SIP kayıt durumu Asterisk ARI hesabı tanımlı olmadığı "
                    "için PBX'ten değil, cihazların kendi bildirdiği "
                    "değerlerden gösteriliyor."),
        }

    # ---- POST ----
    def do_POST(self):
        u = urlparse(self.path)
        try:
            govde = self._govde()
        except ValueError as exc:
            return self._gonder(400, {"hata": str(exc)})
        try:
            return self._api_post(u.path, govde)
        except LookupError as exc:
            self._gonder(404, {"hata": str(exc)})
        except ValueError as exc:
            self._gonder(400, {"hata": str(exc)})
        except KimlikHatasi as exc:
            self._gonder(401, {"hata": kullanici_mesaji(exc), "kimlik": True})
        except CihazHatasi as exc:
            self._gonder(502, {"hata": kullanici_mesaji(exc)})
        except Exception:
            self._hata_yanit()

    def _api_post(self, yol: str, g: dict):
        if yol == "/api/admin/giris":
            parola = g.get("parola", "")
            if not isinstance(parola, str) or len(parola) > 256:
                return self._gonder(400, {"hata": "geçersiz parola alanı"})
            if admin_dogrula(parola):
                return self._gonder(200, {"rol": "admin"})
            # Parola yanıta hiçbir biçimde konmaz.
            return self._gonder(401, {"hata": "Admin şifresi doğrulanamadı"})

        if yol == "/api/tarama":
            env = _env(g.get("set"))
            # `otomatik`: arayüzün dakikalık keşif turu. Ne yaptığı aynı;
            # yalnız kuyruk geçmişinde birikmemesi ve elle başlatılan
            # taramadan ayırt edilebilmesi için işaretlenir.
            oto = g.get("otomatik") is True
            baslik = "Otomatik tarama" if oto else "Tam tarama"
            is_ = isler.Is("tarama", f"{baslik} · Set {env.set_no}",
                           env.set_no, anahtar=f"tarama:{env.set_no}",
                           otomatik=oto)
            for c in env.cihazlar:
                is_.satir_kur(c)
            is_, yeni = isler.YONETICI.ekle(is_, tarama_isi(env))
            return self._gonder(200 if yeni else 202,
                                {**is_.dto(satir=False), "yeni": yeni})

        if yol == "/api/is/iptal":
            is_id = g.get("id")
            if not isinstance(is_id, str):
                return self._gonder(400, {"hata": "iş kimliği gerekli"})
            ok = isler.YONETICI.iptal(is_id)
            return self._gonder(200 if ok else 404, {"iptal": ok})

        if yol == "/api/is/dosya":
            # Açılacak yolu istemci göndermez: iş kaydında duran, panelin
            # kendi yazdığı yol açılır. Aksi halde bu uç "yerel makinede
            # herhangi bir dosyayı aç" demek olurdu.
            is_id, anahtar = g.get("id"), g.get("satir")
            if not isinstance(is_id, str) or not isinstance(anahtar, str):
                return self._gonder(400, {"hata": "iş ve satır kimliği gerekli"})
            is_ = isler.YONETICI.bul(is_id)
            hedef = is_.dosya_yolu(anahtar) if is_ else ""
            if not hedef:
                return self._gonder(404, {"hata": "Bu satırda dosya yok"})
            try:
                dosya.ac(hedef, klasor=bool(g.get("klasor")))
            except FileNotFoundError:
                return self._gonder(404, {
                    "hata": "Dosya bulunamadı — taşınmış ya da silinmiş olabilir"})
            except RuntimeError as exc:
                return self._gonder(500, {"hata": str(exc)})
            return self._gonder(200, {"acildi": True})

        if yol == "/api/is/sil":
            is_id = g.get("id")
            if not isinstance(is_id, str):
                return self._gonder(400, {"hata": "iş kimliği gerekli"})
            ok = isler.YONETICI.sil(is_id)
            return self._gonder(200 if ok else 409,
                                {"silindi": ok,
                                 "hata": None if ok else
                                 "Çalışan iş silinemez, önce iptal edin"})

        if yol == "/api/yenile":
            return self._hafif_yenileme(g)

        if yol == "/api/kimlik":
            return self._kimlik_dene(g)

        if yol == "/api/kimlik/unut":
            if g.get("hepsi") is True:
                kimlik_deposu.hepsini_unut()
                return self._gonder(200, {"unutuldu": "hepsi"})
            env = _env(g.get("set"))
            c = _cihaz(env, g.get("cihazId"))
            kimlik_deposu.unut(c.id, c.ip)
            return self._gonder(200, {"unutuldu": c.id})

        if yol == "/api/ip/kosu":
            env = _env(g.get("set"))
            sw = _cihaz(env, g.get("switch") or
                        (env.switchler()[0].id if env.switchler() else ""))
            izinli = set(ip_atama.izinli_portlar(env, sw.id))
            portlar = ip_atama.portlar_ayristir(str(g.get("portlar", "")), izinli)
            # Koşunun dokunmaması gereken portlar. İkisi de fiziksel
            # gerçek: bilgisayar bir switch'in bir portunda, switch'ler de
            # birbirine birer portla bağlı. Yalnız hedef switch'e ait
            # olanlar bu koşuyu ilgilendirir.
            #
            # Liste İSTEMCİDEN ALINMAZ, koşu başlarken YENİDEN bulunur:
            # arayüzdeki bulgu dakikalarca eski olabilir, bu arada kablo
            # başka porta takılmış olabilir. Yanılma payı burada PoE'yi
            # kendi bağlantımızın üstünde kapatmak demek.
            korumali: dict[int, str] = {}
            try:
                for p in ip_atama.korunan_portlar(env, kimlik_al=_kimlik)["portlar"]:
                    if p["switchId"] == sw.id:
                        korumali[int(p["port"])] = p["sebep"]
            except Exception:
                pass
            # Keşif çalışmadıysa (switch o an cevap vermedi) arayüzün son
            # bulgusuna düşülür — hiç korumamaktan iyidir.
            if not korumali:
                for p in (g.get("korunan") or []):
                    if (isinstance(p, dict) and p.get("switchId") == sw.id
                            and str(p.get("port", "")).isdigit()):
                        korumali[int(p["port"])] = str(
                            p.get("sebep") or "korunan bağlantı")[:80]
            # Kuyruğa girmeden burada da denetlenir: kullanıcı hatayı
            # düğmeye bastığı anda görsün, bir de kuyrukta ölü iş kalmasın.
            ip_atama.korumali_denetle(portlar, korumali)
            # Seçilen gruplar sırayla, her biri kendi betiğiyle yürür.
            # Betiği olmayan grup kuyruğa hiç girmez.
            ham = g.get("gruplar") or g.get("grup") or []
            adlar = [ham] if isinstance(ham, str) else list(ham)
            gruplar = [x["ad"] for x in ip_atama.gruplari_coz(adlar)]
            if not gruplar:
                return self._gonder(400, {"hata": "Cihaz grubu seçilmedi"})
            eksik = ip_atama.kosucusuz(gruplar)
            if eksik:
                return self._gonder(400, {
                    "hata": "Bu grup için IP atama betiği henüz yok: "
                            + ", ".join(eksik)})
            # Adresleme: cihazların fabrika çıkışı beklediği IP ve orada
            # bulunamayanlar için taranacak ağ. Aday listesi burada
            # üretilmez, yalnız doğrulanır — üretimi koşu yapar.
            ayarlar = {
                "fabrikaIp": str(g.get("fabrikaIp") or "").strip(),
                "aramaAgi": str(g.get("aramaAgi") or "").strip(),
                "aramaMaskesi": str(g.get("aramaMaskesi") or "").strip(),
                # Ağ + maske yerine açık adres aralığı: proje maskesi geniş
                # olduğunda (örn. /8) taranacak yeri daraltmanın tek yolu.
                "aramaBas": str(g.get("aramaBas") or "").strip(),
                "aramaSon": str(g.get("aramaSon") or "").strip(),
            }
            if ayarlar["fabrikaIp"] and not ip_atama.ipv4_mi(ayarlar["fabrikaIp"]):
                return self._gonder(400, {"hata": "Fabrika IP geçerli değil"})
            try:
                ip_atama.arama_adaylari(ayarlar["aramaAgi"],
                                        ayarlar["aramaMaskesi"],
                                        bas=ayarlar["aramaBas"],
                                        son=ayarlar["aramaSon"])
            except ValueError as exc:
                return self._gonder(400, {"hata": str(exc)})

            # Başlık kısa tutulur: kuyruk kartında tek satıra sığmayınca
            # üç noktayla kırpılıyor ve "IP ATAMA · YATAKLI_2 · ..."
            # dışında hiçbir şey okunmuyordu. Grup ve port bilgisi zaten
            # satırlarda ve aşama metninde duruyor.
            is_ = isler.Is("ip", f"IP atama · {sw.ad}",
                           env.set_no, anahtar=f"ip:{env.set_no}:{sw.id}")
            is_, yeni = isler.YONETICI.ekle(
                is_, ip_isi(env, sw.id, portlar, korumali, gruplar, ayarlar))
            return self._gonder(200 if yeni else 202,
                                {**is_.dto(satir=False), "yeni": yeni})

        if yol == "/api/ip/fabrika":
            # Test akışı: seçili cihazları yeniden fabrika adresinde topla.
            # Koşunun tersi değil, başlangıç durumunu kurma aracı.
            env = _env(g.get("set"))
            sw = _cihaz(env, g.get("switch") or
                        (env.switchler()[0].id if env.switchler() else ""))
            izinli = set(ip_atama.izinli_portlar(env, sw.id))
            portlar = ip_atama.portlar_ayristir(str(g.get("portlar", "")), izinli)
            ham = g.get("gruplar") or g.get("grup") or []
            adlar = [ham] if isinstance(ham, str) else list(ham)
            gruplar = [x["ad"] for x in ip_atama.gruplari_coz(adlar)]
            if not gruplar:
                return self._gonder(400, {"hata": "Cihaz grubu seçilmedi"})
            fabrika = str(g.get("fabrikaIp") or "").strip()
            if fabrika and not ip_atama.ipv4_mi(fabrika):
                return self._gonder(400, {"hata": "Fabrika IP geçerli değil"})
            is_ = isler.Is("ipfab",
                           f"Fabrika IP'sine döndür · {sw.ad} · "
                           f"{ip_atama.metin_yap(portlar)}",
                           env.set_no, anahtar=f"ipfab:{env.set_no}:{sw.id}")
            is_, yeni = isler.YONETICI.ekle(
                is_, ip_fabrika_isi(env, sw.id, portlar, gruplar,
                                    {"fabrikaIp": fabrika}))
            return self._gonder(200 if yeni else 202,
                                {**is_.dto(satir=False), "yeni": yeni})

        if yol == "/api/konfig/hedef":
            env = _env(g.get("set"))
            c = _cihaz(env, g.get("cihazId"))
            grup = str(g.get("grup") or "")
            alan, deger = str(g.get("alan", "")), str(g.get("deger", ""))
            # "kapsam": grup = aynı değer bütün gruba, cihaz = yalnız bu
            # cihaza (grubunkini ezer). Değer, cihaz tipinin alan tanımına
            # göre burada doğrulanır: geçersiz değer bellekte bekleyip
            # yazma anında patlarsa kullanıcı hatayı kuyrukta görürdü.
            alt = c.subtype or ""
            if str(g.get("kapsam") or "cihaz") == "grup":
                if not grup:
                    return self._gonder(400, {"hata": "grup gerekli"})
                gr = kategori.grup_bul(grup)
                konfig.grup_hedef_yaz(grup, alan, deger,
                                      (gr or {}).get("alt") or alt)
            else:
                konfig.hedef_yaz(c.id, alan, deger, alt)
            try:
                govde = konfig.cek(c, env, _kimlik(c), grup)
            except CihazHatasi as exc:
                govde = {"cihazId": c.id, "grup": grup, "satirlar": [],
                         "alt": alt,
                         "hata": kullanici_mesaji(exc),
                         "kimlik": isinstance(exc, KimlikHatasi)}
            return self._gonder(200, {**govde, **_konfig_alanlari(env, c, grup)})

        if yol == "/api/konfig/sifirla":
            # Kayıtlı varsayılanlar silinir; DeviceMap'teki proje değerleri
            # yerinde kalır, ekran onlara döner.
            env = _env(g.get("set"))
            c = _cihaz(env, g.get("cihazId"))
            grup = str(g.get("grup") or "")
            konfig.varsayilanlari_sil()
            try:
                govde = konfig.cek(c, env, _kimlik(c), grup)
            except CihazHatasi as exc:
                govde = {"cihazId": c.id, "grup": grup, "satirlar": [],
                         "alt": c.subtype or "",
                         "hata": kullanici_mesaji(exc),
                         "kimlik": isinstance(exc, KimlikHatasi)}
            return self._gonder(200, {**govde, **_konfig_alanlari(env, c, grup)})

        if yol == "/api/konfig/uygula":
            env = _env(g.get("set"))
            cihazlar = self._hedef_cihazlar(env, g)
            grup = str(g.get("grup") or "")
            is_ = isler.Is("cfg", f"Konfigürasyon · {len(cihazlar)} cihaz",
                           env.set_no, anahtar=f"cfg:{env.set_no}")
            is_, yeni = isler.YONETICI.ekle(is_,
                                            konfig_isi(env, cihazlar, grup))
            return self._gonder(200 if yeni else 202,
                                {**is_.dto(satir=False), "yeni": yeni})

        if yol == "/api/firmware/sec":
            # İşletim sisteminin dosya seçicisini açar ve seçileni hedef
            # cihaz(lar)a atar. Yol istemciden gelmiyor: tarayıcı gerçek
            # yolu vermiyor, kullanıcı da elle yazmak zorunda kalmasın.
            # İstek, kullanıcı pencereyi kapatana kadar bekler.
            env = _env(g.get("set"))
            cihazlar = self._hedef_cihazlar(env, g)
            hedef = [c for c in cihazlar if firmware.destekli(c)]
            if not hedef:
                return self._gonder(400, {
                    "hata": "Seçilen cihazlarda yazılım yükleme tanımlı değil"})
            # Süzgeç cihazın beklediği dosyaya göre: anons ekipmanı imaj
            # (.bin), Compartment LCD uygulama paketi (.apk). Karışık bir
            # seçim tek dosyayla karşılanamaz.
            uzantilar = {firmware.uzanti(c) for c in hedef}
            if len(uzantilar) > 1:
                return self._gonder(400, {
                    "hata": "Seçilen cihazlar farklı dosya türü bekliyor "
                            "(.bin / .apk) — grupları ayrı ayrı seçin"})
            tur = next(iter(uzantilar))
            baslik = (f"{hedef[0].ad} için .{tur} dosyası"
                      if len(hedef) == 1
                      else f"{len(hedef)} cihaz için .{tur} dosyası")
            try:
                secilen = dosya.sec(baslik, (tur,))
            except RuntimeError as exc:
                return self._gonder(500, {"hata": str(exc)})
            if not secilen:
                return self._gonder(200, {"iptal": True})
            secim = firmware.dosya_sec(
                [c.id for c in hedef], secilen, str(g.get("surum", "")))
            return self._gonder(200, {"dosyalar": secim,
                                      "cihazSayisi": len(hedef),
                                      "seciliSayi": len(firmware.secilenler())})

        if yol == "/api/firmware/surum":
            # Yalnız hedef sürüm değişir; seçili dosyaya dokunulmaz.
            env = _env(g.get("set"))
            cihazlar = self._hedef_cihazlar(env, g)
            secim = firmware.surum_yaz([c.id for c in cihazlar],
                                       str(g.get("surum", "")))
            return self._gonder(200, {"dosyalar": secim})

        if yol == "/api/firmware/dosya":
            # Yolla doğrudan atama. Arayüz bunu kullanmaz (orada dosya
            # işletim sisteminin seçicisinden gelir, bkz. /api/firmware/sec);
            # penceresiz çalıştırmada ve testlerde gereken uç budur.
            # Hedef: tek cihaz (cihazlar: [id]) ya da bütün grup.
            env = _env(g.get("set"))
            yol_metni = g.get("yol")
            if not isinstance(yol_metni, str) or not yol_metni.strip():
                return self._gonder(400, {"hata": "dosya yolu gerekli"})
            cihazlar = self._hedef_cihazlar(env, g)
            # Yükleme ucu olmayan cihaza imaj atanmaz: "gruba uygula"
            # dediğinde listede yükleme yapılamayacak bir cihaz varsa
            # onu sessizce atlamak, sonra "neden yüklenmedi" sorusunu
            # doğuruyordu — hiç seçilmemiş görünmesi doğrusu.
            hedef = [c for c in cihazlar if firmware.destekli(c)]
            if not hedef:
                return self._gonder(400, {
                    "hata": "Seçilen cihazlarda yazılım yükleme tanımlı değil"})
            secim = firmware.dosya_sec(
                [c.id for c in hedef], yol_metni, str(g.get("surum", "")))
            return self._gonder(200, {"dosyalar": secim,
                                      "cihazSayisi": len(hedef),
                                      "seciliSayi": len(firmware.secilenler())})

        if yol == "/api/firmware/sil":
            if g.get("hepsi") is True:
                firmware.temizle()
                return self._gonder(200, {"silindi": "hepsi", "seciliSayi": 0})
            env = _env(g.get("set"))
            cihazlar = self._hedef_cihazlar(env, g)
            silindi = firmware.sil([c.id for c in cihazlar])
            return self._gonder(200, {
                "silindi": silindi,
                "dosyalar": firmware.secilenler([c.id for c in cihazlar]),
                "seciliSayi": len(firmware.secilenler())})

        if yol == "/api/firmware/yukle":
            env = _env(g.get("set"))
            cihazlar = self._hedef_cihazlar(env, g)
            # Yalnız imajı seçilmiş cihazlar kuyruğa girer: dosyası
            # olmayanı işe koymak, satırı "hata" ile dolduran ama hiçbir
            # şey yapmayan bir koşu demek.
            hedef = [c for c in cihazlar
                     if firmware.destekli(c) and firmware.secili_var(c.id)]
            if not hedef:
                return self._gonder(400, {
                    "hata": "Yüklenecek dosyası seçilmiş cihaz yok"})
            is_ = isler.Is("fw", f"Yazılım yükleme · {len(hedef)} cihaz",
                           env.set_no, anahtar=f"fw:{env.set_no}")
            is_, yeni = isler.YONETICI.ekle(is_, firmware_isi(env, hedef))
            return self._gonder(200 if yeni else 202,
                                {**is_.dto(satir=False), "yeni": yeni})

        if yol == "/api/excel":
            env = _env(g.get("set"))
            is_ = isler.Is("excel", f"Excel üret · Set {env.set_no}",
                           env.set_no, anahtar=f"excel:{env.set_no}")
            is_, yeni = isler.YONETICI.ekle(is_, excel_isi(env))
            return self._gonder(200 if yeni else 202,
                                {**is_.dto(satir=False), "yeni": yeni})

        if yol == "/api/mqtt/basla":
            env = _env(g.get("set"))
            broker = env.piscu_ip()
            if not broker:
                return self._gonder(400, {"hata": "PISCU adresi bulunamadı"})
            piscu.DINLEYICI.basla(broker)
            return self._gonder(200, piscu.DINLEYICI.durum())

        if yol == "/api/mqtt/dur":
            piscu.DINLEYICI.dur()
            return self._gonder(200, piscu.DINLEYICI.durum())

        return self._gonder(404, {"hata": "bilinmeyen yol"})

    # ---- ayrıntılı işlemler ----
    def _hedef_cihazlar(self, env, g):
        """İstemcinin seçtiği grup/cihaz listesini envanterden çözer."""
        idler = g.get("cihazlar")
        if isinstance(idler, list) and idler:
            if len(idler) > 256:
                raise ValueError("Çok fazla cihaz seçildi")
            return [_cihaz(env, str(i)) for i in idler]
        grup = kategori.grup_bul(str(g.get("grup", "")))
        if grup is None:
            raise ValueError("Geçerli bir hedef grup seçilmedi")
        return [c for c in env.cihazlar if kategori.grup_eslesir(grup, c)]

    def _hafif_yenileme(self, g: dict):
        """Doğrulanmış cihazların hafif yenilenmesi.

        Tam tarama sürerken çalışmaz: aynı cihaza iki taraftan istek
        gitmesi hem cihazı yorar hem sonuçları karıştırır.

        Cihaza YAZAN bir koşu (IP atama, konfigürasyon, yazılım yükleme)
        sürerken de çalışmaz. Kuyruk tek işçili olduğu için tam tarama bu
        koşularla asla çakışmaz; hafif yenileme ise kuyruğa girmeden,
        isteği karşılayan iş parçacığında okuma yapar — tek çakışabilen
        yol burasıdır. Koşu sırasında cihaz yeniden başlıyor ya da PoE
        portu kapalı oluyor; araya giren okuma o geçici hâli kalıcı sonuç
        diye yazardı.
        """
        env = _env(g.get("set"))
        if isler.YONETICI.aktif(f"tarama:{env.set_no}"):
            return self._gonder(409, {
                "hata": "Tam tarama sürüyor", "beklemede": True})
        kosu = next((j for j in isler.YONETICI.liste()
                     if j.tur in YAZAN_ISLER and j.set_no == env.set_no
                     and j.durum == isler.CALISIYOR), None)
        if kosu is not None:
            return self._gonder(409, {"hata": f"{kosu.baslik} sürüyor",
                                      "beklemede": True})

        gor = isler.gorunum(env.set_no)
        istenen = g.get("cihazlar")
        if istenen is not None and not isinstance(istenen, list):
            raise ValueError("cihazlar bir liste olmalı")

        hedefler = []
        for c in env.cihazlar:
            s = gor.al(c.id)
            if s is None or s.durum != dogrulama.YESIL:
                continue                      # yalnız doğrulanmış cihazlar
            if istenen and c.id not in istenen:
                continue
            hedefler.append(c)
        hedefler = hedefler[:ayar.HAFIF_SINIR]

        telemetri = None
        # kyland ve adb de listede: switch kendi çalışma süresini, Android
        # panel de SIP dahili numarasını her zaman veremiyor; ikisi de
        # telemetriden tamamlanıyor (bkz. okuma.cihaz_oku).
        if any(c.yontem in ("mqtt", "app", "kyland", "adb") for c in hedefler):
            telemetri = _telemetri_onbellekten(env.set_no)
            if telemetri is None:
                # Önbellek boş — keşif turu henüz çalışmamış olmalı. Bir kez
                # toplanır, sonraki turlar oradan okur.
                try:
                    telemetri = _telemetri(env)
                    _telemetri_yaz(env.set_no, telemetri)
                except Exception:
                    telemetri = None

        ntp = env.piscu_ip()

        # Paralel okunur. Sırayla okunduğunda turun KENDİSİ cihaz sayısıyla
        # birlikte uzuyordu (17 cihazda ~7 sn); arayüzün iki saniyede bir
        # yenilemesinin bir anlamı kalmıyor, "canlı" görünen veri yedi
        # saniye eskimiş oluyordu.
        def tek(c):
            # Nesil okumadan HEMEN önce alınır: paralel turda cihaz başına
            # sıra numarası gerekiyor, tur başına değil (bkz. isler.cihaz_turu).
            nesil = isler.sonraki_nesil()
            sonuc = okuma.cihaz_oku(c, kimlik=_kimlik(c), telemetri=telemetri,
                                    timeout=min(ayar.OKUMA_TIMEOUT, 3.0),
                                    beklenen_ntp=ntp, pbx_ip=env.piscu_ip())
            sonuc.nesil = nesil
            gor.yaz(c.id, sonuc)

        if hedefler:
            havuz = ThreadPoolExecutor(
                max_workers=min(ayar.HAFIF_WORKER, len(hedefler)))
            try:
                list(havuz.map(tek, hedefler))
            finally:
                havuz.shutdown(wait=True)

        return self._gonder(200, {**_durum_govdesi(env),
                                  "yenilenen": [c.id for c in hedefler]})

    def _kimlik_dene(self, g: dict):
        """Kullanıcının girdiği kimliği SEÇİLEN CİHAZDA dener.

        Form doldurulmuş olması doğruluk sayılmaz; kimlik ancak cihazdan
        gerçekten doğrulanmış veri alınırsa belleğe yazılır.
        """
        env = _env(g.get("set"))
        c = _cihaz(env, g.get("cihazId"))
        kullanici = g.get("kullanici", "")
        parola = g.get("parola", "")
        if not isinstance(kullanici, str) or not isinstance(parola, str):
            raise ValueError("Kullanıcı adı ve parola metin olmalı")
        if not kullanici.strip():
            raise ValueError("Kullanıcı adı gerekli")
        if len(kullanici) > 128 or len(parola) > 256:
            raise ValueError("Kullanıcı adı ya da parola çok uzun")

        gruba = g.get("grubaUygula") is True
        grup = okuma.kimlik_grubu(c)

        nesil = isler.sonraki_nesil()
        sonuc = okuma.cihaz_oku(c, kimlik=(kullanici, parola),
                                telemetri=None, timeout=ayar.KIMLIK_TIMEOUT,
                                beklenen_ntp=env.piscu_ip(),
                                pbx_ip=env.piscu_ip())
        sonuc.nesil = nesil
        gor = isler.gorunum(env.set_no)

        if sonuc.durum == dogrulama.YESIL:
            # Sıra önemli: önce cihazdan doğrulandı, sonra belleğe yazılır.
            kimlik_deposu.ver(c.id, c.ip, kullanici, parola,
                              grup=grup, gruba_uygula=gruba)
            gor.yaz(c.id, sonuc)
            return self._gonder(200, {
                "sonuc": "dogrulandi",
                "cihaz": _cihaz_dto(c, gor.al(c.id)),
                "durum": _durum_govdesi(env),
                "grubaUygulandi": bool(gruba and grup),
            })

        # BAŞARISIZ: bellekteki önceki (çalışan) kimlik ezilmez.
        mevcut = gor.al(c.id)
        if mevcut is None or mevcut.durum != dogrulama.YESIL:
            gor.yaz(c.id, sonuc)

        mesaj = {
            dogrulama.KIMLIK_BEKLIYOR: "Kullanıcı adı veya parola doğrulanamadı",
            dogrulama.DOGRULANAMADI: sonuc.aciklama or "Cihaz yanıtı doğrulanamadı",
        }.get(sonuc.dogrulama, sonuc.aciklama or "Cihaz okunamadı")
        kod = 401 if sonuc.dogrulama == dogrulama.KIMLIK_BEKLIYOR else 502
        return self._gonder(kod, {
            "sonuc": sonuc.dogrulama, "hata": mesaj,
            "cihaz": _cihaz_dto(c, gor.al(c.id)),
        })

    def _hata_yanit(self):
        """Beklenmeyen hata: kullanıcıya sade metin, loga ayrıntı."""
        iz = traceback.format_exc()
        sys.stderr.write(iz)
        self._gonder(500, {"hata": "Panelde beklenmeyen bir sorun oluştu"})


# ─────────────────────────────────────────────────────────── kapanış ──────
def temizle() -> None:
    """Uygulama kapanırken: kuyruk, dinleyici ve bellekteki kimlikler."""
    try:
        isler.YONETICI.kapat()
    except Exception:
        pass
    try:
        piscu.DINLEYICI.dur()
    except Exception:
        pass
    with _telemetri_kilit:
        _telemetri_onbellek.clear()
    konfig.hedefleri_unut()
    firmware.temizle()
    kimlik_deposu.hepsini_unut()


def sunucu(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Yalnız yerel arayüzde dinleyen sunucu."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Bu servis yalnızca localhost üzerinde çalışır")
    # Konfigürasyon varsayılanları açılışta dosyadan gelir (parola hariç;
    # o hiç yazılmaz). İki giriş noktası da (app.py ve main) buradan
    # geçtiği için yükleme tek yerde duruyor.
    konfig.varsayilanlari_yukle()
    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    p = argparse.ArgumentParser(
        description=f"{ayar.APP_ADI} — yerel API (pencere açmaz)")
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--admin-parolasi", default=None,
                   help="verilirse admin ekranı bu şifreyi sorar; "
                        "hiçbir yere yazılmaz")
    a = p.parse_args()
    admin_parolasi_ayarla(a.admin_parolasi)

    try:
        srv = sunucu("127.0.0.1", a.port)
    except OSError as exc:
        print(f"[HATA] {a.port} portu açılamadı: {exc}")
        return 1

    print(f"API: http://127.0.0.1:{a.port}   (durdurmak için Ctrl-C)")
    print(f"DeviceMap: {ayar.DEVICE_MAP}")
    print("Kimlik bilgileri arayüzden istenir, hiçbir yere yazılmaz.")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        while t.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nKapatılıyor.")
    finally:
        srv.shutdown()
        srv.server_close()
        temizle()
    return 0


if __name__ == "__main__":
    sys.exit(main())
