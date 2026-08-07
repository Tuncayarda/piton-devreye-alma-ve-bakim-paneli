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
- **SIP parolası dahili numaranın aynısıdır.** DeviceMap'te `PBXPassword`
  yazmayan cihazlarda (Amplifier, UIC) parola bulunamıyordu; SIP ucu onu
  zorunlu istediği için o cihazlarda dahili numara da yazılamıyordu.
  Projede açıkça yazılmış bir parola varsa yine o kullanılır.

**IP atama**

- Switch ön panelinden port seçilir, PoE ile cihazlar sırayla açılıp adres
  yazılır. Koşu iptal edilebilir; iptal edilse de PoE portları geri açılır.
- **Fabrika IP'si sete göre değişmez**: yapılandırılmamış cihaz hangi
  sette çalışacağını bilmeden hep aynı adresle (10.1.1.12) geliyor.
  Önceden şablon set numarasıyla çözülüyordu ve set 8'de cihaz
  10.8.1.12'de aranıp bulunamıyordu. Alan yine ekrandan değiştirilebilir.
  Koşu ikisini de dener: sabit adres ve setin kendi 10.n.1.12'si — daha
  önce atanmış cihazlar hâlâ orada olabiliyor.
- Fabrika adresinde bulunamayan cihazlar için ağ + maske yerine **açık
  adres aralığı** da verilebilir (10.1.1.10 – 10.1.1.60 gibi). Ağ maskesi
  geniş olduğunda aranacak yeri daraltmanın yolu budur; her iki yolda da
  en fazla 512 adres denenir.

**Yazılım yükleme**

- Dosya **cihaz başına** seçilir: her satırın kendi dosyası ve hedef
  sürümü var. Bir cihaz farklı bir revizyondan olduğunda grubun geri
  kalanıyla aynı dosyayı almak zorunda değil.
- Dosya, satırdaki **"Seç"** düğmesiyle bilgisayarın kendi dosya
  penceresinden seçilir; yol elle yazılmaz.
- Hepsine aynı dosya gidecekse üstteki düğme tek seçimle bütün gruba yazar.
- Dosyası seçilmemiş cihaz kuyruğa hiç girmez; yol girildiği anda
  doğrulanır (var mı, boş mu, 32 MB sınırı).
- Yükleme sonrası sürüm tekrar okunur. "İstek kabul edildi" tek başına
  başarı sayılmaz; hedef sürüm girilmişse cihazın bildirdiği sürümle
  karşılaştırılır. Kuyruk satırında hangi dosyanın gittiği yazar.
- **Anons ekipmanları** imaj (.bin) alır; istek cihazın kendi arayüzüyle
  birebir aynı: `POST /api/v1/system/firmware`.
- **Compartment LCD** uygulama paketi (.apk) alır: `adb install -r` ile
  kurulur, sürüm `dumpsys package` ile doğrulanır. Cihazdaki sürüm daha
  yeniyse düşürme bir kez `-d` ile denenir; `adb` hata kodları
  anlaşılır mesaja çevrilir.
- Dosya seçicinin süzgeci cihaza göre: APK bekleyen cihaza .bin
  seçtirilmez.
- **Yükleme paralel yürür**: aynı anda en fazla 4 cihaz (ayarlanabilir:
  `FIRMWARE_WORKER`). 12 cihazlık bir sette bekleme süreleri artık uç uca
  eklenmiyor.

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
