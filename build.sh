#!/bin/bash
# Build script: PyInstaller → post-process → DMG
# Usage:
#   ./build.sh              # Build current version
#   ./build.sh bump         # Auto-increment patch version, then build
#   ./build.sh bump-minor   # Auto-increment minor version, then build

set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Desktop Downloader"
VERSION_FILE="app/__init__.py"

# ── Version bump ──
if [[ "${1:-}" == "bump" || "${1:-}" == "bump-minor" ]]; then
    current=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$VERSION_FILE")
    IFS='.' read -r major minor patch <<< "$current"
    if [[ "${1:-}" == "bump-minor" ]]; then
        minor=$((minor + 1))
        patch=0
    else
        patch=$((patch + 1))
    fi
    new_ver="$major.$minor.$patch"
    sed -i '' "s/__version__ = \"$current\"/__version__ = \"$new_ver\"/" "$VERSION_FILE"
    echo "Version bumped: $current → $new_ver"
fi

version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$VERSION_FILE")
echo "=== Building $APP_NAME v$version ==="

# ── Clean ──
rm -rf build dist *.spec __pycache__

# ── Generate spec ──
echo ">>> Generating spec..."
pyi-makespec \
    --name "$APP_NAME" \
    --windowed \
    --onefile \
    --add-data "bin/ffmpeg:bin" \
    --icon /tmp/DesktopDownloader.icns \
    --hidden-import "PySide6.QtSvg" \
    --hidden-import "PySide6.QtSvgWidgets" \
    --hidden-import "PySide6.QtMultimedia" \
    --hidden-import "PySide6.QtMultimediaWidgets" \
    --hidden-import "PySide6.QtXml" \
    --hidden-import "bilibili_api" \
    --hidden-import "bilibili_api.video" \
    --hidden-import "bilibili_api.user" \
    --hidden-import "bilibili_api.search" \
    --hidden-import "bilibili_api.clients" \
    --hidden-import "bilibili_api.clients.HTTPXClient" \
    --hidden-import "bilibili_api.exceptions" \
    main.py 2>/dev/null || true

# ── Inject excludes and BUNDLE config into spec ──
# Use the pre-crafted spec if available, otherwise patch the generated one
if [[ -f "Desktop Downloader.spec" ]]; then
    echo ">>> Using existing spec"
else
    echo ">>> Generating default spec"
    pyinstaller --windowed --onefile \
        --name "$APP_NAME" \
        --add-data "bin/ffmpeg:bin" \
        --icon /tmp/DesktopDownloader.icns \
        --noconfirm \
        main.py 2>/dev/null || true
fi

# ── Build ──
echo ">>> Running PyInstaller..."
pyinstaller --noconfirm "Desktop Downloader.spec" 2>&1 | tail -5

# ── Post-process ──
if [[ -f "post_process.sh" ]]; then
    echo ">>> Post-processing..."
    bash post_process.sh
fi

# ── Create DMG ──
APP_BUNDLE="dist/$APP_NAME.app"
if [[ -d "$APP_BUNDLE" ]]; then
    echo ">>> Creating DMG..."
    DMG_NAME="$APP_NAME-$version.dmg"
    DMG_PATH="dist/$DMG_NAME"
    # Create temporary DMG
    temp_dmg="/tmp/${APP_NAME}_tmp.dmg"
    temp_dir="/tmp/${APP_NAME}_dmg"
    rm -rf "$temp_dir" "$temp_dmg"
    mkdir -p "$temp_dir"
    cp -R "$APP_BUNDLE" "$temp_dir/"
    ln -s /Applications "$temp_dir/Applications"

    hdiutil create -megabytes 512 -fs HFS+ \
        -volname "$APP_NAME" \
        -srcfolder "$temp_dir" \
        -format UDRW \
        "$temp_dmg" -quiet

    # Set volume icon and background
    # (Icon file at /tmp/DesktopDownloader.icns is used by the app itself)

    # Convert to compressed DMG
    hdiutil convert "$temp_dmg" -format UDZO -imagekey zlib-level=9 \
        -o "$DMG_PATH" -quiet
    rm -f "$temp_dmg"
    rm -rf "$temp_dir"

    echo "=== Done: $DMG_PATH ==="
    du -sh "$DMG_PATH"
    du -sh "$APP_BUNDLE"
fi
