# Devreye Alma Paneli

Yataklı tren setlerindeki cihazları tek bir arayüzden doğrulamak ve devreye
alma işlemlerini yönetmek için geliştirilmiş masaüstü uygulamasıdır. Panel,
`DeviceMap.json` envanterini temel alır; desteklenen cihazlarda IP atama,
anons ekipmanlarında yapılandırma, uygun cihazlarda yazılım yükleme ve Excel
kontrol listesi üretme işlemlerini yürütür.

> **Proje durumu:** Kaynak kod `0.9.6` sürümünü bildirir. Bu sürüm henüz
> etiketlenip yayımlanmamıştır; hazırlanan değişiklikler
> [değişiklik günlüğünde](docs/DEGISIKLIKLER.md) yer alır. Yayın için
> `dap-v0.9.6` etiketi oluşturulmalıdır. `dap-v0.9.2`, `dap-v0.9.3` ve
> `dap-v0.9.5` etiketleri hiç oluşturulmadığından o sürümlerin
> değişiklikleri de bu yayına girer.

## Öne çıkan özellikler

- Switch, anons sistemi, kamera/NVR, LCD/LED, erişim noktası, PISCU, HMI ve
  ICU cihazlarını tek envanter üzerinden tarar.
- Tam keşif taramalarını düzenli olarak çalıştırır; doğrulanmış cihazların
  canlı verilerini daha kısa aralıklarla yeniler.
- IP atama sırasında bilgisayarın ve switch bağlantılarının bulunduğu
  portları MAC tablolarından belirleyerek korur.
- Intercom, Handset, Amplifier ve UIC ayarlarını cihazdan okuyup hedef
  değerlerle karşılaştırır; yalnızca değişen alanları yazar ve sonucu yeniden
  doğrular.
- Anons ekipmanlarına `.bin`, Compartment LCD cihazlarına `.apk` yükler;
  işlem sonrasında bildirilen sürümü denetler.
- Excel şablonunu arayüzde ön izler ve doğrulama sonuçlarını işletim
  sisteminin Belgeler klasörüne aktarır.
- Uzun işlemleri kuyrukta yürütür; aşama, ilerleme, cihaz/port sonucu ve ham
  günlük dosyasını ayrı ayrı gösterir.
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
python app.py
```

### Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r docs\requirements-windows.txt
python app.py
```

Uygulama yükseltilmiş (yönetici) yetkiyle çalıştırılır: panel ağ arayüzünü ve
ARP önbelleğini okuyup temizliyor, cihazlara IP yazıyor ve switch portlarını
yönetiyor. Windows'ta paketlenmiş uygulamanın manifesti yöneticilik ister, o
yüzden çift tıklandığında UAC penceresi doğrudan çıkar.

Yetki yoksa panel yine açılmaz — ama sessizce kapanmaz: sebebi anlatan bir
pencere çıkar ve iki yol sunar, **yönetici olarak yeniden başlat** ya da
**çıkış**. İzni işletim sistemi ister: Windows'ta UAC, macOS'ta sistem
parolası penceresi, Linux'ta polkit. O yol düşerse (macOS'ta korumalı
klasörlerde olabiliyor) ve uygulama bir terminalden başlatılmışsa, yükseltmeyi
`sudo` ile o terminale devretmek ayrıca sorulur.
Parola uygulamaya girilmez; istemi işletim sistemi gösterir. Kimsenin başında
olmadığı otomatik koşularda pencere `PANEL_YETKI_PENCERESI=0` ile kapatılır.
`--self-test` ve `--version` bu denetimin dışındadır; ikisi de cihaza ve ağa
dokunmaz.

HTTP tabanlı geliştirme/tanı kipini varsayılan tarayıcıda kullanmak için
`python app.py --tarayici` komutunu çalıştırın. Diğer seçenekler:

| Seçenek | Açıklama |
|---|---|
| `--port 8790` | Yalnız `--tarayici` ile birlikte HTTP portunu sabitler; `0` doğrudan işletim sistemine port seçtirir. |
| `--admin-parolasi …` | Admin ekranını parola ile korur; değer kalıcı depoya yazılmaz. |
| `--self-test` | Pencere ve soket açmadan tek HTML paketini ve üretim köprüsünü doğrular. |
| `--version` | Yalnızca uygulama sürümünü yazdırır. |

## Doğrulama

Aşağıdaki komutlar pencere açmaz ve gerçek cihazlara bağlanmaz:

```bash
python app.py --self-test
python -m unittest discover -s tests -t .
python tools/masaustu_paketi.py --check
```

Testler sahte cihaz sunucuları kullanır. Masaüstü HTML'i CSS, görsel ve
JavaScript'i tek dosyada taşır; kaynak arayüz değiştirildiğinde Deno 2.9.4 ile
`python tools/masaustu_paketi.py` çalıştırılarak yenilenir.

## Belgeler

| Belge | İçerik |
|---|---|
| [Mimari ve çalışma modeli](docs/MIMARI.md) | Katmanlar, güvenlik, tarama, kuyruk ve ekran davranışları |
| [Değişiklik günlüğü](docs/DEGISIKLIKLER.md) | Yayımlanmış ve henüz yayımlanmamış değişiklikler |
| [Derleme ve yayınlama](docs/BUILD_RELEASE.md) | Yerel paketleme ve GitHub Actions yayın akışı |
| [GitHub sürüm metni](docs/RELEASE_NOTES.md) | Sürüm sayfasında kullanılan indirme ve kurulum açıklaması |
| [Cihaz uç noktaları](docs/CIHAZ_ENDPOINTLERI.md) | Cihazlara göre veri kaynakları ve örnek sorgular |
| [Cihaz veri alanları](docs/CIHAZ_VERI_ALANLARI.md) | Excel sütunları, veri eşlemeleri ve doğrulama notları |

## Dizin yapısı

| Yol | İçerik |
|---|---|
| `app.py` | Soketsiz uygulama penceresi, komut satırı seçenekleri ve açılış akışı |
| `masaustu.py` | Dar pywebview köprüsü ve tek HTML yükleyicisi |
| `panel_api.py` | Ortak API servis katmanı ve isteğe bağlı HTTP adaptörü |
| `core/` | Envanter, okuma, doğrulama, kuyruk ve işlem mantığı |
| `betikler/` | Çalışma anında yüklenen, sahada doğrulanmış yardımcı motorlar |
| `static/` | Modüler tarayıcı kaynakları ve üretilmiş `masaustu.html` |
| `tools/masaustu_paketi.py` | Masaüstü HTML'ini üretir ve güncelliğini doğrular |
| `tests/` | Birim ve arayüz testleri ile sahte cihaz sunucuları |
| `docs/` | Mimari, cihaz, paketleme ve sürüm belgeleri |
| `DeviceMap.json` | Ağ topolojisi ve hedef değerler için temel envanter |
| `Yatakli_Saha_Cihaz_Dogrulama.xlsx` | Kontrol listesi şablonu |

### `DeviceMap.json` kimlik bilgisi taşımaz

Envanterdeki `Username`, `Password` ve `PBXPassword` alanları **boştur** ve
öyle kalmalıdır:

- Switch ve kamera kimlikleri panelin kendisinden istenir, yalnız bellekte
  tutulur ve hiçbir dosyaya yazılmaz (bkz. `core/kimlik.py`).
- SIP parolası ayrıca yazılmaz; sahadaki kural gereği dahili numaranın
  aynısıdır ve panel onu dahiliden türetir (bkz. `core/konfig.hedef_of`).
- Cihaz seri numaraları da envanterde tutulmaz; tarama sırasında cihazın
  kendisinden okunur.

Sürekli bütünleştirme bunu denetler: envanterde dolu bir kimlik alanı
bulunursa iş başarısız olur.

### `betikler/` dizini neden ayrı?

Panel, sahada denenmiş üç betiğin iş mantığını yeniden yazmak yerine bunları
çalışma anında dosya yolundan içe aktarır (`core/betik.py`). Paketleme
sırasında dosyalar uygulama paketinin köküne kopyalanır.

| Dosya | Görevi | Kaynağı |
|---|---|---|
| `switch_api.py` | Switch erişimi ile PoE/port okuma | Switch Yönetim Paneli (`syp` dalı) |
| `device_verify.py` | Alan ayıklama ve Excel şeması | Saha doğrulama betiği |
| `intercom_ip_assign.py` | Intercom IP atama akışı | Saha atama betiği |

`switch_api.py`, `syp` dalındaki özgün dosyanın kopyasıdır. Switch API'sinde
değişiklik yapıldığında iki kopya elle eşitlenmelidir.

## Depo ve sürüm düzeni

Bu depo yalnız Devreye Alma ve Bakım Paneli'ni barındırır. Uygulama daha
önce Switch Yönetim Paneli ile aynı depoda, ayrı bir branch'te duruyordu;
o uygulama artık kendi deposunda. İlk commit'ler iki uygulamanın ortak
geçmişi olduğu için eski sürümlerde her ikisinin dosyaları da görünür.

Etiket biçimi `dap-v*`; önek mevcut iş akışlarıyla uyum için korunuyor.
Etiket sürümü, `core/ayar.py` içindeki `APP_VERSION` değeriyle birebir aynı
olmalıdır. Örneğin `APP_VERSION = "0.9.6"` için etiket `dap-v0.9.6` olur;
uyuşmazlıkta yayın derlemesi durur.

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
