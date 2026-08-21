# src/config.py

from pathlib import Path
import json

CONFIG_DIR = Path.home() / ".config" / "ytmusicdl"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "player": "mpv",
    "download_path": str(Path.home() / "Music"),
    "search_limit": 50,
    "acoustid_api_key": "v8pQ6oyB",  # Picard's key (consider getting your own from https://acoustid.org/api-key)
    "create_m3u": True,
    "window_title": "YT Music Downloader",
}