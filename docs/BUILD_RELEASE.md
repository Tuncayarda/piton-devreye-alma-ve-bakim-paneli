# Derleme, Test ve Yayınlama

Devreye Alma Paneli'nin taşınabilir paketlerini üretme ve GitHub Release
çıkarma rehberi.

> Windows için **kurulum paketi** (Inno Setup) ve tüm platformlar için
> **taşınabilir** paketler üretilir. macOS/Linux installer'ları (DMG/PKG,
> DEB/RPM), kod imzalama ve Apple notarization **ileride** ele alınacaktır;
> şu anki çıktılar imzasızdır.

---

## 0. Depo yapısı

Depoda **iki** uygulama var; her biri kendi branch'inin kökünde durur ve
ayrı ayrı derlenip ayrı Release alır. Bu ağaç (`main`) Devreye Alma
Paneli'dir; Switch Yönetim Paneli `syp` branch'indedir.

```
.
├── README.md
├── .github/workflows/
│   ├── ci.yml                          kurulum + self-test + testler
│   ├── build-app.yml                   ortak derleme motoru (workflow_call)
│   └── build-devreye.yml               bu uygulama            (dap-v*)
├── app.py                              giriş noktası, pencere, self-test
├── panel_api.py                        yerel HTTP servisi (127.0.0.1)
├── core/                               iş mantığı (ayar, okuma, konfig, …)
├── betikler/                           çalışma anında yüklenen motorlar
│   ├── switch_api.py                   Switch Yönetim Paneli'nden kopya
│   ├── device_verify.py                saha doğrulama betiği
│   └── intercom_ip_assign.py           IP atama betiği
├── DevreyeAlmaPaneli.spec              PyInstaller yapılandırması
├── DeviceMap.json                      topoloji envanteri (pakete girer)
├── Yatakli_Saha_Cihaz_Dogrulama.xlsx   Excel şablonu (pakete girer)
├── static/                             arayüz (html, css, js, görseller)
├── tests/                              birim testler (pakete GİRMEZ)
├── packaging/
│   ├── appimage.sh                     Linux AppImage
│   └── windows/                        Inno Setup betiği
└── docs/                               belgeler ve bağımlılık listeleri
    ├── MIMARI.md                       mimari ve ekranlar
    ├── BUILD_RELEASE.md                bu dosya
    ├── RELEASE_NOTES.md                Release gövdesi (CI kullanır)
    ├── CIHAZ_ENDPOINTLERI.md           cihaz uçları
    ├── CIHAZ_VERI_ALANLARI.md          okunan veri alanları
    └── requirements*.txt               platform + build bağımlılıkları
```

### Pakete giren veri dosyaları

Panel switch erişimini ve saha betiklerini yeniden yazmaz; çalışma anında
dosya yolundan içe aktarır (`core/betik.py`). Kaynaktan çalışırken bunlar
depodaki yerlerinde durur, **paketlenirken paketin köküne kopyalanır**:

| Dosya | Nereden | Ne için |
|---|---|---|
| `switch_api.py` | `betikler/` | switch okuma, PoE |
| `device_verify.py` | `betikler/` | alan ayıklama, Excel şeması |
| `intercom_ip_assign.py` | `betikler/` | IP atama koşusu |
| `DeviceMap.json` | uygulama kökü | cihaz envanteri |
| `Yatakli_Saha_Cihaz_Dogrulama.xlsx` | uygulama kökü | kontrol listesi şablonu |

Yol çözümü `core/ayar.py` → `veri_dosyasi()` içindedir: paketlenmiş durumda
paketin kökü, kaynaktan çalışırken depodaki göreli yol. Beşinden biri
eksikse **spec build'i durdurur** ve `--self-test` ayrıca tek tek arar;
yarım paket üretip sahada "DeviceMap bulunamadı" ile karşılaşmak istemiyoruz.

---

## 1. Geliştirme çalıştırması

```bash
pip install -r docs/requirements-macos.txt   # ya da -windows / -linux
python3 app.py
```

| Bayrak | İşlevi |
|---|---|
| `--tarayici` | Pencere açmaz, sistem tarayıcısında açar |
| `--port 8790` | Yerel servisin portunu sabitler |
| `--admin-parolasi …` | Admin ekranı için parola sorar (verilmezse sorulmaz) |
| `--self-test` | Pencere açmadan paketi doğrular, çıkış kodu döner |
| `--version` | Yalnız sürümü yazar (CI etiket kontrolü bunu kullanır) |

---

## 2. Doğrulama

```bash
python3 app.py --self-test                    # varlıklar + servis + arayüz
python3 -m unittest discover -s tests -t .    # birim testler
```

Self-test ne yapar: veri dosyalarını ve kardeş betikleri arar, DeviceMap'i
okur, `127.0.0.1` üzerinde servisi açar, `/api/surum`, `/api/proje`,
`/api/durum` uçlarını ve arayüzün sunulduğunu sınar. **Cihaza bağlanmaz.**

Birim testler sahte cihaz sunucuları kullanır (`tests/sahte.py`): KYLAND
switch, ISAPI kamera ve `/api/v1` anons cihazı taklit edilir; gerçek ağa
çıkılmaz. `tests/test_arayuz.py` içindeki JS lint adımı `deno` kuruluysa
çalışır, değilse atlanır (`brew install deno`).

Testler kalıcı dosyalara dokunmaz: konfigürasyon varsayılanları geçici bir
dizine yazılır (`PANEL_VERI_DIZINI`).

---

## 3. Yerel build

```bash
pip install -r docs/requirements-build.txt
rm -rf build dist
python3 -m PyInstaller --noconfirm --clean DevreyeAlmaPaneli.spec
```

Build **Python 3.12** ile alınır (bilerek başka sürüm kullanılacaksa
`DAP_PYTHON_SERBEST=1`). Tek dosya (portable) için `DAP_ONEFILE=1`.

Paketlenmiş uygulamada self-test:

```bash
# macOS
"dist/Devreye Alma Paneli.app/Contents/MacOS/DevreyeAlmaPaneli" --self-test
# Linux
./dist/DevreyeAlmaPaneli/DevreyeAlmaPaneli --self-test
# Windows (PowerShell)
dist\DevreyeAlmaPaneli\DevreyeAlmaPaneli.exe --self-test
```

### Windows kurulum paketi

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
  "/DMyAppVersion=0.9.0-dev" `
  "/DSourceDir=..\..\dist\DevreyeAlmaPaneli" `
  "/DOutputDir=..\..\release" `
  "packaging\windows\DevreyeAlmaPaneli.iss"
```

Installer'ın AppId GUID'i Switch Yönetim Paneli'nden **ayrıdır**: iki
uygulama aynı makinede yan yana kurulur, biri diğerinin üzerine gelmez.

### Linux AppImage

```bash
./packaging/appimage.sh dist/DevreyeAlmaPaneli \
  release/DevreyeAlmaPaneli-0.9.0-dev-linux-x86_64.AppImage 0.9.0-dev
```

---

## 4. GitHub Actions

### `ci.yml` — yayın öncesi kontrol

Tetikleyici: `v*`, `syp-v*`, `dap-v*` etiketi push'u, elle çalıştırma.
Maliyet nedeniyle **her commit'te çalışmaz**.

**İki uygulama için** Windows / Ubuntu / macOS üzerinde: Python 3.12 kurar,
platform requirements'ını yükler, `compileall` ile derleme kontrolü yapar,
bu panelin **birim testlerini** koşar ve kaynaktan `--self-test` çalıştırır.
Ayrı iki job: etiket ↔ `APP_VERSION` kontrolü ve depo kontrolleri (izlenen
hassas dosya, çalışma ağacı temizliği).

### `build-app.yml` — ortak derleme motoru

Kendi başına çalışmaz (`workflow_call`). Hangi uygulamanın derleneceğini
çağıran workflow söyler; ortak adımlar tek yerde durur.

| Matrix | Runner | Çıktı |
|---|---|---|
| windows-x64 | `windows-2025` | onedir ZIP + Inno Setup kurulum paketi |
| linux-x86_64 | `ubuntu-22.04` | AppImage → ZIP |
| macos-arm64 | `macos-15` | `.app` → `ditto` ZIP |
| macos-x64 | `macos-15-intel` | `.app` → `ditto` ZIP |

Her job: checkout → Python 3.12 (pip cache) → bağımlılıklar → sürüm
belirleme → **birim testler** (varsa) → kaynak self-test → temiz PyInstaller
build → **paketlenmiş** self-test → paketleme → çıktı doğrulaması → artifact.

Ubuntu 22.04 üzerinde build alınır; daha yeni dağıtımlarda çalışma ihtimali
bu sayede artar (glibc geriye dönük uyumlu değildir).

### `build-devreye.yml` — bu uygulamanın paketleri

Tetikleyici: elle çalıştırma (`workflow_dispatch`) veya **`dap-v*`** etiketi.
Switch Yönetim Paneli `build-switch.yml` ile ayrı derlenir; ikisi birbirini
beklemez, birbirinin Release'ine dokunmaz.

### Sürüm etiketiyle yayınlama

```bash
# core/ayar.py içindeki APP_VERSION ile aynı olmalı
git tag dap-v0.9.0-dev
git push origin dap-v0.9.0-dev
```

| Etiket | Uygulama |
|---|---|
| `dap-v…` | Devreye Alma Paneli |
| `syp-v…` | Switch Yönetim Paneli |
| `v…` | Switch Yönetim Paneli (depoda tek uygulama varken kullanılan eski biçim) |

Etiketteki sürüm ile `core/ayar.py` içindeki `APP_VERSION` **aynı olmalıdır**;
değilse build açık bir hatayla durur. Bütün build'ler geçmeden Release
oluşturulmaz. Ön sürüm ekleri (`-dev`, `-alpha`, `-beta`, `-rc`) Release'i
**pre-release** olarak işaretler.

Release job'ı artifact'leri indirir, dosyaların var ve boş olmadığını
doğrular, `SHA256SUMS.txt` üretir ve `gh` CLI ile Release'i oluşturur. Aynı
etiket için tekrar çalıştırılırsa varlıklar `--clobber` ile güncellenir.

### İzinler

Workflow'lar en düşük izinle çalışır: build job'larında `contents: read`,
yalnızca Release job'ında `contents: write`. `pull_request_target`
kullanılmaz, secret istenmez.

---

## 5. Üretilen dosyalar

```
DevreyeAlmaPaneli-<sürüm>-windows-x64-Setup.exe
DevreyeAlmaPaneli-<sürüm>-windows-x64.zip
DevreyeAlmaPaneli-<sürüm>-linux-x86_64.zip      (içinde .AppImage)
DevreyeAlmaPaneli-<sürüm>-macos-arm64.zip
DevreyeAlmaPaneli-<sürüm>-macos-x64.zip
SHA256SUMS.txt
```

Doğrulama:

```bash
sha256sum -c SHA256SUMS.txt
```

---

## 6. Kullanıcı notları

- **Windows**: WebView2 Runtime gerekir; kurulum paketi yoksa kendisi kurar.
  ZIP'i kullanacaksan Runtime'ı elle kurmak gerekebilir. SmartScreen uyarısı
  imzasız paket olduğu içindir.
- **macOS**: Gatekeeper "geliştirici doğrulanamadı" der. Sağ tık → Aç ya da
  Sistem Ayarları → Gizlilik ve Güvenlik → "Yine de aç".
- **Linux**: AppImage ZIP'ten çıkarılınca çalıştırma izni korunur.
- Kullanıcının kendi verisi (konfigürasyon varsayılanları) kurulum dizinine
  değil işletim sisteminin uygulama verisi dizinine yazılır; kaldırma bunu
  silmez. Parola hiçbir koşulda yazılmaz.

---

## 7. Kapsam dışı / bilinen sınırlar

- Kod imzalama, notarization, DMG/PKG/DEB/RPM üretimi.
- `macos-x64` runner'ı Intel Mac'ler için; Apple Silicon `arm64` paketini
  kullanır.
- Simge dosyaları (`icons/app.icns`, `app.ico`, `app.png`) henüz yok;
  eklendiğinde spec ve paketleme betikleri kendiliğinden kullanır.
