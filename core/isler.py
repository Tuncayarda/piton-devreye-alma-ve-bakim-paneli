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

# Bir satırın altında tutulan adım sayısının üst sınırı. Adımlar açık işin
# her yoklamasında arayüze gidiyor; sınırsız büyürse uzun bir koşuda cevap
# şişer. En yenileri değerli olduğu için baştan atılır.
ADIM_SINIRI = 40

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
    if isinstance(exc, SystemExit):
        # Süreç içinde çalışan betik sys.exit() çağırdı — neredeyse her
        # zaman argparse'ın geçersiz argümanda yaptığı şey.
        return (f"İş yürütülemedi: betik {exc.code} koduyla çıktı "
                "(geçersiz argüman olabilir)")
    return f"İş yürütülemedi: {type(exc).__name__}"


# ──────────────────────────────────────────────────────────────── iş ──────
class Is:
    """Tek bir arka plan işi."""

    def __init__(self, tur: str, baslik: str, set_no: int,
                 anahtar: str | None = None, otomatik: bool = False):
        self.id = f"j{uuid.uuid4().hex[:10]}"
        self.tur = tur
        self.baslik = baslik
        self.set_no = int(set_no)
        self.anahtar = anahtar or f"{tur}:{set_no}"
        # Kullanıcının değil, arayüzün kendi zamanlayıcısının başlattığı iş.
        # Yalnız geçmiş budamasını ilgilendirir (bkz. Yonetici._budama).
        self.otomatik = bool(otomatik)
        self.durum = BEKLIYOR
        # İşin o anki aşaması — başlıktan ayrı, çünkü başlık sabit
        # ("IP atama · Yatakli_2") ama iş "portlar açılıyor"dan "son
        # doğrulama"ya geçiyor. Yüzde tek başına nerede olunduğunu
        # söylemiyordu.
        self.asama = ""
        self.olusturma = time.time()
        self.baslama: float | None = None
        self.bitis: float | None = None
        self.hata: str | None = None          # worker hatası (cihaz hatası değil)
        self.iptal = threading.Event()
        # İşin kendi hesapladığı ilerleme oranı. Varsayılan hesap
        # "biten satır / toplam satır"; bu bazı işlerde yanlış cevap
        # veriyor (bkz. ilerleme). Yazılırsa o hesabın yerini alır.
        self._oran: float | None = None
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
                   not_: str = "", ip: str = "", yol: str = "",
                   sayilir: bool = False) -> None:
        """Cihaza bağlı olmayan satır (betik çıktısı, üretilen dosya...).

        Bu satırlar varsayılan olarak sayaçlara girmez: "42 cihazdan 7'si
        başarılı" derken araya bir ilerleme satırı karışmamalı.

        `sayilir=True` bunun istisnası: işin gerçek iş birimi cihaz
        değilse (IP atama koşusunda birim PORT) ilerleme o satırlardan
        hesaplanmalı, yoksa yüzde baştan sona %0 kalıyor.

        `yol` verilirse satır bir dosyayı gösteriyor demektir; arayüz onu
        açabilir. Yolu arayüz göndermez, buradan okunur (bkz. core/dosya).
        """
        with self._kilit:
            if anahtar not in self._satir:
                self._sira.append(anahtar)
            if sayilir:
                self._bilgi.discard(anahtar)
            else:
                self._bilgi.add(anahtar)
            # Satır yeniden kurulsa da adımları durur: IP atama koşusunda
            # bir port ikinci turda baştan başlıyor ve o portun ilk turda
            # ne yaşadığı ("cihaz bulunamadı") tam da aranan bilgi.
            eski = self._satir.get(anahtar) or {}
            self._satir[anahtar] = {
                "cihazId": anahtar, "ad": ad[:200], "ip": ip,
                "yontem": "", "durum": durum, "not": not_[:200],
                "dosya": bool(yol), "yol": yol,
                "adimlar": eski.get("adimlar", []),
            }

    def adim_ekle(self, anahtar: str, metin: str, durum: str = TAMAM) -> None:
        """Bir satırın altına adım yazar — satırın kendi küçük geçmişi.

        Koşu satır satır ilerliyor ("port açılıyor", "cihaz aranıyor", "IP
        yazılıyor") ve bu ayrıntı tek bir `not` alanına sığmıyordu: her
        yeni satır bir öncekini siliyor, port hata verince neyin ne zaman
        olduğu kayboluyordu. Arayüz bunları satırın altında kapalı bir
        akordiyonda gösterir.
        """
        with self._kilit:
            satir = self._satir.get(anahtar)
            if satir is None:
                return
            adimlar = satir.setdefault("adimlar", [])
            metin = str(metin).strip()[:160]
            if adimlar and adimlar[-1]["metin"] == metin:
                return                       # aynı adım iki kez yazılmaz
            adimlar.append({"metin": metin, "durum": durum,
                            "zaman": time.time()})
            if len(adimlar) > ADIM_SINIRI:
                del adimlar[:len(adimlar) - ADIM_SINIRI]

    def asama_yaz(self, metin: str) -> None:
        with self._kilit:
            self.asama = str(metin)[:120]

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
        #
        # Adım listesi KOPYALANIR: bu liste kilit dışında JSON'a
        # çevriliyor ve çevirme sırasında koşu yeni bir adım ekleyebilir.
        with self._kilit:
            cikan = []
            for a in self._sira:
                s = self._satir.get(a)
                if s is None:
                    continue
                kopya = {k: v for k, v in s.items() if k != "yol"}
                kopya["adimlar"] = list(s.get("adimlar", ()))
                cikan.append(kopya)
            return cikan

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

    def ilerleme_yaz(self, oran: float) -> None:
        """İşin kendi hesapladığı oranı yazar (0..1) — geri gitmez.

        "Biten satır / toplam satır" her iş için doğru cevap değil: IP
        atama koşusunda portlar koşunun ortasında değil, sonundaki tek
        doğrulama turunda kapanıyor; o yüzden çubuk baştan sona %0
        duruyor, son saniyede %100 oluyordu. O iş kendi aşamalarını
        biliyor ve oranı buradan yazıyor (bkz. ip_atama.Ilerleme).

        Geri gitmemesi kurala bağlı: kullanıcı çubuğun geri gittiğini
        gördüğünde okuduğu bütün sayılara güvenmeyi bırakıyor.
        """
        try:
            deger = float(oran)
        except (TypeError, ValueError):
            return
        deger = min(1.0, max(0.0, deger))
        with self._kilit:
            if self._oran is None or deger > self._oran:
                self._oran = deger

    def ilerleme(self) -> float:
        with self._kilit:
            oran = self._oran
        if oran is not None:
            return round(oran, 4)
        say = self.sayilar()
        if not say["toplam"]:
            return 1.0 if self.durum in (TAMAM, IPTAL, HATA) else 0.0
        bitmis = say["toplam"] - say["bekleyen"]
        return round(bitmis / say["toplam"], 4)

    def dto(self, satir: bool = True) -> dict:
        say = self.sayilar()
        veri = {
            "id": self.id, "tur": self.tur, "baslik": self.baslik,
            "otomatik": self.otomatik, "asama": self.asama,
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
        """Bitmiş işlerin en eskilerini atar; kuyruk sınırsız büyümesin.

        Otomatik taramalar ayrıca budanır. Arayüz dakikada bir tarama
        kuyrukladığı için normal sınıra girselerdi yirmi dakikada bütün
        geçmişi -- IP atama, konfigürasyon, yazılım yükleme kayıtlarını --
        dışarı iterlerdi. Bitmiş otomatik taramadan yalnız en yenisi kalır;
        kullanıcının kendi başlattığı işler olduğu gibi durur.
        """
        for j in [j for j in self._isler
                  if j.otomatik and j.durum in (TAMAM, IPTAL, HATA)][:-1]:
            self._isler.remove(j)
            self._is_govde.pop(j.id, None)
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
                if govde is None:
                    # İş kuyruğa alınıp gövdesi budandıysa (ya da silindiyse)
                    # burada None gelir. Çağırmaya kalkmak TypeError'dı;
                    # sebebi de anlaşılmıyordu.
                    raise RuntimeError("İşin gövdesi bulunamadı")
                govde(is_)
                is_.durum = IPTAL if is_.iptal.is_set() else TAMAM
            except Exception as exc:
                # Worker hatası cihaz hatasından ayrı raporlanır: burada
                # sorun cihazda değil, işi yürüten tarafta.
                is_.durum = HATA
                is_.hata = _hata_metni(exc)
            except BaseException as exc:                     # noqa: BLE001
                # SystemExit ve benzeri BaseException'lar da işi KAPATMALI.
                #
                # Yakalanmadıklarında iş sonsuza kadar "çalışıyor" kalıyor
                # ve dağıtıcı iş parçacığı ölüyordu. İkisinin birlikte
                # sonucu, tek bir çöken koşunun bütün paneli kilitlemesi:
                # "yazan iş sürüyor" sayıldığı için hafif yenileme de tam
                # tarama da 409 ile reddediliyor, ekranlar bir daha
                # tazelenmiyordu (bkz. panel_api hafif yenileme kapısı).
                #
                # En bilinen kaynağı argparse: betiğin main()'i hatalı bir
                # argümanda sys.exit() çağırıyor ve bu Exception değil.
                is_.durum = HATA
                is_.hata = _hata_metni(exc)
                # Yeniden fırlatılmaz: dağıtıcı ayakta kalır, sıradaki iş
                # çalışır. İptal bayrağını kapanış zaten ayrıca yönetiyor.
            finally:
                is_.bitis = time.time()
                with self._kilit:
                    self._calisan = None

    def kapat(self, sure: float | None = None) -> bool:
        """Kuyruğu durdurur: yeni iş alınmaz, süren işler iptal edilir.

        Uygulama kapanışında çağrılır. Yeniden kullanılacaksa `ac()`
        çağrılmalıdır — aksi halde eklenen işler sonsuza kadar "bekliyor"
        kalırdı. Üretim kapanışı süre sınırı kullanmaz: IP atama işinin
        ``finally`` bloğu PoE portlarını geri açmadan süreç sonlandırılamaz.
        ``sure`` yalnız kontrollü tanı/test çağrıları için verilebilir.
        """
        self._kapanis.set()
        with self._uyandir:
            for j in self._isler:
                j.iptal.set()
            self._uyandir.notify_all()
        surucu = self._surucu
        if surucu is not None and surucu.is_alive():
            surucu.join(timeout=sure)
        return surucu is None or not surucu.is_alive()


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
