# Kılavuz ekran görüntüleri

`docs/DABP_Kullanıcı_Kılavuzu.docx` ve `docs/DABP_Geliştirici_Kılavuzu.docx`
içindeki şekiller buradan üretilir. Üç dosya var:

| Dosya | Ne yapar |
|---|---|
| `server.py` | Paneli **demo okumalarla** çalıştırır; pencere açmaz, HTTP verir |
| `capture.py` | Chrome'u sürüp her şekli `out/` altına yazar |
| `embed.py` | Bakılmış şekilleri iki `.docx` kılavuzun içine yerinde yazar |

Bu bir **belgeleme iskelesidir**, uygulamanın parçası değildir —
`tests/support/fakes.py` ile aynı statüde, ve zaten onun sahtelerini
kullanır. `panel` ya da `app.py` buradan hiçbir şey içe aktarmaz.

## Neden gerekli

Kılavuz şekilleri bir trenin yanında çekilemez: donanım her zaman elde
olmaz, ve elde olsa bile iki çekim arasında farklı görünür. Burada okumalar
**belirlenimlidir** — aynı cihaz her koşuda aynı biçimde okunur — dolayısıyla
altı ay sonra yeniden alınan bir şekil yalnız ürünün değiştiği yerde farklıdır.

## Ne değiştiriliyor

- `panel.probe.reader.read_device` — bütün çağıranların (tam tarama, hafif
  yenileme, kimlik denetimi) kullandığı tek giriş. Yerine cihaz kimliğinin
  özetinden türeyen bir okuma konur: cihazların çoğu yanıt verir, birkaçı
  kimlik ister, bir ikisi erişilemezdir.
- `tests/support/fakes.py` içindeki sahte KYLAND switch'i loopback'te
  başlatılır (24 PoE + 4 uplink, `admin` / `123`).
- `tests/support/adb.FakeAdb`, `panel.adb.client`'ın **yalnız kendi**
  `subprocess` görünümünün yerine geçer. Gerçek modül nesnesine `.run`
  yazmak süreçteki her alt süreç çağrısını — `ifconfig -a` dahil —
  yönlendirir ve taramayı bozar.

Ortam, test paketinin sabitlediği gibi sabitlenir (`tests/__init__.py`):
operatörün gerçek ayarları yazılmaz, bu makinenin ağ arayüzüne takma adres
konmaz, ve derleme sırrı admin modu açar — mühendis ekranları da çekilebilsin.

## Kullanım

```bash
python3 -m pip install playwright pillow python-docx   # Chrome ayrıca kurulu olmalı
python3 tools/docshots/server.py         # ayrı bir terminalde
python3 tools/docshots/capture.py        # bütün şekiller
python3 tools/docshots/capture.py 10-switch-genel fig5-contextmenu
```

Üçü de sabitlenmemiştir; hiçbiri ürünle paketlenmez. `playwright` Chrome'u
sürer — tarayıcıyı kendisi indirmez, makinedekini (`channel="chrome"`)
kullanır. `pillow` yalnız `fig3-frontpanel` için gerekir: ön panel ile
büyütülmüş iki konnektör tek karede birleştirilir, ve yoksa koşu şekli
sadece ön panelden ibaret bırakıp bunu söyler. `python-docx` ise `embed.py`
olmadan gerekmez.

Çıktı `tools/docshots/out/` altına yazılır; `docs/user-guide-assets/` ve
`docs/dev-guide-assets/` altına **bakıldıktan sonra** kopyalanır.

Şekiller 1440×900'de, piksel oranı 2 ile alınır — uygulama penceresinin
kendi ölçüsü (`app.py` `WIDTH`/`HEIGHT`), baskı çözünürlüğünde. Yani her
dosya 2880×1800'dür.

Bakıldıktan ve kopyalandıktan sonra şekiller kılavuzların içine yazılır:

```bash
python3 tools/docshots/embed.py --dry-run    # ne değişeceğini söyler, yazmaz
python3 tools/docshots/embed.py              # iki .docx'i yerinde günceller
```

Şekil, gövdedeki sırasına göre değil **kapladığı medya parçasına** göre
adreslenir (`word/media/imageN.png`): paragraflar metin düzenlendikçe yer
değiştirir, medya parçaları değişmez. Yeni bir şekil eklemek bu yüzden iki
yere dokunur — `capture.py` onu çeker, `embed.py` içindeki eşleme onu bir
parçaya bağlar. İkincisi unutulursa şekil çekilir, kopyalanır ve kılavuza
hiç girmez; koşu bu yüzden eşlemenin sahiplenmediği her PNG'yi sonunda
listeler.

`server.py` başka bir paketle de çalışır:

```bash
python3 tools/docshots/server.py gaziray 8846
python3 tools/docshots/capture.py http://127.0.0.1:8846/
```
