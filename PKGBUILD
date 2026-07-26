# Maintainer: afkaral
pkgname=music-downloader
pkgver=1.0.0
pkgrel=1
pkgdesc="Simple YouTube music downloader with Picard tagging and m3u playlist support"
arch=('any')
url="https://github.com/afkaral/yt-music-downloader"
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

# package() $startdir'dan (repo kökü) DEĞİL, izole $srcdir'dan okumalı.
# prepare() burada repoyu build dizinine kopyalayıp asıl kaynağı hiç
# elleşmeden bırakıyor - makepkg -c ile src/ silinse bile repo etkilenmez.
prepare() {
    rm -rf "$srcdir/$pkgname"
    mkdir -p "$srcdir/$pkgname"
    cp -r "$startdir/src" "$srcdir/$pkgname/src"
    cp -r "$startdir/assets" "$srcdir/$pkgname/assets"
    cp "$startdir/LICENSE" "$srcdir/$pkgname/LICENSE"
}

package() {
    cd "$srcdir/$pkgname"

    # src/ altındaki her .py dosyasını (alt klasörler dahil) yapıyı
    # koruyarak kopyala - düz glob (*.py) alt klasörleri sessizce atlar
    install -d "$pkgdir/usr/lib/$pkgname"
    cp -r src/. "$pkgdir/usr/lib/$pkgname/"
    find "$pkgdir/usr/lib/$pkgname" -type f -exec chmod 644 {} \;
    find "$pkgdir/usr/lib/$pkgname" -type d -exec chmod 755 {} \;

    install -d "$pkgdir/usr/bin"
    cat > "$pkgdir/usr/bin/$pkgname" << 'WRAPPER'
#!/bin/sh
exec python3 /usr/lib/music-downloader/main.py "$@"
WRAPPER
    chmod 755 "$pkgdir/usr/bin/$pkgname"

    install -Dm644 assets/music-downloader.desktop \
        "$pkgdir/usr/share/applications/$pkgname.desktop"
    install -Dm644 assets/music-downloader.png \
        "$pkgdir/usr/share/icons/hicolor/256x256/apps/$pkgname.png"
    install -Dm644 LICENSE \
        "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
