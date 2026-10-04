"""Configuration I/O utilities for music_downloader."""
from pathlib import Path
import json
import shutil
import tempfile
import logging
import os

try:
    from ..config import CONFIG_DIR, CONFIG_FILE, DEFAULT_CONFIG
except ImportError:
    from config import CONFIG_DIR, CONFIG_FILE, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


def _validate_config(config: dict) -> dict:
    """Validate configuration keys and data types."""
    if not isinstance(config, dict):
        return dict(DEFAULT_CONFIG)

    validated = dict(DEFAULT_CONFIG)

    # download_path validation
    dl_path = config.get("download_path")
    if isinstance(dl_path, str) and dl_path.strip():
        validated["download_path"] = dl_path.strip()

    # search_limit validation
    limit = config.get("search_limit")
    if isinstance(limit, int) and 5 <= limit <= 200:
        validated["search_limit"] = limit

    # create_m3u validation
    if isinstance(config.get("create_m3u"), bool):
        validated["create_m3u"] = config["create_m3u"]

    # search_platform validation
    if config.get("search_platform") in ("YouTube", "SoundCloud"):
        validated["search_platform"] = config["search_platform"]

    # Boolean toggles
    for key in (
        "tag_use_acoustid", "tag_use_musicbrainz_search", "tag_use_genius",
        "cover_use_caa", "cover_use_itunes", "cover_use_genius",
        "organize_after_tag",
    ):
        if isinstance(config.get(key), bool):
            validated[key] = config[key]

    if isinstance(config.get("library_path"), str):
        validated["library_path"] = config["library_path"].strip()

    # String fields validation
    for key in ("acoustid_api_key", "genius_token", "window_title"):
        val = config.get(key)
        if isinstance(val, str):
            validated[key] = val.strip()

    return validated


def load_config() -> dict:
    """Load configuration from JSON file with robust error handling and validation."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        with open(CONFIG_FILE, "r", encoding="utf8") as f:
            user_config = json.load(f)

        merged_config = _deep_merge(dict(DEFAULT_CONFIG), user_config)
        validated_config = _validate_config(merged_config)

        if validated_config != user_config:
            save_config(validated_config)

        return validated_config

    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Config file corrupted or unreadable (%s). Resetting to defaults.", exc)
        try:
            save_config(dict(DEFAULT_CONFIG))
        except OSError as write_err:
            logger.error("Could not write default config: %s", write_err)
        return dict(DEFAULT_CONFIG)


def _deep_merge(base: dict, override: dict) -> dict:
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


def save_config(cfg: dict) -> None:
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
                try:
                    Path(tmp_path).unlink()
                except OSError:
                    pass
            raise

    except OSError as exc:
        logger.error("Failed to save config: %s", exc)
        raise

def get_library_path(config: dict) -> str:
    """Library root: the dedicated setting, falling back to the download folder."""
    return config.get("library_path") or config.get("download_path", str(Path.home() / "Music"))