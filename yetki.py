#!/usr/bin/env python3
"""Yükseltilmiş yetki: denetim, kullanıcıya sorma ve yeniden başlatma.

Panel ağ arayüzünü ve ARP önbelleğini okuyup temizliyor, cihazlara IP
yazıyor ve switch portlarını yönetiyor. Bunların hiçbiri sıradan kullanıcı
yetkisiyle güvenilir çalışmıyor; en pahalı örneği sahada görüldü: ARP kaydı
temizlenemeyince aynı adreste duran cihazlar birbirinin arkasında kalıyor
ve koşu "cihaz bulunamadı" diyor (bkz. docs/MIMARI §9).

Eskiden yetki yoksa konsola tek satır yazılıp çıkılıyordu. Uygulamayı çift
tıklayan kullanıcı hiçbir şey görmüyordu: pencere açılmıyor, sebebi de
görünmüyordu. Artık bir pencere açılır ve iki yol sunar — yükseltilmiş
yetkiyle yeniden başlatmak ya da çıkmak. Üçüncü bir yol (yetkisiz devam)
bilerek yok: yarısı çalışan bir panel, çalışmayandan daha kötü.

Yükseltme YALNIZCA işletim sisteminin kendi izin penceresiyle yapılır;
parola bu sürece hiç girmez, uygulama parola sormaz ve terminale hiçbir şey
devredilmez:

    Windows   ShellExecuteW "runas"  → UAC penceresi
    macOS     osascript "with administrator privileges" → sistem penceresi
    Linux     pkexec → polkit penceresi

macOS'un tek şartı var: uygulama korumalı bir kullanıcı klasöründe
(Masaüstü/Belgeler/İndirilenler) DURMAMALI. Oradaki bir uygulamayı yönetici
penceresiyle başlatmak işe yaramıyor — yükseltilmiş süreç
security_authtrampoline altında doğuyor ve o klasörlere erişimi
reddediliyor, uygulama kendi dosyasını bile açamıyor ("Operation not
permitted"). Bu durum denemeden önce fark edilip söylenir
(bkz. korumali_klasor).
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time

# Kullanıcı sistemin parola penceresini yanıtlayana kadar beklenecek üst
# sınır. Pencere ekranda durduğu sürece bu süre işliyor.
ONAY_BEKLEME = 180.0

BASLIK = "Yönetici yetkisi gerekiyor"

ACIKLAMA = (
    "Devreye Alma Paneli yükseltilmiş yetkiyle çalışmalıdır.\n\n"
    "Panel ağ arayüzünü ve ARP önbelleğini okuyup temizliyor, cihazlara IP "
    "yazıyor ve switch portlarını yönetiyor; bunların hiçbiri sıradan "
    "kullanıcı yetkisiyle güvenilir biçimde yapılamıyor."
)


def gunluk_yolu() -> str:
    """Yükseltilmiş sürecin çıktısının yazılacağı dosya.

    Yeni süreç ayrı bir oturumda ve arkaplanda başlıyor; açılışta düşerse
    kullanıcı hiçbir şey görmez. Çıktısı burada durur.
    """
    import tempfile

    return os.path.join(tempfile.gettempdir(), "devreye-yukseltme.log")


def pid_yolu() -> str:
    """Yükseltilmiş sürecin PID'i — gerçekten ayakta kaldı mı diye.

    Süreç arkaplanda ve başka bir kullanıcıda başlıyor; başlatan taraf
    dönüş kodunu göremiyor. Kabuk PID'i buraya yazar, biz de birkaç saniye
    sonra sürecin hâlâ var olup olmadığına bakarız.
    """
    import tempfile

    return os.path.join(tempfile.gettempdir(), "devreye-yukseltme.pid")


def elle_yol(sistem: str | None = None) -> str:
    """Kullanıcı kendi başlatmak isterse ne yapmalı — platforma göre."""
    sistem = sistem or platform.system()
    if sistem == "Windows":
        return ("Uygulamaya sağ tıklayıp \"Yönetici olarak çalıştır\" ile de "
                "başlatabilirsiniz.")
    return "Terminalden de başlatabilirsiniz:    sudo python3 app.py"


def yonetici_mi() -> bool:
    """Süreç yükseltilmiş yetkiyle mi çalışıyor?

    Tek soru sorulur ("bu süreç yönetici mi"), cevabı işletim sistemine göre
    başka yerden gelir: POSIX'te etkin kullanıcı kimliği, Windows'ta kabuğun
    kendi sorgusu. Arayüz bu ayrımı hiç görmez.
    """
    try:
        if hasattr(os, "geteuid"):
            return os.geteuid() == 0
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _applescript_metin(deger: str) -> str:
    """AppleScript dizesi — tırnak ve ters bölü kaçırılır."""
    return '"' + deger.replace("\\", "\\\\").replace('"', '\\"') + '"'


# macOS'un TCC ile koruduğu kullanıcı klasörleri. Buradaki bir uygulamayı
# SİSTEM PENCERESİYLE yükseltmek işe yaramıyor: yükseltilmiş süreç
# security_authtrampoline altında doğuyor ve bu klasörlere erişimi
# reddediliyor. Sahada iki kez birebir görüldü — önce `app.py`, sonra
# `env/pyvenv.cfg` için "Operation not permitted". Yetkisiz süreçler aynı
# klasörü okuyabildiği için sebep uzun süre gizli kaldı.
#
# Kullanıcı parolasını boşuna girmesin diye bu, DENEMEDEN ÖNCE söylenir.
KORUMALI_KLASORLER = ("Desktop", "Documents", "Downloads")


def korumali_klasor(dizin: str = "", sistem: str | None = None) -> str:
    """Uygulama macOS'un koruduğu bir klasörde mi? Döner: klasör adı ya da "".
    """
    sistem = sistem or platform.system()
    if sistem != "Darwin":
        return ""
    yol = os.path.realpath(
        dizin or os.path.dirname(os.path.abspath(__file__)))
    ev = os.path.realpath(os.path.expanduser("~"))
    for ad in KORUMALI_KLASORLER:
        kok = os.path.join(ev, ad)
        if yol == kok or yol.startswith(kok + os.sep):
            return ad
    return ""


def yukseltme_plani(sistem: str | None = None, calistirilabilir: str = "",
                    argv: list[str] | None = None,
                    donmus: bool | None = None,
                    calisma_dizini: str = "",
                    terminal: bool | None = None) -> dict:
    """Aynı uygulamayı yükseltilmiş yetkiyle başlatacak plan.

    Ayrı bir işlev, çünkü asıl karar burada veriliyor ve sınanabilir olması
    gerekiyor: yanlış kurulan komut satırı, kullanıcının parolasını girip
    hiçbir şeyin açılmadığını görmesi demek.

    Döner: {"yol", "exe", "argv", "komut"} — `yol` boşsa bu platformda
    otomatik yükseltme yok, kullanıcı elle başlatmalı.
    """
    sistem = sistem or platform.system()
    exe = calistirilabilir or sys.executable
    argv = list(sys.argv if argv is None else argv)
    donmus = getattr(sys, "frozen", False) if donmus is None else donmus
    dizin = calisma_dizini or os.getcwd()

    # Paketlenmiş uygulamada argv[0] uygulamanın kendisidir; yorumlayıcıya
    # ikinci kez verilmez. Betik olarak çalışırken argv[0] betiğin yolu ve
    # verilmesi ŞART — yoksa yükseltilmiş süreç boş bir Python açardı.
    if donmus:
        args = argv[1:]
    else:
        betik = argv[0] if argv else ""
        args = ([os.path.abspath(betik)] if betik else []) + argv[1:]

    if sistem == "Windows":
        return {"yol": "runas", "exe": exe, "argv": args, "komut": [],
                "dizin": dizin}

    if sistem == "Darwin":
        import shlex

        kabuk = " ".join(shlex.quote(p) for p in [exe, *args])
        # Arkaplana atılır: osascript yoksa komutun bitmesini bekler,
        # uygulama açık kaldığı sürece de pencere donardı.
        #
        # `nohup` KULLANILMAZ. `do shell script` komutu terminalsiz
        # çalıştırıyor ve macOS'un nohup'ı orada "can't detach from
        # console: Inappropriate ioctl for device" deyip düşüyordu — panel
        # hiç başlamıyor, kullanıcı da sebebini göremiyordu. Arkaplana
        # atmak için `&` yeterli; girdi /dev/null'dan verilir, çıktı
        # günlüğe gider (süreç açılışta düşerse bakılacak tek yer orası).
        kabuk = (f"cd {shlex.quote(dizin)} && "
                 f"{kabuk} < /dev/null > {shlex.quote(gunluk_yolu())} 2>&1 & "
                 f"echo $! > {shlex.quote(pid_yolu())}")
        return {"yol": "osascript", "exe": exe, "argv": args, "dizin": dizin,
                "komut": ["osascript", "-e",
                          f"do shell script {_applescript_metin(kabuk)} "
                          "with administrator privileges"]}

    if shutil.which("pkexec"):
        # polkit ortamı temizler; pencerenin açılabilmesi için ekran
        # değişkenleri açıkça taşınır.
        cevre = [f"{ad}={os.environ[ad]}" for ad in ("DISPLAY", "XAUTHORITY",
                                                     "WAYLAND_DISPLAY")
                 if os.environ.get(ad)]
        return {"yol": "pkexec", "exe": exe, "argv": args, "dizin": dizin,
                "komut": ["pkexec", *(["env", *cevre] if cevre else []),
                          exe, *args]}

    return {"yol": "", "exe": exe, "argv": args, "komut": [], "dizin": dizin}




def _yasiyor(pid: int) -> bool:
    """PID hâlâ var mı? Başka kullanıcının süreci de "var"dır."""
    try:
        os.kill(pid, 0)
    except PermissionError:            # root'un süreci: bize kapalı ama var
        return True
    except OSError:
        return False
    return True


def _tcc_ipucu(metin: str) -> str:
    """macOS gizlilik korumasının imzası varsa ne yapılacağını söyler.

    Masaüstü, Belgeler ve İndirilenler klasörleri korumalıdır: oradaki bir
    uygulamayı sistem penceresiyle başlatan süreç dosyayı açamayabiliyor ve
    hata "Operation not permitted" olarak görünüyor. Sebebi bilmeden
    bakıldığında bu, dosya izniyle karıştırılıyor.
    """
    if platform.system() != "Darwin":
        return ""
    if "not permitted" not in metin.lower():
        return ""
    return ("\n\nmacOS gizlilik koruması engellemiş olabilir: Masaüstü, "
            "Belgeler ve İndirilenler klasörleri korumalıdır. Terminalden "
            "\"sudo python3 app.py\" ile başlatın ya da uygulamayı bu "
            "klasörlerin dışına taşıyın.")


def gunluk_ozeti() -> str:
    """Günlüğün son anlamlı satırı — kullanıcıya gösterilecek sebep."""
    try:
        with open(gunluk_yolu(), encoding="utf-8", errors="replace") as dosya:
            satirlar = [s.strip() for s in dosya if s.strip()]
    except OSError:
        satirlar = []
    if not satirlar:
        return f"Ayrıntı: {gunluk_yolu()}"
    son = satirlar[-1][:200]
    return f"{son}{_tcc_ipucu(son)}\n\nAyrıntı: {gunluk_yolu()}"


def _pid_oku() -> int:
    """Kabuğun yazdığı PID; henüz yazılmadıysa 0."""
    try:
        with open(pid_yolu(), encoding="utf-8") as dosya:
            return int(dosya.read().strip())
    except (OSError, ValueError):
        return 0


def yeni_surec_durumu(bekle: float = 2.0, pid: int = 0) -> tuple[bool, str]:
    """Yükseltilmiş süreç ayakta kaldı mı? Döner: (ayakta, açıklama).

    Arkaplana atılan süreç başka bir kullanıcıda çalışıyor ve başlatan
    taraf onun dönüş kodunu göremiyor: parola girildiği hâlde hiçbir
    pencere açılmayan durumun sebebi tam olarak buydu (macOS'ta `nohup`
    terminalsiz ortamda düşüyordu ve kimse görmüyordu). Kabuğun yazdığı
    PID'e bakılır; süreç açılışta düştüyse günlüğün son satırı sebep
    olarak döner.
    """
    time.sleep(max(0.0, bekle))
    pid = pid or _pid_oku()
    if not pid:
        return True, ""                # PID okunamıyorsa suçlamak yanlış
    if _yasiyor(pid):
        return True, ""
    return False, "Yükseltilmiş süreç açılışta düştü.\n\n" + gunluk_ozeti()


def yukselt(plan: dict | None = None) -> tuple[bool, str]:
    """Yükseltilmiş yeni süreci başlatır. Döner: (başladı mı, açıklama).

    Başarılıysa çağıran taraf ÇIKMALIDIR: aynı uygulamanın iki kopyası aynı
    DeviceMap'e ve aynı switch'e yazmamalı.
    """
    plan = plan or yukseltme_plani()
    if not plan["yol"]:
        return False, ("Bu sistemde otomatik yükseltme yok. "
                       + elle_yol())
    # Eski koşunun günlüğü ve PID'i silinir: bu koşunun sonucu onlardan
    # okunacak, bayat bir dosya yanlış sebep gösterirdi.
    for yol in (gunluk_yolu(), pid_yolu()):
        try:
            os.remove(yol)
        except OSError:
            pass
    try:
        if plan["yol"] == "runas":
            import ctypes

            # list2cmdline: Windows'ta argüman ayrıştırmasını kabuk değil
            # sürecin kendisi yapıyor; boşluklu yolları elle tırnaklamak
            # tam da burada yanlış gidiyordu.
            params = subprocess.list2cmdline(plan["argv"])
            sonuc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", plan["exe"], params, plan["dizin"], 1)
            # ShellExecuteW eski API: 32'den büyük dönüş başarı demek.
            if int(sonuc) <= 32:
                # 1223 = kullanıcı UAC penceresini reddetti.
                return False, ("Yönetici izni verilmedi"
                               if int(sonuc) == 1223 else
                               f"Yeniden başlatılamadı (kod {int(sonuc)})")
            return True, ""

        # BEKLENMEZ. Yükseltme kanalı (macOS'ta security_authtrampoline)
        # başlattığı sürecin BİTMESİNİ bekliyor: `subprocess.run` kullanınca
        # eski süreç, yeni panel kapanana kadar hayatta kalıyordu — Dock'ta
        # ikinci bir uygulama olarak duruyor, panel kapanınca da PID'i ölü
        # bulup yanlışlıkla "açılışta düştü" penceresi açıyordu. Sahada
        # ölçüldü; yalın `do shell script` 12 saniyelik arkaplan süreciyle
        # 0,1 sn'de dönüyor, yükseltilmiş olan dönmüyor.
        #
        # Bu yüzden süreç başlatılır ve KABUĞUN YAZDIĞI PID beklenir: PID
        # dosyası göründüğü an yeni süreç doğmuş demektir.
        surec = subprocess.Popen(plan["komut"], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True,
                                 # Kendi oturumu: biz çıkınca etkilenmesin.
                                 start_new_session=True)
        bitis = time.monotonic() + ONAY_BEKLEME
        while True:
            pid = _pid_oku()
            if pid:
                # Doğum anını gördük; şimdi ayakta kalıp kalmadığına bak.
                return yeni_surec_durumu(pid=pid)
            kod = surec.poll()
            if kod is not None:
                _cikti, hata_metni = surec.communicate()
                satir = (hata_metni or "").strip().splitlines()
                son = satir[-1] if satir else f"kod {kod}"
                if "-128" in son or "User canceled" in son:
                    return False, "Yönetici izni verilmedi"
                return False, f"Yeniden başlatılamadı: {son}"
            if time.monotonic() >= bitis:
                surec.kill()
                return False, "Yönetici izni verilmedi (yanıt gelmedi)"
            time.sleep(0.2)
    except Exception as exc:                       # noqa: BLE001
        return False, f"Yeniden başlatılamadı: {type(exc).__name__}"


# ─────────────────────────────────────────────────────────────── pencere ──
def _html(mesaj: str, yukseltilebilir: bool, elle: str, ipucu: str = "") -> str:
    import html as _html_mod

    dugmeler = (
        '<button class="birincil" onclick="karar(\'yukselt\')">'
        'Yönetici olarak yeniden başlat</button>' if yukseltilebilir else "")
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; padding:28px 30px; background:#101820; color:#e6edf3;
         font:15px/1.55 -apple-system, "Segoe UI", system-ui, sans-serif; }}
  h1 {{ font-size:17px; margin:0 0 14px; color:#ffd479; }}
  p {{ margin:0 0 12px; white-space:pre-wrap; }}
  .ipucu {{ color:#8fd3a6; font-size:13px; }}
  .elle {{ color:#9fb0c0; font-size:13px; }}
  .satir {{ display:flex; gap:10px; margin-top:22px; }}
  button {{ font:inherit; padding:9px 16px; border-radius:8px; cursor:pointer;
           border:1px solid #33455a; background:#1b2735; color:#e6edf3; }}
  button:hover {{ border-color:#4d6a8c; }}
  .birincil {{ background:#2f6feb; border-color:#2f6feb; color:#fff; }}
</style></head><body>
  <h1>{BASLIK}</h1>
  <p>{_html_mod.escape(mesaj)}</p>
  {f'<p class="ipucu">{_html_mod.escape(ipucu)}</p>' if ipucu else ''}
  <p class="elle">{_html_mod.escape(elle)}</p>
  <div class="satir">
    {dugmeler}
    <button onclick="karar('cikis')">Çıkış</button>
  </div>
<script>
  function karar(k) {{
    document.querySelectorAll('button').forEach(b => b.disabled = true);
    window.pywebview.api.karar_ver(k);
  }}
</script></body></html>"""


def _yerel_pencere(mesaj: str, yukseltilebilir: bool, ipucu: str = "") -> str:
    """pywebview yoksa işletim sisteminin kendi penceresi."""
    sistem = platform.system()
    metin = f"{mesaj}\n\n" + (f"{ipucu}\n\n" if ipucu else "") + elle_yol(sistem)
    try:
        if sistem == "Windows":
            import ctypes

            if not yukseltilebilir:
                ctypes.windll.user32.MessageBoxW(None, metin, BASLIK, 0x10)
                return "cikis"
            # MB_YESNO | MB_ICONWARNING; 6 = Evet
            cevap = ctypes.windll.user32.MessageBoxW(
                None, metin + "\n\nYönetici olarak yeniden başlatılsın mı?",
                BASLIK, 0x04 | 0x30)
            return "yukselt" if int(cevap) == 6 else "cikis"

        if sistem == "Darwin" and yukseltilebilir:
            betik = (f"display dialog {_applescript_metin(metin)} "
                     f"with title {_applescript_metin(BASLIK)} "
                     'buttons {"Çıkış", "Yönetici olarak yeniden başlat"} '
                     'default button 2 with icon caution')
            tamam = subprocess.run(["osascript", "-e", betik],
                                   capture_output=True, text=True, timeout=300)
            return ("yukselt" if "Yönetici" in (tamam.stdout or "")
                    else "cikis")
    except Exception:                              # noqa: BLE001
        pass
    return "cikis"


def sor(mesaj: str = "", yukseltilebilir: bool | None = None,
        ipucu: str = "") -> str:
    """Kullanıcıya pencereyle sorar. Döner: "yukselt" | "cikis".

    Pencereyi kapatmak da "cikis"tır: hiçbir yol yetkisiz açılışa çıkmaz.

    `PANEL_YETKI_PENCERESI=0` pencereyi hiç açmaz: kimsenin başında
    olmadığı bir koşuda (CI, otomatik doğrulama) bekleyen bir pencere işi
    sonsuza kadar asar.
    """
    if os.environ.get("PANEL_YETKI_PENCERESI") == "0":
        return "cikis"
    mesaj = mesaj or ACIKLAMA
    if yukseltilebilir is None:
        yukseltilebilir = bool(yukseltme_plani()["yol"])
    try:
        import webview
    except Exception:                              # noqa: BLE001
        return _yerel_pencere(mesaj, yukseltilebilir, ipucu)

    secim = {"karar": "cikis"}
    try:
        pencere = webview.create_window(
            BASLIK, html=_html(mesaj, yukseltilebilir, elle_yol(),
                               ipucu),
            width=620, height=340, resizable=False,
            background_color="#101820")

        def karar_ver(karar):
            secim["karar"] = "yukselt" if karar == "yukselt" else "cikis"
            pencere.destroy()

        pencere.expose(karar_ver)
        webview.start()
    except Exception:                              # noqa: BLE001
        return _yerel_pencere(mesaj, yukseltilebilir, ipucu)
    return secim["karar"]


def dock_gizle() -> None:
    """macOS: bu sürecin Dock simgesini kaldırır.

    Yükseltme onaylandıktan sonra eski süreç birkaç saniye daha yaşıyor —
    yeni sürecin ayakta kaldığını doğruluyor (bkz. yeni_surec_durumu) ve o
    kontrol "açılışta düştü" hatalarını yakalayan şey, kaldırılmamalı. Ama
    o sırada Dock'ta İKİ simge birden duruyor ve panel iki kez açılmış gibi
    görünüyordu. Pencere kapandığına göre simgenin de durmasının anlamı
    yok.
    """
    if platform.system() != "Darwin":
        return
    try:
        from AppKit import NSApplication

        # 1 = NSApplicationActivationPolicyAccessory: süreç yaşar, Dock'ta
        # ve uygulama değiştiricide görünmez.
        NSApplication.sharedApplication().setActivationPolicy_(1)
    except Exception:                              # noqa: BLE001
        pass


def akis(yaz=print) -> int:
    """Yetkisiz açılışın tamamı. Döner: sürecin çıkış kodu.

    0 yalnız yükseltilmiş yeni süreç başladığında döner — bu süreç işini
    devretmiş demektir. Diğer bütün yollar 1: uygulama açılmadı.
    """
    # Tek yol var: sistemin kendi izin penceresi. Terminale devretme yok —
    # kullanıcı izni pencereden verir, uygulamanın terminalle işi yoktur.
    plan = yukseltme_plani()
    ipucu = ""
    korumali = korumali_klasor()
    if korumali:
        # Bu klasörde yükseltilmiş süreç uygulamanın kendi dosyalarını
        # okuyamıyor (bkz. KORUMALI_KLASORLER). Parola boşuna istenmesin
        # diye denemeden ÖNCE söylenir.
        ipucu = (f"Uygulama {korumali} klasöründe. macOS, korumalı "
                 "klasörlerdeki bir uygulamanın yönetici penceresiyle "
                 "başlatılmasına izin vermiyor: uygulamayı bu klasörün "
                 "dışına taşıyın.")
    yaz("[HATA] " + ACIKLAMA.replace("\n\n", " "))
    if ipucu:
        yaz(ipucu)
    if sor(yukseltilebilir=bool(plan["yol"]), ipucu=ipucu) != "yukselt":
        return 1

    # Bu süreç artık yalnız yeni süreci başlatıp doğrulayacak; ekranda işi
    # kalmadı. Simge burada kaldırılmazsa yeni panelin yanında birkaç
    # saniye ikinci bir uygulama gibi duruyor.
    dock_gizle()
    tamam, hata = yukselt(plan)
    if tamam:
        yaz("Yönetici yetkisiyle yeniden başlatılıyor.")
        if platform.system() != "Windows":
            yaz(f"Yeni sürecin çıktısı: {gunluk_yolu()}")
        return 0

    yaz(f"[HATA] {hata}")
    sor(hata or ACIKLAMA, yukseltilebilir=False, ipucu=ipucu)
    return 1
