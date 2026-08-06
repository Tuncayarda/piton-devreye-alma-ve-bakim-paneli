## Bu sürümde (dap-v0.9.0-dev)

İlk yayınlanan sürüm. **Ön sürüm (dev)**: sahada denenmesi için çıkarıldı,
kararlı sayılmaz.

**Ne yapar**

- Tren setinin tamamını tek DeviceMap'ten okur: switch, anons ekipmanları
  (Amplifier / Handset / Intercom / UIC), kamera ve NVR, ekranlar ve LED,
  PISCU / HMI / ICU.
- Her cihaz için hangi yöntemin kullanıldığını açıkça gösterir (KYLAND HTTP,
  ISAPI, `/api/v1`, ADB, MQTT). Okunamayan alan boş kalır — varsayılan bir
  değer uydurulmaz.
- Kontrol listesi ekranı, Excel çıktısının birebir ön izlemesidir; sütunlar
  şablon dosyasından okunur.

**Konfigürasyon**

- Anons cihazlarının **bütün yazılabilir ayarları** panelden yapılır: SIP
  (PBX IP, dahili no, dış arama, çalma süresi), ses seviyeleri ve gain'ler,
  günlük seviyesi, Handset çalışma modları (PTT, cevaplama, arama, kapatma),
  UIC TC/TL gain'leri, gerilim eşikleri ve çağrı yönlendirme hedefleri.
- Alanlar cihaz tipine göre listelenir ve her ayar cihazın kendi kabul ettiği
  uca gönderilir. Ana ayar ucu yazmaya kapalı olduğu için ses, mod, UIC gain
  ve SIP ayrı uçlara gider.
- **Yalnız cihazdakinden farklı olan alan yazılır.** SIP yazımı cihazı
  yeniden başlattığı için, zaten uyuşan bir ayar uğruna cihaz karartılmaz.
- Yazımdan sonra ayarlar tekrar okunup doğrulanır: HTTP 200 tek başına
  başarı sayılmaz, cihaz tanımadığı alanı sessizce yok sayabiliyor.
- Hedef değerler DeviceMap'ten gelir ve kutularda hazır durur; kullanıcı
  dokunmazsa cihaza yazılan da o değerdir. Girilen değerler kaydedilir,
  uygulama açılışında geri yüklenir.

**IP atama**

- Switch ön panelinden port seçilir, PoE ile cihazlar sırayla açılıp adres
  yazılır. Koşu iptal edilebilir; iptal edilse de PoE portları geri açılır.

**Kimlik ve gizlilik**

- Kullanıcı adı / parola **hiçbir dosyaya yazılmaz**, yalnız oturum boyunca
  bellekte durur. SIP parolası da kaydedilmez.
- Servis yalnız `127.0.0.1` dinler. Arayüz hiçbir zaman bir IP göndererek
  hedef seçemez; hedef her zaman DeviceMap'ten cihaz kimliğiyle bulunur.

**Bilinen sınırlar**

- Paketler **imzasızdır**. Windows'ta SmartScreen, macOS'ta Gatekeeper
  uyarısı çıkar (kurulum belgesindeki adımlar).
- Compartment LCD okuması `adb` gerektirir; sistemde yoksa o cihazlar
  "uygulanmıyor" olarak görünür.
- Cihaz seri numarası anons cihazlarında bulunmuyor; o sütun boş kalır.
