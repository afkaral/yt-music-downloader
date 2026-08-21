# Youtube Music Downloader

Modern music downloader with YouTube search and automatic metadata tagging.

## Features

### Core Features
- YouTube search integration
- Preview songs with MPV/VLC
- High-quality MP3 download (320kbps)
- Automatic album artwork
- Smart playlist management (M3U)
- Configurable download path

### Advanced Tagging
- **Automatic metadata tagging** using MusicBrainz
- AcoustID fingerprinting for accurate song identification
- Original release date preservation
- Multiple cover art formats (PNG/JPEG)
- International metadata support
- Complete track information (ISRC, Barcode, Label)

### Supported Metadata
- Artist, Album, Title
- Track/Disc numbers
- Original release date (e.g., 1982 for Thriller)
- Recording date
- Publisher/Label
- ISRC codes
- Barcode
- MusicBrainz IDs
- AcoustID fingerprint

## Requirements

### System Packages
- Python 3.11+
- yt-dlp
- ffmpeg
- mpv or vlc
- libchromaprint-tools (fpcalc)

### Python Dependencies
- PySide6
- requests
- mutagen

### Arch Linux

```bash
sudo pacman -S python python-pyside6 ffmpeg mpv yt-dlp chromaprint
pip install requests mutagen
```

### Ubuntu/Debian

```bash
sudo apt install python3-pyside6.qtwidgets ffmpeg mpv yt-dlp libchromaprint-tools
pip3 install requests mutagen
```

## Installation

### Arch Linux (Recommended)

```bash
git clone https://github.com/afkaral/yt-music-downloader.git
cd yt-music-downloader/
makepkg -si
```

This installs the application system-wide with a desktop entry.

### Ubuntu/Debian

#### Option 1: Install .deb package (Recommended)

```bash
git clone https://github.com/afkaral/yt-music-downloader.git
cd yt-music-downloader/
./build-deb.sh
sudo dpkg -i music-downloader_1.1.0_all.deb
sudo apt-get install -f  # Fix any missing dependencies
```

Launch from application menu or run `music-downloader`.

#### Option 2: Run from source

```bash
# Install dependencies
sudo apt update
sudo apt install python3-pyside6.qtwidgets python3-requests python3-mutagen ffmpeg mpv yt-dlp libchromaprint-tools

# Clone and run
git clone https://github.com/afkaral/yt-music-downloader.git
cd yt-music-downloader/
python3 src/main.py
```

### Fedora/RHEL

```bash
# Install dependencies
sudo dnf install python3-pyside6 python3-requests python3-mutagen ffmpeg mpv yt-dlp chromaprint-tools

# Clone and run
git clone https://github.com/afkaral/yt-music-downloader.git
cd yt-music-downloader/
python3 src/main.py
```

### Universal Linux (AppImage)

```bash
git clone https://github.com/afkaral/yt-music-downloader.git
cd yt-music-downloader/
./build-appimage.sh

# Make executable and run
chmod +x MusicDownloader-1.1.0-x86_64.AppImage
./MusicDownloader-1.1.0-x86_64.AppImage
```

Note: You still need to install system dependencies (ffmpeg, mpv, chromaprint).

### Windows

1. Install [Python 3.11+](https://www.python.org/downloads/)
2. Install [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) and add to PATH
3. Install [mpv](https://mpv.io/installation/) or [VLC](https://www.videolan.org/vlc/)
4. Download [fpcalc.exe](https://acoustid.org/chromaprint) and add to PATH
5. Install dependencies:

```cmd
pip install -r requirements.txt
```

6. Run:

```cmd
python src\main.py
```

### macOS

```bash
# Install Homebrew if not installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install dependencies
brew install python@3.11 ffmpeg mpv yt-dlp chromaprint pyside@6
pip3 install requests mutagen

# Clone and run
git clone https://github.com/afkaral/yt-music-downloader.git
cd yt-music-downloader/
python3 src/main.py
```

## Configuration

### AcoustID API Key

The application uses a shared API key by default. For better reliability and rate limits:

1. Get your free API key from [acoustid.org/api-key](https://acoustid.org/api-key)
2. Open Settings in the app
3. Paste your API key
4. Save

### Supported Players

- **mpv** (default, recommended)
- **vlc**
- **celluloid** (mpv frontend)
- **clementine**

Any player that can stream URLs via command line should work.

### Settings

- Download directory
- Search result limit (5-200)
- M3U playlist generation (enable/disable)
- Custom AcoustID API key

## How It Works

1. **Search**: Finds music on YouTube
2. **Download**: Downloads audio in high quality MP3
3. **Fingerprint**: Uses AcoustID to identify the exact recording
4. **Match**: Queries MusicBrainz database for metadata
5. **Tag**: Writes comprehensive metadata to the file
6. **Organize**: Updates playlist automatically

## Technology Stack

- **GUI**: PySide6 (Qt6)
- **Download**: yt-dlp + ffmpeg
- **Tagging**: Custom MusicBrainz implementation
- **Fingerprinting**: AcoustID + Chromaprint
- **Metadata**: Mutagen library

## License

MIT
