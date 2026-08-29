# src/core.py
"""
Core business logic for the Music Downloader application.

This module contains pure Python functions for:
1. Searching music from YouTube and SoundCloud using yt-dlp.
2. Downloading audio files.
3. Tagging downloaded files with metadata.

These functions are independent of the GUI and can be used by a CLI interface
or unit tests.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


def get_platform_command(platform: str, query: str, limit: int) -> List[str]:
    """
    Build the yt-dlp command for a specific platform.
    """
    expr = f"{platform}{limit}:{query}"
    cmd = [
        "yt-dlp",
        "--dump-json",
        f"--max-downloads={limit}",
        expr,
    ]
    
    # YouTube needs --flat-playlist to keep JSON small but include URLs
    if platform == "ytsearch":
        cmd.insert(1, "--flat-playlist")
        
    return cmd


def get_environment() -> dict:
    """
    Create an environment dictionary for subprocesses.
    Ensures UTF-8 encoding and unbuffered output.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def search_music(
    query: str, 
    limit: int = 50, 
    platforms: Optional[List[str]] = None
) -> List[Tuple[str, str, str, str]]:
    """
    Search for music using yt-dlp and return results.

    This function runs synchronously and returns a list of tuples:
    (title, uploader, url, platform)

    Args:
        query: The search term.
        limit: Maximum total results to return.
        platforms: List of platforms to search (e.g., ['ytsearch', 'scsearch']).
                   If None, defaults to ['ytsearch'].

    Returns:
        A list of tuples containing search results.
    """
    if platforms is None:
        platforms = ["ytsearch"]

    logger.info(f"Starting search for '{query}' on {platforms} (limit={limit})")
    
    results = []
    seen_urls = set()
    
    # We process platforms sequentially to keep it simple and avoid complex
    # multi-process synchronization in the core logic. 
    # The GUI can run these in threads if needed for responsiveness.
    for platform in platforms:
        if len(results) >= limit:
            break
            
        try:
            cmd = get_platform_command(platform, query, limit)
            logger.debug(f"Running command: {' '.join(cmd)}")
            
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=get_environment()
            )
            
            # Read line by line
            for line in proc.stdout:
                if len(results) >= limit:
                    break
                    
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                title = data.get("title") or ""
                uploader = data.get("uploader") or ""
                url = (
                    data.get("webpage_url")
                    or data.get("url")
                    or (f"https://youtu.be/{data['id']}" if data.get("id") else "")
                )
                
                if not url or url in seen_urls:
                    continue
                    
                seen_urls.add(url)
                results.append((title, uploader, url, platform))
            
            proc.wait()
            
        except FileNotFoundError:
            logger.error("yt-dlp not found. Please install yt-dlp.")
            break
        except Exception as e:
            logger.error(f"Error during search on {platform}: {e}")
            continue
            
    logger.info(f"Search finished. Found {len(results)} results.")
    return results


def download_audio(
    url: str, 
    output_dir: Path, 
    player: str = "mpv",
    timeout: int = 300
) -> Optional[Path]:
    """
    Download audio from a URL using yt-dlp.

    Args:
        url: The video/audio URL.
        output_dir: Directory to save the downloaded file.
        player: The media player to use (for future integration).
        timeout: Maximum time in seconds to wait for download.

    Returns:
        Path to the downloaded file, or None if failed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # yt-dlp template for filename
    template = str(output_dir / "%(title)s.%(ext)s")
    
    cmd = [
        "yt-dlp",
        "-x",  # Extract audio
        "--audio-format", "mp3",
        "--output", template,
        "--no-playlist",
        url
    ]
    
    logger.info(f"Downloading: {url}")
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=get_environment()
        )
        
        # Wait for completion with timeout
        try:
            _, stderr = proc.communicate(timeout=timeout)
            if proc.returncode != 0:
                logger.error(f"yt-dlp failed: {stderr}")
                return None
                
            # Find the downloaded file
            files = list(output_dir.glob("*.mp3"))
            if files:
                return files[-1]  # Return the most recent file
            
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.error(f"Download timed out after {timeout} seconds")
            return None
            
    except FileNotFoundError:
        logger.error("yt-dlp not found.")
        return None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None


def tag_file(file_path: Path, metadata: dict) -> bool:
    """
    Tag an audio file with metadata using mutagen or similar.

    Args:
        file_path: Path to the audio file.
        metadata: Dictionary containing tags (title, artist, album, etc.).

    Returns:
        True if tagging was successful, False otherwise.
    """
    try:
        # This is a placeholder for actual tagging logic
        # You would use a library like 'mutagen' here
        logger.info(f"Tagging file: {file_path} with metadata: {metadata}")
        
        # Example using mutagen (if installed):
        # from mutagen.mp3 import MP3
        # audio = MP3(file_path)
        # audio.tags['TIT2'] = metadata.get('title', '')
        # audio.tags['TPE1'] = metadata.get('artist', '')
        # audio.save()
        
        return True
        
    except Exception as e:
        logger.error(f"Tagging failed for {file_path}: {e}")
        return False