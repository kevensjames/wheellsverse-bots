#!/usr/bin/env bash
# Package the built KaiDesktopBridge binary into a proper .app bundle.
#
# WHY THIS STEP EXISTS. macOS attributes a TCC grant (Screen Recording, Accessibility)
# to a bundle identified by its CFBundleIdentifier, and codesign derives the signing
# identifier from that same Info.plist key. A bare SwiftPM executable has no bundle
# identifier, so it can never hold a stable TCC grant. This assembles the bundle with the
# ONE reserved identifier the helper and the signing gate both require.
#
# It does NOT sign. Signing is the operator's step, with the operator's identity. An
# unsigned bundle produced here still FAILS verify_signing.sh (no signature, no Team ID),
# which is correct: packaging is necessary, not sufficient.
set -euo pipefail

HELPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ID="com.wheellsverse.kai.desktopbridge"
NAME="KaiDesktopBridge"
BIN="$HELPER_DIR/.build/release/$NAME"
OUT="${1:-$HELPER_DIR/dist/$NAME.app}"

[ -f "$BIN" ] || { echo "binary not built; run: (cd '$HELPER_DIR' && swift build -c release)"; exit 2; }

VERSION="$(grep -oE 'VERSION = "[^"]+"' "$HELPER_DIR/Sources/$NAME/main.swift" | head -1 | sed 's/.*"\([^"]*\)".*/\1/')"
VERSION="${VERSION:-0.1.0}"

rm -rf "$OUT"
mkdir -p "$OUT/Contents/MacOS"
cp "$BIN" "$OUT/Contents/MacOS/$NAME"

cat > "$OUT/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>       <string>$BUNDLE_ID</string>
    <key>CFBundleName</key>             <string>$NAME</string>
    <key>CFBundleDisplayName</key>      <string>KAI Desktop Bridge</string>
    <key>CFBundleExecutable</key>       <string>$NAME</string>
    <key>CFBundlePackageType</key>      <string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key>          <string>$VERSION</string>
    <key>LSMinimumSystemVersion</key>   <string>13.0</string>
    <key>LSUIElement</key>              <true/>
    <!-- Usage strings shown by macOS at the TCC prompt. Named narrowly on purpose. -->
    <key>NSAccessibilityUsageDescription</key>
        <string>KAI Desktop Bridge observes and interacts with approved application windows for authorized, scoped missions.</string>
    <key>NSScreenCaptureUsageDescription</key>
        <string>KAI Desktop Bridge captures approved application windows as mission evidence.</string>
</dict>
</plist>
PLIST

cat > "$OUT/Contents/PkgInfo" <<'PKG'
APPL????
PKG

echo "built unsigned bundle: $OUT"
echo "  CFBundleIdentifier = $BUNDLE_ID"
echo "  executable         = Contents/MacOS/$NAME"
echo
echo "NEXT (operator): sign it, then verify."
echo "  codesign --force --options runtime --timestamp --sign \"<Developer ID / Apple Development identity>\" \"$OUT\""
echo "  $HELPER_DIR/verify_signing.sh \"$OUT\"     # must exit 0 before any TCC grant"
