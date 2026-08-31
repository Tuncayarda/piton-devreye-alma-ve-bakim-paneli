# Geliştirici Kılavuzu — İçerik Planı

Bu dosya **Word dokümanının kendisi değil**, onu doldurmak için yazılmış bir
plandır. bölüm iskeleti mevcut geliştirici kılavuzundan (`docs/DABP_Geliştirici_Kılavuzu.docx`) esas alınmıştır; her
başlığın altında **ne anlatılacağı**, **hangi tablonun gireceği**, **hangi
görselin nereye konacağı** ve **bilginin kaynağı** yazılıdır.

Word'e geçerken bölüm bölüm ilerlenecek. Görseller bu aşamada alınmadı;
metinde `[GÖRSEL-n]` olarak işaretlendi.

**Doküman künyesi**

| Alan | Değer |
|---|---|
| Doküman Adı | Devreye Alma ve Bakım Paneli – Yazılım Tasarım Dokümanı |
| Dosya Adı | DABP_Gelistirici_Kilavuzu.docx |
| Şablon | `docs/DABP_Geliştirici_Kılavuzu.docx` (kapak, künye tabloları, üstbilgi/altbilgi, stiller) |
| Hedef okuyucu | Kaynak koda ilk kez bakan geliştirici; bakımı devralacak ekip |
| Yazım dili | Türkçe. Kod, dosya adı, sınıf/fonksiyon adları İngilizce kalır |

**Şablonun stilleri** (Word'e geçerken kullanılacak): `Balk1`–`Balk3`
başlıklar, `TabloMetni` / `TabloMetniBold` tablo hücreleri, `ResimYazs`
şekil altyazısı, `ListeParagraf` madde listesi, `AralkYok` + Consolas kod
blokları, `TBal` + `T1`–`T3` içindekiler.

**Ölçek notu:** Panel 3 müşteri paketi, 77 API ucu (29 GET + 48 POST),
~130 Python modülü, ~54 JS modülü ve 29 test dosyası (911 test) içerir.
Doküman bunların hepsini tek tek anlatmaz; **karar veren yerleri** anlatır.

---

## 1. Giriş

### 1.1. Amaç
- Dokümanın ne olduğu: DABP'nin yazılım tasarımı, mimarisi ve geliştirme akışı.
- Kimin için: kaynak koda ilk kez bakan geliştirici.
- Ne değil: kullanım kılavuzu değil (o ayrı doküman), saha prosedürü değil.

### 1.2. Kapsam
- Uygulamanın mimarisi, alt sistemleri, yerel API'si, arayüz kalıbı,
  sözleşmeleri, test ve paketleme akışı.

### 1.3. Kapsam Dışı
- Cihazların kendi firmware'i ve web arayüzleri.
- Tren üstü kablolama ve ağ topolojisinin fiziksel tasarımı.
- `field_scripts/` altındaki iki saha script'inin iç mantığı (dışarıdan
  gelir, panel onları çalışma anında yükler — bkz. 4.9).

### 1.4. Kısaltmalar ve Tanımlamalar
**Tablo:** Kısaltma | Açıklama

Girecekler: DABP, DeviceMap, Edition (paket), PoE, ADB, APK, ISAPI, PISCU,
LCD, LED, NVR, MQTT, CDP, EMU, DXA, CSP, ARP, MTU, D-kodlu / X-kodlu M12,
"servis anahtarı", "iş" (job), "tur" (round), "probe".

### 1.5. Referans Dokümanlar
**Tablo:** Dosya | İçerik

| Dosya | İçerik |
|---|---|
| `docs/MIMARI.md` | Ayrıntılı mimari notları |
| `docs/CIHAZ_ENDPOINTLERI.md` | Cihazların HTTP uçları |
| `docs/CIHAZ_VERI_ALANLARI.md` | Okunan alanların anlamı |
| `docs/BUILD_RELEASE.md` | Derleme ve yayınlama |
| `docs/DEGISIKLIKLER.md` | Değişiklik geçmişi |
| `README.md` | Hızlı başlangıç |

---

## 2. Genel Bakış

### 2.1. Sistem Tanımı
- DABP tren setlerini sahada devreye alan ve bakımını yapan bir **masaüstü**
  uygulamasıdır. Sunucu değildir, servis değildir, ağda dinlemez.
- Yaptığı iş dört başlıkta: **oku** (tarama/probe), **yaz** (IP, ayar,
  yazılım), **doğrula** (denetim + Excel raporu), **kaydet** (iş geçmişi).
- Tek bir çalıştırılabilir dosya olarak dağıtılır; kurulum sonrası harici
  bağımlılık istemez (ADB dahil paketlenir).

### 2.2. Desteklenen Donanım
**Tablo:** Cihaz türü | Protokol | Okuma yolu | Yazma yolu | Modül

Girecekler: KYLAND switch (HTTP+Basic, `stat/*`), Hikvision kamera/NVR
(ISAPI, Digest), anons cihazı (JSON, kimliksiz), PISCU (MQTT), Kompartıman
LCD (ADB), LED panel. Her satırda ilgili `panel/probe/*.py` modülü.

**Kaynak:** `panel/probe/`, `panel/inventory/catalog.py`,
`docs/CIHAZ_ENDPOINTLERI.md`

### 2.3. Çalışma Ortamı
- Python 3.12.8 (`.python-version`), Windows / macOS / Linux.
- **Yönetici yetkisi zorunlu** — sebebi dört maddeyle (ikinci adres, ARP
  temizliği, IP yazma, PoE portu). Bkz. `panel/elevation/`.
- Bağımlılıklar: `docs/requirements*.txt` (platform başına ayrı dosya).

---

## 3. Mimari

### 3.1. Soketsiz Masaüstü (şablondaki "Gömülü Arayüz" buraya alınacak)
Bu bölüm dokümanın **en önemli** kısmıdır; en çok yanlış anlaşılan tasarım
kararı budur.

- Panel normal çalışmada **hiçbir TCP portu açmaz**. Arayüz tek bir HTML
  dosyası olarak belleğe yüklenir; Python ile JS `PanelBridge.invoke`
  üzerinden konuşur.
- `--browser` bayrağı **yalnızca** geliştirme ve teşhis için HTTP sunucusu
  başlatır. Üretimde kullanılmaz.
- Neden: yerel bir port, aynı makinedeki her sürecin eriştiği bir yüzeydir;
  panelin yaptığı iş (cihazlara yazma) bunu kabul edilemez kılar.
- `static/desktop.html` tek dosyaya gömülür; `panel/desktop/bundle.py`
  sonucun dışarıdan hiçbir kaynak yüklemediğini CSP özetleriyle doğrular.

**Kaynak:** `app.py`, `panel/desktop/bridge.py`, `panel/desktop/bundle.py`,
`panel/api/http_adapter.py`, `tools/build_desktop_bundle.py`

`[GÖRSEL-1]` — Mimari şeması: pywebview penceresi → PanelBridge → 
`panel.api.service.call()` → rotalar → alt sistemler → cihazlar.
Yanında ince bir kol olarak `--browser` → http_adapter. *(Çizim, ekran
görüntüsü değil.)*

### 3.2. Katmanlar
**Tablo:** Katman | Nerede | Sorumluluk | Bilmediği şey

| Katman | Nerede | Sorumluluk |
|---|---|---|
| Giriş | `app.py` | Bayraklar, yetki kontrolü, self-test, pencere |
| Köprü | `panel/desktop/bridge.py` | JS ↔ Python, JSON zarfı |
| Servis | `panel/api/service.py` | Rota çözümleme, istisna → HTTP kodu |
| Muhafız | `panel/api/guard.py` | Paketin görmediği ekranın ucunu reddetme |
| Rotalar | `panel/api/routes/` | Konu başına uç noktalar |
| İş gövdeleri | `panel/api/tasks/` | Kuyrukta çalışan uzun işler |
| Alt sistemler | `panel/<konu>/` | Cihaz erişimi ve iş kuralları |
| Kuyruk | `panel/jobs/` | İş yaşam döngüsü, satırlar, ilerleme |
| Arayüz | `static/js/` | Ekranlar, bileşenler, durum |

Her katmanın **bilmediği** şeyi de yazmak önemli: servis katmanı HTTP'yi
bilmez, alt sistemler kuyruğu bilmez, arayüz cihaz protokolünü bilmez.

### 3.3. Dizin Yapısı
Kod bloğu olarak ağaç + her dizinin bir satırlık açıklaması. `panel/` altındaki
21 alt paket ve `static/js/` altındaki üç dizin (`core/`, `components/`,
`views/`) yazılacak.

### 3.4. İstek Akışı
- Tek giriş: `panel.api.service.call(method, path, query, body)`.
- Sırası: `start()` → yol doğrulama → `guard.refusal()` → gövde doğrulama
  (`BODY_LIMIT`) → handler → `respond()` → `i18n.render()`.
- **İstisna → HTTP kodu tablosu** (aynen girecek):

| İstisna | Kod | Gövde |
|---|---|---|
| `LookupError` | 404 | `{"error": …}` |
| `ValueError` | 400 | `{"error": …}` |
| `FileNotFoundError` | 404 | `{"error": …}` |
| `panel.errors.AuthError` | 401 | `{"error": …, "auth": true}` |
| `panel.errors.DeviceError` | 502 | `{"error": …}` |
| diğer | 500 | genel mesaj (ham iz **yalnızca** stderr'e) |

- `auth: true` bayrağının önemi: arayüz giriş penceresini metne göre değil bu
  bayrağa göre açar.

**Kaynak:** `panel/api/service.py`, `panel/errors.py`, `panel/api/response.py`

### 3.5. Hata Modeli
- `DeviceError` ağacı: `UnreachableError`, `AuthError`, `VerificationError`,
  `NotApplicableError` — her biri kullanıcıya **farklı bir eylem** anlatır
  (kablo mu, parola mı, yanlış cihaz mı).
- `classify(exc)` ham ağ istisnasını bunlardan birine çevirir.
- `EADDRNOTAVAIL` özel durumu: cihaz arızası değil, bilgisayarın adresi yok.
  Yanlış sınıflandırılırsa teknisyen olmayan bir kabloyu aramaya gider.
- Kural: kullanıcıya giden metinde **asla** parola ve ham iz olmaz.

---

## 4. İşlevler

Her alt bölüm aynı kalıpta yazılacak: *ne yapar → nasıl çalışır → dikkat
edilecek nokta → kaynak dosya*.

### 4.1. Paketler (Editions)
- Bir çalıştırılabilir = bir müşteri paketi. `vip-yatakli`, `gdm`, `gaziray`.
- `BASE_VIEWS` her pakette; `ADMIN_VIEWS` yalnızca **servis anahtarıyla**.
- **Güncel dağılım** (yazarken koddan doğrulanacak, yakın zamanda değişti):
  - BASE: overview, devices, ip, config, firmware, network, checklist, history
  - ADMIN: adb, switch, piscu, mqtt, admin
- ADB ve Switch'in admin olmasının gerekçesi koddaki yorumda yazılı ve
  dokümana alınacak: bu ikisi **cihaz listesi olmadan** donanıma yazar;
  yazılan adres kullanıcının yazdığı adrestir, paylaşılan bir ağda bu
  "herhangi bir cihaz" demektir.
- Kısıt **iki yerde birden**: sunucuda `panel/api/guard.py`, istemcide
  `static/js/core/store.js:viewAllowed`. Neden iki yerde: düğmeyi gizlemek
  kimseyi durdurmaz.

**Kaynak:** `panel/editions/catalogue.py`, `runtime.py`, `panel/api/guard.py`

### 4.2. Servis Anahtarı (Admin Key)
- USB anahtarla admin moda geçiş; paket anahtarı **tanır** ama **üretemez**
  (tek yönlü özet ile derlenir).
- `watcher` takılmayı izler, `pack` oturumluk proje kopyalarını tutar,
  `handoff`/`handback` devir akışı.
- Admin moddan çıkarken projenin de geri alınması gerektiği kuralı
  (`lifecycle.leave_admin` — başka müşterinin cihaz listesi ekranda kalmasın).

**Kaynak:** `panel/adminkey/`, `tools/key_digest.py`

### 4.3. Envanter ve Proje
- DeviceMap: projenin cihaz listesi. Cihaz kimlikleri **konumsaldır**
  (`sw1.d3` = birinci switch'in üçüncü cihazı).
- Proje değişince kimliğe bağlı her şey atılır; **kimlik bilgileri istisna**
  (`id@ip` ile anahtarlanır).

**Kaynak:** `panel/inventory/device_map.py`, `catalog.py`,
`panel/api/lifecycle.py:switch_project`

### 4.4. Ağ Hazırlığı
- Bilgisayara cihaz ağında ikinci bir adres eklenir; kapanışta geri alınır.
- Önceki koşudan kalan adresler açılışta süpürülür (`sweep_stale`).
- `PANEL_NETWORK_WRITES=0` testlerde gerçek arayüzü korur.

**Kaynak:** `panel/network/` (adapters, aliases, commands, planning, prepare,
routes)

### 4.5. Tarama ve Okuma (Probe)
- `reader.read_device()` cihaz türüne göre doğru probe'u seçer.
- Her probe **doğrular**: HTTP 200 tek başına başarı değildir.
- Telemetri (PISCU/MQTT) taramanın başında bir kez toplanır, tur boyunca
  paylaşılır.

**Kaynak:** `panel/probe/`, `panel/telemetry/`

### 4.6. IP Atama
- Plan → koşu → doğrulama. Port kapatma/açma ile cihazları tek tek yalıtma.
- `preflash`, `factory_reset`, `lcd_runner` (bench akışı), `audit`.
- İlerleme yüzdesi işin kendi fazlarından yazılır (`progress.py`) — "biten
  satır / toplam satır" bu iş için yanlış cevap.

**Kaynak:** `panel/ip_assign/`

### 4.7. Switch Yönetimi
- **Panelin tek switch istemcisi** `panel/switch/`. IP ekranının ön paneli,
  factory-reset doğrulaması ve Switch ekranı aynı `switch.CLIENT`'tan geçer.
- Kimlik bilgisi **her zaman çağrandan** gelir; istemci hiçbir parola tutmaz.
- `trust_env=False`: yerel switch trafiği proxy'ye düşmemeli.
- Switch başına yazma kilidi + tek tarama kapısı.
- **KYLAND'in üç alışkanlığı** — kendi alt başlığını hak eder:
  1. Port tabloları **bütün olarak** yazılır; tek portu göndermek diğerlerini
     varsayılana çeker.
  2. Boolean alan **ya vardır ya yoktur**, asla `"0"` değildir.
  3. Güç değeri **on kat büyük** gelir (`"123"` = 12,3 W).
- Tarama `MAX_DISCOVERY_ADDRESSES` ile sınırlı; boyut **liste kurulmadan
  önce** kontrol edilir (aksi hâlde /8 için 16,7 milyon dize).

**Kaynak:** `panel/switch/` (client, discovery, ports, device, network,
validation), `panel/probe/switch.py`

### 4.8. ADB Araçları
- Havuz: projeye ait olmayan, elle girilen adres listesi (`pool.py`).
- İşlemler: connect, start, stop, restart, uninstall, install, reboot,
  autostart_install, autostart_remove.
- `KEEP_CONNECTED`: `connect` dışındaki her işlem transport'u geri verir;
  `connect` bilerek bağlı bırakır (`adb devices` listelesin diye).
- `am start` yalan söyler: 0 ile çıkarken `Error:` basar. İki yol denenir,
  ikincisi `monkey`.
- Bir ADB işlemi sürerken panelin otomatik turları durur — iki taraf da aynı
  ADB sunucusundan geçer (`core/schedule.js` + `session_routes.py`).

**Kaynak:** `panel/adb/`

### 4.9. Saha Script'leri
- İki script çalışma anında yüklenir: `device_verify.py` (alan çıkarımı +
  Excel şeması), `intercom_ip_assign.py` (IP koşusu, MAC tablosu ayrıştırma).
- Neden yeniden yazılmıyor: ikinci bir uygulama ilkinden ayrışır.
- **Not:** `switch_api.py` üçüncü script'ti, emekliye ayrıldı — yerini
  `panel/switch/` aldı. Sebebi: Switch ekranının **yazması** gerekiyordu ve
  ödünç alınan salt-okunur bir script bunu ikinci bir istemciye dönüşmeden
  büyütemezdi.

**Kaynak:** `panel/script_loader.py`, `field_scripts/`

### 4.10. Yapılandırma ve Yazılım
- `config_sync`: hedef okuma, karşılaştırma, uygulama; alan tanımları.
- `firmware`: APK kurulumu, sürüm doğrulama, HTTP yükleme.
- `video_config`: kamera/NVR ISAPI yazımı, kanallar, sağlık.

### 4.11. Doğrulama ve Rapor
- `checklist`: sütun tanımları, önizleme, Excel üretimi.

### 4.12. Kimlik Bilgileri
- **Yalnızca bellekte.** Dosya/env/keychain yok; `forget_all()` kapanışta.
- Kayıt cihaz **kanıtladıktan sonra** yapılır — dolu bir form hiçbir şey
  kanıtlamaz (`looks_like_switch`).
- Anahtar `id@ip`: ad tek başına yetmez (iki switch aynı adı taşıyabilir),
  IP tek başına yetmez (set değişince başka cihazı gösterir).
- Grup paylaşımı yalnızca kullanıcı isterse; `"switch"` grubu hem Switch
  ekranı hem IP atama tarafından okunur.

**Kaynak:** `panel/credentials.py`

### 4.13. İş Kuyruğu
- `Job` / `JobQueue` / `sweep_devices` / `DeviceStateView`.
- **İş ile görünüm ayrıdır**: iş biter ve silinir, cihaz durumu kalır. Aksi
  hâlde eski bir işin sonucu taze taramayı eziyordu.
- Uzun işler kuyruğa girer: tarama, IP koşusu, config, firmware, checklist,
  switch taraması (`switchscan`).
- İlerleme geri gitmez — kuralın gerekçesi yazılacak.

**Kaynak:** `panel/jobs/`

---

## 5. Kullanıcı Arayüzü

### 5.1. Ekran Düzeni ve Yönlendirme
- `static/index.html` kabuk; her ekran `<div class="view" id="v-<ad>">`.
- `app.js` içindeki `VIEWS` sözlüğü ekran kimliğini kapsayıcı + çizim
  fonksiyonuna eşler.
- `VIEW_NAME`, `SHORTCUT_VIEWS` (kısayol rakamları listeden **türetilir**),
  `onViewEntered`.

`[GÖRSEL-2]` — Panelin genel görünümü, sol menü ve üst çubuk işaretli.

### 5.2. Çizim Kalıbı (kritik)
- `render(root)` **yalnızca çizer**. `app.js` her durum yayınında çağırır;
  içine veri çekme koymak saniyede bir istek demektir.
- Veri `refresh()` ile gelir; `onViewEntered` ekran açılınca bir kez çağırır.
- Yoklama `setTimeout` **zinciri**, `setInterval` değil.
- Bir kutuya odaklanılmışken çizim ertelenir (`focusInScreenField`), yoksa
  yazılan metin silinir.
- Açık bir açılır liste varken de ertelenir.

### 5.3. Çekirdek Modüller
**Tablo:** Modül | Görevi | Dikkat

`core/dom.js` (`el()`/`fill()` — innerHTML'e tek alternatif),
`core/store.js` (izin listeli tek durum), `core/api.js` (uçların tek tanımı),
`core/i18n.js`, `core/transport.js`, `core/schedule.js`, `core/format.js`.

### 5.4. Bileşenler
`dialog`, `confirm` (`confirmWrite`), `toast`, `table` (`dataTable`),
`sidebar`, `queue`, `locked`, `detail`, `group_bar`, `action_tabs`,
`language`, `front_panel`.

### 5.5. Ön Panel (paylaşılan bileşen)
- Konnektör çizimi ve ızgara aritmetiği `components/front_panel.js`'te; hem
  IP atama hem Switch ekranı kullanır.
- İki ayrı çizim ilk acele düzeltmede ayrışır → aynı switch iki ekranda
  farklı görünür.
- **Paylaşılan olan ile olmayanı ayır:** ortak olan çizim ve yerleşim;
  ortak olmayan, portun ne anlama geldiği (IP ekranı DeviceMap'e ve koşu
  hedefine göre, Switch ekranı canlı PoE durumuna göre renklendirir).
- PoE portu M12 **D-kodlu**: tek halkada dört kontak.
- Uplink M12 **X-kodlu**: köşegenlerde **dört çift**; X pinlerin kendi
  dizilişidir, üstüne çizgi çizilmez.
- `PANEL_SIZES`: IP ekranı `compact`, Switch ekranı `large`.

`[GÖRSEL-3]` — Switch ekranının ön paneli (24 PoE + 4 uplink), bir kısmı
seçili. Yanına 4 pinli ve 8 pinli konnektörün yakın çekimi.

### 5.6. Switch Ekranı
- Yedi dosya: `state`, `session`, `discovery`, `front_panel`, `ports`,
  `network`, `log`, `context_menu`.
- Değişiklik **anında yazılır**, bekletme yoktur.
- Sağ tık menüsü seçime uygulanır; tek istekte batch gider.
- Oturum kaydı yalnızca bellekte.

`[GÖRSEL-4]` — Switch ekranı: tarama sonucu + switch listesi.
`[GÖRSEL-5]` — Port sağ tık menüsü açıkken.

### 5.7. ADB Ekranı
- Beş dosya: `state`, `pool`, `packages`, `operations`, `index`.
- Seçim tarayıcıda yaşar; cihaz listesi sunucuda (yarın da orada olmalı).
- `operationTargets()`: işlem "şu paket şu cihazlarda" değil, **(cihaz,
  paket) çiftleri** listesidir.

`[GÖRSEL-6]` — ADB ekranı: cihaz listesi, arama sonucu, işlem çubuğu.

### 5.8. Dil
- Katalog **sunucudan** gelir (`/api/language`), arayüze gömülmez.
- Tek dosya, iki okuyucu: Python `i18n.t()`, JS `t()`.

---

## 6. Yerel API

### 6.1. Genel Kurallar
- Yalnızca `/api/` ile başlayan yollar; tam URL kabul edilmez.
- Gövde JSON nesnesi olmalı ve `BODY_LIMIT`'i aşmamalı.
- Rota modülü **iki listeye birden** eklenir (`from . import` + `_MODULES`);
  birine ekleyip diğerini unutmak **sessizce 404** üretir.

### 6.2. Okuma Uçları (29 GET)
**Tablo:** Yol | Döndürdüğü | Modül. Konu başlıklarına gruplanacak:
genel/durum, cihaz, IP, config, firmware, checklist, ağ, telemetri, ADB,
switch, edition/admin.

### 6.3. Yazma Uçları (48 POST)
Aynı tablo düzeni. Yazan uçlar **ayrıca işaretlenecek** (cihaza dokunanlar).

### 6.4. Hata Yanıtları
3.4'teki tablo burada tekrar edilecek + örnek gövdeler.

### 6.5. Uzun İşler
- Hangi uçlar iş döndürür, `job.dto()` şekli, `/api/job` ile yoklama,
  `/api/job/cancel`.

---

## 7. Ayarlar ve Kalıcı Veri

- `panel/settings.py`: ortam değişkenleriyle geçersiz kılınabilen sabitler
  (portlar, zaman aşımları, `SWITCH_POE_PORTS`, `ADB_PACKAGE` …).
- `PANEL_DATA_DIR` altında ne tutulur: `ui.json` (dil), `network.json`,
  `network_aliases.json`, `<edition>/adb_devices.json`, kayıtlı config
  varsayılanları.
- **Ne tutulmaz:** parola, günlük dosyası, cihaz sırrı.
- Kalıcı veri **paket başına** ayrılır (`<edition>/` alt dizini).

**Tablo:** Dosya | İçerik | Ne zaman yazılır | Ne zaman silinir

---

## 8. Güvenlik

Bu bölüm bir kural listesi olarak yazılacak; her kuralın **gerekçesi** ve
**nerede zorlandığı** ayrı sütunda.

**Tablo:** Kural | Gerekçe | Nerede zorlanır

Girecek kurallar:
1. Ağda dinlenmez (soketsiz mod).
2. Parola yalnızca bellekte; diske/env/keychain yazılmaz.
3. Parola tarayıcı deposuna ve global duruma girmez.
4. Parola hiçbir yanıtta, iş satırında, hata metninde geçmez.
5. Ham iz yalnızca stderr'e.
6. `innerHTML` / `outerHTML` / `eval` kullanılmaz.
7. Dosya yolu istemciden gelmez (dosya seçici işletim sisteminde açılır).
8. Paketin görmediği ekranın ucu sunucuda reddedilir.
9. Servis anahtarı tanınır, üretilemez.
10. Gömülü arayüz dışarıdan kaynak yüklemez (CSP özetleriyle doğrulanır).
11. Kapanışta bilgisayarın ağı geri alınır.

---

## 9. Uyulması Zorunlu Sözleşmeler

Ayrı bölüm olmayı hak eder: bunlar **testlerle zorlanır**, ihlalde derleme
kırılır. Yeni geliştiricinin ilk gün okuması gereken bölüm budur.

**Tablo:** Kural | Nerede zorlanır

| Kural | Nerede zorlanır |
|---|---|
| Kodda düz cümle yok, mesaj anahtarı var | `test_i18n.py`, `test_language.py` |
| İki katalog birebir aynı anahtar kümesi | `test_i18n.py` |
| Kullanılmayan katalog anahtarı bırakılmaz | `test_i18n.py` |
| Yer tutucular iki dilde aynı | `test_i18n.py` |
| `innerHTML` vb. yasak | `test_frontend.py` |
| Parola diske/tarayıcı deposuna yazılmaz | `test_credentials.py`, `test_security.py` |
| `setInterval` yerine `setTimeout` zinciri | `test_frontend.py` |
| Her JS modülü `app.js`'ten erişilebilir | `test_frontend.py` |
| Her ekranın kapsayıcısı `index.html`'de var | `test_frontend.py` |
| Linklenen her CSS bundle'a giriyor | `test_frontend.py` |
| Ön panel tek yerde çiziliyor | `test_frontend.py` |
| Renk kontrastı tabanı | `test_frontend.py` |
| Yazı boyutu ölçekten seçilir | `test_frontend.py` |
| Rota iki listeye birden eklenir | `routes/__init__.py` (yorum + 404 riski) |

**Katalog biçimi:** düz, tek seviye, **alfabetik**.
`"switch.buttonScan": "Tara",` — iç içe değil.

---

## 10. Geliştirme ve Test

### 10.1. Geliştirme Sunucusu
- `python3 app.py --edition <paket> --browser` → HTTP üzerinden arayüz.
- Yönetici yetkisi gerektirir; testlerde `is_elevated` yamalanır.
- Not: geliştirme sırasında `PANEL_DATA_DIR`'i geçici bir dizine almak,
  operatörün gerçek ayarlarına dokunmamak için önerilir.

### 10.2. Sahte Cihazlar
- `tests/support/fakes.py`: KYLAND switch (PoE tabloları, yazma uçları,
  gönderilen form gövdelerini `server.posts`'ta tutar), Hikvision kamera,
  NVR, anons cihazı, ADB (`FakeAdb`).
- Sahte switch gerçek SICOM3028GPT'yi taklit eder: 24 PoE + isteğe bağlı
  uplink.
- Suite **bu bilgisayarın ağını değiştirmez** (`PANEL_NETWORK_WRITES=0`) ve
  gerçek ayar dizinine yazmaz.

### 10.3. Testler ve Denetim
Kod bloğu olarak komutlar:
```
python3 -m unittest discover -s tests -t . -q
python3 -m ruff check panel/ tests/ app.py tools/
deno lint static/js tests/js
deno check --no-lock static/js/app.js
deno test --no-lock --allow-read tests/js/
python3 app.py --edition vip-yatakli --self-test
python3 tools/build_desktop_bundle.py
```
- 29 test dosyası; JS tarafı `tests/js/` altında deno ile.
- `ruff` yapılandırması `pyproject.toml`'da ve **neden öyle olduğu** orada
  yazılı (bu dokümanda tekrarlanmayacak, işaret edilecek).

### 10.4. Yeni Bir Ekran Eklemek
Adım adım kontrol listesi (dokunulacak 11 yer):
`panel/<konu>/` → `routes/<konu>_routes.py` → `routes/__init__.py` (**iki
liste**) → `editions/catalogue.py` → `messages/{en,tr}.json` →
`index.html` → `views/<ad>/index.js` → `app.js` (import, `VIEWS`,
`VIEW_NAME`, `onViewEntered`) → `core/api.js` → `components/sidebar.js` →
`tools/build_desktop_bundle.py` (yeni CSS varsa).

---

## 11. Derleme ve Yayınlama

- Arayüz `tools/build_desktop_bundle.py` ile tek `static/desktop.html`'e
  gömülür; `panel/desktop/bundle.py` CSP özetleriyle doğrular.
- PyInstaller + `dabp.spec`; **paket başına ayrı çıktı**
  (`tools/edition_info.py` paket tablosundan okur).
- Windows: Inno Setup (`packaging/windows/`). Linux: `packaging/appimage.sh`.
- Servis anahtarı sırrı derleme zamanında **özet** olarak gömülür.
- CI: `.github/workflows/` — dört platform, test + self-test + paketleme.
- Ayrıntı `docs/BUILD_RELEASE.md`'de; burada akış ve karar noktaları.

---

## 12. Ekler

### 12.1. Sözlük
Kodda geçen ve dokümanda kullanılan terimler: tur (round), iş (job), satır
(row), havuz (pool), paket (edition/bundle — **ikisi farklı**, ayrımı yaz),
probe, sweep, künye.

### 12.2. Karar Kaydı
Bu panelde bilinçli olarak **yapılmayan** şeyler ve sebepleri. Yeni gelenin
"neden böyle değil?" sorusunu tek yerde karşılar:

| Karar | Sebep |
|---|---|
| Ağda port dinlenmiyor | Yerel port, makinedeki her sürecin eriştiği yüzeydir |
| Parola diske yazılmıyor | Devreye alma dizüstüsü oturumdan uzun yaşar |
| Günlük dosyası yazılmıyor | Aynı sebep; iş kaydı kuyrukta ve bellekte |
| İkinci switch istemcisi yok | İki istemci timeout ve "giriş gerekli" tanımında ayrışır |
| Ön panel tek yerde çiziliyor | İki çizim aynı switch'i farklı gösterir |
| Otomatik turlar kapalı başlıyor | Panel çoğu zaman tek cihaza tek iş için açılır |
| Bekletme/uygula adımı kaldırıldı | Ekranın var oluş sebebinin önüne ikinci tık koyuyordu |
| `am start` tek yola bırakılmadı | Bazı bundle'lar launcher activity bildirmiyor |

---

## Word'e Geçerken

1. Şablon `docs/DABP_Geliştirici_Kılavuzu.docx`; kapak, künye tabloları, üstbilgi/altbilgi ve
   stiller korunacak. Künye alanları (doküman adı, dosya adı, tarih,
   hazırlayan, versiyon) ve **sayfa üstbilgisi** güncellenecek — şablonun
   üstbilgisi hâlâ eski projeyi yazıyor.
2. İçindekiler gerçek TOC alanı olarak bırakılacak; Word'de **Ctrl+A → F9**
   ile sayfa numaraları güncellenir.
3. Tablolar `TabloKlavuzu` stilinde, başlık satırı `TabloMetniBold` ve
   dolgulu; altyazı `ResimYazs` ile "Tablo N …".
4. Görseller ortalanmış, `keepNext` ile altyazıya bağlı; altyazı
   "Şekil N - …" biçiminde `SEQ Figure` alanıyla.
5. Kod blokları Consolas, `AralkYok` stili, açık gri dolgu.
6. Bölümler **sırayla** yazılacak; her bölüm bitince gözden geçirilip
   sonrakine geçilecek.

**Yazmadan önce koddan doğrulanacaklar** (bu plan yazıldıktan sonra
değişebilecek yerler):
- `BASE_VIEWS` / `ADMIN_VIEWS` dağılımı,
- GET/POST uç sayıları ve listeleri,
- `apps.OPERATIONS` listesi,
- test sayısı,
- `settings.py`'deki sabitler.
