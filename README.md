# Devreye Alma ve Bakım Paneli

Tren setlerindeki cihazları tek bir arayüzden doğrulamak ve devreye alma
işlemlerini yönetmek için geliştirilmiş masaüstü uygulamasıdır. Panel, bir
`DeviceMap` envanterini temel alır; desteklenen cihazlarda IP atama, anons
ekipmanlarında yapılandırma, uygun cihazlarda yazılım yükleme ve Excel
kontrol listesi üretme işlemlerini yürütür.

> **Proje durumu:** Kaynak kod `1.0.4` sürümünü bildirir. Yayın için paket
> başına etiket atılır (`dap-vip-yatakli-v1.0.4` gibi); ayrıntılar
> [derleme ve yayınlama](docs/BUILD_RELEASE.md) belgesindedir. Hazırlanan
> değişiklikler [değişiklik günlüğündedir](docs/DEGISIKLIKLER.md).

## Her müşteri kendi paketini alır

Tek program, birden çok paket. Bir paket yalnız kendi müşterisinin
projesini taşır: başka bir müşterinin cihaz listesi, adresleri ve dahili
numaraları o pakette **yoktur** — gizlenmez, dosyada bulunmaz. Ayrım derleme
anında yapılır (`panel/editions/catalogue.py`).

| Paket | İçindeki projeler |
|---|---|
| `vip-yatakli` | Yataklı ve VIP — aynı müşterinin iki tren tipi, üst çubuktan seçilir |
| `gdm` | GDM |
| `gaziray` | Gaziray |

Kaynaktan çalıştırırken hangi paket olduğu **söylenmelidir**; çıplak
`python app.py` geçerli adları yazıp durur.

Mühendis ekranları (Proje & Cihaz Listesi, PISCU, MQTT, ADB, Switch) yalnız
**admin modda** görünür. Parola yok, gizli tık yok, komut satırı seçeneği
yok; iki kapı var ve ikisinde de kanıtı sunucu tarafı denetler:

| Kapı | Ne ister |
|---|---|
| **Servis anahtarı** | Panelin tanıdığı bir anahtar dosyası |
| **Uzaktan oturum** | Telefonla okutulan bir QR onayı, ya da mühendisin kendi hesabı |

Kapıyı tutan kalmayınca mod kapanır — cihazlara yazan bir iş sürüyorsa iş
bitene kadar bekletilerek.

Anahtar iki yerden okunur:

| Yer | Ne zaman |
|---|---|
| Takılı USB bellek | Normal kullanım; anahtar taşınan fiziksel bir şeydir |
| **Uygulamanın kendi klasörü** (`.exe`'nin yanı) | Uzaktan erişim: klavyenin başında bellek takacak kimse yoktur |

İkisinde de aranan dosya aynı: `dabp-admin-key.json`. Dosya **sırrı değil,
doğrulanabilir bir kanıt** taşır ve pakete damgalanmış özete karşı sınanır —
başkasının koyduğu bir dosya, yanlış bellek gibi reddedilir ve içindeki
hiçbir şey başka bir paket için anahtar üretemez. Klasördeki kopyanın
vazgeçtiği tek şey fizikselliktir: kopyalanabilir, ve doğru klasördeki bir
kopya o kurulumda admin modu açar.

Uzaktan oturumu imzalayan servis **ayrı ve private bir depoda**; bu depoda
özel anahtar yok, yalnız doğrulama var. Oturum kendiliğinden bitiyor,
telefondan kapatılabiliyor ve ağ giderse birkaç saniyede düşüyor.

Ayrıntılar: `panel/adminkey/`, `panel/remotekey/`.

## Öne çıkan özellikler

- Switch, anons sistemi, kamera/NVR, LCD/LED, erişim noktası, PISCU, HMI ve
  ICU cihazlarını tek envanter üzerinden tarar.
- Tam keşif taramalarını düzenli olarak çalıştırır; doğrulanmış cihazların
  canlı verilerini daha kısa aralıklarla yeniler.
- IP atama sırasında bilgisayarın ve switch bağlantılarının bulunduğu
  portları MAC tablolarından belirleyerek korur.
- Compartment LCD cihazlarını switch portlarında sırayla yalıtır; isteğe bağlı
  APK kurulumundan sonra `10.1.1.40…` kaynak adreslerinden seçili setin
  adreslerine ADB ile taşır ve seri numarası/port kimliğini doğrular.
  Test tezgâhında fiziksel işlem switch'i ve herhangi bir PoE portu ayrıca
  seçilebilir; bağlı LCD kaynak IP ve switch MAC tablosuyla DeviceMap'teki
  kimliğine güvenli biçimde eşleştirilir.
- Atanacak adresin maskesi girilebilir (varsayılan `/24`) ve Compartment
  LCD'ler 1. set adreslerine (`10.1.1.40…`) geri döndürülebilir. Tezgâhta tek
  bir porta takılı LCD'ye, DeviceMap'e bakılmadan istenen adres yazılabilir.
- Intercom, Handset, Amplifier ve UIC ayarlarını cihazdan okuyup hedef
  değerlerle karşılaştırır; yalnızca değişen alanları yazar ve sonucu yeniden
  doğrular. Compartment LCD'de şimdilik tek yazılabilir alan IP adresidir ve
  ADB üzerinden yazılır.
- Anons ekipmanlarına `.bin`, Compartment LCD cihazlarına `.apk` yükler;
  işlem sonrasında APK manifestindeki gerçek paket kimliğini ve bildirilen
  sürümü denetler.
- Excel şablonunu arayüzde ön izler ve doğrulama sonuçlarını işletim
  sisteminin Belgeler klasörüne aktarır.
- Uzun işlemleri kuyrukta yürütür; aşama, ilerleme, cihaz/port sonucu ve ham
  günlük dosyasını ayrı ayrı gösterir.
- Arayüz Türkçe ve İngilizce çalışır; dil üst bardan değiştirilir ve seçim
  kaydedilir.
- Masaüstü arayüzünü HTTP ve loopback portu açmadan, pywebview'un doğrudan
  Python–JavaScript köprüsü üzerinden çalıştırır. Arayüzde girilen erişim
  kimlikleri süreç belleğinde tutulur ve uygulama kapandığında silinir.

## Hızlı başlangıç

Uygulama Python 3.10 veya sonrasını gerektirir. Paketler Python 3.12 ile
oluşturulur ve sürekli bütünleştirme denetimleri bu sürümle çalıştırılır.

### macOS veya Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r docs/requirements-macos.txt  # Linux: requirements-linux.txt
python app.py --edition vip-yatakli
```

### Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r docs\requirements-windows.txt
python app.py --edition vip-yatakli
```

Paketlenmiş uygulamada bu bayrak gereksizdir: paket hangi müşterinin paketi
olduğunu **damgasından** bilir ve damgayla çelişen bir `--edition` değeri
sessizce yok sayılmaz, **reddedilir**.

Uygulama yükseltilmiş (yönetici) yetkiyle çalıştırılır: panel ağ arayüzünü ve
ARP önbelleğini okuyup temizliyor, cihazlara IP yazıyor ve switch portlarını
yönetiyor. Windows'ta paketlenmiş uygulamanın manifesti yöneticilik ister, o
yüzden çift tıklandığında UAC penceresi doğrudan çıkar.

Yetki yoksa panel yine açılmaz — ama sessizce kapanmaz: sebebi anlatan bir
pencere çıkar. İzni işletim sistemi ister: Windows'ta UAC, macOS'ta sistem
parolası penceresi, Linux'ta polkit. Parola uygulamaya girilmez; istemi
işletim sistemi gösterir. Kimsenin başında olmadığı otomatik koşularda
yükseltme denemesi `PANEL_ELEVATION_PROMPT=0` ile kapatılır. `--self-test` ve
`--version` bu denetimin dışındadır; ikisi de cihaza ve ağa dokunmaz.

| Seçenek | Açıklama |
|---|---|
| `--edition <paket>` | Hangi müşterinin paketi olarak çalışılacağı. Kaynaktan **zorunlu**; `DAP_EDITION` ortam değişkeni de kabul edilir. |
| `--browser` | HTTP tabanlı geliştirme/tanı kipini varsayılan tarayıcıda açar. |
| `--port 8790` | Yalnız `--browser` ile birlikte HTTP portunu sabitler; `0` doğrudan işletim sistemine port seçtirir. |
| `--self-test` | Pencere ve soket açmadan paketi, cihaz listesini ve üretim köprüsünü doğrular; çıkış kodu döner. |
| `--version` | Yalnızca uygulama sürümünü yazdırır. |

### Fuar / gösterim kipi

`ADB_REQUIRE_PACKAGE=0`

Kompartıman LCD okuması normalde ekranda `com.piton.train_lcd_panel`
uygulamasını arar ve bulamazsa cihazı **kırmızı** işaretler. Trende doğru
davranış budur: ekran zaten o uygulama için oradadır.

Fuarda değildir. Stantta ödünç alınmış donanım olur, her ünitede başka bir
uygulama çalışır ve aranacak tek bir uygulama yoktur; o zaman bütün pano
kırmızıya döner ve gerçekten erişilemeyen üniteler bu gürültünün içinde
kaybolur. Bu değişkenle ADB'nin **bağlanabilmesi yeterli** sayılır.

Gevşetilse de ekran yanıt vermek zorundadır: seri numarası, saat dilimi ve
çalışma süresi aynı bağlantı üzerinden okunur ve hiçbirini vermeyen cihaz yine
erişilemez sayılır. Düşen tek şart, adı belli bir uygulamanın aranmasıdır.

```bash
ADB_REQUIRE_PACKAGE=0 python app.py --edition vip-yatakli
```

## Doğrulama

Aşağıdaki komutlar pencere açmaz ve gerçek cihazlara bağlanmaz:

```bash
python app.py --edition vip-yatakli --self-test
python -m unittest discover -s tests -t .
python tools/build_desktop_bundle.py --check
```

Testler sahte cihaz sunucuları kullanır. Masaüstü HTML'i CSS, görsel ve
JavaScript'i tek dosyada taşır; kaynak arayüz değiştirildiğinde Deno 2.9.4 ile
`python tools/build_desktop_bundle.py` çalıştırılarak yenilenir. Arayüz
testleri ayrıca `deno test --allow-read tests/js/` ile koşar.

## Belgeler

| Belge | İçerik |
|---|---|
| [Mimari ve çalışma modeli](docs/MIMARI.md) | Katmanlar, güvenlik, tarama, kuyruk ve ekran davranışları |
| [Değişiklik günlüğü](docs/DEGISIKLIKLER.md) | Yayımlanmış ve henüz yayımlanmamış değişiklikler |
| [Derleme ve yayınlama](docs/BUILD_RELEASE.md) | Paket başına derleme, servis anahtarı ve GitHub Actions yayın akışı |
| [GitHub sürüm metni](docs/RELEASE_NOTES.md) | Sürüm sayfasında kullanılan indirme ve kurulum açıklaması |
| [Cihaz uç noktaları](docs/CIHAZ_ENDPOINTLERI.md) | Cihazlara göre veri kaynakları ve örnek sorgular |
| [Cihaz veri alanları](docs/CIHAZ_VERI_ALANLARI.md) | Excel sütunları, veri eşlemeleri ve doğrulama notları |

## Dizin yapısı

| Yol | İçerik |
|---|---|
| `app.py` | Soketsiz uygulama penceresi, komut satırı seçenekleri ve açılış akışı |
| `panel/api/` | Ortak servis katmanı, yol tabloları, yetki süzgeci ve isteğe bağlı HTTP adaptörü |
| `panel/desktop/` | Dar pywebview köprüsü ve tek HTML yükleyicisi |
| `panel/editions/` | Paket tablosu: hangi paket hangi projeyi ve hangi ekranları taşır |
| `panel/adminkey/` | USB servis anahtarı: okuma, yazma, izleme; mühürlü proje haritaları |
| `panel/remotekey/` | İmzalı uzaktan oturum: QR eşleşmesi, hesapla giriş, nabız |
| `panel/elevation/` | Yükseltilmiş yetki kapısı ve platforma göre yeniden başlatma |
| `panel/inventory/` | DeviceMap envanteri, IP şablonu çözümü, kategori tanımları |
| `panel/probe/` | Cihaz okuma: switch, anons, kamera/NVR, ADB, MQTT |
| `panel/ip_assign/` | IP atama planı, korunan portlar, koşu ve ilerleme |
| `panel/config_sync/` | Konfigürasyon oku/karşılaştır/yaz |
| `panel/firmware/` | Yazılım yükleme (anons: HTTP imaj, LCD: adb APK) |
| `panel/checklist/` | Excel şablonu, ön izleme ve çıktı |
| `panel/network/` | Bilgisayarın kendi ağ adreslerinin hazırlanması |
| `panel/jobs/` | FIFO iş kuyruğu ve tarama görünümü |
| `panel/messages/` | Türkçe ve İngilizce arayüz metinleri |
| `field_scripts/` | Çalışma anında yüklenen, sahada doğrulanmış yardımcı motorlar |
| `static/` | Modüler tarayıcı kaynakları ve üretilmiş `desktop.html` |
| `icons/` | Uygulama ikonu: `app.png`, `app.icns`, `app.ico` (logodan üretilir) |
| `tools/` | Masaüstü paketleyicisi, paket bilgisi ve servis anahtarı araçları |
| `tests/` | Birim ve arayüz testleri ile sahte cihaz sunucuları |
| `docs/` | Mimari, cihaz, paketleme ve sürüm belgeleri |
| `dabp.spec`, `packaging/` | PyInstaller tanımı, Windows kurulumu ve AppImage |
| `devicemaps/<proje>/` | Projenin envanteri ve kontrol listesi: `DeviceMap_<Proje>.json` + `Field_Device_Verification_<Proje>.xlsx` (adlandırma standardı: bkz. `docs/BUILD_RELEASE.md`) |
| `devicemaps/_base/` | Çalışma kitaplarının üretildiği şablon; bir projeye ait değildir |

### DeviceMap kimlik bilgisi taşımaz

Envanterdeki `Username`, `Password` ve `PBXPassword` alanları **boştur** ve
öyle kalmalıdır:

- Switch ve kamera kimlikleri panelin kendisinden istenir, yalnız bellekte
  tutulur ve hiçbir dosyaya yazılmaz (bkz. `panel/credentials.py`).
- SIP parolası ayrıca yazılmaz; sahadaki kural gereği dahili numaranın
  aynısıdır ve panel onu dahiliden türetir (bkz.
  `panel/config_sync/targets.py`).
- Cihaz seri numaraları da envanterde tutulmaz; tarama sırasında cihazın
  kendisinden okunur.

Sürekli bütünleştirme bunu denetler: envanterde dolu bir kimlik alanı
bulunursa iş başarısız olur.

### `field_scripts/` dizini neden ayrı?

Panel, sahada denenmiş iki betiğin iş mantığını yeniden yazmak yerine bunları
çalışma anında dosya yolundan içe aktarır (`panel/script_loader.py`).
Paketleme sırasında dosyalar uygulama paketinin köküne kopyalanır.

| Dosya | Görevi | Kaynağı |
|---|---|---|
| `device_verify.py` | Alan ayıklama ve Excel şeması | Saha doğrulama betiği |
| `intercom_ip_assign.py` | Intercom IP atama akışı | Saha atama betiği |

Switch erişimi üçüncü bir betikti (`switch_api.py`) ve iki kopyası elle
eşitleniyordu. Artık paketin kendi parçası: `panel/switch/`. Switch ekranının
**yazması** gerekiyordu, ödünç alınan salt-okunur bir betik ise bunu ikinci
bir istemciye dönüşmeden büyütemezdi — ve elle eşitlenen iki kopya zaten
ayrışmanın beklendiği yerdi.

## Depo ve sürüm düzeni

Bu depo yalnız Devreye Alma ve Bakım Paneli'ni barındırır. Uygulama daha
önce Switch Yönetim Paneli ile aynı depoda, ayrı bir branch'te duruyordu;
o uygulama artık kendi deposunda. İlk commit'ler iki uygulamanın ortak
geçmişi olduğu için eski sürümlerde her ikisinin dosyaları da görünür.

Etiket biçimi `dap-<paket>-v*`: her müşteri paketi kendi etiketiyle
yayımlanır ve biri için build alırken diğerleri derlenmez. Etiket sürümü,
`panel/settings.py` içindeki `APP_VERSION` değeriyle birebir aynı olmalıdır —
örneğin `APP_VERSION = "1.0.0"` için `dap-gdm-v1.0.0`; uyuşmazlıkta yayın
derlemesi durur. Paket ayrımından önceki `dap-v*` biçimi eski sürümlerde
görülür.

Hazır paketler [Releases](../../releases) sayfasındadır. Paketler henüz
kod imzalı değildir; Windows masaüstü paketi Edge WebView2 çalışma
zamanını gerektirir. Ayrıntılı platform yönergeleri her sürümün indirme
sayfasında yer alır.

## Lisans

Telif Hakkı © 2026 **Piton Technology**. Tüm hakları saklıdır.

Bu depo **tescillidir**: kaynağın görünür olması kullanım hakkı vermez.
Yazılı izin olmadan kullanılamaz, kopyalanamaz, değiştirilemez ve
dağıtılamaz. Koşulların tamamı [LICENSE](LICENSE) dosyasındadır.

Üçüncü taraf kütüphaneler kendi lisanslarıyla gelir (bkz.
`docs/requirements*.txt`). Linux masaüstü paketi **PyQt6** kullanır; PyQt6
GPL/ticari çift lisanslıdır ve bu paketin dağıtımı Riverbank'tan ticari
lisans gerektirebilir. macOS (PyObjC) ve Windows (pythonnet) bağımlılıkları
izin verici lisanslıdır.
