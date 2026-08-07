# Devreye Alma Paneli — Mimari ve Çalıştırma

Yataklı tren setlerinin sahada devreye alınması için masaüstü paneli.
DeviceMap topolojisini yükler, cihazları okur, kimlik isteyen cihazları
kilit menüsünde toplar ve kontrol listesini Excel'e döker.

---

## 1. Çalıştırma

```bash
cd "Interface/Devreye Alma Paneli"
python3 -m venv .venv
.venv/bin/python -m pip install -r docs/requirements.txt
.venv/bin/python app.py
```

Tek komutla açılış: `python3 app.py`

| Komut | Ne yapar |
|---|---|
| `python3 app.py` | Masaüstü penceresini açar (pywebview) |
| `python3 app.py --tarayici` | Pencere yerine varsayılan tarayıcıda açar |
| `python3 app.py --admin-parolasi ****` | Admin ekranını şifreye bağlar (hiçbir yere yazılmaz) |
| `python3 app.py --self-test` | Pencere açmadan paketi doğrular; ağa çıkmaz |
| `python3 panel_api.py --port 8790` | Yalnız API (hata ayıklama) |
| `python3 -m unittest discover -s tests -t .` | Bütün testler |

Admin şifresi verilmezse admin ekranı şifresiz açılır. Şifre yalnız
bellekte tutulur, `secrets.compare_digest` ile karşılaştırılır.

---

## 2. Katmanlar

```
app.py            pywebview penceresi + yerel servisin ömrü
panel_api.py      ThreadingHTTPServer, REST uçları, iş gövdeleri
core/
  ayar.py         sabitler, yollar, portlar, süreler
  betik.py        kardeş projelerdeki çalışan betikleri içe aktarma
  device_map.py   DeviceMap envanteri, IP şablonu çözümü, güvenli DTO
  kategori.py     kategoriler, işlem grupları, yöntem eşlemesi
  kimlik.py       RAM kimlik deposu (kalıcı depo YOK)
  hata.py         cihaz hatalarının sınıflandırılması
  dogrulama.py    yeşil/turuncu/kırmızı/gri kararı, nesil damgası
  okuma.py        okuma dağıtıcısı + Announcement/ADB okuyucuları
  switch_okuma.py KYLAND — Switch Yönetim Paneli'nin kodunu kullanır
  video_okuma.py  Kamera/NVR — ISAPI, digest auth
  piscu.py        MQTT telemetri + canlı dinleyici
  isler.py        FIFO iş kuyruğu + tarama görünümü
  ip_atama.py     IP atama planı ve koşusu
  konfig.py       konfigürasyon oku/yaz
  firmware.py     yazılım yükleme (anons: HTTP imaj, LCD: adb APK)
  excel.py        kontrol listesi Excel çıktısı
  kontrol.py      Excel şablonunun ekran önizlemesi
static/           index.html + css/ + js/ (vanilla ES modules, build yok)
tests/            unittest paketi + sahte cihazlar
```

Arayüz tarafında Node.js, paketleyici ya da derleme adımı yoktur;
`static/js` doğrudan tarayıcıya ES module olarak servis edilir.

---

## 3. Çalışan kodu yeniden yazmama

Panel üç betiği **çalışma anında içe aktarır** (`core/betik.py`), kopyalamaz:

| Betik | Ne için |
|---|---|
| `Interface/Switch Yönetim Paneli/switch_api.py` | Switch erişiminin tamamı |
| `YATAKLI_DevreyeAlma/device_verify.py` | Excel şeması ve alan tabloları |
| `YATAKLI_DevreyeAlma/intercom_ip_assign.py` | IP atama koşusu |

Switch okuması `switch_api.sw_get(ip, "stat/basicInfo", kimlik=(k, p))`
çağrısına iner. URL, Basic Auth biçimi, port, timeout, header ve
"JSON gelmiyorsa oturum açılması gerekiyor" kuralı iki panelde birebir
aynıdır — bu yüzden Switch Yönetim Paneli'nde çalışan hesap burada da
çalışır. `tests/test_switch.py::test_1` bunu iddia etmekle kalmaz, aynı
sahte switch'e iki panelin yolundan sorup sonuçları karşılaştırır.

`kimlik` her çağrıda açıkça verilir; verildiği sürece `switch_api` kendi
modül içi kimlik deposuna hiç bakmaz.

---

## 4. Kimlik bilgileri — kritik akış

**Kural: kullanıcı adı ve parola yalnızca çalışan Python sürecinin
belleğinde durur.**

Bilerek bulunmayanlar: `.env`, JSON, SQLite, keychain, `localStorage`,
`sessionStorage`, çerez, log satırı, exception mesajı, iş kuyruğu satırı,
API yanıtı.

### Akış

```
Tam tarama
   └─ cihaz 401/403 döndürür ya da JSON yerine oturum sayfası verir
        └─ durum: TURUNCU (kimlik_bekliyor)
             └─ üst bardaki kilit kutucuğuna düşer, rozet artar
                  └─ kullanıcı cihaza tıklar → modal
                       └─ POST /api/kimlik  {cihazId, kullanici, parola}
                            ├─ cihazdan DOĞRULANMIŞ veri geldi
                            │    ├─ kimlik RAM'e yazılır
                            │    ├─ sonuç görünüme yazılır → YEŞİL
                            │    ├─ kilit listesinden çıkar
                            │    ├─ sayaçlar aynı yanıtta güncellenir
                            │    └─ hafif yenileme listesine girer
                            └─ doğrulanamadı
                                 ├─ RAM'deki ÖNCEKİ çalışan kimlik EZİLMEZ
                                 ├─ cihaz zaten yeşilse yeşil kalır
                                 └─ hata tipine göre ayrı mesaj
```

Doğrulama kararını sunucu verir. Formun doldurulmuş olması doğruluk
sayılmaz; cihazdan beklenen veri gelmelidir.

### Hata mesajları ayrıdır

| Durum | Mesaj | Renk |
|---|---|---|
| 401/403 ya da oturum sayfası | "Kullanıcı adı veya parola doğrulanamadı" | turuncu |
| Timeout / bağlantı reddi | "Cihaz zaman aşımına uğradı" / "Cihaza ulaşılamadı" | kırmızı |
| 200 ama beklenmeyen gövde | "Cihaz yanıtı doğrulanamadı" | kırmızı |
| Yöntem tanımlı değil | "Bu cihazda uygulanmıyor" | gri |

Parola hiçbir hata mesajına eklenmez.

### Kimlik grubu

Varsayılan davranış yalnız seçilen cihazı doğrulamaktır. Kullanıcı modalde
"aynı hesabı grupta kullan" derse kimlik `switch` / `video` grubu altına
da yazılır ve o gruptaki diğer cihazlar için kullanılır.

### Kapanış

`panel_api.temizle()` — pencere kapanınca `app.py`'nin `finally` bloğundan
çağrılır: iş kuyruğu durdurulur, MQTT dinleyicisi kapatılır, konfigürasyon
hedefleri ve firmware seçimi silinir, **bütün kimlikler unutulur**. Yeni
açılışta şifre isteyen her cihaz için bilgi yeniden istenir.

---

## 5. Cihaz durumları

| Renk | Anlamı |
|---|---|
| **Yeşil** | Cihaza bağlanıldı ve beklenen/doğrulanabilir veri alındı |
| **Turuncu** | Cihaz erişilebilir ama kullanıcı adı/parola gerekiyor |
| **Kırmızı** | Timeout, bağlantı reddi, ağ hatası ya da doğrulanamayan yanıt |
| **Gri** | Bu cihazda yöntem uygulanmıyor ya da henüz okunmadı |

Gri'nin iki alt hali ayrı tutulur: `okunmadi` ve `uygulanmiyor`. Ekranda
"—" okunmadı demektir; "N/A" o cihaz türünde geçersiz alan demektir.
Okunmamış hiçbir alan için varsayılan değer uydurulmaz.

### Okuma yöntemleri

| Tip | Yöntem | Uç | Kimlik |
|---|---|---|---|
| Switch | KYLAND | `/stat/basicInfo` | Basic (gerekli) |
| Camera, NVR | ISAPI | `/ISAPI/System/deviceInfo` | Digest (gerekli) |
| Announcement | HTTP | `/api/v1/system/settings` | yok |
| PISCU, HMI | MQTT | `ALFA/AppStatus/#` | yok |
| LCD/Compartment | ADB | `getprop` · `dumpsys` · `logcat` (5555) | yok |
| Diğerleri | MQTT | `ALFA/DeviceMap` (retained) | yok |

MQTT broker'a ulaşılamazsa ilgili cihazlar **gri** kalır ve sebebi yazılır —
"hatalı" gösterilmez, uydurma veri üretilmez.

Bazı alanlar tek kaynaktan gelmiyor; okuyucu ikisini birleştirir:

- **Switch çalışma süresi** cihazın `operateTime` alanından (gün/saat/dakika/
  saniye) hesaplanır; cihaz vermezse DeviceMap `Status.Uptime` kullanılır.
- **PISCU / HMI çalışma süresi** AppStatus yükünde yoktur, aynı cihazın
  DeviceMap kaydından alınır. Kapalı cihazın `-1` değeri süre sayılmaz.
- **DeviceMap adresleri şablondur** (`10.n.1.4`). Telemetri kayıtları hem
  şablon hem çözülmüş adresle indekslenir; yoksa hiçbir arama tutmaz.
- **Gain, ses seviyesinden ayrı** bir alandır (`speakerGain` / `micGain`);
  seviye araması `gain` içeren adları eler. `SIP Arama No` cihazın aradığı
  hedeftir (`pbxOutExtension`), kendi dahilisi değil.
- **Compartment LCD'nin SIP dahili numarası ve PBX adresi** cihaz günlüğüne
  yalnız uygulama açılışında yazıldığı için çoğu zaman tamponda yoktur.
  Dahili numara broker'daki `ALFA/SipPort/<ip>` duyurusundan, PBX adresi
  ise (cihaz "registered" derken) setin PISCU'sundan tamamlanır. Değerin
  hangi kaynaktan geldiği cihaz detayında yazılır — cihazdan okunmamış bir
  değer okunmuş gibi gösterilmez.

Kontrol listesi kendi ucundan (`/api/kontrol`) besleniyor; cihaz verisi
değiştiğinde ekran açıksa yeniden çekilir (en fazla 1,5 saniyede bir ve
yalnız sonuçlar gerçekten değiştiyse). Yoksa tarama sürerken ekranda eski
satırlar kalıyordu.

---

## 6. Tarama ve iş kuyruğu

Açılışta **hiçbir cihaza bağlanılmaz**; yalnız yerel DeviceMap yüklenir.
Önceki oturumdan kimlik yüklenmez.

"Güncelle" → `POST /api/tarama` → FIFO kuyruğa iş eklenir.

- İş satırları **tarama başlamadan önce** kurulur; kullanıcı ilk saniyeden
  ne yapıldığını görür.
- Aynı tren setinin bekleyen/çalışan taraması varsa yeni iş açılmaz;
  mevcut iş `HTTP 202` ile döner. Hızlı çift tıklama ikinci iş üretmez.
- İptal her cihazdan **önce** denetlenir; sıradaki cihazlara hiç
  dokunulmaz. Çalışmakta olan tek istek kendi zaman aşımı kadar sürer.
- Worker hatası (`is.hata`) ile cihaz bağlantı hatası (satır durumu) ayrı
  alanlardır.
- Sonuçta başarılı / erişim bekleyen / hatalı sayıları ayrı gösterilir.

### İş ile görünüm ayrımı

```
Is         → ne yapıldığının kaydı. Biter, kuyrukta durur, silinir.
Gorunum    → cihazların o anki durumu. İşten bağımsızdır.
```

Kuyruk geçmişindeki eski bir iş sonucu yeni tarama görüntüsünü ezemez.

### Nesil damgası

Her okuma, gönderilmeden önce artan bir sayaçtan `nesil` alır.
`Gorunum.yaz()` daha eski nesilli bir sonucu **yazmaz**. Kullanıcı şifre
girip cihazı yeşile çevirdikten sonra hâlâ yolda olan tarama cevabı geri
döndüğünde onu turuncuya çeviremez. Karşılaştırma saat değil sayaç
üzerinden yapılır — saat geri alınabilir, sayaç alınamaz.

---

## 7. Hafif yenileme

- Yalnız **doğrulanmış (yeşil)** cihazlar yenilenir.
- `setInterval` **kullanılmaz**: her tur, bir önceki istek bittikten sonra
  `setTimeout` ile kurulur (~5 sn). Aynı cihaz için istek birikmez.
- Tam tarama sürerken hafif yenileme çalışmaz; sunucu `409` döner.
- "Duraklat" yalnız yeni turları durdurur; süren istek düzgün tamamlanır.
- Tur başına en fazla `HAFIF_SINIR` (64) cihaz okunur.
- Cihaz cevap vermeyi bırakırsa kırmızıya döner ve yeşil olmadığı için
  bir sonraki turda listeden düşer.

---

## 8. API güvenliği

- Yalnız `127.0.0.1` dinlenir; `panel_api.sunucu()` başka bir arayüz
  isteğini reddeder. CORS başlığı gönderilmez.
- **İstemci hedef seçemez.** Gövdeye `ip` ya da `type` koymak hiçbir şeyi
  değiştirmez; hedef her zaman DeviceMap'ten `cihazId` ile bulunur.
- Tren seti `1..16` aralığına zorlanır (şablondaki `n` doğrudan IP'nin
  ikinci oktetine gider).
- POST gövdesi tip ve boyut denetiminden geçer (üst sınır 64 KB).
- Statik dosya servisi `resolve()` sonrası `static/` kökü altında olmayan
  her yolu reddeder.
- Hiçbir yanıtta parola ya da `Authorization` başlığı bulunmaz.
- Ham yığın izi yalnız sunucunun kendi hata çıktısına gider; kullanıcı
  "Panelde beklenmeyen bir sorun oluştu" görür.

---

## 9. Ekranlar

| Ekran | İçerik |
|---|---|
| Rol seçimi | Kullanıcı / Admin (şifre yalnız tanımlıysa sorulur) |
| Genel Bakış | KPI'lar, kategori durumu, sistem özeti, son işlemler |
| Tüm Cihazlar | Kategori + durum filtresi; cihazın son bilinen durumu |
| Cihaz detayı | Kimlik / Ağ / SIP blokları, kimlik gir, kimliği unut |
| **Kontrol Listesi** | Çıktının ön izlemesi (şablonun tüm sütunları) + kategori filtresi |
| IP Atama | DeviceMap'ten çıkan plan, ön panel, dry-run |
| Konfigürasyon | Cihazdaki değer ↔ hedef değer karşılaştırması |
| Yazılım Yükleme | Cihaz başına dosya seçimi (.bin / .apk), hedef sürüm, gruba toplu atama |
| PISCU & PBX | MQTT istemcileri, SIP dahili numaraları |
| MQTT İzleme | Canlı akış (kullanıcı başlatır, tampon sınırlı) |
| Proje & Cihaz Listesi | DeviceMap, tren seti, kategori tanımı (admin) |
| İşlem Kuyruğu | Sağdan açılan panel, canlı satırlar, iptal |
| Kilit menüsü | Kimlik bekleyen cihazlar, rozet sayacı |

Sol menüdeki sıra ekranda göründüğü gibidir: **Kontrol Listesi işlemlerin
en üstündedir**, çünkü sahada en sık açılan ekran odur.

### Cihaz kategorileri

Menüde yalnız kategori başlıkları listelenir (Anons Ekipmanları, Video
Sistemi, …); alt tiplere inilmez. İki kademe derinlik sahada okunurluğu
düşürüyordu — alt tip kırılımı gerekince cihaz listesindeki durum filtresi
kullanılır.

### Kontrol Listesi = çıktının ön izlemesi

Amaç, Excel'e yazılacak bilginin önceden görülebilmesi. Tablo panelin
standart tablo biçimindedir; şablonun **bütün sütunları** vardır ve
sütun adları ile gri (N/A) hücreler `core/kontrol.py` tarafından
doğrudan şablon dosyasından okunur. Kodda ayrı bir kolon listesi
tutulmaz: şablon değişince liste de değişir. `core/excel.py` aynı
eşlemeyi kullandığı için ekranda görünen değer ile dosyaya yazılan değer
aynıdır — bir test bunu doğrudan karşılaştırır.

Üstteki kategori şeridi listeyi filtreler: yalnız seçilen kategorideki
cihazlar gösterilir. 23 sütun sığmadığı için tablo kendi içinde yatay
kayar; sayfa gövdesi kaymaz.

### Konfigürasyon = DeviceMap hedefi ↔ cihazdaki değer

Ekran her alan için iki değeri yan yana gösterir: cihazdan okunan ve
yazılacak hedef. Hedefin sırası **cihaza özel > gruba girilen > DeviceMap**.
Kutular hedef değerle **hazır gelir**; kullanıcı hiçbir şeye dokunmazsa
"Gruba Uygula" DeviceMap'teki konfigürasyonu yazar. Devralınan değer
kutuda soluk/italik durur, girilen değerden ayırt edilir.

DeviceMap'te bir ayarın anahtarı **cihazın kendi alan adıdır** (büyük/küçük
harf önemsiz): `SpeakerVolume`, `MicGain`, `LogLevel`, `PBXExtension`,
`Target1`, `TcHigh`… Panel ayrıca bir eşleme tablosu tutmaz. Üç düzey
birleşir, sonraki öncekini ezer:

```json
{
  "Config": {
    "Announcement":         { "LogLevel": 1 },
    "Announcement/Handset": { "SpeakerVolume": 80, "AnswerMode": 1 }
  },
  "Switches": [
    { "Devices": [
      { "Type": "Announcement", "SubType": "Handset",
        "PBXExtension": "3001", "SpeakerVolume": 70 }
    ]}
  ]
}
```

- Geçersiz proje değeri (aralık dışı, tanımsız seçim) hedef sayılmaz ve
  cihaza yazılmaz; satırda `DeviceMap ✕` olarak sebebiyle görünür. Hatalı
  proje verisini cihaza yazmak, yanlış ayarı kalıcı hâle getirmek olurdu.
- Gruba yazılacak değer kutusu, o ayar gruptaki bütün cihazlarda aynıysa
  dolu gelir. Cihaza göre değişen alanda (dahili numara) bilerek boş kalır:
  tek numara gösterip kullanıcının bir harf değiştirmesi bütün gruba aynı
  numarayı yazdırırdı.
- Alan listesi **cihaz tipine göre** daralır; hangi alanın hangi uca
  gittiği `core/konfig.py` → `ROTA` tablosundadır (ayrıntı:
  `YATAKLI_DevreyeAlma/CIHAZ_ENDPOINTLERI.md`). Cihaz tek bir "ayarları
  yaz" ucu sunmuyor; ana uç POST'a 405 döner.
- **Yalnız farklı olan alan yazılır.** SIP ucu cihazı yeniden başlattığı
  için, zaten uyuşan bir ayar uğruna cihaz karartılmaz; iş satırı bu
  durumda "Ayarlar zaten uyuşuyor — yazılmadı" der.
- Yazımdan sonra ayarlar tekrar okunur. HTTP 200 başarı sayılmaz: cihaz
  tanımadığı alanı hata vermeden yok sayabiliyor.
- SIP parolası girilebilir ama **hiçbir yanıtta geri dönmez**; satırda
  yalnız uyuşup uyuşmadığı ve kaynağı görünür. Bu değer cihazın SIP kaydı
  içindir, panelin cihaza bağlanma kimliği değildir (bkz. bölüm 4).
  Parola `Config` bloğuna YAZILMAZ — projede önerilen ya da fabrika
  parolası diye bir şey yok. Kaynak sırası: ekrandan girilen değer >
  DeviceMap'teki `PBXPassword` (Intercom, Handset) > **dahili numaranın
  kendisi**. Son adım sahadaki kuraldır: anons ekipmanlarının SIP
  parolası dahili numarasıyla aynı. `PBXPassword` yazmayan cihazlarda
  (Amplifier, UIC) parola hiç bulunamıyor, SIP ucu onu zorunlu istediği
  için o cihazlarda dahili numara da yazılamıyordu. Numara ekrandan
  değişirse parola da onunla birlikte değişir.
- Gizli alanı cihaz geri bildirmiyorsa (parolayı maskeleyen firmware)
  doğrulama o alanı atlar: okunamaması "cihaz yazmadı" demek değildir.
- Girilen değerler **kalıcıdır**: her değişiklikte kullanıcının veri
  dizinine (`ayar.veri_dizini()`, macOS'ta *Application Support*) yazılır ve
  `panel_api.sunucu()` açılışta geri yükler. Gizli alan (SIP parolası)
  dosyaya HİÇ girmez; bozuk dosya, tanınmayan alan ya da geçersiz değer
  sessizce atlanır — eski bir dosya yüzünden panel açılmaz olmamalı, cihaza
  da tanımsız değer gitmemeli. "Kayıtlı Değerleri Sıfırla" dosyayı siler,
  ekran DeviceMap değerlerine döner. Dosya proje ağacına ya da DeviceMap'in
  yanına yazılmaz (bir test bunu doğrular).
- Ekran **iki aşamalı** yüklenir: `/api/konfig/alanlar` cihaza hiç
  gitmez (alan listesi + hedefler + DeviceMap değerleri, ~5 ms), cihazdaki
  değerler arkadan `/api/konfig` ile gelir. Tek istek beklenirken grup
  değiştirmek saniyelerce eski grubun alanlarını gösteriyordu. Geciken
  yanıtın yeni seçimin üstüne yazmaması için her tazelemenin sıra numarası
  var. Konfigürasyon okuması ek uçlardan yalnız gerekeni ister (Handset'te
  `system/modes`, diğerlerinde hiç): olmayan altı ucu denemek okumayı
  gereksiz uzatıyordu.
- Salt okunur **SIP Kaydı** satırı cihazın `status` alanıdır. Dahili
  numara/parola yazıldıktan sonra bakılacak yer burasıdır: cihaz ayarı
  kabul etmiş olabilir ama PBX'e kaydolmamış olabilir; yazma doğrulaması
  yalnız alanın oturduğunu söyler, kaydın tuttuğunu söylemez.

### Tren seti değiştirme

Üst bardaki `SET n` bir açılır listedir ve **rolden bağımsızdır**: saha
kullanıcısı da set atlayabilir. Set değişince cihaz listesi, IP planı,
kontrol listesi ve çıktı dosyası adı yeniden hesaplanır; görünüm set
başına tutulduğu için eski setin sonuçları taşınmaz. Tarama sürerken
seçici kilitlenir.

### Yazılım yükleme = cihaz başına dosya

Dosya **her cihaz için ayrı** seçilir (`core/firmware.py`, cihaz kimliğine
göre bir sözlük). Sahada bir intercom farklı bir donanım revizyonundan
olabiliyor ve grubun geri kalanıyla aynı .bin'i almıyor; tek bir "seçili
dosya" tutulduğunda bu görünmüyor, yanlış imaj sessizce gidiyordu.

**İki cihaz ailesi, iki yol:**

| Aile | Dosya | Yol | Doğrulama |
|---|---|---|---|
| Anons (Intercom, Handset, Amplifier, UIC) | `.bin` | HTTP multipart | cihaz yeniden başlar, `/api/v1/system/settings` sürümü okunur |
| Compartment LCD | `.apk` | `adb install -r` | `dumpsys package` → `okuma.paket_bilgisi` |

Beklenen uzantı `firmware.UZANTI` tablosundan gelir; dosya seçicinin
süzgeci ve ekrandaki yardım metni oradan beslenir. APK bekleyen cihaza
.bin seçtirmenin anlamı yok, karışık seçim de tek dosyayla karşılanamaz
(uç 400 döner).

APK tarafının ayrıntıları:

- Kurulum cihazı yeniden başlatmaz, yalnız uygulama yeniden kurulur;
  bu yüzden "cihaz geri gelene kadar bekle" adımı yoktur.
- Cihazdaki sürüm yenisinden büyükse paket yöneticisi reddediyor. Sahada
  eski sürüme dönmek gerekebildiği için `INSTALL_FAILED_VERSION_DOWNGRADE`
  görülürse `-d` ile bir kez daha denenir (bayrak baştan gönderilmez:
  bazı cihazlarda düşürme kapalı ve komutun tamamı reddediliyor).
- `adb install` çıktısındaki bilinen hata kodları tek satırlık Türkçe
  mesaja çevrilir (`firmware._kurulum_hatasi`).
- Kurulum başarılı görünüp `com.piton.train_lcd_panel` sürümü
  okunamıyorsa iş başarısız sayılır: APK başka bir pakete ait olabilir.

**Koşu paraleldir.** Cihazlar birbirinden bağımsız (her biri kendi
dosyasını alıyor, kendi doğrulamasını bekliyor); sırayla yapmak bütün
bekleme sürelerini uç uca ekliyordu. Aynı anda `ayar.FIRMWARE_WORKER`
(varsayılan **4**) cihaz yüklenir — tarama kadar yüksek tutulmaz, çünkü
her yükleme bir cihazı karartıyor ve sahadaki kişinin neyin kapandığını
görmesi gerekiyor. İptal her cihazdan önce denetlenir; o an süren yazım
kesilmez (yarıda kesilen firmware cihazı kullanılamaz bırakır).

Dosya **işletim sisteminin kendi penceresinden** seçilir: tarayıcı sanal
alanı `<input type=file>` seçiminin gerçek yolunu vermiyor, panel de
imajı kopyalamıyor — yalnız yolunu tutuyor. Satırdaki "Seç" düğmesi
`POST /api/firmware/sec` çağırır; sunucu `core/dosya.sec` ile seçiciyi
açar (macOS `osascript`, Windows `OpenFileDialog`, Linux
`zenity`/`kdialog`), dönen yolu doğrular ve hedef cihazlara atar. İstek
kullanıcı pencereyi kapatana kadar sürer; vazgeçilirse eski seçim
korunur. Yol elle yazılmaz.

Olağan durum (bütün gruba aynı imaj) için ekranın üstünde tek bir düğme
var: aynı uç grup adıyla çağrılır ve dosya gruptaki her cihaza atanır.
Satırdaki "Değiştir" yalnız o cihazı etkiler, "×" seçimi kaldırır. Hedef
sürüm `POST /api/firmware/surum` ile dosyaya dokunmadan değişir.

`POST /api/firmware/dosya` (yolla doğrudan atama) arayüzde kullanılmaz;
penceresiz çalıştırma ve testler için durur.

İstek cihazın kendi arayüzünün gönderdiğiyle birebir aynıdır:
`POST /api/v1/system/firmware`, `multipart/form-data`, alan adı
`firmware`, parça türü `application/macbinary`. Uç adı "update" değil —
yanlış adrese giden yükleme cihazda HTTP 404 ile düşüyordu.

Kurallar:

- Yükleme yalnız yolu tanımlı cihazlarda var (anons ailesi ve
  Compartment LCD). Başka bir gruba dosya atanmaz — uç 400 döner.
- **Dosyası olmayan cihaz kuyruğa girmez.** Yükleme ucu yalnız seçimi
  olanları işe koyar; hiç yoksa iş hiç oluşmaz (400).
- Dosya yolu girildiği anda doğrulanır (var mı, boş mu, 32 MB sınırı) ve
  yükleme anında bir kez daha bakılır: seçimden sonra silinmiş olabilir.
- Seçim **yalnız bellektedir**; panel imajı kendi dizinine kopyalamaz,
  kapanışta seçim gider (bkz. `panel_api.temizle`).
- HTTP 200 başarı sayılmaz: cihaz yeniden başlar, sürümü tekrar okunur ve
  hedef sürüm girilmişse onunla karşılaştırılır. Kuyruk satırında hangi
  dosyanın gittiği yazar.

### Tarama sırasında canlı durum

Adım adım ilerleme **yalnız işlem kuyruğunda** gösterilir: çalışan iş
kartı ince mavi çerçeve alır, satırlar sırayla durum değiştirir. Cihaz
listesi her zaman cihazın son bilinen durumunu gösterir — iki yerde
birden ilerleme göstermek listeyi tarama süresince okunmaz hale
getiriyordu.

Kuyruk satırlarında cihaz adı, IP ve durum bulunur. Hata sebebi satıra
yazılmaz (kuyruğu okunmaz hale getiriyordu); ayrıntı satırın ipucu
metninde ve cihaz detayında durur.

Taramanın ilk saniyeleri MQTT telemetrisi toplamakla geçtiği için kuyruğa
bir ilerleme satırı düşülür ("Canlı MQTT telemetrisi"). Bu satır cihaz
sayaçlarına girmez — "42 cihazdan 7'si başarılı" derken araya bir ilerleme
satırı karışmamalı.

**Admin ekranında cihaz kullanıcı adı/parolası kaydedilemez.** Eski
panellerdeki "kimlik bilgilerini dosyaya kaydet", "parolayı sil",
"parola kayıtlı" alanları bilinçli olarak yoktur; tek yapılabilen,
bellekteki kimlikleri unutmaktır.

---

## 10. Arayüz kuralları

- Cihazdan gelen hiçbir değer `innerHTML` ile basılmaz. `core/dom.js`
  içindeki `el()` yalnız `textContent` üzerinden yazar; başka yol sunmaz.
  Bir cihazın adı `<img onerror=...>` olsa bile ekranda aynen o metin
  görünür, çalışmaz. `tests/test_arayuz.py` bunu kaynakta denetler.
- Parola global duruma (`durum.js`) yazılmaz: `ata()` bilinen anahtar
  listesi dışına yazmaz ve o listede parola anahtarı yoktur. Modaldaki
  değer doğrudan API çağrısına verilir, yanıt döner dönmez alan temizlenir.
- Temel tasarım 1440×900. Kenar çubuğu 1080 px altında üste biner ve
  açılır kapanır olur; geniş tablolar kendi içinde yatay kayar; sayfa
  gövdesi hiç yatay kaymaz.
- İkon düğmelerinin `aria-label`'ı vardır, diyaloglarda odak tuzağı ve
  Escape çalışır, kilit/kuyruk panelleri `aria-expanded` bildirir.

---

## 11. Testler

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

`tests/sahte.py` gerçek cihazların davranışını taklit eden test
sunucuları içerir (Basic Auth switch, oturum sayfası döndüren switch,
digest kamera, announcement cihazı, hiç cevap vermeyen cihaz). **Bunlar
test altyapısıdır; uygulama hiçbir koşulda sahte cihaz üretmez.**

| # | Gereksinim | Yer |
|---|---|---|
| 1 | Çalışan hesap iki panelde de doğrulanır | `test_switch.py` |
| 2 | Yanlış switch parolası başarı sayılmaz | `test_switch.py` |
| 3 | 200 dönen login HTML'i kabul edilmez | `test_switch.py` |
| 4 | 401/403 cihazı kilit listesine düşer | `test_kimlik.py` |
| 5 | Doğru bilgi → yeşil + kilitten çıkar | `test_kimlik.py` |
| 6 | Yanlış bilgi RAM kimliğini ezmez | `test_kimlik.py` |
| 7 | Kapanışta RAM deposu temizlenir | `test_kimlik.py` |
| 8 | Yeni süreçte önceki parolalar yok | `test_kimlik.py` |
| 9 | Hiçbir dosyaya parola yazılmaz | `test_guvenlik.py` |
| 10 | API ve kuyruk satırları parolasız | `test_guvenlik.py` |
| 11 | Aynı adlı farklı IP'li switch karışmaz | `test_switch.py` |
| 12 | Eski cevap yeni doğrulamayı ezmez | `test_kimlik.py` |
| 13 | Çift tıklama iki iş oluşturmaz | `test_kuyruk.py` |
| 14 | Aktif tarama varken ikincisi başlamaz | `test_kuyruk.py` |
| 15 | Kamera 401 kilit akışına girer | `test_kimlik.py` |
| 16 | Timeout ≠ yanlış parola | `test_kimlik.py` |
| 17 | İstemcinin IP'sine bağlanılmaz | `test_guvenlik.py` |
| 18 | İptal işi kontrollü sonlandırır | `test_kuyruk.py` |
| 19 | Frontend lint/syntax denetimi | `test_arayuz.py` |
| 20 | Hepsi tek komutla çalışır | yukarıdaki komut |

Ek olarak `tests/test_kontrol.py`: şablon iskeletinin dosyadan geldiğini,
N/A ile "okunmadı"nın ayrı kaldığını, önizleme ile Excel çıktısının aynı
değeri verdiğini ve tarama sırasındaki canlı işlem durumunu doğrular.

Test 19 `deno lint` + `deno check` kullanır. Deno kurulu değilse test
atlanır (`brew install deno`); Python söz dizimi denetimi her koşulda
çalışır.

---

## 12. Bilinen sınırlar

- **IP atama koşusu** `intercom_ip_assign.py`'yi süreç içinde çalıştırır.
  Betik kendi akışını sonuna kadar yürüttüğü için koşu **başladıktan
  sonra** iptal edilemez; iptal yalnız kuyrukta beklerken çalışır.
  Varsayılan dry-run'dır.
- **SIP kayıt durumu** Asterisk ARI hesabı tanımlı olmadığı için PBX'ten
  değil, cihazların kendi bildirdiği değerlerden gösterilir. Ekranda bu
  açıkça yazılır.
- **Compartment LCD** okuması `adb` komutunu gerektirir. Kurulu değilse
  cihazlar gri kalır ve sebebi yazılır. Cihaz yeşil sayılmak için yalnız
  adb'ye bağlanmakla kalmaz, `dumpsys package` çıktısından panel
  uygulamasının sürümünü de vermek zorundadır; sürüm okunamayan cihaz
  kırmızıdır. SIP dahili/PBX bilgisi `logcat -d -s AnnounceSip:I`
  satırlarından okunur, günlük tamponu dönmüşse boş kalabilir.
- **paho-mqtt** kurulu değilse MQTT kaynaklı cihazlar gri kalır.
- Firmware dosyası tarayıcı sanal alanı yüzünden yol yazılarak seçilir.
