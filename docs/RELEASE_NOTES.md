Bu masaüstü uygulaması, tren setindeki ağ anahtarlarını (switch), anons,
video, ekran ve kontrol sistemlerini doğrular; desteklenen cihazlara IP
adresi atar ve bu cihazların yapılandırma işlemlerini yürütür.

> **Ön sürümler.** Dosya adında `-dev`, `-alpha`, `-beta` veya `-rc` eki
> bulunan paketler saha denemesi içindir ve kararlı sürüm sayılmaz.

## İndirme ve çalıştırma

Dosya adlarındaki `<sürüm>` bölümü, sayfanın başlığında görünen sürüm
numarasıdır; örneğin `0.9.6`.

| Sistem | Dosya | Yapılacak işlem |
|---|---|---|
| **Windows x64** | `DevreyeAlmaPaneli-<sürüm>-windows-x64-Setup.exe` | **Önerilen:** Dosyayı çalıştırın ve kurulum adımlarını izleyin. |
| Windows x64 | `DevreyeAlmaPaneli-<sürüm>-windows-x64.zip` | ZIP arşivini çıkarın; aşağıdaki taşınabilir paket notunu uygulayın. |
| macOS (Apple Silicon) | `DevreyeAlmaPaneli-<sürüm>-macos-arm64.zip` | ZIP arşivini çıkarın ve içindeki `.app` paketini açın. |
| macOS (Intel) | `DevreyeAlmaPaneli-<sürüm>-macos-x64.zip` | ZIP arşivini çıkarın ve içindeki `.app` paketini açın. |
| Linux x86_64 | `DevreyeAlmaPaneli-<sürüm>-linux-x86_64.zip` | ZIP arşivini çıkarın ve içindeki `.AppImage` dosyasını çalıştırın. |

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
Get-ChildItem -LiteralPath '.\DevreyeAlmaPaneli' -Recurse -File | Unblock-File
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
chmod +x DevreyeAlmaPaneli-*-linux-x86_64.AppImage
```

### Compartment LCD

Compartment LCD okuması ve bu cihazlara yazılım yüklenmesi için Android
Platform Tools içindeki `adb` komutu gerekir. `adb` bulunamazsa ilgili
cihazlar bu denetimler için "uygulanmıyor" olarak görünür.

## Dosya bütünlüğünü doğrulama

`SHA256SUMS.txt`, bu sayfadaki bütün paketlerin SHA-256 özetlerini içerir.
Yalnızca bir paket indirdiyseniz önce o dosyanın özetini hesaplayın ve sonucu
`SHA256SUMS.txt` içindeki aynı dosya satırıyla karşılaştırın. Aşağıdaki
örneklerde `<sürüm>` bölümünü indirdiğiniz paketin sürümüyle değiştirin.

```powershell
# Windows PowerShell
Get-FileHash -Algorithm SHA256 '.\DevreyeAlmaPaneli-<sürüm>-windows-x64-Setup.exe'
```

```bash
# macOS
shasum -a 256 'DevreyeAlmaPaneli-<sürüm>-macos-arm64.zip'

# Linux
sha256sum 'DevreyeAlmaPaneli-<sürüm>-linux-x86_64.zip'
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
**[docs/DEGISIKLIKLER.md](https://github.com/Tuncayarda/DevreyeAlmaPaneli/blob/main/docs/DEGISIKLIKLER.md)**
