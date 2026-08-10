# Yataklı Cihaz Veri Alanları

Bu belge, `betikler/device_verify.py` dosyasının doldurduğu Excel sütunlarını
ve her alanın gerçek kaynağını tanımlar. Bilgiler sahadan alınan yanıtlarla
doğrulanmıştır. İlk taslaktan farklı çıkan noktalar, **Doğrulama notları**
başlığı altında ayrıca açıklanır.

## Şablon yapısı

Kontrol listesi üç banda ayrılır:

| Bant | Sütun | Kim doldurur |
|---|---|---|
| FİZİKSEL KONTROL | A–C | Kullanıcı ve DeviceMap yapısı |
| DOĞRULAMA KRİTERİ | D–H | Beklenen değerler |
| YAZILIM KONTROL | I–W | Betik, cihazdan okunan |

Her alanın sabit bir sütunu vardır. Bir cihaz türü o alanı kullanmıyorsa hücre
gri (N/A) boyanır ve betik oraya hiçbir zaman yazmaz.

## Doğrulama kriteri sütunları

| Sütun | Alan | Kaynak |
|---|---|---|
| E | IP Şablonu | DeviceMap `IP` (`10.n.1.x`) |
| F | Beklenen IP | Excel formülü — `n` yerine tren seti numarası |
| G | Beklenen Versiyon | Elle doldurulur (sarı) |
| H | Beklenen SIP Dahili No | DeviceMap `PBXExtension` |

`PBXExtension` bir **tanım** değeridir, cihazdan okunan değer değil. Bu yüzden
doğrulama kriteri tarafında durur; cihazın bildirdiği değer T sütununa yazılır
ve ikisi karşılaştırılıp renklenir.

## Ortak yazılım kontrol alanları

Bütün cihazlar ve switch'ler için geçerlidir. Kaynakta bulunmayan değer boş
bırakılır.

| Sütun | Alan | Tip | Kaynak |
|---|---|---|---|
| I | Cihaz İsmi | metin | DeviceMap `Name` |
| J | Bağlantı Bilgisi | metin | Çözülmüş IP — yalnızca cihaz doğrulandıysa |
| K | Versiyon | metin | Cihazın kendi bildirdiği sürüm |
| L | Cihaz Numarası | metin | Seri numarası / donanım kimliği |
| M | Durum Açıklaması | metin | `Aktif`, `Pasif` veya boş |
| N | Çalışma Süresi | metin | `saat:dakika:saniye` biçiminde (ör. `03:25:41`) |

### Durum dönüşümü

| Panel sonucu | Durum Açıklaması |
|---|---|
| Cihaz doğrulandı; sonuç yeşil | `Aktif` |
| Cihaza ulaşılamadı veya kimlik doğrulaması bekleniyor; sonuç kırmızı/turuncu | `Pasif` |
| Cihaz henüz okunmadı ya da denetim bu cihazda uygulanmıyor; sonuç gri/yok | Boş |

Bu dönüşüm yalnız ham `NoError` alanına bakmaz. MQTT kaynaklı cihazlarda
AppStatus `Status` değerinin `connected` olması ve canlı DeviceMap kaydındaki
`Status.NoError` değerinin `true` olması birlikte gerekir. Saklanan
(`retained`) bir AppStatus mesajının varlığı, cihazın hâlâ bağlı olduğunu tek
başına kanıtlamaz.

## Cihaz türüne özel alanlar

| Sütun | Alan | Tip | Geçerli türler |
|---|---|---|---|
| O | Hoparlör Ses Seviyesi | yüzde | Amplifier, Handset, Intercom |
| P | Mikrofon Ses Seviyesi | yüzde | Amplifier, Handset, Intercom |
| Q | Hoparlör Gain | sayı | Amplifier, Handset, Intercom |
| R | Mikrofon Gain | sayı | Amplifier, Handset, Intercom |
| S | SIP PBX IP | metin | Amplifier, Handset, Intercom, UIC, LCD/Compartment |
| T | SIP Dahili No | metin | Amplifier, Handset, Intercom, UIC, LCD/Compartment |
| U | SIP Arama No | metin | Handset, Intercom |
| V | Saat Dilimi | metin | LCD/Compartment |
| W | Ağ/Zaman Kontrolü | metin | Camera, NVR |

`Ağ/Zaman Kontrolü` alanı `Uygun`, `Bağlantı Yok` ya da başarısız kontrollerin
virgülle birleştirilmiş hâli (`Saat`, `NTP`, `Maske`) olur. Saat dilimi, NTP IP
adresi ve alt ağ maskesi ayrıca sütun olarak saklanmaz.

## Cihaz türü alan özeti

| DeviceMap `Type` / `SubType` | Kullanılacak alanlar |
|---|---|
| `PISCU` | Ortak — sürüm ve kimlik AppStatus'tan |
| `HMI` | Ortak — sürüm ve kimlik AppStatus'tan |
| `ICU` | Ortak — yalnızca DeviceMap |
| `AP` | Ortak — yalnızca DeviceMap |
| `LED / Front` | Ortak — yalnızca DeviceMap |
| `LCD / Landing` | Ortak — yalnızca DeviceMap |
| `Switch` | Ortak, **Cihaz Numarası hariç** |
| `LCD / Compartment` | Ortak + Saat Dilimi, SIP PBX IP, SIP Dahili No; sürüm `dumpsys package` ile okunur |
| `Announcement / UIC` | Ortak + SIP PBX IP, SIP Dahili No |
| `Announcement / Amplifier` | Ortak + ses/kazanç (`gain`), SIP PBX IP, SIP Dahili No |
| `Announcement / Handset` | Ortak + ses/kazanç (`gain`), SIP (üçü de) |
| `Announcement / Intercom` | Ortak + ses/kazanç (`gain`), SIP (üçü de) |
| `Camera / Corridor` | Ortak + Ağ/Zaman Kontrolü |
| `Camera / Landing` | Ortak + Ağ/Zaman Kontrolü |
| `NVR` | Ortak + Ağ/Zaman Kontrolü |

---

## Doğrulama notları

Bu bölüm, geliştirme sırasında sahadan alınan gerçek yanıtların ilk taslaktan
farklı çıktığı noktaları açıklar.

### 1. Arıza bayrakları ayrıştırılmıyor

İlk tasarımda `Has Network Failure` → `Pasif (Bağlantı)`, `Has Power Failure` →
`Pasif (PoE)` ayrımı vardı. Bu bayraklar tutarlı doldurulmuyor:

| Cihaz | NoError | NetFail | PwrFail |
|---|---|---|---|
| Compartment_Lcd_1 | true | **true** | false |
| Compartment_Lcd_2–6, 8–10 | false | true | false |
| Compartment_Lcd_7, 11 | false | **false** | false |

Aynı anda `NoError=true` ve `Has Network Failure=true` olan kayıt var;
kapalı cihazların bir kısmında da hiçbir neden bayrağı ayarlanmamış. Neden
gösterimi kaldırıldı, yalnızca `Aktif` / `Pasif` yazılıyor.

### 2. Çalışma süresi biçimi

`0 saat, 40 dakika, 28 saniye` yerine **`00:40:28`** kullanılır. Uzun biçim
sütuna sığmıyordu.

### 3. Anons cihazlarının gerçek alan adları

`GET /api/v1/system/settings` yanıtı (Intercom `10.n.1.10` örneği):

```json
{
  "version": "1.2.4",          "status": "Registered",
  "uptime": 6230,              "calltimeout": 30,
  "micvolume": 100,            "speakervolume": 100,
  "micgain": 1,                "speakergain": 1,
  "miclevel": 0,
  "ip": "10.1.1.10",           "netmask": "255.255.0.0",
  "gateway": "10.1.1.100",     "pbxip": "10.1.1.1",
  "pbxextension": "2003",      "pbxpassword": "2003",
  "pbxoutextension": "5001"
}
```

Önemli noktalar:

- GET yanıtındaki ham alan adı `pbxoutextension` biçimindedir. Yazma
  gövdesindeki karşılığı `pbxOutExtension`'dır; "outbound" değil **"out"**
  kullanılır.
- **Seri numarası alanı yok.** Bu cihazlarda `Cihaz Numarası` boş kalır.
- `speakergain` / `micgain` alanları mevcut; ses seviyesinden ayrı sütunlara
  yazılır.
- Handset ayrıca `answermode`, `hangupmode`, `callmode`, `pttenabled` alanlarını;
  Amplifier ise `loglevel`, `usedhcp`, `speakerlevel` alanlarını döndürüyor.
  Bunlar kontrol listesine alınmadı.
- Amplifier `micvolume` döndürüyor (değeri `0`), `pbxoutextension` ise boş —
  dışarı arama yapmadığı doğrulandı.

### 4. SIP dış arama numarası DeviceMap'te tanımlı

DeviceMap'teki dahili numara blokları:

| Blok | Cihaz | Aralık |
|---|---|---|
| 1xxx | Amplifier | 1001 |
| 2xxx | Intercom | 2001–2012 |
| 3xxx | Handset | 3001 |
| 4xxx | UIC | 4001 |
| 6xxx | LCD / Compartment | 6001–6011 |

**5xxx bloğu bir cihazın kendi dahili numarası olarak kullanılmaz.** Bununla
birlikte `5001`, artık DeviceMap'in tür düzeyindeki konfigürasyonunda açıkça
tanımlıdır:

```json
{
  "Announcement/Intercom": { "PBXOutExtension": "5001" },
  "Announcement/Handset":  { "PBXOutExtension": "4001" }
}
```

Intercom cihazlarının aradığı `5001`, PISCU üzerindeki Asterisk dialplan'ında
tanımlı çağrı grubudur. Handset'in dış arama hedefi `4001` ise UIC'nin gerçek
dahili numarasıdır.

U sütunundaki `SIP Arama No`, cihazdan okunan mevcut değerdir. Şablonda bunun
için ayrı bir **beklenen dış arama numarası** sütunu yoktur; beklenen değer
konfigürasyon ekranında DeviceMap `PBXOutExtension` alanından gelir.

### 5. PISCU ve HMI sürümleri MQTT'den geliyor

Bu iki cihazın sürüm ve donanım kimliği HTTP'den değil, saklanan (`retained`)
MQTT mesajlarından alınır. Aşağıdaki değerler tren seti 1 örneğidir;
AppStatus `DeviceIP` alanı şablon değil, çözülmüş gerçek IP taşır:

```
ALFA/AppStatus/ClientManager_PISCU_YATAKLI_1   ip=10.1.1.1  v=1.2.7  hwid=604A17F3
ALFA/AppStatus/ClientManager_MCP_YATAKLI_1     ip=10.1.1.4  v=1.2.5  hwid=34DA8534
```

`ClientManager_MCP_*` mesajı HMI üzerinde çalışan uygulamaya aittir; bu yüzden
**HMI için SSH erişimi gerekmez.**

Eşleştirme `DeviceIP` alanı üzerinden yapılır. `ClientId` içindeki isme göre
eşleştirmek yanlıştır — farklı tren setinin kaydını çeker.

Mesajın varlığı cihazın bağlı olduğunu tek başına göstermez. `Status` değeri
`connected` değilse veya aynı cihazın canlı DeviceMap kaydında
`Status.NoError` değeri `true` değilse cihaz doğrulanmış sayılmaz.

### 6. KYLAND switch alan adları

`GET /stat/basicInfo` yanıtı:

```
basicInfo.deviceType   Aquam8128-B-4GE24P-L2-L2
basicInfo.deviceName   SWITCH
basicInfo.serialNum    --
basicInfo.softVer      F6014
basicInfo.hardVer      V1.2
basicInfo.operateTime  { day, hour, minute, second }
```

- `serialNum` değeri doğrudan `--`; yani seri numarası okunamıyor.
  `Cihaz Numarası` sütunu switch bölümünde gri bırakıldı.
- Çalışma süresi tek bir `uptime` alanı olarak değil, `operateTime` altında
  parçalı geliyor. Devreye Alma Paneli bu dört parçayı saniyeye çevirip
  `Çalışma Süresi` sütununa yazar (`day*86400 + hour*3600 + minute*60 +
  second`); saha örneği `{0, 7, 30, 39}` → `07:30:39`. Cihaz cevap
  vermezse DeviceMap'teki `Status.Uptime` değerine düşülür.

### 7. PISCU ve HMI'ın çalışma süresi AppStatus'ta yok

`ALFA/AppStatus/#` yükü yalnız şu alanları taşır:

```json
{"ClientId": "ClientManager_MCP_YATAKLI_1", "DeviceIP": "10.1.1.4",
 "HWID": "34DA8534", "IsMaster": false, "MasterIP": "",
 "Status": "connected", "Version": "1.2.5"}
```

Sürüm ve donanım kimliği buradan, **çalışma süresi ise aynı cihazın
`ALFA/DeviceMap` kaydındaki `Status.Uptime` alanından** alınır. İki kaynak
birleştirilmezse bu iki cihazın `Çalışma Süresi` sütunu boş kalır.

Dikkat: `ALFA/DeviceMap` adresleri **şablondur** (`10.n.1.4`), AppStatus
ise gerçek IP verir (`10.1.1.4`). Kayıt ararken şablonun çözülmesi gerekir;
aksi halde DeviceMap kaynaklı hiçbir cihaz bulunamaz. Kapalı cihazlarda
`Uptime` `-1` gelir — bu bir süre değildir, yazılmaz.

### 8. Compartment LCD sürümü — kaynağı belirlendi

- ADB `ro.build.display.id` → `C33P-V1.5-11-WM-15...` — bu Android **derleme**
  kimliği, uygulama sürümü değil. Sürüm için kullanılmaz.
- DeviceMap `Status.Version` alanında `0.0.5` gözlemlenmiştir; panel yine de
  cihazdaki kurulu uygulamanın sürümünü doğrudan paket yöneticisinden okur.

Doğru kaynak paket yöneticisidir:

```bash
adb shell dumpsys package com.piton.train_lcd_panel \
  | grep -E "versionName|versionCode|minSdk|targetSdk|firstInstallTime|lastUpdateTime"
```

```
versionName=0.0.5        uygulama sürümü   -> Versiyon sütunu
versionCode=1            sürüm kodu
minSdk=21 targetSdk=35   Android API aralığı
firstInstallTime=...     ilk kurulum
lastUpdateTime=...       son güncelleme
```

Bu nedenle Compartment LCD satırlarındaki `Versiyon` hücreleri artık N/A
değildir. SIP dahili numarası ve PBX adresi de uygulamanın kendi günlüğünden
okunur:

```bash
adb logcat -d -s AnnounceSip:I '*:S'
```

```
SIP engine started: sip:6001@10.1.1.1:5060 (UDP)  -> SIP Dahili No, SIP PBX IP
Registration state=registered code=200            -> kayıt durumu (cihaz beyanı)
```

Seri numarası (`ro.serialno`) ve saat dilimi (`persist.sys.timezone`) ADB'den
okunmaya devam eder.

**Dikkat — `SIP engine started` satırı yalnız uygulama açılışında bir kez
yazılır.** Cihaz günlerdir çalışıyorsa o satır döngüsel tampondan düşmüş
olur; `Registration state` satırı yaklaşık 5 dakikada bir yinelendiği için
kayıt durumu gelir ancak dahili numara gelmez. Numarayı görmek için uygulamayı
yeniden başlatmak **gerekmez**: aynı bilgi MQTT aracısında saklanan bir mesajda
bulunur.

#### ALFA/SipPort — cihazı yeniden başlatmadan dahili numara okuma

```
ALFA/SipPort/10.1.1.40   {"SipPort": 6001}
ALFA/SipPort/10.1.1.41   {"SipPort": 6002}
...
ALFA/SipPort/10.1.1.50   {"SipPort": 6011}
```

Konu adı **çözülmüş** IP taşır (şablon değil). Panel önce cihazın günlüğüne
bakar, orada yoksa bu duyuruyu kullanır ve değerin kaynağını cihaz
detayında yazar ("cihaz günlüğü" / "ALFA/SipPort/<ip>").

`SIP PBX IP` değeri de aynı günlük satırından okunur. O satır düşmüşse ve cihaz
`Registration state=registered` diyorsa PBX adresi setin PISCU'sudur —
sette başka registrar yok — ve sütun oradan doldurulur. Kayıtlı olmayan
cihaza PBX **yazılmaz**; olmayan bir bağlantıyı varmış göstermek olurdu.
Her iki alanın kaynağı cihaz detayında yazılıdır:

| Alan | Kaynak sırası |
|---|---|
| SIP Dahili No | cihaz günlüğü → `ALFA/SipPort/<ip>` |
| SIP PBX IP | cihaz günlüğü → proje (PISCU), yalnız kayıtlıyken |

Aynı cihazlar için MQTT aracısında başka künye konuları da bulunur. Bunlar kontrol
listesinde kullanılmaz, ancak gerekirse erişilebilir:

```
ALFA/DeviceCheck/10.1.1.40  {"BundleId","IpAddress","MacAddress","VersionNo","Timestamp"}
ALFA/DeviceInfo/10.1.1.40   {"LinkType","SerialNumber","SubType","Type"}
ALFA/Volume/10.1.1.40       {"IsThereAnounce","Volume"}
```

Günlük tamponunun dönmesi tek başına hata sayılmaz — sürümün okunamaması
sayılır, o cihaz yeşil gösterilmez.

### 9. DeviceMap'in tren seti kontrol edilmeli

DeviceMap'teki switch kayıtlarında `TrainSet` alanı vardır. Durum bilgileri
(sürüm, çalışma süresi, aktiflik) yalnızca o an bağlı olan trene aittir. Farklı
bir tren seti için çalıştırıldığında bu alanlar kullanılmaz; yalnızca yapısal
bilgiler (cihaz adı, IP şablonu, tür, dahili numara) geçerlidir.

### 10. Servisler aynı port numarasını kullanıyor

`ARDUINO_HTTP_PORT`, `VIDEO_HTTP_PORT` ve `KYLAND_HTTP_PORT` üçü de **80**.
Cihaz türü port numarasından ayırt edilemez; ağ taramasında tür tespiti
uç denenerek yapılır.

### 11. Sahada tespit edilen uyumsuzluk

`10.1.1.10` adresindeki Intercom kendini `pbxextension = 2003` olarak
bildiriyor, DeviceMap ise o adres için `2001` tanımlıyor. Şablondaki
`Beklenen SIP Dahili No` / `SIP Dahili No` karşılaştırması bu farkı kırmızı
gösterir.
