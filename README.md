# YT Music Downloader

> [!WARNING]
> This project was written entirely with AI assistance. Treat it as AI slop: it works for my own setup, but the code has not been audited line by line, it has very few tests, and it will contain bugs. It also rewrites tags and moves files inside your music library. Back up anything you care about before pointing it at a real collection, and read the code before you trust it. There is no support and no stability guarantee.

## Purpose

It does three things:

1. Searches YouTube or SoundCloud and downloads audio as MP3 with yt-dlp.
2. Tags the files using AcoustID and MusicBrainz, with Genius as a fallback, in a way that keeps albums intact on a Navidrome server.
3. Optionally moves tagged files into an `Artist/Album/NN - Title.ext` layout.

Several choices are opinionated and made for Navidrome. If your setup differs, you may not want them (see [Behavior you may not want](#behavior-you-may-not-want)).

## Requirements

- Python 3.10 or newer
- Python packages: PySide6, requests, mutagen (`requirements.txt`)
- System tools: yt-dlp, ffmpeg (including ffprobe), chromaprint (provides `fpcalc`)
- Optional: mpv and python-mpv, for the preview player

## Installation

```bash
git clone https://github.com/afkaral/yt-music-downloader.git
cd yt-music-downloader
pip install -r requirements.txt
```

System tools:

```bash
sudo pacman -S yt-dlp ffmpeg chromaprint                    # Arch
sudo apt install yt-dlp ffmpeg libchromaprint-tools         # Debian/Ubuntu
```

## Usage

### GUI

```bash
python -m src
```

`python src/main.py` also works. The window has:

- Search for tracks on YouTube or SoundCloud (chosen in settings) and preview them by double-clicking a result.
- Download: saves the selected track as MP3 with embedded thumbnail and metadata, then tags it.
- Tag File: tags any audio file you pick.
- Organize: moves tagged files from a folder you pick into the library layout. It asks for confirmation first.
- Build M3U: writes an M3U playlist for the download folder.
- Settings, split into Download, Tagging and Library tabs.

### Command line

```bash
python -m src                                # GUI
python -m src download URL [-o DIR] [--tag]  # download, optionally tag
python -m src tag PATH [-r] [options]        # tag a file or a folder
python -m src organize SOURCE [-l LIBRARY] [--copy] [--no-recursive]
python -m src config --list
python -m src config --get KEY
python -m src config --set KEY=VALUE
```

`--verbose` and `--quiet` are global flags and go before the command:

```bash
python -m src --verbose tag ~/Music/inbox -r --no-acoustid
```

Options of `tag` that override the saved settings for a single run:

| Flag | Controls |
| --- | --- |
| `--acoustid` / `--no-acoustid` | AcoustID fingerprint lookup |
| `--mb-search` / `--no-mb-search` | MusicBrainz text search fallback |
| `--genius` / `--no-genius` | Genius metadata fallback |
| `--caa` / `--no-caa` | Cover Art Archive covers |
| `--itunes` / `--no-itunes` | iTunes covers |
| `--genius-cover` / `--no-genius-cover` | Genius covers |
| `--organize` / `--no-organize` | Move files into the library after tagging |
| `-l`, `--library` | Library root used by `--organize` |

Everything is enabled by default except organizing after tagging.

## Configuration

The config file is `~/.config/ytmusicdl/config.json`. Settings can be changed in the GUI or with `config --set`.

```json
{
  "download_path": "/home/user/Music/Downloads",
  "library_path": "/home/user/Music/Library",
  "search_limit": 50,
  "search_platform": "YouTube",
  "create_m3u": true,
  "acoustid_api_key": "v8pQ6oyB",
  "genius_token": "",
  "tag_use_acoustid": true,
  "tag_use_musicbrainz_search": true,
  "tag_use_genius": true,
  "cover_use_caa": true,
  "cover_use_itunes": true,
  "cover_use_genius": true,
  "organize_after_tag": false,
  "window_title": "YT Music Downloader"
}
```

- `library_path` empty means the download folder is used as the library.
- `acoustid_api_key` defaults to a public demo key. A free personal key from https://acoustid.org/api-key is better.
- `genius_token` is needed for the Genius fallback; without it Genius is skipped. Get one at https://genius.com/api-clients.
- With `organize_after_tag` on, the automatic M3U for the download folder is skipped, since the files leave that folder.

## How tagging works

1. The artist and title to search for come from the file's existing tags if both are present. Otherwise they are parsed from the filename (a leading track number is stripped, `Artist - Title` is split), and as a last resort the artist is taken from the folder name.
2. The AcoustID fingerprint is computed with `fpcalc` and looked up, which gives a MusicBrainz release.
3. If that fails, MusicBrainz is searched by artist and title.
4. If MusicBrainz gives nothing, Genius is tried (title, artist, album, year, credits, track number).
5. Cover art comes from the Cover Art Archive (release, then release group), then iTunes. On the Genius path it comes from Genius, then iTunes.
6. The metadata is normalized and written to the file.

## Library layout

```
Library/
  Artist/
    Album/
      01 - Title.mp3
```

- Albums are grouped by album artist and cleaned album title. The year is ignored, so a remaster or reissue lands in the same folder as the original.
- Characters that are illegal on NTFS and FAT are removed from folder and file names.
- If a target file name already exists, `(2)`, `(3)` and so on is appended.
- Files missing an artist, album or title tag are skipped and left where they are. A single without an album tag is therefore not moved.
- Files are moved by default. `--copy` copies instead.

## Behavior you may not want

These are deliberate, to keep Navidrome from splitting albums:

- MusicBrainz IDs, barcode, catalog number, AcoustID tags, disc number and disc subtitle are removed from the files.
- Track numbers continue across discs of a multi-disc release.
- Disambiguation such as `(TUR)` or `(2)` is stripped from artist names. The album artist is the primary artist without featured artists.
- Remaster, deluxe, edition and similar suffixes are stripped from album titles, as are trailing dots.
- Date, original date and original year are collapsed to a single year per release. This can be turned off with `UNIFY_RELEASE_YEAR` in `src/core/tagger.py`.

## Supported formats

MP3 (ID3), FLAC and OGG/OGA (Vorbis comments, embedded pictures), M4A/MP4 (MP4 atoms).

## Packaging

Scripts for an AppImage, a Debian package, an Arch PKGBUILD, a Nix flake, a Flatpak manifest and a Windows build are in `packaging/` and `.github/workflows/`. I develop and use this on Arch-based Linux only; the other targets are not guaranteed to work.

## Development

```bash
python -m pytest
```

The tests are minimal.

## Acknowledgements

This project is mostly glue around other people's work. Thanks to:

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloading and searching
- [mutagen](https://github.com/quodlibet/mutagen) for reading and writing tags
- [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) for the GUI
- [requests](https://github.com/psf/requests) for HTTP
- [FFmpeg](https://ffmpeg.org/) for audio conversion and duration probing
- [Chromaprint and AcoustID](https://acoustid.org/) for audio fingerprinting
- [MusicBrainz](https://musicbrainz.org/) and the [Cover Art Archive](https://coverartarchive.org/) for metadata and artwork
- [Genius](https://genius.com/) and the iTunes Search API for fallback metadata and artwork
- [mpv](https://mpv.io/) and [python-mpv](https://github.com/jaseg/python-mpv) for the preview player
- [Navidrome](https://www.navidrome.org/), which this is built around

## License

GPLv3. See [LICENSE](LICENSE).