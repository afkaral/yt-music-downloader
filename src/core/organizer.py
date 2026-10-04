#!/usr/bin/env python3
"""
Music Library Organizer

Moves/copies already-tagged audio files into a Library/Artist/Album/NN - Title.ext
layout. Releases are grouped by artist + cleaned album title only, ignoring year,
so remasters/reissues/different-year pressings of the same album never create
separate folders. Reuses MusicTagger's artist/album normalization so folder
names always match what the tagger itself writes into file metadata.
"""

import os
import re
import shutil
import logging
import argparse
from pathlib import Path
from typing import Optional, Dict, List

from mutagen import File as MutagenFile

try:
    from .tagger import MusicTagger
except ImportError:
    from tagger import MusicTagger

# Characters illegal on NTFS/exFAT/FAT32 paths
INVALID_FS_CHARS_RE = re.compile(r'[\\/:*?"<>|]')

class MusicOrganizer:
    """Organizes tagged audio files into Library/Artist/Album/NN - Title.ext"""

    SUPPORTED_FORMATS = MusicTagger.SUPPORTED_FORMATS

    def __init__(self, library_root: str, logger: logging.Logger = None, move: bool = True):
        self.library_root = Path(library_root)
        self.move = move
        self.logger = logger or logging.getLogger(__name__)
        if not self.logger.handlers and not logging.getLogger().handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

        # Used only for its artist/album normalization rules, so organized
        # folder names always match what the tagger writes into file tags
        self._tagger = MusicTagger(logger=self.logger)
        self.skipped_files: List[str] = []

    # ------------------------------------------------------------------
    # Tag reading
    # ------------------------------------------------------------------

    def _read_tags(self, filepath: Path) -> Optional[Dict]:
        """Read the tags needed to place a file in the library"""
        try:
            audio = MutagenFile(str(filepath), easy=True)
        except Exception as e:
            self.logger.warning(f"Cannot read tags: {filepath.name} ({e})")
            return None

        if not audio:
            self.logger.warning(f"No readable tags: {filepath.name}")
            return None

        def first(key: str) -> str:
            values = audio.get(key)
            return values[0].strip() if values and values[0].strip() else ''

        artist = first('artist')
        albumartist = first('albumartist') or artist
        album = first('album')
        title = first('title')
        tracknumber = first('tracknumber')

        if not artist or not album or not title:
            self.logger.warning(f"Missing artist/album/title tags: {filepath.name}")
            return None

        return {
            'artist': artist,
            'albumartist': albumartist,
            'album': album,
            'title': title,
            'tracknumber': tracknumber,
        }

    # ------------------------------------------------------------------
    # Naming
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Strip characters illegal on NTFS/exFAT/FAT32 and trailing dots"""
        cleaned = INVALID_FS_CHARS_RE.sub('', name).strip()
        cleaned = re.sub(r'[.\s]+$', '', cleaned)
        return cleaned or 'Unknown'

    @staticmethod
    def _track_number_prefix(tracknumber: str) -> str:
        """Extract a plain two-digit prefix from a tag like '7' or '7/14'"""
        match = re.match(r'\s*(\d+)', tracknumber or '')
        if not match:
            return ''
        return f"{int(match.group(1)):02d}"

    def _target_path(self, tags: Dict, ext: str) -> Path:
        # Album grouping ignores year entirely: a cleaned title is the only
        # key, so "Album (Remastered)" and "Album (2017 Edit)" both collapse
        # into the same "Album" folder as the original release
        artist = self._tagger._clean_artist_name(tags['albumartist']) or 'Unknown Artist'
        album = self._tagger._clean_album_name(tags['album']) or 'Unknown Album'
        title = tags['title'] or 'Unknown Title'

        artist_dir = self._sanitize_filename(artist)
        album_dir = self._sanitize_filename(album)
        title_safe = self._sanitize_filename(title)

        track_prefix = self._track_number_prefix(tags['tracknumber'])
        filename = f"{track_prefix} - {title_safe}{ext}" if track_prefix else f"{title_safe}{ext}"

        return self.library_root / artist_dir / album_dir / filename

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_collision(target: Path) -> Path:
        """Append ' (2)', ' (3)', ... if the destination filename is taken"""
        if not target.exists():
            return target
        stem, ext = target.stem, target.suffix
        counter = 2
        while True:
            candidate = target.with_name(f"{stem} ({counter}){ext}")
            if not candidate.exists():
                return candidate
            counter += 1

    def organize_file(self, filepath: Path) -> Optional[Path]:
        """Move/copy a single file into its Library/Artist/Album/NN - Title location"""
        ext = filepath.suffix.lower()
        if ext not in self.SUPPORTED_FORMATS:
            return None

        tags = self._read_tags(filepath)
        if not tags:
            self.skipped_files.append(str(filepath))
            return None

        target = self._target_path(tags, ext)

        if target.resolve() == filepath.resolve():
            self.logger.debug(f"Already in place: {filepath}")
            return target

        target = self._resolve_collision(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            if self.move:
                shutil.move(str(filepath), str(target))
            else:
                shutil.copy2(str(filepath), str(target))
            self.logger.info(f"{'Moved' if self.move else 'Copied'}: {filepath.name} -> {target}")
            return target
        except Exception as e:
            self.logger.error(f"Failed to place {filepath.name}: {e}")
            return None

    def organize_directory(self, source: str, recursive: bool = True) -> Dict[str, int]:
        """Organize every supported audio file under source into the library"""
        source_path = Path(source)
        results = {'organized': 0, 'skipped': 0}

        if recursive:
            files = [p for p in source_path.rglob('*') if p.suffix.lower() in self.SUPPORTED_FORMATS]
        else:
            files = [p for p in source_path.iterdir() if p.is_file() and p.suffix.lower() in self.SUPPORTED_FORMATS]

        self.logger.info(f"Found {len(files)} file(s) to organize")

        for filepath in files:
            if self.organize_file(filepath):
                results['organized'] += 1
            else:
                results['skipped'] += 1

        self.logger.info(f"Organize complete: {results['organized']} organized, {results['skipped']} skipped")
        return results

    def write_skip_log(self, path: str) -> None:
        """Write the list of untagged/unreadable files skipped this run to a text file"""
        if not self.skipped_files:
            return
        content = "\n".join(self.skipped_files) + "\n"
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.logger.info(f"Skip log written: {path} ({len(self.skipped_files)} file(s))")

    # ------------------------------------------------------------------
    # Future-path lookup (used by the genre playlist migrator)
    # ------------------------------------------------------------------

    def compute_target_relpath(self, filepath: Path) -> Optional[Path]:
        """
        Read a file's tags and compute the Artist/Album/NN - Title.ext path it
        would get from organize_file, without touching the filesystem.
        """
        tags = self._read_tags(filepath)
        if not tags:
            return None
        target = self._target_path(tags, filepath.suffix.lower())
        return target.relative_to(self.library_root)

def main():
    parser = argparse.ArgumentParser(
        description="Organize a tagged music folder into Library/Artist/Album/NN - Title.ext"
    )
    parser.add_argument('source', help='Folder containing already-tagged audio files')
    parser.add_argument('library', help='Target library root')
    parser.add_argument('--copy', action='store_true', help='Copy instead of move')
    parser.add_argument('--no-recursive', action='store_true', help='Do not scan subfolders of source')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='[%(levelname)s] %(message)s'
    )
    logger = logging.getLogger('organizer')

    organizer = MusicOrganizer(args.library, logger=logger, move=not args.copy)
    organizer.organize_directory(args.source, recursive=not args.no_recursive)

    if organizer.skipped_files:
        skip_log_path = Path(args.library) / "_needs_tagging.txt"
        organizer.write_skip_log(str(skip_log_path))

if __name__ == '__main__':
    main()