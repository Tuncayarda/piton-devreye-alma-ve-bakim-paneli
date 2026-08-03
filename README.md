# VIP / YATAKLI — Devreye Alma

Tren devreye alma çalışmaları için araçlar.

## İçerik

| Klasör | Ne işe yarar |
|---|---|
| `Interface/Switch Yönetim Paneli/` | KYLAND switch'leri bulan, port/PoE/IP ayarlarını yöneten masaüstü uygulaması |
| `YATAKLI_DevreyeAlma/` | Saha cihaz doğrulama ve intercom IP atama betikleri |

## Switch Yönetim Paneli

Geliştirme çalıştırması:

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

Hazır paketler [Releases](../../releases) sayfasındadır. Paketler imzasızdır;
Windows'ta WebView2 Runtime gerekir —
ayrıntılar yukarıdaki belgede.
