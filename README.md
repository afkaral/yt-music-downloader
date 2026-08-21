# YouTube Music Downloader

Download music from YouTube with automatic metadata tagging via MusicBrainz.

## Features

- YouTube search
- Preview with MPV/VLC
- High-quality MP3 downloads (320kbps)
- Automatic metadata tagging (artist, album, year, cover art)
- AcoustID fingerprinting for accurate song identification
- Original release date preservation
- Complete metadata (ISRC, Barcode, Label, MusicBrainz IDs)
- Optional M3U playlist generation

## Requirements

**System:** Python 3.11+, ffmpeg, mpv/vlc, yt-dlp, chromaprint (fpcalc)

**Python:** PySide6, requests, mutagen

## Installation

### Package Installation (Recommended)

**Arch Linux:**
```bash
makepkg -si
```

**Ubuntu/Debian:**
```bash
./build-deb.sh
sudo dpkg -i music-downloader_1.1.0_all.deb
sudo apt-get install -f
```

**Universal Linux (AppImage):**
```bash
./build-appimage.sh
chmod +x MusicDownloader-1.1.0-x86_64.AppImage
./MusicDownloader-1.1.0-x86_64.AppImage
```

### Run from Source

**Linux:**
```bash
# Arch
sudo pacman -S python-pyside6 python-requests python-mutagen ffmpeg mpv yt-dlp chromaprint

# Ubuntu/Debian
sudo apt install python3-pyside6.qtwidgets python3-requests python3-mutagen ffmpeg mpv yt-dlp libchromaprint-tools

# Fedora
sudo dnf install python3-pyside6 python3-requests python3-mutagen ffmpeg mpv yt-dlp chromaprint-tools

# Run
python3 src/main.py
```

**Windows:**
```cmd
pip install -r requirements.txt
python src\main.py
```

**macOS:**
```bash
brew install python@3.11 ffmpeg mpv yt-dlp chromaprint pyside@6
pip3 install requests mutagen
python3 src/main.py
```

## Configuration

Access via Settings button:

- **Download directory:** Where files are saved
- **Player:** mpv (default), vlc, celluloid, clementine
- **Search limit:** Results per search (5-200)
- **M3U playlist:** Auto-generate playlists (on/off)
- **AcoustID API key:** Optional custom key ([get free key](https://acoustid.org/api-key))

## How It Works

1. Search YouTube
2. Download audio (yt-dlp + ffmpeg)
3. Fingerprint audio (AcoustID)
4. Query metadata (MusicBrainz)
5. Tag file (Mutagen)
6. Update playlist (optional)

## License

MIT