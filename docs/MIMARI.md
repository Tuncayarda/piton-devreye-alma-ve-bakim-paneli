# Devreye Alma ve Bakım Paneli — Mimari ve Çalıştırma

Tren setlerini sahada devreye almak için geliştirilmiş bir masaüstü
panelidir. DeviceMap topolojisini yükler, cihazları okur, kimlik isteyen
cihazları kilit menüsünde toplar ve kontrol listesini Excel'e döker.
Her müşteriye kendi paketi derlenir (§2.1); mühendis ekranları servis
anahtarıyla (§2.2) ya da imzalı bir uzaktan oturumla (§2.3) açılır.

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

Bağımlılıklar kurulduktan sonra açılış, **hangi müşterinin paketi olduğu
söylenerek**: `python3 app.py --edition vip-yatakli`. Çıplak `python3 app.py`
çalışmaz; geçerli adları yazıp 2 ile çıkar (§2.1).

| Komut | Ne yapar |
|---|---|
| `python3 app.py --edition <paket>` | HTTP/loopback kullanmadan pywebview penceresini açar |
| `python3 app.py --edition <paket> --browser` | HTTP tabanlı geliştirme/tanı kipini varsayılan tarayıcıda açar |
| `python3 app.py --edition <paket> --browser --port 8790` | Tanı servisinin portunu sabitler |
| `python3 app.py --edition <paket> --self-test` | Pencere/soket açmadan paketi, cihaz listesini ve üretim köprüsünü doğrular; cihaz ağına bağlanmaz |
| `python3 app.py --version` | Uygulama sürümünü yazdırır |
| `python3 -m panel.api --edition <paket> --port 8790` | Yalnız API (hata ayıklama) |
| `python3 -m unittest discover -s tests -t .` | Bütün testler |

### Yükseltilmiş yetki kapısı

Panel ağ arayüzünü ve ARP önbelleğini okuyup temizliyor, cihazlara IP yazıyor
ve switch portlarını yönetiyor. Bunlar sıradan kullanıcı yetkisiyle **sessizce
yarım** çalışıyor: en pahalı örneği ARP kaydının silinememesi, aynı adresteki
cihazların birbirinin arkasında kalması ve koşunun "cihaz bulunamadı" demesi
(bkz. §9). Bu yüzden yetkisiz kip yok.

Denetim `panel.elevation.is_elevated()` ile yapılır (POSIX'te `geteuid`, Windows'ta
`IsUserAnAdmin`) ve `--self-test` / `--version` dışındaki bütün kipleri kapsar;
o ikisi cihaza ve ağa hiç dokunmaz.

Yetki yoksa **doğrudan işletim sisteminin parola kutusu açılır.** Arada
panelin kendi penceresi yoktur.

Bir zamanlar vardı: "Yönetici olarak yeniden başlat / Çıkış" diye soran bir
pencere. Sorduğu şeyi veremiyordu — yetkiyi yalnız işletim sistemi verebilir —
ve kullanıcı aynı kararı iki kez veriyordu, önce bize sonra sisteme. Tek karar
için iki pencere. Artık soru sistemin kendi kutusudur.

Reddedilirse panel açılmaz. Ardından **sebebini söyleyen tek bir pencere**
çıkar ve içeri giden bir yol sunmaz; uygulamayı çift tıklayan biri, bir kez
zıplayıp hiçbir şey yapmayan bir simgeyle kalmasın diye. Üçüncü bir yol
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
reddederse sebep hem konsola hem o tek pencereye yazılır; sessizce kapanmak,
hatanın kendisiydi.

**Dock simgesi ancak devir gerçekleştikten sonra gizlenir.** Önceden yükseltme
denenmeden önce gizleniyordu; o zaman parola kutusu görünmeyen bir uygulamadan
geliyormuş gibi duruyor, başarısızlıkta da sebebi anlatan pencere öne
gelemiyordu. Şimdi `hide_dock_icon()` yalnız yeni süreç doğduktan sonra
çağrılır — o andan sonra eski sürecin gösterecek bir şeyi kalmaz.

Windows'ta paketlenmiş uygulamanın manifestine ayrıca yönetici isteği gömülür
(`uac_admin=True`, bkz. `dabp.spec`): çift tıklamada UAC önce
çıkar ve panel doğrudan yükseltilmiş açılır. Bu yol yine de gerekli — betikten
çalıştırma ve eski kısayollar bu manifestten geçmez.

Kimsenin başında olmadığı koşularda (CI, otomatik doğrulama) bekleyen bir
parola kutusu işi sonsuza kadar asar. `PANEL_ELEVATION_PROMPT=0` bu yüzden
artık **yükseltme denemesinin kendisini** de durdurur, yalnız pencereyi değil:
kendi penceremiz kalktığı için bu denetimden hemen sonrası sistemin parola
kutusudur ve akış ona ulaşmadan bitmelidir.

İki ayrıntı sahada ölçülerek eklendi:

- **Süreç kendiliğinden kapanmıyordu.** Pencere motorunun olay döngüsü
  kapandıktan sonra Cocoa/GTK iş parçacıkları süreci ayakta tutabiliyor;
  yükseltilmiş süreç başladıktan sonra eski süreç dışarıdan sonlandırılana
  kadar açık kaldı. `app._hemen_cik()` `main()` döndükten sonra yorumlayıcıyı
  doğrudan bitirir — kapatılacak bir şey kalmamıştır, servisler `main`'in
  `finally` bloğunda zaten kapanmıştır.
- **Yeni sürecin çıktısı bir günlüğe yazılır**
  (`panel.elevation.privileges.log_path()`, geçici dizinde
  `dap-elevation.log`). Arkaplandaki yükseltilmiş süreç
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
  anlamı yok: `panel.elevation.prompt.hide_dock_icon()` süreci Dock dışına alır
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

Admin moda geçişin bir parolası **yoktur** — eskiden vardı ve kaldırıldı.
İki kapı var: takılı bir servis anahtarı (§2.2) ve imzası doğrulanmış bir
uzaktan oturum (§2.3). İkisi de kanıtı sunucu tarafında denetlenir. Normal masaüstü kipinde dinleyen bir
sunucu yoktur ve köprü yalnız paket içindeki WebView'a açılır. İsteğe bağlı
tarayıcı kipi ise yalnız geri döngü arayüzünde (`127.0.0.1`) dinler.

---

## 2. Katmanlar

```
app.py            pywebview penceresi + uygulama ömrü (soket açmaz)
panel/
  settings.py     sabitler, yollar, portlar, süreler
  script_loader.py  kardeş projelerdeki çalışan betikleri içe aktarma
  credentials.py  RAM kimlik deposu (kalıcı depo YOK)
  errors.py       cihaz hatalarının sınıflandırılması
  status.py       yeşil/turuncu/kırmızı/gri kararı, nesil damgası
  i18n.py         iki dilli metin kataloğu (messages/tr.json, en.json)
  desktop/        tek public invoke() içeren pywebview köprüsü + tek HTML
  api/            ortak servis katmanı, yol tabloları, yetki süzgeci,
                  isteğe bağlı HTTP adaptörü
  editions/       paket tablosu: hangi paket hangi projeyi/ekranı taşır (§2.1)
  adminkey/       servis anahtarı, mühürlü haritalar (§2.2)
  remotekey/      imzalı uzaktan oturum: QR eşleşmesi ve hesapla giriş (§2.3)
  authority.py    admin modu kim açık tutuyor — kimse kalmayınca kapanır
  elevation/      yükseltilmiş yetki kapısı ve yeniden başlatma (§1)
  inventory/      DeviceMap envanteri, IP şablonu çözümü, kategoriler
  probe/          okuma dağıtıcısı: switch (KYLAND), anons, kamera/NVR
                  (ISAPI), ADB, MQTT telemetri
  jobs/           FIFO iş kuyruğu + tarama görünümü
  ip_assign/      IP atama planı, korunan portlar, koşu ve ilerleme
  network/        bu bilgisayarın kendi adreslerinin hazırlanması
  system/         arayüz/MAC bilgisi ve işletim sistemi dosya seçicisi
  config_sync/    konfigürasyon oku/karşılaştır/yaz
  firmware/       yazılım yükleme (anons: HTTP imaj, LCD: adb APK)
  checklist/      Excel şablonunun ön izlemesi ve çıktısı
  video_config/   kamera/NVR yapılandırma akışı
field_scripts/    sahada doğrulanmış üç betik (§3)
static/           modüler kaynaklar + üretilmiş tek parça desktop.html
tools/            masaüstü paketleyicisi, paket bilgisi, anahtar araçları
tests/            unittest paketi + sahte cihazlar
```

Tarayıcı tanı kipinde `static/js` doğrudan ES module olarak servis edilir.
Üretim masaüstü kipinde aynı modül grafiği Deno 2.9.4 ile IIFE'ye paketlenir;
CSS, logo ve favicon ile birlikte `static/desktop.html` içine gömülür.
`app.py` bu dosyayı belleğe okuyup `create_window(html=...)` ile açar ve
yalnız `PanelBridge.invoke` metodunu `Window.expose(...)` izin listesine
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
Köprü yanıtları `{ok, status, body}` zarfındadır. `panel.api` aynı çağrıyı
işler; HTTP Handler yalnız ayrıştırma/serileştirme adaptörüdür.

### 2.1 Paketler — her müşteri kendi programını alır

Tek program, birden çok paket. Bir müşterinin teknisyeni cihaz listesini
açtığında başka bir müşterinin envanterini, adreslerini ve dahili
numaralarını **bulamamalıdır**; bu yüzden ayrım bir tıklamayla geri
alınamayacak yerde, **derleme anında** yapılır. Her paket yalnız kendi
DeviceMap'ini taşır.

Tablo `panel/editions/catalogue.py` içindedir ve **yalnız standart kütüphane
kullanır**: `dabp.spec` bu dosyayı `importlib` ile doğrudan yükleyip
çalıştırılabilir adını, ürün adını ve paketlenecek cihaz listesini oradan
okur (spec `panel`'i içe aktaramaz — derleme ortamında `requests` yoktur).

Paketler arasında **kodda hiçbir dal yoktur**. Bir müşterinin görmemesi
gereken ekran, o paketin `views` listesinde bulunmaz; hem kenar çubuğu hem
de API süzgeci aynı listeyi okur (`panel/api/guard.py`), böylece "ekranı
gizlemek" ile "verisini reddetmek" ayrışamaz. Ekranı gizlemek tek başına
hiçbir şey değildir: köprü bütün API'yi sayfaya açar.

Hangi paket olduğu şu sırayla belirlenir:

1. **paketlenmiş build'de damga** (`panel/editions/_stamp.py`, derlemede
   üretilir) — ve yalnız o. Müşteri kendi paketini `--edition` ile başka bir
   paket gibi başlatamaz: bayrak sessizce yok sayılmaz, **reddedilir**.
2. kaynaktan `--edition`
3. kaynaktan `DAP_EDITION`
4. hiçbiri — ve bu bir hatadır, varsayılan değil.

Bir paket birden çok proje taşıyabilir (`vip-yatakli`: Yataklı ve VIP); üst
çubuktaki proje adı o zaman bir menüdür. Proje değiştirmek DeviceMap'i,
ayarları ve kuyruktaki cihaz sonuçlarını birlikte değiştirir — cihaz
kimlikleri konumsaldır ("sw1.d3" başka projede başka bir cihazdır), o yüzden
eski projeye ait sonuç yeni projede gösterilmez. Cihazlara **yazan** bir iş
sürerken proje değiştirilemez.

Ayarlar da paket başına ayrı klasörde tutulur (`panel/settings.py:data_dir`):
GDM için girilen bir hedef değer Gaziray'da o yuvadaki donanıma yazılırdı.

### 2.2 Servis anahtarı — cepte taşınan kapı

Mühendis ekranları (Proje & Cihaz Listesi, PISCU, MQTT, ADB, Switch) admin
modda açılır. Admin moda geçişin parolası, gizli tıkı ve komut satırı
seçeneği **yoktur**; iki yol var, bu birincisi: panelin tanıdığı bir anahtar
dosyası (`panel/adminkey/`). İkincisi uzaktan oturum, §2.3. Dosya iki yerde aranır: takılı bir USB bellekte —
normal kullanım, anahtar taşınan fiziksel bir şeydir — ve uygulamanın kendi
klasöründe, çünkü uzaktan bağlanılan bir makinede belleği takacak kimse
yoktur. İkisinde de aynı doğrulamadan geçer; klasördeki kopyanın vazgeçtiği
tek şey fizikselliktir.

Bunun için iki değer ve aralarında tek yönlü bir işlev vardır:

```
S = build sırrı              yalnız derlemeyi kesen kişide
K = pbkdf2(S, tuz, 600k)     ANAHTAR DOSYASINA yazılan değer
D = sha256(K)                PAKETE gömülen değer
```

Paket `D`'yi taşır. Bir belleği doğrulamak `sha256(K') == D` — hızlıdır,
saniyede birkaç kez yapılabilir. Tersi mümkün değildir: `D`'den `K`
üretilemez, yani **paket bellek üretemez**; `K`'den `S` üretilemez, yani
kaybolan bir bellek sırrı ele vermez. Hiçbir pakete `S` gömülmez; CI bunu
çıkan paketten geri okuyarak denetler.

İlk bellek, bellek takılarak yazılamaz. Önyükleme bu yüzden sırrın kendisidir:
sırrı ortamında ya da ağacın kökündeki `.adminkey-secret` dosyasında tutan
bir **kaynak** çalıştırması hiçbir şey takılmadan admin açılır ve ilk belleği
yazabilir. Paketlenmiş build ne ortam değişkenine ne o dosyaya bakar.

| Parça | Görevi |
|---|---|
| `secret.py` | `S → K → D` ve neyin kabul edileceği |
| `keyfile.py` | Bellekteki dosya: savunmacı okuma, atomik yazma |
| `volumes.py` | Belleğin üç işletim sisteminde nerede göründüğü |
| `handback.py` | macOS'ta çıkarılabilir disk iznini işletim kullanıcısının oturumuna devretme |
| `handoff.py` | Sırrın yükseltme penceresini geçmesi (dosya yolu taşınır, değer taşınmaz) |
| `media.py` | Belleği silip FAT32 kurma (panelin veri yok eden tek işlemi) |
| `pack.py` | Bellekte taşınan ek proje cihaz listeleri |
| `vault.py` | Bir dosyayı yalnız `K` açacak biçimde mühürleme (şifrele-sonra-MAC, yalnız stdlib) |
| `sealed.py` | Pakete gömülü mühürlü haritaları admin modda açma — YALNIZ admin modda: anahtarın görülmesi yetmez, alan kipinde başka müşterinin haritası geçici dizine hiç çözülmez; açılanlar (proje, anahtar) başına bir kez çözülür |
| `watcher.py` | Belleğin takılı olup olmadığını **bildirme** (§2.3, `authority.py`) |

**Bellek çıkarılınca admin modu kapanır** — anahtarı anahtar yapan da budur.
Ama artık iki kaynak var, o yüzden kapatma kararı `panel/authority.py`'ye
taşındı: her izleyici yalnız kendi gördüğünü **bildiriyor** (`report("key",
…)`, `report("remote", …)`) ve `settle()` hiçbirinin tek başına
cevaplayamadığı soruyu cevaplıyor — kapıyı hâlâ tutan var mı? USB izleyicisi
uzaktan oturumdan habersiz olduğu için, bu ayrım olmadan az önce açılan bir
uzaktan oturumu iki saniye içinde kapatıyordu. `settle()` kararı vermeden
hemen önce kaynakları kilit altında bir kez daha okur: karar ile uygulama
arasında bağlanan bir uzak oturum, bir saniye içinde geri kapatılmaz.

`authority.py` **asla açmaz**, yalnız kapatır. Giriş, kanıtı denetleyebilen
yerde hak edilir — birimin yeniden okunduğu `admin_routes.post_mode`,
imzanın denetlendiği `remote_routes` — böylece bir bildirme hatası yetki
yükseltmesine dönüşemez.

Tek istisna, cihazlara yazan bir iştir: yarım kalmış bir IP ataması ya da
yazılım yüklemesi, kapıyı birkaç dakika daha açık tutmaktan kötüdür; kapanma
kuyruk boşalana kadar bekletilir ve rozet bunu söyler.

İzleme, sorunun **ucuz yarısını** (hangi birimler bağlı — bir glob ve bir
stat) 0,35 sn'de bir, tamamını (belleği okumak) değişimde ve 2 sn'de bir
sorar. Sebebi ölçülmüştü: çıkarma anında algılanıyor, takma geç
algılanıyordu — 2 sn'lik tek nabız, bağlanması 1-2 sn süren bir birimi hep
kaçırıyor.

macOS'ta çıkarılabilir diskler ayrı bir gizlilik iznine bağlıdır ve panel
yükseltilmiş çalıştığı için o izin onda yoktur: bellek görünür, üzerindeki
her dosya `EPERM` döner. Okuma bu yüzden klavyedeki kullanıcının oturumuna
devredilir (`handback.py`). **Sıralama kritiktir**: ölçüldü, ilk soran taraf
bütün süreç ağacı adına karar veriyor — önce panel kendi adına sorup
reddedilirse devretme de reddediliyor.

### 2.3 Uzaktan oturum — imzalı ikinci kapı

Servis anahtarı "mühendis burada mı?" sorusunu bir bellekle cevaplıyor.
Uzaktaki bir makinede belleği takacak kimse olmadığı için aynı soru ağ
üzerinden de sorulabiliyor — geride yarın yine cevap verebilecek bir şey
bırakmadan (`panel/remotekey/`).

**Özel anahtar bu depoda yok.** Ayrı ve private bir depodaki Cloudflare
Worker'da duruyor; panel yalnız **doğrulama** yapıyor (`ed25519.py`, RFC 8032,
içeri alınmış, imza üretemez). Paket hangi açık anahtarlara güvendiğini
`verify.py`'de taşıyor.

İki yol var, ikisi de aynı yerde bitiyor:

| Yol | Nasıl |
|---|---|
| **QR eşleşmesi** (`pairing.py`) | Panel servisten bir kare ister, ekrana koyar, birkaç saniyede bir "onaylandı mı" diye sorar. Onaylayan turu **admin moda geçiren tur** olur. |
| **Hesapla giriş** (`account.py`) | Makinenin başındaki mühendis kendi e-postası ve parolasıyla girer; servis bu kuruluma bağlı bir oturum üretir. |

Ortak nokta: **modu sunucu açar**, imzayı denetledikten sonra. İkisi de
`WATCH.connect()` yoluna girer, dolayısıyla kanıtın denetlendiği tek bir yer
vardır.

```
protocol.py   meydan okuma, ve bir cevabın reddedilme sebeplerinin tamamı
session.py    bu kurulumun kendine verdiği rastgele ad
client.py     panelin internete konuştuğu tek yer
watcher.py    nabız, ve modu bitiren süre
```

Birkaç karar bilerek böyle:

- **Kareyi servis çiziyor, panel değil.** Gelen SVG bir `<img>` içinde
  base64 `data:` kaynağı olarak gösteriliyor — `<img>` içindeki SVG şartname
  gereği durağandır, betik çalışmaz. Karşılığında panel karenin işaret ettiği
  adresin **derlenmiş servis adresiyle harfi harfine aynı** olduğunu
  doğruluyor: kare bir telefonu bir sayfaya gönderiyor.
- **Yerel son kullanma yok.** Sürenin bittiğini servisin cevabı söylüyor;
  panelin duvar saati bir ay şaşabilir.
- **Parola tek bir alanda ve tek bir istek gövdesinde.** `state`'e girmiyor,
  yeniden denemek için saklanmıyor, cevap gelir gelmez alan siliniyor —
  hangi cevap gelirse gelsin.
- **Oturum iade ediliyor.** Admin moddan çıkarken ya da uygulama kapanırken
  servise haber veriliyor; oturum tek makineye bağlı olduğu için iade
  edilmezse yuva boşa yanar.

Ağ giderse ya da oturum telefondan kapatılırsa nabız bunu birkaç saniyede
buluyor ve mod düşüyor — cihazlara yazma sürüyorsa §2.2'deki istisna burada
da geçerli.

---

## 3. Çalışan kodu yeniden yazmama

Panel iki betiği **çalışma anında içe aktarır** (`panel/script_loader.py`),
kopyalamaz:

| Betik | Ne için |
|---|---|
| `field_scripts/device_verify.py` | Excel şeması ve alan tabloları |
| `field_scripts/intercom_ip_assign.py` | IP atama koşusu |

Switch erişimi üçüncü bir betikti; artık paketin içinde, `panel/switch/`
altında ve **panelin tek switch istemcisi**. IP atama ekranının ön paneli,
factory-reset doğrulaması ve Switch ekranı aynı `switch.CLIENT`'tan geçer:
URL, HTTP Basic kimlik doğrulama biçimi, port, zaman aşımı, HTTP başlıkları
ve "JSON gelmiyorsa oturum açılması gerekiyor" kuralı tek yerde tanımlıdır.
İki istemci, timeout'un ne olduğu ve bir yanıtın ne zaman "giriş gerekli"
sayılacağı konusunda ayrışır — o gün bir ekranda çalışan hesap diğerinde
"doğrulanamadı" demeye başlar.

`kimlik` her çağrıda açıkça verilir; istemci hiçbir parola tutmaz ve hiçbir
depoya bakmaz (`panel/credentials.py`).

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
                       └─ POST /api/credentials  {cihazId, kullanici, parola}
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

`panel/probe/reader.py` iki bağımsız sinyali birlikte değerlendirir:

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

Kontrol listesi `/api/checklist` ucundan beslenir. Cihaz verisi değiştiğinde ve
ekran açık olduğunda sonuçlar en fazla 1,5 saniyede bir yeniden alınır; veri
değişmediyse istek yapılmaz. Böylece tarama sürerken eski satırların ekranda
kalması önlenir.

---

## 6. Tarama ve iş kuyruğu

Açılışta **hiçbir cihaza bağlanılmaz**; yalnız yerel DeviceMap yüklenir.
Önceki oturumdan kimlik yüklenmez.

"Güncelle" → `POST /api/scan` → FIFO kuyruğa iş eklenir.

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
- **Her iki otomatik tur da duraklatılabilir** (üst çubuktaki düğme,
  `state.autoRefresh`; karar `static/js/core/schedule.js` içinde). Sebebi:
  cihaz okumak bedava değil — Kompartıman LCD adb üzerinden okunur ve tur,
  o panelde çalışan kişinin adb oturumunu elinden alır. Duraklatma yalnız
  **panelin kendiliğinden** başlattığı turları durdurur: "Güncelle" ile
  istenen tarama da, kuyruktaki iş de çalışmaya devam eder. Tercih diske
  **yazılmaz**; ertesi sabah duraklatılmış açılan bir panel, sebebini
  söylemeden dünkü okumaları gösterirdi. Duraklatıldığı sürece durum
  metni "son tarama ..." yerine bunu söyler.
- Tam tarama sürerken hafif yenileme çalışmaz; sunucu `409` döner.
- **Cihaza yazan koşu** (IP atama, konfigürasyon, yazılım yükleme)
  sürerken kendiliğinden tarama başlatılmaz; hafif yenileme de `409`
  alır (`panel.jobs.writing`; kuyrukta BEKLEYEN yazan iş de sayılır —
  tek işçi bir sonraki saniye ona başlayacaktır). Kuyruk tek işçili olduğu
  için tam tarama
  bu koşularla zaten çakışamaz — elle istenen tarama kuyrukta bekler ve
  koşudan **sonra** çalışır. Hafif yenileme ise kuyruğa girmeden okuma
  yaptığı için tek çakışabilen yol odur, ayrıca engellenir.
- Tur başına en fazla `HAFIF_SINIR` (64) cihaz okunur, `HAFIF_WORKER`
  kadarı aynı anda.
- **MQTT telemetrisi tur başına toplanmaz.** Toplama artık TEK bağlantıdır
  ve saklanan mesaj patlaması durulunca biter (`telemetry.client`,
  IDLE_CUTOFF; tavan `MQTT_TIMEOUT`) — eskiden üç bağlantı ve iki dolu
  pencereyle ~9 sn tutuyordu. Önbellek yine de durur: saniyenin altındaki
  bir toplama bile 2 sn'lik hafif turun tekrarlayacağı bir broker gidiş
  gelişidir ve ulaşılamayan broker her seferinde bağlantı zaman aşımını
  ödetir. Keşif turunun topladığı görüntü `TELEMETRI_TTL` (90 sn) boyunca
  önbellekte tutulur, hafif turlar oradan okur.
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
  `panel.api.http_adapter.serve()` başka bir arayüz isteğini reddeder ve CORS açılmaz.
- Tanı kipinde POST'lar çapraz-kaynaklıysa reddedilir (Host/Origin geri
  döngü olmalı, gövde `application/json` beyan etmeli — ön uçtaki her sayfa
  127.0.0.1'e erişebilir ve "simple" bir POST'un yan etkisi cevabı okumadan
  gerçekleşir); HTML yanıtlarına `'self'` CSP başlığı eklenir. Masaüstü
  paketi kendi, daha sıkı CSP'sini taşır.
- Okuma, kimlik doğrulama, konfigürasyon ve yazılım yükleme uçlarında
  **istemci keyfî bağlantı hedefi seçemez**. Gövdeye `ip` ya da `type`
  eklemek hedefi değiştirmez; cihaz, DeviceMap'ten `cihazId` ile bulunur.
- IP atama ekranı, işlevi gereği fabrika adresi ile arama ağı/maske veya
  başlangıç-bitiş aralığı alır. Bu alanlar sunucuda IPv4 ve aday sayısı
  sınırından geçirilir; switch ve hedef cihazlar yine DeviceMap'ten seçilir.
- Tren seti `1..254` aralığına zorlanır (şablondaki `n` doğrudan IP'nin
  ikinci oktetine gider). **Gövdesinden set çözen her POST katı çözücüden
  geçer** (`inventory_for_write`): geçersiz ya da eksik set 400 alır, sessizce
  Set 1'e düşmez — düşse işlem başka bir trene yönelirdi. Hoşgörülü çözücü
  yalnız GET ekranlarının açılışında kalır.
- "Bulunamadı" yalnız panelin kendi `NotFoundError`'ıdır; bir handler
  hatasından sızan çıplak `KeyError` 404 maskesine girmez, 500 olarak
  günlüklenir.
- POST gövdesi tip ve boyut denetiminden geçer (üst sınır 64 KB).
- Statik dosya servisi `resolve()` sonrası `static/` kökü altında olmayan
  her yolu reddeder.
- API yanıtlarında kullanıcı tarafından girilen parolalar, DeviceMap'in
  gizli alanları veya `Authorization` başlığı bulunmaz.
- Ham yığın izi yalnız sunucunun kendi hata çıktısına gider; kullanıcı
  "Panelde beklenmeyen bir sorun oluştu" görür.
- **IP atama koşusu sürerken o switch'e ekrandan yazılamaz.** Koşu, switch'i
  saha betiğinin kendi istemcisiyle sürer ve `switch.CLIENT`'ın yazma
  kilidini dakikalarca tutamazdı; bunun yerine koşu bir sahiplik bırakır
  (`claim_run`) ve Switch ekranının yazma uçları 409 ile bekletir.

---

## 9. Ekranlar

| Ekran | İçerik |
|---|---|
| Genel Bakış | KPI'lar, kategori durumu, sistem özeti, son işlemler |
| Tüm Cihazlar | Kategori + durum filtresi; cihazın son bilinen durumu |
| Cihaz detayı | Kimlik / Ağ / SIP blokları, kimlik gir, kimliği unut |
| **Kontrol Listesi** | Çıktının ön izlemesi (şablonun tüm sütunları) + kategori filtresi |
| IP Atama | DeviceMap'ten çıkan plan, canlı switch ön paneli, korunan portlar ve gerçek atama koşusu |
| Konfigürasyon | Cihazdaki değer ↔ hedef değer karşılaştırması |
| Yazılım Yükleme | Cihaz başına dosya seçimi (.bin / .apk), gruba toplu atama |
| PISCU & PBX | MQTT istemcileri, SIP dahili numaraları |
| MQTT İzleme | Canlı akış (kullanıcı başlatır, tampon sınırlı) |
| Proje & Cihaz Listesi | DeviceMap, tren seti, kategori tanımı, servis anahtarı yazma (yalnız admin modda) |
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
sütun adları ile gri (N/A) hücreler `panel/checklist/columns.py` tarafından
doğrudan şablon dosyasından okunur. Kodda ayrı bir kolon listesi
tutulmaz: şablon değişince liste de değişir. `panel/checklist/workbook.py` aynı
eşlemeyi kullandığı için ekranda görünen değer ile dosyaya yazılan değer
aynıdır — bir test bunu doğrudan karşılaştırır.

Üstteki kategori şeridi listeyi filtreler: yalnız seçilen kategorideki
cihazlar gösterilir. 23 sütun sığmadığı için tablo kendi içinde yatay
kayar; sayfa gövdesi kaymaz.

Liste **kendiliğinden tazelenir**: cihaz durumları her değiştiğinde
`/api/checklist` yeniden okunur (bkz. `app.js`'teki `VIEW_LIFECYCLE` tablosunun enter kancası; imza
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
  gittiği `panel/config_sync/fields.py` → `ROUTES` tablosundadır (ayrıntı:
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
- Ekran **iki aşamalı** yüklenir: `/api/config/fields` cihaza hiç
  gitmez (alan listesi + hedefler + DeviceMap değerleri, yaklaşık 5 ms), cihazdaki
  değerler arkadan `/api/config` ile gelir. Tek istek beklenirken grup
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

1. `panel/system/interfaces.py` bu bilgisayarın arayüzlerini, MAC'lerini ve
   IP'lerini verir. Bu bilgiler bütün switch'ler için bir kez okunur. Bir
   hedefe çıkan yerel adres, o hedefe UDP soketi
   *bağlayarak* (paket göndermeden) çekirdeğin yönlendirme tablosundan
   öğrenilir.
2. `panel/probe/switch.mac_table()` bir switch'in öğrenme tablosunu
   `{mac: port}` olarak okur. Uçlar ve ayrıştırma **IP atama betiğinden**
   gelir (`MAC_ENDPOINTS`, `_parse_mac_table`); koşu da aynı tabloyu
   kullandığı için ikisi ayrışamaz.
3. `panel/ip_assign/ports.protected_ports()` bütün switch'leri **paralel** sorar
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
portları **yeniden keşfeder** (`/api/ip/run`); arayüzün gönderdiği
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
yakalamıyordu ve hata `/api/ip/protected` ucuna kadar çıkıp 500
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
çıktısı `panel/ip_assign/progress.py` içinde yapılandırılmış veriye dönüştürülür:

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
(`tests/test_progress.py`, girdisi gerçek bir koşu günlüğüdür):

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

### Adres yazılmadan önce yazılım yükleme

Sahadan gelen ikinci arıza: trenlere uzun süre önce gönderilmiş bazı
intercomların yazılımı, **kendi sürümünü ve kimliğini yanlış bildirecek kadar**
eski. Bu cihazlara başka bir şey yapılmadan önce yazılım atılması gerekiyor.

Bunun mümkün olduğu **tek an koşunun içi**. Koşu PoE portlarını teker teker
açar; o anda tek bir cihaz erişilebilir ve hâlâ fabrika adresindedir. Bir
dakika sonra kendi adresine geçmiş ve birbirinden ayırt edilemeyen on iki
cihazdan biri olmuştur — Yazılım ekranından hangisine ne atılacağı artık
bilinemez.

Bu yüzden adım saha betiğinin port döngüsünün **içine** girer.
`intercom_ip_assign.py` içine tek bir uzatma noktası eklendi:

```
BEFORE_WRITE(port, ip, settings, cfg) -> (ok, note)
```

Betik tek başına çalıştırıldığında `None`'dır ve hiçbir şey değişmez; paneli
koşudan önce kurar, sonra da **mutlaka geri alır** (süreç geneli durum;
bırakılırsa sonraki koşu istemediği hâlde yazılım atar). Bütün mantık
`panel/ip_assign/preflash.py` tarafında.

**Ne zaman yükler.** Seçeneğin açık olduğu her portta. Karşılaştırılacak bir
"beklenen sürüm" yok: bu adımın var olma sebebi zaten sürümünü yanlış ya da
hiç bildirmeyen cihazlar, dolayısıyla karşılaştırmanın tek dürüst cevabı
"bilemiyorum" olurdu ve bu hiçbir zaman "güncel" sayılamazdı. Sürüm yine de
yükleme öncesi ve sonrası okunur; yalnız koşu günlüğünde görünmek için.

**Yükleme başarısız olursa port başarısızdır ve IP yazılmaz.** Yazılımı
atılamamış bir cihazı adresine taşımak, sorunu gizlemek olurdu.

Dosya **koşu için tektir**, cihaz başına değil: adım gerçekleştiği anda cihaz
fabrika adresindedir ve on iki intercomdan hangisi olduğunu söylememiştir —
cihaz başına seçim, tam da bu adımın çözdüğü sorunun cevabını varsaymak olur.

**Dosya yolu tarayıcıya hiç gitmez.** Kullanıcı dosyayı işletim sisteminin
kendi penceresinden seçer, panel yolu kendinde tutar; ekran yalnız dosyanın
adını ve boyutunu görür. İş günlüğü dosyalarındaki kuralın aynısı — istemcinin
okuyabildiği yol, istemcinin gönderebildiği yoldur.

Geri bildirim koşunun kendi biçiminde: port satırının altında `firmware`
adımı (`PORT_STEPS`, yüzdenin %70'i), yüklenen/atlanan/başarısız her cihaz
için bir cümle.

### Compartment LCD ADB devreye alma koşusu

Compartment LCD, Intercom'un ortak fabrika adresi ve HTTP yazıcısını
kullanmaz. `DeviceMap` şablonunun **Set 1 çözümü** her cihazın kaynak
adresidir (`10.1.1.40 … 10.1.1.50`); seçili set çözümü hedef adresidir
(`10.<set>.1.40 … .50`). Plan satırı bu nedenle cihaz başına `sourceIp` ve
`targetIp` yayımlar.

İki uç da koşu seçeneğidir, sabit değil: `sourceSet` cihazların **şu an**
bulunduğu seti, `targetSet` gidecekleri seti söyler. Varsayılanları set 1 ve
açık settir; **fabrika sıfırlama ikisini yer değiştirir** (`targetSet=1`) ve
tek kullanıcısı odur. Arayüzde "cihazları şu setten şu sete taşı" diye bir
seçenek yoktur; sahada işe yaramadığı için kaldırıldı. Hedef önek ayrı bir
seçenektir ve **boş bırakılması "belirtilmedi" demektir** (`parse_prefix`
uçlarda `default=0` ile çağrılır): kararı `effective_prefix` verir —
operatörün yazdığı, yoksa projenin beyanı (Gaziray `/16`), en son `/24`.
Uçların boş kutuyu doğrudan 24'e çevirmesi projenin dalını erişilmez
kılıyordu; Intercom koşusunda ise belirtilmemiş maske hiç yazılmaz, cihaz
kendi maskesini korur (`panel/ip_assign/runner.py`). Koşu sonundaki
doğrulama da aynı öneki arar (`panel/ip_assign/addressing.py`).

`panel/ip_assign/runner.py` grup bazındaki koşucuyu
`RUNNERS["Compartment LCD"]` üzerinden `lcd_runner.py`'ye yollar. Akış her
port için şöyledir:

1. Yönetilen portlar kapatılır; sıradaki port ve daha önce tamamlanan portlar
   açık tutulur.
2. Yalnız o cihaza ait kaynak ve hedef adres denenir. ADB transportu her
   komutta açıkça `-s <ip>:5555` ile belirtilir; `adb devices` sırası ya da
   örtük "geçerli cihaz" hiçbir kararda kullanılmaz.
3. Android seri numarası okunur ve adresin MAC'i switch tablosunda beklenen
   portla eşleştirilir. İkisinden biri doğrulanamazsa cihaza yazılmaz.
4. Kullanıcı APK adımını açtıysa mevcut cihaz/set kapsamlı firmware seçimi
   kullanılır. `adb install -r` ve sürüm denetimi kaynak adreste tamamlanmadan
   IP komutu gönderilmez.
5. Tek bir `su -c` işlemi içinde `eth0` global IPv4 adresleri temizlenir,
   hedef `/24` eklenir ve bağlantı açılır. Adres silindiğinde ADB yanıtının
   düşmesi beklenir; komutun dönüşü başarı kanıtı değildir.
6. Eski ve yeni ADB transportları ayrı ayrı kapatılır. Yeni adrese sınırlı
   sayıda yeniden bağlanılır; seri numarası, MAC→port eşleşmesi ve `eth0`
   global IPv4 kümesinin tam olarak `{hedef/24}` olması doğrulanır. Eski bir
   `/16` ya da ikinci bir global adres kalırsa port başarısızdır.

`adb kill-server` kullanılmaz; başka ekranların ya da başka uygulamaların ADB
oturumlarına dokunulmaz. Her portun `finally` adımı hem kaynak hem hedef
transportu temizler. Koşu, hata ve iptal yollarının ortak son adımında bütün
yönetilen PoE portlarını üç denemeye kadar yeniden açar.

IP ekranındaki işlem switch'i, DeviceMap cihaz eşlemesinden ayrı bir fiziksel
sınırdır. LCD-only planda kullanıcı örneğin `sw2` seçtiğinde PoE, MAC tablosu,
erişim kimliği ve iş anahtarı `sw2` üzerinden yürür; `deviceSwitchId` ise
DeviceMap'teki tek kanonik LCD düzenini gösterir. Cihaz kimliği, görünen adı,
portu, kaynak IP'si ve hedef IP'si bu kanonik kayıttan sunucu tarafında yeniden
çözülür ve istek gövdesinden alınmaz. Seçilen switch'in gerçekten Switch
olması ve cihazın MAC'inin seçilen fiziksel portta görülmesi yazımdan önce
zorunludur. Bu çapraz-switch eşleme yalnız Compartment LCD grubuna açıktır.

LCD planında `rows` seçilen **fiziksel** PoE portlarını, `candidateRows` ise
DeviceMap'teki değiştirilemez cihaz/port/kaynak/hedef kayıtlarını taşır. Bu
yüzden DeviceMap'te boş olan port 8 de çalışma portu olabilir; port numarası
hiçbir zaman ilk adaya ya da aynı numaralı DeviceMap satırına körlemesine
bağlanmaz. Port tek başına açılınca aday kaynak ve hedef adresleri iki zaman
sınırlı paralel turda denenir, exact ADB transportu ile Android seri numarası
okunur ve MAC→port kanıtı alınır. Bulunan IP hangi `candidateRows` kaydına
aitse yalnız o kaydın hedefi yazılır. Daha önce kullanılan cihaz aynı koşuda
ikinci fiziksel porta atanmaz; yanlış-port ve kalan ADB transportları temizlenir.
Fiziksel izin listesi PoE yüzüyle sınırlıdır (`1..SWITCH_POE_PORTS`); uplink ve
korunan port denetimleri ayrıca sürer. Intercom planı DeviceMap portlarına
bağlı kalır.

Intercom'un HTTP/PBX kimlik denetimi LCD sonuçlarına uygulanmaz; LCD kimliği
koşucu içinde seri + switch portuyla doğrulanır. Aynı nedenle HTTP tabanlı
adres haritası ucu Compartment LCD grubunu reddeder.
`POST /api/ip/factory-reset` ise grubu görüp yol ayırır: Intercom için HTTP
üzerinden ortak fabrika adresinde toplama, Compartment LCD için `targetSet=1`
ile sıradan ADB koşusu. APK dosya yolu IP isteğinin gövdesinden alınmaz; sunucu, firmware
seçimini set ve DeviceMap cihaz kimliğiyle kendi belleğinden bulur.

### Tek porta elle IP atama (LCD tezgâh akışı)

`POST /api/ip/lcd-assign` → `lcd_runner.run_manual()`. `post_run`'dan ayrı bir
uçtur, çünkü sözleşmesi terstir: `post_run`'da hangi adresin nereye gideceğine
DeviceMap karar verir ve istemci yalnız port seçer; burada **adres isteğin
kendisidir**. Bu yüzden ayrı uç, ayrı doğrulama ve ayrı iş gövdesi
(`lcd_manual_task`).

Ekranın şu anki adresi istenmez — tezgâhta bilinmeyen şey odur. Port izole
edildikten sonra `manual_candidates()` listesi taranır: DeviceMap'teki bütün
Compartment LCD satırlarının set 1, açık set ve (verilmişse) `sourceSet`
karşılıkları, artı istenen adresin kendisi. Sonuncusu aynı yazımın ikinci kez
zararsız olmasını sağlar.

Kanıt kuralı sıradan koşuyla aynıdır ve gevşetilmez: yalnız seçilen port
beslenir, cevap veren adresin MAC'i o portta görülmeden komut gönderilmez,
sonrasında aynı Android seri numarası yeni adreste ve `eth0` üzerinde başka
global adres kalmamış olarak bulunmalıdır. Fark yalnızca hedefin yazılmış
olması ve sonrasında bir DeviceMap kimliği iddia edilmemesidir.

### Cihaz ayarlarında Compartment LCD: tek yazılabilir alan

`config_sync` bir cihazın ayarlarını, o cihazın kendi web arayüzünün POST
ettiği uca yazar. Android ekranın böyle bir ucu yok. `ROUTES` tablosuna bu
yüzden HTTP olmayan tek bir işaret eklendi — `ADB_NETWORK = "adb:network"` —
ve altında tek alan var: `ipAddress`. İşaret bilinçli olarak `ENDPOINT_ORDER`
dışındadır; HTTP yazma döngüsü ona asla POST etmez.

Okuma ve yazma `panel/config_sync/adb_network.py` içinde, `lcd_runner`'ın
küçük açık yüzeyi (`connect`, `addresses`, `serial_of`, `write_address`)
üzerinden yapılır. İki uygulama olmaması özellikle önemli: "yazıldı" sözünün
anlamı iki ekranda da aynı kalmalı.

**Maske korunur.** `eth0` hangi öneki kullanıyorsa yazımdan sonra da odur.
Maskeyi değiştirmek devreye alma kararıdır ve IP atama ekranındaki alana
aittir; "adres" yazan bir ayar satırının sessizce ağ maskesini değiştirmesi
beklenmez. `eth0` üzerinde birden çok global adres varsa hangisinin geçerli
olduğu **tahmin edilmez**, hata verilir: bu, yarım kalmış bir koşunun bıraktığı
durumdur ve gizlenmemelidir.

DeviceMap'teki `IP` alanı **şablondur** (`10.n.1.40`). `_project_target`
bu alanı özel olarak ele alır ve hedef olarak envanterin açık set için çözdüğü
adresi verir; ham şablon hedef gösterilseydi ekran hiçbir cihazın taşıyamayacağı
bir adres isterdi.

### Kamera ve NVR: alan değil, prosedür

Anons cihazında bir ayar bir alandır: uca gövde gider, geri okunur,
karşılaştırılır. Kamerada değildir. Saat ve NTP yazılır, akış profilleri üç
kanala birden gider, 3. akış **kapalıyken 103 numaralı kanal yoktur**, onu
açmak cihazı yeniden başlatır ve profil ancak cihaz geri geldikten sonra
yazılabilir. Sıra, işin kendisidir.

Bu yüzden prosedür `panel/video_config/` paketindedir: `isapi.py` (TEK
ISAPI taşıma katmanı — oturum `trust_env=False`, digest ve "yazma kabul
edildi mi" kuralı; tarama tarafı `probe/camera.py` de buradan geçer),
`procedure.py` (kamera ile NVR'ın paylaştığı sıralı adımlar: saat/NTP
yazımı, disk biçimlendirme, yeniden başlatma; `WRITE_TIMEOUT` 10 sn),
`payloads.py` (sahada kanıtlanmış XML gövdeler), `channels.py` (NVR kanal
listesi), `camera.py`, `nvr.py`, `defaults.py`, `health.py`.

Ekran, hedef değerler, kimlik bilgileri ve iş kuyruğu yine `config_sync`'in:
`fetch()` ve `apply_targets()` cihazın okuma yöntemine göre dallanıyor
(`adb`, `http`) — video için üçüncü dal `isapi` eklendi. `read_state()` düz
bir sözlük döndürdüğü için satırlar aynı `_rows()` ile üretilir; ikinci bir
ekran, ikinci bir rota, ikinci bir iş tipi yoktur.

`ROUTES` tablosuna `ISAPI_CAMERA` / `ISAPI_NVR` işaretleri eklendi — tıpkı
`ADB_NETWORK` gibi bir uç değil, bir prosedürün adı. Eşleme anahtarı da
değişti: tablo artık SubType değil **scope** eşliyor. Anons ailesinde scope
zaten SubType'tır; kamerada SubType proje sözlüğüdür (`Corridor`, `Landing`,
bazı projelerde hiç yok) ve ISAPI yüzeyi hakkında hiçbir şey söylemez, o
yüzden video tarafında scope cihazın **Type**'ıdır (`config_scope`).

Kurallar:

- **Ağ ayarına dokunulmaz.** Sahadaki `nvr.py`'nin `set_network_mask` adımı
  şunu yapıyor: `PUT` `[OK]` dönüyor, sonra cihaz kendi adresinde yok.
  Geri getirmenin yolu kabinde elektrik kesip SADP ile IP vermek. Panelden
  geri alınamayacak tek ayar bu olurdu, o yüzden port edilmedi: adres ve
  maske SADP'nin işi, panel ikisini de **okuyup** raporluyor (doğrulama
  sütununda "Maske", ayar penceresinde salt okunur satır).
  `isapi.interface_mask` bu yüzden tam eşleşme arar — yanlış arayüzün
  maskesini raporlamak, doğru kurulmuş bir cihazı hatalı göstermektir.
- **Hareket algılama yoktur.** VMD tetikçisi ve takvimi yalnız Gaziray'da
  kullanılıyor; panele bilerek alınmadı.
- Sağlam disk biçimlendirilmez; yalnız `unformatted` / `uninitialized` /
  `error` durumundaki disk. Bir ayar uygulanırken kayıt silinmez.
- NVR kanal tablosu koda gömülmedi: kameranın `CameraID` ve `CameraName`
  alanları DeviceMap'te zaten var, liste oradan türer. Projeye kamera
  eklemek kod değişikliği gerektirmez.
- NVR kanal gövdesi **kameranın** parolasını taşır (NVR kameraya kendisi
  bağlanır). Panel parola saklamadığından değer o oturumun bellekteki
  kimlik bilgisinden gelir; yoksa hangi kameranın kimliğinin gerektiği
  söylenir.
- Doğrulama kuralı gevşetilmedi: hedef, cihazdan geri okunmadan "yazıldı"
  sayılmaz. NVR'da geri okuma yeniden başlatmadan **önce** yapılır — kapanan
  cihaz hiçbir soruya cevap vermez.
- Hiçbir şey değişmediyse NVR yeniden başlatılmaz. Değişiklik olmayan bir
  koşu için seti yayından düşürmek kabul edilebilir bir maliyet değildir.
- Prosedür her adımını `report(metin, durum)` ile anlatır; `config_task` bunu
  `job.add_step` ile cihazın satırının altına yazar. Tek satırlık not bir
  prosedürün ancak son adımını taşıyabiliyordu.
- Doğrulama turu (`panel/probe/camera.py`) saat/NTP/maskenin yanına
  `video_config/health.py` kontrollerini ekler: NVR'da disk ve buzzer,
  kamerada SD kart, IR ve 3. akış. Okunamayan kontrol "uygun" demez.
  `health.buzzer_on` hem taramanın hem yazma yolunun kullandığı tek okumadır;
  tetikçi listesi bildirim yöntemi taşımıyorsa `diskerror`/`diskfull` adıyla
  sorulur.

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
Uç `GET /api/ip/address-map`, iş kuyruğuna girmez (hiçbir şey yazmaz).

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

### Kalıcılık doğrulaması (devre dışı)

"Yazıldı" ile "kalıcı yazıldı" aynı şey değil; ancak betiğin sondaki güç
çevrimi koşuyu uzatıyor ve işi biten bütün cihazları yeniden karartıyordu.
Bu nedenle kalıcılık seçeneği arayüzden kaldırıldı ve panel çalıştırıcısı
her koşuda `--no-persist-check` gönderiyor. Eski bir istemci artık bu denetimi
yeniden açamaz. Her port için yazmadan hemen sonra yapılan sıradan adres
okuma denetimi devam eder.

### Fabrika adresinde toplama (test akışı)

`panel/ip_assign/factory_reset.py`, koşuyu baştan denemek için gereken
başlangıç durumunu kurar: seçili intercomların hepsine "IP'ni fabrika
adresine çevir" isteği gönderilir. PoE'ye, switch ayarlarına ve
DeviceMap'e dokunulmaz.

IP atama ekranında kaynak olarak **bulunduğu set** ya da **harici set**
seçilir. Harici set numarası `1..254` aralığında zorunlu doğrulanır ve hedef
adresler o set için DeviceMap'ten yeniden çözülür; geçersiz değer hiçbir zaman
sessizce Set 1'e düşmez. Hedef yine seçili fabrika IP adresidir.

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

Uygulama normalde yükseltilmiş yetkiyle açılır (bkz.
`panel/elevation/`) ve
gerektiğinde ARP kayıtlarını temizler. Yetkinin olmadığı bir kurulumda (örneğin
panel doğrudan `python app.py --edition <paket> --browser` ile geliştirme
kipinde
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

### Bilgisayarın ağı = eksik alt ağ adresini panel kendisi ekler

**Bir tren setinde iki ağ gerekir, bir değil.** Operatör 8. seti seçtiğinde
cihazlar hâlâ fabrikadan geldikleri `10.1.1.x` adresindedir; switch'ler ve
yazılacak adresler ise `10.8.1.x`. `required_networks` ikisini de ister.

Ağı hazırlamak **cihazla konuşan her işin** ilk adımıdır: tarama, IP atama,
LCD elle atama, fabrika sıfırlama, **cihaz ayarları ve yazılım yükleme**. Son
ikisi uzun süre bu listede değildi; set değiştirip doğrudan o ekranlara giden
biri sebebi görünmeden her satırda "cihaza ulaşılamıyor" alıyordu.
`tests/test_network.py` bu listeyi kaynakta denetler.

Panel hangi arayüzün cihazlara gittiğini **bilmiyorsa hiçbir şey eklemez** ve
bunu `needsAdapter` ile söyler. IP ekranı bu durumda koşuyu başlatmaz —
başlatsa her portta "cihaz bulunamadı" derdi — ve Ağ ekranına giden bir
düğme gösterir. Arayüz seçimi kaydedilemezse bu da bir hata olarak bildirilir;
sessizce yutulduğunda ekran "seçildi" diyor ama sonraki açılış yine soruyordu.



Sahadan gelen arıza: bilgisayar `10.17.1.222/24`, switch'ler `10.17.1.100` ve
`10.17.1.101`, intercom'lar ise fabrika adresi olan `10.1.1.12` üzerinde.
Switch'ler sorunsuz okundu — aynı /24 içindeler. Cihazlar okunamadı: bu
bilgisayarın `10.1.0.0/16` içinde hiçbir adresi yok, dolayısıyla fabrika
adresine giden her yoklama **paket makineden çıkmadan** başarısız oldu. Koşu
bütün portlarda "cihaz bulunamadı" bildirdi; adresi sistem ayarlarından elle
eklemek gerekti.

Fabrika adresi sete göre değişmez (bir cihaz fabrikadan hangi sete gireceğini
bilmeden çıkar), bu yüzden projenin kendi ağıyla neredeyse hiçbir zaman aynı
/24 içinde olmaz. Arıza, yapılandırılmamış her cihazda tekrar eder.

`panel/network` bu adımı üstlenir. Bir koşu, fabrika sıfırlama, tarama veya
adres haritası başlarken:

1. **Gereken ağlar hesaplanır** (`planning.required_networks`): fabrika
   adresinin /24'ü, setin kendi ağı, IP ekranında verilen arama aralığı.
   Bilgisayarın **zaten içinde bulunduğu** ağlar listeden düşülür —
   `10.1.0.0/16` üzerindeki bir makine `10.1.1.12`'ye zaten erişir.
2. **Arayüz seçilir** (`adapters.choose`) — ya da seçilmez. Yalnız iki şey
   sayılır, ikisi de bu makineye ait **olgu**: kullanıcının Ağ ekranındaki
   seçimi, sonra hedef ağlardan birinde **halihazırda adresi olan** arayüz.
   Sıra önemli: önce fabrika ağı (`10.1.1.x`) bakılır — bir cihazın geldiği
   ağ orasıdır ve ilk koşudan sonra panelin kendi `10.1.1.225`'i de o
   kartadır — sonra switch'lerin ağı.

   **Üçüncü bir cevap yoktur.** Önceki sürüm hiçbiri tutmadığında sıralamaya
   (taşıyıcı, kablolu, adresli) düşüyordu ve telefonuna bağlanmış bir
   dizüstünde **telefonu** seçti: adres hiçbir yere gitmeyen bir karta
   eklendi, koşu eskisi gibi başarısız oldu, ekran ise bir arayüz seçildiğini
   yazıyordu. Yanlış tahmin, cevapsızlıktan kötüdür — artık hiçbir şey
   eklenmez, Ağ ekranı arayüzü sorar ve tek tıkla iş biter. Yönlendirme
   tablosuna da **bakılmaz**: eşleşen yol yokken çekirdeğin cevabı yine
   varsayılan yolun arayüzü, yani telefondur.
3. **Adres seçilir** (`planning.choose_host`): varsayılan son oktet `225`,
   doluysa `226…240`. DeviceMap'in planladığı adresler, fabrika adresi ve
   bilgisayarın kendi adresleri elenir.
4. **Adres eklenir** (`aliases.add`). Kayıt **komuttan önce** yazılır: ikisi
   arasında öldürülen bir süreç de arkasında temizlenecek bir iz bırakır.
   Komut 0 döndürse bile adres arayüzde **görünmüyorsa** eklenmiş sayılmaz.
   Kaldırmada da simetrik: komut başarısızsa ve adres hâlâ arayüzdeyse
   **kayıt silinmez**. Silmek daha kötüydü — adres kartta kalıyor, onu
   gösteren hiçbir kayıt kalmıyordu, dolayısıyla bir sonraki açılışın
   temizleyeceği bir şey de yoktu. Yetkisiz bir sürecin, yetkili bir sürecin
   eklediğini geri alamaması bunu sahada üretti.

| sistem  | ekleme | kaldırma |
|---------|--------|----------|
| macOS   | `ifconfig <dev> alias <ip> netmask <maske>` | `ifconfig <dev> -alias <ip>` |
| Linux   | `ip addr add <ip>/<önek> dev <dev>` | `ip addr del <ip>/<önek> dev <dev>` |
| Windows | `netsh interface ipv4 add address name=<idx> … store=active` | `netsh … delete address … store=active` |

Windows'ta `store=active` taşıyıcı bir ayrıntı değil: adresi kayıt defterine
yazmaz, yani süreç öldürülse bile adres yeniden başlatmada gider. `netsh set`,
`New-NetIPAddress` ve `networksetup` **hiçbir zaman** kullanılmaz; üçü de var
olan yapılandırmayı değiştirir ya da kalıcı yazar. Yine Windows'ta `netsh`'in
istediği bağlantı adı `ipconfig` çıktısından okunamaz — blok başlığı yerel
dilde yazılır — bu yüzden arayüz **indeksi** kullanılır; indeks tek bir
PowerShell çağrısıyla, sekmeyle ayrılmış ve yerelleştirilmemiş biçimde alınır.

macOS'ta maske **yazma anında** seçilir (`aliases.alias_prefix`), sabit
değildir. Sebebi: macOS bir alt ağın yolunu onu talep eden adrese bağlar ve
adres gittiğinde bu bağı korur. Arayüzde zaten aynı /24'ten bir adres varken
tam maskeyle eklenen alias yolu devralır; `ifconfig -alias` sonra adresi siler
ama **yolu ona bağlı bırakır**. Arayüz canlı bir adres taşımaya devam eder,
o ağdaki her yol ölü adresi gösterir ve içindeki her `connect()` anında
EADDRNOTAVAIL ile düşer. Sahada bir oturum kapandıktan sonra bütün bir /24
böyle öldü: kırk iki cihazlık tarama, tek bir paket çıkmadan milisaniyelerde
"cihaza ulaşılamıyor" verdi. Yolu zaten taşıyan bir adres varsa alias `/32`
alır — host alias yolu hiç sahiplenmez, dolayısıyla öksüz de bırakamaz — tam
maske yalnızca yolu ilk kuran biz olduğumuzda kullanılır. Kardeş bir `/32`
"yol var" saymaz, yoksa yol hiç kurulmaz ve her koşuda bir adres birikirdi.

`panel/network/routes.py` bunun ikinci yarısıdır ve hiçbir şey hazırlamaz:
yönlendirme tablosunu geri okur (`netstat -rnl`, RT_IFA sütunu yalnızca
BSD'de vardır) ve kaynak adresi artık makinede olmayan ağları bildirir. Bu
durum onu yaratan süreçten uzun yaşar, adres silen başka araçlarla da
oluşabilir ve cihaz tarafından bakınca **ölü donanımdan ayırt edilemez** — bir
öğleden sonraya mal olan da buydu. Her hazırlık adımı bunu kontrol eder ve
kuyrukta tek bir uyarı satırı olur; onarım ayrıcalıklı route cerrahisi
gerektirir, yapılmaz, satır ne yapılacağını söyler. Aynı arıza cihaz tarafında
`panel.errors` içinde EADDRNOTAVAIL olarak yakalanır ve "cihaza ulaşılamıyor"
yerine bilgisayarı işaret eden kendi mesajını alır.

Adresler oturum boyunca durur — koşudan sonraki tarama, konfigürasyon ve
firmware ekranları da aynı erişime muhtaçtır — ve uygulama kapanırken
`panel.api.lifecycle.reset()` içinde geri alınır. Çökme hâlinde kayıt dosyası
sahipsiz kalır; bir sonraki açılış `sweep_stale()` ile bunları temizler. Kaydın
sahibi hâlâ yaşıyorsa bu başka bir panel kopyasının işidir ve dokunulmaz.

İşlem **sormadan** yapılır ama sessiz değildir: eklenen her adres kuyrukta bir
satır olur ve Ağ ekranında listelenir. Başarısızlık işin hatası değil, uyarı
satırıdır — bilgisayar cihazlara buradan görülemeyen bir yolla erişiyor
olabilir; erişemiyorsa da işlemin kendi mesajı buradaki tahminden daha çok şey
söyler.

**Bilinen sınır:** çakışma denetimi DeviceMap ve bilgisayarın kendi adresleri
üzerinden yapılır. Adresi kullanan üçüncü bir cihaz, adres atanmadan görülemez
— bir adresi yoklamak için ona giden bir yol gerekir, kurulan şey de tam
olarak o yoldur. Böyle bir çakışma, koşunun cihazlara erişememesi olarak
ortaya çıkar. Ağ ekranı bunu yazar.

**"Ağı hazırla" diye bir düğme yoktur ve olmamalıdır.** Bu treni devreye alan
kişiler ağ mühendisi değil; eksik olanı listeleyip düzeltilmesi için emir
bekleyen bir ekran, bozuk sanılan bir ekrandır. Hazırlık beş yerde
kendiliğinden olur:

- uygulama **açılırken** (`lifecycle.start`, kayıtlı ya da güvenle belirlenen
  arayüz varsa Set 1 fabrika ağı ilk tarama beklenmeden hazırlanır),
- Ağ ekranını **açmak** (`refresh` doğrudan `POST /api/network/prepare`
  çağırır — tekrarı zararsızdır, hâlihazırda duran adres `required`
  içinde değildir),
- arayüz **seçmek** (`POST /api/network/settings` aynı istekte hazırlar;
  panel zaten yalnız o cevabı bekliyordu, ardından ikinci bir düğmeye
  bastırmak kullanıcıya az önce söylediğini onaylatmak olurdu),
- bir **koşu, fabrika sıfırlama ya da tarama** başlatmak,
- **tren setini değiştirmek** (yeni setin keşif turu taramayı, tarama da
  hazırlığı tetikler).

`ensure()` ile arayüz değiştiren `select_adapter()` aynı yeniden girişli
kilidin altında tercih okuma, gereken ağ hesabı, panelin eski alias'ını
kaldırma ve yenisini ekleme işlemlerini tek transaction olarak yürütür. Bu,
arka plandaki bir taramanın en3 için aldığı eski kararı kullanıcı en6'yı
seçtikten sonra uygulamasını engeller. Kullanıcının/işletim sisteminin eklediği
adresler `aliases.active()` içinde olmadığı için taşıma adayı değildir.

Ekranda kalan tek düğme "Geri al"dır: eklenen adresi geri almanın başka yolu
yoktur, eklemenin ise dört yolu vardır.

Ağ ekranı ayrıca şunları gösterir: kullanılan arayüz ve seçici, arayüze
verilen adres (`10.1.1.225/24`), gereken ağlar ve panelin eklediği adresler
(tek tek ya da topluca geri alma). Son oktet, önek ve "koşudan önce otomatik
hazırla" ayarları kaldırılmıştır; panel her zaman `.225/24` ekler ve hazırlığı
gerektiğinde kendiliğinden yapar. Panelin eklemediği hiçbir adres buradan
değiştirilemez ya da kaldırılamaz.

**Testler bu makineyi yapılandırmaz.** Tarama ve IP koşusu sahte cihazlarla
uçtan uca çalıştırıldığı ve bu işler başlarken ağı hazırladığı için
`ifconfig alias` gerçekten çalıştı: `unittest discover` bir geliştiricinin
canlı arayüzüne dört adres bıraktı. `panel.network.aliases.WRITES_ALLOWED`
(çevre değişkeni `PANEL_NETWORK_WRITES`) bunun için var; test paketi
`tests/__init__.py` içinde kapatır (paket modülü her `tests.<ad>` importundan önce koşar; `panel`'i `support.base`'den önce import eden bir test modülü base'deki ayarı atlıyordu), yazma yolunu sınayan testler sahte
komutun etrafında yeniden açar.

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

Dosya **her cihaz için ayrı** seçilir (`panel/firmware/selection.py`, cihaz kimliğine
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

macOS AppleScript'teki `of type {"apk"}` ifadesi bir uzantı değil UTI
süzgecidir. Android Studio bulunmayan makinelerde APK dinamik `public.data`
olarak sınıflanabildiği için dosya görünse bile seçilemiyordu. macOS seçicisi
bu nedenle dosyaları UTI ile elemez; seçilen yolun beklenen `.apk`/`.bin`
uzantısı API sınırında yeniden ve kesin olarak doğrulanır. Boyut sınırları da
formata göredir: `.bin` için 32 MiB, tek dosyalı `.apk` için 512 MiB.

APK tarafının ayrıntıları:

- Kurulum cihazı yeniden başlatmaz, yalnız uygulama yeniden kurulur;
  bu yüzden "cihaz geri gelene kadar bekle" adımı yoktur.
- Cihazdaki sürüm yenisinden büyükse paket yöneticisi reddediyor. Sahada
  eski sürüme dönmek gerekebildiği için `INSTALL_FAILED_VERSION_DOWNGRADE`
  görülürse `-d` ile bir kez daha denenir (bayrak baştan gönderilmez:
  bazı cihazlarda düşürme kapalı ve komutun tamamı reddediliyor).
- `adb install` çıktısındaki bilinen hata kodları tek satırlık Türkçe
  mesaja çevrilir (`firmware._kurulum_hatasi`).
- Seçilen APK'nın `AndroidManifest.xml` kaydından paket kimliği ve sürümü
  bağımlılıksız okunur. Kurulumdan önce ve sonra `dumpsys package` tam bu
  kimlikle çağrılır; böylece geçici bir test uygulaması sabit panel paket adı
  sanılmaz. `adb install` yalnız sıfır çıkış kodu, tek başına `Success` satırı
  ve kurulum sonrasında seçilen paketin okunması birlikte gerçekleşirse
  başarılıdır. Karşılaştırılan sürüm **APK'nın kendi manifestindeki**
  sürümdür; elle girilen bir "beklenen sürüm" yoktur. Böyle bir alan vardı ve
  kaldırıldı: dosyanın zaten söylediğini tekrar ediyor, yanlış yazıldığında da
  başarılı bir kurulumu hata gösteriyordu.
- Yalnız tek `.apk` paketi desteklenir. `.xapk`, `.apks`, `.apkm` veya ayrı
  OBB dosyası gerektiren oyun/uygulama dağıtımları bu yükleyiciye verilmez.

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
`POST /api/firmware/pick` çağırır; sunucu `panel/system/files.pick_file` ile seçiciyi
açar (macOS `osascript`, Windows `OpenFileDialog`, Linux
`zenity`/`kdialog`), dönen yolu doğrular ve hedef cihazlara atar. İstek
kullanıcı seçim yapana kadar, en fazla 300 saniye bekler. Kullanıcı vazgeçerse
veya süre dolarsa eski seçim korunur. Linux'ta `zenity` ve `kdialog` ikisi de
yoksa işlem açık bir hata mesajıyla sonlanır. Yol arayüzde elle yazılmaz.

Olağan durum (bütün gruba aynı imaj) için ekranın üstünde tek bir düğme
var: aynı uç grup adıyla çağrılır ve dosya gruptaki her cihaza atanır.
Satırdaki "Değiştir" yalnız o cihazı etkiler, "×" seçimi kaldırır. Bir seçim
yalnız dosyayı taşır; yanında saklanan başka bir değer yoktur.

`POST /api/firmware/file` (yolun doğrudan sunucuya verildiği uç) arayüzde
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
- Dosya yolu girildiği anda doğrulanır (var mı, boş mu, beklenen uzantı ve
  formata özgü boyut sınırı) ve yükleme anında bir kez daha bakılır: seçimden
  sonra silinmiş olabilir.
- Seçim **yalnız bellektedir**; panel imajı kendi dizinine kopyalamaz,
  kapanışta seçim gider (bkz. `panel_api.temizle`).
- HTTP 200 başarı sayılmaz: cihaz yeniden başlar ve sürümünü **bildirmek
  zorundadır**. `.bin` tarafında karşılaştırılacak elle girilmiş bir değer
  yoktur; APK tarafında manifest sürümü karşılaştırılır. Kuyruk satırında
  hangi dosyanın gittiği yazar.

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
  gövdesi hiç yatay kaymaz. Dört kırılma noktası vardır — 1080 / 900 / 720 /
  620 — ve beşincisi eklenmez: birbirine iki-üç piksel uzaklıktaki eşikler
  hiçbir davranış farkı taşımıyordu.
- İkon düğmelerinin `aria-label`'ı vardır, diyaloglarda odak tuzağı ve
  Escape çalışır, kilit/kuyruk panelleri `aria-expanded` bildirir.

### Renk ve yazı: tek kaynak, ölçülen eşik

- Bütün renk ve boyut jetonları `static/css/base.css` içindeki tek `:root`
  bloğundadır. **Metin taşıyan her jeton `--bg` ve `--panel` üzerinde en az
  4.5:1 kontrasta sahiptir**, göz kararıyla değil ölçülerek;
  `tests/test_frontend.py` altına düşeni reddeder. `--text-dim` aylarca
  3.38:1'deydi ve panelin en yaygın ikincil rengiydi.
- **Dolgu rengi ile metin rengi ayrı jetonlardır.** `--ok/-auth/-failed/
  -unknown` nokta, kenar ve port grafiği boyar; bir KELİME `--ok-text`,
  `--auth-text`, `--failed-text`, `--unknown-text` ile yazılır. Kırmızı dolgu
  (3.7:1) ve gri, okunacak kadar açık değil.
- **Yazı boyutu yalnız `--fs-*` ölçeğinden seçilir** ve `rem`'dir; sekiz
  basamak var, en küçüğü 11 px. Bir ekran kendi boyutunu yazmaz — ne CSS'te
  `px` ne JS'te satır içi. Eskiden 22 ayrı değer ve 49 satır içi boyut vardı;
  on bir basamak beş pikselin içine sıkışmıştı, yani hiçbir şey anlatmıyordu.
  Kapı yine `tests/test_frontend.py`'de.

### Ekran değişimi görülmeyene de söylenir

- Görünüm değiştiğinde odak `#content`'e taşınır, tek `h1` ve
  `#route-status` canlı bölgesi ekranın adını taşır (`app.js:announceView`).
  Öncesinde odak menü düğmesinde kalıyor, ekran okuyucuya hiçbir şey
  duyurulmuyordu. `#toast` bu işi yapamaz: tek slotludur ve iş kuyruğunun
  kendi mesajları üzerine yazar.
- İçerik `<main>`'dir, sayfanın ilk sekmesi "İçeriğe atla" bağlantısıdır.

### Izgaralar tablodur

- Dokuz veri ızgarasının hepsi `components/table.js` içindeki `dataTable`
  üzerinden kurulur. Görsel yerleşim CSS ızgarasıdır, ama `role="table"`,
  `role="row"`, `role="columnheader"` ve `role="cell"` nitelikleri kurucu
  tarafından eklenir — çağıran satırı eskisi gibi kurar, rolleri hatırlamak
  zorunda değildir.
- `dom.js:preserveScroll` `.table-wrap` düğümlerini **belge sırasına göre**
  eşleştirir; sarmalayıcı sayısı değişirse yatay kaydırma sessizce bozulur.

### Yazma işleminden önce sorulur

- **Cihazı yeniden başlatan, adresini değiştiren ya da beslemesini kesen her
  işlem** `components/confirm.js` içindeki `confirmWrite` ile onay ister ve
  kaç cihazı, hangi portları etkilediğini yazar. Odak "Vazgeç"tedir, yani
  Enter ve Escape ikisi de "hayır" demektir.
- Kural eskiden hafızayla uygulanıyordu ve ters işliyordu: yazılım yükleme ve
  fabrika sıfırlama soruyordu, "IP atamayı başlat" ile "12 cihaza uygula"
  sormuyordu — panelin en ağır iki işlemi, soru sormayan iki işlemdi.

### Hata ekranda kalır

- `showError` **kendiliğinden kaybolmaz**; kapatma düğmesi taşır ve üst üste
  gelen mesajlar yığılır (en fazla üç). Bildirimlerin yarısından çoğu
  reddedilmiş bir yazmayı anlatıyor; altı saniye sonra silinen ve bir sonraki
  "iş kuyruğa alındı" mesajının üzerine yazdığı bir hata, hiç gösterilmemiş
  sayılır. Başarı ve bilgi mesajları eskisi gibi solar.
- Bir satırın NEDEN başarısız olduğu görünür metindir, `title` değil: fare
  ipucu klavyeyle okunamaz, ekran okuyucuya gitmez ve ekran görüntüsüne
  girmez. Kuyrukta bu not yalnız başarısız/uyarı/atlanmış satırlarda çıkar —
  hepsinde çıkarsa liste okunmaz hâle geliyordu.

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
| 4 | 401/403 cihazı kilit listesine düşer | `test_credentials.py` |
| 5 | Doğru bilgi → yeşil + kilitten çıkar | `test_credentials.py` |
| 6 | Yanlış bilgi RAM kimliğini ezmez | `test_credentials.py` |
| 7 | Kapanışta RAM deposu temizlenir | `test_credentials.py` |
| 8 | Yeni süreçte önceki parolalar yok | `test_credentials.py` |
| 9 | Oturumda girilen cihaz erişim parolası dosyaya yazılmaz | `test_security.py` |
| 10 | API ve kuyruk satırları parolasız | `test_security.py` |
| 11 | Aynı adlı farklı IP'li switch karışmaz | `test_switch.py` |
| 12 | Eski cevap yeni doğrulamayı ezmez | `test_credentials.py` |
| 13 | Çift tıklama iki iş oluşturmaz | `test_jobs.py` |
| 14 | Aktif tarama varken ikincisi başlamaz | `test_jobs.py` |
| 15 | Kamera 401 kilit akışına girer | `test_credentials.py` |
| 16 | Zaman aşımı ≠ yanlış parola | `test_credentials.py` |
| 17 | Kimlik isteğinde hedef, istemci IP'sinden değil DeviceMap'ten alınır | `test_security.py` |
| 18 | İptal işi kontrollü sonlandırır | `test_jobs.py` |
| 19 | Ön yüz statik ve söz dizimi denetimi | `test_frontend.py` |
| 20 | Hepsi tek komutla çalışır | yukarıdaki komut |

Ek olarak `tests/test_progress.py`: IP atama koşusunun çıktısını gerçek
bir saha günlüğünden oynatıp aynı anda tek portun çalıştığını, portların
koşu içinde kapandığını, yüzdenin aşama payına göre ilerleyip geri
gitmediğini ve satır altı adımların doğru porta yazıldığını doğrular
(bkz. §9 "IP atama koşusunun ilerlemesi").

Ek olarak `tests/test_elevation.py`: yükseltilmiş yetki akışı — hangi platformda
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
