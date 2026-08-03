Taşınabilir (portable) yapılar — **imzasız**.

| Platform | Dosya | Çalıştırma |
|---|---|---|
| Windows x64 | `...-windows-x64.zip` | Klasörü açın, `SwitchYonetimPaneli.exe` |
| Linux x86_64 | `...-linux-x86_64.AppImage` | `chmod +x` sonra çalıştırın |
| macOS Apple Silicon | `...-macos-arm64.zip` | Açın, `.app`'i çalıştırın |
| macOS Intel | `...-macos-x64.zip` | Açın, `.app`'i çalıştırın |

Bütünlük doğrulaması için `SHA256SUMS.txt` eklidir.

**Gereksinimler ve uyarılar**

- Windows: Microsoft Edge **WebView2 Runtime** gerekir (Windows 10 21H2+ ile
  birlikte gelir). Eksikse uygulama bunu açılışta bildirir.
- macOS: ilk açılışta **yerel ağ erişimi** izni sorulur; switch'leri bulmak
  için gereklidir.
- Paketler imzasız olduğu için Windows SmartScreen ve macOS Gatekeeper uyarı
  gösterebilir. Ayrıntılar: `Interface/Switch Yönetim Paneli/BUILD_RELEASE.md`
