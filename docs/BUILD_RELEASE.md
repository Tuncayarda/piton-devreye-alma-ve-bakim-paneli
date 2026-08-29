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
│   ├── adb/                            Android ekranlar + gömülü adb çözümü
│   ├── switch/                         KYLAND switch istemcisi (tek istemci)
│   ├── i18n.py                         mesaj kataloğu (t / lazy)
│   ├── messages/                       en.json · tr.json — bütün metinler
│   ├── settings.py                     sabitler ve yol çözümü
│   └── …                               ip_assign, config_sync, probe, jobs
├── field_scripts/                      çalışma anında yüklenen motorlar
│   ├── device_verify.py                saha doğrulama betiği
│   └── intercom_ip_assign.py           IP atama betiği
├── platform-tools/                     adb (depoda YOK — bkz. ADB araçları)
├── dabp.spec                           PyInstaller yapılandırması
├── devicemaps/                         proje başına klasör (pakete girer)
│   ├── _base/                          çalışma kitaplarının üretildiği şablon
│   └── <proje>/                        DeviceMap_<Proje>.json +
│                                       Field_Device_Verification_<Proje>.xlsx
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

Panel iki saha betiğini yeniden yazmaz; çalışma anında dosya yolundan içe
aktarır (`panel/script_loader.py`). Kaynaktan çalışırken bunlar depodaki
yerlerinde durur, **paketlenirken paketin köküne kopyalanır**:

| Dosya | Nereden | Ne için |
|---|---|---|
| `device_verify.py` | `field_scripts/` | alan ayıklama, Excel şeması |
| `intercom_ip_assign.py` | `field_scripts/` | IP atama koşusu |
| `DeviceMap_<Proje>.json` | `devicemaps/<proje>/` | cihaz envanteri |
| `Field_Device_Verification_<Proje>.xlsx` | `devicemaps/<proje>/` | projenin kontrol listesi |

### Dosya adlandırma standardı

Bir projenin bütün dosya adları **anahtarından** türetilir; tablo bunu elle
yazmaz, `panel/editions/catalogue.py` içindeki `project()` üretir:

| | |
|---|---|
| klasör | `devicemaps/<anahtar>/` |
| envanter | `DeviceMap_<Anahtar>.json` |
| çalışma kitabı | `Field_Device_Verification_<Anahtar>.xlsx` |

`<Anahtar>` anahtarın ilk harfi büyütülmüş hâlidir (`gdm` → `Gdm`). Baş harf
süs değil: `Inventory.project` proje adını dosyanın kökünden okur, üst çubukta
görünen ad odur ve `panel/video_config/nvr.py` ona bakarak dallanır.
`tests/test_editions.py` standardı yerinde tutar.

`devicemaps/_base/Field_Device_Verification.xlsx` bu standardın dışındadır:
bir projeye ait değil, çalışma kitaplarının **üretildiği** şablondur
(`tools/make_checklist_template.py`). Pakete o değil, projenin kendi kitabı
girer.

> Switch erişimi üçüncü bir betikti (`switch_api.py`); emekliye ayrıldı.
> Yerini paketin içindeki `panel/switch/` aldı — Switch ekranının **yazması**
> gerekiyordu ve ödünç alınan salt-okunur bir betik bunu ikinci bir istemciye
> dönüşmeden büyütemezdi.

Yol çözümü `panel/settings.py` → `data_file()` içindedir: paketlenmiş durumda
paketin kökü, kaynaktan çalışırken depodaki göreli yol. Dördünden biri
eksikse `dabp.spec` derlemeyi durdurur; `--self-test` de bu
dosyaları tek tek arar. Böylece eksik paket üretilmesi ve sahada
"DeviceMap bulunamadı" hatasıyla karşılaşılması önlenir.

### ADB araçları (`platform-tools/`)

**Sürüm derlemesinde bu adım atlanırsa paket sessizce eksik çıkar.**

Android ekranlara `adb` ile erişilir ve panelin kurulduğu makinenin Android
Studio taşımak için bir sebebi yoktur. Bu yüzden `adb` **paketin içine
konur**: `panel/adb/binary.py` önce paketteki kopyayı arar, sonra `PATH`'e
düşer. Kopya yoksa sağlıklı bir ekran sahada "adb komutu bulunamadı" der.

Depo bu ikilileri taşımaz (Google'ın kendi lisansıyla gelen üçüncü taraf
indirmesidir). Derlemeden önce depo köküne açın:

```bash
# https://developer.android.com/tools/releases/platform-tools
# İşletim sistemine göre doğru arşivi indirin ve depo köküne açın:
unzip platform-tools-latest-<os>.zip -d .
ls platform-tools/adb        # macOS/Linux
ls platform-tools/adb.exe    # Windows
```

**`dabp.spec` eksik adb ile derlemeyi durdurur.** Uyarı basıp devam etmez;
servis anahtarındaki kalıbın aynısı. Sebebi: adb'siz bir paket derlenir,
açılır, çalışır — ve sahada sağlam bir ekran "okunamıyor" der. Bu, arızanın
sahadan derlemeye taşınmasıdır.

Klasör doğru ikiliyi taşımalı: Windows'ta `adb.exe`, diğerlerinde `adb`.
macOS arşivini Windows koşucusunda açmak, doğru görünen ama Windows'un
çalıştıramayacağı bir klasör bırakır — spec bunu da reddeder.

```
[spec] adb tools: /…/platform-tools                     ← doğru
[spec] …/platform-tools holds no adb.exe, so this …     ← derleme durur
```

Bilerek adb'siz bir geliştirici derlemesi için:

```bash
DAP_ALLOW_NO_ADB=1 DAP_EDITION=… python3 -m PyInstaller --clean dabp.spec
```

**İkinci ağ:** `--self-test` paketlenmiş uygulamada adb'yi tekrar arar ve
bulamazsa `RESULT: failed` verip 1 ile çıkar. CI bunu her platformda
çalıştırır, yani spec ile artefakt arasında kaybolan bir adb de yakalanır.

```
[OK  ] ADB executable (in the package) — /…/_internal/platform-tools/adb
[FAIL] ADB executable (in the package) — not bundled — this package cannot
       reach an Android display
```

**CI bunu kendisi indirir.** `build-app.yml` içindeki "Fetch the ADB tools"
adımı koşucunun işletim sistemine göre doğru arşivi çeker; elle bir şey
yapmak gerekmez. Yukarıdaki indirme yalnızca **yerel** derleme içindir.

Sahadaki bir makinede başka bir `adb` kullanılması gerekirse
`DABP_ADB_BINARY` ortam değişkeni her şeyin önüne geçer.

---

## 1. Geliştirme çalıştırması

```bash
pip install -r docs/requirements-macos.txt   # ya da -windows / -linux
python3 app.py
```

| Bayrak | İşlevi |
|---|---|
| `--edition <ad>` | Bu çalıştırmanın hangi paket olduğu — kaynaktan **zorunlu** |
| `--browser` | HTTP tabanlı geliştirme/tanı kipini sistem tarayıcısında açar |
| `--browser --port 8790` | Tanı servisinin portunu sabitler |
| `--self-test` | Pencere açmadan paketi doğrular, çıkış kodu döner |
| `--version` | Yalnız sürümü yazar (etiket denetimi bunu kullanır) |

Kaynaktan çıplak `python3 app.py` **çalışmaz**: hangi müşterinin paketi
olduğu söylenmeden açılmaz ve geçerli adları yazıp 2 ile çıkar. Paketlenmiş
bir build'de ise durum tersine döner — sürüm binary'nin içine damgalanmıştır
ve `--edition` verilirse *reddedilir*. Müşteri kendi paketini başkasının
paketi olarak başlatamasın diye böyle; admin moda yalnızca servis
anahtarıyla geçilir.

```bash
python3 app.py --edition gdm                # bir müşteri paketi
python3 app.py --edition gdm --self-test
DAP_EDITION=vip-yatakli python3 -m unittest discover -s tests -t .
```

Paketler ve içerdikleri projeler `panel/editions/catalogue.py` dosyasındaki
tabloda durur. Listeyi görmek için:

```bash
python3 tools/edition_info.py --list
```

`--admin-parolasi` kaldırıldı. Admin modun tek kapısı USB servis anahtarı
(`panel/adminkey/`); anahtarı yalnızca `admin` paketi yazabilir.

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

Derleme **hangi paketi ürettiğini bilmek zorundadır**: `DAP_EDITION` ile
söylenir, ve verilmezse spec geçerli adları yazıp durur.

```bash
python3 -m pip install -r docs/requirements-build.txt
python3 tools/build_desktop_bundle.py --check
rm -rf build dist
DAP_EDITION=gdm DAP_ADMIN_KEY_SECRET="…" \
  python3 -m PyInstaller --noconfirm --clean dabp.spec
```

Windows PowerShell için:

```powershell
python -m pip install -r docs/requirements-build.txt
python tools/build_desktop_bundle.py --check
$env:DAP_EDITION = "gdm"
$env:DAP_ADMIN_KEY_SECRET = "…"
python -m PyInstaller --noconfirm --clean dabp.spec
```

Üretilen her dosya pakete göre adlandırılır: `dabp-gdm.exe`,
`dist/dabp-gdm/`, `dabp-gaziray.app`. Böylece iki paket aynı makineye yan
yana kurulabilir.

| Ortam değişkeni | İşlevi |
|---|---|
| `DAP_EDITION` | **Zorunlu.** Üretilecek paket (`tools/edition_info.py --list`) |
| `DAP_ADMIN_KEY_SECRET` | Servis anahtarının build sırrı — aşağıya bakın |
| `DAP_ALLOW_NO_ADMIN_KEY=1` | Sır olmadan derlemeye izin verir; çıkan paketin admin modu hiç açılmaz |
| `DAP_ALLOW_ANY_PYTHON=1` | Python 3.12 dışında bir sürümle derlemeye izin verir |
| `DAP_ONEFILE=1` | Tek dosyalı taşınabilir paket |

**Servis anahtarının build sırrı.** `DAP_ADMIN_KEY_SECRET`, USB anahtarını
üreten ve tanıyan tek değerdir. Spec bundan tek yönlü bir özet hesaplar:

- **Her pakete yalnızca özet** gömülür. Paket bir anahtarı tanıyabilir, ama
  ondan yeni anahtar üretemez — özetten geri dönüş yoktur.
- **Sırrın kendisi hiçbir pakete girmez.** Sır, build'i kesen kişide kalır.
  CI bunu çıkan paketten geri okuyarak doğrular.

**Sır aynı zamanda önyükleme anahtarıdır.** İlk servis anahtarı, servis
anahtarı takarak yapılamaz — o yüzden sır, henüz var olmayan USB'nin yerine
geçer: **sırrı elinde tutan bir kaynak çalıştırması** hiçbir şey takılmadan
admin açılır ve ilk belleği yazabilir:

```bash
DAP_ADMIN_KEY_SECRET=<sır> python3 app.py --edition gdm
```

Değişken yükseltme (yönetici şifresi) penceresini **atlatabiliyor**: değer
yalnızca senin okuyabildiğin bir dosyaya yazılıyor, komut satırında yalnız
yolu geçiyor, yükselen süreç okuyup dosyayı siliyor (`panel/adminkey/
handoff.py`). Windows'ta `runas` ortam almadığı için orada hâlâ yönetici
PowerShell'inden başlatmak gerekiyor; panel bunu yazıyor.

**Ya da bir dosya — lisans dosyası gibi.** Ortam değişkeni sürece
*başlarken* kopyalanır; panel açıkken `export` etmek çalışan süreci
etkilemez, yani her seferinde yeniden başlatmak gerekirdi. Sır bunun yerine
kaynak ağacının kökündeki `.adminkey-secret` dosyasına yazılabilir:

```bash
printf '%s\n' "$DAP_ADMIN_KEY_SECRET" > .adminkey-secret   # admin açılır
rm .adminkey-secret                                        # admin kapanır
```

Dosya **her soruluşta** okunuyor: bıraktığın anda üst çubuktaki "admin moda
geç" düğmesi çıkıyor, sildiğin anda (bellek çıkarılmış gibi, en geç ~2 sn
içinde) mod düşüyor — cihazlara yazan bir iş sürüyorsa iş bitene kadar
bekliyor. Yükseltme penceresini de kendiliğinden aşıyor: yükselen süreç aynı
dizinde başlıyor ve aynı dosyayı okuyor. Öncelik sırası: damga → ortam
değişkeni → dosya. `.gitignore`'da; **paketlenmiş build hiç okumuyor.**

Admin moda üst çubuktaki düğmeyle elle girilip çıkılabilir. Düğme yalnızca
bellek takılıyken ya da bu çalıştırma sırrı taşırken (ortamda veya dosyada)
görünür.

Bu yalnızca kaynaktan geçerlidir; paketlenmiş bir build ortam değişkenine
bakmaz, damgasına bakar (`panel/adminkey/secret.py`). Yani sahadaki hiçbir
paket kendiliğinden admin açılmaz — tek yol USB'dir. Anahtar malzemesi hiç
yoksa admin moda **hiçbir yoldan** girilemez.

### Kaynaktan çalışırken anahtarın tanınması

Paketlenmiş bir build hangi anahtarı kabul edeceğini **damgasından** bilir.
Kaynak ağacında damga yoktur, yani kaynaktan çalışan bir panel hiçbir
anahtarı tanımaz — bellek takılır ve sanki hiç takılmamış gibi olur.

Kaynaktan yazılan bir anahtar **kendini kaydeder**: yazıldığı anda özeti
kaynak ağacının kökündeki `.adminkey-dev.json` dosyasına düşer ve bu ağaçtan
kaynaktan çalışan **her sürüm** o belleği tanır. Ortam değişkeni gerekmez.

Dosya neden ayar dizininde değil de ağacın kökünde: ayar dizini `HOME`'a
bağlı, panel ise kendini **başka bir kullanıcı olarak** yeniden başlatıyor.
`pkexec` sürece root'un `HOME`'unu, Windows'ta `runas` bambaşka bir profili
veriyor; `--remember` ise senin ev dizinine yazıyor. İkisinin buluşup
buluşmaması yükseltme aracının keyfine kalıyor (macOS'ta osascript `HOME`'u
koruyor, polkit korumuyor) — bir işletim sisteminde tanınan anahtarın
diğerinde sessizce yok sayılması buradan çıkıyordu.

Başka yerde ya da bir meslektaşınca yazılmış bir belleği kaydettirmek
için:

```bash
python3 tools/key_digest.py /Volumes/DABP-KEY --remember
```

Bu dosya hiçbir şey yetkilendirmez — bir özet anahtar üretemez — ve
**paketlenmiş build tarafından hiç okunmaz**: bir paketin neyi kabul ettiği
derleme anında belirlenir, diskteki hiçbir dosya buna ekleme yapamaz.

### Uygulama ikonu

Üç dosya `icons/` altında **depoda duruyor**; derleme makinesi bunları
üretmiyor, sadece kullanıyor:

| Dosya | Nerede | Kim alıyor |
|---|---|---|
| `app.ico` | `dabp.spec` → `EXE(icon=)`, `dabp.iss` → `SetupIconFile` | Windows |
| `app.icns` | `dabp.spec` → `BUNDLE(icon=)` | macOS |
| `app.png` | `packaging/appimage.sh` | Linux (AppImage) |

Logo değişirse yeniden üretmek için (macOS + `brew install librsvg`):

```bash
python3 tools/make_icons.py
```

Betik, logodaki **işareti** (favicon'daki "P" ve üstündeki iki çizgi) kesip
panelin kendi arka plan rengiyle kare bir ikon kuruyor. macOS ve Linux için
köşeleri yuvarlak, Windows için tam kare — Windows ikonu olduğu gibi çizdiği
için yuvarlak köşe orada boşluklu küçük bir kutu gibi duruyor. `.ico` elle
yazılıyor: macOS'ta **çok boyutlu** ico üreten bir araç yok ve tek bir 256
piksellik görüntünün 16'ya küçültülmüşü okunmuyor.

### macOS: çıkarılabilir disk izni

macOS çıkarılabilir diskleri ayrı bir gizlilik iznine bağlıyor ve bu izin
**bir kişiye ve onun başlattığı uygulamaya** ait. Panel ise kendini
yükseltilmiş olarak yeniden başlatıyor; o süreç ne o kişi ne o uygulama.
Sonuç: `/Volumes` altında bellek görünüyor, üzerindeki her dosya `EPERM`
dönüyor ve sistem soru bile sormuyor — şifre kutusunun o tarafında
sorulacak kimse yok.

Panel bunu artık **kendi çözüyor**: okumayı, dosya seçicide zaten
kullanılan yolla (`launchctl asuser` + `sudo -H -u`) klavyedeki kullanıcının
oturumuna devrediyor — izin zaten onda. Kullanıcının hiçbir ayara girmesi
gerekmiyor. Bkz. `panel/adminkey/handback.py`.

**Sıralama kritik ve tesadüf değil.** macOS 26'da ölçüldü: ilk soran taraf
tüm süreç ağacı adına karar veriyor. Önce devretme yapılırsa okumalar
çalışıyor; önce panelin kendisi reddedilirse bu ret başlattığı her sürece de
geçiyor ve bir dakika önce çalışan `ls` "Operation not permitted" diyor.
Bu yüzden `keyfile.read` devretme mümkünse **belleğe hiç dokunmadan**
devrediyor.

Devretmenin de mümkün olmadığı durumda (grafik oturum yok, başka işletim
sistemi) panel sessiz kalmıyor, sebebini yazıyor (`adminkey.denied`). O
zaman izin elle veriliyor: **Sistem Ayarları → Gizlilik ve Güvenlik →
Dosyalar ve Klasörler → Çıkarılabilir Birimler** (ya da **Tam Disk
Erişimi**); paketlenmiş uygulamada listeye `.app`, kaynaktan çalışırken
Python yorumlayıcısı eklenir. Paketin sorduğu cümle
`NSRemovableVolumesUsageDescription` içinde (bkz. `dabp.spec`).

**Bilinen sınır:** anahtar **yazmak** aynı izne tabi ve o yol devredilmiyor.
Bellek yazarken izinli bir terminalden
(`DAP_ADMIN_KEY_SECRET=<sır> sudo -E python3 app.py --edition gdm`)
çalışmak gerekiyor; hata görünür şekilde bildiriliyor.

Bu yol yalnızca **kaynaktan** çalıştırmaya aittir. Paketlenmiş bir build
ortamdaki sırra da, diskteki bu dosyaya da bakmaz; neyi kabul ettiği derleme
anında belirlenir ve tek kapısı USB'dir.

Sır **hiç kimse tarafından yazılmaz** — CI secret'ında ve parola yöneticinde
durur — bu yüzden akılda kalıcı olması gereksiz ve zararlıdır. Müşteri
paketinde özetin kendisi bulunduğu için, sırrı tahmin etmeye çalışan biri her
denemesinde 600.000 PBKDF2 turu öder; bu yavaşlatma kısa ya da anlamlı bir
değeri kurtarmaz. Rastgele üretin:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

43 karakter, 256 bit, yalnızca `A-Za-z0-9_-` — kabuk, YAML ve PowerShell'de
tırnak derdi çıkarmaz. Spec 24 karakterden kısa bir sırla derlemeyi reddeder.

### Sır kaybolursa

Sır bir CI secret'ından geri okunamaz ve onu üretecek başka bir şey yoktur.
Ama **sahadaki hiçbir şey bozulmaz**: doğrulama sırrı kullanmaz, paketteki
özetle USB'deki değeri karşılaştırır. Eldeki bütün anahtarlar, eldeki bütün
paketlerde çalışmaya devam eder.

Kaybolan tek yetenek, sır olmadan **yeni sürüm derlemek**: yeni bir sırla
derlenen paket, eski anahtarları tanımaz.

Bu yüzden özet, elinde kalan **herhangi bir anahtardan** geri alınabilir —
paketin ihtiyacı olan şey sırrın kendisi değil, özetidir:

```bash
python3 tools/key_digest.py /Volumes/DABP-KEY
```

Çıkan değeri `DAP_ADMIN_KEY_DIGESTS` ile derlemeye ver; sır olmadan da
çalışır:

```bash
DAP_EDITION=gdm DAP_ADMIN_KEY_DIGESTS=<yukarıdaki değer> python3 -m PyInstaller --noconfirm --clean dabp.spec
```

Böyle derlenen bir paket sahadaki bütün anahtarları tanır. Kurtarılamayan
tek şey **yeni anahtar üretmek** — o sırrın kendisini ister. Elindeki bir
belleği kopyalamak yine çalışır: bütün anahtarlar birbirinin aynısıdır.

Toparlanmak istediğinde: yeni bir sır üret, paketleri **hem yeni sır hem
eski özetle** derle (aşağıya bakın), sahayı güncelle, sonra eski özeti
listeden düşür.

### Sırrı değiştirmek (rotasyon)

`DAP_ADMIN_KEY_SECRET` ve `DAP_ADMIN_KEY_DIGESTS` birlikte verilebilir. Yeni
sırla üretilen anahtarlar da, eski özete karşılık gelen eldeki anahtarlar da
çalışır:

```bash
DAP_EDITION=gdm DAP_ADMIN_KEY_SECRET=<yeni> DAP_ADMIN_KEY_DIGESTS=<eski özet> python3 -m PyInstaller --noconfirm --clean dabp.spec
```

Sahadaki son bilgisayar güncellendikten sonra `DAP_ADMIN_KEY_DIGESTS`'i
kaldırın; o andan itibaren eski anahtarlar ölür. Derleme kaydı kaç özetin
kabul edildiğini yazar (`digest only (+1 accepted)`), değerleri asla yazmaz.

Aynı sır bütün paketlerde ve bütün sürümlerde kullanılır: bir müşterinin
anahtarı diğerinin paketini de açar, ki maksat zaten budur. Sırrı
değiştirmek eldeki bütün anahtarları geçersiz kılar ve yeni build gerektirir
(bu yüzden paketler bir *özet listesi* taşır — geçiş sırasında eski ve yeni
sır birlikte kabul edilebilsin diye). Sır asla komut satırına yazılmaz,
loglanmaz ve depoda tutulmaz; CI'da GitHub Actions secret'ıdır.

Paketlenmiş uygulamayı doğrulama — hangi paket olduğunu ve hangi anahtar
malzemesini taşıdığını kendisi söyler:

```bash
# macOS
"dist/dabp-gdm.app/Contents/MacOS/dabp-gdm" --self-test
# Linux
./dist/dabp-gdm/dabp-gdm --self-test
```

```
  edition: gdm (dabp-gdm)
  [OK  ] Edition stamped into the package — gdm
  [OK  ] Admin key material — digest only
```

Bir müşteri paketinde `secret embedded` yazıyorsa o paket **dağıtılmamalıdır**:
sır sızmış demektir ve o müşteri diğer bütün paketler için anahtar üretebilir.
CI bunu her derlemede denetler.

Windows uygulaması GUI alt sistemiyle derlendiği için PowerShell doğrudan
çalıştırıldığında sürecin bitmesini beklemeyebilir. Gerçek çıkış kodunu almak
için `Start-Process -Wait -PassThru` kullanın:

```powershell
$exe = (Resolve-Path '.\dist\dabp\dabp.exe').Path
$islem = Start-Process -FilePath $exe -ArgumentList '--self-test' `
  -Wait -PassThru -NoNewWindow
if ($islem.ExitCode -ne 0) {
  throw "self-test başarısız: çıkış kodu $($islem.ExitCode)"
}
```

### Windows kurulum paketi

```powershell
$surum = "1.0.0"  # panel/settings.py içindeki APP_VERSION ile aynı olmalı
$paket = "gdm"
$ad   = python tools/edition_info.py --edition $paket --field display_name
$appId = python tools/edition_info.py --edition $paket --field app_id
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
  "/DMyAppVersion=$surum" `
  "/DMyAppSlug=dabp-$paket" `
  "/DMyAppName=$ad" `
  "/DMyAppId=$appId" `
  "/DSourceDir=..\..\dist\dabp-$paket" `
  "/DOutputDir=..\..\release" `
  "packaging\windows\dabp.iss"
```

**AppId GUID'i paket başınadır.** Hem Switch Yönetim Paneli'nden ayrıdır, hem
de paketler birbirinden: GDM'ye yapılan bir güncelleme Gaziray'ın üzerine
yazmaz, hepsi aynı makinede yan yana durabilir. GUID'ler
`panel/editions/catalogue.py` tablosunda tutulur ve
`tools/edition_info.py --field app_id` ile okunur.

### Linux AppImage

```bash
SURUM="$(python3 app.py --version)"
PAKET=gdm
./packaging/appimage.sh "dist/dabp-${PAKET}" \
  "release/dabp-${PAKET}-${SURUM}-linux-x86_64.AppImage" "$SURUM"
```

---

## 4. GitHub Actions

### `ci.yml` — yayın öncesi doğrulama

`main` dalındaki bu iş akışının gerçek tetikleyicileri şunlardır:

- **`dap-*-v*` etiketi gönderimi:** Etikete alınan kaynak kodu doğrular.
- **Elle çalıştırma (`workflow_dispatch`):** Seçilen `main` sürümünü doğrular.

Testler ve `--self-test` `vip-yatakli` paketi olarak koşar; suite build
sırrını dışa aktardığı için admin modunda çalışır ve mühendis ekranları da
sınanır (bkz. `tests/support/base.py`).
Üçüncü bir denetim, çıplak `python app.py` çağrısının **sıfırdan farklı**
çıktığını doğrular.

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

**Bir çalıştırma = bir paket.** Bir müşteriye build alırken diğer müşterilerin
paketleri derlenmez.

- **Elle çalıştırma (`workflow_dispatch`):** Açılan listeden paket seçilir;
  dört platform için çıktı arşivi üretir, GitHub sürümü yayımlamaz.
- **`dap-<paket>-v*` etiketi gönderimi:** O paketi üretir ve bütün derleme
  hedefleri başarıyla tamamlanırsa GitHub sürümünü yayımlar.

`resolve` işi etiketten paket adını çıkarır ve tabloya karşı doğrular; tabloda
olmayan bir ad (eski `dap-v0.9.7` biçimi, ya da bir yazım hatası) burada
durur.

**Secret.** `DAP_ADMIN_KEY_SECRET` deponun Actions secret'ları arasında
tanımlı olmalıdır. Yeniden kullanılabilir workflow'lar secret'ları miras
almaz; `secrets: inherit` satırı bu yüzden vardır. Secret tanımsızsa build
yine tamamlanır, ama çıkan paketin admin modu **hiç açılmaz** — `--self-test`
çıktısında `Admin key material — none` yazar.

Switch Yönetim Paneli, `syp` dalındaki kendi `build-switch.yml` dosyasıyla
ayrı derlenir. İki uygulamanın akışları birbirini beklemez ve birbirinin
GitHub sürümüne dokunmaz.

### Sürüm etiketiyle yayınlama

```bash
# Önce panel/settings.py içindeki APP_VERSION değerini yeni sürüme yükseltin.
SURUM="$(python3 app.py --version)"
PAKET=gdm                                   # tools/edition_info.py --list
git tag "dap-${PAKET}-v${SURUM}"
git push origin "dap-${PAKET}-v${SURUM}"
```

Bütün paketleri yayımlamak için her biri için ayrı etiket atılır:

```bash
for PAKET in vip-yatakli gdm gaziray fuar; do
  git tag "dap-${PAKET}-v${SURUM}"
  git push origin "dap-${PAKET}-v${SURUM}"
done
```

| Etiket | Uygulama |
|---|---|
| `dap-vip-yatakli-v…` | Devreye Alma Paneli — VIP ve Yataklı |
| `dap-gdm-v…` | Devreye Alma Paneli — GDM |
| `dap-gaziray-v…` | Devreye Alma Paneli — Gaziray |
| `dap-fuar-v…` | Devreye Alma Paneli — Fuar |
| `dap-v…` | Eski, paket ayrımından önceki biçim |
| `syp-v…` | Switch Yönetim Paneli |
| `v…` | Switch Yönetim Paneli (depoda tek uygulama varken kullanılan eski biçim) |

Etikette paket adından sonra gelen sürüm, `##*-v` (en uzun eşleşme) ile
çıkarılır. `#` ile çıkarmak `dap-vip-yatakli-v0.9.8` etiketinde yanlış sonuç
verir — paket adının içinde de bir `-v` vardır.

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
| Başlık | `Devreye Alma ve Bakım Paneli - GDM v0.9.8` — ham etiket değil, ürün adı + sürüm |
| Etiket | `dap-<paket>-v*` / `syp-v*` · `v*` |
| Dosya adları | `dabp-gdm-…`, `dabp-gaziray-…` / `SwitchYonetimPaneli-…` |
| Sürüm açıklaması | İlgili uygulamanın `docs/RELEASE_NOTES.md` dosyası |
| README bağlantısı | `../../releases?q=dap-`; yalnız Devreye Alma Paneli sürümlerini gösterir |

Her paket kendi Release sayfasına çıkar, çünkü her paketin kendi etiketi
vardır. Bir müşteri kendi sürümünün sayfasına bakar; sayfada başka
müşterilerin dosyaları bulunmaz.

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
kullanılmaz.

Tek gizli değer `DAP_ADMIN_KEY_SECRET`'tir ve yalnızca PyInstaller adımına,
**ortam değişkeni olarak** verilir — komut satırına hiç yazılmaz, çünkü komut
satırı runner üzerinde işlem listesinden okunabilir ve `set -x` çıktısında
görünür; logdaki maskeleme bunların ikisini de geri almaz. Anahtar
malzemesinin doğru gömüldüğü, derlenen paketin `--self-test` çıktısından
geri okunarak denetlenir.

---

## 5. Üretilen dosyalar

Her paket kendi adıyla, beş dosya olarak çıkar. `<paket>` yerine
`vip-yatakli`, `gdm`, `gaziray` veya `fuar` gelir:

```
dabp-<paket>-<sürüm>-windows-x64-Setup.exe
dabp-<paket>-<sürüm>-windows-x64.zip
dabp-<paket>-<sürüm>-linux-x86_64.zip      (içinde .AppImage)
dabp-<paket>-<sürüm>-macos-arm64.zip
dabp-<paket>-<sürüm>-macos-x64.zip
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
Get-FileHash -Algorithm SHA256 '.\dabp-<sürüm>-windows-x64-Setup.exe'
```

```bash
# macOS
shasum -a 256 'dabp-<sürüm>-macos-arm64.zip'

# Linux
sha256sum 'dabp-<sürüm>-linux-x86_64.zip'
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
