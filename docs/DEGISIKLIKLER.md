# Değişiklik Günlüğü — Devreye Alma Paneli

Bu belge, Devreye Alma Paneli'nin sürümler arasındaki kullanıcıya dönük
değişikliklerini kaydeder. İndirme ve kurulum bilgileri
[GitHub sürüm metninde](RELEASE_NOTES.md), teknik ayrıntılar ise
[mimari belgede](MIMARI.md) yer alır.

## v1.0.6 — 30 Ağustos 2026

Admin moda artık uzaktan da girilebiliyor: telefonla okutulan bir QR ya da
kendi hesabınız. Ekranlardaki açıklama satırları kalktı.

### Uzaktan oturum

Servis anahtarı, klavyenin başında birinin bellek takmasını istiyor. Uzaktaki
bir makinede bunu yapacak kimse olmadığı için admin moda ikinci bir kapı
açıldı: üst çubuktaki **Uzaktan oturum** düğmesi iki yol sunuyor, ikisi de
aynı anda ekranda.

- **QR ile.** Panel bir kare çiziyor, yetkili kişi telefonuyla okutup
  onaylıyor, panel admin moda geçiyor. Kimsenin bir şey yazması gerekmiyor.
- **Hesapla.** Makinenin başındaki mühendis kendi e-postası ve parolasıyla
  giriyor. Hesabı yoksa aynı ekrandan açabiliyor — ama yeni hesap bir yönetici
  yetki verene kadar giriş yapamıyor, ekran bunu peşinen söylüyor.

Oturumu **sunucu** açıyor, panel değil: imzayı doğrulayan taraf o. Oturum
kendiliğinden bitiyor, telefondan kapatılabiliyor ve ağ giderse birkaç saniye
içinde admin mod düşüyor. Cihazlara yazma sürerken düşmüyor — yarım kalmış
bir IP ataması, birkaç dakika açık kalan bir kapıdan kötüdür.

**Sekiz haneli oturum kodu kutusu kaldırıldı.** Kareyle aynı kişinin uyanık
olmasını gerektiriyordu, karşılığında ekranın bir sütununu harcıyordu ve
operatöre trenin yanında sekiz karakter yazdırıyordu.

### Mühürlü proje haritaları

Her paket artık bütün projelerin cihaz listesini taşıyor, ama yalnız kendisini
açık taşıyor: diğerleri servis anahtarındaki değerle mühürlü. Kendi paketini
çalıştıran müşteri için hiçbir şey değişmiyor — listeyi göremiyor, baytları
zaten okuyamıyor. Anahtar takılıyken admin modda diğer projeler açılabiliyor,
ve admin moddan çıkınca çözülmüş kopyalar siliniyor.

### Ekranlar sadeleşti

Kontrollerin altındaki açıklama cümleleri kaldırıldı — ne yaptığını düğmenin
kendisi söylüyor. Aynı sadeleşme birkaç yerde yerleşimi de değiştirdi:

- **Proje ve cihaz listesi** switch'e göre gruplandı. 110 cihazın düz bir
  tablosu yerine, her switch bir başlık ve portları altında; yanında arama
  kutusu ve kategori sayımı.
- **Arama kutuları** artık örnek yazı taşımıyor; kutunun içinde duran ve
  kaybolmayan bir büyüteç var.
- **Cihaz listesinde** başlık kaç satırın göründüğünü söylüyor.

### Bunlar da

- **macOS'ta Düzenle menüsü.** Cmd-C, Cmd-V ve Cmd-A pencerenin her yerinde
  çalışıyor; daha önce menü çubuğunda Düzenle menüsü olmadığı için hiçbir yere
  ulaşmıyordu.
- **Cihaz profilleri proje başına bir dosyada.** Panelin bir projenin
  ekipmanı hakkında bildiği her şey tek dosyada; iki müşterinin "Intercom"u
  aynı cihaz olmak zorunda değil.
- **Sürüm başlıkları kısaldı.** GitHub sürüm sayfalarının adı artık paketin
  kendi adı (`dabp-gdm-v1.0.6`) — eski uzun başlık listede kırpılıyordu.

## v1.0.5 — 29 Ağustos 2026

Gaziray ve GDM kendi paketleriyle geldi, cihaz listesi çoklu seçim kazandı.

### İki yeni müşteri paketi

Gaziray ve GDM artık kendi kurulum paketleri: her biri yalnız kendi cihaz
listesini ve kendi kontrol listesini taşıyor. Paketler `devicemaps/` altında
proje başına bir klasörde duruyor — cihaz haritası ve ondan üretilen kontrol
listesi yan yana, böylece yarım teslimat gözle görülür bir yarım klasör
oluyor.

Bu iki projede **broker, saat kaynağı ve santral PISCU değil**, kendi
makineleri. Panel bu adresleri artık "PISCU'dur" varsayımıyla değil, paket
tablosundan okuyor:

- **Gaziray**: dört vagon dört ayrı /24'te, broker beşinci bir ağda
  (10.n.0.1). Panel kendine verdiği adresi ve cihazlara yazdığı maskeyi buna
  göre genişletiyor; dar bir maske vagonu kendi başına bırakıyordu.
- **GDM**: 125 cihazın tamamı tek /24'te, kayıt kameraların kendi
  kartlarında — depolama denetimi bu pakette gerçekten çalışıyor.

### Cihaz listesinde çoklu seçim ve sağ tık

Switch ekranındaki tıklama kuralları cihaz listesine de geldi: tek tık,
**Shift** ile aralık, **Ctrl/Cmd** ile tek tek ekleme. Seçim varken başlıkta
kaç cihazın seçili olduğu yazıyor ve tek düğmeyle temizleniyor.

Sağ tık menüsü seçimin tamamına işliyor — örneğin bir yazılım yüklemesi
başlatılırken onay kutusu kaç cihaza yükleneceğini söylüyor. Tek satıra
özgü işlemler (ayrıntıları aç gibi) yalnız tek satır seçiliyken çıkıyor.

- **Satır yoğunluğu düğmesi.** Üst çubuktaki yeni düğme tabloları sık ve
  seyrek arasında değiştiriyor; seçim uygulama ayarlarında kalıcı.

### Maske denetimi artık oktet sınırında

Kameranın maskesi "projenin tamamına erişiyor mu" diye sınanıyor ve
projenin genişliği cihaz haritasından hesaplanıyor. Bu hesap bugüne kadar
adreslerin kendisine bakıyordu ve **kimsenin çizmediği bir sınır**
uydurabiliyordu: Yataklı'nın adresleri .1 ile .101 arasında olduğu için bir
/25 çıkıyor, trenin gerçekte kurulu olduğu /24'e ayarlı bir kamera hatalı
görünüyordu. Genişlik artık /24, /16, /8 dışında bir değere yuvarlanmıyor.

- **Fuar'ın ağ genişliği düzeltildi.** Standın adresleri 10.1.1.x ile
  10.1.4.x arasında, yani dört ayrı /24 — ama pakette bir genişlik yazmadığı
  için IP atama /24 yazıyordu. Panel kendi ayarladığı cihazın maskesini sonra
  "dar" diye raporluyordu. Fuar da Gaziray gibi /16 yazıyor.

## v1.0.4 — 28 Ağustos 2026

Servis anahtarı artık uzaktan bağlanılan bir makinede de çalışıyor.

### Admin mod uzaktan da açılabiliyor

Admin moda giriş bugüne kadar **takılı bir USB belleğe** bağlıydı, ve bu
bilerek böyleydi: anahtar taşınan fiziksel bir şey olsun, kopyalanabilir bir
parolaya dönmesin diye.

Uzaktan bağlanılan bir makinede bu, çalışmayan bir kural. Klavyenin başında
belleği takacak kimse yok — ve admin modun arkasındaki ekranlara mühendisin
ihtiyaç duyduğu an tam olarak odada olmadığı an. Anahtar dosyası artık
**uygulamanın kendi klasöründen** de okunuyor: bir belleğe yazılmış anahtar
oraya kopyalanınca o kurulumda admin mod açılıyor.

**Vazgeçilen tek şey fizikselliktir.** Doğrulama hiç gevşemedi:

- Dosya **sırrı taşımıyor**, doğrulanabilir bir kanıt taşıyor — bir
  kopyasından yeni anahtar üretilemiyor, başka bir paket için anahtar
  üretilemiyor.
- Kanıt, pakete derleme anında damgalanmış özete karşı sınanıyor. Doğru
  klasörde durmak bir dosyayı geçerli yapmıyor; başkasının koyduğu bir dosya
  **yanlış bellek gibi reddediliyor**.
- Ayarlar dizini değil, uygulamanın klasörü. Panel kendini yükseltilmiş
  olarak yeniden başlatıyor ve ayarlar dizini `HOME`'a bağlı — yükselen
  süreç başka bir kullanıcının dizinine bakardı.

**Bellek elde varsa o kazanıyor.** Hem klasörde hem elde anahtar varken
panel az önce takılanı okuyor: takan kişinin kastettiği odur.

### Kapak altında

- Bellek gözcüsü hâlâ **yalnızca çıkarılabilir sürücüleri** izliyor.
  Uygulamanın klasörü belirip kaybolmaz; onu da karşılaştırmaya katmak
  hiçbir şey tespit etmeyen sabit bir terim eklemek olurdu. O klasördeki bir
  anahtar zaten her turda ve pencerenin sorduğu her soruda okunuyor.

## v1.0.3 — 28 Ağustos 2026

Ayrı bir uygulama olan Switch Yönetim Paneli panelin bir ekranı oldu, ADB
ekranı yeniden başlatma ve geçmiş kazandı, fuar standı için kendi paketi
çıktı. Bu iki ekran artık servis anahtarı istiyor.

### Switch ekranı panelin içinde

Switch'lere bugüne kadar ikinci bir uygulamadan bakılıyordu. O uygulama
kalktı; yaptığı her şey panelin **Switch Yönetim** ekranında. Kazanılan şey
tek ekran değil: burada girilen hesap IP atama ekranının switch okumalarını
da açıyor, çünkü ikisi parolayı artık aynı yerden soruyor. Eskiden aynı
switch için aynı parola iki kez giriliyordu.

- **Ağı tarayarak switch bulma.** Adres aralığı `10.1.1.0-255/24` gibi bir
  ağ ya da `10.1.1.20-40` gibi bir aralık olarak yazılır — switch'ler .100
  ile .110 arasındaysa kalan 244 adresi taramanın bedeli boşa geçen
  zamandır. Bir taramada en çok 1024 adrese bakılır; daha genişi kaç adres
  ettiğini söyleyerek reddedilir, sessizce yarıda bırakılmaz.
- **Cihazın ön yüzü ekranda.** Portlar gerçek yerleşimiyle çizilir; renkler
  besliyor / bağlı / kapalı / bağlı ama beslemesiz ayrımını yapar. Aynı
  çizim IP atama ekranında da kullanılıyor, yani iki ekran aynı switch'i
  aynı gösteriyor — birinde 7. port başka yerde duruyorsa hangisine
  inanılacağı sorusu ortaya çıkıyordu.
- **Port ve PoE tabloları.** Portlar tıklanarak seçilir, sağ tık menüsü
  seçili portların tamamına birden yazar: PoE kipi, port açma/kapama, uplink
  türü. Menü uyguladığınız anda switch'e yazar ve bunu söyler.
- **Yönetim adresi, kaydetme, yeniden başlatma ve fabrika ayarları.** Adres
  değiştirmek, ayarları kalıcı kaydetmek, switch'i yeniden başlatmak ve
  fabrika ayarlarına döndürmek — dördü de ne kaybedileceğini yazan bir onay
  kutusunun arkasında. Fabrika ayarı için switch'in adresi elle yazılıyor.
- **Yazılamayacak bir adres yazılmadan reddediliyor.** Loopback, multicast
  ya da desteklenmeyen bir maske girildiğinde switch oraya taşınmıyor; bu
  hatanın karşılığı konsol kablosuyla kurtarma olurdu.
- Adres değişikliği, yeniden başlatma ve fabrika ayarı, switch'in cevabı
  gönderemeden gittiği işlemler. Bağlantının kopması **beklenen sonuç**
  olarak, yani başarı olarak okunuyor; eskiden bu "işlem başarısız" diye
  görünüyordu — switch çoktan sıfırlanırken.

### ADB ekranı: yeniden başlatma, sunucu ve geçmiş

- **Ekranları yeniden başlatma.** Uygulamayı değil ekranı. Komut
  gönderilmekle kalmıyor, cihazın geri gelmesi bekleniyor: önce bağlantıyı
  düşürmesi (25 sn), sonra yeniden cevap vermesi (120 sn). İki ayrı hata
  cümlesi var — "komut kabul edildi ama cihaz hiç kapanmadı" ile "yeniden
  başladı ama süresi içinde dönmedi" — çünkü operatörün öğrenmek istediği
  şey komutun gittiği değil, ekranın geri geldiği.
- **Hepsini bağla / sunucuyu sıfırla.** İkisi de seçimden bağımsız, bu
  bilgisayarın ADB sunucusuyla ilgili işler: listedeki bütün adresleri
  bağlar, ya da takılan sunucuyu durdurup başlatır.
- **Durum kartı ve geçmiş.** Üstte o an koşan işin satırları, altında biten
  işlemlerin kaydı — en yenisi üstte, yirmi satırlık kaydırılabilir bir
  kutuda. Tezgâhta bir öğleden sonra bir düzine koşu demek ve sonradan
  sorulan soru hep önceki koşularla ilgili oluyor: "46 geri geldi mi?",
  "bunu hangilerine kurmuştum?".
- **Listeyi dışa aktarma.** Adres listesi JSON olarak kaydedilebiliyor;
  nereye kaydedileceği soruluyor. İçe aktarma zaten vardı.
- **Adres alanı aralık kabul ediyor:** `10.1.1.45-47`, ya da virgülle
  ayrılmış birkaç adres.

### ADB ve Switch ekranları servis anahtarı istiyor

İki ekran da temel ekranlardan alınıp admin ekranlarının yanına konuldu.
Sebep, ne yaptıkları: panelin diğer bütün saha ekranları projenin cihaz
listesi üzerinden çalışır ve yalnızca o listedekine dokunabilir. Bu ikisi
**elle yazılan bir adrese** gidip cevap veren neyse ona işlem yapar — paylaşılan
bir ağda bu, herhangi bir cihaz demektir: kapatılan bir switch portu,
kesilen bir PoE beslemesi, kurulan bir uygulama, yeniden başlatılan bir
ekran. Anahtar, bunu yapan kişinin yapması gereken kişi olduğunu söylüyor.

Sunucu da aynı kuralı uyguluyor; arayüzden gizlemek tek başına bir kapı
değil.

### Fuar paketi

Dördüncü bir müşteri paketi çıktı: **`fuar`**. Fuardaki stant bir tren
değil, tek bir raf — bir KYLAND switch ve yanındaki on iki cihaz. Cihaz
haritasındaki adresler de bu yüzden düz yazılmış (`10.1.1.x`), trenlerdeki
gibi set numarasına göre şablonlanmamış: tek bir set var ve yeri
değişmiyor.

Paketin ayrı olmasının sebebi diğerleriyle aynı: salondaki dizüstü
bilgisayarda, müşteri olmayan insanlara gösterilen bir makinede, her
müşterinin cihaz listesini taşıyan bir build bulunmamalı. Fuar haritasındaki
kullanıcı adları, parolalar ve dahili numara parolaları da boşaltıldı.

- **Stant kipi.** Kompartıman LCD okuması normalde ekranda panel
  uygulamasını arar ve bulamazsa cihazı kırmızı işaretler; trende doğru
  davranış budur, çünkü ekran zaten o uygulama için oradadır. Stantta
  donanım ödünç alınmıştır ve her ünitede başka bir şey çalışır — o zaman
  bütün pano kırmızıya döner ve gerçekten erişilemeyen üniteler bu gürültüde
  kaybolur. Fuar paketinde ADB'nin **bağlanabilmesi** yetiyor; ekran yine
  seri numarasını, saat dilimini ve çalışma süresini vermek zorunda, düşen
  tek şart adı belli bir uygulamanın aranması. Satır da bunu yazıyor:
  "ekran yanıt verdi (seri no) — üzerinde panel uygulaması yok".
- Bu, ortam değişkeni değil **projenin özelliği**: standı kuran kişinin bir
  bayrağı hatırlaması gerekmiyor, trene giden paket de gevşemeyi miras
  almıyor. İkisi de olmayan bir tezgâh için `ADB_REQUIRE_PACKAGE` her iki
  yöne de zorlayabiliyor.
- **Kendi kontrol listesi şablonu.** Excel şablonu satırlarını cihazlara IP
  şablonuna göre eşler; ortak dosyada olmayan cihazlar için hiçbir satır
  dolmaz ve ekranda bunun sebebini söyleyen bir şey olmaz. Fuarın kendi
  şablonu var, ve şablonu artık açık olan proje belirliyor.

### İki yeni cihaz türü

- **Anons / Swanneck** (kaz boynu mikrofon). Intercom ile aynı Piton anons
  yazılımını çalıştırıyor — aynı uçlar, aynı alanlar — o yüzden aynı şekilde
  yapılandırılıyor ve güncelleniyor. Adresi panel vermiyor; Handset gibi
  elle kuruluyor, sonra yalnızca yapılandırılıyor.
- **LCD / Twin.** Kompartıman LCD gibi Android: adresi ADB üzerinden
  yazılıyor, uygulaması APK olarak gidiyor. IP atama koşusu **yok** — o
  koşu port port ilerleyen haliyle Kompartıman LCD için yazılmış.

### Kullanıcı ve geliştirici kılavuzları

`docs/` altında iki kılavuz var artık: ekran ekran anlatan bir **kullanıcı
kılavuzu** ve mimariyi, veri akışını ve karar gerekçelerini anlatan bir
**geliştirici kılavuzu** — ikisi de ekran görüntüleri ve şemalarla.

### Kapak altında

Kullanıcıya dönük bir karşılığı yok, ama bu sürümde yapılanlar:

- **Switch erişimi artık panelin kendi parçası** (`panel/switch/`).
  Eskiden `field_scripts/switch_api.py` ödünç alınan salt-okunur bir
  betikti ve iki depoda iki kopyası elle eşitleniyordu — ayrışmanın
  beklendiği yer tam olarak orasıydı. Switch ekranının **yazması**
  gerekiyordu; bunu ikinci bir istemciye dönüşmeden büyütmenin yolu yoktu.
  Panelin tek switch istemcisi var: Switch ekranı, IP atama ekranının ön
  paneli ve fabrika ayarı doğrulaması aynı yerden geçiyor.
- **Switch ön yüzü tek bir çizim.** İki ekran ayrı ayrı çiziyordu; ortak olan
  şey — konnektör grafiği ve hangi portun nerede durduğu — paylaşıldı,
  gerçekten farklı olan şey — portların neye göre renklendiği — paylaşılmadı.
- **API kapısı yol öneki ile eşleşiyor.** Kısıtlı ekranların uçları tek tek
  yazılıydı; iki uçlu bir ekranda bu tutuyordu, ama yeni ekranların on bir ve
  on dört ucu var. O uzunlukta bir liste, içinde sessiz bir boşluk olan
  listedir: kapının arkasındaki ekrana eklenen yeni bir uç, biri bu dosyayı
  hatırlayana kadar açık kalırdı.
- **Paket adb'siz derlenemiyor.** `platform-tools/` yoksa `dabp.spec`
  derlemeyi durduruyor (bilerek atlamak için `DAP_ALLOW_NO_ADB=1`), paketlenmiş
  `--self-test` adb'yi tekrar arıyor ve CI arşivi kendi indiriyor. Sebebi:
  adb'siz bir paket derlenir, açılır, çalışır — ve sahada sağlam bir ekran
  "okunamıyor" der. Bu, arızayı sahadan derlemeye taşıyor.
- **Saha doğrulama betiği panelin adb'sini kullanıyor**, tek başına
  çalıştırıldığında da `adb` adını. Kamera toplayıcısı da artık alt türleri
  tek tek saymıyor: her yeni projede bu dosya düzenlenmeden kameralar
  raporda görünmüyordu ve eksiklik hata olarak değil, boş bir sütun olarak
  çıkıyordu.

## v1.0.2 — 27 Ağustos 2026

Panele gömülü bir ADB aracı eklendi; otomatik tarama artık duraklatılmış
başlıyor.

### ADB araçları ekranı

Menüde kendi başlığı olan yeni bir ekran. Diğer ekranlardan farkı, projeye
bağlı olmaması: kendi adres listesini tutar ve DeviceMap'i hiç tanımaz.
Tezgâhtaki ya da kabindeki Android ekranlarla doğrudan çalışmak içindir.

- **Kendi cihaz listesi.** Adresler elle eklenir, çıkarılır ya da bir JSON
  dosyasından içe aktarılır; liste kaydedilir ve panel kapanınca kaybolmaz.
  Bozuk bir satır ekranı kapatmaz — atlanır ve kaç tanesinin atlandığı
  söylenir.
- **Anahtar kelimeyle uygulama arama.** Paket adını kimse ezbere yazmaz;
  kutuya "gebze" yazılır ve seçili cihazlardaki eşleşen paketler listelenir.
  Virgülle ayırarak birkaç kelime aynı anda aranabilir.
- **Toplu işlem.** Seçili cihazlarda uygulama başlatma, durdurma, yeniden
  başlatma, silme ve APK kurma — hepsi aynı anda. Farklı cihazlarda farklı
  paketler seçildiyse her cihaza kendi paketi için komut gider; paketin
  bulunmadığı cihaza hiç komut gitmez ve hangi cihazın dışarıda kaldığı
  ekranda yazar.
- **Kendiliğinden başlatma.** Bir uygulama, ekran açıldığında kendiliğinden
  kalkacak biçimde ayarlanabilir. Bu, cihazın sistem bölümüne iki dosya
  yazar ve fabrika ayarlarına dönmek onları geri getirmez, o yüzden ne
  yazılacağı dosya adlarıyla gösterilip onaylatılır. Kaldırma da aynı iki
  dosyayı siler.
- İşlem sürerken panelin kendi yenileme turları durur. Bu ekranın işi iş
  kuyruğuna girmez; üst çubuktaki listede görünmez.

### Otomatik tarama duraklatılmış başlıyor

Panel açılır açılmaz DeviceMap'teki her adrese gitmiyor artık. Bir
Compartment LCD adb ile okunuyor ve kendiliğinden başlayan bir tur, o
ekranla uğraşan kişinin bağlantısını elinden alıyordu. Üst çubukta
"Duraklatıldı" yazar; **Şimdi tara** her zaman çalışır ve ilk tıklamada
otomatik turlar da başlar.

### Kapak altında

Kullanıcıya dönük bir karşılığı yok, ama bu sürümde yapılanlar:

- **Tek bir ADB taşıma katmanı.** `adb`, birbirinden habersiz dört ayrı
  yerden ve dört ayrı hata davranışıyla çağrılıyordu. Artık tek yerden
  çağrılıyor; "adb kurulu değil" gibi bir durum da ekranda okunabilir bir
  cümle olarak çıkıyor, "beklenmedik cihaz sorunu" olarak değil.
- **`adb` pakete gömülebiliyor.** Paketin içinde bir `platform-tools`
  klasörü varsa panel onu kullanır, yoksa PATH'teki `adb`'ye düşer —
  Android geliştirme araçları kurulu olmayan bir bilgisayarda da ekranlara
  ulaşılabilsin diye.

## v1.0.1 — 27 Ağustos 2026

Bakım sürümü. Ekranlarda ve akışlarda değişiklik yok; bir donma hatası
düzeltildi, geri kalanı kodun kendisiyle ilgili.

### Geniş bir arama maskesi paneli artık dondurmuyor

IP atama ekranındaki "Arama ağı" alanına geniş bir maske yazıldığında —
örneğin `255.255.0.0` ya da `255.0.0.0` — panel on sekiz saniyeye kadar
donuyor ve yaklaşık bir gigabayt bellek harcıyordu. Sonunda gösterdiği şey
yalnızca "arama ağı çok geniş" uyarısıydı; yani tüm o bekleme, verilecek
cevabı zaten bilen bir işlem içindi. Uyarı artık anında çıkıyor.

Yanlışlıkla yazılan bir maske de aynı yoldan geçtiği için, bu hata sahada
"panel kilitlendi" olarak görülebiliyordu.

### Kapak altında

Kullanıcıya dönük bir karşılığı yok, ama bu sürümde yapılanlar:

- **Adres haritasındaki üç ifade artık çeviriye tabi.** "the factory
  address" gibi parçalar İngilizce arayüzde de Türkçe arayüzde de
  kataloğa uğramadan yazılıyordu.
- **Anons ve switch tarafında kalan iki Türkçe cümle** İngilizceye
  çevrildi (kod tabanı İngilizce, arayüz metni katalogdan gelir).
- **Cihaz okuma yöntemleri tablosu ile saha betiğinin toplayıcı tablosu**
  arasındaki tutarsızlık bir testle bağlandı; ikisi sessizce ayrışamıyor.
- **Bağımlılık sürümleri sabitlendi**, böylece aynı etiketin iki derlemesi
  aynı paketleri taşıyor.
- Testler 117 saniye yerine 25 saniyede koşuyor; sürekli tümleştirme her
  değişiklikte çalışıyor ve linter kapısı eklendi.

## v1.0.0 — 26 Ağustos 2026

### Her müşteri kendi paketini alıyor, rol seçme ekranı kalktı

Panel bugüne kadar tek bir müşteriye göre kuruluydu: cihaz listesi binary'nin
içine gömülüydü ve açılışta bir rol seçme ekranı çıkıyordu. O ekranda "Admin"
düğmesine basmak yetiyordu — parola tanımlanmamışsa uygulama doğrudan admin
açılıyordu. Yani müşteriye giden pakette, o müşterinin görmemesi gereken
ekranlar bir tık uzaktaydı.

Artık program müşteri başına bir kez paketleniyor ve **her paket yalnızca
kendi projesinin cihaz listesini taşıyor**. Başka bir müşterinin cihazları,
adresleri ve dahili numaraları gizlenmiyor — dosyada yok. Bugün üç paket
var:

| Paket | İçindeki projeler |
|---|---|
| `vip-yatakli` | Yataklı, ve VIP (cihaz listesi geldiğinde) |
| `gdm` | GDM |
| `gaziray` | Gaziray |

Dördüncü bir "servis" paketi vardı — açılışta zaten admin olan, iç kullanıma
ayrılmış bir build. **Kaldırıldı.** Kendi kendini içeri alan bir paket, bir
kopyası müşteri makinesine düştüğü anda bütün ayrımı geçersiz kılıyordu;
admin artık bir *mod* ve oraya tek kapı USB.

Rol seçme ekranı tümüyle kalktı. Uygulama doğrudan panele açılıyor; kim
olduğunuzu paket söylüyor. Aynı müşterinin iki projesi olan `vip-yatakli`
paketinde üst çubuktaki proje adı bir menü: Yataklı ile VIP arasında geçiş
oradan yapılıyor. VIP'in cihaz listesi henüz teslim edilmediği için menüde
sebebiyle birlikte gri duruyor; dosya geldiğinde kendiliğinden açılıyor.

### Uygulamanın kendi ikonu var

Windows'ta görev çubuğu ve kurulum dosyası, macOS'ta Dock, Linux'ta menü —
üçü de artık jenerik bir simge yerine Piton işaretini gösteriyor. İkon
logodaki "P" işaretinden, panelin kendi arka plan rengiyle üretiliyor
(`tools/make_icons.py`); macOS ve Linux için köşeleri yuvarlak, Windows için
tam kare.

### Admin moda USB anahtarıyla geçiliyor

Müşteri paketleri admin moda geçebilir, ama tek bir yoldan: **belirli bir USB
belleği takarak**. Parola yok, gizli tık yok, komut satırı seçeneği yok.
Anahtar takılıyken uygulama açılırsa "admin modda başlatılsın mı?" diye
soruyor; çalışırken takılırsa "admin moda geçilsin mi?" diye. Hayır demek
soruyu susturuyor — bellek çıkarılıp yeniden takılana kadar bir daha
sorulmuyor.

**Admin moda elle girilip çıkılabiliyor.** Üst çubukta iki düğme var:
admin moddayken "çık", saha modundayken "gir". Giriş düğmesi **yalnızca
girilebilecekse** görünüyor — bellek takılıysa ya da bu çalıştırma build
sırrını taşıyorsa. İkisi de yoksa düğme yok; sunucu da isteği aynı kurala
göre reddediyor. Sırla açılan bir çalıştırma da artık saha moduna
inebiliyor: mühendisin müşterinin gördüğünü görmesi gereken hâl bu, ve sır
elde olduğu için dönüş yolu kapanmıyor.

**Bellek çıkarılınca admin modu kapanıyor.** Tek istisna: cihazlara yazan bir
iş (IP atama, ayar yazma, yazılım yükleme) sürüyorsa kapanma iş bitene kadar
bekletiliyor ve rozet bunu söylüyor. Yarım kalmış bir yazma işini yetki
düşürerek bozmak, kapıyı birkaç dakika daha açık tutmaktan kötü.

İlk anahtar, anahtar takarak yapılamaz — o yüzden **build sırrı** henüz var
olmayan ilk USB'nin yerine geçiyor: sırrı ortamında tutan bir **kaynak**
çalıştırması hiçbir şey takılmadan admin açılıyor ve ilk belleği yazıyor.
Sır bir **dosyada** da tutulabiliyor: kaynak ağacının kökündeki
`.adminkey-secret`. Ortam değişkeni sürece başlarken kopyalandığı için panel
açıkken `export` etmek işe yaramıyordu; dosya her soruluşta okunuyor, yani
bırakınca admin moda geçilebiliyor, silince mod bellek çıkarılmış gibi
düşüyor. `.gitignore`'da ve paketlenmiş build tarafından hiç okunmuyor.

Ortam değişkeni yükseltme sırasında kaybolmuyor artık: değer, yalnızca o
kullanıcının okuyabildiği bir dosyaya yazılıyor, komut satırında yalnız
**yolu** geçiyor ve yükselen süreç dosyayı okuyup siliyor. Komut satırı
herkese açık; sır oraya hiç çıkmıyor.
Paketlenmiş bir build ortam değişkenine bakmıyor, damgasına bakıyor; sır ise
hiçbir pakete girmiyor. Yani sahadaki hiçbir paket kendiliğinden admin
açılmıyor. Anahtar malzemesi hiç yoksa admin moda hiçbir yoldan girilemiyor
ve panel bunu söylüyor.

Kaynaktan çalıştırılan bir build'de damga olmadığı için hiçbir anahtar
tanınmıyordu: bellek takılıyor, panel sanki takılmamış gibi duruyordu.
Artık kaynaktan yazılan bir anahtar **kendini kaydediyor** — kaydı kaynak
ağacının kökündeki `.adminkey-dev.json` tutuyor, o ağaçtan kaynaktan çalışan
her sürüm belleği tanıyor, ortam değişkeni gerekmiyor. Kayıt ayar dizininde
değil, çünkü ayar dizini `HOME`'a bağlı ve panel kendini **başka bir
kullanıcı olarak** yeniden başlatıyor: `--remember` senin ev dizinine
yazarken çalışan panel root'un ev dizinine bakabiliyordu. Başka yerde üretilmiş bir bellek
`tools/key_digest.py <sürücü> --remember` ile kaydettiriliyor. Kayıt dosyası hiçbir şey yetkilendirmiyor ve
paketlenmiş build tarafından hiç okunmuyor; bir paketin neyi kabul ettiği
derleme anında belirleniyor. Anahtar malzemesi yoksa terminal bunu ve ne
yapılacağını yazıyor.

Anahtarı **yalnızca sırrı elinde tutan yazabiliyor**. Her pakete anahtarın
kendisi değil, tek yönlü bir özeti gömülüyor: paket bir belleği tanıyabiliyor
ama ondan yeni bir bellek üretemiyor — USB ile admin moda geçirilmiş bir
paket bile. Bu ayrım paketin içinden okunarak aşılamaz.

Anahtar iki yoldan yazılabiliyor. **"Sürücüyü sil ve anahtarı yaz"** USB'nin
tamamını siler, MBR + FAT32 kurar ve anahtarı yazar — Windows, macOS ve
Linux'ta hiçbir şey kurmadan okunan bir bellek çıkar. **"Hazır bir sürücüye
yaz"** ise var olan bir belleğe yalnızca anahtar dosyasını bırakır.

Silme, panelin kendi dosyaları dışında veri yok eden tek işlemi; kuralları
buna göre: yalnızca işletim sisteminin **çıkarılabilir** dediği sürücüler
listelenir, sistemin açıldığı disk hiçbir koşulda görünmez (harici bir
diskten açılmış bir makine de dahil), onay kutusu sürücünün adını ve boyutunu
yazar, ve sunucu tıklama anında listeyi yeniden okur — ekran çizildiğinden
beri bellek değişmiş olabilir.

Aynı belleğe `dabp-projects/` klasörü koyularak ek proje cihaz listeleri de
taşınabiliyor. Admin modda bu projeler menüde çıkıyor ve panel yeniden
başlatılmadan aralarında geçiş yapılabiliyor — sahaya yeni build göndermeden
bir proje ulaştırmanın yolu bu. Bellek çıkarıldığında paket kendi projesine
geri dönüyor.

Bir ekranı menüden gizlemek tek başına yeterli değildi: masaüstü köprüsü tüm
API'yi sayfaya açıyor, yani düğmesi olmayan bir ekranın verisi yine de
istenebiliyordu. Artık sunucu da reddediyor — saha modunda PISCU ve MQTT
uçları 403 dönüyor.

### Her paketin kendi ayar klasörü var

Aynı bilgisayara iki paket kurulabildiği için ayarlar da ayrıldı:
`%APPDATA%\dabp\gdm`, `…\dabp\gaziray`. Ayar hedefleri (tren seti, cihaz
kimliği) ile anahtarlanıyor ve cihaz kimlikleri konumsal — "sw1.d3" başka
projede başka cihaz demek. Tek dosyayı paylaşsalardı GDM için girilen bir
değer Gaziray'da o yuvadaki donanıma yazılırdı.

### Sürüm başına etiket

`dap-gdm-v0.9.8`, `dap-gaziray-v0.9.8`, `dap-vip-yatakli-v0.9.8`. Bir
müşteriye build alırken diğerleri derlenmiyor, her
paket kendi Release sayfasına çıkıyor. Ayrıntılar: [BUILD_RELEASE.md].

Bu arada etiketten sürüm numarasını çıkaran ifadede canlı bir hata bulundu:
`${TAG#*-v}` en kısa öneki attığı için `dap-vip-yatakli-v0.9.8` etiketinden
`0.9.8` yerine `ip-yatakli-v0.9.8` çıkıyordu. Dört yerde düzeltildi.

[BUILD_RELEASE.md]: BUILD_RELEASE.md

### Kamera/NVR koşusu ne yaptığını satır satır anlatıyor

Bir kamera veya NVR'ı ayarlamak tek bir alan yazmak değil, sıralı bir işlem:
kanallar, disk, buzzer, yeniden başlatma. Satırın tek satırlık notu bunların
ancak sonuncusunu taşıyabiliyordu. Artık kuyrukta cihazın satırının altında
adımlar açılıyor — sahadaki script'in ekrana bastığı satırların aynısı:

```
Saat dilimi yazıldı: CST-3:00:00
NTP sunucusu yazıldı: 10.1.1.1
1. kanal eklendi: Corridor 1 @ 10.1.1.24
1 numaralı disk unformatted durumundaydı — biçimlendirildi
Sesli uyarı 2 tetikçide kapatıldı
Kanalları alması için NVR yeniden başlatılıyor
```

Cihaz penceresi de aynı soruyu öbür taraftan yanıtlıyor: uygulamadan önce
"Kamera kanalları 0/3, Depolama 1: unformatted, Sesli uyarı FARKLI", sonra
"3/3, 1: ok, UYGUN".

### Tarama artık kaydedip kaydetmeyeceğini de soruyor

Doğrulama sütunu ("Ağ/zaman kontrolü") bugüne kadar yalnız saat dilimi, NTP ve
maskeye bakıyordu — yani cihazın ağda olduğunu söylüyordu, kayıt alacağını
değil. Sahadaki CCTV doğrulama script'inin baktığı geri kalanı da eklendi:

- **NVR:** disk durumu ve buzzer'ın hâlâ açık olup olmadığı
- **Kamera:** SD kart, IR aydınlatma, 3. akış

Okunamayan bir kontrol "uygun" demiyor, "okunamadı" diyor. Buzzer'da bir de
şu var: bazı yazılımlarda tetikçi listesi bildirim yöntemlerini taşımıyor;
o durumda beep verebilen iki tetikçi (`diskerror`, `diskfull`) adıyla
soruluyor — aksi halde ötmeye devam eden bir kabin "sessiz" görünüyordu.

### Cihaz ayarları penceresi ayar adlarını yazıyor

Pencerenin ilk sütunu ayarın adı yerine mesaj anahtarını gösteriyordu
(`field.sipPbx`). Grup kartı adı çeviriyordu, satırlar çevirmiyordu.

### IP ekranı: başlat düğmesi formu kesmiyor, maske gerçek değeriyle duruyor

- **"IP atamayı başlat" çubuğu artık ekranın altına yapışmıyor.** Yapıştığı
  için formun ortasında duruyor, arkasındaki adresleme satırlarını ve işlem
  özetini örtüyordu — yani operatörün onaylamak üzere olduğu "Hedef" ve
  "Atanacak maske" satırlarını. Çubuk formun bittiği yerde duruyor.
- **Tek porta elle IP atama kartına "Atanacak maske" alanı eklendi.** Orada
  yalnızca "maske {x} olarak yazılır, üstteki karttan değiştirebilirsiniz"
  yazıyordu; tek port atarken maskeyi değiştirmek için başka bir karta
  çıkmak gerekiyordu. İki kutu tek ayarı gösteriyor: birine yazınca diğeri de
  değişiyor.
- **Hayalet placeholder metinleri kaldırıldı.** "Atanacak maske" kutusu artık
  yazılacak maskeyi gerçek değer olarak gösteriyor; port, fabrika adresi ve
  arama aralığı kutularındaki soluk örnekler zaten altlarındaki yardım
  satırında yazdığı için kaldırıldı.

### Doğrulama ekranı programın geri kalanıyla aynı ölçekte

Cihaz denetimi tablosunda cihaz adı ve erişim durumu 15 piksel, yani yanındaki
cihaz listesinden iki kademe büyük yazılıyordu; satır yüksekliği de ona göre
48 pikseldi. Tablo artık panelin her yerinde kullanılan ölçeği ve satır
yüksekliğini kullanıyor.

### Doğrulama ekranı bütün cihazları listeliyor

Liste yalnız sapması olan cihazları gösteriyordu; bu "ne bozuk" sorusunu
yanıtlıyor ama "her şey kontrol edildi mi" sorusunu yanıtlamıyordu — sorunsuz
bir cihazla listede hiç olmayan bir cihaz aynı görünüyordu, ikisi de yok.
Artık kapsamdaki her cihaz satırda: incelenecekler üstte, geri kalanlar
altında yeşil **"Sapma yok"** ile. Sekmenin adı da içeriğe uydu: *Sapmalar* →
*Cihaz denetimi*, ve başlıktaki rozet "14 incelenecek · 42 cihaz" diyor.

### Tarama sürerken ana sayfa canlı

Ana sayfadaki bütün sayılar taramanın **bitmesini** bekliyordu: oturumun ilk
taraması boyunca — yani operatörün en çok baktığı dakikada — kutucuklar "—"
gösteriyor, kart "henüz tarama yapılmadı" diyordu; oysa cihazlar kuyrukta tek
tek yeşile dönüyordu. Artık yanıt veren cihaz o anda sayılıyor: kutucuklar ve
kategori çubukları dolmaya başlıyor, kontrol özeti "Tarama sürüyor · 9/15
cihaz okundu" diyor ve bittiğini yalnız gerçekten bittiğinde söylüyor.

### Kamera ve NVR ayarları panele girdi

Kamera ve NVR konfigürasyonu bugüne kadar terminalden, proje ve tren seti
sorulan iki ayrı script ile yapılıyordu. Artık **Ayarlar** ekranında: cihaz
tipi listesinden Camera veya NVR seçiliyor, geri kalanı diğer cihazlarla aynı
— ortak değerler grup kartında, cihaza özel olanlar cihazın penceresinde,
yazma işlemi iş kuyruğunda.

- **Kameraya yazılanlar:** saat dilimi ve NTP sunucusu, kamera adı, ses
  (arka ve pantograf kameralarında mikrofon yok, kapalı geliyor), IR
  aydınlatma, üç akış profili ve 3. akış. 3. akış kapalıysa açılıyor, kamera
  yeniden başlıyor ve panel geri gelmesini bekleyip profili yazıyor — elle
  yapıldığında en çok atlanan adım buydu.
- **NVR'a yazılanlar:** saat dilimi ve NTP, kameraların kanal olarak
  eklenmesi, sesli uyarının kapatılması ve sonda yeniden başlatma. Kanal
  listesi projeye özel bir tablodan değil DeviceMap'ten türüyor: kameranın
  `CameraID` alanı kanal numarası, `CameraName` alanı kanal adı. Projeye
  kamera eklendiğinde NVR'a da kendiliğinden geliyor.
- **Ağ ayarına dokunulmuyor: adres ve maske SADP ile veriliyor.** Sahadaki
  script maskeyi yazınca cihaz isteği kabul ediyor, ardından kendi adresinde
  kayboluyor; geri getirmek için kabinde elektrik kesip SADP ile IP'yi
  yeniden vermek gerekiyor. Panelden geri alınamayacak tek ayar bu olurdu,
  bu yüzden panele alınmadı. Panel maskeyi okuyup raporluyor: doğrulama
  sütununda beklenenden farklıysa "Maske" diyor, ayar penceresinde salt
  okunur satır olarak duruyor.
- **Sağlam SD kart / disk biçimlendirilmiyor.** Yalnız formatsız veya arızalı
  olan biçimlendiriliyor — bir ayar uygulanırken kayıt silinmesi kabul
  edilebilir bir yan etki değil. Onay penceresi bunu ve yeniden başlatmayı
  önceden söylüyor.
- **Değişmeyen ayar için istek atılmıyor.** Cihazda zaten doğru olan değer
  uğruna kamera karartılmıyor, hiçbir şey değişmediyse NVR yeniden
  başlatılmıyor; satır "zaten uyumlu" diyor.
- Hareket algılama (motion detection) bu projede kullanılmadığından panele
  alınmadı.

### Saha kontrolü: set 8 seçilince ağ gerçekten hazır mı

Senaryo şu: operatör 8. vagonu seçiyor, ama cihazların hepsi hâlâ fabrikadan
geldikleri `10.1.1.x` adresinde. **İki ağ birden gerekiyor** — cihazların
bulunduğu `10.1.1.0/24` ve switch'lerin ve yazılacak adreslerin bulunduğu
`10.8.1.0/24` — ve depo ağındaki bir dizüstü ikisinde de değil. Hesap doğru
çalışıyordu; üç boşluk vardı.

- **IP ekranı, panel hangi ağ kartının cihazlara gittiğini bilmiyorsa artık
  başlatmıyor.** Panel bunu bilerek tahmin etmiyor (yanlış tahmin, telefona
  bağlı bir dizüstünde telefonu seçiyordu). Ama bunu yalnız iş kuyruğu
  söylüyordu — yani koşu başladıktan sonra. Şimdi düğme kapalı, sebebi ekranda
  yazıyor ve yanında **"Ağ ekranını aç"** düğmesi var. Bir kez seçmek yetiyor.
- **Cihaz ayarları ve yazılım yükleme de artık ağı hazırlıyor.** Tarama ve IP
  atama bunu hep yapıyordu, bu ikisi yapmıyordu: set değiştirip doğrudan bu
  ekranlara giden ya da otomatik turları duraklatmış olan biri, sebebi
  görünmeden her satırda "cihaza ulaşılamıyor" alıyordu.
- **Arayüz seçimi kaydedilemezse artık söyleniyor.** Yazma hatası sessizce
  yutuluyordu: ekran "seçildi" diyor, hiçbir şey kaydedilmiyor ve bir sonraki
  açılışta panel yine soruyordu. Panelin kendi başına bulamadığı tek şey bu
  seçim; sessizce kaybetmek en kötü kaybetme biçimi.

### Kaldırıldı: set aktarma

Cihazları bir setten diğerine IP atayarak taşıma seçeneği kaldırıldı. Kaynak
set alanı, ilgili doğrulama ve plan parametresi de gitti. Compartment LCD'leri
1. set adreslerine döndürme bundan etkilenmiyor — o, aynı mekanizmayı ters
yönde kullanan ayrı bir akış ve yerinde duruyor.

### Arayüz denetimi: 18 maddenin tamamı kapatıldı

Çalışan sürüm üzerinde bir arayüz denetimi yapıldı — altı ekran gezildi, renk
kontrastı ve yazı boyutları tarayıcıda ölçüldü, klavye ve ekran-okuyucu
davranışı denetlendi. Çıkan 18 maddenin hepsi giderildi; envanter sırasında
bulunan altı madde daha eklendi.

**Okunabilirlik.**

- **İkincil metin rengi kontrast eşiğine çıkarıldı.** `--text-dim` panel
  zemininde 3.38:1'di — normal metin için gereken 4.5:1'in altında — ve
  zaman damgalarından alan açıklamalarına, alt bilgiden "son tarama"
  satırına kadar panelin en yaygın ikincil rengiydi. Artık 4.58:1.
- **Durum rengi ile durum metni ayrıldı.** Satırda "Hata" yazan kırmızı
  3.7:1'deydi, gri ise daha da koyu. Nokta ve kenarlar eski renkleri
  kullanmaya devam ediyor; okunacak kelimeler kendi jetonlarını aldı.
- **Yazı ölçeği yeniden kuruldu.** 22 ayrı boyut (9 px'ten 32 px'e, yarım
  piksel adımlarla) ve JavaScript içine yazılmış 49 satır içi boyut vardı.
  Yerine sekiz basamaklı, `rem` tabanlı tek bir ölçek geldi; en küçük metin
  9 px'ten 11 px'e çıktı ve tarayıcı yakınlaştırması ile işletim sisteminin
  yazı boyutu tercihi artık çalışıyor.
- Bu ikisi için **kalıcı test kapısı** eklendi: kontrastı düşen bir renk ya
  da ölçek dışında seçilmiş bir boyut derlemeyi kırıyor.

**Bilginin görünür olması.**

- **Bir işin neden başarısız olduğu artık satırda yazıyor.** Sebep yalnız
  fare ipucundaydı: klavyeyle okunamıyor, ekran okuyucuya gitmiyor ve
  ekran görüntüsüne girmiyordu. Not yalnız başarısız, uyarılı ve atlanmış
  satırlarda çıkıyor — hepsinde çıkarsa kuyruk okunmaz hâle geliyor.
- **Tablolar tablo oldu.** Dokuz veri ızgarasının hepsi `role` nitelikleri
  taşıyor; 42 satır × 8 sütunluk cihaz listesi ekran okuyucuya sütun
  başlıklarıyla birlikte ulaşıyor. Görsel yerleşim değişmedi.
- **Kuyruk sayaçları etiketlendi.** `0 0 33` üç sayıyı yalnız renkle ayırt
  ediyordu; artık her sayının yanında durumunun şekli var.

**Klavye ve ekran okuyucu.**

- Ekran değiştiğinde **odak içeriğe taşınıyor** ve ekranın adı hem tek `h1`
  hem de ayrı bir canlı bölge üzerinden duyuruluyor. Öncesinde odak menü
  düğmesinde kalıyordu ve hiçbir şey duyurulmuyordu.
- `<main>` bölgesi ve **"İçeriğe atla"** bağlantısı eklendi.
- **Klavye kısayolları:** `1`–`6` ana ekranlar, `/` cihaz araması, `?`
  kısayol listesi. Bir alana yazarken hiçbiri devreye girmiyor.
- Klavye odak halkasını tamamen silen bir kural kaldırıldı.

**Güvenlik eşiği.**

- **Cihazı yeniden başlatan, adresini değiştiren ya da beslemesini kesen her
  işlem artık onay istiyor** ve kaç cihazı, hangi portları etkilediğini
  yazıyor. Eskiden kural tersine işliyordu: yazılım yükleme ve fabrika
  sıfırlama soruyordu, "IP atamayı başlat" ile "N cihaza uygula" tek tıkla
  gidiyordu — panelin en ağır iki işlemi, soru sormayan iki işlemdi.
- **Hata mesajları artık kaybolmuyor.** Kapatılana kadar duruyor ve üst üste
  yığılıyor; öncesinde altı saniye sonra siliniyor ve bir sonraki "iş kuyruğa
  alındı" mesajı üzerine yazabiliyordu.

**Yerleşim ve bulunabilirlik.**

- **İşlem kuyruğu artık içeriği örtmüyor:** geniş pencerede kendi sütununu
  alıyor, dar pencerede örtüyor ama arkayı karartıyor. Kuyruk her iş
  başlatıldığında kendiliğinden açıldığı için "IP atamayı başlat" düğmesinin
  panelin altında kalması istisna değil, olağan durumdu.
- **Cihaz listesine arama ve sütun sıralaması eklendi.** Arama ad, tür, port,
  IP, sürüm ve hata metni üzerinde çalışıyor; birden çok kelime aynı anda
  aranıyor. IP sıralaması oktetlere göre yapılıyor.
- **Birincil eylem formun altına taşındı** ve kaydırırken orada duruyor;
  hazırlık göstergesi de yanında.
- **Ağ ekranı tek satırlık bir durum ile başlıyor** ("Hazır — ek adres
  gerekmiyor" / "2 ağa erişim yok"); üç açıklama paragrafı katlanabilir bir
  bölüme alındı.
- **Genel bakış** ekranı ilk taramadan önce "şimdi ne yapmalıyım" kartını öne
  alıyor; boş sayaçlar aşağı iniyor.
- **Kenar çubuğu adlarıyla açık başlıyor.** Altı soyut ikon, ara sıra
  kullanan biri için ezber yüküydü.

**İlk temas.**

- **Rol seçimi ekranı ne seçtiğinizi söylüyor.** İki özdeş kartın altına
  birer cümle eklendi ve ters duran ikonlar düzeltildi: "Kullanıcı"da kalkan,
  "Admin"de kişi silüeti vardı.
- **"Giriş bilgisi gerekenler" paneli boşken açıklıyor.** Bomboş bir kutu
  gösteriyordu; oysa IP ekranı aynı anda "kimlik girin" diyebiliyor. İki
  farklı şeyin aynı kelimelerle anlatıldığı artık yazıyor ve kimliğin nereden
  girileceği söyleniyor.
- **Yönetici yetkisi doğrudan sistemden isteniyor.** Panelin kendi "yönetici
  olarak yeniden başlat / çıkış" penceresi kaldırıldı: veremediği bir şeyi
  soruyordu ve kullanıcı aynı kararı iki kez veriyordu, önce panele sonra
  işletim sistemine. Artık uygulama açılırken doğrudan sistemin parola kutusu
  çıkıyor.
- **İzin verilmezse panel açılmıyor.** Ardından sebebini söyleyen tek bir
  pencere çıkıyor — yetkinin ne için gerektiğini dört madde hâlinde yazıyor ve
  içeri giden bir yol sunmuyor. Uygulamayı çift tıklayıp hiçbir şey
  olmamasındansa sebebi görmek yeğdir.
- Dock simgesi artık ancak devir gerçekleştikten sonra gizleniyor; öncesinde
  parola kutusu görünmeyen bir uygulamadan geliyormuş gibi duruyordu.
- Vazgeçilen bir yükseltme isteğinde arkada kalan parola penceresi de
  kapatılıyor.
- `PANEL_ELEVATION_PROMPT=0` artık yükseltme denemesinin kendisini de
  durduruyor: kendi penceremiz kalktığı için CI'da bir sonraki adım doğrudan
  parola kutusu olurdu.

**Kaldırıldı / düzeltildi.**

- Yazılım yükleme onay penceresindeki, kataloğa hiç girmemiş İngilizce cümle
  çevrildi; dil kapısı şablon dizelerini de görüyor artık.
- 8 kırılma noktası 4'e indi (1080 / 900 / 720 / 620); aralarında davranış
  farkı olmayan eşikler birleştirildi.

### Panel artık bilgisayarın ağını kendisi hazırlıyor

- **Sorun.** Bilgisayar `10.17.1.222/24`, switch'ler `10.17.1.100/101`,
  intercom'lar ise fabrika adresi `10.1.1.12` üzerindeyken IP ataması hiçbir
  portu tamamlayamıyordu. Switch okunuyor (aynı /24), cihaz okunamıyordu:
  bilgisayarın `10.1.x` ağında adresi olmadığı için yoklama paketi makineden
  bile çıkmıyor, koşu bunu "cihaz bulunamadı" diye bildiriyordu. Adresi
  sistem ayarlarından elle eklemek gerekiyordu.
- **Çözüm.** Panel, bir işlem başlarken hangi ağlara erişmesi gerektiğini
  hesaplıyor ve eksik olanlar için kullandığı ağ arayüzüne **ikincil bir
  adres** ekliyor (varsayılan olarak o ağın `.225`'i, `/24`). Fabrika adresi
  hangi sete girileceğinden bağımsız olduğu için bu adım artık her
  yapılandırılmamış cihazda gerekiyor.
- **Nerede çalışıyor:** IP atama, fabrika sıfırlama, tam tarama ve adres
  haritası. macOS, Windows ve Ubuntu'da.
- **Sormadan, ama görünür.** Eklenen her adres iş kuyruğunda kendi satırını
  alır ve yeni **Ağ** ekranında listelenir.
- **Eklenen adresler uygulama kapanınca kaldırılır.** Oturum boyunca durur,
  çünkü koşudan sonraki tarama, konfigürasyon ve yazılım yükleme ekranları da
  aynı erişime muhtaç. Uygulama çökerse adres arkada kalır; bir sonraki
  açılışta panel bunu kendisi temizler. Windows'ta adres kayıt defterine
  yazılmadığı için yeniden başlatma da temizler.
- **Var olan yapılandırmaya dokunulmaz.** Panel yalnızca kendi adresini
  ekler ve yalnızca kendi eklediğini kaldırır; bilgisayarın asıl adresi,
  DHCP ayarı, yönlendirme tablosu ve VLAN'lar değiştirilmez.

- **Adresler:** seçilen arayüze her zaman `10.1.1.225/24` verilir (fabrika
  ağı), üstüne seçili tren setinin ağı eklenir — set 14 için `10.14.1.225/24`.
  Sistem baştan sona `/24` maskeyle ilerler; son oktet ve önek kullanıcı
  ayarı değildir.
- **Set değişince kendiliğinden.** Yeni set seçildiğinde başlayan keşif turu
  ağı da hazırlar; ayrıca bir düğmeye basmak gerekmez. Uygulamayı kullanan
  kişinin ağ hakkında hiçbir şey bilmesi gerekmiyor.
- **Uygulama açılır açılmaz.** Daha önce seçilmiş bir arayüz varsa ilk tarama
  beklenmeden `10.1.1.225/24` hazırlanır. Arayüz yoksa ya da seçim belirsizse
  panel tahmin etmez ve kullanıcı seçimini bekler.
- **Arayüz değişikliği gerçekten taşır.** Panel en3 üzerinde açıldıktan sonra
  en6 seçilirse kendi eklediği adres en3'ten kaldırılıp en6'ya eklenir. Arka
  plandaki bir tarama aynı anda çalışsa bile eski arayüze geri ekleyemez.

### Compartment LCD: APK yükleme ve IP atama

- IP atama ekranına **Compartment LCD** hedefi eklendi. DeviceMap'teki
  cihazlar switch portlarında sırayla işlenir; fabrika trenindeki kaynaklar
  `10.1.1.40`'tan başlar, hedefler seçili set için aynı son okteti korur
  (örneğin `10.7.1.40`). Maske varsayılan olarak `/24`'tür; aşağıdaki
  "Atanacak maske" alanından değiştirilebilir.
- Port alanının üstündeki **işlem switch'i** ayrıca seçilebilir. Örneğin
  DeviceMap'te LCD düzeni `sw1` altında olsa da cihazlar geçici olarak `sw2`
  üzerinden devreye alınabilir. PoE, MAC tablosu ve switch kimliği seçilen
  fiziksel switch'ten; cihaz adı, port, kaynak ve hedef IP ise değişmeden
  DeviceMap'in kanonik LCD düzeninden gelir. Bu esneklik yalnız LCD akışına
  açılmıştır; Intercom eşlemesi sessizce başka switch'e taşınmaz.
- LCD test kablosu DeviceMap'te cihaz tanımlı olmayan **herhangi bir fiziksel
  PoE portuna** takılabilir. Örneğin port 8 artık hata/uyarı üretmez. Port
  izole edildikten sonra kaynak ve hedef aday adresleri sınırlı biçimde
  taranır; cevap veren LCD'nin MAC'i gerçekten seçilen portta görülürse kendi
  DeviceMap kimliği ve hedef IP'si kullanılır. Uplink, bilgisayar ve
  switchler-arası korunan portlar seçilemez. Intercom için tanımlı-port kuralı
  değişmemiştir.
- IP hedefi ve cihaz satırları DeviceMap'teki adları **aynen** gösterir;
  envanter adı çevrilmez veya yeniden adlandırılmaz.
- İstenirse APK, cihaz kaynak adresindeyken ve portta tek başınayken yüklenip
  sürümü doğrulanır. APK kurulamazsa o cihazın IP'sine dokunulmaz.
- macOS'un APK'yı genel `public.data` sayıp dosya penceresinde gri bırakması
  giderildi. Pencere dosyayı seçilebilir gösterir; sunucu seçimden sonra
  `.apk` uzantısını kesin olarak denetler. `.bin` sınırı 32 MiB kalırken tek
  APK sınırı 512 MiB'dir; 125 MiB'lik test APK'sı bu akıştan geçirilmiştir.
- Kurulum doğrulaması artık sabit panel paket adına bağlı değildir. Seçilen
  APK'nın `AndroidManifest.xml` içindeki paket kimliği ve sürümü okunur;
  `adb install` sonrasında tam o paket `dumpsys package` ile doğrulanır.
  `.xapk`, `.apks`, `.apkm` ve ayrı OBB gerektiren dağıtımlar bu tek-APK
  akışının kapsamında değildir.
- ADB hiçbir zaman cihaz listesindeki ilk kaydı kullanmaz. Her komut açıkça
  `<kaynak-ip>:5555` ya da `<hedef-ip>:5555` transportuna gönderilir; IP
  değişiminden sonra eski ve yeni ADB kayıtları ayrı ayrı temizlenir.
- Başarı yalnız yeni adreste **aynı Android seri numarası**, doğru switch
  portu ve `eth0` üzerinde yalnızca `<hedef-ip>/<seçilen maske>` görülürse
  verilir. Eski `/16` adresi kalmışsa port tamamlanmış sayılmaz.
- Seçilen portlar koşu boyunca yalıtılır; tamamlanan ekranlar açık kalır ve
  işlem bittiğinde ya da iptal edildiğinde yönetilen bütün portlar yeniden
  açılır.

### Atanacak IP'nin maskesi girilebiliyor

- IP atama ekranındaki **"Atanacak maske"** alanı, cihaza yazılacak maskeyi
  belirler. Boş bırakılırsa proje varsayılanı `255.255.255.0` kullanılır;
  `255.0.0.0` da `/8` de yazılabilir. Sınır `/8` ile `/30` arasıdır.
- Compartment LCD için bu doğrudan `ip addr add <adres>/<maske>` komutuna
  girer ve koşu sonundaki doğrulama da aynı maskeyi arar.
- Intercom için maske normalde **cihazın kendi bildirdiği maskedir** ve
  panel ona dokunmaz. Alan doldurulduğunda seçim bilinçli sayılır ve cihazın
  bildirdiğinin yerine geçer; boş bırakıldığında eski davranış aynen sürer.

### Compartment LCD: 1. set adreslerine döndürme

- LCD hedefinde **"1. set adreslerine döndür"** kartı var. Intercom'daki
  fabrika sıfırlamanın karşılığı, ama aynı şey değil: burada ekranlar tek bir
  adreste toplanmaz. Her ekran DeviceMap'teki son oktetini korur ve
  `10.1.1.40`, `.41`, … adreslerine döner.
- Bu, sıradan IP atama koşusunun iki setinin yer değiştirmiş hâlidir: portlar
  sırayla açılır, ekran ADB ile bulunur, MAC'i o portta doğrulanır ve adres
  yazıldıktan sonra yeniden bağlanılarak denetlenir. İkinci bir uygulama
  yazılmadı.
- Cihazların hangi sette olduğu karttan seçilir: açık set ya da elle girilen
  bir set.

### Compartment LCD: tek porta elle IP atama

- LCD hedefinde **"Tek porta elle IP atama"** kartı var. Bir port ve bir
  adres girilir; DeviceMap'e hiç bakılmaz. Amaç, ait olduğu tren seti henüz
  yokken tek bir ekranı tezgâhta denemek.
- Ekranın **şu anki adresi sorulmaz**: port izole edildikten sonra
  DeviceMap'teki bütün Compartment LCD adayları (1. set, açık set, varsa
  girilen kaynak set) ve istenen adresin kendisi sınırlı biçimde taranır.
- Kanıt kuralı değişmiyor: yalnız seçilen port beslenir, cevap veren ekranın
  MAC'i gerçekten o portta görülmeden hiçbir komut gönderilmez ve iş bittiğinde
  aynı Android seri numarası yeni adreste, `eth0` üzerinde başka adres
  kalmadan bulunmalıdır.
- Aynı adresi ikinci kez yazmak zararsızdır: ekran zaten oradaysa hiçbir
  komut gönderilmez.

### Cihaz ayarlarında Compartment LCD

- **Cihaz ayarları** ekranına Compartment LCD eklendi. Şimdilik tek bir
  yazılabilir alanı var: **IP adresi**. Ekranın bildirdiği sürüm, seri numarası
  ve SIP kaydı ise okunur olarak listelenir.
- Diğer cihazlar ayarlarını HTTP ucundan alır; Android ekranın böyle bir ucu
  yok, bu yüzden okuma ve yazma ADB üzerinden yapılır.
- **Maske değiştirilmez:** ekran hangi maskeyi kullanıyorsa o korunur. Maskeyi
  değiştirmek devreye alma kararıdır ve IP atama ekranındaki alana aittir.
- Yazmanın başarılı sayılması için komutun cevabı yetmez — adres değişimi o
  cevabı zaten çoğu kez kesiyor. Yeni adrese yeniden bağlanılır, **aynı
  Android seri numarası** aranır ve `eth0` üzerinde başka adres kalmamış
  olması istenir.

### Kaldırıldı: "beklenen sürüm" alanları

- Yazılım ekranındaki toplu **"Hedef sürüm"** kutusu, satır başına düşen
  sürüm sütunu, IP ekranındaki APK sürüm kutusu ve `.bin` yüklemedeki
  **"Beklenen sürüm"** alanı kaldırıldı. Elle yazılan bu değer, dosyanın
  kendisinde zaten yazan bilgiyi tekrar ediyor ve yanlış yazıldığında başarılı
  bir kurulumu hata gösteriyordu.
- APK doğrulaması kaybolmadı: kurulumdan sonra beklenen sürüm artık seçilen
  APK'nın kendi `AndroidManifest.xml` dosyasından okunuyor.
- `.bin` yüklemede kurulum sonrası cihazın geri gelip **bir sürüm bildirmesi**
  hâlâ şart; karşılaştırılacak elle girilmiş bir değer yok.

### IP atamadan önce yazılım yükleme

- Sahaya uzun süre önce gönderilmiş bazı intercomların yazılımı, **kendi
  sürümünü ve kimliğini yanlış bildirecek kadar** eski; bu cihazlara IP
  atamadan önce yazılım atılması gerekiyor.
- IP atama ekranına **"Adres atamadan önce yazılım yükle"** seçeneği eklendi.
  Açıldığında bir `.bin` dosyası sorulur.
- Koşu portu açıp cihazı fabrika adresinde bulduğu anda — tek bir cihazın
  erişilebilir olduğu **tek an** — yazılımı yükler, cihazın geri gelmesini
  bekler, sonra IP'yi yazar.
- **Seçilen her porta yüklenir.** Cihazın bildirdiği sürüme bakılarak atlama
  yapılmaz: bu adımın var olma sebebi, o cihazların sürümlerini yanlış
  bildirmesi. Sürüm yine de yükleme öncesi ve sonrası okunup koşu günlüğüne
  yazılır.
- **Yükleme başarısız olursa o portun IP'si yazılmaz**, port başarısız
  işaretlenir ve sebebi satırda görünür. Koşu diğer portlarla devam eder.
- Dosya koşu için tektir ve **yolu tarayıcıya hiç gitmez**: seçim işletim
  sisteminin kendi penceresinden yapılır, ekran yalnız dosya adını görür.

### Yeni ekran: Ağ

- Kenar çubuğunda yeni bir alan. Kullanılan arayüzü ve ona verilen adresi,
  bu setin gerektirdiği ağları ve panelin eklediği adresleri gösterir.
- **Panel arayüzü tahmin etmez.** Yalnız cihazların ağında (`10.1.1.x`, ya da
  setin ağında) halihazırda adresi olan bir arayüzü kendiliğinden seçer.
  Böyle bir arayüz yoksa **hiçbir şey seçmez** ve sorar. Önceki hâli
  sıralamaya düşüyordu ve telefon internetine bağlı bir dizüstünde telefonu
  seçiyordu — adres hiçbir yere gitmeyen bir karta ekleniyor, koşu eskisi
  gibi başarısız oluyor, ekran ise arayüz seçildiğini yazıyordu.
- **"Ağı hazırla" düğmesi yok.** Ağ ekranını açmak, arayüz seçmek, bir koşu
  ya da tarama başlatmak ve tren setini değiştirmek — dördü de ağı
  kendiliğinden hazırlıyor. Ekranda kalan tek düğme "Geri al"; eklenen adresi
  geri almanın başka yolu yok, eklemenin ise dört yolu var.
- Adres biçimi sabittir: panel her zaman `.225/24` kullanır ve gerektiğinde
  kendiliğinden hazırlar. Ağ ekranında bunun için ayrı bir ayar bloğu yoktur.
- **Bilinen sınır, ekranda da yazıyor:** çakışma denetimi DeviceMap ve
  bilgisayarın kendi adresleri üzerinden yapılır; adresi zaten kullanan
  üçüncü bir cihaz, bağlantı denenene kadar görülemez.

### Yan düzeltme: ifconfig'i olmayan Linux

- `ifconfig` kurulu olmayan güncel Ubuntu'da bilgisayarın hiçbir ağ arayüzü
  okunamıyordu; koşunun korunacak portu (bilgisayarın takılı olduğu port) bu
  yüzden bulunamıyordu. `ip` komutunun iki çıktısı artık birleştiriliyor:
  `ip -o link` MAC adresini, `ip -o addr` adresleri veriyor — hiçbiri tek
  başına yetmiyordu.

## v0.9.7 — 14 Ağustos 2026

`dap-v0.9.1-dev` etiketinden bu yana yayımlanan ilk sürümdür: v0.9.2, v0.9.3,
v0.9.5 ve v0.9.6 için hazırlanan bütün değişiklikler bu paketin içindedir.

### Uygulama artık Türkçe ve İngilizce

- Arayüzün tamamı **iki dilli**. Dil, rol seçim ekranının sağ üst köşesinde
  ve üst barda duran **TR / EN** düğmesiyle değiştiriliyor; seçim
  kaydediliyor ve uygulama bir daha aynı dille açılıyor.
- **Varsayılan Türkçe.** İşletim sisteminin dili İngilizceyse panel İngilizce
  açılır; başka bir dilse ya da hiç belirtilmemişse Türkçe açılır.
- Çeviri yalnız etiketleri değil **hata mesajlarını, işlem kuyruğu
  satırlarını ve iş başlıklarını** da kapsıyor. Dil süren bir koşunun
  ortasında değiştirilirse kuyruktaki satırlar da o anda yeni dile geçiyor.
- **Uygulamanın adı da dili izliyor:** Türkçede *Devreye Alma ve Bakım
  Paneli*, İngilizcede *Commissioning and Maintenance Panel*. Pencerenin
  başlık çubuğu dil değiştiği anda güncelleniyor. Kurulum sihirbazı, Başlat
  menüsü girdisi ve macOS paket adı derleme sırasında sabitlendiği için her
  zaman Türkçe.
- Bütün metinler tek bir sözlük dosyasında toplandı; bir ifadeyi düzeltmek
  için uygulamanın yeniden derlenmesi gerekmiyor.
- **Çeviri artık gerçekten her ekranı kapsıyor.** İlk turda geçmiş ekranı,
  Excel önizleme, doğrulama bulguları, IP atama uyarıları, switch ön paneli,
  cihaz detay paneli ve firmware ekranı kısmen İngilizce kalmıştı; bu
  sürümde arayüzün tamamı gözden geçirildi. Excel dosyasının **sütun
  başlıkları** şablondan geldiği için hem ekranda hem dosyada İngilizce
  kalır — önizleme, üretilecek dosyanın birebir aynısıdır.

### Dikkat: bu sürümde taşınmayanlar

- **Dosya adları değişti.** Paketler artık `dabp-<sürüm>-…` adıyla
  yayımlanıyor; çalıştırılabilir dosya `dabp`, Windows kurulumu ise
  `dabp` klasörüne yapılıyor. Eski sürümün kısayolu yeni kuruluma işaret
  etmez; kısayolu yeniden oluşturun. Eski kurulumu Windows "Uygulamalar"
  listesinden ayrıca kaldırabilirsiniz.
- **Konfigürasyon ekranında kayıtlı hedef değerler taşınmıyor.** Ayarların
  saklandığı klasör uygulama adıyla birlikte değiştiği için, önceki
  sürümlerde girilmiş varsayılanlar bu sürümde boş gelir ve bir kez yeniden
  girilmelidir. (Parolalar hiçbir zaman diske yazılmıyordu, onlarda değişen
  bir şey yok.)
- **Excel şablonu yenilendi:** dosya adı `Field_Device_Verification.xlsx`,
  sayfa adı `Checklist` ve sütun başlıkları İngilizce oldu. Eski şablondan
  elle doldurulmuş dosyalarınız varsa saklayın; yeni şablonla birleşmezler.

### IP atama koşusu daha güvenilir raporluyor

- Koşunun ilerlemesi artık saha betiğinin **yazdığı cümlelerden** değil,
  betiğin ürettiği **yapılandırılmış olaylardan** okunuyor. Daha önce bir
  cümlenin kelimesi değiştiğinde ilerleme çubuğu ve port satırları sessizce
  bozuluyordu; artık metin serbestçe değişebiliyor.
- Port satırlarının durumu, adım geçmişi ve yüzdesi bu olaylardan geliyor;
  ham çıktı eskisi gibi tek satırdan açılan koşu günlüğünde duruyor.

### Kontrol listesi

- Excel sütunları koda **sabit kimliklerle** bağlandı. Başlık metni artık
  ekranda görünen bir etikettir; başlığı değiştirmek sütunu boşaltmıyor.

### Düzeltmeler

- IP ekranındaki ön panel lejandında **"besliyor" örneği 320 piksel
  yüksekliğinde çerçeveli bir kutu olarak çiziliyordu**; MQTT ekranının
  kutusuyla aynı sınıf adını paylaşmasından kaynaklanıyordu.
- Doğrulama ekranındaki tablo, sayfa yenilendiğinde bazı sütunları
  "erişilemez" sayabiliyordu.
- Masaüstü paketinin bütünlük denetimi, birden çok stil dosyası kullanılınca
  hatalı biçimde başarısız oluyordu.
- Panelin HTTP başlığı ve birkaç iç yol hâlâ eski uygulama adını taşıyordu.

## v0.9.6 — Yayımlanmamış

### Fabrika adresinde toplama yeniden yazıldı

- **Aynı adreste birden çok cihaz kalıyordu.** İşlem her cihaza yalnız
  DeviceMap'teki adresinden ulaşmayı deniyor ve tek tur yürüyordu; iki cihaz
  aynı adresi paylaştığında yalnız biri taşınıyor, ikincisi kaç kez
  denenirse denensin orada kalıyordu. Akış artık tur tur yürüyor: her turda
  bütün aday adresler yoklanıyor, cevap veren her cihaz fabrika adresine
  yazılıyor ve adresin gerçekten boşaldığı doğrulanıyor.
- **Cihaz artık kendi kimliğiyle tanınıyor.** Intercom, dahili numarasını
  (`pbxExtension`) bildiriyor ve DeviceMap aynı alanı taşıyor; hangi cihazın
  hangi porta ait olduğu böylece switch kimliğine ve ARP'a gerek kalmadan
  kesin biçimde çözülüyor. Başka bir cihazın adresinde duran cihaz da doğru
  satıra yazılıyor.
- **"Adresinde cevap yok" artık hata sayılmıyor**, atlandı olarak
  işaretleniyor: cihaz büyük olasılıkla zaten fabrika adresindedir. İşi
  başarısız yapan tek şey cihazın eski adresinde kalması.
- İşlem yüzdesi ilerliyor ve her cihaz için ayrı satır açılıyor; eskiden
  çubuk baştan sona %0 duruyordu.

### IP atama koşusu

- **Koşudan sonra cihaz kimliği doğrulanıyor.** "Port tamamlandı" demek
  yalnız "hedef adres cevap verdi" demekti; koşu yanlış cihaza yazmış
  olabiliyordu. Artık her portun hedef adresindeki cihazın dahili numarası
  DeviceMap'le karşılaştırılıyor, uyuşmayan port kırmızı işaretleniyor ve
  iş özeti cihazların karıştığını söylüyor.
- **Kalıcılığı doğrula** seçeneği kaldırıldı. Panel, işi biten cihazları
  yeniden karartmamak için sonda güç çevrimi yapmıyor; eski istemciler de bu
  davranışı yeniden açamıyor.
- Teknik ayrıntılar bloğu kaldırıldı. Fabrika IP adresine dönüş, bulunduğu set
  ile `1..254` aralığında girilen harici set arasında seçim yapılabilen ayrı
  bir bakım kartına taşındı.

### Yönetici yetkisi

- Yetki olmadan açıldığında uygulama artık sessizce kapanmıyor: sebebi
  anlatan bir pencere çıkıyor ve **Yönetici olarak yeniden başlat** ile
  **Çıkış** sunuyor. İzni işletim sistemi istiyor (Windows'ta UAC, macOS'ta
  sistem parola penceresi, Linux'ta polkit); parola uygulamaya girilmiyor.
- Windows paketinin manifesti yönetici istiyor; çift tıklamada UAC doğrudan
  çıkıyor.
- Yükseltilmiş süreç başlatıldıktan sonra eski süreç kendini kapatıyor ve
  Dock/görev çubuğunda ikinci bir uygulama olarak durmuyor. Yeni süreç
  açılışta düşerse sebebi gösteriliyor.

## v0.9.5 — Yayımlanmamış

### Soketsiz masaüstü arayüzü

- Masaüstü uygulamasının kendi arayüz iletişimi yerel HTTP'den pywebview'un
  doğrudan Python–JavaScript köprüsüne taşındı. Normal açılışta loopback
  adresine bağlanılmaz ve dinleyen TCP portu oluşturulmaz; Nmap ile gelen
  Npcap/WFP sürücüsü gibi geri döngü süzgeçleri artık panelin açılışını
  etkileyemez.
- HTML, CSS, görseller ve JavaScript üretim için tek bir gömülü HTML
  artefaktında paketlenir. Dosya URL'leri, indirmeler ve dış bağlantılar
  kapalıdır; içerik güvenlik politikası ağ erişimini reddeder.
- Ortak servis katmanı HTTP'den ayrıldı. Aynı işlem sözleşmesi masaüstünde
  köprü, yalnız geliştirme/tanı amacıyla seçilen `--tarayici` kipinde HTTP
  adaptörü üzerinden çalışır.
- `--self-test` artık pencere veya soket açmadan gerçek üretim köprüsünü ve
  tek parça arayüz paketini doğrular.

### İşlem kuyruğu dayanıklılığı

- **Çöken bir işlem tüm paneli kilitliyordu.** İşlem gövdesi
  `SystemExit` gibi olağan dışı bir hatayla sonlanırsa iş sonsuza kadar
  **Çalışıyor** durumunda kalıyor, kuyruğun dağıtıcı iş parçacığı ise
  sona eriyordu. Cihazlara yazan bir işlem sürüyor sayıldığından hafif
  yenileme ve tam tarama istekleri reddediliyor, işlem sonrasında hiçbir
  ekran güncellenmiyordu. Bu tür hatalar artık işi hata durumunda
  kapatır ve kuyruk çalışmaya devam eder.
- Gövdesi kuyruktan düşmüş bir iş, anlaşılmayan bir tür hatası yerine
  açıklamalı biçimde sonlandırılır.
- **IP atama özeti çıkış kodu yerine sonucu bildirir.** Kısmen tamamlanan
  koşuda "betik 1 koduyla bitti" yazıyordu; artık kaç portun tamamlandığı
  ve kaçının kaldığı yazılır, ayrıntı için port satırları ve koşu günlüğü
  gösterilir.

## v0.9.3 — Yayımlanmamış

Bu sürüm yalnızca Windows'a özgü düzeltmeler içerir. Aşağıdaki sorunların
hiçbiri macOS ve Linux'ta görülmüyordu; bu yüzden geliştirme sırasında
fark edilmemişlerdi.

### Windows uyumluluğu

- **Bilgisayarın bağlı olduğu switch portu bulunamıyordu.** Korunan port
  listesi Windows'ta boş kalıyor, IP atama koşusu kendi bağlantısını
  kesme riskine karşı korunamıyordu. Nedeni, konsol çıktısının yanlış kod
  sayfasıyla çözülmesiydi: `ipconfig /all` çıktısı OEM kod sayfasıyla
  (Türkçe kurulumda cp857) yazılırken Python ANSI kod sayfasını (cp1254)
  kullanıyordu. Çıktının ilk satırındaki "ı" harfi cp1254'te tanımsız
  olduğundan çözme adımı hata veriyor ve bu hata `/api/ip/korunan` ucuna
  kadar ulaşıyordu. Komut çıktıları artık bayt olarak alınıp platforma
  uygun kod sayfasıyla, hata vermeyecek biçimde çözülür.
- **ARP önbelleği Yönetici olarak çalıştırıldığında bile
  temizlenemiyordu.** Yetki denetimi Windows'ta yalnızca POSIX'e özgü bir
  çağrıya dayandığı için sonuç koşulsuz "yetki yok" oluyordu. Denetim
  artık yükseltilmiş süreci tanır; silme işlemi `arp -d` ve gerekirse
  `netsh interface ipv4 delete neighbors` ile yapılır. Aynı fabrika
  adresini kullanan cihazlarda bayat ARP kaydı bu nedenle "cihaz
  bulunamadı" hatasına yol açmaz.
- **Yetki uyarısı Windows'ta uygulanamayacak bir öneri veriyordu.** Metin
  `sudo -v` çalıştırılmasını istiyordu; artık platforma göre üretilir ve
  Windows'ta uygulamanın Yönetici olarak başlatılması önerilir.
- **MAC ile port doğrulaması Windows'ta hiç çalışmıyordu.** ARP tablosu
  POSIX söz dizimiyle (`arp -n`) sorgulanıyor ve MAC yalnızca iki nokta
  ile ayrılmış biçimde aranıyordu. Windows'ta karşılığı `arp -a`, ayraç
  ise tiredir; ikisi de karşılanmadığı için doğrulama sessizce atlanıyordu.
- Konsolsuz Windows derlemesinde her yardımcı komut için kısa süreli bir
  konsol penceresi açılıyordu; komutlar artık pencere oluşturmadan
  çalıştırılır.

## v0.9.2 — Yayımlanmamış

Bu sürüm için hazırlanan değişiklikler `dap-v0.9.1-dev` etiketinden sonra
eklenmiştir.

> `dap-v0.9.2` ve `dap-v0.9.3` etiketleri hiç oluşturulmadı. Bu iki
> sürümün değişiklikleri ilk kez `dap-v0.9.7` ile yayımlanmıştır;
> bölümler yalnız neyin ne zaman eklendiğini göstermek için ayrı duruyor.

### Tarama ve canlı yenileme

- Yenileme akışı sürekli çalışacak biçimde yeniden düzenlendi; üst bardaki
  duraklatma düğmesi kaldırıldı.
- Tam keşif taraması 60 saniyede bir çalışır ve `DeviceMap.json` içindeki tüm
  hedefleri denetler. Oturum açıldığında veya tren seti değiştirildiğinde ilk
  tarama kısa bir gecikmeyle otomatik olarak başlar.
- Son taramada doğrulanmış cihazların verileri yaklaşık iki saniyede bir
  hafif yenilemeyle güncellenir. Ulaşılamayan cihazların zaman aşımı,
  çalışan cihazların verisini geciktirmez.
- **Güncelle** düğmesi yeni ve yinelenen bir tarama oluşturmak yerine sıradaki
  keşif turunu öne alır ve 60 saniyelik sayacı yeniden başlatır.
- IP atama, yapılandırma veya yazılım yükleme işlemi sürerken otomatik keşif
  başlatılmaz. Elle istenen tarama kuyrukta bekler; hafif yenileme de yazma
  işlemi tamamlanana kadar durur. Böylece yeniden başlatılan veya PoE gücü
  geçici olarak kesilen cihazların ara durumu kalıcı sonuç olarak yazılmaz.
- Hafif yenileme cihazları paralel okur ve MQTT verisini her turda yeniden
  toplamak yerine son keşif görüntüsünü kullanır. Sahada ölçülen 17 cihazlık
  örnekte tur süresi yaklaşık 9 saniyeden 0,6 saniyeye düştü.
- Otomatik taramalar işlem geçmişini doldurmaz; tamamlanan otomatik
  taramalardan yalnızca en yenisi saklanır. Elle başlatılan işlemler korunur.

### MQTT durum doğrulaması

- MQTT'deki *retained* `AppStatus` kaydının tek başına cihazın çevrim içi
  olduğunu kanıtlamadığı dikkate alındı. Panel artık uygulama bağlantı
  durumunu (`connected`) ve PISCU'nun canlı sağlık kaydını (`NoError`)
  birlikte değerlendirir.
- Bağlantısı kesilmiş bir HMI veya yalnızca eski MQTT kaydı kalan başka bir
  cihaz artık yeşil **Doğrulandı** olarak gösterilmez. Son bağlantı durumu ve
  başarısızlık nedeni cihaz satırında açıklanır.
- Sağlık denetiminden geçen fakat arızalı bildirilen MQTT cihazları gri
  **Uygulanmıyor** yerine kırmızı **Doğrulanamadı** durumuna alınır. Gri durum
  yalnızca ilgili denetimin o cihaz için geçerli olmadığı anlamına gelir.

### Kontrol listesi ve Excel

- Kontrol listesi, cihaz sonuçları değiştiğinde otomatik olarak yenilenir.
- Başlığın altında son tarama saati ve verinin yaşı gösterilir; yaş bilgisi
  saniyede bir güncellenir ve iki dakikayı aştığında uyarı rengine döner.
- **Excel Üret** işlemi öncesinde son tarama saati, veri yaşı ve sonuç
  sayaçlarını gösteren bir onay penceresi açılır. Veri bayatsa kullanıcı
  uyarılır ve **Önce Güncelle** seçeneğiyle keşif turu öne alınabilir.

### IP atama ve korunan bağlantılar

- Elle doldurulan **Korunan bağlantılar** formu kaldırıldı. Bilgisayarın bağlı
  olduğu portlar ile switchler arası bağlantı portları artık switchlerin MAC
  öğrenme tablolarından otomatik olarak belirlenir.
- Yerel ağ arayüzlerinin MAC adresleri tüm switchlerde paralel aranır. Erişim
  portu ile uplink portu, ilgili portta öğrenilen MAC sayısı kullanılarak
  birbirinden ayrılır.
- Komşu switchin kendi MAC adresi diğer switchin tablosunda aranarak switchler
  arası bağlantı portları belirlenir.
- Yanıt vermeyen bir switch, diğer switchlerin incelenmesini engellemez.
  **Switch ulaşılamıyor** ve **MAC tablosu okunamıyor** durumları ayrı
  açıklanır. Gerekli koruma portları bulunamazsa tahmin yapılmaz ve IP atama
  işlemi başlatılmaz.
- Korunan portlar 30 saniyede bir yeniden doğrulanır. Koşu başlatılırken
  sunucu da bulguları yeniden denetler; böylece son anda değişen kablo
  bağlantıları dikkate alınır.
- Korunan portlar switch ön panelinde turuncu, işlem özetinde ise kaynak MAC
  adresi ve doğrulama zamanı ile birlikte gösterilir.
- Switch kimlik bilgileri sonradan girildiğinde korunan port aramasının
  yinelenmemesine ve ekranın yeniden çizilmesi sırasında doğrulama
  zamanlayıcılarının sıfırlanmasına neden olan sorunlar giderildi.

### İşlem kuyruğu ve performans

- IP atama ilerlemesinin iş birimi çıktı satırı yerine hedef port olarak
  değiştirildi. İş kartı artık etkin portu, aşamayı ve toplam ilerlemeyi
  gösterir.
- Koşunun başındaki plan satırlarının etkin port sanılması düzeltildi; aynı
  anda yalnızca gerçekten işlenen port **Çalışıyor** durumunda görünür.
- Ertelenmiş doğrulama akışı için **Yazıldı** ara durumu eklendi. İlerleme;
  hazırlık (%5), temel tarama (%7), port atama (%70), PoE portlarını geri
  açma (%4) ve son doğrulama (%14) aşamalarına göre hesaplanır. Yüzde geriye
  gitmez ve yarıda kesilen işlem %100 olarak gösterilmez.
- Port bulunamadığında hata işlem sürerken görünür. Son doğrulama turu her
  port için nihai durumu belirler.
- Her port satırına, saat bilgisi içeren ve varsayılan olarak kapalı duran bir
  adım geçmişi eklendi. İkinci turdaki adımlar önceki turun ayrıntılarını
  silmez.
- IP atama betiğinin ham çıktısı işletim sisteminin Belgeler klasörüne zaman
  damgalı günlük dosyası olarak yazılır ve işlem kuyruğundan açılabilir.
- İş kartına ilerleme çubuğu eklendi; durdurma düğmesinin kart dışına taşması
  giderildi ve gereksiz uzun IP atama başlığı kısaltıldı.
- Yapılandırma yazımı aynı anda en fazla dört cihazda çalışacak biçimde
  paralelleştirildi. Eşzamanlı işlem sayısı `KONFIG_WORKER` ile ayarlanabilir.

## v0.9.1-dev — 7 Ağustos 2026

> **Geliştirme sürümü:** Saha denemeleri için yayımlanmıştır; kararlı sürüm
> olarak değerlendirilmemelidir.

### Eklendi

- Cihaz başına dosya ve hedef sürüm seçilebilen **Yazılım Yükleme** ekranı
  eklendi. Aynı dosya, istenirse tek seçimle grubun tamamına atanabilir.
- Anons ekipmanları için `.bin` imajları
  `POST /api/v1/system/firmware` üzerinden yüklenir; cihaz yeniden döndüğünde
  bildirdiği sürüm doğrulanır.
- Compartment LCD cihazlarına `.apk` paketleri `adb install -r` ile yüklenir.
  Daha eski bir sürüme dönülmesi gerektiğinde kurulum bir kez `-d` seçeneğiyle
  yinelenir ve sonuç `dumpsys package` çıktısıyla doğrulanır.
- Seçilen dosyanın varlığı, boyutu ve cihaz türüne uygun uzantısı kuyruğa
  eklenmeden önce denetlenir. Dosyası seçilmeyen cihazlar işleme alınmaz.
- Yazılım yüklemeleri aynı anda en fazla dört cihazda çalışacak biçimde
  paralelleştirildi (`FIRMWARE_WORKER`).

### Yapılandırma

- Intercom, Handset, Amplifier ve UIC cihazlarının yazılabilir SIP, ses,
  çalışma modu, kazanç, gerilim eşiği ve çağrı yönlendirme alanları cihaz
  türüne göre listelenir.
- Her ayar, cihazın kabul ettiği uç noktaya gönderilir. Yalnızca mevcut
  değerden farklı alanlar yazılır; yazma sonrasında değerler yeniden okunarak
  doğrulanır. HTTP 200 yanıtı tek başına başarı sayılmaz.
- Hedef değerler `DeviceMap.json` içinden yüklenir. Kullanıcının değiştirdiği
  hedefler uygulamanın veri dizinine kaydedilir ve sonraki açılışta geri
  yüklenir.
- `PBXPassword` tanımı bulunmayan Amplifier ve UIC cihazlarında SIP parolası
  için dahili numarayı kullanan geri dönüş kuralı eklendi. Projede açıkça
  tanımlanmış bir parola varsa öncelik bu değerdedir.

### IP atama

- Switch ön panelinden seçilen cihazlar PoE portları sırayla açılarak
  adreslenir. İşlem iptal edilse bile kapatılan PoE portları yeniden açılır.
- Fabrika IP adresi, tren setinden bağımsız olarak `10.1.1.12` kabul edildi.
  İşlem hem bu sabit adresi hem de daha önce atanmış olabilecek `10.n.1.12`
  adresini dener.
- Fabrika adresinde bulunamayan cihazlar için ağ/maskeye alternatif olarak
  açık bir IP aralığı girilebilir. Her iki yöntemde de en fazla 512 adres
  denenir.

### Depo düzeni

- Devreye Alma Paneli `main` dalının köküne taşındı.
- Çalışma anında yüklenen saha betikleri `betikler/` dizininde toplandı.
- Devreye Alma Paneli ve Switch Yönetim Paneli için etiket ve yayın akışları
  birbirinden ayrıldı.

### Güvenlik ve bilinen sınırlar

- Arayüzde girilen cihaz erişim kimlikleri süreç belleğinde tutulur ve
  uygulama kapandığında silinir. Kullanıcının arayüzde girdiği SIP parolası
  kalıcı ayar dosyasına yazılmaz. Proje envanterinde önceden bulunan tanım
  alanları bu kuralın kapsamı dışındadır.
- Yerel servis yalnızca `127.0.0.1` adresini dinler. İstemci doğrudan IP
  göndererek hedef seçemez; hedef, cihaz kimliği üzerinden envanterden
  çözülür.
- Dağıtım paketleri kod imzalı değildir. Windows SmartScreen ve macOS
  Gatekeeper ilk açılışta uyarı gösterebilir.
- Compartment LCD okuması ve yazılım yüklemesi için sistemde `adb` bulunması
  gerekir; bulunmadığında ilgili denetimler **Uygulanmıyor** olarak görünür.
- Anons cihazlarında seri numarası veri kaynağından sağlanmadığı için ilgili
  kontrol listesi hücresi boş bırakılır.

## v0.9.0-dev — 6 Ağustos 2026

İlk etiketli geliştirme sürümüdür. Cihaz doğrulama, kontrol listesi,
yapılandırma ve IP atama akışlarının saha denemelerine açıldığı temel sürümü
oluşturur.
