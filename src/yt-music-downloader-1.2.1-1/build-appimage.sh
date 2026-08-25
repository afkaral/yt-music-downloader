#!/bin/bash
# Build AppImage for universal Linux distribution

set -e

APP_NAME="MusicDownloader"
VERSION=$(cat VERSION 2>/dev/null | tr -d '\r\n' || echo "1.2.1")
APPDIR="${APP_NAME}.AppDir"
OUTPUT_NAME="${APP_NAME}-${VERSION}-x86_64.AppImage"

echo "Building ${OUTPUT_NAME}..."

# Clean previous build
rm -rf "$APPDIR" "$OUTPUT_NAME"
mkdir -p "$APPDIR"

# Create directory structure
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/lib/music-downloader"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy source files
cp src/*.py "$APPDIR/usr/lib/music-downloader/"

# Create launcher script
cat > "$APPDIR/usr/bin/music-downloader" << 'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
exec python3 "$HERE/../lib/music-downloader/main.py" "$@"
EOF
chmod 755 "$APPDIR/usr/bin/music-downloader"

# Copy desktop file and icon
cp assets/music-downloader.desktop "$APPDIR/"
cp assets/music-downloader.desktop "$APPDIR/usr/share/applications/"
cp assets/music-downloader.png "$APPDIR/"
cp assets/music-downloader.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/"

# Create AppRun
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="$HERE/usr/bin:$PATH"
exec "$HERE/usr/bin/music-downloader" "$@"
EOF
chmod 755 "$APPDIR/AppRun"

# Download appimagetool if not exists
if [ ! -f "appimagetool-x86_64.AppImage" ]; then
    echo "Downloading appimagetool..."
    wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool-x86_64.AppImage
fi

# Fix FUSE library loading issue
export LD_LIBRARY_PATH="/usr/lib:/lib:/usr/lib64:$LD_LIBRARY_PATH"

# Build AppImage with explicit library path
ARCH=x86_64 env LD_LIBRARY_PATH="/usr/lib:/lib:/usr/lib64:$LD_LIBRARY_PATH" ./appimagetool-x86_64.AppImage "$APPDIR" "$OUTPUT_NAME"

echo "AppImage successfully built: $OUTPUT_NAME"
