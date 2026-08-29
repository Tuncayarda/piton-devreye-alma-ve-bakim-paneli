Tren setindeki switch, anons, video, ekran ve kontrol sistemlerini doğrulayan;
desteklenen cihazlara IP adresi atayıp yapılandırmalarını yürüten masaüstü
uygulaması. Arayüz Türkçe ve İngilizce.

Bu sayfa **tek bir müşteri paketinin** sürümüdür; hangisi olduğu başlıkta
yazar. Farklı paketler aynı bilgisayara yan yana kurulabilir.

## İndirme

| Sistem | Dosya |
|---|---|
| **Windows x64** | `dabp-<paket>-<sürüm>-windows-x64-Setup.exe` — **önerilen** |
| Windows x64 (taşınabilir) | `dabp-<paket>-<sürüm>-windows-x64.zip` |
| macOS (Apple Silicon) | `dabp-<paket>-<sürüm>-macos-arm64.zip` |
| macOS (Intel) | `dabp-<paket>-<sürüm>-macos-x64.zip` |
| Linux x86_64 | `dabp-<paket>-<sürüm>-linux-x86_64.zip` (AppImage) |

`-dev`, `-alpha`, `-beta`, `-rc` ekli paketler saha denemesi içindir.

## Kurulum notları

Paketler **kod imzası taşımaz**; işletim sistemi uyarısı beklenen bir
durumdur.

- **Windows** (10 21H2+ / 11): SmartScreen uyarısında *Daha fazla bilgi →
  Yine de çalıştır*. Taşınabilir ZIP açılmıyorsa güvenlik işaretini kaldırın:
  `Get-ChildItem -LiteralPath '.\dabp-<paket>' -Recurse -File | Unblock-File`
- **macOS** (11+): Finder'da uygulamaya sağ tıklayıp *Aç*. İlk açılışta
  istenen yerel ağ izni saha cihazlarına erişmek için gereklidir.
- **Linux**: `sudo apt install libxcb-cursor0 libegl1 libgl1 zenity` ve
  gerekirse `chmod +x dabp-*-linux-x86_64.AppImage`.

## Dosya doğrulama

`SHA256SUMS.txt` bu sayfadaki bütün paketlerin özetlerini içerir
(`sha256sum -c SHA256SUMS.txt`, Windows'ta `Get-FileHash`). Özet
eşleşmiyorsa paketi çalıştırmayın.

---

Kurulum ve kullanım ayrıntıları için **Kullanıcı Kılavuzu**, sürüm geçmişi
için **[değişiklik günlüğü](https://github.com/Tuncayarda/piton-devreye-alma-ve-bakim-paneli/blob/main/docs/DEGISIKLIKLER.md)**.
