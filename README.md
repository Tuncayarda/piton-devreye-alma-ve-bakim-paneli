# VIP / YATAKLI — Devreye Alma

Tren devreye alma çalışmaları için araçlar.

## İçerik

| Klasör | Ne işe yarar |
|---|---|
| `Interface/Switch Yönetim Paneli/` | KYLAND switch'leri bulan, port/PoE/IP ayarlarını yöneten masaüstü uygulaması |
| `Interface/Devreye Alma Paneli/` | Tren setinin tamamını (switch, anons, video, ekran, kontrol) doğrulayan, IP atayan ve konfigüre eden masaüstü uygulaması |
| `YATAKLI_DevreyeAlma/` | Saha cihaz doğrulama ve intercom IP atama betikleri |

İki uygulama **ayrı ayrı** derlenir ve **ayrı** Release alır. Devreye Alma
Paneli, switch erişimi ve saha betikleri için Switch Yönetim Paneli'nin
`switch_api.py` dosyasını ve `YATAKLI_DevreyeAlma/` betiklerini çalışma
anında kullanır; paketlenirken bu dosyalar paketin içine kopyalanır.

## Switch Yönetim Paneli

```bash
cd "Interface/Switch Yönetim Paneli"
pip install -r docs/requirements-macos.txt   # ya da -windows / -linux
python3 app.py
```

Hızlı doğrulama (pencere açmaz, ağa çıkmaz):

```bash
python3 app.py --self-test
```

Paket üretme, GitHub Actions ve sürüm yayınlama:
**[Interface/Switch Yönetim Paneli/docs/BUILD_RELEASE.md](Interface/Switch%20Y%C3%B6netim%20Paneli/docs/BUILD_RELEASE.md)**

## Devreye Alma Paneli

```bash
cd "Interface/Devreye Alma Paneli"
pip install -r docs/requirements-macos.txt   # ya da -windows / -linux
python3 app.py
```

Doğrulama (pencere açmaz, cihaza bağlanmaz):

```bash
python3 app.py --self-test
python3 -m unittest discover -s tests -t .
```

Mimari ve ekranlar: **[docs/MIMARI.md](Interface/Devreye%20Alma%20Paneli/docs/MIMARI.md)** ·
paket üretme ve yayınlama: **[docs/BUILD_RELEASE.md](Interface/Devreye%20Alma%20Paneli/docs/BUILD_RELEASE.md)**

## Sürüm etiketleri

Depoda iki uygulama olduğu için etiketler önekli:

| Etiket | Hangi uygulama | Workflow |
|---|---|---|
| `syp-v1.2.3` | Switch Yönetim Paneli | `build-switch.yml` |
| `v1.2.3` | Switch Yönetim Paneli (eski biçim, çalışmaya devam eder) | `build-switch.yml` |
| `dap-v0.9.0-dev` | Devreye Alma Paneli | `build-devreye.yml` |

Etiketteki sürüm, uygulamanın kendi `APP_VERSION` değeriyle aynı olmak
zorundadır; değilse build açık bir hatayla durur.

Hazır paketler [Releases](../../releases) sayfasındadır. Paketler imzasızdır;
Windows'ta WebView2 Runtime gerekir — ayrıntılar uygulamaların
BUILD_RELEASE belgelerinde.
