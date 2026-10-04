#!/usr/bin/env python3
"""
YT Music Downloader - Main Entry Point

Usage:
  python ytmusicdl.py              # Launch GUI (default)
  python ytmusicdl.py gui          # Launch GUI explicitly
  python ytmusicdl.py tag <file>   # Tag audio file
  python ytmusicdl.py config --list # Show configuration
  python ytmusicdl.py --help       # Show help
"""

import os
import sys
import argparse
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from logging_config import configure_logging
from utils import load_config, save_config, get_library_path
from core.tagger import MusicTagger
from core.organizer import MusicOrganizer

if getattr(sys, 'frozen', False):
    app_dir = str(Path(sys.executable).parent)
    os.environ["PATH"] = app_dir + os.pathsep + os.environ.get("PATH", "")

def get_version():
    """Read version from VERSION file"""
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "1.3.0"

def cmd_gui(args, config, logger):
    """Launch GUI application"""
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QIcon
        from gui.main_window import MainWindow
        app = QApplication(sys.argv)
        app.setApplicationName("YT Music Downloader")
        app.setApplicationVersion(get_version())
        app.setDesktopFileName("music-downloader")
        
        root_dir = Path(__file__).resolve().parent.parent
        icon_path = root_dir / "assets" / "music-downloader.png"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
        
        window = MainWindow()
        window.show()
        
        logger.info(f"GUI started - version {get_version()}")
        sys.exit(app.exec())
        
    except ImportError as e:
        logger.error(f"Cannot start GUI: {e}")
        logger.error("Install GUI dependencies: pip install PySide6")
        sys.exit(1)


# (argparse dest, MusicTagger option key, help text) for per-run source toggles
TAG_SOURCES = (
    ('acoustid', 'use_acoustid', 'AcoustID fingerprint lookup'),
    ('mb_search', 'use_musicbrainz_search', 'MusicBrainz text search fallback'),
    ('genius', 'use_genius', 'Genius metadata fallback'),
    ('caa', 'use_caa', 'Cover Art Archive covers'),
    ('itunes', 'use_itunes', 'iTunes covers'),
    ('genius_cover', 'use_genius_cover', 'Genius covers'),
)


def _tagger_options(args, config):
    """Config toggles, overridden by any --flag / --no-flag given on the command line"""
    options = MusicTagger.options_from_config(config)
    for dest, key, _ in TAG_SOURCES:
        value = getattr(args, dest, None)
        if value is not None:
            options[key] = value
    return options


def _build_organize_hook(config, logger, organize=None, library=None):
    """Return a callable that moves a tagged file into the library, or None when disabled"""
    if organize is None:
        organize = config.get('organize_after_tag', False)
    if not organize:
        return None
    organizer = MusicOrganizer(library or get_library_path(config), logger=logger)
    return lambda filepath: organizer.organize_file(Path(filepath))


def cmd_tag(args, config, logger):
    """Tag audio files with metadata"""
    tagger = MusicTagger(
        logger=logger,
        acoustid_key=config.get('acoustid_api_key'),
        genius_token=config.get('genius_token'),
        options=_tagger_options(args, config)
    )
    organize_hook = _build_organize_hook(config, logger, args.organize, args.library)

    path = Path(args.path)
    
    if not path.exists():
        logger.error(f"Path not found: {path}")
        sys.exit(1)
    
    if path.is_dir():
        results = tagger.process_directory(
            str(path),
            recursive=args.recursive,
            on_success=organize_hook
        )
        logger.info(f"Complete: {results['success']} success, {results['failed']} failed")
        sys.exit(0 if results['failed'] == 0 else 1)
    else:
        success = tagger.process_file(str(path))
        if success and organize_hook:
            organize_hook(str(path))
        sys.exit(0 if success else 1)


def cmd_organize(args, config, logger):
    """Move tagged audio files into the Artist/Album/NN - Title layout"""
    source = Path(args.source)
    if not source.is_dir():
        logger.error(f"Folder not found: {source}")
        sys.exit(1)

    library = args.library or get_library_path(config)
    organizer = MusicOrganizer(library, logger=logger, move=not args.copy)
    organizer.organize_directory(str(source), recursive=not args.no_recursive)

def cmd_config(args, config, logger):
    """View or modify configuration"""
    if args.list:
        # List all config
        print("\nCurrent configuration:")
        print(f"  Config file: {Path.home() / '.config' / 'ytmusicdl' / 'config.json'}")
        print("\nSettings:")
        for key, value in sorted(config.items()):
            # Hide sensitive tokens
            if 'token' in key.lower() and value:
                display_value = value[:10] + "..." if len(value) > 10 else "***"
            elif 'key' in key.lower() and value and value != "v8pQ6oyB":
                display_value = value[:10] + "..." if len(value) > 10 else "***"
            else:
                display_value = value
            print(f"  {key}: {display_value}")
        print()
        return
    
    if args.get:
        # Get specific key
        value = config.get(args.get)
        if value is None:
            logger.error(f"Key not found: {args.get}")
            logger.info(f"Available keys: {', '.join(config.keys())}")
            sys.exit(1)
        print(value)
        return
    
    if args.set:
        # Set key=value
        try:
            key, value = args.set.split('=', 1)
            key = key.strip()
            value = value.strip()
            
            # Type conversion
            if value.lower() == 'true':
                value = True
            elif value.lower() == 'false':
                value = False
            elif value.isdigit():
                value = int(value)
            
            config[key] = value
            save_config(config)
            logger.info(f"✓ Set {key} = {value}")
            logger.info(f"  Config saved to: {Path.home() / '.config' / 'ytmusicdl' / 'config.json'}")
        except ValueError:
            logger.error("Invalid format. Use: key=value")
            logger.info("Example: python ytmusicdl.py config --set genius_token=YOUR_TOKEN")
            sys.exit(1)
        return
    
    # No action specified
    logger.error("Specify --list, --get KEY, or --set KEY=VALUE")
    logger.info("Examples:")
    logger.info("  python ytmusicdl.py config --list")
    logger.info("  python ytmusicdl.py config --get genius_token")
    logger.info("  python ytmusicdl.py config --set genius_token=YOUR_TOKEN")
    sys.exit(1)


def cmd_download(args, config, logger):
    """Download music from URL"""
    import subprocess
    
    download_path = Path(args.output) if args.output else Path(config.get('download_path'))
    download_path.mkdir(parents=True, exist_ok=True)
    
    command = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--embed-thumbnail",
        "--embed-metadata",
        "--no-playlist",
        "-o", str(download_path / "%(title)s.%(ext)s"),
        args.url
    ]
    
    logger.info(f"Downloading: {args.url}")
    logger.info(f"Output: {download_path}")
    
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        logger.info("✓ Download complete")
        
        # Auto-tag if requested
        if args.tag:
            logger.info("Tagging downloaded file...")
            # Find most recently created MP3 in download dir
            mp3_files = sorted(download_path.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
            if mp3_files:
                latest_file = mp3_files[0]
                tagger = MusicTagger(
                    logger=logger,
                    acoustid_key=config.get('acoustid_api_key'),
                    genius_token=config.get('genius_token'),
                    options=MusicTagger.options_from_config(config)
                )
                if tagger.process_file(str(latest_file)):
                    logger.info(f"✓ Tagged: {latest_file.name}")
                    organize_hook = _build_organize_hook(config, logger)
                    if organize_hook:
                        organize_hook(str(latest_file))
                else:
                    logger.warning("Tagging failed")
            else:
                logger.warning("No MP3 file found to tag")
        
        sys.exit(0)
    except subprocess.CalledProcessError as e:
        logger.error(f"Download failed: {e}")
        if e.stderr:
            logger.error(e.stderr)
        sys.exit(1)
    except FileNotFoundError:
        logger.error("yt-dlp not found. Install with: pip install yt-dlp")
        sys.exit(1)

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog='ytmusicdl',
        description='YouTube Music Downloader with auto-tagging',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Launch GUI (default)
  %(prog)s gui                          # Launch GUI explicitly
  %(prog)s download <url>               # Download from URL
  %(prog)s download <url> --tag         # Download and auto-tag
  %(prog)s tag song.mp3                 # Tag single file
  %(prog)s tag /music -r                # Tag directory recursively
  %(prog)s config --set genius_token=XXX # Set Genius API token
  %(prog)s config --list                # Show all settings
  %(prog)s tag /music -r --no-acoustid  # Tag without fingerprint lookup
  %(prog)s organize /music/inbox        # Move tagged files into Artist/Album/NN - Title

Configuration:
  Config file: ~/.config/ytmusicdl/config.json
  
  Set Genius token:
    1. Get token: https://genius.com/api-clients
    2. Set it: %(prog)s config --set genius_token=YOUR_TOKEN
  
  Set AcoustID key (optional):
    1. Get key: https://acoustid.org/api-key  
    2. Set it: %(prog)s config --set acoustid_api_key=YOUR_KEY
        """
    )
    
    parser.add_argument('-v', '--version', action='version', version=f'%(prog)s {get_version()}')
    parser.add_argument('--verbose', action='store_true', help='Enable debug logging')
    parser.add_argument('--quiet', action='store_true', help='Only show errors')
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # GUI command
    subparsers.add_parser('gui', help='Launch graphical interface (default)')
    
    # Download command
    download_parser = subparsers.add_parser('download', help='Download music from URL')
    download_parser.add_argument('url', help='YouTube or SoundCloud URL')
    download_parser.add_argument('-o', '--output', help='Output directory (default: config download_path)')
    download_parser.add_argument('-t', '--tag', action='store_true', help='Auto-tag after download')
    
    # Tag command
    tag_parser = subparsers.add_parser('tag', help='Tag audio files with metadata')
    tag_parser.add_argument('path', help='File or directory to tag')
    tag_parser.add_argument('-r', '--recursive', action='store_true', help='Scan subdirectories')

    for dest, _, help_text in TAG_SOURCES:
        tag_parser.add_argument(
            '--' + dest.replace('_', '-'),
            dest=dest,
            action=argparse.BooleanOptionalAction,
            default=None,
            help=f'{help_text} (default: from config)'
        )
    tag_parser.add_argument(
        '--organize',
        action=argparse.BooleanOptionalAction,
        default=None,
        help='Move tagged files into Artist/Album/NN - Title (default: from config)'
    )
    tag_parser.add_argument('-l', '--library', help='Library root for --organize (default: library_path or download_path)')

    # Organize command
    organize_parser = subparsers.add_parser('organize', help='Move tagged files into Artist/Album/NN - Title')
    organize_parser.add_argument('source', help='Folder containing tagged audio files')
    organize_parser.add_argument('-l', '--library', help='Library root (default: library_path or download_path)')
    organize_parser.add_argument('--copy', action='store_true', help='Copy instead of move')
    organize_parser.add_argument('--no-recursive', action='store_true', help='Do not scan subfolders')
    
    # Config command
    config_parser = subparsers.add_parser('config', help='View or modify configuration')
    config_group = config_parser.add_mutually_exclusive_group(required=True)
    config_group.add_argument('--list', action='store_true', help='List all settings')
    config_group.add_argument('--get', metavar='KEY', help='Get specific setting')
    config_group.add_argument('--set', metavar='KEY=VALUE', help='Set configuration value')
    
    args = parser.parse_args()
    
    # Setup logging
    if args.verbose:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.ERROR
    else:
        log_level = logging.INFO
    
    logger = configure_logging(level=log_level)
    
    # Load config
    config = load_config()
    
    # Route to command (default to GUI if none specified)
    command = args.command or 'gui'
    
    commands = {
        'gui': cmd_gui,
        'download': cmd_download,
        'tag': cmd_tag,
        'config': cmd_config,
        'organize': cmd_organize,
    }
    
    handler = commands.get(command)
    if handler:
        try:
            handler(args, config, logger)
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
            sys.exit(130)
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()

