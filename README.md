# Devreye Alma Paneli

Yataklı tren setlerindeki cihazları tek bir arayüzden doğrulamak ve devreye
alma işlemlerini yönetmek için geliştirilmiş masaüstü uygulamasıdır. Panel,
`DeviceMap.json` envanterini temel alır; desteklenen cihazlarda IP atama,
anons ekipmanlarında yapılandırma, uygun cihazlarda yazılım yükleme ve Excel
kontrol listesi üretme işlemlerini yürütür.

> **Proje durumu:** Kaynak kod `0.9.3` sürümünü bildirir. Bu sürüm henüz
> etiketlenip yayımlanmamıştır; hazırlanan değişiklikler
> [değişiklik günlüğünde](docs/DEGISIKLIKLER.md) yer alır. Yayın için
> `dap-v0.9.3` etiketi oluşturulmalıdır. `dap-v0.9.2` etiketi hiç
> oluşturulmadığından o sürümün değişiklikleri de bu yayına girer.

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
- Yerel API'yi yalnızca `127.0.0.1` üzerinde sunar. Arayüzde girilen erişim
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

Masaüstü penceresi yerine varsayılan tarayıcıyı kullanmak için
`python app.py --tarayici` komutunu çalıştırın. Diğer seçenekler:

| Seçenek | Açıklama |
|---|---|
| `--port 8790` | Yerel servisi belirtilen portta açar; varsayılan olarak boş bir port seçilir. |
| `--admin-parolasi …` | Admin ekranını parola ile korur; değer kalıcı depoya yazılmaz. |
| `--self-test` | Pencereyi açmadan paket ve yerel servis denetimlerini çalıştırır. |
| `--version` | Yalnızca uygulama sürümünü yazdırır. |

## Doğrulama

Aşağıdaki komutlar pencere açmaz ve gerçek cihazlara bağlanmaz:

```bash
python app.py --self-test
python -m unittest discover -s tests -t .
```

Testler sahte cihaz sunucuları kullanır. JavaScript söz dizimi denetimleri,
sistemde Deno kuruluysa test paketine dâhil edilir.

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
| `app.py` | Uygulama penceresi, komut satırı seçenekleri ve açılış akışı |
| `panel_api.py` | Panelin yerel HTTP API'si |
| `core/` | Envanter, okuma, doğrulama, kuyruk ve işlem mantığı |
| `betikler/` | Çalışma anında yüklenen, sahada doğrulanmış yardımcı motorlar |
| `static/` | Derleme adımı gerektirmeyen HTML, CSS ve JavaScript arayüzü |
| `tests/` | Birim ve arayüz testleri ile sahte cihaz sunucuları |
| `docs/` | Mimari, cihaz, paketleme ve sürüm belgeleri |
| `DeviceMap.json` | Ağ topolojisi ve hedef değerler için temel envanter |
| `Yatakli_Saha_Cihaz_Dogrulama.xlsx` | Kontrol listesi şablonu |

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

Depoda iki uygulama bulunur ve her biri kendi dalında geliştirilir:

| Dal | Uygulama | Etiket biçimi |
|---|---|---|
| `main` | Devreye Alma Paneli (bu dal) | `dap-v*` |
| `syp` | Switch Yönetim Paneli | `syp-v*`, eski sürümlerde `v*` |

Etiket sürümü, `core/ayar.py` içindeki `APP_VERSION` değeriyle birebir aynı
olmalıdır. Örneğin `APP_VERSION = "0.9.3"` için etiket `dap-v0.9.3` olur;
uyuşmazlıkta yayın derlemesi durur.

Hazır paketler [Devreye Alma Paneli sürümleri](../../releases?q=dap-v)
sayfasındadır. Paketler henüz kod imzalı değildir; Windows masaüstü paketi
Edge WebView2 çalışma zamanını gerektirir. Ayrıntılı platform yönergeleri
her sürümün indirme sayfasında yer alır.

> GitHub sürüm listesi depo düzeyindedir; dallara göre ayrı liste sunulmaz.
> Uygulamalar başlık, etiket öneki ve paket adlarıyla ayrılır. “Latest”
> rozeti de depo düzeyinde tek olduğu için yayınlar bilinçli olarak
> `--latest=false` seçeneğiyle oluşturulur.
