# Derleme, Test ve Yayınlama

Devreye Alma Paneli'nin taşınabilir paketlerini üretme ve GitHub'da sürüm
yayımlama rehberi.

> Windows için **kurulum paketi** (Inno Setup) ve desteklenen tüm işletim
> sistemleri için **taşınabilir** paketler üretilir. macOS ve Linux kurulum
> paketleri (DMG/PKG, DEB/RPM), kod imzalama ve Apple noter onayı
> (notarization) **ileride** ele alınacaktır; şu anki çıktılar imzasızdır.

---

## 0. Depo yapısı

Depoda **iki** uygulama bulunur. Her uygulama kendi dalının kökünde durur,
ayrı ayrı derlenir ve yayımlanır. Bu ağaç (`main`) Devreye Alma Paneli'dir;
Switch Yönetim Paneli `syp` dalındadır.

```
.
├── README.md
├── .github/workflows/
│   ├── ci.yml                          bağımlılık + self-test + testler
│   ├── build-app.yml                   ortak derleme akışı (workflow_call)
│   └── build-commissioning-panel.yml   bu uygulamanın yayını   (dap-v*)
├── app.py                              giriş noktası, pencere, self-test
├── panel/                              uygulama paketi
│   ├── api/                            servis katmanı + HTTP adaptörü
│   ├── desktop/                        soketsiz pywebview köprüsü
│   ├── i18n.py                         mesaj kataloğu (t / lazy)
│   ├── messages/                       en.json · tr.json — bütün metinler
│   ├── settings.py                     sabitler ve yol çözümü
│   └── …                               ip_assign, config_sync, probe, jobs
├── field_scripts/                      çalışma anında yüklenen motorlar
│   ├── switch_api.py                   Switch Yönetim Paneli'nden kopya
│   ├── device_verify.py                saha doğrulama betiği
│   └── intercom_ip_assign.py           IP atama betiği
├── CommissioningPanel.spec             PyInstaller yapılandırması
├── DeviceMap.json                      topoloji envanteri (pakete girer)
├── Field_Device_Verification.xlsx      Excel şablonu (pakete girer)
├── static/                             kaynak arayüz + üretilmiş desktop.html
├── tools/build_desktop_bundle.py       Deno 2.9.4 paketleme/doğrulama aracı
├── tests/                              birim testler (pakete GİRMEZ)
├── packaging/
│   ├── appimage.sh                     Linux AppImage
│   └── windows/                        Inno Setup betiği
└── docs/                               belgeler ve bağımlılık listeleri
    ├── MIMARI.md                       mimari ve ekranlar
    ├── BUILD_RELEASE.md                bu dosya
    ├── RELEASE_NOTES.md                GitHub sürümü açıklaması
    ├── CIHAZ_ENDPOINTLERI.md           cihaz uçları
    ├── CIHAZ_VERI_ALANLARI.md          okunan veri alanları
    └── requirements*.txt               işletim sistemi ve derleme bağımlılıkları
```

### Pakete giren veri dosyaları

Panel switch erişimini ve saha betiklerini yeniden yazmaz; çalışma anında
dosya yolundan içe aktarır (`panel/script_loader.py`). Kaynaktan çalışırken bunlar
depodaki yerlerinde durur, **paketlenirken paketin köküne kopyalanır**:

| Dosya | Nereden | Ne için |
|---|---|---|
| `switch_api.py` | `field_scripts/` | switch okuma, PoE |
| `device_verify.py` | `field_scripts/` | alan ayıklama, Excel şeması |
| `intercom_ip_assign.py` | `field_scripts/` | IP atama koşusu |
| `DeviceMap.json` | uygulama kökü | cihaz envanteri |
| `Field_Device_Verification.xlsx` | uygulama kökü | kontrol listesi şablonu |

Yol çözümü `panel/settings.py` → `data_file()` içindedir: paketlenmiş durumda
paketin kökü, kaynaktan çalışırken depodaki göreli yol. Beşinden biri
eksikse `CommissioningPanel.spec` derlemeyi durdurur; `--self-test` de bu
dosyaları tek tek arar. Böylece eksik paket üretilmesi ve sahada
"DeviceMap bulunamadı" hatasıyla karşılaşılması önlenir.

---

## 1. Geliştirme çalıştırması

```bash
pip install -r docs/requirements-macos.txt   # ya da -windows / -linux
python3 app.py
```

| Bayrak | İşlevi |
|---|---|
| `--tarayici` | HTTP tabanlı geliştirme/tanı kipini sistem tarayıcısında açar |
| `--tarayici --port 8790` | Tanı servisinin portunu sabitler |
| `--admin-parolasi …` | Admin ekranı için parola sorar (verilmezse sorulmaz) |
| `--self-test` | Pencere açmadan paketi doğrular, çıkış kodu döner |
| `--version` | Yalnız sürümü yazar (etiket denetimi bunu kullanır) |

---

## 2. Doğrulama

```bash
python3 app.py --self-test                    # varlıklar + soketsiz köprü
python3 -m unittest discover -s tests -t .    # birim testler
python3 tools/build_desktop_bundle.py --check      # tek HTML güncel mi
```

**Self-test kapsamı:** Veri dosyalarını ve kardeş betikleri arar, DeviceMap'i
okur, tek parça masaüstü HTML'ini yükler ve `/api/surum`, `/api/proje`,
`/api/durum` işlemlerini doğrudan pywebview köprüsü sözleşmesiyle sınar.
Pencere veya dinleyen soket açmaz; **cihaza bağlanmaz.**

Birim testler sahte cihaz sunucuları kullanır (`tests/sahte.py`): KYLAND
switch, ISAPI kamera ve `/api/v1` anons cihazı taklit edilir; gerçek ağa
çıkılmaz. `tests/test_arayuz.py` içindeki JavaScript denetimi, `deno`
kuruluysa çalışır; değilse yalnız ilgili test atlanır. Yayın/CI akışındaki
artefakt güncellik kontrolü için tam Deno 2.9.4 zorunludur. Kurulu sürümü
`deno --version` ile doğrulayın; farklı bir Deno 2 sürümü de bilinçli olarak
reddedilir.

Testler kalıcı dosyalara dokunmaz: konfigürasyon varsayılanları geçici bir
dizine yazılır (`PANEL_VERI_DIZINI`).

---

## 3. Yerel derleme

Önce kullanılan işletim sisteminin bağımlılıklarını kurun:

| İşletim sistemi | Komut |
|---|---|
| macOS | `python3 -m pip install -r docs/requirements-macos.txt` |
| Linux | `python3 -m pip install -r docs/requirements-linux.txt` |
| Windows | `python -m pip install -r docs/requirements-windows.txt` |

Ardından derleme bağımlılıklarını kurup temiz derlemeyi başlatın. macOS ve
Linux için:

```bash
python3 -m pip install -r docs/requirements-build.txt
python3 tools/build_desktop_bundle.py --check
rm -rf build dist
python3 -m PyInstaller --noconfirm --clean CommissioningPanel.spec
```

Windows PowerShell için:

```powershell
python -m pip install -r docs/requirements-build.txt
python tools/build_desktop_bundle.py --check
python -m PyInstaller --noconfirm --clean CommissioningPanel.spec
```

Derleme **Python 3.12** ile yapılır. Bilerek başka bir Python sürümü
kullanılacaksa `DAP_PYTHON_SERBEST=1`, tek dosyalı taşınabilir paket
üretilecekse `DAP_ONEFILE=1` ayarlanır.

Paketlenmiş uygulamayı macOS ve Linux'ta doğrulama:

```bash
# macOS
"dist/Commissioning and Maintenance Panel.app/Contents/MacOS/CommissioningPanel" --self-test
# Linux
./dist/CommissioningPanel/CommissioningPanel --self-test
```

Windows uygulaması GUI alt sistemiyle derlendiği için PowerShell doğrudan
çalıştırıldığında sürecin bitmesini beklemeyebilir. Gerçek çıkış kodunu almak
için `Start-Process -Wait -PassThru` kullanın:

```powershell
$exe = (Resolve-Path '.\dist\CommissioningPanel\CommissioningPanel.exe').Path
$islem = Start-Process -FilePath $exe -ArgumentList '--self-test' `
  -Wait -PassThru -NoNewWindow
if ($islem.ExitCode -ne 0) {
  throw "self-test başarısız: çıkış kodu $($islem.ExitCode)"
}
```

### Windows kurulum paketi

```powershell
$surum = "0.9.7"  # panel/settings.py içindeki APP_VERSION ile aynı olmalı
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
  "/DMyAppVersion=$surum" `
  "/DSourceDir=..\..\dist\CommissioningPanel" `
  "/DOutputDir=..\..\release" `
  "packaging\windows\CommissioningPanel.iss"
```

Kurulum paketinin AppId GUID'i Switch Yönetim Paneli'nden **ayrıdır**. Bu
sayede iki uygulama aynı makinede yan yana kurulabilir; biri diğerinin
üzerine yazılmaz.

### Linux AppImage

```bash
SURUM="$(python3 app.py --version)"
./packaging/appimage.sh dist/CommissioningPanel \
  "release/CommissioningPanel-${SURUM}-linux-x86_64.AppImage" "$SURUM"
```

---

## 4. GitHub Actions

### `ci.yml` — yayın öncesi doğrulama

`main` dalındaki bu iş akışının gerçek tetikleyicileri şunlardır:

- **`dap-v*` etiketi gönderimi:** Etikete alınan kaynak kodu doğrular.
- **Elle çalıştırma (`workflow_dispatch`):** Seçilen `main` sürümünü doğrular.

Dal gönderimleri ve çekme istekleri (`pull_request`) bu iş akışını otomatik
başlatmaz. Maliyet nedeniyle **her değişiklik kaydında çalıştırılmaz**. `v*`
ve `syp-v*` etiketleri de `main` dalındaki `ci.yml` dosyasının kapsamında
değildir.

`self-test` işi yalnız Devreye Alma Paneli'ni Windows, Ubuntu ve macOS
üzerinde doğrular. Her hedefte Python 3.12 ve işletim sistemine özgü
bağımlılıklar kurulur; `compileall`, birim testler, kaynak koddan
`--self-test` ve `--version` çalıştırılır.

Etiket gönderimlerinde `version-check` işi, `dap-v*` etiketindeki değer ile
`panel/settings.py` içindeki `APP_VERSION` değerini karşılaştırır. `repo-checks`
işi ise izlenen hassas dosya adlarını ve temiz depo durumunu denetler.

### `build-app.yml` — ortak derleme akışı

Bu iş akışı kendi başına çalışmaz; `workflow_call` aracılığıyla çağrılır.
Çağıran iş akışı, hangi uygulamanın derleneceğini girdilerle belirtir.

| Hedef | GitHub çalıştırıcısı | Üretilen çıktı |
|---|---|---|
| windows-x64 | `windows-2025` | Klasör tabanlı ZIP + Inno Setup kurulum paketi |
| linux-x86_64 | `ubuntu-22.04` | AppImage içeren ZIP |
| macos-arm64 | `macos-15` | `.app` içeren `ditto` ZIP'i |
| macos-x64 | `macos-15-intel` | `.app` içeren `ditto` ZIP'i |

Her derleme işi sırasıyla depoyu alır, Python 3.12 ile bağımlılıkları kurar,
sürümü belirler, varsa birim testleri ve kaynak `--self-test` denetimini
çalıştırır. Ardından temiz bir PyInstaller derlemesi yapar, paketlenmiş
uygulamada `--self-test` çalıştırır, çıktıyı paketleyip doğrular ve GitHub
Actions çıktı arşivi olarak yükler.

Linux paketi Ubuntu 22.04 üzerinde derlenir. Daha yeni bir sistemde derlenen
ikili eski bir `glibc` sürümünde çalışmayabileceğinden, bu seçim desteklenen
dağıtım aralığını genişletir.

### `build-commissioning-panel.yml` — bu uygulamanın paketleri

- **Elle çalıştırma (`workflow_dispatch`):** Dört hedef için paket ve GitHub
  Actions çıktı arşivi üretir; GitHub sürümü yayımlamaz.
- **`dap-v*` etiketi gönderimi:** Paketleri üretir ve bütün derleme hedefleri
  başarıyla tamamlanırsa GitHub sürümünü yayımlar.

Switch Yönetim Paneli, `syp` dalındaki kendi `build-switch.yml` dosyasıyla
ayrı derlenir. İki uygulamanın akışları birbirini beklemez ve birbirinin
GitHub sürümüne dokunmaz.

### Sürüm etiketiyle yayınlama

```bash
# Önce panel/settings.py içindeki APP_VERSION değerini yeni sürüme yükseltin.
SURUM="$(python3 app.py --version)"
git tag "dap-v${SURUM}"
git push origin "dap-v${SURUM}"
```

| Etiket | Uygulama |
|---|---|
| `dap-v…` | Devreye Alma Paneli |
| `syp-v…` | Switch Yönetim Paneli |
| `v…` | Switch Yönetim Paneli (depoda tek uygulama varken kullanılan eski biçim) |

Etiketteki sürüm ile `panel/settings.py` içindeki `APP_VERSION` **aynı olmalıdır**;
değilse derleme açık bir hatayla durur. Bütün derleme hedefleri başarıyla
tamamlanmadan GitHub sürümü oluşturulmaz. Ön sürüm ekleri (`-dev`, `-alpha`,
`-beta`, `-rc`) sürümü GitHub'da **ön sürüm** (pre-release) olarak işaretler.

Daha önce yayımlanmış bir etiket taşınmamalı veya yeni değişiklikler eski
sürüm başlığına eklenmemelidir. Yayımlanmamış değişiklikler önce
`docs/DEGISIKLIKLER.md` içinde `Yayımlanmamış` ibaresi bulunan bölümde
tutulmalı; yayın
hazırlığında yeni `APP_VERSION`, değişiklik günlüğü başlığı ve `dap-v*`
etiketi birlikte oluşturulmalıdır.

Yayın işi, GitHub Actions çıktı arşivlerini indirir; dosyaların var ve boş
olmadığını doğrular, `SHA256SUMS.txt` üretir ve `gh` komut satırı aracıyla
GitHub sürümünü oluşturur. Aynı etiketin akışı yeniden çalıştırılırsa aynı
adlı varlıklar `--clobber` ile güncellenir ve artık beklenmeyen varlıklar
silinir.

GitHub sürümü açıklaması, **etiketin işaret ettiği kaynak kodu kaydındaki**
`docs/RELEASE_NOTES.md` dosyasından alınır. Bu dosyayı daha sonra `main`
dalında değiştirmek, yayımlanmış bir sürümün açıklamasını geriye dönük
olarak güncellemez.

### İki uygulama, tek Releases sayfası

GitHub'da Releases sayfası **depo başınadır**; dal başına ayrı bir sayfa
yoktur. İki uygulamanın sürümleri aynı listede görünür ve şöyle ayrılır:

| Ne | Nasıl |
|---|---|
| Başlık | `Devreye Alma Paneli v0.9.6` — ham etiket değil, uygulama adı + sürüm |
| Etiket | `dap-v*` / `syp-v*` · `v*` |
| Dosya adları | `CommissioningPanel-…` / `SwitchYonetimPaneli-…` |
| Sürüm açıklaması | İlgili uygulamanın `docs/RELEASE_NOTES.md` dosyası |
| README bağlantısı | `../../releases?q=dap-v`; yalnız Devreye Alma Paneli sürümlerini gösterir |

İki ayrıntı bilerek böyle:

- **`--latest=false`.** "Latest" rozeti depo başına tektir. Bu seçenek
  kullanılmasaydı son yayımlanan uygulama diğerinin rozetini alabilirdi; bu
  yüzden iki uygulama da bilerek bu rozetin dışında tutulur.
- **`--generate-notes` kullanılmıyor.** Sürüm açıklaması yalnızca
  `docs/RELEASE_NOTES.md` içeriğidir. GitHub'ın ürettiği değişiklik listesi,
  birbirine karışan iki etiket dizisi nedeniyle diğer uygulamanın
  değişikliklerini de içerebilirdi. Ayrıntılı sürüm geçmişi
  `docs/DEGISIKLIKLER.md` dosyasında tutulur.

### İzinler

İş akışları en düşük izinle çalışır: derleme işlerinde `contents: read`,
yalnızca yayın işinde `contents: write` kullanılır. `pull_request_target`
kullanılmaz ve gizli değer istenmez.

---

## 5. Üretilen dosyalar

```
CommissioningPanel-<sürüm>-windows-x64-Setup.exe
CommissioningPanel-<sürüm>-windows-x64.zip
CommissioningPanel-<sürüm>-linux-x86_64.zip      (içinde .AppImage)
CommissioningPanel-<sürüm>-macos-arm64.zip
CommissioningPanel-<sürüm>-macos-x64.zip
SHA256SUMS.txt
```

`SHA256SUMS.txt`, beş paketin tamamının özetini içerir. Bütün paketler ve
özet dosyası aynı klasördeyse toplu denetim yapılabilir:

```bash
# Linux
sha256sum -c SHA256SUMS.txt

# macOS
shasum -a 256 -c SHA256SUMS.txt
```

Yalnızca bir paket indirildiyse tüm listeyi `-c` ile denetlemek, indirilmeyen
dosyalar için hata üretir. Bu durumda ilgili dosyanın özetini hesaplayıp
`SHA256SUMS.txt` içindeki aynı satırla karşılaştırın:

```powershell
# Windows PowerShell
Get-FileHash -Algorithm SHA256 '.\CommissioningPanel-<sürüm>-windows-x64-Setup.exe'
```

```bash
# macOS
shasum -a 256 'CommissioningPanel-<sürüm>-macos-arm64.zip'

# Linux
sha256sum 'CommissioningPanel-<sürüm>-linux-x86_64.zip'
```

---

## 6. Kullanıcı notları

- **Windows:** WebView2 Runtime gerekir. Önerilen kurulum paketi, bu bileşen
  bulunmuyorsa yükler; taşınabilir ZIP paketinde bileşeni ayrıca kurmak
  gerekebilir. SmartScreen uyarısı, paketin kod imzası taşımamasından
  kaynaklanır.
- **macOS:** Gatekeeper "geliştirici doğrulanamadı" uyarısı verebilir.
  Finder'da uygulamaya sağ tıklayıp *Aç* seçeneğini kullanın ya da Sistem
  Ayarları → Gizlilik ve Güvenlik bölümünden *Yine de aç* seçeneğini seçin.
- **Linux:** ZIP arşivi normalde AppImage dosyasının çalıştırma iznini korur.
  Arşiv yöneticisi bu izni korumadıysa `chmod +x` ile yeniden verin. Yazılım
  dosyası seçimi için sistemde `zenity` veya `kdialog` bulunmalıdır.
- Kullanıcının kendi verisi (konfigürasyon varsayılanları) kurulum dizinine
  değil işletim sisteminin uygulama verisi dizinine yazılır; kaldırma bunu
  silmez. Arayüzde girilen cihaz erişim kimlikleri (kullanıcı adı ve parola)
  ile SIP parolası kalıcı depoya yazılmaz; yalnızca geçerli oturum süresince
  bellekte tutulur.

---

## 7. Kapsam dışı / bilinen sınırlar

- Kod imzalama, Apple noter onayı (notarization) ve DMG/PKG/DEB/RPM üretimi.
- `macos-x64` çalıştırıcısı Intel Mac'ler içindir; Apple Silicon sistemler
  `macos-arm64` paketini kullanır.
- Simge dosyaları (`icons/app.icns`, `icons/app.ico`, `icons/app.png`) henüz
  yoktur; eklendiklerinde `.spec` dosyası ve paketleme betikleri bunları
  kendiliğinden kullanır.
