#!/usr/bin/env python3
"""Devreye Alma Paneli — masaüstü uygulaması.

Normal masaüstü kipinde arayüz tek parça HTML olarak belleğe yüklenir ve
Python ile JavaScript pywebview'un doğrudan köprüsü üzerinden konuşur. Yerel
HTTP sunucusu, TCP portu veya loopback bağlantısı açılmaz. Npcap/WFP gibi ağ
süzgeçleri bu nedenle uygulamanın kendi arayüz iletişimine etki edemez.

HTTP yalnız açıkça ``--tarayici`` istendiğinde geliştirme/tanı amacıyla
başlatılır. Kapanışta iş kuyruğu durdurulur, MQTT dinleyicisi kapatılır ve
bellekteki bütün cihaz kimlikleri unutulur (bkz. panel_api.temizle).

Uygulama yükseltilmiş (yönetici) yetkiyle çalıştırılır; ağ arayüzü, ARP
önbelleği ve switch portlarıyla yapılan işler bunu gerektiriyor. Yetki yoksa
panel açılmaz; bunun yerine kullanıcıya bir pencere çıkar ve iki yol sunar —
yönetici olarak yeniden başlatmak ya da çıkmak (bkz. yetki.py).

Çalıştırma:
    python3 app.py
    python3 app.py --tarayici              # pencere yerine tarayıcıda aç
    python3 app.py --admin-parolasi ****   # admin ekranını şifreye bağla
    python3 app.py --self-test             # pencere açmadan doğrula
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import traceback
from pathlib import Path

BURASI = Path(__file__).resolve().parent
sys.path.insert(0, str(BURASI))

import yetki
from yetki import yonetici_mi                      # noqa: F401  (test yaması)

ASGARI_PYTHON = (3, 10)
GENISLIK, YUKSEKLIK = 1440, 900

PYWEBVIEW_YOK = (
    "Uygulama penceresi için pywebview gerekli ve kurulu değil.\n\n"
    "Kurulum:\n"
    "    python3 -m pip install -r docs/requirements.txt\n\n"
    "Pencere olmadan denemek için:\n"
    "    python3 app.py --tarayici"
)


def yaz(mesaj: str) -> None:
    try:
        print(mesaj)
    except Exception:
        pass


def http_hazir(url: str, saniye: float = 5.0) -> bool:
    """Tarayıcı kipindeki HTTP adaptörünün gerçekten yanıtını doğrular."""
    import json
    import time
    import urllib.request

    acici = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    son = time.monotonic() + saniye
    while time.monotonic() < son:
        try:
            with acici.open(f"{url}/api/surum", timeout=0.5) as yanit:
                veri = json.loads(yanit.read())
            if (yanit.status == 200 and isinstance(veri, dict)
                    and isinstance(veri.get("surum"), str)):
                return True
        except (OSError, ValueError):
            time.sleep(0.05)
    return False


def macos_kimlik(ad: str) -> None:
    """Dock'ta yorumlayıcının adı yerine uygulama adı görünsün."""
    if platform.system() != "Darwin" or getattr(sys, "frozen", False):
        return
    try:
        from Foundation import NSBundle
        bilgi = (NSBundle.mainBundle().localizedInfoDictionary()
                 or NSBundle.mainBundle().infoDictionary())
        if bilgi is not None:
            bilgi["CFBundleName"] = ad
            bilgi["CFBundleDisplayName"] = ad
    except Exception:
        pass


def self_test() -> int:
    """Pencere ve soket açmadan üretim masaüstü yolunu doğrular."""
    from core import ayar, device_map
    from masaustu import PanelKoprusu, html_yukle
    import panel_api

    sonuc = []

    def kontrol(ad: str, kosul: bool, ek: str = "") -> bool:
        yaz(f"  [{'OK  ' if kosul else 'HATA'}] {ad}" + (f" — {ek}" if ek else ""))
        sonuc.append(kosul)
        return kosul

    yaz(f"{ayar.APP_ADI} {ayar.APP_VERSION} — self-test")

    kontrol("DeviceMap bulundu", ayar.DEVICE_MAP.exists(), str(ayar.DEVICE_MAP))
    kontrol("Excel şablonu bulundu", ayar.EXCEL_SABLON.exists())
    for varlik in ("index.html", "masaustu.html", "css/temel.css", "js/app.js",
                   "piton-logo.svg", "piton-favicon.png"):
        kontrol(f"static/{varlik}", (ayar.STATIC_DIR / varlik).exists())
    # Kardeş projelerdeki üç betik (bkz. core/betik.py). Paketlenmiş
    # uygulamada bunlar paketin içine kopyalanır; biri eksikse switch
    # okuması, IP atama ya da Excel çıktısı sahada çalışmaz — paket
    # üretildiği yerde anlaşılsın.
    for ad, yol in (("Switch Yönetim Paneli backend'i", ayar.SWITCH_PANELI),
                    ("Saha doğrulama betiği", ayar.DEVICE_VERIFY),
                    ("IP atama betiği", ayar.INTERCOM_IP_ASSIGN)):
        kontrol(ad, yol.exists(), str(yol))

    try:
        env = device_map.yukle(1)
        kontrol("DeviceMap okundu", len(env.cihazlar) > 0,
                f"{len(env.cihazlar)} cihaz")
    except Exception as exc:
        kontrol("DeviceMap okundu", False, str(exc))

    kopru = None
    try:
        kopru = PanelKoprusu()
        html = html_yukle(kopru._yetenek)
        kontrol("Masaüstü arayüzü tek parça", "dap-transport" in html)
        panel_api.baslat()
        for yol in ("/api/surum", "/api/proje?set=1", "/api/durum?set=1"):
            zarf = kopru.invoke(kopru._yetenek, "GET", yol, {})
            kontrol(f"Köprü GET {yol}",
                    zarf.get("ok") is True and isinstance(zarf.get("body"), dict),
                    str(zarf.get("body", {}).get("hata", "")))
    except Exception as exc:
        kontrol("Soketsiz masaüstü köprüsü", False, str(exc))
    finally:
        if kopru is not None:
            kopru._kapat()
        panel_api.temizle()

    basarili = all(sonuc)
    yaz("SONUÇ: " + ("başarılı" if basarili else "başarısız"))
    return 0 if basarili else 1


def tarayici_kipi(port: int) -> int:
    """İsteğe bağlı geliştirme/tanı sunucusunu çalıştırır."""
    import threading
    import time
    import webbrowser

    from core import ayar
    import panel_api

    try:
        # Port 0 doğrudan gerçek dinleyiciye verilir. Ayrı bir sokette port
        # seçip kapatmak Windows'ta başka süreçlerle yarış oluşturuyordu.
        srv = panel_api.sunucu("127.0.0.1", port)
    except (OSError, ValueError, OverflowError) as exc:
        yaz(f"[HATA] Tarayıcı servisi açılamadı: {exc}")
        return 1

    gercek_port = int(srv.server_address[1])
    url = f"http://127.0.0.1:{gercek_port}"
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="panel-http")
    t.start()
    try:
        if not http_hazir(url):
            yaz("[HATA] Tarayıcı servisi HTTP yanıtı vermedi.")
            return 1
        yaz(f"{ayar.APP_ADI} {ayar.APP_VERSION} — tarayıcı tanı kipi")
        yaz(f"Adres: {url}")
        yaz("Durdurmak için Ctrl-C")
        webbrowser.open(url)
        try:
            while t.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            yaz("\nKapatılıyor.")
        return 0
    finally:
        srv.shutdown()
        srv.server_close()
        panel_api.temizle()


def main() -> int:
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if sys.version_info < ASGARI_PYTHON:
        yaz(f"[HATA] Python {ASGARI_PYTHON[0]}.{ASGARI_PYTHON[1]}+ gerekli.")
        return 1

    ap = argparse.ArgumentParser(description="Devreye Alma Paneli")
    ap.add_argument("--tarayici", action="store_true",
                    help="HTTP tabanlı geliştirme/tanı kipini tarayıcıda aç")
    ap.add_argument("--port", type=int, default=None,
                    help="yalnız --tarayici kipindeki port (0 = otomatik)")
    ap.add_argument("--admin-parolasi", default=None,
                    help="admin ekranı bu şifreyi sorar; hiçbir yere yazılmaz")
    ap.add_argument("--self-test", action="store_true",
                    help="pencere açmadan paketi doğrula")
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args()

    from core import ayar
    if a.version:
        yaz(ayar.APP_VERSION)
        return 0
    if a.self_test:
        return self_test()

    # Argüman doğrulaması yetki denetiminden önce: yanlış kullanım, yetki
    # uyarısının arkasına saklanmasın.
    if a.port is not None and not a.tarayici:
        yaz("[HATA] --port yalnız --tarayici ile kullanılabilir.")
        return 2

    # Dock kimliği yetki denetiminden ÖNCE kurulur: yetki penceresi de bu
    # uygulamanın penceresi. Kurulmayınca Dock'ta yorumlayıcının adıyla
    # ("Python") ayrı bir simge çıkıyor ve panel İKİNCİ bir uygulama gibi
    # görünüyordu.
    macos_kimlik(ayar.APP_ADI)

    # Yetki denetimi paket doğrulamasından (--self-test, --version) sonra
    # ama servis kurulmadan önce: o iki kip cihaza ve ağa hiç dokunmadığı
    # için yükseltilmiş yetki istemez.
    #
    # Yetki yoksa panel yine açılmaz; ama kullanıcı sebebini bir pencerede
    # görür ve oradan yönetici olarak yeniden başlatabilir (bkz. yetki.akis).
    if not yonetici_mi():
        return yetki.akis(yaz)

    import panel_api
    panel_api.admin_parolasi_ayarla(
        a.admin_parolasi or os.environ.get("PANEL_ADMIN_PAROLASI"))

    if a.tarayici:
        return tarayici_kipi(0 if a.port is None else a.port)

    kopru = None
    try:
        try:
            import webview
        except ImportError:
            yaz("[HATA] " + PYWEBVIEW_YOK)
            return 1

        from masaustu import PanelKoprusu, html_yukle

        panel_api.baslat()
        kopru = PanelKoprusu()
        html = html_yukle(kopru._yetenek)
        # Pywebview 6.x'te dosya URL'leri kimi platformlarda varsayılan
        # olarak açık olabilir. Arayüz bellekte olduğu için ikisine de gerek
        # yoktur; açıkça kapatmak yanlış paketlemenin sessizce çalışmasını da
        # önler.
        webview.settings["ALLOW_FILE_URLS"] = False
        webview.settings["ALLOW_DOWNLOADS"] = False
        # Gelecekte arayüze target=_blank bağlantı eklenirse ayrıcalıklı
        # WebView içinde gezinmesin; işletim sisteminin tarayıcısına çıksın.
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["REMOTE_DEBUGGING_PORT"] = None

        pencere = webview.create_window(
            ayar.APP_ADI, html=html,
            width=GENISLIK, height=YUKSEKLIK,
            min_size=(980, 620),
            background_color="#101820",
        )
        # js_api=nesne kullanılmaz: pywebview'un düşük seviyeli çağrı
        # dağıtıcısında nesnenin gizli üyelerine adla erişim yüzeyi kalır.
        # Exact-name allowlist'e yalnız oturum anahtarı denetleyen bu tek
        # fonksiyon eklenir; köprünün durumu WebView'a aktarılmaz.
        pencere.expose(kopru.invoke)
        yaz(f"{ayar.APP_ADI} {ayar.APP_VERSION} — soketsiz masaüstü kipi")
        yaz(f"DeviceMap: {ayar.DEVICE_MAP}")
        yaz("Kimlik bilgileri arayüzden istenir, hiçbir yere yazılmaz.")
        if platform.system() == "Windows":
            # Eski MSHTML motoruna sessiz geri dönüş yok: modern modül ve
            # güvenlik davranışı için WebView2 zorunludur.
            webview.start(gui="edgechromium", http_server=False)
        else:
            webview.start(http_server=False)
        return 0
    except Exception:
        yaz("[HATA] Pencere açılamadı:\n" + traceback.format_exc(limit=4))
        return 1
    finally:
        # Pencere kapandı: yeni köprü çağrıları kesilir; kuyruk, MQTT ve
        # bellekteki kimlikler temizlenir. Burada kapatılacak HTTP sunucusu
        # yoktur.
        if kopru is not None:
            kopru._kapat()
        yaz("Arka plan işlemleri durduruluyor.")
        panel_api.temizle()


def _hemen_cik(kod: int) -> None:
    """Yorumlayıcıyı doğrudan bitirir.

    Pencere motoru (pywebview → Cocoa/GTK) olay döngüsü kapandıktan sonra
    süreci ayakta tutabiliyor: yetki penceresinden yükseltilmiş süreç
    başlatıldıktan sonra ESKİ süreç kendiliğinden kapanmadı, dışarıdan
    sonlandırılana kadar açık kaldı. Aynı panelin iki kopyasının aynı
    switch'e ve aynı DeviceMap'e bakması tam da kaçınılan durum.

    `main()` çoktan döndüğü için kapatılacak bir şey kalmıyor: köprü ve
    servisler onun `finally` bloğunda zaten kapandı (bkz. main). Geriye
    yalnız tamponlardaki çıktıyı boşaltmak kalıyor.
    """
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.flush()
        except Exception:
            pass
    os._exit(int(kod))


if __name__ == "__main__":
    _hemen_cik(main())
