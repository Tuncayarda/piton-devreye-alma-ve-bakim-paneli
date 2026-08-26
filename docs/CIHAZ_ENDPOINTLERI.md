# Yataklı Cihazlardan Veri Alma

DeviceMap'te 2 switch ve bu switch'lere bağlı 40 cihaz bulunur. IP adresleri
`10.n.1.x` şablonundadır; buradaki `n`, tren seti numarasıdır.

IP adresleri tek tek ortam değişkenlerinde tutulmaz. Aşağıdaki tanılama
komutları cihaz listesini `DeviceMap.json` dosyasındaki `Type` ve `SubType`
alanlarından çıkarır, ardından `n` değerini `TRAIN_SET_NO` ile değiştirir.
DeviceMap'e aynı türde yeni bir cihaz eklendiğinde komutlar o cihazı da
kendiliğinden kapsar.

İkinci oktet tren setini belirtir: `10.1.1.x` tren 1, `10.2.1.x` tren 2.
`DeviceMap.json` içindeki `TrainSet` alanı dosyanın hangi trene ait olduğunu
söyler; durum bilgileri (sürüm, çalışma süresi, aktiflik) yalnızca o tren için
geçerlidir.

`ARDUINO_HTTP_PORT`, `VIDEO_HTTP_PORT` ve `KYLAND_HTTP_PORT` değerlerinin
üçü de `80`'dir. Cihaz türü port numarasından ayırt edilemez; ayrım uç
yoluna göre yapılır.

## Komut ortamını hazırlama

Komutları depo kökünde, Bash kabuğunda çalıştırın. Temel HTTP örnekleri için
`curl` ve `jq`; MQTT örnekleri için ayrıca `mosquitto_sub`; Compartment LCD
örnekleri için `adb` gerekir. HMI'ın isteğe bağlı işletim sistemi sorgusu
`ssh` kullanır.

Depoda zorunlu bir `.env` dosyası yoktur. Aşağıdaki örnek, gizli olmayan
değerleri yalnız geçerli kabuk oturumu için tanımlar. Gerekirse varsayılanları
saha ortamınıza göre değiştirin:

```bash
cd /tam/yol/DevreyeAlmaPaneli

export DEVICE_MAP_FILE="${DEVICE_MAP_FILE:-$PWD/DeviceMap.json}"
export TRAIN_SET_NO="${TRAIN_SET_NO:-1}"

export ARDUINO_HTTP_PORT="${ARDUINO_HTTP_PORT:-80}"
export VIDEO_HTTP_PORT="${VIDEO_HTTP_PORT:-80}"
export KYLAND_HTTP_PORT="${KYLAND_HTTP_PORT:-80}"
export PISCU_MQTT_PORT="${PISCU_MQTT_PORT:-1883}"
export PISCU_DASHBOARD_PORT="${PISCU_DASHBOARD_PORT:-18083}"
export PISCU_DEVICE_MAP_TOPIC="${PISCU_DEVICE_MAP_TOPIC:-ALFA/DeviceMap}"
export COMPARTMENT_LCD_ADB_PORT="${COMPARTMENT_LCD_ADB_PORT:-5555}"
export COMPARTMENT_LCD_PAKET="${COMPARTMENT_LCD_PAKET:-com.piton.train_lcd_panel}"
export ASTERISK_ARI_PORT="${ASTERISK_ARI_PORT:-8088}"

if [ ! -r "$DEVICE_MAP_FILE" ]; then
  printf 'DeviceMap okunamadı: %s\n' "$DEVICE_MAP_FILE" >&2
elif [[ ! "$TRAIN_SET_NO" =~ ^[0-9]+$ ]] \
    || [ "$TRAIN_SET_NO" -lt 1 ] || [ "$TRAIN_SET_NO" -gt 254 ]; then
  printf 'TRAIN_SET_NO 1 ile 254 arasında bir sayı olmalıdır.\n' >&2
else
  device_ips() {
    device_type="$1"
    device_subtype="${2:-}"

    jq -r \
      --arg train "$TRAIN_SET_NO" \
      --arg device_type "$device_type" \
      --arg device_subtype "$device_subtype" \
      '
        .Switches[].Devices[]
        | select(.Type == $device_type)
        | select(
            $device_subtype == ""
            or .SubType == $device_subtype
          )
        | .IP
        | gsub("n"; $train)
      ' "$DEVICE_MAP_FILE"
  }

  switch_ips() {
    jq -r \
      --arg train "$TRAIN_SET_NO" \
      '.Switches[].IP | gsub("n"; $train)' \
      "$DEVICE_MAP_FILE"
  }

  PISCU_IP="$(device_ips PISCU | head -n 1)"
  export PISCU_IP
fi
```

Hazırlık başarılıysa `device_ips`, `switch_ips` ve `PISCU_IP` kullanılabilir.
Bir hata yazıldıysa depo köküne geçtiğinizi, DeviceMap yolunu ve tren seti
numarasını düzeltmeden sonraki komutlara geçmeyin.

Kimlik bilgilerini depodaki bir dosyaya veya kabuk geçmişine yazmayın.
Yalnız sorgulayacağınız servisler için bilgileri gizli istemle, geçerli kabuk
oturumuna alın:

```bash
kimlik_oku() {
  kullanici_degiskeni="$1"
  parola_degiskeni="$2"
  servis="$3"

  read -r -p "${servis} kullanıcı adı: " kullanici
  read -r -s -p "${servis} parolası: " parola
  printf '\n'
  printf -v "$kullanici_degiskeni" '%s' "$kullanici"
  printf -v "$parola_degiskeni" '%s' "$parola"
  export "$kullanici_degiskeni" "$parola_degiskeni"
  unset kullanici parola
}

# Aşağıdaki satırlardan yalnız ihtiyacınız olanları çalıştırın.
# kimlik_oku KYLAND_USERNAME KYLAND_PASSWORD 'KYLAND'
# kimlik_oku VIDEO_USERNAME VIDEO_PASSWORD 'Kamera/NVR'
# kimlik_oku PISCU_USERNAME PISCU_PASSWORD 'EMQX Dashboard'
# kimlik_oku ASTERISK_ARI_USERNAME ASTERISK_ARI_PASSWORD 'Asterisk ARI'
```

Bu değişkenler yalnız açık kabukta kalır. İşiniz bitince kabuğu kapatabilir
veya parola değişkenleriyle yardımcı işlevi temizleyebilirsiniz:

```bash
unset KYLAND_PASSWORD VIDEO_PASSWORD PISCU_PASSWORD ASTERISK_ARI_PASSWORD
unset -f kimlik_oku
```

## Anons cihazlarının ortak alan adları

Amplifier, Handset ve Intercom aynı `/api/v1/system/settings` ucundan okunur.
UIC de bu uçtan okunur, ancak döndürdüğü alan kümesi cihaz türüne göre
farklıdır. Aşağıdaki örnek, Intercom cihazından doğrulanmış ham yanıttır:

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

Dikkat edilecek noktalar:

- GET yanıtındaki dış arama alanı `pbxoutextension` biçimindedir. Yazma
  gövdesindeki karşılığı **`pbxOutExtension`**'dır; alan adı "outbound"
  sözcüğünü kullanmaz.
- **Seri numarası alanı yoktur.** Bu cihazlarda `Cihaz Numarası` boş kalır.
- `speakergain` / `micgain`, `speakervolume` / `micvolume` alanlarından
  ayrıdır; kontrol listesinde ayrı sütunlarda tutulur.
- `pbxpassword` gizli bilgidir; tanılama çıktısından çıkarılmalı ve kontrol
  listesine hiçbir zaman yazılmamalıdır.

## Anons cihazlarına ayar yazma

`GET /api/v1/system/settings` bütün ayarları okur ama **yazmak için
kullanılamaz**: POST isteğine `405 Method Not Allowed` döner. Cihazın kendi
web arayüzü ayarları türüne göre ayrı uçlara gönderiyor. Aşağıdakiler
sahadaki cihazların (Amplifier 10.1.1.5, Handset 10.1.1.6, Intercom
10.1.1.10, UIC 10.1.1.60) arayüzünden ve doğrudan istekle doğrulanmıştır.
Devreye Alma Paneli'ndeki `core/konfig.py` → `ROTA` tablosu bunun birebir
karşılığıdır.

| Uç | Gövde | Kısmi gövde | Yeniden başlatır |
|---|---|---|---|
| `POST /api/v1/audio/volume` | `micVolume`, `speakerVolume`, `speakerGain`, `micGain`, `logLevel` | evet | hayır |
| `POST /api/v1/system/modes` | `pttEnabled`, `answerMode`, `callMode`, `hangupMode` (+ `speakerGain`, `micGain`, `logLevel`) | hayır — dört mod alanı zorunlu | hayır |
| `POST /api/v1/uic/gains` | `tcSpeakerGain`, `tcMicGain`, `tlSpeakerGain`, `tlMicGain` | hayır — dördü zorunlu | hayır |
| `POST /api/v1/sip/settings` | `pbxIp`, `pbxExtension`, `pbxPassword` (+ tipe göre `pbxOutExtension`, `callTimeout`, `target1..4`, `tcHigh/tcLow/tlHigh/tlLow`) | evet, ama üç zorunlu alan her istekte bulunmalı | **evet** |
| `POST /api/v1/network/ip` | `useDhcp`, `ip`, `netmask`, `gateway`, `ntpIp` | — | evet |

Cihaz tipine göre hangi alan hangi uca gider:

| Alan | Amplifier | Handset | Intercom | UIC |
|---|---|---|---|---|
| `speakerVolume` | audio | audio | audio | audio |
| `micVolume` | — | audio | audio | audio |
| `speakerGain` / `micGain` | audio (yalnız speaker) | **modes** | audio | — |
| `logLevel` | audio | **modes** | audio | audio |
| mod alanları | — | modes | — | — |
| `tc*/tl*Gain` | — | — | — | uic/gains |
| `pbxOutExtension` | — | sip | sip | — |
| `callTimeout` | — | sip | — | sip |
| `target1..4`, eşikler | — | — | — | sip |

Dikkat edilecek noktalar:

- Zorunlu alan eksikse cihaz `400` ile `Missing required fields` /
  `Missing mode fields` döndürüyor; `uic/gains` ucu ise bağlantıyı
  düşürüyor. Değiştirilmeyen zorunlu alanlar okunan değerle doldurulmalı.
- Gönderilmeyen alanlar korunuyor: yalnız `pbxExtension` yazıldığında
  `pbxOutExtension` ve `callTimeout` yerinde kalıyor.
- **`sip/settings` cihazı yeniden başlatıyor** (`SIP configuration saved.
  Rebooting...`). Ses/gain ayarı için bu uca dokunmayın; ayar zaten
  doğruysa istek atmayın.
- `sip/settings` parolayı zorunlu tutar; dolayısıyla parola olmadan dahili
  numara da yazılamaz. Panelin güncel kaynak sırası şöyledir: kullanıcının
  ekranda girdiği değer → cihaz kaydındaki `PBXPassword` → SIP dahili
  numarasının kendisi. Son adım sahadaki kurala dayanır: anons cihazlarında
  SIP parolası dahili numarayla aynıdır. Kullanıcı dahili numarayı değiştirirse
  bu geri dönüş değeri de yeni numara olur.
- Yanıtlar JSON değil, düz metindir (`Volume updated`, `UIC gains saved`).
- Ondalık alanlar cihazda `float32` olarak saklanır: `2.4` yazıldıktan sonra
  `2.4000000953674316` okunuyor. Karşılaştırma tam eşitlikle yapılmamalı.
- Kazanç (`gain`) seçenekleri: `1, 2, 4, 6, 8, 12, 16, 24, 32, 48, 64`.
  `logLevel`: `0` = yalnızca Error, `1` = Info + Error.
  `callTimeout` (arayüzde "Ring Time"): `0, 5, 10, 15, 20, 30, 45, 60, 90, 120`.
  `answerMode`: `0` butonla / `1` otomatik. `callMode`: `0` tek basış /
  `1` uzun basış (3 sn). `hangupMode`: `0` tek / `1` çift basış / `2` DTMF.
  Eşikler `0–5` V, `0,1` adım.
- UIC yönlendirmesi: `target1` = TC (3+ 4-) → giden, `target2` = TL (3- 4+)
  → giden, `target3` = gelen → TC, `target4` = gelen → TL.

## Kamera ve NVR'a ayar yazma

Kamera ve NVR ayarları tek bir uca gövde göndererek yazılmaz; sırası önemli
olan bir ISAPI çağrı dizisidir. Aşağıdakiler sahada kullanılan CCTV
script'lerinden alınmıştır ve Devreye Alma Paneli'nde `panel/video_config/`
paketinin birebir karşılığıdır. İstekler digest kimlik doğrulaması ister,
gövde XML'dir, yanıt `ResponseStatus` taşır — `200` tek başına başarı
anlamına gelmez.

| Uç | Yön | Ne yapar | Yeniden başlatır |
|---|---|---|---|
| `PUT System/time` | kamera · NVR | `timeMode=NTP` + saat dilimi | hayır |
| `PUT System/time/ntpServers/1` | kamera · NVR | NTP sunucusu (setin PISCU'su) | hayır |
| `GET System/Network/interfaces` | kamera · NVR | **yalnız okuma** — adres ve maske SADP ile veriliyor | — |
| `GET/PUT System/Hardware` | kamera | `IrLightSwitch/mode` (proje ayarı: `close`) | **evet** |
| `GET/PUT System/Software/channels/1` | kamera | `ThirdStream` aç/kapa | **evet** |
| `PUT Streaming/channels/101 · 102 · 103` | kamera | üç akış profili | hayır |
| `GET ContentMgmt/Storage/hdd` + `PUT .../{id}/format` | kamera · NVR | yalnız `unformatted` / `uninitialized` / `error` diskleri biçimlendirir | hayır |
| `GET/POST ContentMgmt/InputProxy/channels`, `PUT .../{id}` | NVR | kameraları kanal olarak ekler | hayır |
| `GET Event/triggers`, `GET/PUT Event/triggers/{id}` | NVR | sesli uyarıyı (beep) kapatır | hayır |
| `PUT System/reboot` | kamera · NVR | yeniden başlatma | **evet** |

Dikkat edilecek noktalar:

- **Ağ ayarı ISAPI üzerinden YAZILMAZ.** `PUT .../interfaces/{id}/ipAddress`
  isteği `[OK]` dönüyor, ardından cihaz kendi adresinde kayboluyor: geri
  getirmek için kabinde elektrik kesip SADP ile IP'yi yeniden vermek
  gerekiyor. Sahada `nvr.py`'nin `set_network_mask` adımıyla görüldü; panel
  bu adımı hiç almadı. Maske ve adres SADP'nin işi, panel ikisini de okuyup
  raporluyor.
- Eski NVR firmware'inin kendi kanal yönetimi sayfası ve sahadaki `nvr.py`,
  `ContentMgmt/InputProxy/channels` yazımlarını XML gövdeyle fakat
  `Content-Type: application/x-www-form-urlencoded` başlığıyla gönderiyor.
  Panel yalnız bu kanal uçlarında aynı başlığı kullanır; kamera ve NVR'ın diğer
  ISAPI yazımları `application/xml` olarak kalır. Başlığı bütün ISAPI istekleri
  için ortaklaştırmak eski NVR'ın kanal güncellemesini HTTP 400 ile reddetmesine
  yol açıyor. Aynı eski arayüz yeni kanalın POST gövdesine `<name>` eklerken
  mevcut kanalın PUT gövdesinde bu alanı göndermiyor; panel de aynı iki ayrı
  gövde biçimini kullanır.
- **103 numaralı kanal, 3. akış kapalıyken yoktur.** Sıra bu yüzden şudur:
  `System/Software/channels/1` ile aç → `System/reboot` → cihaz geri gelene
  kadar bekle → `Streaming/channels/103` yaz. Panel 15 saniye bekler, sonra
  5 saniye aralıkla 30 deneme yapar.
- IR modu ve 3. akış dışındaki hiçbir ayar kamerayı yeniden başlatmaz.
  Cihazda zaten doğru olan değer için istek atılmaz; bir ayar uğruna kamera
  karartılmaz.
- 102 ve 103 profilleri 101'den türetilir (`320x240` / proje çözünürlüğü,
  farklı multicast portları). Üçü tek parça yazılır.
- Sağlam disk **biçimlendirilmez**. Bir ayar uygulanırken kayıt silinmesi
  kabul edilebilir bir yan etki değildir.
- NVR kanal listesi projeye özel bir tablodan değil, DeviceMap'ten türer:
  kameranın `CameraID` alanı kanal numarası, `CameraName` alanı kanal adıdır.
- Mevcut Yataklı profili tam olarak 1–4 kanallarını taşır. Bu dört kanal
  yazılıp cihazdan kanal numarası ve kamera adresiyle geri doğrulanmadan eski
  kanallar silinmez; eksik/yarım DeviceMap bütün NVR kanal listesini
  temizleyemez. Kanal listesi hiç okunamazsa panel güvenlik için yazmaya da
  başlamaz. Ad yeni kanal eklenirken DeviceMap'ten gönderilir; eski firmware
  mevcut kanal PUT'unda adı kabul etmediği için güncelleme doğrulaması adresle
  yapılır.
- Kanal gövdesi **kameranın** kullanıcı adı ve parolasını taşır: NVR akışı
  çekmek için kameraya kendisi bağlanır. Panel parolayı diske yazmadığından
  bu değer o oturumda girilen kimlik bilgisinden gelir.
- Sesli uyarının `enabled` bayrağı yoktur; tetikçinin `beep` bildirim bloğu
  gövdeden silinip geri yazılır.
- NVR kanalları ancak yeniden başlatmadan sonra alır; panel bu yüzden bir
  şey yazdıysa sonda `System/reboot` gönderir. Hiçbir şey değişmediyse
  göndermez.
- **Hareket algılama (motion detection) bu projede yoktur.** VMD tetikçisi,
  7/24 takvimi ve grid haritası yalnız Gaziray'da kullanılır ve panele
  bilerek alınmamıştır.

## Amplifier

### Komut

```bash
for ip in $(device_ips Announcement Amplifier); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/settings" \
  | jq --arg ip "$ip" \
      '{ip: $ip, data: del(.pbxpassword, .pbxPassword)}'
done
```

```bash
for ip in $(device_ips Announcement Amplifier); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/logs"
done
```

### Komutun yaptığı

DeviceMap'teki bütün Amplifier adreslerini gezer. Her erişilebilir Amplifier
cihazından çalışma süresi, ses, ağ ve SIP bilgilerini alır. PBX parolasını,
cihaz yazılımının kullandığı iki olası harf biçiminde de tanılama çıktısından
çıkarır. İkinci komut cihaz günlüklerini alır.

Mevcut DeviceMap'te Amplifier adresi `10.n.1.5` olarak tanımlıdır. Yeni
Amplifier kayıtları DeviceMap'e eklendiğinde komut onları da otomatik sorgular.

> **Not:** Amplifier'ın `pbxoutextension` değeri boştur — dışarı arama
> yapmadığı doğrulanmıştır. Kontrol listesinde `SIP Arama No` sütunu bu
> bölümde gri bırakılmıştır. `micvolume` alanını döndürür (gözlemlenen
> değer `0`).

### Alınabilecek bilgiler

- Yazılım sürümü
- SIP kayıt durumu
- Çalışma süresi
- Hoparlör seviyesi ve kazanç (`gain`) değeri
- Günlük seviyesi
- DHCP durumu
- IP adresi, alt ağ maskesi ve ağ geçidi
- PBX IP ve PBX dahili numarası
- NTP IP
- Sistem başlatma, Ethernet ve SIP kayıt günlükleri

## Handset

### Komut

```bash
for ip in $(device_ips Announcement Handset); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/settings" \
  | jq --arg ip "$ip" \
      '{ip: $ip, data: del(.pbxpassword, .pbxPassword)}'

  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/modes" \
  | jq --arg ip "$ip" '{ip: $ip, modes: .}'
done
```

```bash
for ip in $(device_ips Announcement Handset); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/logs"
done
```

### Komutun yaptığı

DeviceMap'teki bütün Handset adreslerini gezer. Handset çalışma süresi, ses,
ağ, SIP ve çalışma modu bilgilerini alır. PBX parolasını tanılama çıktısından
çıkarır. İkinci komut cihaz günlüklerini alır.

Mevcut DeviceMap'te Handset adresi `10.n.1.6` olarak tanımlıdır.

### Alınabilecek bilgiler

- Yazılım sürümü
- SIP kayıt durumu
- Çalışma süresi
- Mikrofon ve hoparlör seviyeleri
- Mikrofon ve hoparlör kazanç (`gain`) değerleri
- Anlık mikrofon seviyesi
- IP adresi, alt ağ maskesi ve ağ geçidi
- PBX IP, PBX dahili ve dış arama numarası
- Cevaplama, kapatma ve arama modları
- PTT durumu
- Günlük seviyesi
- Sistem ve SIP kayıt günlükleri

## Intercomlar

### Komut

```bash
for ip in $(device_ips Announcement Intercom); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/settings" \
  | jq --arg ip "$ip" \
      '{ip: $ip, data: del(.pbxpassword, .pbxPassword)}'
done
```

```bash
for ip in $(device_ips Announcement Intercom); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/logs"
done
```

### Komutun yaptığı

DeviceMap'teki 12 Intercom için `10.n.1.10` ile `10.n.1.21` arasındaki bütün
adresleri gezer. Erişilebilir olan her Intercom cihazından çalışma süresi,
ses, ağ ve SIP bilgilerini alır. PBX parolasını tanılama çıktısından çıkarır.
İkinci komut cihaz günlüklerini alır.

### Alınabilecek bilgiler

- Yazılım sürümü
- SIP kayıt durumu
- Çalışma süresi
- Mikrofon ve hoparlör seviyeleri
- Mikrofon ve hoparlör kazanç (`gain`) değerleri
- Anlık mikrofon seviyesi
- IP adresi, alt ağ maskesi ve ağ geçidi
- PBX IP, PBX dahili ve dış arama numarası
- Arama zaman aşımı
- Sistem ve SIP kayıt günlükleri

## PISCU ve EMQX Dashboard

### Komut

```bash
for ip in $(device_ips PISCU); do
  token=$(
    jq -n \
      '{username: env.PISCU_USERNAME, password: env.PISCU_PASSWORD}' \
    | curl --connect-timeout 2 --max-time 10 -sS \
        -H 'Content-Type: application/json' \
        -X POST \
        "http://${ip}:${PISCU_DASHBOARD_PORT}/api/v5/login" \
        --data-binary @- \
    | jq -r '.token'
  )

  for endpoint in nodes listeners metrics stats; do
    curl --connect-timeout 2 --max-time 10 -sS \
      -H "Authorization: Bearer ${token}" \
      "http://${ip}:${PISCU_DASHBOARD_PORT}/api/v5/${endpoint}" \
    | jq --arg ip "$ip" --arg endpoint "$endpoint" \
        '{piscu: $ip, endpoint: $endpoint, data: .}'
  done

  curl --connect-timeout 2 --max-time 10 -sS \
    -H "Authorization: Bearer ${token}" \
    "http://${ip}:${PISCU_DASHBOARD_PORT}/api/v5/clients?limit=100" \
  | jq --arg ip "$ip" '{piscu: $ip, clients: .}'

  curl --connect-timeout 2 --max-time 10 -sS \
    -H "Authorization: Bearer ${token}" \
    "http://${ip}:${PISCU_DASHBOARD_PORT}/api/v5/topics?limit=100" \
  | jq --arg ip "$ip" '{piscu: $ip, topics: .}'

  curl --connect-timeout 2 --max-time 10 -sS \
    -H "Authorization: Bearer ${token}" \
    "http://${ip}:${PISCU_DASHBOARD_PORT}/api/v5/subscriptions?limit=100" \
  | jq --arg ip "$ip" '{piscu: $ip, subscriptions: .}'

  unset token
done
```

```bash
for ip in $(device_ips PISCU); do
  mosquitto_sub \
    -h "$ip" \
    -p "$PISCU_MQTT_PORT" \
    -t "$PISCU_DEVICE_MAP_TOPIC" \
    -C 1 \
    -W 5 \
  | jq
done
```

### Komutun yaptığı

DeviceMap'teki bütün PISCU adreslerini gezer. Her PISCU üzerindeki EMQX
Dashboard API'sine giriş yapar ve geçici erişim belirteciyle broker durum
bilgilerini okur. Belirteci tutan kabuk değişkeni her PISCU sorgusunun
sonunda temizlenir.

İkinci komut MQTT aracısındaki saklanan (`retained`) `ALFA/DeviceMap`
mesajını alır.
Mevcut DeviceMap'te PISCU adresi `10.n.1.1` olarak tanımlıdır.

> **Not:** Bu bölüm broker bilgisi verir. PISCU'nun **kendi yazılım sürümü ve
> donanım kimliği** buradan alınmaz — `ALFA/AppStatus/ClientManager_PISCU_*`
> mesajından gelir (bkz. "Uygulama Durumu" bölümü). EMQX sürümü (`5.x`) ile
> PISCU uygulama sürümü (`1.2.x`) farklı şeylerdir.

### Alınabilecek bilgiler

- EMQX sürümü ve sürüm türü (`edition`)
- Broker düğüm adı, çalışma durumu ve çalışma süresi
- Bağlı MQTT istemcisi sayısı
- İstemci kimliği, bağlantı IP'si ve bağlantı zamanı
- İstemci başına abonelik ve mesaj sayaçları
- Etkin MQTT konu listesi
- İstemci-konu abonelik eşleşmeleri ve QoS değerleri
- MQTT TCP ve WebSocket dinleyici durumları
- Broker metrikleri ve istatistikleri
- DeviceMap içindeki 2 switch ve 40 cihazın bilgileri

## KYLAND switch'leri

### Komut

```bash
for ip in $(switch_ips); do
  for endpoint in \
    basicInfo \
    portList \
    poeStatus \
    macQuery \
    portStream \
    lldpNeighbor \
    portState \
    statisticsStatus \
    arpSearch \
    logQuery
  do
    curl --connect-timeout 2 --max-time 10 -sS \
      -u "${KYLAND_USERNAME}:${KYLAND_PASSWORD}" \
      "http://${ip}:${KYLAND_HTTP_PORT}/stat/${endpoint}" \
    | jq --arg ip "$ip" --arg endpoint "$endpoint" \
        '{switch: $ip, endpoint: $endpoint, data: .}'
  done
done
```

### Komutun yaptığı

DeviceMap'teki `10.n.1.100` ve `10.n.1.101` adresli iki KYLAND switch'i gezer.
Her switch'in HTTP Basic Authentication korumalı durum uçlarından cihaz, port,
PoE, MAC, trafik, LLDP, STP, ARP ve günlük bilgilerini okur.

`basicInfo` yanıtındaki alan adları:

```
basicInfo.deviceType   Aquam8128-B-4GE24P-L2-L2
basicInfo.deviceName   SWITCH
basicInfo.serialNum    --
basicInfo.softVer      F6014
basicInfo.hardVer      V1.2
basicInfo.logicVer     V1.0.1
basicInfo.operateTime  { day, hour, minute, second }
```

> **Not:** `serialNum` değeri doğrudan `--` döner; yani seri numarası
> okunamıyor — kontrol listesinde switch'in `Cihaz Numarası` sütunu gri
> bırakılmıştır. Ayrıca çalışma süresi tek bir `uptime` alanında değil,
> `operateTime` altında parçalı gelir.

### Alınabilecek bilgiler

- Switch modeli ve cihaz adı
- MAC adresi (seri numarası dönmüyor)
- Donanım, mantık (`logic`) ve yazılım sürümleri
- Derleme tarihi
- CPU ve RAM kullanımı
- Sistem zamanı ve çalışma süresi
- FE/GE port listesi
- Port bazında PoE durumu, güç ve akım
- MAC adresinin bağlı olduğu switch portu
- Port bazında RX/TX byte ve paket sayaçları
- Unicast, multicast, broadcast, drop, pause ve CRC sayaçları
- LLDP komşuları ve yönetim adresleri
- Port STP rolü ve durumu
- ARP tablosu
- Switch sistem ve erişim günlükleri

## Kameralar

### Komut

```bash
for ip in $(device_ips Camera); do
  for endpoint in \
    System/deviceInfo \
    System/time \
    System/time/ntpServers/1 \
    System/Network/interfaces
  do
    curl --connect-timeout 2 --max-time 8 -sS \
      --digest \
      -u "${VIDEO_USERNAME}:${VIDEO_PASSWORD}" \
      "http://${ip}:${VIDEO_HTTP_PORT}/ISAPI/${endpoint}"
  done
done
```

### Komutun yaptığı

DeviceMap'teki dört kamerayı gezer:

- Corridor kameralar: `10.n.1.24` ve `10.n.1.25`
- Landing kameralar: `10.n.1.26` ve `10.n.1.27`

Her erişilebilir kameranın ISAPI servisinden cihaz, zaman, NTP ve ağ
bilgilerini XML olarak alır.

### Alınabilecek bilgiler

- Kamera modeli
- Seri numarası
- Donanım yazılımı ve cihaz sürümü
- Cihaz adı
- Saat dilimi ve yerel saat
- NTP sunucusu
- IP adresi
- Alt ağ maskesi
- Ağ geçidi ve ağ arayüzleri

## NVR

### Komut

```bash
for ip in $(device_ips NVR); do
  for endpoint in \
    System/deviceInfo \
    System/time \
    System/time/ntpServers/1 \
    System/Network/interfaces
  do
    curl --connect-timeout 2 --max-time 8 -sS \
      --digest \
      -u "${VIDEO_USERNAME}:${VIDEO_PASSWORD}" \
      "http://${ip}:${VIDEO_HTTP_PORT}/ISAPI/${endpoint}"
  done
done
```

### Komutun yaptığı

DeviceMap'teki bütün NVR adreslerini gezer. Her erişilebilir NVR'ın ISAPI
servisinden cihaz, zaman, NTP ve ağ bilgilerini XML olarak alır.

Mevcut DeviceMap'te NVR adresi `10.n.1.3` olarak tanımlıdır.

### Alınabilecek bilgiler

- NVR modeli
- Seri numarası
- Donanım yazılımı ve cihaz sürümü
- Saat dilimi ve yerel saat
- NTP sunucusu
- IP adresi, alt ağ maskesi ve ağ geçidi
- Ağ arayüzleri

## Compartment LCD'ler

### Komut

```bash
for ip in $(device_ips LCD Compartment); do
  adb connect "${ip}:${COMPARTMENT_LCD_ADB_PORT}"
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell getprop ro.product.manufacturer
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell getprop ro.product.model
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell getprop ro.product.board
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell getprop ro.board.platform
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell getprop ro.serialno
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell getprop ro.build.version.release
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell getprop ro.build.display.id
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell getprop persist.sys.timezone
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell cat /proc/uptime
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell wm size
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" shell dumpsys package "$COMPARTMENT_LCD_PAKET"
  adb -s "${ip}:${COMPARTMENT_LCD_ADB_PORT}" logcat -d -s AnnounceSip:I '*:S'
done
```

### Komutun yaptığı

DeviceMap içinde `Type: LCD` ve `SubType: Compartment` olan bütün cihazları
bulur. Mevcut DeviceMap'te `10.n.1.40` ile `10.n.1.50` arasında 11
Compartment LCD bulunmaktadır.

Her Compartment LCD'nin TCP `5555` ADB servisine bağlanarak Android cihaz
bilgilerini okur. `10.1.1.40:5555` bağlantısı doğrulanmış ve cihaz
`rk3568_r` kabuk ortamını açmıştır.

> **Not — uygulama sürümü:** `ro.build.display.id` değeri
> `C33P-V1.5-11-WM-15...` şeklindedir; bu Android **derleme kimliğidir**,
> uygulama sürümü değil. Uygulama sürümü paket yöneticisinden okunur:
> `dumpsys package com.piton.train_lcd_panel` → `versionName=0.0.5`.
> Bu nedenle Compartment LCD satırlarındaki `Versiyon` hücreleri N/A değildir.
> SIP dahili numarası ve PBX adresi `logcat -d -s AnnounceSip:I` çıktısındaki
> `SIP engine started: sip:6001@10.1.1.1:5060 (UDP)` satırından,
> kayıt durumu ise `Registration state=registered code=200` satırından gelir.
> `ro.serialno` (seri no) ve `persist.sys.timezone` (saat dilimi) okunmaya
> devam etmektedir.

### Alınabilecek bilgiler

- Cihaz üreticisi
- Cihaz modeli
- Kart ve işlemci platformu
- Android seri numarası
- Android sürümü
- Android derleme bilgisi
- Saat dilimi
- Sistem çalışma süresi
- Ekran çözünürlüğü
- Panel uygulamasının sürümü, sürüm kodu, min/hedef SDK'sı, kurulum ve
  son güncelleme tarihi
- SIP dahili numarası, PBX adresi/portu ve kayıt durumu

## Landing LCD'ler

### Komut

```bash
mosquitto_sub \
  -h "$PISCU_IP" \
  -p "$PISCU_MQTT_PORT" \
  -t "$PISCU_DEVICE_MAP_TOPIC" \
  -C 1 \
  -W 5 \
| jq --arg train "$TRAIN_SET_NO" '
    [
      .Switches[].Devices[]
      | select(.Type == "LCD" and .SubType == "Landing")
      | {
          name: .Name,
          ip: (.IP | gsub("n"; $train)),
          status: .Status
        }
    ]
  '
```

### Komutun yaptığı

DeviceMap mesajını okuyup yalnızca Landing LCD cihazlarını seçer. Mevcut
DeviceMap'te `10.n.1.51` ve `10.n.1.52` adresli iki Landing LCD bulunmaktadır.
Bu cihazlarda ADB veya başka bir cihaz içi uç henüz doğrulanmamıştır.

### Alınabilecek bilgiler

- Cihaz adı ve tren setine göre çözülmüş beklenen IP
- Aktiflik durumu
- Ağ ve güç hata bayrakları
- Çalışma süresi
- DeviceMap'te bulunuyorsa yazılım sürümü ve seri numarası

## LED'ler

### Komut

```bash
mosquitto_sub \
  -h "$PISCU_IP" \
  -p "$PISCU_MQTT_PORT" \
  -t "$PISCU_DEVICE_MAP_TOPIC" \
  -C 1 \
  -W 5 \
| jq --arg train "$TRAIN_SET_NO" '
    [
      .Switches[].Devices[]
      | select(.Type == "LED")
      | {
          name: .Name,
          ip: (.IP | gsub("n"; $train)),
          subtype: .SubType,
          width: .Width,
          height: .Height,
          status: .Status
        }
    ]
  '
```

### Komutun yaptığı

DeviceMap mesajını okuyup yalnızca LED cihazlarını seçer. Mevcut DeviceMap'te
`10.n.1.30` ve `10.n.1.31` adresli iki Front LED bulunmaktadır.

### Alınabilecek bilgiler

- Cihaz adı ve tren setine göre çözülmüş beklenen IP
- Cihaz tipi ve alt tipi
- Ekran genişliği ve yüksekliği
- Aktiflik durumu
- Ağ, güç, süreç ve sistem hata bayrakları
- Çalışma süresi
- Yazılım sürümü

## Access Point'ler

### Komut

```bash
mosquitto_sub \
  -h "$PISCU_IP" \
  -p "$PISCU_MQTT_PORT" \
  -t "$PISCU_DEVICE_MAP_TOPIC" \
  -C 1 \
  -W 5 \
| jq --arg train "$TRAIN_SET_NO" '
    [
      .Switches[].Devices[]
      | select(.Type == "AP")
      | {
          name: .Name,
          ip: (.IP | gsub("n"; $train)),
          status: .Status
        }
    ]
  '
```

### Komutun yaptığı

DeviceMap mesajını okuyup yalnızca Access Point cihazlarını seçer. Mevcut
DeviceMap'te `10.n.1.7` ve `10.n.1.8` adresli iki AP bulunmaktadır.

### Alınabilecek bilgiler

- AP cihaz adı
- Beklenen ve tren setine göre çözülmüş IP
- Aktiflik durumu
- Ağ ve güç hata bayrakları
- Çalışma süresi
- DeviceMap'te bulunuyorsa sürüm ve seri numarası

## ICU

### Komut

```bash
mosquitto_sub \
  -h "$PISCU_IP" \
  -p "$PISCU_MQTT_PORT" \
  -t "$PISCU_DEVICE_MAP_TOPIC" \
  -C 1 \
  -W 5 \
| jq --arg train "$TRAIN_SET_NO" '
    [
      .Switches[].Devices[]
      | select(.Type == "ICU")
      | {
          name: .Name,
          ip: (.IP | gsub("n"; $train)),
          status: .Status
        }
    ]
  '
```

### Komutun yaptığı

DeviceMap mesajını okuyup ICU kaydını seçer. Mevcut DeviceMap'te ICU adresi
`10.n.1.2` olarak tanımlıdır.

### Alınabilecek bilgiler

- ICU cihaz adı
- Beklenen ve tren setine göre çözülmüş IP
- Aktiflik durumu
- Ağ ve güç hata bayrakları
- Çalışma süresi
- DeviceMap'te bulunuyorsa sürüm ve seri numarası

## UIC

### Komut

UIC'nin cihazdan bildirdiği ayarları okumak için:

```bash
for ip in $(device_ips Announcement UIC); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/settings" \
  | jq --arg ip "$ip" \
      '{ip: $ip, data: del(.pbxpassword, .pbxPassword)}'
done
```

PISCU'nun canlı DeviceMap kaydını görmek için:

```bash
mosquitto_sub \
  -h "$PISCU_IP" \
  -p "$PISCU_MQTT_PORT" \
  -t "$PISCU_DEVICE_MAP_TOPIC" \
  -C 1 \
  -W 5 \
| jq --arg train "$TRAIN_SET_NO" '
    [
      .Switches[].Devices[]
      | select(.SubType == "UIC")
      | {
          name: .Name,
          ip: (.IP | gsub("n"; $train)),
          pbxExtension: .PBXExtension,
          status: .Status
        }
    ]
  '
```

### Komutun yaptığı

İlk komut DeviceMap'teki UIC adresini bulur ve cihazın HTTP ayar ucundan
çalışma, ses, ağ ve SIP bilgilerini okur; PBX parolasını tanılama çıktısından
çıkarır. İkinci komut canlı DeviceMap mesajından UIC kaydını seçer. Mevcut
DeviceMap'te UIC adresi `10.n.1.60`, PBX dahili numarası `4001` olarak
tanımlıdır.

### Alınabilecek bilgiler

- UIC cihaz adı
- Cihazın bildirdiği IP ile tren setine göre çözülmüş beklenen IP
- PBX dahili numarası
- SIP kayıt durumu ve PBX adresi
- Hoparlör ve mikrofon ses seviyeleri
- Aktiflik durumu
- Ağ ve güç hata bayrakları
- Çalışma süresi
- Yazılım sürümü

## Uygulama Durumu (AppStatus)

PISCU ve HMI üzerinde çalışan uygulamalar durumlarını saklanan (`retained`)
MQTT mesajı olarak yayınlar. Sürüm ve donanım kimliği buradan alınır.

### Komut

```bash
mosquitto_sub \
  -h "$PISCU_IP" \
  -p "$PISCU_MQTT_PORT" \
  -t 'ALFA/AppStatus/#' \
  -W 5 \
| jq '{
    uygulama: .ClientId,
    ip: .DeviceIP,
    donanim_kimligi: .HWID,
    durum: .Status,
    yazilim_surumu: .Version
  }'
```

### Komutun yaptığı

`ALFA/AppStatus/` altındaki bütün saklanan mesajları okur. Aşağıdaki değerler
tren seti 1'den alınmış doğrulanmış örneklerdir; `DeviceIP` alanı şablon değil,
cihazın çözülmüş gerçek IP adresini taşır:

| ClientId | DeviceIP | Cihaz | Version | HWID |
|---|---|---|---|---|
| `ClientManager_PISCU_YATAKLI_1` | `10.1.1.1` | PISCU | `1.2.7` | `604A17F3` |
| `ClientManager_MCP_YATAKLI_1` | `10.1.1.4` | HMI | `1.2.5` | `34DA8534` |

Cihaz eşleştirmesi `DeviceIP` alanı üzerinden yapılmalıdır. `ClientId`
içindeki isme göre eşleştirmek yanlıştır — farklı tren setinin kaydını çeker.

Saklanan mesajın varlığı tek başına cihazın hâlâ bağlı olduğunu göstermez.
Panelin güncel doğrulaması, AppStatus `Status` alanının `connected` olmasını ve
canlı DeviceMap kaydındaki `Status.NoError` değerinin `true` olmasını birlikte
ister. AppStatus `disconnected` ise veya canlı kayıt cihazı arızalı/kapalı
bildiriyorsa sonuç başarısızdır.

### Alınabilecek bilgiler

- Uygulama kimliği (`ClientId`)
- Cihazın gerçek IP adresi
- Donanım kimliği (`HWID`)
- Bağlantı durumu (`connected`)
- Yazılım sürümü

## HMI

HMI'ın yazılım sürümü ve donanım kimliği **AppStatus mesajından** alınır
(`ClientManager_MCP_*`, bkz. yukarısı). Bu bilgiler için SSH gerekmez.

### Komut

AppStatus'ta bulunmayan işletim sistemi bilgileri gerekirse:

```bash
read -r -p 'HMI SSH kullanıcı adı: ' HMI_SSH_USERNAME
export HMI_SSH_USERNAME

for ip in $(device_ips HMI); do
  ssh "${HMI_SSH_USERNAME}@${ip}" \
    'hostnamectl; cat /etc/os-release; uptime; ip -j addr'
done
```

### Komutun yaptığı

DeviceMap'teki bütün HMI adreslerini gezer ve SSH üzerinden işletim sistemi,
çalışma süresi ve ağ bilgilerini okur. Mevcut DeviceMap'te HMI adresi
`10.n.1.4` olarak tanımlıdır. SSH kimliği henüz doğrulanmamıştır; kontrol
listesi bu komuta ihtiyaç duymaz.

### Alınabilecek bilgiler

- Ana makine adı (`hostname`)
- İşletim sistemi ve sürümü
- Çekirdek (`kernel`) ve mimari bilgileri
- Sistem çalışma süresi
- Sistem yük ortalaması
- Ağ arayüzleri
- IP ve MAC adresleri

## Asterisk PBX

### Komut

```bash
curl --connect-timeout 2 --max-time 10 -sS \
  -u "${ASTERISK_ARI_USERNAME}:${ASTERISK_ARI_PASSWORD}" \
  "http://${PISCU_IP}:${ASTERISK_ARI_PORT}/ari/asterisk/info" \
| jq
```

### Komutun yaptığı

PISCU üzerindeki Asterisk ARI servisinden PBX sistem bilgilerini okur.
`ASTERISK_ARI_USERNAME` ve `ASTERISK_ARI_PASSWORD` değişkenleri, "Komut
ortamını hazırlama" bölümündeki gizli istemle yetkili ARI hesabından
alınmalıdır. Panelin kontrol listesi bu isteğe bağlı tanılama komutunu
kullanmaz.

### Alınabilecek bilgiler

- Asterisk sürümü
- Derleme bilgileri
- Sistem ve çalışma durumu
- Asterisk yapılandırma bilgileri
- PBX çalışma süresi bilgileri
