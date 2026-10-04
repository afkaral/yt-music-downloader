"""YT Music Downloader - Download and tag music from YouTube/SoundCloud"""
__version__ = "1.3.0"
__author__ = "YT Music Downloader Team"

# Make key components available at package level
from .core.tagger import MusicTagger
from .config import CONFIG_FILE, DEFAULT_CONFIG
from .utils import load_config, save_config, find_downloaded_file
from .logging_config import configure_logging

__all__ = [
    'MusicTagger',
    'load_config',
    'save_config',
    'find_downloaded_file',
    'CONFIG_FILE',
    'DEFAULT_CONFIG',
    'configure_logging',
]