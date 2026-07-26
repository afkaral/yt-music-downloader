# Youtube Music Downloader

Basic music downloader with youtube search.(Made with AI assistant.)

Purpose; search, listen and download songs with gui.

## Features

- Search on Youtube
- Lists results
- Preview with MPV
- MP3 download (yt-dlp + ffmpeg)
- Fetch cover from youtube video
- Metadata inject
- Choose download path
- Make and refresh m3u file after tag
- Tag downloaded file with MusicbrainzPicard

## Requirements

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

## Run or install

```bash
python src/main.py
```

installation:

```bash
makepkg -si
```

## Licanse

MIT
