#!/bin/bash
# Build .deb package for Debian/Ubuntu

set -e

PKG_NAME="music-downloader"
VERSION=$(cat VERSION 2>/dev/null || echo "1.2.0")
ARCH="all"
BUILD_DIR="debian"

echo "Building ${PKG_NAME}_${VERSION}_${ARCH}.deb..."

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/DEBIAN"

# Create directory structure
mkdir -p "$BUILD_DIR/usr/lib/music-downloader"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$BUILD_DIR/usr/share/doc/music-downloader"

# Copy source files
cp src/*.py "$BUILD_DIR/usr/lib/music-downloader/"

# Create launcher script
cat > "$BUILD_DIR/usr/bin/music-downloader" << 'EOF'
#!/bin/sh
exec python3 /usr/lib/music-downloader/main.py "$@"
EOF
chmod 755 "$BUILD_DIR/usr/bin/music-downloader"

# Copy desktop file and icon
cp assets/music-downloader.desktop "$BUILD_DIR/usr/share/applications/"
cp assets/music-downloader.png "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps/"

# Copy documentation
cp README.md "$BUILD_DIR/usr/share/doc/music-downloader/"
cp LICENSE "$BUILD_DIR/usr/share/doc/music-downloader/"

# Create control file
cat > "$BUILD_DIR/DEBIAN/control" << EOF
Package: music-downloader
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.11), python3-pyside6.qtwidgets, python3-requests, python3-mutagen, yt-dlp, ffmpeg, mpv, libchromaprint-tools
Maintainer: afkaral <afkaral@github.com>
Description: YouTube music downloader with MusicBrainz tagging
 Modern music downloader with YouTube search and automatic metadata tagging.
 Features:
  - YouTube search integration
  - High-quality MP3 download (320kbps)
  - Automatic MusicBrainz metadata tagging
  - AcoustID fingerprinting
  - Album artwork support
  - Smart playlist management
Homepage: https://github.com/afkaral/yt-music-downloader
EOF

# Build package
dpkg-deb --build "$BUILD_DIR" "${PKG_NAME}_${VERSION}_${ARCH}.deb"

echo "Package built: ${PKG_NAME}_${VERSION}_${ARCH}.deb"
echo "Install with: sudo dpkg -i ${PKG_NAME}_${VERSION}_${ARCH}.deb"
echo "             sudo apt-get install -f  # to fix dependencies"
