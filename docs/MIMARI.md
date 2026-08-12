# Devreye Alma Paneli — Mimari ve Çalıştırma

Yataklı tren setlerini sahada devreye almak için geliştirilmiş bir masaüstü
panelidir.
DeviceMap topolojisini yükler, cihazları okur, kimlik isteyen cihazları
kilit menüsünde toplar ve kontrol listesini Excel'e döker.

---

## 1. Çalıştırma

Kaynak koddan çalıştırmak için Python 3.10 veya üzeri gerekir. Masaüstü
pencere motoru işletim sistemine göre değiştiğinden, yalnız ortak paketleri
içeren `docs/requirements.txt` yerine platform dosyası kurulmalıdır. Örneğin
macOS'ta:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r docs/requirements-macos.txt
.venv/bin/python app.py
```

Linux'ta `docs/requirements-linux.txt` kullanılmalıdır. Windows'ta aynı akış
şöyledir:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r docs\requirements-windows.txt
.\.venv\Scripts\python.exe app.py
```

Platform dosyalarının her biri ortak gereksinimleri de içerir. Linux masaüstü
penceresi için dağıtımın Qt sistem kitaplıkları, işletim sistemi dosya seçicisi
için de `zenity` veya `kdialog` gerekebilir. Yayın paketleri Python 3.12 ile
üretilir; ayrıntılar `docs/BUILD_RELEASE.md` içindedir.

Bağımlılıklar kurulduktan sonra doğrudan açılış: `python3 app.py`

| Komut | Ne yapar |
|---|---|
| `python3 app.py` | HTTP/loopback kullanmadan pywebview penceresini açar |
| `python3 app.py --tarayici` | HTTP tabanlı geliştirme/tanı kipini varsayılan tarayıcıda açar |
| `python3 app.py --tarayici --port 8790` | Tanı servisinin portunu sabitler |
| `python3 app.py --admin-parolasi ****` | Admin rolü seçim ekranına parola denetimi ekler; uygulama bu değeri kalıcılaştırmaz |
| `python3 app.py --self-test` | Pencere/soket açmadan tek HTML paketini ve üretim köprüsünü doğrular; cihaz ağına bağlanmaz |
| `python3 app.py --version` | Uygulama sürümünü yazdırır |
| `python3 panel_api.py --port 8790` | Yalnız API (hata ayıklama) |
| `python3 -m unittest discover -s tests -t .` | Bütün testler |

### Yükseltilmiş yetki kapısı

Panel ağ arayüzünü ve ARP önbelleğini okuyup temizliyor, cihazlara IP yazıyor
ve switch portlarını yönetiyor. Bunlar sıradan kullanıcı yetkisiyle **sessizce
yarım** çalışıyor: en pahalı örneği ARP kaydının silinememesi, aynı adresteki
cihazların birbirinin arkasında kalması ve koşunun "cihaz bulunamadı" demesi
(bkz. §9). Bu yüzden yetkisiz kip yok.

Denetim `yetki.yonetici_mi()` ile yapılır (POSIX'te `geteuid`, Windows'ta
`IsUserAnAdmin`) ve `--self-test` / `--version` dışındaki bütün kipleri kapsar;
o ikisi cihaza ve ağa hiç dokunmaz.

Yetki yoksa eskiden konsola tek satır yazılıp çıkılıyordu: uygulamayı çift
tıklayan kullanıcı **hiçbir şey görmüyordu**. Artık bir pencere açılır ve iki
yol sunar — "Yönetici olarak yeniden başlat" ve "Çıkış". Üçüncü bir yol
(yetkisiz devam) bilerek yok.

| | yükseltme | parolayı kim sorar |
|---|---|---|
| Windows | `ShellExecuteW` fiil `runas` | UAC |
| macOS | `osascript … with administrator privileges` | sistem parola penceresi |
| Linux | `pkexec` (yoksa otomatik yükseltme yok) | polkit |
| yedek (POSIX, terminalden başlatıldıysa) | `sudo` ile süreç **yerinde** değiştirilir | sudo, aynı terminalde |

Asıl yol sistemin kendi izin penceresidir; uygulamanın terminalle işi yoktur.
Yedek yol yalnız pencere yolu düştüğünde **sorulur** — sessizce başka bir yola
sapılmaz.

Yedeğe ihtiyaç macOS'ta doğabiliyor: sistem penceresiyle başlatılan süreç
`security_authtrampoline` altında doğuyor ve korumalı klasörlere
(Masaüstü/Belgeler/İndirilenler) erişimi TCC tarafından reddedilebiliyor.
Sahada bir kez birebir şu görüldü: `can't open file '…/Desktop/dap/app.py':
[Errno 1] Operation not permitted`. Bu, macOS'un bir kerelik klasör erişimi
sorusuna cevap verilene kadar süren geçici bir durum; sonraki ölçümlerde aynı
komut sorunsuz çalıştı. `sudo` ile devredilen süreç terminalin kimliğini
sürdürdüğü için o engel hiç doğmaz. Paketlenmiş uygulama `/Applications`
altında durduğundan orada da sorun çıkmaz.

Parola uygulamaya girilmez, uygulama parola sormaz: istemi işletim sistemi
gösterir, panel yalnız yeni süreci başlatır ve **kendisi çıkar** — aynı panelin
iki kopyası aynı switch'e ve aynı DeviceMap'e yazmamalı. Kullanıcı istemi
reddederse sebep hem konsola hem ikinci bir pencereye yazılır; sessizce
kapanmak, hatanın kendisiydi.

Windows'ta paketlenmiş uygulamanın manifestine ayrıca yönetici isteği gömülür
(`uac_admin=True`, bkz. `DevreyeAlmaPaneli.spec`): çift tıklamada UAC önce
çıkar ve panel doğrudan yükseltilmiş açılır. Pencere yine de gerekli — betikten
çalıştırma ve eski kısayollar bu manifestten geçmez.

Kimsenin başında olmadığı koşularda (CI, otomatik doğrulama) bekleyen bir
pencere işi sonsuza kadar asar; `PANEL_YETKI_PENCERESI=0` pencereyi hiç açmaz
ve akış doğrudan "çıkış" ile biter.

İki ayrıntı sahada ölçülerek eklendi:

- **Süreç kendiliğinden kapanmıyordu.** Pencere motorunun olay döngüsü
  kapandıktan sonra Cocoa/GTK iş parçacıkları süreci ayakta tutabiliyor;
  yükseltilmiş süreç başladıktan sonra eski süreç dışarıdan sonlandırılana
  kadar açık kaldı. `app._hemen_cik()` `main()` döndükten sonra yorumlayıcıyı
  doğrudan bitirir — kapatılacak bir şey kalmamıştır, servisler `main`'in
  `finally` bloğunda zaten kapanmıştır.
- **Yeni sürecin çıktısı bir günlüğe yazılır** (`yetki.gunluk_yolu()`,
  geçici dizinde `devreye-yukseltme.log`). Arkaplandaki yükseltilmiş süreç
  açılışta düşerse kullanıcı hiçbir şey görmez; geriye bakılacak tek yer
  orasıdır. Konsola da yolu yazılır.
- **macOS'ta `nohup` kullanılmaz.** `do shell script` komutu terminalsiz
  çalıştırıyor ve oradaki nohup `can't detach from console: Inappropriate
  ioctl for device` deyip düşüyordu: parola giriliyor, komut 0 dönüyor,
  panel hiç açılmıyordu. Arkaplana atmak için `&` yeterli; girdi
  `/dev/null`'dan verilir.
- **Onaydan sonra eski süreç görünmez olur.** Doğrulama boyunca (aşağıdaki
  madde) birkaç saniye daha yaşıyor ve o sırada Dock'ta yeni panelin yanında
  ikinci bir simge duruyordu. Pencere kapandığına göre simgenin durmasının
  anlamı yok: `yetki.dock_gizle()` süreci Dock dışına alır
  (`NSApplicationActivationPolicyAccessory`).
- **Yükseltme kanalının bitmesi BEKLENMEZ.** macOS'ta
  `security_authtrampoline`, başlattığı sürecin bitmesini bekliyor:
  `subprocess.run` kullanıldığında eski süreç, yeni panel kapanana kadar
  hayatta kalıyordu — Dock'ta ikinci bir uygulama olarak duruyor, panel
  kapanınca da PID'i ölü bulup yanlışlıkla "açılışta düştü" penceresi
  açıyordu. Ölçüm: yalın `do shell script` 12 saniyelik arkaplan süreciyle
  0,1 sn'de dönüyor, yükseltilmiş olan dönmüyor. Kanal `Popen` ile
  başlatılır (kendi oturumunda) ve **kabuğun yazdığı PID** beklenir; PID
  dosyası göründüğü an yeni süreç doğmuştur.
- **PID'in yazılması da yetmez**, çünkü süreç açılışta düşebilir.
  `yeni_surec_durumu()` birkaç saniye sonra sürecin hâlâ var olup olmadığına
  bakar ve düşmüşse günlüğün son satırını sebep olarak gösterir. Sebep "Operation not
  permitted" ise macOS gizlilik koruması açıklanır: Masaüstü/Belgeler/
  İndirilenler klasörlerindeki bir uygulamayı sistem penceresiyle başlatan
  süreç dosyayı açamayabiliyor ve bu, dosya izniyle karıştırılıyor.

---

Admin şifresi verilmezse admin ekranı şifresiz açılır. Şifre yalnız
bellekte tutulur ve `secrets.compare_digest` ile karşılaştırılır. Bu denetim,
yerel arayüzde Admin rolüne geçiş kapısıdır; servis işlemleri için oturum veya
yetkilendirme belirteci üretmez. Normal masaüstü kipinde dinleyen bir sunucu
yoktur ve köprü yalnız paket içindeki WebView'a açılır. İsteğe bağlı tarayıcı
kipi ise yalnız geri döngü arayüzünde (`127.0.0.1`) dinler. Komut satırına
yazılan bir değer kabuk geçmişinde ya da süreç listesinde görünebileceğinden
işletim sistemi düzeyindeki komut geçmişi ayrıca dikkate alınmalıdır.

---

## 2. Katmanlar

```
app.py            pywebview penceresi + uygulama ömrü (soket açmaz)
masaustu.py       tek public invoke() içeren pywebview köprüsü
panel_api.py      ortak PanelService + isteğe bağlı HTTP adaptörü
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
  yerel_ag.py     bu bilgisayarın arayüz/MAC bilgisi (korunacak port için)
  konfig.py       konfigürasyon oku/yaz
  firmware.py     yazılım yükleme (anons: HTTP imaj, LCD: adb APK)
  excel.py        kontrol listesi Excel çıktısı
  kontrol.py      Excel şablonunun ekran önizlemesi
static/           modüler kaynaklar + üretilmiş tek parça masaustu.html
tools/            Deno tabanlı deterministik masaüstü paketleyicisi
tests/            unittest paketi + sahte cihazlar
```

Tarayıcı tanı kipinde `static/js` doğrudan ES module olarak servis edilir.
Üretim masaüstü kipinde aynı modül grafiği Deno 2.9.4 ile IIFE'ye paketlenir;
CSS, logo ve favicon ile birlikte `static/masaustu.html` içine gömülür.
`app.py` bu dosyayı belleğe okuyup `create_window(html=...)` ile açar ve
yalnız `PanelKoprusu.invoke` metodunu `Window.expose(...)` izin listesine
ekler. Köprü nesnesinin kendisi `js_api` olarak verilmez; gizli Python üyeleri
WebView'ın çağrı ağacına girmez. Pywebview'a yerel dosya yolu verilmediği için
pywebview'un dahili HTTP sunucusu da başlamaz.

Tek HTML'in CSP'si `default-src 'none'` ve `connect-src 'none'` ile bütün ağ
yüklemelerini kapatır; iki inline script yalnız SHA-256 özetleriyle açılır.
Pywebview 6.2.1 köprü dönüşlerini sayfa bağlamına aktarırken kontrollü
JavaScript değerlendirmesi kullandığı için `script-src` ayrıca
`'unsafe-eval'` içerir. Bu izin kaldırıldığında köprü de çalışmaz; dış
kaynaklara ve ağ bağlantılarına izin vermez.

Görünümler taşıma ayrıntısını bilmez. `static/js/core/api.js` mevcut semantik
metotları korur; tarayıcıda `fetch`, masaüstünde
`window.pywebview.api.invoke(capability, method, path, body)` kullanır.
`capability`, her pencere açılışında üretilen 256 bitlik ve 43 karakterlik
oturum anahtarıdır; tek HTML'deki doğrulanmış meta alanına çalışma anında
yerleştirilir. Yanlış anahtar 403 alır. Böylece WebView başka bir belgeye
yönlense bile yeni belge yalnız açık fonksiyonun adını bilerek servisi
çağıramaz.
Köprü yanıtları `{ok, status, body}` zarfındadır. `panel_api.PanelService`
aynı çağrıyı işler; HTTP Handler yalnız ayrıştırma/serileştirme adaptörüdür.

---

## 3. Çalışan kodu yeniden yazmama

Panel üç betiği **çalışma anında içe aktarır** (`core/betik.py`), kopyalamaz:

| Betik | Ne için |
|---|---|
| `betikler/switch_api.py` | Switch erişiminin tamamı |
| `betikler/device_verify.py` | Excel şeması ve alan tabloları |
| `betikler/intercom_ip_assign.py` | IP atama koşusu |

Switch okuması `switch_api.sw_get(ip, "stat/basicInfo", kimlik=(k, p))`
çağrısına iner. URL, HTTP Basic kimlik doğrulama biçimi, port, zaman aşımı,
HTTP başlıkları ve
"JSON gelmiyorsa oturum açılması gerekiyor" kuralı iki panelde birebir
aynıdır — bu yüzden Switch Yönetim Paneli'nde çalışan hesap burada da
çalışır. `tests/test_switch.py::test_1` bunu iddia etmekle kalmaz, aynı
sahte switch cihazına iki panelin yolundan sorup sonuçları karşılaştırır.

`kimlik` her çağrıda açıkça verilir; verildiği sürece `switch_api` kendi
modül içi kimlik deposuna hiç bakmaz.

---

## 4. Kimlik bilgileri — kritik akış

**Kural: panelde oturum sırasında girilen cihaz erişim kullanıcı adı ve
parolaları yalnızca çalışan Python sürecinin belleğinde tutulur.** Admin
parolası ile ekrandan girilen SIP parolası da uygulama tarafından kalıcı
depoya yazılmaz.

Cihaz erişim kimlikleri için `.env`, JSON, SQLite, keychain,
`localStorage`, `sessionStorage` veya çerez tabanlı bir kalıcı depo yoktur.
Bu değerler loglara, istisna mesajlarına, iş kuyruğu satırlarına ve API
yanıtlarına da eklenmez.

`DeviceMap.json` bu kuraldan ayrı değerlendirilir. Dosyada eski
`Username`/`Password` alanları bulunabilir; panel bu alanları cihaz erişim
kimliği olarak kullanmaz ve DTO/API yanıtlarına taşımaz. `PBXPassword` ise
cihaza bağlanma kimliği değil, SIP yapılandırmasının proje girdisidir:
gerektiğinde cihaza yazılır ancak yine DTO/API yanıtlarında gösterilmez.

### Akış

```
Tam tarama
   └─ cihaz 401/403 döndürür ya da JSON yerine oturum sayfası verir
        └─ durum: TURUNCU (kimlik_bekliyor)
             └─ üst bardaki kilit kutucuğuna düşer, rozet artar
                  └─ kullanıcı cihaza tıklar → iletişim kutusu
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
| Zaman aşımı / bağlantı reddi | "Cihaz zaman aşımına uğradı" / "Cihaza ulaşılamadı" | kırmızı |
| 200 ama beklenmeyen gövde | "Cihaz yanıtı doğrulanamadı" | kırmızı |
| Yöntem tanımlı değil | "Bu cihazda uygulanmıyor" | gri |

Parola hiçbir hata mesajına eklenmez.

### Kimlik grubu

Varsayılan davranış yalnız seçilen cihazı doğrulamaktır. Kullanıcı iletişim
kutusunda
"aynı hesabı grupta kullan" derse kimlik `switch` / `video` grubu altına
da yazılır ve o gruptaki diğer cihazlar için kullanılır.

### Kapanış

Pencere kapanınca önce yeni köprü çağrıları reddedilir ve o anda çalışan
senkron çağrıların bitmesi süre sınırı olmadan beklenir. Ardından
`panel_api.temizle()` iş kuyruğunu iptal eder; IP atama işinin PoE portlarını
geri açan `finally` temizliği dâhil çalışan kuyruk işi tamamlanmadan süreç
sonlandırılmaz. Son olarak MQTT dinleyicisi kapatılır, konfigürasyon hedefleri
ve firmware seçimi silinir, **bütün kimlikler unutulur**. Yeni açılışta şifre
isteyen her cihaz için bilgi yeniden istenir.

---

## 5. Cihaz durumları

| Renk | Anlamı |
|---|---|
| **Yeşil** | Cihaza bağlanıldı ve beklenen/doğrulanabilir veri alındı |
| **Turuncu** | Cihaz erişilebilir ama kullanıcı adı/parola gerekiyor |
| **Kırmızı** | Zaman aşımı, bağlantı reddi, ağ hatası ya da doğrulanamayan yanıt |
| **Gri** | Bu cihazda yöntem uygulanmıyor ya da henüz okunmadı |

Grinin iki alt hâli ayrı tutulur: `okunmadi` ve `uygulanmiyor`. Ekranda
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
| Diğerleri | MQTT | `ALFA/DeviceMap` (saklanan, `retained`) | yok |

MQTT aracısına ulaşılamazsa ilgili cihazlar **gri** kalır ve nedeni yazılır —
"hatalı" gösterilmez, uydurma veri üretilmez.

#### Saklanan (`retained`) mesajın varlığı cihazın varlığı değildir

MQTT kaynaklı cihazlara panel **doğrudan bağlanmaz**; durumlarını
MQTT aracısındaki saklanan mesajlardan okur. Bu mesaj cihaz bağlantısı
kesildikten sonra da aracıda kalabildiği için tek başına erişilebilirlik
kanıtı değildir. Önceki davranışta bu durum, ağ bağlantısı olmayan ve IP
adresinde yanıt vermeyen bir HMI'ın, satır notu `disconnected` olduğu hâlde
yeşil "Doğrulandı" gösterilmesine yol açabiliyordu.

`core/okuma.py` iki bağımsız sinyali birlikte değerlendirir:

| Kaynak | Alan | Anlam |
|---|---|---|
| `ALFA/AppStatus/…` | `Status` | `connected` / `disconnected` |
| `ALFA/DeviceMap` | `Status.NoError` | PISCU'nun o anki izlemesi |

- Bağlantı düştüğünde MQTT **Last Will and Testament (LWT)** mesajı
  `{"ClientId": "…MCP…", "Status": "disconnected"}` biçiminde saklanmış
  olarak kalır. Bu yükte `DeviceIP`, `HWID` ve `Version` alanları bulunmaz; kayıt
  `ClientId` üzerinden eşleştirilir. `Status` alanı `connected` değilse cihaz
  artık kırmızı gösterilir.
- LWT yayınlanamadan güç kesilirse AppStatus kaydı `connected` kalmış
  olabilir. İkinci işaret bu yüzden var: PISCU'nun canlı kaydı cihazı
  arızalı bildiriyorsa (`NoError=false`, `Uptime=-1`) yeşile geçilmez.
- **`Has Network Failure` kullanılmaz.** Alanın çalışan PISCU kaydında da
  `true` olabildiği gözlendiğinden, tek başına cihazın yokluğunu göstermez;
  bu değerlendirmede `NoError` kullanılır.
- Arızalı bildirilen cihazın önceki **gri "uygulanmıyor"** eşlemesi kaldırıldı.
  Gri, denetimin o cihaz türüne uygulanmadığını ifade eder; denetlenip arızalı
  bulunan cihaz artık kırmızı "doğrulanamadı" durumuna geçer.

Dokuz MQTT kaynaklı cihazla yapılan ölçümde `NoError` değeri ile ICMP sonucu
tam olarak eşleşti; yalnız PISCU erişilebilirdi. Panel ayrıca ICMP sorgusu
göndermez: ICMP yalnız ağ erişimini, broker kaydı ise uygulama durumunu
gösterir.

Bazı alanlar birden çok kaynaktan beslenir; okuyucu bu verileri birleştirir:

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
  Dahili numara MQTT aracısındaki `ALFA/SipPort/<ip>` duyurusundan, PBX adresi
  ise (cihaz "registered" derken) setin PISCU'sundan tamamlanır. Değerin
  hangi kaynaktan geldiği cihaz detayında yazılır — cihazdan okunmamış bir
  değer okunmuş gibi gösterilmez.

Kontrol listesi `/api/kontrol` ucundan beslenir. Cihaz verisi değiştiğinde ve
ekran açık olduğunda sonuçlar en fazla 1,5 saniyede bir yeniden alınır; veri
değişmediyse istek yapılmaz. Böylece tarama sürerken eski satırların ekranda
kalması önlenir.

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
- İş yürütücüsü hatası (`is.hata`) ile cihaz bağlantı hatası (satır durumu) ayrı
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

## 7. Yenileme

Yenileme **sürekli**dir ve durdurulamaz (duraklat düğmesi yoktur). İki
ayrı hızda çalışır, çünkü iki farklı soruyu cevaplarlar:

| Tur | Aralık | Soru | Hedef |
|---|---|---|---|
| Keşif (tam tarama) | 60 sn | "Bu IP'de cihaz var mı?" | DeviceMap'teki **her** cihaz |
| Hafif yenileme | yaklaşık 2 sn | "Çalışan cihazın verisi ne?" | Yalnız **yeşil** cihazlar |

Ayrımın gerekçesi: ulaşılamayan cihaz okunurken zaman aşımı kadar
beklenir. Her turda bütün haritayı taramak, çalışan cihazların verisini
ölü cihazların zaman aşımı kadar bayatlatırdı.

- "Güncelle" düğmesi tarama **başlatmaz**, sıradaki keşif turunu **öne
  çeker**: işi hemen kuyruğa alır ve dakikalık sayacı sıfırlar.
- Keşif turu, oturum açılışında ve set değişiminde de kısa bir gecikmeyle
  çalışır; panel artık boş tabloyla açılmaz.
- Otomatik taramalar iş kaydında `otomatik` ile işaretlenir. Kuyruk
  geçmişinde yalnız en yenisi tutulur (`Yonetici._budama`) — yoksa
  dakikalık turlar yirmi dakikada bütün geçmişi dışarı iterdi.
- `setInterval` **kullanılmaz**: her tur, bir önceki istek bittikten sonra
  `setTimeout` ile kurulur. Aynı cihaz için istek birikmez.
- Tam tarama sürerken hafif yenileme çalışmaz; sunucu `409` döner.
- **Cihaza yazan koşu** (IP atama, konfigürasyon, yazılım yükleme)
  sürerken kendiliğinden tarama başlatılmaz; hafif yenileme de `409`
  alır (`panel_api.YAZAN_ISLER`). Kuyruk tek işçili olduğu için tam tarama
  bu koşularla zaten çakışamaz — elle istenen tarama kuyrukta bekler ve
  koşudan **sonra** çalışır. Hafif yenileme ise kuyruğa girmeden okuma
  yaptığı için tek çakışabilen yol odur, ayrıca engellenir.
- Tur başına en fazla `HAFIF_SINIR` (64) cihaz okunur, `HAFIF_WORKER`
  kadarı aynı anda.
- **MQTT telemetrisi tur başına toplanmaz.** `Telemetri.topla()` üç MQTT
  bağlantısı açıp saklanan mesajları bekliyor (yaklaşık 9 sn); bu, turun kendisini
  dokuz saniyeye çıkarıyor ve "birkaç saniyede bir yenileme"yi anlamsız
  kılıyordu. Keşif turunun topladığı görüntü `TELEMETRI_TTL` (90 sn)
  boyunca önbellekte tutulur, hafif turlar oradan okur.
  **Sonucu:** yalnız telemetriden beslenen cihazlar (`mqtt`, `app`) hafif
  turda en fazla bir keşif turu kadar eski veriyle görünür; asıl doğrulama
  onlarda dakikalık turdur. Doğrudan okunan cihazlar (`http`, `isapi`,
  `kyland`, `adb`) her hafif turda gerçekten okunur.
- Cihaz cevap vermeyi bırakırsa kırmızıya döner ve yeşil olmadığı için
  bir sonraki hafif turda listeden düşer; ona bir daha ancak keşif turu
  bakar.

---

## 8. API güvenliği

- Varsayılan masaüstü kipinde dinleyen TCP/HTTP soketi yoktur. Pywebview'a
  tek public `invoke()` metodu açılır; oturum anahtarı, yöntem, yol, gövde
  tipi ve boyutu doğrulanır. Dosya URL'leri, indirmeler ve uzaktan hata
  ayıklama kapalıdır.
- Yalnız açıkça seçilen tarayıcı/tanı kipinde `127.0.0.1` dinlenir;
  `panel_api.sunucu()` başka bir arayüz isteğini reddeder ve CORS açılmaz.
- Okuma, kimlik doğrulama, konfigürasyon ve yazılım yükleme uçlarında
  **istemci keyfî bağlantı hedefi seçemez**. Gövdeye `ip` ya da `type`
  eklemek hedefi değiştirmez; cihaz, DeviceMap'ten `cihazId` ile bulunur.
- IP atama ekranı, işlevi gereği fabrika adresi ile arama ağı/maske veya
  başlangıç-bitiş aralığı alır. Bu alanlar sunucuda IPv4 ve aday sayısı
  sınırından geçirilir; switch ve hedef cihazlar yine DeviceMap'ten seçilir.
- Tren seti `1..254` aralığına zorlanır (şablondaki `n` doğrudan IP'nin
  ikinci oktetine gider).
- POST gövdesi tip ve boyut denetiminden geçer (üst sınır 64 KB).
- Statik dosya servisi `resolve()` sonrası `static/` kökü altında olmayan
  her yolu reddeder.
- API yanıtlarında kullanıcı tarafından girilen parolalar, DeviceMap'in
  gizli alanları veya `Authorization` başlığı bulunmaz.
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
| IP Atama | DeviceMap'ten çıkan plan, canlı switch ön paneli, korunan portlar ve gerçek atama koşusu |
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

Liste **kendiliğinden tazelenir**: cihaz durumları her değiştiğinde
`/api/kontrol` yeniden okunur (bkz. `app.js acikEkraniTazele`; imza
değişmediyse istek yapılmaz). Başlığın altında verinin yaşı yazar —
saniyede bir kendini yeniler ve `BAYAT_SN`'i (120 sn) geçince turuncuya
döner.

**Excel üretmeden önce onay sorulur.** Kutu verinin yaşını, sayaçları ve
bayatsa bir uyarıyı gösterir; "Önce Güncelle" taramayı öne çeker.
Gerekçe sahadan: dosya üretildiğinde hangi ana ait olduğu bilinmiyordu ve
on dakika önceki okumadan çıkan Excel, onu imzalayan kişiye yanlış bir
"şu an böyle" belgesi veriyordu.

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
  cihaza yazılmaz; satırda nedeni ile birlikte `DeviceMap ✕` olarak görünür. Hatalı
  proje verisini cihaza yazmak, yanlış ayarı kalıcı hâle getirmek olurdu.
- Gruba yazılacak değer kutusu, o ayar gruptaki bütün cihazlarda aynıysa
  dolu gelir. Cihaza göre değişen alanda (dahili numara) bilerek boş kalır:
  tek numara gösterip kullanıcının bir harf değiştirmesi bütün gruba aynı
  numarayı yazdırırdı.
- Alan listesi **cihaz tipine göre** daralır; hangi alanın hangi uca
  gittiği `core/konfig.py` → `ROTA` tablosundadır (ayrıntı:
  `docs/CIHAZ_ENDPOINTLERI.md`). Cihaz tek bir "ayarları
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
  `panel_api.baslat()` açılışta geri yükler. Gizli alan (SIP parolası)
  dosyaya HİÇ girmez; bozuk dosya, tanınmayan alan ya da geçersiz değer
  sessizce atlanır — eski bir dosya yüzünden panel açılmaz olmamalı, cihaza
  da tanımsız değer gitmemeli. "Kayıtlı Değerleri Sıfırla" dosyayı siler,
  ekran DeviceMap değerlerine döner. Dosya proje ağacına ya da DeviceMap'in
  yanına yazılmaz (bir test bunu doğrular).
- Ekran **iki aşamalı** yüklenir: `/api/konfig/alanlar` cihaza hiç
  gitmez (alan listesi + hedefler + DeviceMap değerleri, yaklaşık 5 ms), cihazdaki
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

### IP atama = korunan portlar MAC tablolarından bulunur

Koşu, yönetilen PoE portlarını sırayla kapatıp açar. Bilgisayarın bağlı olduğu
portlar ile switch'ler arası bağlantı portları bu işlemin dışında tutulmalıdır.
İlk gruptaki bir portun kapatılması koşunun switch'e erişimini keser; ikinci
gruptaki bir portun kapatılması ise bağlantının arkasındaki switch'i tümüyle
ulaşılamaz duruma getirir.

Önceki sürümlerde bu bilgiler "Korunan bağlantılar" formuna elle giriliyordu;
form artık kullanılmaz. Hatalı giriş, korunması gereken bir portun koşuya
alınması veya geçerli bir hedef portun gereksiz yere dışlanması riskini
doğuruyordu. Portlar bunun yerine switch'lerin MAC öğrenme tablolarından
belirlenir:

1. `core/yerel_ag.py` bu bilgisayarın arayüzlerini, MAC'lerini ve
   IP'lerini verir. Bu bilgiler bütün switch'ler için bir kez okunur. Bir
   hedefe çıkan yerel adres, o hedefe UDP soketi
   *bağlayarak* (paket göndermeden) çekirdeğin yönlendirme tablosundan
   öğrenilir.
2. `core/switch_okuma.mac_tablosu()` bir switch'in öğrenme tablosunu
   `{mac: port}` olarak okur. Uçlar ve ayrıştırma **IP atama betiğinden**
   gelir (`MAC_ENDPOINTS`, `_parse_mac_table`); koşu da aynı tabloyu
   kullandığı için ikisi ayrışamaz.
3. `core/ip_atama.korunan_portlar()` bütün switch'leri **paralel** sorar
   ve iki kuralı uygular.

**Kural 1 — bilgisayarın MAC'i.** Bir switch'in hangi portunda
öğrenilmişse, o port o switch'e giden yoldur. Bilgisayarın doğrudan
takılı olduğu switch'te bu onun kendi portu; diğer switch'lerde o
switch'e ulaşmak için kullanılan uplink. İkisi de korunur.

Bilgisayarın **doğrudan** bağlı olduğu switch, ilgili portta öğrenilmiş MAC
sayısından belirlenir: erişim portunda tek cihaz bulunurken uplink portunda
switch'in arkasındaki birden çok cihaz bulunur. Liste sırası kullanılmaz;
komşu switch de bilgisayarın MAC adresini kendi uplink portunda görür.

**Kural 2 — komşunun kendi MAC'i.** Switch B'nin `basicInfo`'da bildirdiği
MAC, switch A'nın tablosunda hangi porttaysa A'nın B'ye giden bağlantısı
odur. Bilgisayarın yolu üstünde olmayan switch-switch bağlantıları ancak
bu yöntemle bulunur.

Ulaşılamayan bir switch keşfi sonlandırmaz; yalnız kendi zaman aşımından
sonra sonuç dışı kalır ve diğer switch'lerin paralel sorguları sürer.
`mac_tablosu()` bağlantı hatasında **kalan uçları denemez**; üç ucun ardışık
zaman aşımı toplam gecikmeyi yaklaşık on iki saniyeye çıkarırdı. "Switch
kapalı" (`UlasilamadiHatasi`) ile "switch bu ucu tanımıyor" (boş sözlük)
ayrı sonuçlardır ve arayüzde farklı açıklamalarla gösterilir. Bulunamayan
değerler **tahmin edilmez**; gerekli korunan port belirlenemezse koşu
başlatılmaz.

Bulgu tek seferlik değildir. Ekran açıkken
`KORUNAN_ARALIK` (30 sn) aralıkla yeniden doğrulanır — kablo koşu
başlamadan önce başka porta taşınmış olabilir. Koşu başlarken sunucu da
portları **yeniden keşfeder** (`/api/ip/kosu`); arayüzün gönderdiği
liste yalnız o an switch cevap vermezse kullanılan son bilgidir.

Bulgu ekranda ayrı bir formda değil, iki yerde görünür: ön panelde
korunan portlar turuncu, koşu özetinde "Bilgisayar → Yatakli_2 · p24" ve
"Korunan pN · sebep" satırları. Hangi MAC'ten, hangi arayüzden ve kaç
saniye önce doğrulandığı satırın ipucu metninde durur.

`yerel_ag.py` çıktıyı **etikete göre ayrıştırmaz**; örneğin `ipconfig /all`
Türkçe Windows'ta "Fiziksel Adres" etiketini kullanır. Çıktı bunun yerine
arayüz bloklarına ayrılır ve her blokta yerel ayardan bağımsız MAC ile IPv4
kalıpları aranır. IP karşılaştırmasında metin içinde arama yerine **tam
eşitlik** kullanılır; böylece `10.1.1.5` aranırken `10.1.1.50` adresinin
arayüzü seçilmez.

##### Konsol çıktısı bayt okunur, `text=True` kullanılmaz

Etiketten bağımsız ayrıştırma yetmedi: Windows'ta bilgisayarın switch
portu **hiç bulunamıyordu**, korunacak port listesi boş kalıyordu.

Sebep ayrıştırma değil, çözme (decode) adımıydı. `subprocess.run(...,
text=True)` çözümü Python'a bırakıyor, Python da Windows'ta **ANSI** kod
sayfasını seçiyor (Türkçe kurulumda cp1254). Oysa konsol araçları
**OEM** kod sayfasıyla yazıyor (cp857). `ipconfig /all` çıktısının ilk
satırındaki "Yapılandırması" kelimesinin `ı` harfi cp857'de `0x8d` ve o
bayt cp1254'te **tanımsız** → `UnicodeDecodeError`.

Bu istisna ne `OSError` ne `SubprocessError`; `_komut`'un `except`i onu
yakalamıyordu ve hata `/api/ip/korunan` ucuna kadar çıkıp 500
veriyordu. macOS ve Linux'ta hem çıktı hem tercih edilen kod sayfası
UTF-8 olduğu için arıza hiç görünmedi — testteki Windows örneği de
ASCII'ye sadeleştirilmiş ("Yapilandirmasi") olduğu için yakalanmamıştı.

Şimdi çıktı **bayt** alınıp `yerel_ag.coz()` ile çözülüyor: Windows'ta
`oem`, diğerlerinde `utf-8`, ikisi de bulunamazsa `latin-1` — hepsi
`errors="replace"` ile. Aranan her şey ASCII olduğundan (MAC kalıbı,
IPv4, arayüz adı) yanlış çözülmüş bir Türkçe harf ayrıştırmayı
etkilemez; yani `replace` burada kayıpsızdır ve "çözemedim" diye bir
durum kalmaz. Aynı çağrı Windows'ta `CREATE_NO_WINDOW` ile yapılır:
konsolsuz derlemede her komut bir konsol penceresi açıp kapatıyordu.

> **Zamanlayıcı davranışı.** IP ekranındaki turlar (`yenilemeyiKur`) her
> çizimde yeniden kurulduğunda, birkaç saniyelik cihaz yenilemesi hem 5
> saniyelik panel turunun hem de 30 saniyelik doğrulama turunun tamamlanmasını
> engelliyordu. Kurulmuş zamanlayıcı artık korunur; turlar ekrandan çıkılınca
> durur.

#### Gerçek koşu ve iptal davranışı

Panelden başlatılan IP atama işlemi bir önizleme değildir: koşucu,
`intercom_ip_assign.py` betiğini `--dry-run` seçeneği olmadan çalıştırır ve
cihazların ağ ayarları ile switch PoE durumunu gerçekten değiştirir. Fabrika
adresi, arama ağı/maskesi veya açık adres aralığı koşudan önce sunucuda
doğrulanır; aday adres sayısı `ARAMA_SINIRI` (512) ile sınırlıdır.

İptal eşgüdümlüdür. İş kuyruğundaki iptal bayrağı, betiğin bir sonraki tam
çıktı satırında `KeyboardInterrupt` akışına çevrilir. O anda sürmekte olan bir
HTTP isteği, bekleme veya cihaz yazımı zorla yarıda kesilmez; bu adım çıktı
ürettikten sonra kalan hedeflere ve sonraki cihaz gruplarına geçilmez. Betik,
temizlik aşamasında yönetilen PoE portlarını en fazla üç kez yeniden açmayı
dener. Bu girişimler başarısız olursa iş hata durumuna alınır ve switch
arayüzünden elle müdahale edilmesi gerektiği bildirilir. Temizlikten sonra
betiğin standart son doğrulaması tamamlandığı için iptal yanıtı anlık
olmayabilir.

Aynı fabrika adresini kullanan cihazlar arasında geçiş yapılırken ARP
önbelleğinin temizlenmesi gerekir. Yetki yoksa ekran koşudan önce uyarır ve
cihaz arama sonuçları bayat ARP kaydından etkilenebilir.

| | yetki | silme komutu | MAC okuma |
|---|---|---|---|
| POSIX | root ya da `sudo -v` | `arp -d` · `ip neigh flush` | `arp -n` |
| Windows | Yönetici (`IsUserAnAdmin`) | `arp -d` · `netsh … delete neighbors` | `arp -a` |

Windows sütunu **eskiden yoktu ve üç yerde birden bozuktu**:

1. `arp_silebilir()` orada koşulsuz `False` dönüyordu. `os.geteuid`
   Windows'ta yok; `AttributeError` yakalanıp "yetki yok" sayılıyordu.
   Yani uygulama **Yönetici olarak başlatılsa bile** ARP önbelleği hiç
   temizlenmiyordu. Karşılığı yükseltilmiş süreçtir, `sudo` değil.
2. Yetki uyarısı kullanıcıya `sudo -v` öneriyordu — Windows'ta öyle bir
   komut yok. Öneri metni artık platforma göre üretilir
   (`arp_yetki_ipucu`) ve arayüze `/api/ip/plan` içinde `arpIpucu` olarak
   gider; tarayıcı işletim sistemini tahmin etmez.
3. `host_mac()` `arp -n` çağırıyor ve MAC'i yalnız iki nokta ile arıyordu.
   Windows'ta `-n` diye bir seçenek yok (`-a` var) ve MAC tire ile
   yazılıyor. İkisi de tutmadığı için **MAC ile port doğrulaması
   Windows'ta sessizce hiç çalışmıyordu** — `verify_port` her seferinde
   "ARP'ta MAC yok" deyip doğrulamayı atlıyordu.

Betiğin iki `subprocess` çağrısı da artık `komut_ciktisi()` üzerinden
geçer: çıktı bayt alınır ve kod sayfası ne olursa olsun istisna atmadan
çözülür (yukarıdaki `text=True` tuzağının aynısı burada da vardı, üstelik
koşuyu ortasından düşürebilecek yerde).

### IP atama koşusunun ilerlemesi

Önceki uygulama, betiğin her çıktı satırını kuyruğa ayrı bir "adım" olarak
ekliyordu. Yaklaşık iki yüz satırlık çıktı oluşmasına karşın bu satırlar
sayaçlara katılmadığından ilerleme baştan sona **%0** görünüyordu; etkin aşama
ve kalan iş miktarı anlaşılamıyordu.

**Betik yeniden yazılmadı.** Saha tarafından doğrulanmış akış kardeş projeyle
ortaktır (§3). İlerleme raporlaması için bu akışı değiştirmek yerine betik
çıktısı `core/ip_atama.Ilerleme` içinde yapılandırılmış veriye dönüştürülür:

- Koşunun gerçek iş birimi **port**. Her hedef port için baştan bir satır
  açılır (`ozel_satir(..., sayilir=True)`).
- Betiğin işaretleri okunur: port başlangıcı, `[OK] Port N`,
  `[!] Port N: sebep`, `=== Tur N`, son özet tablosu. Son tablo **nihai durum
  kaynağıdır**; bir turda hata alan port sonraki turda tamamlanmış,
  "yazıldı" görünen bir port ise yeni adresinde cevap vermemiş olabilir.
- İşin aşaması (`Is.asama`) ayrı taşınır: "Port 14 · Cihaz aranıyor
  (3/12)", "Son doğrulama", "PoE portları geri açılıyor". Yüzde değeri tek
  başına etkin aşamayı belirtmediği için bu bilgi ayrı gösterilir.

Ham çıktı kaybolmaz: Belgeler klasörüne zaman damgalı bir günlük
dosyasına yazılır ve kuyrukta tek satırla açılır (`dosya.gunluk_yolu`).
Tamamlanamayan portların ayrıntılı hata çıktısı bu günlükte korunur.

#### Betik çıktısının ayrıştırılmasındaki üç özel durum

Bu durumların üçü de saha çıktılarında gözlendi ve testlerle sabitlendi
(`tests/test_ilerleme.py`, girdisi gerçek bir koşu günlüğüdür):

1. **Koşunun başındaki plan dökümü port başlangıcı değildir.** Betik
   önce planı yazar (`   port 11  ->  10.1.1.10`), ardından portları tek
   tek işler (`[1/12] Port 11 -> 10.1.1.10`). Sayacı aramayan bir
   kalıp, koşu daha ilk saniyesindeyken **on iki portu birden
   "çalışıyor"** gösteriyordu. Başlangıcın işareti `[i/n]` sayacıdır.
2. **`[OK] Port N` çoğu koşuda hiç yazılmaz.** Betik doğrulamayı sona
   bırakıyor (varsayılan `--defer-verify`): port turunda yazdığı satır
   `yazıldı (reset doğrulandı)`, teyit ise sondaki özet tablosunda yer alır.
   Yalnız `[OK]` işaretini bekleyen sayaç hiçbir portu tamamlanmış saymadığı
   için bütün satırlar sonuna kadar "çalışıyor" kalıyor, yüzde %0'da duruyor
   ve son tablo işlendiğinde %100'e çıkıyordu. Bu ara durum
   `ip_atama.YAZILDI` ("Yazıldı") olarak modellenir ve sayaçlarda
   "başarılı" değildir.
3. **`[!] Port 45 sn'de bağlanmadı` satırındaki sayı saniyedir, port
   değil**; hata kalıbı bu yüzden iki nokta arar.

#### Yüzde: aşama paylı

"Biten port / toplam port" oranı ertelenmiş doğrulama nedeniyle doğru
ilerlemeyi göstermiyordu (yukarıda 2. madde). Yüzde artık
`ip_atama.ASAMALAR` üzerinden hesaplanıp `Is.ilerleme_yaz()` ile yazılır;
paylar süreye göre değil saha ölçümlerine göre belirlenmiştir:

| aşama | pay | içeride neye göre ilerler |
|---|---|---|
| Hazırlık | %5 | — |
| Temel tarama | %7 | — |
| Port atama | %70 | biten port + süren portun kendi adımı |
| PoE geri açılıyor | %4 | — |
| Son doğrulama | %14 | özet tablosunda okunan satır |

Süren portun kendi adımları da ilerleme çubuğunu günceller (`PORT_ADIMLARI`: PoE
açılıyor → cihaz aranıyor → cihaz bulundu → IP yazılıyor →
doğrulanıyor). Tek bir portun bir dakikaya kadar sürebilmesi nedeniyle bu
ara adımlar da ilerleme değerine yansıtılır. İki kural uygulanır:

- **Yüzde geri gitmez** (`ilerleme_yaz` yalnız büyüğü yazar). İkinci tur
  ilerleme değerini azaltmaz.
- **Yarıda kesilen koşu %100 göstermez.** Çubuk ancak özet tablosu
  tamamlandığında dolar; iptal edilen koşu tamamlanmış gibi gösterilmez.

#### Satır altı adımlar (akordiyon)

Port başlangıcının altındaki ayrıntı satırları portun **adım geçmişi**
olur (`Is.adim_ekle`): "aralıktaki portlar kapatılıyor, 14 açılıyor…",
"cihaz bulundu: 10.1.1.12", "IP yazılıyor", "cihaz bulunamadı". Arayüzde
satıra basınca açılan bir akordiyonda, saatleriyle görünür; **varsayılan
kapalıdır**; böylece çok sayıda portun adımları kuyruk görünümünü gereksiz
ölçüde uzatmaz. Tek bir `not` alanında her yeni değer bir öncekini sildiği
için olay sırası korunamıyordu. Adımlar ikinci turda da silinmez; ilk turdaki
hata nedeni daha sonra incelenebilir. Satır başına en fazla
`isler.ADIM_SINIRI` adım tutulur (açık işin her yoklamasında arayüze
gidiyorlar).

### Adres haritası = "hangi adreste kim var"

Sahadaki en sık soru buydu ve cevabı yalnız dış araçlarla (`arp-scan`), o da
MAC düzeyinde alınabiliyordu: "10.1.1.13'te üç cihaz var" biliniyor ama
hangileri olduğu bilinmiyordu. Oysa intercom kendi **dahili numarasını**
bildiriyor (`pbxExtension`) ve DeviceMap aynı alanı taşıyor
(`PBXExtension`) — ikisi birleşince cümle tamamlanıyor: *"10.1.1.13'te
oturan cihaz aslında port 22'nin cihazı."*

`ip_atama.adres_haritasi()` aday adresleri (fabrika adresi + gruptaki
cihazların DeviceMap adresleri + verilmişse arama aralığı) **salt okuma**
yoklar ve her adres için satır üretir: DeviceMap'te kimin olduğu, şu an kimin
olduğu ve durum — `yerinde` / `yabanci` / `cakisma` / `bos` / `taninmiyor`.

Çakışma tek yoklamayla görünmez: adres her seferinde tek cihaz cevaplar. Bu
yüzden birkaç tur yoklanır ve turlar arasında ARP kaydı temizlenir; bir
adreste FARKLI dahililer görülmüşse orada birden çok cihaz var demektir.
Uç `GET /api/ip/harita`, iş kuyruğuna girmez (hiçbir şey yazmaz).

### Koşudan sonra kimlik denetimi

Betiğin `find_device` işlevi cihazı **uptime tahminiyle** seçiyor ve bulduğu
cihazın kim olduğuna bakmıyor (`pbxExtension` betikte hiç geçmez). Aynı
adreste iki cihaz varken yanlış olana yazmak bu yüzden mümkün — sahada
sonucu görüldü: üç cihaz tek bir hedef adreste toplandı, bir cihaz da başka
bir portun adresine yazılmıştı. "Port tamamlandı" demek yalnız "hedef adres
cevap verdi" demek.

Betik değiştirilmiyor (§3). Denetim koşudan SONRA panel katmanında yapılıyor
(`ip_atama.kimlik_dogrula`): her portun hedef adresi yoklanır, cevap verenin
dahilisi DeviceMap'teki cihazla karşılaştırılır. Sonuç port satırlarına
yazılır (`dogru` sessizce adım olarak, `yanlis` ve `cakisma` satırı KIRMIZI
yapar) ve iş özeti "cihazlar karışmış" der — bu, "port tamamlanamadı"dan
farklı ve daha ağır bir sonuçtur.

### Kalıcılık doğrulaması (isteğe bağlı)

"Yazıldı" ile "kalıcı yazıldı" aynı şey değil: cihaz ayarı yalnız belleğine
almış olabilir ve ilk güç kesintisinde eski adresine döner. Betiğin bunun
için bir kontrolü var (sonda portların gücünü bir kez kesip açar) ama koşuyu
uzattığı ve işi biten cihazları yeniden karartığı için panel onu varsayılan
olarak kapatıyor (`--no-persist-check`). Devreye alma bittiğinde bir kez
görmek isteyen kullanıcı için arayüzde **"Kalıcılığı doğrula (sonda güç
çevrimi)"** kutusu var; işaretlenirse bayrak gönderilmez ve betik kendi
kontrolünü yapar.

### Fabrika adresinde toplama (test akışı)

`core/ip_atama.fabrikaya_dondur`, koşuyu baştan denemek için gereken
başlangıç durumunu kurar: seçili intercomların hepsine "IP'ni fabrika
adresine çevir" isteği gönderilir. PoE'ye, switch ayarlarına ve
DeviceMap'e dokunulmaz.

İlk uygulama her cihaza **yalnız DeviceMap'teki adresinden** ulaşmayı
deniyor ve tek tur yürüyordu. Sahada iki durumda tıkanıyordu; ikisi de
`arp-scan` çıktısında görünür:

1. **Cihaz DeviceMap'teki adresinde değil.** İşlem bir kez çalıştıktan
   sonra cihazların çoğu zaten fabrika adresindedir; eski adreslerinde
   kimse cevap vermez. Bütün satırlar "cevap vermedi" uyarısı verip iş
   başarısız görünüyordu — oysa yapılacak bir şey kalmamıştı.
2. **İki cihaz aynı adreste** (`10.1.1.14 … (DUP: 2)`). O adrese giden
   tek istek yalnız birine ulaşır; ikincisi adres boşalana kadar görünmez.
   İşlem kaç kez tekrarlanırsa tekrarlansın bu iki cihaz orada kalıyordu.

Akış bu yüzden **tur tur** yürür: her turda bütün aday adresler (seçili
cihazların DeviceMap adresleri + verilmişse arama aralığı) yoklanır, cevap
veren her cihaz fabrika adresine yazılır, sonra adresin gerçekten boşaldığı
doğrulanır. Adres boşalınca arkasındaki ikinci cihaz görünür hale gelir;
hiçbir adres cevap vermeyene kadar tur tekrarlanır (`FABRIKA_TUR_SINIRI`).

Dört ayrıntı bu akışı doğru kılıyor:

- **Cihazın kimliği cihazdan sorulur: dahili numara.** Intercom
  `/api/v1/system/settings` yanıtında `pbxExtension` veriyor ve aynı alan
  DeviceMap'te de duruyor (`PBXExtension`). "Bu adreste cevap veren kim"
  sorusu böylece ARP'a, switch kimliğine ve MAC tablosuna hiç ihtiyaç
  duymadan yanıtlanıyor (`dahili_no`). Sahada `10.1.1.13`'te oturan cihazın
  aslında **port 22'nin** cihazı olduğu (dahili 2012) bu yolla görüldü.
- **Yazmanın kanıtı "adres sustu" değil, "oradaki cihaz değişti".** Aynı
  adreste iki cihaz varken biri taşındıktan sonra adres cevap vermeye devam
  eder. `_adres_bosaldi` bu yüzden cevabın kimden geldiğine bakar: dahili
  numara, yoksa cihazın bildirdiği MAC, yoksa ARP tablosu.
- **Satır, kesinlik sırasına göre seçilir:** dahili → port, sonra MAC → port
  (switch MAC tablosu), en son "bu adres DeviceMap'te kimin" varsayımı.
  Cihaz başka bir cihazın adresinde dururken satır yine doğru porta yazılır;
  seçili portların dışında kalan bir cihaza ise hiç dokunulmaz.
- **"Adresinde cevap yok" hata değildir**, `atlandi`'dır: cihaz büyük
  olasılıkla zaten fabrika adresindedir. İşi kırmızıya boyayan tek şey,
  cihazın eski adresinde **kalmasıdır** (`panel_api._ip_fabrika_hatasi`).
  Sonda fabrika adresi de bir kez yoklanır: orada da cevap yoksa cihazlar
  bu ağda hiç görünmüyor demektir ve bu bildirilir.

#### ARP temizliği: yoklamadan önce değil, gerekirse

Koşu turun başında bütün aday adreslerin ARP kaydını siliyor, sonra tek bir
yoklama yapıyordu. Sahadaki ölçüm bunun neden yıkıcı olduğunu gösterdi:

| adres | durum | yoklama süresi |
|---|---|---|
| `10.1.1.14` | ARP kaydı geçerli | **0,01 sn** — cevap |
| `10.1.1.10` | kayıt çözülmemiş | **2,00 sn** — zaman aşımı |

Kaydı silmek adresi baştan çözülmeye zorluyor ve çözümleme, yoklamanın kendi
zaman aşımından uzun sürebiliyor. Sonuç: cihazlar yerli yerinde dururken
**bütün satırlar "adresinde cevap yok"** oluyordu. İşin parmak izi buydu —
kaydı hiç silinmeyen tek adres (fabrika adresi) aynı koşuda sorunsuz cevap
veriyordu.

`_yokla` sırayı tersine çevirir: önce işletim sisteminin elindeki kayıtla
yoklanır (geçerliyse cevap milisaniyelerde gelir), **ancak cevap gelmezse**
kayıtlar temizlenip yeniden bakılır — bayat kayıt ihtimali ancak o zaman
anlamlı. Aynı sıra yazma sonrası kontrolde de geçerlidir (`_adres_bosaldi`):
tek sessizlik yetmez, kayıt temizlenip bir daha bakılır.

Yoklama tek denemeyle bitmez (`FABRIKA_YOKLAMA_DENEME` = 2) ama iki deneme de
FARKLI şeyi ölçer: birincisi eldeki kayıtla, ikincisi kayıt temizlendikten
sonra. Üçüncüsü aynı ölçümü tekrarlayıp koşuyu uzatmaktan başka bir şey
yapmıyordu.

#### Koşu neden uzun görünüyordu

Cihaz bulunmayan tekrarlar da "tur" sayılıyordu: iki cihazlık bir çakışmada
kullanıcı **"8. tur"** görüp işin uzadığını sanıyordu, oysa iş ikinci turda
bitmişti. Artık tur yalnız CİHAZ BULUNAN geçişleri sayar; boş tekrar aşama
metninde "yeniden bakılıyor (1/2)" olarak görünür. Ayrıca koşu zaten boş bir
yoklamayla bittiyse son kontrol tekrarlanmaz — aynı ölçümü ikinci kez yapmak
işi uzatmaktan başka bir şey yapmıyor.

Yapacak iş olmayan koşunun ölçülen süresi (12 cihaz, hepsi fabrika
adresinde): yetkili kipte **~16 sn**, ARP temizlenemeyen kipte ~64 sn — ikinci
sayı kaydın kendiliğinden dönmesini beklemenin bedeli.

#### ARP önbelleği temizlenemediğinde

Uygulama normalde yükseltilmiş yetkiyle açılır (bkz. `yetki.py`) ve
gerektiğinde ARP kayıtlarını temizler. Yetkinin olmadığı bir kurulumda (örneğin
panel doğrudan `python app.py --tarayici` ile geliştirme kipinde
çalıştırıldığında) aynı adresteki cihazlar **sırayla** görünür: kayıt taşınmış
bir cihazın MAC'ini gösterirken o adres "cevap vermedi" görünür.

Ölçüm: aynı adresi paylaşan cihazlar birbirinin ARP duyurusunu ezdiği için
işletim sisteminin kaydı kendiliğinden dönüyor — `10.1.1.13`'ün kaydı ~20
saniyede iki cihaz arasında gidip geldi. Akış bunu kullanır: boş geçen tur
işi bitirmez, `FABRIKA_TUR_ARASI` kadar beklenip `FABRIKA_BOS_TUR` kez daha
denenir. Yetki varsa boş tur gerçekten boştur ve beklenmez.

Sonuç yine de eksik kalabileceği için bu durum saklanmaz: koşunun ilk
satırında, "cevap yok" satırlarının notunda, son kontrolde ve iş özetinde
yetkinin olmadığı ve sonucun kesin sayılamayacağı yazar. Arayüz de fabrika
diyaloğunda düğmeye basılmadan önce uyarır (`/api/ip/plan` → `arpTemizlik`).

İlerleme koşuyla aynı biçimde raporlanır (`FabrikaIlerleme`,
`FABRIKA_ASAMALARI`): her hedef cihaz sayılan bir satır, satırın altında
kendi adımları, üstte aşama ve yüzde. Eskiden her çıktı satırı kuyruğa
bilgi satırı olarak giriyordu; bilgi satırları sayaçlara girmediği için
**yüzde baştan sona %0** kalıyordu. Davranış `tests/test_fabrika.py` ile
sabitlenmiştir.

### Tren seti değiştirme

Üst bardaki `SET n`, `1` ile `254` arasında tam sayı kabul eden bir sayı
alanıdır; hazır bir açılır liste değildir. Alan **rolden bağımsızdır** ve saha
kullanıcısı da set değiştirebilir. Sınırlar arayüze sunucu metadatasından gelir,
sunucu da gönderilen değeri aynı aralıkta doğrular.

Set değişince cihaz listesi, IP planı, kontrol listesi ve çıktı dosyası adı
yeniden hesaplanır; görünüm set başına tutulduğu için önceki setin sonuçları
taşınmaz. Elle başlatılmış tarama sırasında alan kilitlenir. Otomatik keşif
turu alanı kilitlemez; kullanıcı seti değiştirirse eski sete ait otomatik iş
için iptal istenir, ardından yeni set yüklenir ve ilk keşif turu planlanır.

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
kullanıcı seçim yapana kadar, en fazla 300 saniye bekler. Kullanıcı vazgeçerse
veya süre dolarsa eski seçim korunur. Linux'ta `zenity` ve `kdialog` ikisi de
yoksa işlem açık bir hata mesajıyla sonlanır. Yol arayüzde elle yazılmaz.

Olağan durum (bütün gruba aynı imaj) için ekranın üstünde tek bir düğme
var: aynı uç grup adıyla çağrılır ve dosya gruptaki her cihaza atanır.
Satırdaki "Değiştir" yalnız o cihazı etkiler, "×" seçimi kaldırır. Hedef
sürüm `POST /api/firmware/surum` ile dosyaya dokunmadan değişir.

`POST /api/firmware/dosya` (yolun doğrudan sunucuya verildiği uç) arayüzde
kullanılmaz; penceresiz çalıştırma ve testler için korunur.

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
birden ilerleme göstermek listeyi tarama süresince okunamaz hâle
getiriyordu.

Kuyruk satırlarında cihaz adı, IP ve durum bulunur. Hata sebebi satıra
yazılmaz (kuyruğu okunamaz hâle getiriyordu); ayrıntı satırın ipucu
metninde ve cihaz detayında durur.

Taramanın ilk saniyeleri MQTT telemetrisi toplamakla geçtiği için kuyruğa
bir ilerleme satırı düşülür ("Canlı MQTT telemetrisi"). Bu satır cihaz
sayaçlarına girmez — "42 cihazdan 7'si başarılı" derken araya bir ilerleme
satırı karışmamalı.

**Admin ekranında oturum sırasında girilen cihaz erişim kullanıcı adı ve
parolaları kaydedilemez.** Eski panellerdeki "kimlik bilgilerini dosyaya
kaydet", "parolayı sil" ve "parola kayıtlı" alanları yoktur; yalnız
bellekteki kimlikler unutulabilir. DeviceMap'te bulunabilen eski
`Username`/`Password` alanları bu ekranda gösterilmez ve erişim için
kullanılmaz (bkz. bölüm 4).

---

## 10. Arayüz kuralları

- Cihazdan gelen hiçbir değer `innerHTML` ile basılmaz. `static/js/core/dom.js`
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
| 3 | HTTP 200 dönen oturum açma HTML'i kabul edilmez | `test_switch.py` |
| 4 | 401/403 cihazı kilit listesine düşer | `test_kimlik.py` |
| 5 | Doğru bilgi → yeşil + kilitten çıkar | `test_kimlik.py` |
| 6 | Yanlış bilgi RAM kimliğini ezmez | `test_kimlik.py` |
| 7 | Kapanışta RAM deposu temizlenir | `test_kimlik.py` |
| 8 | Yeni süreçte önceki parolalar yok | `test_kimlik.py` |
| 9 | Oturumda girilen cihaz erişim parolası dosyaya yazılmaz | `test_guvenlik.py` |
| 10 | API ve kuyruk satırları parolasız | `test_guvenlik.py` |
| 11 | Aynı adlı farklı IP'li switch karışmaz | `test_switch.py` |
| 12 | Eski cevap yeni doğrulamayı ezmez | `test_kimlik.py` |
| 13 | Çift tıklama iki iş oluşturmaz | `test_kuyruk.py` |
| 14 | Aktif tarama varken ikincisi başlamaz | `test_kuyruk.py` |
| 15 | Kamera 401 kilit akışına girer | `test_kimlik.py` |
| 16 | Zaman aşımı ≠ yanlış parola | `test_kimlik.py` |
| 17 | Kimlik isteğinde hedef, istemci IP'sinden değil DeviceMap'ten alınır | `test_guvenlik.py` |
| 18 | İptal işi kontrollü sonlandırır | `test_kuyruk.py` |
| 19 | Ön yüz statik ve söz dizimi denetimi | `test_arayuz.py` |
| 20 | Hepsi tek komutla çalışır | yukarıdaki komut |

Ek olarak `tests/test_ilerleme.py`: IP atama koşusunun çıktısını gerçek
bir saha günlüğünden oynatıp aynı anda tek portun çalıştığını, portların
koşu içinde kapandığını, yüzdenin aşama payına göre ilerleyip geri
gitmediğini ve satır altı adımların doğru porta yazıldığını doğrular
(bkz. §9 "IP atama koşusunun ilerlemesi").

Ek olarak `tests/test_yetki.py`: yükseltilmiş yetki akışı — hangi platformda
hangi komutla yükseltildiği (paketlenmiş uygulamada `argv[0]`'ın tekrar
verilmemesi dahil), kullanıcının istemi reddetmesinin nasıl bildirildiği ve
"çıkış" seçildiğinde hiçbir servisin kurulmadığı. Testler pencere AÇMAZ.

Ek olarak `tests/test_fabrika.py`: cihazları fabrika adresinde toplama
akışını sahte bir ağ üzerinde oynatır — aynı adreste duran iki cihazın
ikisinin de toplandığını, eski adresinde cevap vermeyen cihazın hata
sayılmadığını, bulunan cihazın MAC üstünden kendi satırına yazıldığını ve
yüzdenin iş sürerken ilerlediğini doğrular (bkz. §9 "Fabrika adresinde
toplama"). Aynı sahte ağ üzerinde adres haritasının durumları
(`yerinde`/`yabanci`/`cakisma`), koşu sonrası kimlik denetiminin yanlış
cihazı yakalaması ve kalıcılık bayrağının betiğe doğru yansıması da
sabitlenmiştir. Üç akış da **hiçbir şey yazmadığını** ayrıca doğrular.

`tests/test_arayuz.py` içindeki `test_19c_ulasilmayan_modul_kalmaz`,
`app.js`ten başlayan içe aktarım ağacını yürüyüp hiçbir yerden çağrılmayan
JS modülü kalmadığını denetler: "bu dosya hâlâ kullanılıyor mu?" sorusu bir
kez elle grep'lenip yanlış cevaplandı, artık denetim testte.

Ek olarak `tests/test_kontrol.py`: şablon iskeletinin dosyadan geldiğini,
N/A ile "okunmadı"nın ayrı kaldığını, önizleme ile Excel çıktısının aynı
değeri verdiğini ve tarama sırasındaki canlı işlem durumunu doğrular.

Test 19 `deno lint` + `deno check` kullanır. Deno kurulu değilse test
atlanır; masaüstü artefaktını üretmek ve güncelliğini doğrulamak için tam
Deno 2.9.4 gerekir. Python söz dizimi denetimi her koşulda çalışır.

---

## 12. Bilinen sınırlar

- **IP atama koşusu** `intercom_ip_assign.py`'yi süreç içinde çalıştırır.
  Panel koşusu gerçek cihaz ve PoE durumuna yazar; `dry-run` değildir. İptal,
  betiğin tam çıktı satırları arasındaki güvenli noktalarda işlenir. Etkin ağ
  isteği zorla kesilmediği ve temizlikten sonra son doğrulama yürüdüğü için
  durdurma gecikmeli tamamlanabilir. PoE portlarını yeniden açma girişimi
  başarısız olursa elle müdahale gerekir (bkz. bölüm 9).
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
- **Linux dosya seçicisi** `zenity` veya `kdialog` gerektirir. İkisi de
  kurulu değilse firmware seçimi hata verir; arayüzde elle yol girişi yoktur.
