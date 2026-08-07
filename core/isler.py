#!/usr/bin/env python3
"""İş kuyruğu ve tarama görüntüsü.

Uzun cihaz işlemleri HTTP isteğini kilitlemez: istek bir iş oluşturur ve
hemen döner, iş arka planda FIFO sırayla çalışır, arayüz iş durumunu
sorarak canlı gösterir.

İki şey bilerek ayrı tutulur:

  · İŞ (Is)       — ne yapıldığının kaydı. Biter, kuyrukta durur, silinir.
  · GÖRÜNÜM       — cihazların o anki durumu. İşten bağımsızdır.

Kuyruk geçmişindeki eski bir iş sonucunun yeni tarama görüntüsünü ezmesi
tam olarak bu ayrım olmadığında oluyor. Ayrıca her okuma bir "nesil"
numarasıyla yazılır: daha eski nesilli bir cevap, daha yeni bir sonucu
geri alamaz. Kullanıcı şifre girip cihazı yeşile çevirdikten sonra hâlâ
yolda olan tarama cevabı onu turuncuya döndüremez.

İş satırlarında parola, Authorization başlığı ya da ham yığın izi
BULUNMAZ; yalnızca kullanıcıya gösterilebilir metin bulunur.
"""
from __future__ import annotations

import itertools
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import ayar, dogrulama
from .hata import CihazHatasi

BEKLIYOR, CALISIYOR, TAMAM, IPTAL, HATA = (
    "bekliyor", "calisiyor", "tamam", "iptal", "hata")

# Okuma nesli — süreç boyunca artan tek sayaç.
_NESIL = itertools.count(1)


def sonraki_nesil() -> int:
    return next(_NESIL)


# ─────────────────────────────────────────────────────────── görünüm ──────
class Gorunum:
    """Bir tren setinin o anki cihaz durumları."""

    def __init__(self, set_no: int):
        self.set_no = set_no
        self._sonuc: dict[str, dogrulama.Sonuc] = {}
        self._kilit = threading.Lock()
        self.son_tarama: float | None = None

    def yaz(self, cihaz_id: str, sonuc: dogrulama.Sonuc) -> bool:
        """Sonucu yazar. Daha yeni bir sonuç varsa yazmaz ve False döner."""
        with self._kilit:
            eski = self._sonuc.get(cihaz_id)
            if eski is not None and eski.nesil > sonuc.nesil:
                return False
            self._sonuc[cihaz_id] = sonuc
            return True

    def al(self, cihaz_id: str) -> dogrulama.Sonuc | None:
        with self._kilit:
            return self._sonuc.get(cihaz_id)

    def hepsi(self) -> dict[str, dogrulama.Sonuc]:
        with self._kilit:
            return dict(self._sonuc)

    def sayilar(self) -> dict:
        return dogrulama.sayilar(self.hepsi().values())

    def kimlik_bekleyenler(self) -> list[str]:
        return [k for k, s in self.hepsi().items() if dogrulama.kimlik_bekliyor(s)]

    def temizle(self) -> None:
        with self._kilit:
            self._sonuc.clear()


_GORUNUM: dict[int, Gorunum] = {}
_GORUNUM_KILIT = threading.Lock()


def gorunum(set_no: int) -> Gorunum:
    with _GORUNUM_KILIT:
        return _GORUNUM.setdefault(int(set_no), Gorunum(int(set_no)))


def _hata_metni(exc: BaseException) -> str:
    """İşin neden bittiğini kullanıcıya anlatan tek cümle.

    Kendi hata sınıflarımızın (CihazHatasi ailesi) ve girdi doğrulamasının
    (ValueError) metinleri kullanıcı için yazılmıştır, parola içermez ve
    ne yapılacağını söyler: "Yataklı_2 için kullanıcı adı/parola
    girilmemiş" ile "KimlikHatasi" arasındaki fark, kullanıcının işi
    çözüp çözemeyeceğidir.

    Tanımadığımız istisnalarda yalnız sınıf adı kalır — beklenmeyen bir
    hatanın metni iç bilgi ya da ham iz taşıyabilir.
    """
    if isinstance(exc, (CihazHatasi, ValueError, FileNotFoundError)):
        metin = str(exc).strip()
        if metin:
            return metin
    return f"İş yürütülemedi: {type(exc).__name__}"


# ──────────────────────────────────────────────────────────────── iş ──────
class Is:
    """Tek bir arka plan işi."""

    def __init__(self, tur: str, baslik: str, set_no: int,
                 anahtar: str | None = None):
        self.id = f"j{uuid.uuid4().hex[:10]}"
        self.tur = tur
        self.baslik = baslik
        self.set_no = int(set_no)
        self.anahtar = anahtar or f"{tur}:{set_no}"
        self.durum = BEKLIYOR
        self.olusturma = time.time()
        self.baslama: float | None = None
        self.bitis: float | None = None
        self.hata: str | None = None          # worker hatası (cihaz hatası değil)
        self.iptal = threading.Event()
        self._satir: dict[str, dict] = {}
        self._sira: list[str] = []
        self._bilgi: set[str] = set()      # sayaçlara girmeyen satırlar
        self._kilit = threading.Lock()

    # ---- satırlar ----
    def satir_kur(self, cihaz) -> None:
        """Tarama başlamadan önce her cihaz için satır oluşturulur.

        Satırların baştan var olması arayüzün "ne yapılıyor"u ilk saniyeden
        göstermesini sağlar; cihazlar bittikçe belirmez, durumları değişir.
        """
        with self._kilit:
            self._satir[cihaz.id] = {
                "cihazId": cihaz.id, "ad": cihaz.ad, "ip": cihaz.ip,
                "yontem": cihaz.yontem, "durum": BEKLIYOR, "not": "Kuyrukta",
            }
            self._sira.append(cihaz.id)

    def ozel_satir(self, anahtar: str, ad: str, durum: str = TAMAM,
                   not_: str = "", ip: str = "", yol: str = "") -> None:
        """Cihaza bağlı olmayan satır (betik çıktısı, üretilen dosya...).

        Bu satırlar sayaçlara girmez: "42 cihazdan 7'si başarılı" derken
        araya bir ilerleme satırı karışmamalı.

        `yol` verilirse satır bir dosyayı gösteriyor demektir; arayüz onu
        açabilir. Yolu arayüz göndermez, buradan okunur (bkz. core/dosya).
        """
        with self._kilit:
            if anahtar not in self._satir:
                self._sira.append(anahtar)
            self._bilgi.add(anahtar)
            self._satir[anahtar] = {
                "cihazId": anahtar, "ad": ad[:200], "ip": ip,
                "yontem": "", "durum": durum, "not": not_[:200],
                "dosya": bool(yol), "yol": yol,
            }

    def satir_guncelle(self, cihaz_id: str, durum: str, not_: str = "") -> None:
        with self._kilit:
            satir = self._satir.get(cihaz_id)
            if satir is None:
                return
            satir["durum"] = durum
            if not_:
                satir["not"] = not_

    def satirlar(self) -> list[dict]:
        # Dosya yolu arayüze gönderilmez: arayüzün dosyayı açmak için
        # bilmesi gereken tek şey satırın bir dosya olduğu. Yolu, isteği
        # karşılayan uç buradan okur (dosya_yolu).
        with self._kilit:
            return [{k: v for k, v in self._satir[a].items() if k != "yol"}
                    for a in self._sira if a in self._satir]

    def dosya_yolu(self, anahtar: str) -> str:
        with self._kilit:
            return (self._satir.get(anahtar) or {}).get("yol", "")

    # ---- sayaçlar ----
    def sayilar(self) -> dict:
        say = {"toplam": 0, "basarili": 0, "erisimBekleyen": 0, "hatali": 0,
               "bekleyen": 0, "atlanan": 0}
        with self._kilit:
            bilgi = set(self._bilgi)
        for s in self.satirlar():
            if s["cihazId"] in bilgi:
                continue
            say["toplam"] += 1
            d = s["durum"]
            if d == "tamam":
                say["basarili"] += 1
            elif d == "kimlik":
                say["erisimBekleyen"] += 1
            elif d == "hata":
                say["hatali"] += 1
            elif d == "atlandi":
                say["atlanan"] += 1
            else:
                say["bekleyen"] += 1
        return say

    def ilerleme(self) -> float:
        say = self.sayilar()
        if not say["toplam"]:
            return 1.0 if self.durum in (TAMAM, IPTAL, HATA) else 0.0
        bitmis = say["toplam"] - say["bekleyen"]
        return round(bitmis / say["toplam"], 4)

    def dto(self, satir: bool = True) -> dict:
        say = self.sayilar()
        veri = {
            "id": self.id, "tur": self.tur, "baslik": self.baslik,
            "setNo": self.set_no, "durum": self.durum,
            "olusturma": self.olusturma, "baslama": self.baslama,
            "bitis": self.bitis, "ilerleme": self.ilerleme(),
            "hata": self.hata, "sayilar": say,
            # İptal istendi ama iş henüz duruyor: worker o an bir cihazın
            # zaman aşımını bekliyor olabiliyor. Arayüz bu aralıkta hâlâ
            # "Çalışıyor" yazınca düğmeye basan kişi bir şey olmadı sanıyor.
            "iptalIstendi": self.iptal.is_set(),
        }
        if satir:
            veri["satirlar"] = self.satirlar()
        return veri


# ───────────────────────────────────────────────────────── yönetici ───────
class Yonetici:
    """FIFO iş kuyruğu — aynı anda tek iş çalışır."""

    def __init__(self, gecmis_siniri: int = 20):
        self._isler: list[Is] = []
        self._kilit = threading.RLock()
        self._sira: list[Is] = []
        self._uyandir = threading.Condition(self._kilit)
        self._calisan: Is | None = None
        self._kapanis = threading.Event()
        self._is_govde: dict[str, callable] = {}
        self._surucu: threading.Thread | None = None
        self.gecmis_siniri = gecmis_siniri
        self._surucu_kur()

    def _surucu_kur(self) -> None:
        """Dağıtıcı iş parçacığını (yeniden) başlatır.

        Her ekleme öncesi denetleniyor: iş parçacığı beklenmedik bir
        şekilde ölürse kuyruk sessizce durur ve bütün işler sonsuza kadar
        "bekliyor" görünür. Burada kendini toparlıyor.
        """
        with self._kilit:
            if self._kapanis.is_set():
                return
            if self._surucu is not None and self._surucu.is_alive():
                return
            self._surucu = threading.Thread(target=self._dongu, daemon=True,
                                            name="is-kuyrugu")
            self._surucu.start()

    def ac(self) -> None:
        """Kapatılmış yöneticiyi yeniden kullanılabilir hale getirir."""
        self._kapanis.clear()
        self._surucu_kur()

    def kapali_mi(self) -> bool:
        return self._kapanis.is_set()

    # ---- kuyruk ----
    def ekle(self, is_: Is, govde) -> tuple[Is, bool]:
        """İşi kuyruğa alır.

        Aynı anahtarlı bekleyen/çalışan iş varsa YENİ iş oluşturulmaz;
        mevcut iş döndürülür. "Güncelle"ye iki kere basmak ikinci bir
        tarama başlatmaz, hızlı çift tıklama da aynı işe düşer.

        Döner: (iş, yeni_mi)
        """
        if self._kapanis.is_set():
            raise RuntimeError("İş kuyruğu kapatıldı")
        self._surucu_kur()
        with self._kilit:
            mevcut = next((j for j in self._isler
                           if j.anahtar == is_.anahtar
                           and j.durum in (BEKLIYOR, CALISIYOR)), None)
            if mevcut is not None:
                return mevcut, False
            self._isler.append(is_)
            self._is_govde[is_.id] = govde
            self._sira.append(is_)
            self._budama()
            self._uyandir.notify()
            return is_, True

    def bul(self, is_id: str) -> Is | None:
        with self._kilit:
            return next((j for j in self._isler if j.id == is_id), None)

    def liste(self) -> list[Is]:
        with self._kilit:
            return list(self._isler)

    def aktif(self, anahtar: str) -> Is | None:
        with self._kilit:
            return next((j for j in self._isler
                         if j.anahtar == anahtar
                         and j.durum in (BEKLIYOR, CALISIYOR)), None)

    def iptal(self, is_id: str) -> bool:
        with self._kilit:
            is_ = self.bul(is_id)
            if is_ is None or is_.durum in (TAMAM, IPTAL, HATA):
                return False
            is_.iptal.set()
            if is_.durum == BEKLIYOR:
                # Henüz başlamadıysa kuyruktan çıkar; worker'a hiç girmesin.
                if is_ in self._sira:
                    self._sira.remove(is_)
                is_.durum = IPTAL
                is_.bitis = time.time()
                for s in is_.satirlar():
                    is_.satir_guncelle(s["cihazId"], "atlandi", "İptal edildi")
            return True

    def sil(self, is_id: str) -> bool:
        with self._kilit:
            is_ = self.bul(is_id)
            if is_ is None:
                return False
            if is_.durum in (BEKLIYOR, CALISIYOR):
                return False               # önce iptal edilmeli
            self._isler.remove(is_)
            self._is_govde.pop(is_id, None)
            return True

    def _budama(self) -> None:
        """Bitmiş işlerin en eskilerini atar; kuyruk sınırsız büyümesin."""
        bitmis = [j for j in self._isler if j.durum in (TAMAM, IPTAL, HATA)]
        fazla = len(bitmis) - self.gecmis_siniri
        for j in bitmis[:max(0, fazla)]:
            self._isler.remove(j)
            self._is_govde.pop(j.id, None)

    # ---- çalıştırıcı ----
    def _dongu(self) -> None:
        while not self._kapanis.is_set():
            with self._uyandir:
                while not self._sira and not self._kapanis.is_set():
                    self._uyandir.wait(0.5)
                if self._kapanis.is_set():
                    return
                is_ = self._sira.pop(0)
                govde = self._is_govde.get(is_.id)
                self._calisan = is_
            if is_.iptal.is_set():
                is_.durum = IPTAL
                is_.bitis = time.time()
                continue
            is_.durum = CALISIYOR
            is_.baslama = time.time()
            try:
                govde(is_)
                is_.durum = IPTAL if is_.iptal.is_set() else TAMAM
            except Exception as exc:
                # Worker hatası cihaz hatasından ayrı raporlanır: burada
                # sorun cihazda değil, işi yürüten tarafta.
                is_.durum = HATA
                is_.hata = _hata_metni(exc)
            finally:
                is_.bitis = time.time()
                with self._kilit:
                    self._calisan = None

    def kapat(self, sure: float = 3.0) -> None:
        """Kuyruğu durdurur: yeni iş alınmaz, süren işler iptal edilir.

        Uygulama kapanışında çağrılır. Yeniden kullanılacaksa `ac()`
        çağrılmalıdır — aksi halde eklenen işler sonsuza kadar "bekliyor"
        kalırdı.
        """
        self._kapanis.set()
        with self._uyandir:
            for j in self._isler:
                j.iptal.set()
            self._uyandir.notify_all()
        surucu = self._surucu
        if surucu is not None and surucu.is_alive():
            surucu.join(timeout=sure)


YONETICI = Yonetici()


# ───────────────────────────────────────────────── paralel cihaz turu ─────
def cihaz_turu(is_: Is, cihazlar, oku, worker: int | None = None) -> None:
    """Cihaz listesini paralel okur, iş satırlarını canlı günceller.

    `oku(cihaz) -> dogrulama.Sonuc` — hangi protokolün konuşulduğunu
    bilmez; okuma katmanı karar verir.

    İptal her cihazdan ÖNCE denetlenir: sıradaki cihazlara hiç dokunulmaz,
    çalışmakta olan tek istek kendi zaman aşımı kadar sürebilir.
    """
    havuz = ThreadPoolExecutor(max_workers=worker or ayar.TARAMA_WORKER)
    gor = gorunum(is_.set_no)

    def tek(cihaz):
        if is_.iptal.is_set():
            is_.satir_guncelle(cihaz.id, "atlandi", "İptal edildi")
            return
        is_.satir_guncelle(cihaz.id, CALISIYOR, "Okunuyor")
        nesil = sonraki_nesil()
        sonuc = oku(cihaz)
        sonuc.nesil = nesil
        yazildi = gor.yaz(cihaz.id, sonuc)
        durum = {
            dogrulama.YESIL: "tamam",
            dogrulama.TURUNCU: "kimlik",
            dogrulama.KIRMIZI: "hata",
            dogrulama.GRI: "atlandi",
        }[sonuc.durum]
        not_ = sonuc.aciklama
        if not yazildi:
            not_ = f"{not_} (daha yeni bir sonuç mevcut)"
        is_.satir_guncelle(cihaz.id, durum, not_)

    try:
        list(havuz.map(tek, cihazlar))
    finally:
        havuz.shutdown(wait=True)
    gor.son_tarama = time.time()
