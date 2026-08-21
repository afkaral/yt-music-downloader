#!/bin/bash
# Build AppImage for universal Linux distribution

set -e

APP_NAME="MusicDownloader"
VERSION="1.2.0"
APPDIR="${APP_NAME}.AppDir"

echo "Building ${APP_NAME}-${VERSION}-x86_64.AppImage..."

# Clean previous build
rm -rf "$APPDIR"
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

# Copy desktop file
cp assets/music-downloader.desktop "$APPDIR/"
cp assets/music-downloader.desktop "$APPDIR/usr/share/applications/"

# Copy icon
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

# Build AppImage
ARCH=x86_64 ./appimagetool-x86_64.AppImage "$APPDIR" "${APP_NAME}-${VERSION}-x86_64.AppImage"

echo "AppImage built: ${APP_NAME}-${VERSION}-x86_64.AppImage"
echo "Run with: ./${APP_NAME}-${VERSION}-x86_64.AppImage"
echo ""
echo "Note: You still need to install dependencies:"
echo "  Ubuntu/Debian: sudo apt install python3-pyside6.qtwidgets python3-requests python3-mutagen yt-dlp ffmpeg mpv libchromaprint-tools"
echo "  Fedora: sudo dnf install python3-pyside6 python3-requests python3-mutagen yt-dlp ffmpeg mpv chromaprint-tools"
echo "  Arch: sudo pacman -S python-pyside6 python-requests python-mutagen yt-dlp ffmpeg mpv chromaprint"
