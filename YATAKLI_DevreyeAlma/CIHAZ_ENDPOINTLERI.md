# Yataklı Cihazlardan Veri Alma

DeviceMap'te 2 switch ve switch'lere bağlı 40 cihaz bulunmaktadır. IP adresleri
`10.n.1.x` şablonundadır. Buradaki `n`, tren set numarasıdır.

IP adresleri `.env` içinde tek tek tutulmaz. Bütün komutlar cihaz listesini
`DeviceMap.json` dosyasından Type/SubType bilgisine göre bulur ve `n` değerini
`.env` içindeki `TRAIN_SET_NO` ile değiştirir. DeviceMap'e aynı tipte yeni bir
cihaz eklendiğinde komutlar o cihazı da otomatik olarak kapsar.

İkinci oktet tren setini belirtir: `10.1.1.x` tren 1, `10.2.1.x` tren 2.
`DeviceMap.json` içindeki `TrainSet` alanı dosyanın hangi trene ait olduğunu
söyler; durum bilgileri (versiyon, uptime, aktiflik) yalnızca o tren için
geçerlidir.

`ARDUINO_HTTP_PORT`, `VIDEO_HTTP_PORT` ve `KYLAND_HTTP_PORT` değerlerinin
üçü de `80`'dir. Cihaz türü port numarasından ayırt edilemez; ayrım
endpoint yoluna göre yapılır.

Komutları çalıştırmadan önce:

```bash
cd YATAKLI_DevreyeAlma
set -a
source .env
set +a

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
```

## Announcement cihazlarının ortak alan adları

Amplifier, Handset ve Intercom aynı `/api/v1/system/settings` yanıtını verir.
Doğrulanmış alan adları:

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

- Dış arama alanının adı **`pbxOutExtension`** — "outbound" değil "out".
- **Seri numarası alanı yoktur.** Bu cihazlarda `Cihaz Numarası` boş kalır.
- `speakergain` / `micgain`, `speakervolume` / `micvolume` alanlarından
  ayrıdır; kontrol listesinde ayrı sütunlarda tutulur.
- `pbxpassword` çıktıdan silinmeli, kontrol listesine yazılmaz.

## Amplifier

### Komut

```bash
for ip in $(device_ips Announcement Amplifier); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/settings" \
  | jq --arg ip "$ip" '{ip: $ip, data: del(.pbxPassword)}'
done
```

```bash
for ip in $(device_ips Announcement Amplifier); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/logs"
done
```

### Komutun yaptığı

DeviceMap'teki bütün Amplifier IP son oktetlerini gezer. Her erişilebilir
Amplifier cihazından çalışma, ses, ağ ve SIP bilgilerini alır. PBX parolasını
çıktıdan siler. İkinci komut cihaz loglarını alır.

Mevcut DeviceMap'te Amplifier adresi `10.n.1.5` olarak tanımlıdır. Yeni
Amplifier kayıtları DeviceMap'e eklendiğinde komut onları da otomatik sorgular.

> **Not:** Amplifier'ın `pbxoutextension` değeri boştur — dışarı arama
> yapmadığı doğrulanmıştır. Kontrol listesinde `SIP Arama No` sütunu bu
> bölümde gri bırakılmıştır. `micvolume` alanını döndürür (gözlemlenen
> değer `0`).

### Alınabilecek bilgiler

- Yazılım versiyonu
- SIP kayıt durumu
- Uptime
- Hoparlör seviyesi ve gain değeri
- Log seviyesi
- DHCP durumu
- IP, subnet mask ve gateway
- PBX IP ve PBX dahili numarası
- NTP IP
- Sistem başlatma, Ethernet ve SIP kayıt logları

## Handset

### Komut

```bash
for ip in $(device_ips Announcement Handset); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/settings" \
  | jq --arg ip "$ip" '{ip: $ip, data: del(.pbxPassword)}'

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

DeviceMap'teki bütün Handset adreslerini gezer. Handset çalışma, ses, ağ, SIP
ve çalışma modu bilgilerini alır. PBX parolasını çıktıdan siler. İkinci komut
cihaz loglarını alır.

Mevcut DeviceMap'te Handset adresi `10.n.1.6` olarak tanımlıdır.

### Alınabilecek bilgiler

- Yazılım versiyonu
- SIP kayıt durumu
- Uptime
- Mikrofon ve hoparlör seviyeleri
- Mikrofon ve hoparlör gain değerleri
- Anlık mikrofon seviyesi
- IP, subnet mask ve gateway
- PBX IP, PBX dahili ve dış arama numarası
- Answer, hangup ve call modları
- PTT durumu
- Log seviyesi
- Sistem ve SIP kayıt logları

## Intercomlar

### Komut

```bash
for ip in $(device_ips Announcement Intercom); do
  curl --connect-timeout 2 --max-time 5 -sS \
    "http://${ip}:${ARDUINO_HTTP_PORT}/api/v1/system/settings" \
  | jq --arg ip "$ip" '{ip: $ip, data: del(.pbxPassword)}'
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
adresleri gezer. Erişilebilir olan her Intercom cihazından çalışma, ses, ağ ve
SIP bilgilerini alır. PBX parolasını çıktıdan siler. İkinci komut cihaz
loglarını alır.

### Alınabilecek bilgiler

- Yazılım versiyonu
- SIP kayıt durumu
- Uptime
- Mikrofon ve hoparlör seviyeleri
- Mikrofon ve hoparlör gain değerleri
- Anlık mikrofon seviyesi
- IP, subnet mask ve gateway
- PBX IP, PBX dahili ve dış arama numarası
- Arama zaman aşımı
- Sistem ve SIP kayıt logları

## PISCU / EMQX Dashboard

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
Dashboard API'sine giriş yapar ve geçici tokenla broker durum bilgilerini
okur. Token her PISCU sorgusunun sonunda silinir.

İkinci komut MQTT broker üzerindeki retained `ALFA/DeviceMap` mesajını alır.
Mevcut DeviceMap'te PISCU adresi `10.n.1.1` olarak tanımlıdır.

> **Not:** Bu bölüm broker bilgisi verir. PISCU'nun **kendi yazılım sürümü ve
> donanım kimliği** buradan alınmaz — `ALFA/AppStatus/ClientManager_PISCU_*`
> mesajından gelir (bkz. "Uygulama Durumu" bölümü). EMQX sürümü (`5.x`) ile
> PISCU uygulama sürümü (`1.2.x`) farklı şeylerdir.

### Alınabilecek bilgiler

- EMQX sürümü ve edition bilgisi
- Broker node adı, çalışma durumu ve uptime
- Bağlı MQTT client sayısı
- Client ID, bağlantı IP'si ve bağlantı zamanı
- Client başına subscription ve mesaj sayaçları
- Aktif MQTT topic listesi
- Client-topic subscription eşleşmeleri ve QoS değerleri
- MQTT TCP ve WebSocket listener durumları
- Broker metrikleri ve istatistikleri
- DeviceMap içindeki 2 switch ve 40 cihazın bilgileri

## KYLAND Switch'ler

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
Her switch'in HTTP Basic Authentication korumalı durum endpointlerinden cihaz,
port, PoE, MAC, trafik, LLDP, STP, ARP ve log bilgilerini okur.

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

> **Not:** `serialNum` değeri literal `--` döner, yani seri numarası
> okunamıyor — kontrol listesinde switch'in `Cihaz Numarası` sütunu gri
> bırakılmıştır. Ayrıca uptime tek bir alan değil, `operateTime` altında
> parçalı gelir.

### Alınabilecek bilgiler

- Switch modeli ve cihaz adı
- MAC adresi (seri numarası dönmüyor)
- Donanım, logic ve yazılım sürümleri
- Build tarihi
- CPU ve RAM kullanımı
- Sistem zamanı ve uptime
- FE/GE port listesi
- Port bazında PoE durumu, güç ve akım
- MAC adresinin bağlı olduğu switch portu
- Port bazında RX/TX byte ve paket sayaçları
- Unicast, multicast, broadcast, drop, pause ve CRC sayaçları
- LLDP komşuları ve yönetim adresleri
- Port STP rolü ve durumu
- ARP tablosu
- Switch sistem ve erişim logları

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
- Firmware ve cihaz sürümü
- Cihaz adı
- Saat dilimi ve yerel saat
- NTP sunucusu
- IP adresi
- Subnet mask
- Gateway ve ağ arayüzleri

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
- Firmware ve cihaz sürümü
- Saat dilimi ve yerel saat
- NTP sunucusu
- IP, subnet mask ve gateway
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
done
```

### Komutun yaptığı

DeviceMap içinde `Type: LCD` ve `SubType: Compartment` olan bütün cihazları
bulur. Mevcut DeviceMap'te `10.n.1.40` ile `10.n.1.50` arasında 11
Compartment LCD bulunmaktadır.

Her Compartment LCD'nin TCP `5555` ADB servisine bağlanarak Android cihaz
bilgilerini okur. `10.1.1.40:5555` bağlantısı doğrulanmış ve cihaz
`rk3568_r` shell ortamını açmıştır.

> **Not — uygulama sürümü:** `ro.build.display.id` değeri
> `C33P-V1.5-11-WM-15...` şeklindedir; bu Android **build kimliğidir**,
> uygulama sürümü değil. DeviceMap `Status.Version` alanı da (`0.0.5`)
> sahadaki kurulu sürümle uyuşmuyor. Doğru kaynak netleşene kadar kontrol
> listesinde bu bölümün `Versiyon` sütunu gri bırakılmıştır.
> `ro.serialno` (seri no) ve `persist.sys.timezone` (saat dilimi) okunmaya
> devam etmektedir.

### Alınabilecek bilgiler

- Cihaz üreticisi
- Cihaz modeli
- Kart ve işlemci platformu
- Android seri numarası
- Android sürümü
- Android build bilgisi
- Saat dilimi
- Sistem uptime
- Ekran çözünürlüğü

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
Bu cihazlarda ADB veya başka bir cihaz içi endpoint henüz doğrulanmamıştır.

### Alınabilecek bilgiler

- Cihaz adı ve gerçek IP
- Aktiflik durumu
- Ağ ve güç hata bayrakları
- Uptime
- DeviceMap'te bulunuyorsa yazılım versiyonu ve seri numarası

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

- Cihaz adı ve gerçek IP
- Cihaz tipi ve alt tipi
- Ekran genişliği ve yüksekliği
- Aktiflik durumu
- Ağ, güç, süreç ve sistem hata bayrakları
- Uptime
- Yazılım versiyonu

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
- Beklenen ve gerçek IP
- Aktiflik durumu
- Ağ ve güç hata bayrakları
- Uptime
- DeviceMap'te bulunuyorsa versiyon ve seri numarası

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
- Beklenen ve gerçek IP
- Aktiflik durumu
- Ağ ve güç hata bayrakları
- Uptime
- DeviceMap'te bulunuyorsa versiyon ve seri numarası

## UIC

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

DeviceMap mesajını okuyup UIC cihazını seçer. Mevcut DeviceMap'te UIC adresi
`10.n.1.60`, PBX dahili numarası `4001` olarak tanımlıdır.

### Alınabilecek bilgiler

- UIC cihaz adı
- Beklenen ve gerçek IP
- PBX dahili numarası
- Aktiflik durumu
- Ağ ve güç hata bayrakları
- Uptime
- Yazılım versiyonu

## Uygulama Durumu (AppStatus)

PISCU ve HMI üzerinde çalışan uygulamalar durumlarını retained MQTT mesajı
olarak yayınlar. Sürüm ve donanım kimliği buradan alınır.

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

`ALFA/AppStatus/` altındaki bütün retained mesajları okur. Mevcut sistemde iki
mesaj bulunmaktadır:

| ClientId | DeviceIP | Cihaz | Version | HWID |
|---|---|---|---|---|
| `ClientManager_PISCU_YATAKLI_1` | `10.n.1.1` | PISCU | `1.2.7` | `604A17F3` |
| `ClientManager_MCP_YATAKLI_1` | `10.n.1.4` | HMI | `1.2.5` | `34DA8534` |

Cihaz eşleştirmesi `DeviceIP` alanı üzerinden yapılmalıdır. `ClientId`
içindeki isme göre eşleştirmek yanlıştır — farklı tren setinin kaydını çeker.

### Alınabilecek bilgiler

- Uygulama kimliği (`ClientId`)
- Cihazın gerçek IP adresi
- Donanım kimliği (`HWID`)
- Bağlantı durumu (`connected`)
- Yazılım sürümü

## HMI

HMI'nin yazılım sürümü ve donanım kimliği **AppStatus mesajından** alınır
(`ClientManager_MCP_*`, bkz. yukarısı). Bu bilgiler için SSH gerekmez;
`.env` içindeki `HMI_SSH_USERNAME` ve `HMI_SSH_PASSWORD` kullanılmamaktadır.

### Komut

AppStatus'ta bulunmayan işletim sistemi bilgileri gerekirse:

```bash
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

- Hostname
- İşletim sistemi ve sürümü
- Kernel ve mimari bilgileri
- Sistem uptime
- Load average
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
`.env` içindeki `ASTERISK_ARI_USERNAME` ve `ASTERISK_ARI_PASSWORD` değerleri
yetkili ARI hesabıyla doldurulmalıdır.

### Alınabilecek bilgiler

- Asterisk sürümü
- Build bilgileri
- Sistem ve çalışma durumu
- Asterisk yapılandırma bilgileri
- PBX uptime bilgileri
