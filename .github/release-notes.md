## İndirme

| Platform | Dosya | Not |
|---|---|---|
| **Windows x64** | `...-windows-x64-Setup.exe` | **Önerilen.** Kurulum paketi |
| Windows x64 | `...-windows-x64.zip` | Taşınabilir — aşağıdaki uyarıyı okuyun |
| Linux x86_64 | `...-linux-x86_64.AppImage` | `chmod +x` sonra çalıştırın |
| macOS Apple Silicon | `...-macos-arm64.zip` | Açın, `.app`'i çalıştırın |
| macOS Intel | `...-macos-x64.zip` | Açın, `.app`'i çalıştırın |

Bütünlük doğrulaması için `SHA256SUMS.txt` eklidir.

## Windows: ZIP mi, Setup mu?

**Setup.exe önerilir.** ZIP'ten çıkarılan dosyalara Windows "internetten
indirildi" damgası koyuyor; bu damga yüzünden .NET,
`_internal\pythonnet\runtime\Python.Runtime.dll` dosyasını `0x80131515`
hatasıyla reddediyor ve pencere açılmıyor.

ZIP kullanmak zorundaysanız, klasörü açtıktan sonra PowerShell'de:

```powershell
Get-ChildItem -LiteralPath 'SwitchYonetimPaneli' -Recurse -File | Unblock-File
```

Kurulum paketiyle kurulan dosyalarda bu damga oluşmaz; ayrıca WebView2
Runtime eksikse installer onu sessizce kurar.

## Gereksinimler ve uyarılar

- **Windows:** Microsoft Edge WebView2 Runtime (Windows 10 21H2+ ile gelir).
  Eksikse Setup.exe kurar; ZIP kullanıyorsanız kendiniz kurmanız gerekir.
- **macOS:** ilk açılışta yerel ağ erişimi izni sorulur; switch'leri bulmak
  için gereklidir.
- Paketler **imzasızdır** — Windows SmartScreen ve macOS Gatekeeper uyarı
  gösterebilir. Ayrıntılar:
  `Interface/Switch Yönetim Paneli/BUILD_RELEASE.md`
