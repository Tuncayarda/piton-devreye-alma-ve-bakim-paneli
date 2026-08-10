#!/usr/bin/env python3
"""Dosyayı işletim sisteminin kendi uygulamasıyla açmak ve seçtirmek.

Panel bir Excel çıkarınca kullanıcının sıradaki işi onu açmaktır; dosyayı
Finder/Gezgin'de elle aramak gereksiz bir adım. Aynı sebeple firmware
imajı da elle yol yazarak değil, işletim sisteminin dosya seçicisiyle
seçilir (bkz. `sec`).

`ac` YOL ALMAZ, yol çağıran taraftan gelir — ama arayüzden gelen bir
metin olarak değil: iş kaydında duran, panelin kendi yazdığı yol olarak.
Tarayıcıdan gelen metinle dosya açmak, yerel serviste bile "herhangi bir
dosyayı aç" ucu demek olurdu. `sec` ise yolu hiç almaz, üretir: seçimi
yapan kullanıcının kendisidir.

Komutlar kabuk üzerinden değil, argüman listesiyle çalıştırılır; dosya
adında boşluk ya da kabuk karakteri olması bir şeyi değiştirmez.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path

from . import ayar


def gunluk_yolu(ad: str) -> Path:
    """Uzun bir koşunun ham çıktısı için zaman damgalı dosya yolu.

    Çıktı kuyruk satırı olarak tutulamayacak kadar uzun (IP atama koşusu
    iki yüz satır yazıyor) ama atılamayacak kadar da değerli: bir port
    neden tamamlanmadı sorusunun cevabı orada. Kuyrukta tek satırla
    açılır (bkz. panel_api.ip_isi).
    """
    damga = time.strftime("%Y%m%d-%H%M%S")
    hedef = ayar.CIKTI_DIZINI / f"{ad}-{damga}.log"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    return hedef


def _komut(yol: Path, klasor: bool) -> list[str]:
    sistem = platform.system()
    if sistem == "Darwin":
        # -R dosyayı Finder'da seçili gösterir.
        return ["open", "-R", str(yol)] if klasor else ["open", str(yol)]
    if sistem == "Windows":
        if klasor:
            return ["explorer", f"/select,{yol}"]
        return ["cmd", "/c", "start", "", str(yol)]
    return ["xdg-open", str(yol.parent if klasor else yol)]


def ac(yol: Path | str, klasor: bool = False) -> None:
    """Dosyayı (ya da bulunduğu klasörü) açar.

    Dosya yoksa hata verir: "açtım" deyip hiçbir şey olmaması, kullanıcıyı
    dosyanın nerede olduğunu aramaya bırakır.
    """
    p = Path(yol)
    if not p.exists():
        raise FileNotFoundError(f"Dosya bulunamadı: {p}")
    try:
        # Windows'ta explorer dosyayı seçtiğinde 1 döndürebiliyor; çıkış
        # kodu burada bir şey ifade etmiyor, o yüzden check edilmez.
        subprocess.run(_komut(p, klasor), check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10)
    except FileNotFoundError as exc:      # açıcı komut yok (kimi Linux)
        raise RuntimeError(
            "Dosyayı açacak bir uygulama bulunamadı") from exc
    except subprocess.SubprocessError as exc:
        raise RuntimeError("Dosya açılamadı") from exc


# ─────────────────────────────────────────────────────── dosya seçtirme ──
# Tarayıcı sanal alanı `<input type=file>` seçiminin gerçek yolunu
# vermiyor; panel de dosyayı kendi dizinine kopyalamıyor, yalnız yolunu
# tutuyor. Bu yüzden seçici, tarayıcıda değil işletim sisteminde açılır:
# kullanıcı pencereden dosyayı seçer, panel yalnız yolu öğrenir.
#
# Diyalog kullanıcı seçim yapana kadar bekler; çağıran uç bu süre boyunca
# bloke olur (servis çok iş parçacıklı, diğer istekler etkilenmez).
SECICI_BEKLEME = 300.0                     # 5 dk sonra vazgeçilmiş sayılır

# "tell application System Events" ile yazılmıyor: o yol ilk çalıştırmada
# otomasyon izni (TCC) soruyor ve izin verilmezse seçici hiç açılmıyor.
# Diyalog osascript'in kendisine ait; pencere öne gelsin diye önce
# uygulama etkinleştirilir.
_MACOS_BETIK = '''
tell me to activate
set secilen to choose file with prompt "{baslik}"{tur}
POSIX path of secilen
'''

_WINDOWS_BETIK = '''
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = "{baslik}"
$d.Filter = "{filtre}"
$d.Multiselect = $false
if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::Out.WriteLine($d.FileName)
}}
'''


def _secici_komutu(baslik: str, uzantilar: tuple[str, ...]) -> list[str]:
    sistem = platform.system()
    if sistem == "Darwin":
        tur = ""
        if uzantilar:
            liste = ", ".join(f'"{u}"' for u in uzantilar)
            tur = f" of type {{{liste}}}"
        return ["osascript", "-e",
                _MACOS_BETIK.format(baslik=baslik, tur=tur)]
    if sistem == "Windows":
        kalip = ";".join(f"*.{u}" for u in uzantilar) or "*.*"
        filtre = (f"Firmware ({kalip})|{kalip}|Tüm dosyalar (*.*)|*.*"
                  if uzantilar else "Tüm dosyalar (*.*)|*.*")
        return ["powershell", "-NoProfile", "-STA", "-Command",
                _WINDOWS_BETIK.format(baslik=baslik, filtre=filtre)]
    # Linux: masaüstü ortamının seçicisi. İkisi de yoksa çağıran taraf
    # anlaşılır bir hata görür — sessizce boş dönmek "iptal etti" gibi
    # okunurdu.
    if shutil.which("zenity"):
        komut = ["zenity", "--file-selection", f"--title={baslik}"]
        if uzantilar:
            kalip = " ".join(f"*.{u}" for u in uzantilar)
            komut.append(f"--file-filter=Firmware | {kalip}")
        return komut
    if shutil.which("kdialog"):
        kalip = " ".join(f"*.{u}" for u in uzantilar) or "*"
        return ["kdialog", "--getopenfilename", ".", kalip,
                "--title", baslik]
    raise RuntimeError(
        "Dosya seçici bulunamadı (zenity ya da kdialog kurulu değil)")


def sec(baslik: str = "Dosya seç",
        uzantilar: tuple[str, ...] = ()) -> str | None:
    """İşletim sisteminin dosya seçicisini açar.

    Dönüş: seçilen dosyanın tam yolu; kullanıcı vazgeçtiyse None.
    Seçici hiç açılamıyorsa RuntimeError.
    """
    komut = _secici_komutu(baslik, uzantilar)
    try:
        r = subprocess.run(komut, capture_output=True, text=True,
                           timeout=SECICI_BEKLEME)
    except FileNotFoundError as exc:
        raise RuntimeError("Dosya seçici açılamadı") from exc
    except subprocess.TimeoutExpired:
        return None                        # pencere açık kaldı: vazgeçildi
    yol = (r.stdout or "").strip()
    if yol:
        return yol
    # Vazgeçme ile gerçek hata ayrı: zenity/kdialog yalnız 1 döndürür,
    # macOS ise "User canceled. (-128)" yazar. Mesaj sistem diline göre
    # çevrildiği için metne değil AppleScript hata numarasına bakılır.
    hata = (r.stderr or "").strip()
    vazgecti = not hata or "-128" in hata or "cancel" in hata.lower()
    if r.returncode != 0 and not vazgecti:
        raise RuntimeError(f"Dosya seçilemedi: {hata.splitlines()[0][:120]}")
    return None
