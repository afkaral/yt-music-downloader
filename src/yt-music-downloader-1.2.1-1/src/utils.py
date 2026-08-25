# src/utils.py
from pathlib import Path
from config import *
import subprocess
import json
import re

def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

    try:
        with open(CONFIG_FILE, "r", encoding="utf8") as f:
            config = json.load(f)

        merged_config = DEFAULT_CONFIG.copy()
        for key, value in config.items():
            merged_config[key] = value

        if merged_config != config:
            save_config(merged_config)
        
        return merged_config
    except (json.JSONDecodeError, Exception):
        print("Warning: Corrupted config file detected. Resetting to default.")
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def find_downloaded_file(output):
    for line in output.splitlines():
        m = re.search(
            r"\[ExtractAudio\] Destination: (.+)",
            line
        )
        if m:
            return m.group(1)
    return None

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    with open(CONFIG_FILE, "w", encoding="utf8") as f:
        json.dump(cfg, f, indent=4)

def rebuild_m3u(folder):
    folder = Path(folder)
    playlist = folder / f"{folder.name}.m3u"

    with open(playlist, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        for music in sorted(folder.iterdir()):
            if music.suffix.lower() not in (".mp3", ".flac"):
                continue

            result = subprocess.run([
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(music),
            ],
            capture_output=True,
            text=True)

            try:
                duration = int(float(result.stdout.strip()))
            except Exception:
                duration = 0

            f.write(f"#EXTINF:{duration},{music.stem}\n")
            f.write(f"{music.name}\n")