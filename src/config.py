# src/config.py

from pathlib import Path
import json

CONFIG_DIR = Path.home() / ".config" / "ytmusicdl"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "player": "mpv",
    "download_path": "/mnt/depo/Müzikler/Downloads/",
    "search_limit": 50,
}