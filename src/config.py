# src/config.py
from pathlib import Path
import json

CONFIG_DIR = Path.home() / ".config" / "ytmusicdl"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "download_path": str(Path.home() / "Music"),
    "search_limit": 50,
    "search_platform": "YouTube",  # YouTube or SoundCloud
    "acoustid_api_key": "v8pQ6oyB",  # Get your own from https://acoustid.org/api-key
    "genius_token": "",  # Get from https://genius.com/api-clients
    "create_m3u": True,
    "tag_use_acoustid": True,
    "tag_use_musicbrainz_search": True,
    "tag_use_genius": True,
    "cover_use_caa": True,
    "cover_use_itunes": True,
    "cover_use_genius": True,
    "library_path": "",  # empty = use download_path
    "organize_after_tag": False,
    "window_title": "YT Music Downloader",
}
