#!/usr/bin/env bash
# build_app.sh — Build the complete Sathgen Dashboard desktop app
# Usage: ./build_app.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.cargo/bin:$HOME/Library/Python/3.9/bin:$PATH"

echo "▶ Step 1: Build Python bundle with PyInstaller (clean build)..."
chmod -R u+w build/ dist/ 2>/dev/null || true
rm -rf build/ dist/
pyinstaller -y sathgendashboard.spec
echo "  ✓ Python bundle built: dist/sathgendashboard/"

echo ""
echo "▶ Step 2: Build Tauri Rust shell (no Python resources)..."
rm -rf src-tauri/sathgendashboard-bin
cp -r dist/sathgendashboard src-tauri/sathgendashboard-bin
(cd src-tauri && cargo tauri build 2>&1 | grep -E "Compiling|Finished|Bundling|Error|error" | tail -6)
echo "  ✓ Tauri shell compiled"

# Locate the Tauri-built .app — check known cargo target locations first.
TAURI_APP=""
CARGO_TARGET="$(cd src-tauri && cargo metadata --no-deps --format-version 1 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['target_directory'])" 2>/dev/null)"
SANDBOX_TARGET="/var/folders/mh/fqg3v7yn1y538bqtyl28_35r0000gn/T/cursor-sandbox-cache/699536e77528ae1fd82f92108e3cfa33/cargo-target"
for candidate in \
    "$CARGO_TARGET/release/bundle/macos/SathgenDashboard.app" \
    "$CARGO_TARGET/release/bundle/macos/Sathgendashboard.app" \
    "$SANDBOX_TARGET/release/bundle/macos/SathgenDashboard.app" \
    "$SANDBOX_TARGET/release/bundle/macos/Sathgendashboard.app" \
    "src-tauri/target/release/bundle/macos/SathgenDashboard.app" \
    "src-tauri/target/release/bundle/macos/Sathgendashboard.app"
do
    if [ -d "$candidate" ]; then
        TAURI_APP="$candidate"
        break
    fi
done

if [ -z "$TAURI_APP" ]; then
    echo "ERROR: Could not locate Tauri-built SathgenDashboard.app" >&2
    exit 1
fi
echo "  ✓ Found bundle at: $TAURI_APP"

# Ensure the bundle is consistently named SathgenDashboard.app (Tauri may produce
# a differently-cased name when it uses a cached binary from an older productName setting).
if [[ "$TAURI_APP" == *"/Sathgendashboard.app" ]]; then
    RENAMED_APP="${TAURI_APP%/Sathgendashboard.app}/SathgenDashboard.app"
    rm -rf "$RENAMED_APP"
    mv "$TAURI_APP" "$RENAMED_APP"
    TAURI_APP="$RENAMED_APP"
    echo "  ✓ Renamed bundle to SathgenDashboard.app"
fi

echo ""
echo "▶ Step 3: Inject Python bundle into app (preserving structure)..."
RESOURCES="$TAURI_APP/Contents/Resources"
rm -rf "$RESOURCES/sathgendashboard-bin"
rsync -a --exclude='*.pyc' dist/sathgendashboard/ "$RESOURCES/sathgendashboard-bin/"
echo "  ✓ Python bundle injected"

echo ""
echo "▶ Step 4: Make Python binary executable..."
chmod +x "$RESOURCES/sathgendashboard-bin/sathgendashboard"
echo "  ✓ Permissions set"

echo ""
echo "▶ Step 5: Signing deferred to DMG staging step (step 6) for validity after install..."
echo "  ✓ Skipped early sign"

echo ""
echo "▶ Step 6: Package into DMG..."
DMG_NAME="SathgenDashboard_1.0.0_aarch64.dmg"
rm -f "$SCRIPT_DIR/$DMG_NAME"
# Stage app + Applications symlink so users can drag-to-install
RW_DMG="$SCRIPT_DIR/godavari_rw.dmg"
DMG_STAGING=$(mktemp -d)
cp -r "$TAURI_APP" "$DMG_STAGING/SathgenDashboard.app"
# Sign AFTER copy so the signature covers the final bundle state
codesign --force --deep --sign - "$DMG_STAGING/SathgenDashboard.app" 2>&1 | head -2 || true
ln -s /Applications "$DMG_STAGING/Applications"

# Pre-populate background so it exists when the DMG is mounted
mkdir -p "$DMG_STAGING/.background"
cp "$SCRIPT_DIR/src-tauri/assets/dmg-background.png" "$DMG_STAGING/.background/bg.png"

# Build writable DMG, position icons via AppleScript, then compress
rm -f "$RW_DMG"
hdiutil create -srcfolder "$DMG_STAGING" -volname "Sathgen Dashboard" \
    -fs HFS+ -format UDRW -size 120m "$RW_DMG" 2>&1 | tail -1
DEVICE=$(hdiutil attach -readwrite -noverify "$RW_DMG" 2>&1 | awk 'END{print $1}')
sleep 2
osascript <<APPLESCRIPT
tell application "Finder"
  tell disk "Sathgen Dashboard"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set bounds of container window to {200, 120, 760, 440}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 80
    set background picture of viewOptions to file ".background:bg.png"
    set position of item "SathgenDashboard.app" to {140, 120}
    set position of item "Applications" to {420, 120}
    update without registering applications
    delay 3
    close
  end tell
end tell
APPLESCRIPT
sync
hdiutil detach "$DEVICE"
sleep 1
hdiutil convert "$RW_DMG" -format UDZO -imagekey zlib-level=9 \
    -o "$SCRIPT_DIR/$DMG_NAME" 2>&1 | tail -1
rm -f "$RW_DMG"
rm -rf "$DMG_STAGING"
echo "  ✓ DMG created: $DMG_NAME"

echo ""
echo "✅ Build complete!"
echo "   App:  $TAURI_APP"
echo "   DMG:  $SCRIPT_DIR/$DMG_NAME"
du -sh "$SCRIPT_DIR/$DMG_NAME"
