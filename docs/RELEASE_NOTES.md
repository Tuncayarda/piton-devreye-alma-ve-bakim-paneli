Tren setinin tamamını (switch, anons, video, ekran, kontrol) doğrulayan,
IP atayan ve konfigüre eden masaüstü uygulaması.

> **Ön sürüm (dev).** Sahada denenmesi için çıkarıldı, kararlı sayılmaz.

## İndir

| Sistem | Dosya | Ne yapılır |
|---|---|---|
| **Windows x64** | `...-windows-x64-Setup.exe` | **Önerilen** — çalıştır, kurulur |
| Windows x64 | `...-windows-x64.zip` | Taşınabilir — aşağıdaki nota bak |
| macOS (Apple Silicon) | `...-macos-arm64.zip` | Aç, `.app`'i çalıştır |
| macOS (Intel) | `...-macos-x64.zip` | Aç, `.app`'i çalıştır |
| Linux x86_64 | `...-linux-x86_64.zip` | Aç, `.AppImage`'i çalıştır |

## Bilinmesi gerekenler

**Windows'ta ZIP yerine Setup.exe kullanın.** ZIP'ten çıkan dosyalara Windows
"internetten indirildi" damgası koyuyor ve uygulama açılmıyor. Mecburen ZIP
kullanacaksanız PowerShell'de:

```powershell
Get-ChildItem -LiteralPath 'DevreyeAlmaPaneli' -Recurse -File | Unblock-File
```

**Paketler imzasızdır.** Windows'ta SmartScreen uyarısı → *Daha fazla bilgi* →
*Yine de çalıştır*. macOS'ta uygulamaya sağ tık → *Aç*.

**Gereksinimler.** Windows 10 21H2+ / 11: Edge WebView2 Runtime (Setup.exe
kurar). macOS 11+: ilk açılışta yerel ağ izni sorulur, cihazlara ulaşmak için
gerekli. Linux: eksikse `sudo apt install libxcb-cursor0 libegl1 libgl1`.
Compartment LCD okuması ve yazılım yüklemesi için sistemde `adb` gerekir;
yoksa o cihazlar "uygulanmıyor" görünür.

**Doğrulama.** `SHA256SUMS.txt` eklidir:
`shasum -a 256 -c SHA256SUMS.txt` (macOS) · `sha256sum -c SHA256SUMS.txt` (Linux)

---

Sürümlerde ne değiştiği: **[docs/DEGISIKLIKLER.md](../../blob/main/docs/DEGISIKLIKLER.md)**
