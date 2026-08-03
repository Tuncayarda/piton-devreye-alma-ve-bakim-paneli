# Derleme, Test ve Yayınlama

Switch Yönetim Paneli'nin taşınabilir paketlerini üretme ve GitHub Release
çıkarma rehberi.

> Windows için **kurulum paketi** (Inno Setup) ve tüm platformlar için
> **taşınabilir** paketler üretilir. macOS/Linux installer'ları (DMG/PKG,
> DEB/RPM), kod imzalama ve Apple notarization **ileride** ele alınacaktır;
> şu anki çıktılar imzasızdır.

---

## 0. Depo yapısı

```
.
├── docs/                                  bütün belgeler
│   ├── BUILD_RELEASE.md                   bu dosya
│   └── RELEASE_NOTES.md                   Release gövdesi (CI kullanır)
├── .github/workflows/
│   ├── ci.yml                             kurulum + self-test
│   └── build.yml                          paket üretimi ve Release
└── Interface/Switch Yönetim Paneli/        uygulamanın kendisi
    ├── app.py, switch_api.py              kaynak kod
    ├── static/                            arayüz
    ├── icons/                             uygulama simgeleri
    ├── packaging/                         AppImage + Inno Setup
    ├── requirements*.txt                  bağımlılıklar
    └── SwitchYonetimPaneli.spec           PyInstaller
```

---

## 1. Geliştirme çalıştırması

```bash
cd "Interface/Switch Yönetim Paneli"
pip install -r requirements-macos.txt      # ya da -windows / -linux
python3 app.py
```

Faydalı bayraklar:

| Bayrak | İşlevi |
|---|---|
| `--switch-port 8080` | Switch'ler 80 dışında bir porttaysa |
| `--version` | Sürümü yazdırır (tek kaynak: `switch_api.py` → `APP_VERSION`) |
| `--self-test` | Pencere açmadan paketi doğrular (aşağıya bakın) |
| `SYP_HEADLESS=1` | Pencere açmadan servisi çalıştırır (sunucu/CI) |

Uygulama yalnızca **pywebview** ile açılır. Tarayıcıya düşme, Chrome `--app`
ya da `webbrowser` kullanımı yoktur; pywebview yoksa uygulama açılmaz ve
sebebini bir pencereyle bildirir.

---

## 2. Self-test

```bash
python3 app.py --self-test        # kaynak koddan
```

Paketlenmiş uygulamada:

| Platform | Komut |
|---|---|
| Windows | `SwitchYonetimPaneli.exe --self-test` |
| Linux | `SwitchYonetimPaneli --self-test` |
| macOS | `"Switch Yönetim Paneli.app/Contents/MacOS/SwitchYonetimPaneli" --self-test` |

**Ne kontrol eder**

1. `pywebview`, `requests`, `switch_api` içe aktarılabiliyor mu?
1b. **Yalnızca Windows'ta:** `pythonnet` (`import clr`) ve WinForms pencere
   motoru (`webview.platforms.winforms`) gerçekten yükleniyor mu, WebView2
   Runtime registry'de kayıtlı mı? Bu üçü, "import webview" başarılı olsa
   bile pencerenin açılamayacağı durumları yakalar (engellenmiş DLL, eksik
   runtime).
2. `static/` klasörü doğru çözülüyor mu? (kaynakta dosyanın yanı,
   paketlenmişte `sys._MEIPASS`)
3. `index.html`, `app.js`, `style.css`, `piton-logo.svg`, `piton-favicon.png`
   var mı ve boş değil mi?
4. Yerel HTTP servisi rastgele boş bir 127.0.0.1 portunda açılıyor mu?
5. Servis hazır hâle geliyor mu?
6. `GET /` → 200 mü, gövde gerçekten bu uygulamanın arayüzü mü
   (`Switch Yönetim Paneli` + `id="detail"` + sürümlenmiş varlık adresleri)?
7. `GET /api/version` → 200 ve sürüm `APP_VERSION` ile aynı mı?
8. `GET /app.js`, `GET /style.css` → 200 mü?

**Ne yapmaz:** pencere açmaz, işletim sistemi diyaloğu göstermez, switch
taraması yapmaz, yerel ağdaki cihazlara bağlanmaz, kimlik sormaz, internete
çıkmaz. Sunucu `finally` içinde her koşulda kapatılır.

Çıkış kodu: başarılı **0**, başarısız **1**.

> **Windows'ta dikkat.** Uygulama `console=False` (GUI alt sistemi) ile
> derlenir. PowerShell böyle bir exe'yi `& $exe` ile çağırınca **beklemez**
> ve `$LASTEXITCODE` boş kalır — self-test geçse bile kontrol başarısız
> görünür. Doğru kullanım:
>
> ```powershell
> $p = Start-Process -FilePath .\SwitchYonetimPaneli.exe `
>        -ArgumentList '--self-test' -Wait -PassThru -NoNewWindow `
>        -RedirectStandardOutput out.txt -RedirectStandardError err.txt
> Get-Content out.txt
> $p.ExitCode        # 0 ise başarılı
> ```
>
> `cmd.exe` kullanıyorsanız `start /wait SwitchYonetimPaneli.exe --self-test`
> ve ardından `echo %ERRORLEVEL%`.

---

## 3. Yerel build

Ön koşul: **Python 3.12**. `SwitchYonetimPaneli.spec` başka bir sürümle
build almayı durdurur (`SYP_PYTHON_SERBEST=1` ile aşılabilir).

```bash
cd "Interface/Switch Yönetim Paneli"
pip install -r requirements-<platform>.txt
pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean SwitchYonetimPaneli.spec
```

Çıktılar:

| Platform | Çıktı |
|---|---|
| Windows | `dist/SwitchYonetimPaneli/` (onedir) |
| Linux | `dist/SwitchYonetimPaneli/` (onedir) |
| macOS | `dist/Switch Yönetim Paneli.app` |

### Windows kurulum paketi

Inno Setup 6.3+ gerekir ([indir](https://jrsoftware.org/isdl.php)).

```powershell
# WebView2 bootstrapper (bir kez yeterli)
New-Item -ItemType Directory -Force packaging\windows\redist | Out-Null
Invoke-WebRequest "https://go.microsoft.com/fwlink/p/?LinkId=2124703" `
  -OutFile packaging\windows\redist\MicrosoftEdgeWebview2Setup.exe

& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
  "/DMyAppVersion=1.0.1" `
  "/DSourceDir=..\..\dist\SwitchYonetimPaneli" `
  "/DOutputDir=..\..\release" `
  "packaging\windows\SwitchYonetimPaneli.iss"
```

Kurulum paketi ne yapar:

- `_internal` dâhil tüm klasörü `C:\Program Files\Switch Yonetim Paneli`
  altına kurar (yalnızca exe kopyalamak **çalışmaz**)
- WebView2 Runtime'ı registry'den kontrol eder
  (`{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`, HKLM32 ve HKCU32) — yoksa
  Evergreen Bootstrapper'ı sessizce kurar
- Başlat menüsü kısayolu, isteğe bağlı masaüstü kısayolu oluşturur
- Güncellemede çalışan uygulamayı kapatır
- Kaldırıcı üretir; **kullanıcı log ve ayarlarını silmez**
  (`%LOCALAPPDATA%\SwitchYonetimPaneli`)
- Yalnızca x64 Windows 10+ üzerinde kurulur

### Linux AppImage

```bash
cd "Interface/Switch Yönetim Paneli"
./packaging/appimage.sh dist/SwitchYonetimPaneli \
    release/SwitchYonetimPaneli-1.0.1-linux-x86_64.AppImage 1.0.1
# CI ayrıca bunu ZIP'e alır (çalıştırma izni korunsun diye)
zip -9 -j release/SwitchYonetimPaneli-1.0.1-linux-x86_64.zip \
    release/SwitchYonetimPaneli-1.0.1-linux-x86_64.AppImage
```

`appimagetool` sürümü betikte sabittir (**1.9.1**). `APPIMAGETOOL_SHA256`
ortam değişkeni verilirse indirilen araç doğrulanır; verilmezse indirilenin
özeti ekrana yazılır. Elde hazır araç varsa `APPIMAGETOOL_BIN=/yol/appimagetool`
ile indirme atlanır.

---

## 4. GitHub Actions

### `ci.yml` — yayın öncesi kontrol

Tetikleyici: `v*` etiketi push'u, elle çalıştırma.

Maliyet nedeniyle **her commit'te çalışmaz**. Günlük geliştirmede yerelde:

```bash
python3 app.py --self-test
```

Windows / Ubuntu / macOS üzerinde: Python 3.12 kurar, platform
requirements'ı yükler, `compileall` ile derleme kontrolü yapar, kaynak
koddan `--self-test` çalıştırır. Ayrı bir job depoda izlenen hassas dosya
olup olmadığına ve çalışma ağacının temizliğine bakar.

CI gerçek switch'e ya da özel ağa **bağlanmaz**.

### `build.yml` — paket üretimi

Tetikleyici: elle çalıştırma (`workflow_dispatch`) veya `v*` etiketi push'u.

| Matrix | Runner | Çıktı |
|---|---|---|
| windows-x64 | `windows-2025` | onedir ZIP + Inno Setup kurulum paketi |
| linux-x86_64 | `ubuntu-22.04` | AppImage → ZIP |
| macos-arm64 | `macos-15` | `.app` → `ditto` ZIP |
| macos-x64 | `macos-15-intel` | `.app` → `ditto` ZIP |

Her job: checkout → Python 3.12 (pip cache) → bağımlılıklar → sürüm
belirleme → kaynak self-test → temiz PyInstaller build → **paketlenmiş**
self-test → paketleme → çıktı boş mu kontrolü → artifact yükleme.

Ubuntu 22.04 üzerinde build alınır; daha yeni dağıtımlarda çalışma ihtimali
bu sayede artar (glibc geriye dönük uyumlu değildir).

### Elle build başlatma

GitHub → **Actions** → *Build* → **Run workflow**.
Sonuç yalnızca **Artifact** olur, Release oluşmaz.

### Sürüm etiketiyle yayınlama

`v1.2.3` biçiminde etiket push'lanır. Etiketteki sürüm ile
`switch_api.py` içindeki `APP_VERSION` **aynı olmalıdır**; değilse build
açık bir hatayla durur. Bütün build'ler geçmeden Release oluşturulmaz.

Release job'ı artifact'leri indirir, dosyaların var ve boş olmadığını
doğrular, `SHA256SUMS.txt` üretir ve `gh` CLI ile Release'i oluşturur.
Aynı etiket için tekrar çalıştırılırsa varlıklar `--clobber` ile
güncellenir (yeni Release açılmaz).

### Artifact ile Release farkı

| | Artifact | Release |
|---|---|---|
| Ne zaman | Her Build çalıştırması | Yalnızca `v*` etiketinde |
| Süre | 14 gün | Kalıcı |
| Erişim | Depoya erişimi olanlar | Herkes (depo public ise) |
| Checksum | Yok | `SHA256SUMS.txt` |

### İzinler

Workflow'lar en düşük izinle çalışır: build job'larında `contents: read`,
yalnızca Release job'ında `contents: write`. `pull_request_target`
kullanılmaz, fork PR'larına yazma yetkisi verilmez, secret istenmez.

---

## 5. Üretilen dosyalar

```
SwitchYonetimPaneli-<sürüm>-windows-x64-Setup.exe
SwitchYonetimPaneli-<sürüm>-windows-x64.zip
SwitchYonetimPaneli-<sürüm>-linux-x86_64.zip      (içinde .AppImage)
SwitchYonetimPaneli-<sürüm>-macos-arm64.zip
SwitchYonetimPaneli-<sürüm>-macos-x64.zip
SHA256SUMS.txt
```

Doğrulama:

```bash
sha256sum -c SHA256SUMS.txt        # Linux
shasum -a 256 -c SHA256SUMS.txt    # macOS
```

---

## 6. Desteklenen sistemler ve kullanıcı notları

| Platform | Mimari | Not |
|---|---|---|
| Windows 10 21H2+ / 11 | x64 | **WebView2 Runtime** gerekir |
| Ubuntu 22.04+ ve dengi | x86_64 | AppImage |
| macOS 11+ | arm64 | CI yalnız macOS 15'te doğrular |
| macOS 11+ | x86_64 | CI yalnız macOS 15 Intel'de doğrular |

**Windows — ZIP yerine Setup.exe.** ZIP'ten çıkarılan dosyalara Windows
"internetten indirildi" damgası (`Zone.Identifier`) koyar. Bu damga yüzünden
.NET, `_internal\pythonnet\runtime\Python.Runtime.dll` dosyasını
`0x80131515` hatasıyla reddeder ve pencere açılmaz. ZIP kullanmak
zorundaysanız klasörü açtıktan sonra:

```powershell
Get-ChildItem -LiteralPath 'SwitchYonetimPaneli' -Recurse -File | Unblock-File
```

Kurulum paketiyle kurulan dosyalarda bu sorun oluşmaz.

**Windows — WebView2.** Pencere motoru Microsoft Edge WebView2'dir. Windows
10 21H2 ve sonrasında işletim sistemiyle gelir. Yoksa ücretsiz
[Evergreen WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
kurulmalıdır; eksikse uygulama bunu açılışta anlaşılır bir pencereyle söyler.

**macOS — yerel ağ izni.** İlk açılışta macOS yerel ağ erişimi sorar; switch'leri
bulmak için gereklidir. Reddedilirse tarama sonuç vermez
(Sistem Ayarları → Gizlilik ve Güvenlik → Yerel Ağ).

**İmzasız paket uyarıları.** Paketler imzalı değildir:

- Windows: SmartScreen "bilinmeyen yayımcı" uyarısı verebilir →
  *Daha fazla bilgi* → *Yine de çalıştır*.
- macOS: Gatekeeper açılışı engelleyebilir → uygulamaya sağ tık → *Aç*, ya da
  Sistem Ayarları → Gizlilik ve Güvenlik → *Yine de aç*.

**Linux — AppImage.** ZIP içinde dağıtılır (hem yer kazandırır hem
çalıştırma iznini korur):

```bash
unzip SwitchYonetimPaneli-*-linux-x86_64.zip
./SwitchYonetimPaneli-*.AppImage
```

ZIP açıldığında dosya çalıştırılabilir gelir. Yine de izin sorunu görürsen:

```bash
chmod +x SwitchYonetimPaneli-*.AppImage
```

Qt kütüphaneleri eksikse:

```bash
sudo apt install libxcb-cursor0 libegl1 libgl1
```

---

## 7. Log dosyaları

| Platform | Konum |
|---|---|
| Windows | `%LOCALAPPDATA%\SwitchYonetimPaneli\logs\uygulama.log` |
| macOS | `~/Library/Logs/SwitchYonetimPaneli/uygulama.log` |
| Linux | `$XDG_STATE_HOME/SwitchYonetimPaneli/uygulama.log` (yoksa `~/.local/state/...`) |

512 KB'ı geçince devreder, iki yedek tutulur. Uygulama klasörüne hiçbir şey
yazılmaz.

---

## 8. Kapsam dışı / bilinen sınırlar

- CI gerçek switch bağlantısını **test etmez**; yalnızca 127.0.0.1 üzerinde
  kendi servisini sınar. Cihaz uyumluluğu sahada doğrulanmalıdır.
- Kod imzalama ve notarization bu aşamada yoktur; Windows kurulum paketi
  üretilir, macOS/Linux installer'ları yoktur.
- `universal2` macOS paketi üretilmez; iki ayrı mimari çıktı verilir.
- Kimlik bilgileri hiçbir dosyada tutulmaz, kullanıcıdan istenir ve yalnızca
  bellekte kalır.
