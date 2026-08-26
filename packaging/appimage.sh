#!/usr/bin/env bash
# Builds an AppImage from the PyInstaller onedir output — Commissioning and
# Maintenance Panel.
#
#   ./packaging/appimage.sh <dist_dir> <output.AppImage> <version> [name]
#
# Example:
#   ./packaging/appimage.sh dist/dabp-gdm \
#       release/dabp-gdm-1.0.0-linux-x86_64.AppImage 1.0.0 \
#       "Devreye Alma ve Bakim Paneli - GDM"
#
# The appimagetool version is pinned (APPIMAGETOOL_VERSION below). Give a
# sha256 and the download is verified; leave it empty and the sha256 of what
# was downloaded is printed — put that in APPIMAGETOOL_SHA256 to pin it.
set -euo pipefail

DIST_DIR="${1:?dist directory is required}"
OUTPUT="${2:?output file is required}"
VERSION="${3:-0.0.0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# PyInstaller's onedir output is dist/<name>/<name>: the directory and the
# executable inside it carry the same name, and that name is per edition now
# (dabp-vip-yatakli, dabp-gdm …). Derived rather than written down — the
# hard-coded "dabp" survived the split into packages and the Linux build
# died on `chmod: cannot access AppDir/usr/bin/dabp`.
APP_BINARY_NAME="$(basename "$DIST_DIR")"
# Per edition as well, so two packages installed side by side get a menu
# entry and an icon each instead of overwriting one another.
DESKTOP_ID="$APP_BINARY_NAME"
# What the menu entry says. Passed in by the build from the edition table;
# the fallback is the product without a customer, for a build by hand.
DISPLAY_NAME="${4:-Commissioning and Maintenance Panel}"

APPIMAGETOOL_VERSION="1.9.1"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
# When empty only a warning is printed; once filled in, verification is
# mandatory.
APPIMAGETOOL_SHA256="${APPIMAGETOOL_SHA256:-}"

WORK_DIR="$(mktemp -d)"
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

APPDIR="$WORK_DIR/AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"

echo "==> building the AppDir (version $VERSION)"
cp -a "$DIST_DIR/." "$APPDIR/usr/bin/"
test -x "$APPDIR/usr/bin/$APP_BINARY_NAME" \
  || chmod +x "$APPDIR/usr/bin/$APP_BINARY_NAME"

# .desktop — required by AppImage
cat > "$APPDIR/usr/share/applications/$DESKTOP_ID.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=$DISPLAY_NAME
GenericName=Commissioning Panel
Comment=Train set commissioning and verification panel
Exec=$APP_BINARY_NAME
Icon=$DESKTOP_ID
Categories=Network;System;
Terminal=false
DESKTOP
cp "$APPDIR/usr/share/applications/$DESKTOP_ID.desktop" "$APPDIR/"

# Icon. `icons/app.png` is the application's own, built from the logo by
# `tools/make_icons.py` and committed. The UI favicon stays as the fallback
# for a tree without it: appimagetool expects a file matching the Icon key
# in the .desktop file, and shipping none stops the build on some of its
# versions.
ICON="$APP_ROOT/icons/app.png"
if [ ! -f "$ICON" ]; then
  ICON="$APP_ROOT/static/piton-favicon.png"
  echo "!! icons/app.png is missing — using the UI favicon: $ICON"
fi
if [ -f "$ICON" ]; then
  cp "$ICON" "$APPDIR/usr/share/icons/hicolor/256x256/apps/$DESKTOP_ID.png"
  cp "$ICON" "$APPDIR/$DESKTOP_ID.png"
  # .DirIcon: the first place desktop environments look
  cp "$ICON" "$APPDIR/.DirIcon"
else
  echo "!! no icon found — building the AppImage without one"
fi

# AppRun — the entry point that runs when the AppImage starts
cat > "$APPDIR/AppRun" <<APPRUN
#!/bin/sh
APPDIR_ROOT="\$(dirname "\$(readlink -f "\$0")")"
exec "\$APPDIR_ROOT/usr/bin/$APP_BINARY_NAME" "\$@"
APPRUN
chmod +x "$APPDIR/AppRun"

TOOL="$WORK_DIR/appimagetool"
if [ -n "${APPIMAGETOOL_BIN:-}" ]; then
  # Skip the download when a tool is already at hand (offline build / test).
  echo "==> using the provided appimagetool: $APPIMAGETOOL_BIN"
  cp "$APPIMAGETOOL_BIN" "$TOOL"
else
  echo "==> downloading appimagetool ${APPIMAGETOOL_VERSION}"
  curl -fsSL --retry 3 -o "$TOOL" "$APPIMAGETOOL_URL"
fi
ACTUAL_SHA256="$(sha256sum "$TOOL" | cut -d' ' -f1)"
if [ -n "$APPIMAGETOOL_SHA256" ]; then
  if [ "$ACTUAL_SHA256" != "$APPIMAGETOOL_SHA256" ]; then
    echo "!! appimagetool sha256 mismatch"
    echo "   expected: $APPIMAGETOOL_SHA256"
    echo "   actual  : $ACTUAL_SHA256"
    exit 1
  fi
  echo "   sha256 verified"
else
  echo "!! APPIMAGETOOL_SHA256 is empty — nothing was verified."
  echo "   To pin it, use this value: $ACTUAL_SHA256"
fi
chmod +x "$TOOL"

echo "==> building the AppImage"
mkdir -p "$(dirname "$OUTPUT")"
# No FUSE on CI: appimagetool is run by extracting its own contents.
ARCH=x86_64 "$TOOL" --appimage-extract-and-run \
  "$APPDIR" "$OUTPUT"

chmod +x "$OUTPUT"
echo "==> ready: $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
