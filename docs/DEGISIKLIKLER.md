# Değişiklik Günlüğü — Devreye Alma Paneli

Bu belge, Devreye Alma Paneli'nin sürümler arasındaki kullanıcıya dönük
değişikliklerini kaydeder. İndirme ve kurulum bilgileri
[GitHub sürüm metninde](RELEASE_NOTES.md), teknik ayrıntılar ise
[mimari belgede](MIMARI.md) yer alır.

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

### Yeni: adres haritası

- IP ekranına **Adres haritası** düğmesi eklendi. Aday adresler salt okuma
  yoklanıp "bu adres DeviceMap'te kimin, şu an kim var, durumu ne"
  gösteriliyor: yerinde, başka cihaz, çakışma, boş. Aynı adreste birden çok
  cihaz olup olmadığı da görünüyor.

### IP atama koşusu

- **Koşudan sonra cihaz kimliği doğrulanıyor.** "Port tamamlandı" demek
  yalnız "hedef adres cevap verdi" demekti; koşu yanlış cihaza yazmış
  olabiliyordu. Artık her portun hedef adresindeki cihazın dahili numarası
  DeviceMap'le karşılaştırılıyor, uyuşmayan port kırmızı işaretleniyor ve
  iş özeti cihazların karıştığını söylüyor.
- **Kalıcılığı doğrula** seçeneği eklendi (varsayılan kapalı): koşunun
  sonunda portların gücü bir kez kesilip açılarak ayarın cihazda kalıcı
  olduğu denetleniyor.

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
