Bu masaüstü uygulaması, tren setindeki ağ anahtarlarını (switch), anons,
video, ekran ve kontrol sistemlerini doğrular; desteklenen cihazlara IP
adresi atar ve bu cihazların yapılandırma işlemlerini yürütür.

> **Ön sürümler.** Dosya adında `-dev`, `-alpha`, `-beta` veya `-rc` eki
> bulunan paketler saha denemesi içindir ve kararlı sürüm sayılmaz.

Arayüz Türkçe ve İngilizce çalışır. İlk açılışta işletim sisteminin dili
kullanılır; dil, üst bardaki **TR / EN** düğmesiyle değiştirilir ve seçim
kaydedilir.

## Bu sayfadaki paket

Uygulama her müşteri için ayrı paketlenir ve bir paket yalnız kendi
projesini taşır. Bu sayfa **tek bir paketin** sürümüdür; hangisi olduğu
sayfanın başlığında yazar.

| Paket | Uygulama adı | İçindeki projeler |
|---|---|---|
| `vip-yatakli` | Devreye Alma ve Bakım Paneli - VIP ve Yataklı | Yataklı, VIP |
| `gdm` | Devreye Alma ve Bakım Paneli - GDM | GDM |
| `gaziray` | Devreye Alma ve Bakım Paneli - Gaziray | Gaziray |
| `fuar` | Devreye Alma ve Bakım Paneli - Fuar | Fuar |

Farklı paketler aynı bilgisayara yan yana kurulabilir; birbirinin üzerine
yazmaz ve ayarlarını paylaşmazlar.

## İndirme ve çalıştırma

Dosya adlarındaki `<paket>` bölümü yukarıdaki tablodaki kimliktir,
`<sürüm>` bölümü ise sayfanın başlığında görünen sürüm numarasıdır; örneğin
`dabp-gdm-1.0.0-windows-x64-Setup.exe`.

| Sistem | Dosya | Yapılacak işlem |
|---|---|---|
| **Windows x64** | `dabp-<paket>-<sürüm>-windows-x64-Setup.exe` | **Önerilen:** Dosyayı çalıştırın ve kurulum adımlarını izleyin. |
| Windows x64 | `dabp-<paket>-<sürüm>-windows-x64.zip` | ZIP arşivini çıkarın; aşağıdaki taşınabilir paket notunu uygulayın. |
| macOS (Apple Silicon) | `dabp-<paket>-<sürüm>-macos-arm64.zip` | ZIP arşivini çıkarın ve içindeki `.app` paketini açın. |
| macOS (Intel) | `dabp-<paket>-<sürüm>-macos-x64.zip` | ZIP arşivini çıkarın ve içindeki `.app` paketini açın. |
| Linux x86_64 | `dabp-<paket>-<sürüm>-linux-x86_64.zip` | ZIP arşivini çıkarın ve içindeki `.AppImage` dosyasını çalıştırın. |

## İşletim sistemi notları

### Windows

Windows 10 21H2 veya sonrası ya da Windows 11 gerekir. Uygulama, Microsoft
Edge WebView2 Runtime kullanır; önerilen `Setup.exe` paketi bu bileşen kurulu
değilse yükler.

Uygulamanın masaüstü arayüzü yerel HTTP portu kullanmaz. Bu nedenle Nmap,
Wireshark veya Npcap kurulu bilgisayarlarda loopback bağdaştırıcısı/süzgeci
panelin açılışını etkilemez; Npcap'i kaldırmanız gerekmez.

**Mümkünse ZIP yerine `Setup.exe` paketini kullanın.** Windows, internetten
indirilen ZIP arşivindeki dosyalara güvenlik işareti ekleyebilir; bu işaret
uygulamanın açılmasını engelleyebilir. Taşınabilir ZIP paketini kullanmanız
gerekiyorsa arşivi çıkardıktan sonra, üst klasörde açtığınız PowerShell'de şu
komutu çalıştırın:

```powershell
Get-ChildItem -LiteralPath '.\dabp-<paket>' -Recurse -File | Unblock-File
```

Paketler kod imzası taşımaz. SmartScreen uyarısı görünürse *Daha fazla bilgi*
seçeneğini, ardından *Yine de çalıştır* düğmesini kullanın.

### macOS

macOS 11 veya sonrası gerekir. Paketler kod imzası taşımaz. Gatekeeper
uyarısı görünürse Finder'da uygulamaya sağ tıklayın ve *Aç* seçeneğini
kullanın. İlk çalıştırmada istenen yerel ağ izni, saha cihazlarına erişmek
için gereklidir.

### Linux

Ubuntu ve Debian tabanlı dağıtımlarda eksik sistem kitaplıklarını ve yazılım
dosyası seçimi için gereken `zenity` aracını şu komutla kurabilirsiniz. Bunun
yerine `kdialog` da kullanılabilir; diğer dağıtımlarda paket adları farklı
olabilir:

```bash
sudo apt install libxcb-cursor0 libegl1 libgl1 zenity
```

Arşiv yöneticiniz çalıştırma iznini korumadıysa izni yeniden verin:

```bash
chmod +x dabp-*-linux-x86_64.AppImage
```

### Compartment LCD

Compartment LCD okuması ve bu cihazlara yazılım yüklenmesi için Android
Platform Tools içindeki `adb` komutu gerekir. `adb` bulunamazsa ilgili
cihazlar bu denetimler için "uygulanmıyor" olarak görünür.

### Servis anahtarı

Panelin mühendis ekranları (proje ve cihaz listesi tanımları, PISCU, MQTT)
saha kullanımında görünmez. Bunlar yalnız Piton'un servis USB belleği
takılıyken açılır; bellek çıkarıldığında panel kendiliğinden saha görünümüne
döner. Günlük kullanım için gereken hiçbir işlem bu ekranlara bağlı değildir.

## Dosya bütünlüğünü doğrulama

`SHA256SUMS.txt`, bu sayfadaki bütün paketlerin SHA-256 özetlerini içerir.
Yalnızca bir paket indirdiyseniz önce o dosyanın özetini hesaplayın ve sonucu
`SHA256SUMS.txt` içindeki aynı dosya satırıyla karşılaştırın. Aşağıdaki
örneklerde `<sürüm>` bölümünü indirdiğiniz paketin sürümüyle değiştirin.

```powershell
# Windows PowerShell
Get-FileHash -Algorithm SHA256 '.\dabp-<paket>-<sürüm>-windows-x64-Setup.exe'
```

```bash
# macOS
shasum -a 256 'dabp-<paket>-<sürüm>-macos-arm64.zip'

# Linux
sha256sum 'dabp-<paket>-<sürüm>-linux-x86_64.zip'
```

Bütün paketleri ve `SHA256SUMS.txt` dosyasını aynı klasöre indirdiyseniz tüm
dosyaları tek komutla denetleyebilirsiniz:

```bash
# macOS
shasum -a 256 -c SHA256SUMS.txt

# Linux
sha256sum -c SHA256SUMS.txt
```

Özetlerden biri eşleşmiyorsa ilgili paketi çalıştırmayın ve yeniden indirin.

---

Tüm sürümlerin değişiklik günlüğü:
**[docs/DEGISIKLIKLER.md](https://github.com/Tuncayarda/piton-devreye-alma-ve-bakim-paneli/blob/main/docs/DEGISIKLIKLER.md)**
