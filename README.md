# Devreye Alma Paneli

Tren setinin tamamını (switch, anons, video, ekran, kontrol) doğrulayan,
IP atayan ve konfigüre eden masaüstü uygulaması.

> **Depo iki uygulama barındırır, her biri kendi branch'inde:**
>
> | Branch | Uygulama | Etiket |
> |---|---|---|
> | `main` | Devreye Alma Paneli (bu ağaç) | `dap-v*` |
> | `syp` | Switch Yönetim Paneli | `syp-v*`, `v*` |
>
> İki branch'in ortak geçmişi `fb320cd` commit'ine kadar aynıdır; eski
> `Interface/…` ve `YATAKLI_DevreyeAlma/` düzeni o commit'e kadar geçmişte
> olduğu gibi durur.

## Çalıştırma

```bash
pip install -r docs/requirements-macos.txt   # ya da -windows / -linux
python3 app.py
```

Doğrulama (pencere açmaz, cihaza bağlanmaz):

```bash
python3 app.py --self-test
python3 -m unittest discover -s tests -t .
```

## Dizin yapısı

| Yol | Ne var |
|---|---|
| `app.py` | Uygulama penceresi ve açılış akışı |
| `panel_api.py` | Panelin yerel HTTP API'si |
| `core/` | İş mantığı (`ayar.py` içinde `APP_VERSION`) |
| `betikler/` | Panelin çalışma anında yüklediği motorlar — aşağıya bak |
| `static/` | Arayüz (HTML / CSS / JS) |
| `tests/` | Birim testler (sahte cihaz sunucularıyla) |
| `docs/` | Mimari, cihaz uçları, paketleme belgeleri |
| `DeviceMap.json` | Ağ topolojisinin tek kaynağı |
| `Yatakli_Saha_Cihaz_Dogrulama.xlsx` | Boş kontrol listesi şablonu |

### `betikler/` neden ayrı

Panel, sahada denenmiş üç betiğin iş mantığını yeniden yazmaz; çalışma
anında dosya yolundan içe aktarır (`core/betik.py`). Paketlenirken bu üç
dosya paketin köküne kopyalanır.

| Dosya | Ne yapar | Aslen |
|---|---|---|
| `switch_api.py` | Switch erişimi, PoE / port okuma | Switch Yönetim Paneli (`syp` branch'i) |
| `device_verify.py` | Alan ayıklama, Excel şeması | Saha doğrulama betiği |
| `intercom_ip_assign.py` | Intercom IP atama akışı | Saha atama betiği |

`switch_api.py` bir kopyadır: özgün dosya `syp` branch'inin kökündedir ve
iki taraf **elle** eşitlenir. Switch tarafında API değişince buraya da
taşınması gerekir.

## Sürüm ve paketleme

Etiket biçimi `dap-v0.9.0-dev`. Etiketteki sürüm `core/ayar.py` içindeki
`APP_VERSION` ile birebir aynı olmak zorundadır; değilse build açık bir
hatayla durur.

Mimari ve ekranlar: **[docs/MIMARI.md](docs/MIMARI.md)** ·
paket üretme ve yayınlama: **[docs/BUILD_RELEASE.md](docs/BUILD_RELEASE.md)** ·
sürüm notları: **[docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md)**

Cihaz uçları ve veri alanları:
**[docs/CIHAZ_ENDPOINTLERI.md](docs/CIHAZ_ENDPOINTLERI.md)** ·
**[docs/CIHAZ_VERI_ALANLARI.md](docs/CIHAZ_VERI_ALANLARI.md)**

Hazır paketler [Releases](../../releases) sayfasındadır. Paketler imzasızdır;
Windows'ta WebView2 Runtime gerekir.
