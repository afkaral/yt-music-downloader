"""System-level helper utilities for music_downloader."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def find_downloaded_file(output: str) -> Optional[Path]:
    """Extract the destination file path from yt-dlp output as a Path object."""
    if not isinstance(output, str):
        logger.warning("Expected string output from yt-dlp, got %s", type(output).__name__)
        return None

    # Pattern 1: Standard yt-dlp extract-audio destination
    match = re.search(r"\[ExtractAudio\] Destination:\s*(.+)", output)
    if match:
        path = Path(os.path.normpath(match.group(1).strip()))
        if path.exists():
            return path

    # Pattern 2: File already downloaded previously
    match = re.search(r"\[download\]\s+(.+?)\s+has already been downloaded", output)
    if match:
        path = Path(os.path.normpath(match.group(1).strip()))
        if path.exists():
            return path

    # Pattern 3: Fallback destination match
    match = re.search(r"Destination:\s*(.+?\.\w+)", output)
    if match:
        path = Path(os.path.normpath(match.group(1).strip()))
        if path.exists():
            return path

    logger.debug("Could not parse destination from yt-dlp output")
    return None


def _get_duration_ffprobe(filepath: Path) -> int:
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

        return int(float(duration_str))

    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        logger.debug("ffprobe error on %s: %s", filepath, exc)
        return 0


def _atomic_write(path: Path, content: str) -> None:
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
    except OSError as exc:
        logger.error("Failed to write %s: %s", path, exc)
        if Path(tmp_path).exists():
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
        raise