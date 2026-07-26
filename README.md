# Music Downloader

Basit bir YouTube müzik arama ve indirme uygulaması.(AI yardımıyla yapıldı.)

Amaç; terminal kullanmadan şarkı aramak, dinlemek ve MP3 olarak indirmektir.

## Özellikler

- YouTube üzerinde arama
- Sonuçları listeleme
- MPV ile önizleme
- MP3 indirme (yt-dlp + ffmpeg)
- Kapak resmi ekleme
- Metadata gömme
- İndirme klasörü seçebilme
- M3U playlist dosyasını otomatik güncelleme
- İndirilen dosyayı MusicBrainz Picard ile açma

## Gereksinimler

- Python 3.11+
- PySide6
- yt-dlp
- ffmpeg
- mpv
- Picard

Arch Linux:

```bash
sudo pacman -S python python-pyside6 ffmpeg mpv picard yt-dlp
```

## Çalıştırma

```bash
python src/main.py
```

## Lisans

MIT