#!/usr/bin/env python3
"""HTTP gerektirmeyen masaüstü arayüz artefaktını üretir.

``static/index.html`` ve modüler JavaScript kaynakları tarayıcı kipinin
kaynağı olmaya devam eder. Bu araç, aynı kaynaklardan pywebview için tek bir
HTML dosyası türetir:

* Deno 2.9.4 ile JavaScript modül grafiğini IIFE biçiminde paketler.
* Üç CSS dosyasını, logo ve favicon'u HTML içine gömer.
* Köprü taşımasını işaretler ve ağ erişimini kapatan bir CSP ekler.

Çıktı deterministiktir; tarih, geçici yol ya da makineye özgü bilgi içermez.
Artefakt elle düzenlenmemelidir.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

KOK = Path(__file__).resolve().parent.parent
STATIC = KOK / "static"
GIRIS_HTML = STATIC / "index.html"
GIRIS_JS = STATIC / "js" / "app.js"
CIKTI = STATIC / "masaustu.html"
CSS_DOSYALARI = (
    STATIC / "css" / "temel.css",
    STATIC / "css" / "bilesen.css",
    STATIC / "css" / "ekran.css",
)
LOGO = STATIC / "piton-logo.svg"
FAVICON = STATIC / "piton-favicon.png"
DENO_SURUMU = "2.9.4"
CAPABILITY_PLACEHOLDER = "__DAP_CAPABILITY__"
CAPABILITY_DESENI = re.compile(r"[A-Za-z0-9_-]{43}\Z")
BRIDGE_BOOTSTRAP = (
    '(() => {\n'
    '  const meta = document.querySelector(\'meta[name="dap-capability"]\');\n'
    '  if (!meta) throw new Error("Masaüstü köprü anahtarı bulunamadı");\n'
    '  Object.defineProperties(window, {\n'
    '    __PANEL_TRANSPORT__: '
    '{value: "bridge", writable: false, configurable: false},\n'
    '    __PANEL_CAPABILITY__: '
    '{value: meta.content, writable: false, configurable: false},\n'
    '  });\n'
    '  document.addEventListener("click", (olay) => {\n'
    '    const hedef = olay.target;\n'
    '    if (hedef && hedef.closest && hedef.closest("a[href]")) '
    'olay.preventDefault();\n'
    '  }, true);\n'
    '  document.addEventListener("submit", (olay) => olay.preventDefault(), true);\n'
    '  for (const ad of ["dragenter", "dragover", "drop"]) {\n'
    '    document.addEventListener(ad, (olay) => olay.preventDefault(), true);\n'
    '  }\n'
    '})();'
)


class PaketHatasi(RuntimeError):
    """Üretim veya güvenlik denetimi tamamlanamadı."""


class _HtmlDenetleyici(HTMLParser):
    """Yükleme yapan HTML niteliklerini ve CSP metnini toplar."""

    URL_NITELIKLERI = frozenset({
        "src", "href", "poster", "action", "formaction", "background",
        "manifest", "xlink:href",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.url_nitelikleri: list[tuple[str, str, str, dict[str, str]]] = []
        self.data_nitelikleri: list[tuple[str, str, str, dict[str, str]]] = []
        self.yasakli_nitelikler: list[tuple[str, str]] = []
        self.tekrarli_nitelikler: list[tuple[str, str]] = []
        self.script_nitelikleri: list[dict[str, str]] = []
        self.csp: list[str] = []
        self.tasima: list[str] = []
        self.capability: list[str] = []
        self.meta_refresh_sayisi = 0
        self.style_sayisi = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        adlar = [ad.lower() for ad, _ in attrs]
        for ad in sorted(set(adlar)):
            if adlar.count(ad) > 1:
                self.tekrarli_nitelikler.append((tag, ad))
        nitelikler = {ad.lower(): deger or "" for ad, deger in attrs}
        for ad, deger in nitelikler.items():
            if ad in self.URL_NITELIKLERI:
                self.url_nitelikleri.append((tag, ad, deger, nitelikler))
            if deger.strip().lower().startswith("data:"):
                self.data_nitelikleri.append((tag, ad, deger, nitelikler))
            if ad in {"srcset", "ping"} or (tag == "object" and ad == "data"):
                self.yasakli_nitelikler.append((tag, ad))
        if tag == "script":
            self.script_nitelikleri.append(nitelikler)
        elif tag == "style":
            self.style_sayisi += 1
        elif tag == "meta":
            http_equiv = nitelikler.get("http-equiv", "").strip().lower()
            if http_equiv == "content-security-policy":
                self.csp.append(nitelikler.get("content", ""))
            elif http_equiv == "refresh":
                self.meta_refresh_sayisi += 1
            meta_adi = nitelikler.get("name", "").strip().lower()
            if meta_adi == "dap-transport":
                self.tasima.append(nitelikler.get("content", ""))
            elif meta_adi == "dap-capability":
                self.capability.append(nitelikler.get("content", ""))


def _komut(argv: list[str], *, hata_basligi: str) -> subprocess.CompletedProcess[str]:
    cevre = os.environ.copy()
    cevre["DENO_NO_UPDATE_CHECK"] = "1"
    cevre["NO_COLOR"] = "1"
    try:
        sonuc = subprocess.run(
            argv,
            cwd=KOK,
            env=cevre,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PaketHatasi(f"{hata_basligi}: {exc}") from exc
    if sonuc.returncode:
        ayrinti = (sonuc.stderr or sonuc.stdout).strip()
        raise PaketHatasi(f"{hata_basligi} (çıkış {sonuc.returncode}):\n{ayrinti}")
    return sonuc


def deno_bul() -> str:
    """Deterministik bundle için tam olarak sabitlenen Deno'yu doğrular."""
    deno = shutil.which("deno")
    if not deno:
        raise PaketHatasi(
            f"Deno {DENO_SURUMU} bulunamadı. Masaüstü paketini üretmek için "
            f"Deno {DENO_SURUMU}'ü "
            "kurun ve `deno --version` komutunun PATH üzerinde çalıştığını "
            "doğrulayın: https://docs.deno.com/runtime/getting_started/installation/"
        )
    sonuc = _komut([deno, "--version"], hata_basligi="Deno sürümü okunamadı")
    eslesme = re.search(r"(?m)^deno\s+(\d+\.\d+\.\d+)(?=\s|$)", sonuc.stdout)
    if not eslesme:
        raise PaketHatasi(f"Deno sürümü anlaşılamadı: {sonuc.stdout.strip()!r}")
    surum = eslesme.group(1)
    if surum != DENO_SURUMU:
        raise PaketHatasi(
            f"Deterministik masaüstü paketi için Deno {DENO_SURUMU} gerekli; "
            f"PATH üzerindeki sürüm Deno {surum}. "
            f"`deno upgrade --version {DENO_SURUMU}` komutunu kullanın."
        )
    return deno


def javascript_paketle(deno: str) -> str:
    """app.js grafiğini denetler ve dış bağımlılıksız bir IIFE döndürür."""
    ortak = ["--no-config", "--no-lock", "--no-remote"]
    _komut(
        [deno, "check", *ortak, str(GIRIS_JS.relative_to(KOK))],
        hata_basligi="JavaScript tip/söz dizimi denetimi başarısız",
    )
    sonuc = _komut(
        [
            deno,
            "bundle",
            "--platform",
            "browser",
            "--format",
            "iife",
            *ortak,
            str(GIRIS_JS.relative_to(KOK)),
        ],
        hata_basligi="JavaScript paketi üretilemedi",
    )
    paket = sonuc.stdout.replace("\r\n", "\n").rstrip() + "\n"
    if not paket.strip():
        raise PaketHatasi("Deno boş bir JavaScript paketi üretti.")
    return paket


def _veri_uri(yol: Path, mime: str) -> str:
    kod = base64.b64encode(yol.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{kod}"


def _tam_degistir(metin: str, eski: str, yeni: str, *, adet: int = 1) -> str:
    bulunan = metin.count(eski)
    if bulunan != adet:
        raise PaketHatasi(
            f"{GIRIS_HTML.relative_to(KOK)} şablonu beklenen biçimde değil: "
            f"{eski!r} {adet} kez yerine {bulunan} kez bulundu."
        )
    return metin.replace(eski, yeni)


def _css_birlestir() -> str:
    parcalar = []
    for yol in CSS_DOSYALARI:
        metin = yol.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip()
        if _ham_metin_kapanisi_var(metin, "style"):
            raise PaketHatasi(f"{yol.relative_to(KOK)} güvenli biçimde gömülemiyor.")
        parcalar.append(f"/* {yol.relative_to(KOK).as_posix()} */\n{metin}")
    return "\n\n".join(parcalar) + "\n"


def _script_ozeti(script_icerigi: str) -> str:
    ozet = hashlib.sha256(script_icerigi.encode("utf-8")).digest()
    return base64.b64encode(ozet).decode("ascii")


def _ham_metin_kapanisi_var(metin: str, etiket: str) -> bool:
    """HTML raw-text öğesini gerçekten kapatabilecek sınırı yakalar."""
    desen = rf"</{re.escape(etiket)}(?=[\t\n\f\r />])"
    return re.search(desen, metin, flags=re.I) is not None


def _csp_beklenen(scriptler: list[str]) -> dict[str, frozenset[str]]:
    hashler = [f"'sha256-{_script_ozeti(icerik)}'" for icerik in scriptler]
    if len(hashler) != 2 or len(set(hashler)) != 2:
        raise PaketHatasi("CSP için iki farklı inline script özeti gerekli.")
    return {
        "default-src": frozenset({"'none'"}),
        "script-src": frozenset({"'unsafe-eval'", *hashler}),
        "style-src": frozenset({"'unsafe-inline'"}),
        "img-src": frozenset({"data:"}),
        "connect-src": frozenset({"'none'"}),
        "font-src": frozenset({"'none'"}),
        "object-src": frozenset({"'none'"}),
        "base-uri": frozenset({"'none'"}),
        "form-action": frozenset({"'none'"}),
    }


def _csp_uret(scriptler: list[str]) -> str:
    beklenen = _csp_beklenen(scriptler)
    # Hash sırası scriptlerin belge sırasını izlesin; kalan tokenlerin sırası
    # sabittir. Validator kümelerle karşılaştırdığı için semantik sıralama
    # farklılıkları güvenlik sözleşmesini gevşetmez.
    script_hashleri = [f"'sha256-{_script_ozeti(kod)}'" for kod in scriptler]
    tokenler = {
        **beklenen,
        "script-src": (*script_hashleri, "'unsafe-eval'"),
    }
    return "; ".join(
        f"{ad} {' '.join(tokenler[ad])}"
        for ad in beklenen
    )


def _csp_cozumle(csp: str) -> dict[str, tuple[str, ...]]:
    """CSP'yi tekrarlı direktif/tokenleri sessizce yutmadan ayrıştırır."""
    direktifler: dict[str, tuple[str, ...]] = {}
    for ham in csp.split(";"):
        parcalar = ham.split()
        if not parcalar:
            raise PaketHatasi("CSP boş bir direktif içeriyor.")
        ad = parcalar[0].lower()
        tokenler = tuple(parcalar[1:])
        if ad in direktifler:
            raise PaketHatasi(f"CSP direktifi tekrarlandı: {ad}")
        if not tokenler:
            raise PaketHatasi(f"CSP direktifi tokensiz: {ad}")
        if len(tokenler) != len(set(tokenler)):
            raise PaketHatasi(f"CSP tokeni tekrarlandı: {ad}")
        direktifler[ad] = tokenler
    return direktifler


def html_uret(javascript: str) -> str:
    """Kaynak HTML'yi bütün bağımlılıkları gömülü masaüstü HTML'ine çevirir."""
    html = GIRIS_HTML.read_text(encoding="utf-8").replace("\r\n", "\n")
    css = _css_birlestir()
    if _ham_metin_kapanisi_var(javascript, "script"):
        raise PaketHatasi("JavaScript paketi güvenli biçimde HTML içine gömülemiyor.")

    bootstrap_icerigi = "\n" + BRIDGE_BOOTSTRAP + "\n"
    script_icerigi = "\n" + javascript.rstrip() + "\n"
    scriptler = [bootstrap_icerigi, script_icerigi]
    # Pywebview, expose edilen Python çağrılarının sonucunu sayfa bağlamına
    # aktarırken kontrollü eval kullanır. Inline kod yine yalnız iki hash ile
    # sınırlıdır; connect-src bütün ağ erişimini kapalı tutar.
    csp = _csp_uret(scriptler)
    meta = (
        '<meta name="dap-transport" content="bridge">\n'
        f'<meta name="dap-capability" content="{CAPABILITY_PLACEHOLDER}">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        "<script>" + bootstrap_icerigi + "</script>"
    )
    html = _tam_degistir(
        html,
        '<meta charset="utf-8">',
        '<meta charset="utf-8">\n' + meta,
    )
    html = _tam_degistir(
        html,
        '<link rel="icon" type="image/png" href="/piton-favicon.png">',
        '<link rel="icon" type="image/png" href="'
        + _veri_uri(FAVICON, "image/png")
        + '">',
    )
    css_linkleri = "\n".join(
        f'<link rel="stylesheet" href="/css/{yol.name}">' for yol in CSS_DOSYALARI
    )
    html = _tam_degistir(html, css_linkleri, "<style>\n" + css + "</style>")
    html = _tam_degistir(
        html,
        'src="/piton-logo.svg"',
        'src="' + _veri_uri(LOGO, "image/svg+xml") + '"',
        adet=2,
    )
    html = _tam_degistir(
        html,
        '<script type="module" src="/js/app.js"></script>',
        "<script>" + script_icerigi + "</script>",
    )
    html = _tam_degistir(
        html,
        "<!DOCTYPE html>",
        "<!DOCTYPE html>\n<!-- tools/masaustu_paketi.py tarafından üretildi; elle düzenlemeyin. -->",
    )
    return html.rstrip() + "\n"


def _scriptleri_ayir(html: str) -> list[str]:
    return re.findall(r"<script(?:\s[^>]*)?>(.*?)</script\s*>", html, flags=re.I | re.S)


def _data_uri_coz(uri: str, mime: str) -> bytes:
    onek = f"data:{mime};base64,"
    if not uri.startswith(onek):
        raise PaketHatasi(f"Beklenmeyen data URI türü; {mime} gerekli.")
    try:
        return base64.b64decode(uri[len(onek):], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PaketHatasi(f"Geçersiz {mime} data URI.") from exc


def html_dogrula(html: str) -> None:
    """Artefaktın dosya/ağ yüklemesine ihtiyaç duymadığını doğrular."""
    denetleyici = _HtmlDenetleyici()
    try:
        denetleyici.feed(html)
        denetleyici.close()
    except Exception as exc:
        raise PaketHatasi(f"Üretilen HTML ayrıştırılamadı: {exc}") from exc

    if denetleyici.tasima != ["bridge"]:
        raise PaketHatasi("Masaüstü taşıma işareti eksik veya birden fazla.")
    if len(denetleyici.capability) != 1:
        raise PaketHatasi("Tek bir dap-capability meta etiketi gerekli.")
    capability = denetleyici.capability[0]
    if (capability != CAPABILITY_PLACEHOLDER
            and not CAPABILITY_DESENI.fullmatch(capability)):
        raise PaketHatasi(
            "dap-capability placeholder veya 43 karakter URL-safe token olmalı."
        )
    if len(denetleyici.csp) != 1:
        raise PaketHatasi("Tek bir Content-Security-Policy meta etiketi gerekli.")
    if denetleyici.meta_refresh_sayisi:
        raise PaketHatasi("Meta refresh masaüstü artefaktında yasaktır.")
    if denetleyici.tekrarli_nitelikler:
        bulunan = ", ".join(
            f"<{tag}> {ad}" for tag, ad in denetleyici.tekrarli_nitelikler)
        raise PaketHatasi("Tekrarlı HTML niteliği bulundu: " + bulunan)
    if denetleyici.yasakli_nitelikler:
        bulunan = ", ".join(
            f"<{tag}> {ad}" for tag, ad in denetleyici.yasakli_nitelikler)
        raise PaketHatasi("Ağ veya gömülü kaynak niteliği yasak: " + bulunan)
    if denetleyici.style_sayisi != 1:
        raise PaketHatasi("Üç CSS kaynağı tek bir inline style içinde olmalı.")
    if len(denetleyici.script_nitelikleri) != 2:
        raise PaketHatasi("Bootstrap ve uygulama için iki inline script bulunmalı.")
    for nitelikler in denetleyici.script_nitelikleri:
        if nitelikler.get("src") or nitelikler.get("type", "").lower() == "module":
            raise PaketHatasi("Masaüstü script'leri inline ve klasik olmalı.")

    gecersiz_url = []
    for tag, ad, deger, _ in denetleyici.url_nitelikleri:
        if not deger or deger.startswith("#") or deger.startswith("data:"):
            continue
        gecersiz_url.append(f"<{tag}> {ad}={deger!r}")
    if gecersiz_url:
        raise PaketHatasi(
            "Dış veya yerel dosya referansı kaldı: " + ", ".join(gecersiz_url)
        )

    data_nitelikleri = denetleyici.data_nitelikleri
    faviconlar = [
        (deger, nitelikler)
        for tag, ad, deger, nitelikler in data_nitelikleri
        if tag == "link" and ad == "href"
        and nitelikler.get("rel", "").strip().lower() == "icon"
        and nitelikler.get("type", "").strip().lower() == "image/png"
    ]
    logolar = [
        deger for tag, ad, deger, _ in data_nitelikleri
        if tag == "img" and ad == "src"
    ]
    if len(data_nitelikleri) != 3 or len(faviconlar) != 1 or len(logolar) != 2:
        raise PaketHatasi(
            "Yalnız bir PNG favicon ve iki SVG logo data URI'sine izin verilir."
        )
    if _data_uri_coz(faviconlar[0][0], "image/png") != FAVICON.read_bytes():
        raise PaketHatasi("Gömülü favicon kaynak PNG ile eşleşmiyor.")
    for logo in logolar:
        if _data_uri_coz(logo, "image/svg+xml") != LOGO.read_bytes():
            raise PaketHatasi("Gömülü logo kaynak SVG ile eşleşmiyor.")

    scriptler = _scriptleri_ayir(html)
    if len(scriptler) != 2:
        raise PaketHatasi("Bootstrap ve JavaScript paketi ayrıştırılamadı.")
    bootstrap, script = scriptler
    if bootstrap.strip() != BRIDGE_BOOTSTRAP:
        raise PaketHatasi("Bridge bootstrap uygulama paketinden önce kurulmadı.")
    if ("__PANEL_TRANSPORT__" not in script or '"bridge"' not in script
            or "__PANEL_CAPABILITY__" not in script):
        raise PaketHatasi(
            "Uygulama paketi bridge taşıma/yetenek işaretini kullanmıyor.")
    if any(re.search(r"(?m)^\s*(?:import|export)\s", kod)
           for kod in scriptler):
        raise PaketHatasi("JavaScript paketinde import/export ifadesi kaldı.")
    if any(re.search(r"(?i)\bdata:", kod) for kod in scriptler):
        raise PaketHatasi("Inline JavaScript içinde beklenmeyen data URI kaldı.")
    # Tarayıcı kipiyle ortak kaynak grafiğinde HTTP adaptörü de bulunur.
    # Bootstrap bridge dalını paketten önce seçer; CSP'nin connect-src
    # yasağı ise bir regresyonda fetch'e düşülmesini fail-closed yapar.

    if re.search(r"@import\b", html, flags=re.I):
        raise PaketHatasi("Inline CSS içinde @import kaldı.")
    for eslesme in re.finditer(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", html,
                              flags=re.I | re.S):
        hedef = eslesme.group(2).strip()
        if hedef:
            raise PaketHatasi(f"Inline CSS kaynak URI'si kullanıyor: {hedef!r}")

    beklenen_csp = _csp_beklenen(scriptler)
    bulunan_csp = _csp_cozumle(denetleyici.csp[0])
    if set(bulunan_csp) != set(beklenen_csp):
        eksik = sorted(set(beklenen_csp) - set(bulunan_csp))
        fazla = sorted(set(bulunan_csp) - set(beklenen_csp))
        raise PaketHatasi(
            f"CSP direktif kümesi geçersiz; eksik={eksik}, fazla={fazla}."
        )
    for ad, beklenen_tokenler in beklenen_csp.items():
        bulunan_tokenler = frozenset(bulunan_csp[ad])
        if bulunan_tokenler != beklenen_tokenler:
            raise PaketHatasi(
                f"CSP {ad} token kümesi geçersiz: {sorted(bulunan_tokenler)}"
            )


def artefakt_uret() -> str:
    deno = deno_bul()
    html = html_uret(javascript_paketle(deno))
    html_dogrula(html)
    return html


def _atomik_yaz(yol: Path, metin: str) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici_ad = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=yol.parent,
            prefix=f".{yol.name}.",
            suffix=".tmp",
            delete=False,
        ) as gecici:
            gecici.write(metin)
            gecici_ad = gecici.name
        # NamedTemporaryFile Unix'te 0600 oluşturur. Takip edilen üretim
        # artefaktı kaynak dosyaları gibi bütün kullanıcılarca okunabilsin.
        Path(gecici_ad).chmod(0o644)
        os.replace(gecici_ad, yol)
    finally:
        if gecici_ad:
            try:
                Path(gecici_ad).unlink(missing_ok=True)
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="HTTP'siz pywebview arayüzünü tek HTML olarak üretir."
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="dosya yazmadan static/masaustu.html artefaktının güncel olduğunu doğrula",
    )
    secenek = ap.parse_args(argv)
    try:
        beklenen = artefakt_uret()
        if secenek.check:
            if not CIKTI.is_file():
                raise PaketHatasi(
                    f"{CIKTI.relative_to(KOK)} yok; önce "
                    "`python3 tools/masaustu_paketi.py` çalıştırın."
                )
            mevcut = CIKTI.read_text(encoding="utf-8")
            if mevcut != beklenen:
                raise PaketHatasi(
                    f"{CIKTI.relative_to(KOK)} güncel değil; "
                    "`python3 tools/masaustu_paketi.py` ile yeniden üretin."
                )
            print(f"[OK] {CIKTI.relative_to(KOK)} güncel ve doğrulandı.")
            return 0

        _atomik_yaz(CIKTI, beklenen)
        print(f"[OK] {CIKTI.relative_to(KOK)} üretildi ({len(beklenen.encode('utf-8'))} bayt).")
        return 0
    except PaketHatasi as exc:
        print(f"[HATA] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
