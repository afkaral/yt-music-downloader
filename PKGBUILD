pkgname=music-downloader
pkgver=1.0.0
pkgrel=1
pkgdesc="Simple YouTube music downloader with Picard tagging and m3u playlist support"
arch=('any')
license=('MIT')
depends=(
    python
    pyside6
    yt-dlp
    ffmpeg
    mpv
    picard
)
source=()
sha256sums=()

package() {
    install -d "$pkgdir/usr/lib/music-downloader"
    install -Dm644 -t "$pkgdir/usr/lib/music-downloader" "$startdir"/src/*.py

    install -d "$pkgdir/usr/bin"
    cat > "$pkgdir/usr/bin/music-downloader" << 'WRAPPER'
#!/bin/sh
exec python3 /usr/lib/music-downloader/main.py "$@"
WRAPPER
    chmod 755 "$pkgdir/usr/bin/music-downloader"

    install -Dm644 "$startdir/assets/music-downloader.desktop" \
        "$pkgdir/usr/share/applications/music-downloader.desktop"
    install -Dm644 "$startdir/assets/music-downloader.png" \
        "$pkgdir/usr/share/icons/hicolor/256x256/apps/music-downloader.png"
}
