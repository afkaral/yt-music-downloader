pkgname=music-downloader
pkgver=1.2.1
pkgrel=1
pkgdesc="YouTube music downloader with automatic MusicBrainz tagging and playlist support"
arch=('any')
url="https://github.com/afkaral/yt-music-downloader"
license=('GPL-3.0-or-later')
depends=(
    python
    pyside6
    python-requests
    python-mutagen
    yt-dlp
    ffmpeg
    mpv
    chromaprint
)
source=("${url}/archive/refs/tags/v${pkgver}-${pkgrel}.tar.gz")
sha256sums=('90f78a270115b7bf8ae040ee238ea5ac47bf7afcb094aab62734a22d35153c30')  # replace with real checksum after first successful build
package() {
    # $srcdir contains the extracted tarball
    cd "$srcdir/yt-music-downloader-${pkgver}-${pkgrel}"

    # Python modules
    install -d "$pkgdir/usr/lib/music-downloader"
    install -m644 src/*.py "$pkgdir/usr/lib/music-downloader/"

    # Wrapper executable in $PATH
    install -d "$pkgdir/usr/bin"
    cat > "$pkgdir/usr/bin/music-downloader" << 'WRAPPER'
#!/bin/sh
exec python3 /usr/lib/music-downloader/main.py "$@"
WRAPPER
    chmod 755 "$pkgdir/usr/bin/music-downloader"

    # Desktop entry & icon (assumes assets/ exists in the repo)
    install -Dm644 assets/music-downloader.desktop "$pkgdir/usr/share/applications/music-downloader.desktop"
    install -Dm644 assets/music-downloader.png "$pkgdir/usr/share/icons/hicolor/256x256/apps/music-downloader.png"
}

