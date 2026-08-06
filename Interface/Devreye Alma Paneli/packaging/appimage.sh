#!/usr/bin/env bash
# PyInstaller onedir çıktısından AppImage üretir — Devreye Alma Paneli.
#
#   ./packaging/appimage.sh <dist_dizini> <cikti.AppImage> <surum>
#
# Örnek:
#   ./packaging/appimage.sh dist/DevreyeAlmaPaneli \
#       release/DevreyeAlmaPaneli-0.9.0-dev-linux-x86_64.AppImage 0.9.0-dev
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
test -x "$APPDIR/usr/bin/DevreyeAlmaPaneli" \
  || chmod +x "$APPDIR/usr/bin/DevreyeAlmaPaneli"

# .desktop — AppImage için zorunlu
cat > "$APPDIR/usr/share/applications/devreyealmapaneli.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Devreye Alma Paneli
GenericName=Commissioning Panel
Comment=Tren seti devreye alma ve dogrulama paneli
Exec=DevreyeAlmaPaneli
Icon=devreyealmapaneli
Categories=Network;System;
Terminal=false
DESKTOP
cp "$APPDIR/usr/share/applications/devreyealmapaneli.desktop" "$APPDIR/"

# İkon. Uygulamanın kendi ikonu (icons/app.png) henüz yok; o gelene kadar
# arayüzün favicon'u kullanılıyor. appimagetool .desktop içindeki Icon
# anahtarına karşılık bir dosya bekliyor; hiç ikon koymamak bazı
# sürümlerinde build'i durduruyor.
IKON="$UYGULAMA_KOK/icons/app.png"
if [ ! -f "$IKON" ]; then
  IKON="$UYGULAMA_KOK/static/piton-favicon.png"
  echo "!! icons/app.png yok — arayüz favicon'u kullanılıyor: $IKON"
fi
if [ -f "$IKON" ]; then
  cp "$IKON" "$APPDIR/usr/share/icons/hicolor/256x256/apps/devreyealmapaneli.png"
  cp "$IKON" "$APPDIR/devreyealmapaneli.png"
  # .DirIcon: masaüstü ortamlarının ilk baktığı yer
  cp "$IKON" "$APPDIR/.DirIcon"
else
  echo "!! ikon bulunamadı — AppImage ikonsuz üretiliyor"
fi

# AppRun — AppImage açılışında çalışan giriş noktası
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
KOK="$(dirname "$(readlink -f "$0")")"
exec "$KOK/usr/bin/DevreyeAlmaPaneli" "$@"
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
