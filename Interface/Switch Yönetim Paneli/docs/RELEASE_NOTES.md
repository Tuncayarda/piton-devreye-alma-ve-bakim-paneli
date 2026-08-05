## Bu sürümde (v1.0.3)

**Tarama**

- Tarama sürerken "Tara" düğmesi **İptal**'e dönüşüyor; basınca tarama hem
  arayüzde hem sunucu tarafında gerçekten duruyor ve hemen yeni bir tarama
  başlatılabiliyor. Yanlış ağ aralığı yazıldığında beklemek gerekmiyor.
- Sağ listenin başlığı "Bulunan switchler" yerine **Kullanılabilir
  switchler**.

**İşlem geçmişi**

- Toplu gönderimde artık "3 değişiklik uygulandı" değil, **yapılan her
  değişiklik tek tek** yazılıyor ("Port 26 kapatıldı", "Port 3 gücü
  kesildi"…).
- Büyük harfe çevirme Türkçe kuralına takıldığı için "KAYİT" görünen etiket
  düzeltildi: **KAYIT**.
- Alt bardaki son işlem satırında saniye gösterilmiyor (saat:dakika yeter);
  saniye ayrıntısı işlem geçmişi listesinde duruyor.

**Ön panel gösterim kılavuzu (yeni)**

- Renk açıklamalarının sağına bir **bilgi düğmesi** eklendi. Tıklayınca
  açılan pencerede, bir portun alabileceği **her görünüm tek tek örnekle**
  anlatılıyor: cihazı besliyor, bağlı ama güç çekmiyor, bağlı ama PoE
  kapalı, boş, boş + PoE kapalı, port kapalı, bekleyen değişiklik — ve
  uplink portları için ayrı liste.
- Örnekler haritadaki konnektörlerle **aynı koddan** çiziliyor, dolayısıyla
  kılavuz gerçek görüntüden hiçbir zaman ayrı düşmez.
- Simge yazı tipi karakteri değil, geometriden çizili SVG: Windows, macOS
  ve Linux pencere motorlarında aynı görünür.

**Portlar sekmesi**

- Sekme adı "Portlar & PoE" yerine **Portlar**.
- Sayaç satırı ("24 port · 5 bağlı…") noktalarla ayrılmış tek satır olmaktan
  çıktı; her sayaç kendi **dikdörtgen bölmesinde**.
- Sayacın önüne **"Son güncelleme:"** açıklaması eklendi.
- Toplu modda duraklatma göstergesi: yazı tipine göre uzayıp halkanın dışına
  taşan "‖" karakteri yerine **sabit ölçülü çizim**.
- PoE ve uplink tablolarında **Hız sütunları hizalandı**; gigabit uplinkler
  artık sağa kaymış görünmüyor.

**Toplu gönderim**

- Onay penceresi **gönderilecek tüm değişiklikleri madde madde** listeliyor.
  Önceden yalnızca riskli olanlar yazılıyor, geri kalanı görülmeden
  gidiyordu.
- Şerit üzerindeki bilgilendirme metni ve noktalama düzeltildi.

**Diğer**

- **Kaydet** düğmesi: kaydedilecek bir şey yokken içi boş, kaydedilmemiş
  değişiklik varken **yeşil** (turuncu "uyarı" rengi yerine).
- Onay pencerelerine sağ üstte **kapatma çarpısı** eklendi.
- Ön panelde sağ tık menüsünde, işaretli satırın yanındaki gereksiz
  "geçerli" yazısı kaldırıldı; "Portu aç / Portu kapat" satırları durum
  adı olarak **"Port açık" / "Port kapalı"** oldu.
- Switch künyesindeki model / IP / sürüm bilgileri **/** ile ayrılıyor.
- Logonun yanındaki başlıkta "SWİTCH" yazan yerler **SWITCH** olarak
  düzeltildi.

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
