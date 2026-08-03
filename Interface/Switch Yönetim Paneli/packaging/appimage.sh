#!/usr/bin/env bash
# PyInstaller onedir çıktısından AppImage üretir.
#
#   ./packaging/appimage.sh <dist_dizini> <cikti.AppImage> <surum>
#
# Örnek:
#   ./packaging/appimage.sh dist/SwitchYonetimPaneli \
#       release/SwitchYonetimPaneli-1.0.1-linux-x86_64.AppImage 1.0.1
#
# appimagetool sürümü sabittir (aşağıdaki APPIMAGETOOL_SURUM). Bir sha256
# verirsen indirilen dosya doğrulanır; vermezsen indirilenin sha256'sı
# ekrana yazılır — onu APPIMAGETOOL_SHA256'ya koyup sabitle.
set -euo pipefail

DIST_DIZINI="${1:?dist dizini gerekli}"
CIKTI="${2:?çıktı dosyası gerekli}"
SURUM="${3:-0.0.0}"

BURASI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UYGULAMA_KOK="$(cd "$BURASI/.." && pwd)"

APPIMAGETOOL_SURUM="1.9.1"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_SURUM}/appimagetool-x86_64.AppImage"
# Boşsa yalnızca uyarı verilir; doldurulunca zorunlu doğrulama yapılır.
APPIMAGETOOL_SHA256="${APPIMAGETOOL_SHA256:-}"

CALISMA="$(mktemp -d)"
temizle() { rm -rf "$CALISMA"; }
trap temizle EXIT

APPDIR="$CALISMA/AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"

echo "==> AppDir kuruluyor"
cp -a "$DIST_DIZINI/." "$APPDIR/usr/bin/"
test -x "$APPDIR/usr/bin/SwitchYonetimPaneli" \
  || chmod +x "$APPDIR/usr/bin/SwitchYonetimPaneli"

# .desktop — AppImage için zorunlu
cat > "$APPDIR/usr/share/applications/switchyonetimpaneli.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Switch Yonetim Paneli
GenericName=Switch Management Panel
Comment=KYLAND switch yonetim paneli
Exec=SwitchYonetimPaneli
Icon=switchyonetimpaneli
Categories=Network;System;
Terminal=false
DESKTOP
cp "$APPDIR/usr/share/applications/switchyonetimpaneli.desktop" "$APPDIR/"

# İkon — yoksa build durmaz, AppImage ikonsuz üretilir
IKON="$UYGULAMA_KOK/icons/app.png"
if [ -f "$IKON" ]; then
  cp "$IKON" "$APPDIR/usr/share/icons/hicolor/256x256/apps/switchyonetimpaneli.png"
  cp "$IKON" "$APPDIR/switchyonetimpaneli.png"
else
  echo "!! ikon bulunamadı ($IKON) — AppImage ikonsuz üretiliyor"
fi

# AppRun — AppImage açılışında çalışan giriş noktası
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
KOK="$(dirname "$(readlink -f "$0")")"
exec "$KOK/usr/bin/SwitchYonetimPaneli" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

ARAC="$CALISMA/appimagetool"
if [ -n "${APPIMAGETOOL_BIN:-}" ]; then
  # Elde hazır araç varsa indirme yapma (çevrimdışı build / test).
  echo "==> hazır appimagetool kullanılıyor: $APPIMAGETOOL_BIN"
  cp "$APPIMAGETOOL_BIN" "$ARAC"
else
  echo "==> appimagetool ${APPIMAGETOOL_SURUM} indiriliyor"
  curl -fsSL --retry 3 -o "$ARAC" "$APPIMAGETOOL_URL"
fi
GERCEK="$(sha256sum "$ARAC" | cut -d' ' -f1)"
if [ -n "$APPIMAGETOOL_SHA256" ]; then
  if [ "$GERCEK" != "$APPIMAGETOOL_SHA256" ]; then
    echo "!! appimagetool sha256 uyuşmuyor"
    echo "   beklenen: $APPIMAGETOOL_SHA256"
    echo "   gelen   : $GERCEK"
    exit 1
  fi
  echo "   sha256 doğrulandı"
else
  echo "!! APPIMAGETOOL_SHA256 boş — doğrulama yapılmadı."
  echo "   Sabitlemek için bu değeri kullan: $GERCEK"
fi
chmod +x "$ARAC"

echo "==> AppImage üretiliyor"
mkdir -p "$(dirname "$CIKTI")"
# CI'da FUSE yok: appimagetool'u kendi içeriğini açarak çalıştırıyoruz.
ARCH=x86_64 "$ARAC" --appimage-extract-and-run \
  "$APPDIR" "$CIKTI"

chmod +x "$CIKTI"
echo "==> hazır: $CIKTI ($(du -h "$CIKTI" | cut -f1))"
