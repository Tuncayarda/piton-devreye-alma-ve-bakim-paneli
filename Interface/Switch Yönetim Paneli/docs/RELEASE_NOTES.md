## İndirme

| Platform | Dosya | Nasıl çalıştırılır |
|---|---|---|
| **Windows x64** | `...-windows-x64-Setup.exe` | **Önerilen.** Kurulumu çalıştırın |
| Windows x64 | `...-windows-x64.zip` | Taşınabilir — aşağıdaki uyarıyı okuyun |
| Linux x86_64 | `...-linux-x86_64.zip` | ZIP'i açın, `.AppImage`'i çalıştırın |
| macOS Apple Silicon | `...-macos-arm64.zip` | ZIP'i açın, `.app`'i çalıştırın |
| macOS Intel | `...-macos-x64.zip` | ZIP'i açın, `.app`'i çalıştırın |

Bütünlük doğrulaması için `SHA256SUMS.txt` eklidir:

```bash
sha256sum -c SHA256SUMS.txt        # Linux
shasum -a 256 -c SHA256SUMS.txt    # macOS
```

## Windows: kurulum mu, ZIP mi?

**Kurulum paketi (Setup.exe) önerilir.** ZIP'ten çıkarılan dosyalara Windows
"internetten indirildi" damgası koyuyor; bu damga yüzünden .NET,
`_internal\pythonnet\runtime\Python.Runtime.dll` dosyasını `0x80131515`
hatasıyla reddediyor ve pencere açılmıyor.

ZIP kullanmak zorundaysanız, klasörü açtıktan sonra PowerShell'de:

```powershell
Get-ChildItem -LiteralPath 'SwitchYonetimPaneli' -Recurse -File | Unblock-File
```

Kurulum paketiyle kurulan dosyalarda bu damga oluşmaz; ayrıca WebView2
Runtime eksikse kurulum onu sessizce tamamlar.

## Gereksinimler

- **Windows 10 21H2+ / 11 (x64):** Microsoft Edge **WebView2 Runtime**.
  İşletim sistemiyle gelir; yoksa Setup.exe kurar. ZIP kullanıyorsanız
  [buradan](https://developer.microsoft.com/microsoft-edge/webview2/)
  kendiniz kurmanız gerekir.
- **macOS 11+:** ilk açılışta **yerel ağ erişimi** izni sorulur; switch'leri
  bulmak için gereklidir. Reddedilirse tarama sonuç vermez
  (Sistem Ayarları → Gizlilik ve Güvenlik → Yerel Ağ).
- **Linux (x86_64):** Qt kütüphaneleri eksikse
  `sudo apt install libxcb-cursor0 libegl1 libgl1`.

## İmzasız paket uyarıları

Paketler dijital olarak imzalanmamıştır:

- **Windows SmartScreen:** "bilinmeyen yayımcı" uyarısı →
  *Daha fazla bilgi* → *Yine de çalıştır*.
- **macOS Gatekeeper:** uygulamaya sağ tık → *Aç*, ya da
  Sistem Ayarları → Gizlilik ve Güvenlik → *Yine de aç*.

Ayrıntılı belge: `docs/BUILD_RELEASE.md`
