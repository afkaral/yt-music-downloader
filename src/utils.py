# src/utils.py
from pathlib import Path
import subprocess
import json
import re
import shutil
import tempfile
import logging
import os
from config import CONFIG_DIR, CONFIG_FILE, DEFAULT_CONFIG

logger = logging.getLogger(__name__)

if 'CONFIG_DIR' not in dir():
    CONFIG_DIR = Path.home() / ".config" / "music-downloader"
    CONFIG_FILE = CONFIG_DIR / "config.json"
    DEFAULT_CONFIG = {
        "player": "mpv",
        "download_path": str(Path.home() / "Music"),
        "search_limit": 50,
        "create_m3u": True,
        "search_platforms": ["ytsearch", "scsearch", "gvsearch"],  # List of yt‑dlp search
        "acoustid_api_key": "v8pQ6oyB",  # Picard's key
    }

def load_config():
    """Load configuration from JSON file with robust error handling."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        with open(CONFIG_FILE, "r", encoding="utf8") as f:
            user_config = json.load(f)

        merged_config = _deep_merge(dict(DEFAULT_CONFIG), user_config)

        if merged_config != user_config:
            save_config(merged_config)

        return merged_config

    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Config file corrupted or unreadable (%s). Resetting to defaults.", exc)
        try:
            save_config(dict(DEFAULT_CONFIG))
        except OSError as write_err:
            logger.error("Could not write default config: %s", write_err)
        return dict(DEFAULT_CONFIG)


def _deep_merge(base, override):
    """Recursively merge *override* into a copy of *base*."""
    result = base.copy()
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def find_downloaded_file(output):
    """Extract the destination file path from yt-dlp output."""
    if not isinstance(output, str):
        logger.warning("Expected string output from yt-dlp, got %s", type(output).__name__)
        return None

    # Pattern 1: Standard yt-dlp extract-audio destination
    match = re.search(r"\[ExtractAudio\] Destination:\s*(.+)", output)
    if match:
        path = Path(match.group(1).strip())
        if path.exists():
            return str(path)

    # Pattern 2: Fallback – look for any file extension pattern after "Destination"
    match = re.search(r"Destination:\s*(.+?\.\w+)", output)
    if match:
        path = Path(match.group(1).strip())
        if path.exists():
            return str(path)

    logger.debug("Could not parse destination from yt-dlp output")
    return None


def save_config(cfg):
    """Atomically write configuration to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=CONFIG_DIR, prefix=".config_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            shutil.move(tmp_path, CONFIG_FILE)
        except Exception:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink(missing_ok=True)
            raise

    except OSError as exc:
        logger.error("Failed to save config: %s", exc)
        raise


def _get_duration_ffprobe(filepath):
    """Get duration of an audio file using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return 0

        duration_str = result.stdout.strip()
        if not duration_str:
            return 0

        duration = float(duration_str)
        return int(duration)

    except (subprocess.TimeoutExpired, ValueError, OSError):
        return 0


def _atomic_write(path, content):
    """Write content to *path* atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=".tmp_", suffix=".m3u"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        shutil.move(tmp_path, path)
    except Exception as exc:
        logger.error("Failed to write %s: %s", path, exc)
        if Path(tmp_path).exists():
            Path(tmp_path).unlink(missing_ok=True)
        raise