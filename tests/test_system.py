import pytest
from pathlib import Path
from src.utils.system import find_downloaded_file, _atomic_write

def test_find_downloaded_file_pattern1(tmp_path):
    """Test extracting file path from standard ExtractAudio output"""
    fake_file = tmp_path / "Test Track.mp3"
    fake_file.write_text("dummy content")
    
    yt_dlp_output = f"[ExtractAudio] Destination: {fake_file}\nDeleting original file..."
    
    result = find_downloaded_file(yt_dlp_output)
    assert result == fake_file
    assert isinstance(result, Path)

def test_find_downloaded_file_pattern2(tmp_path):
    """Test extracting file path from fallback Destination pattern"""
    fake_file = tmp_path / "Underground Track.flac"
    fake_file.write_text("dummy content")
    
    yt_dlp_output = f"Destination: {fake_file}\n[ffmpeg] Correcting container..."
    
    result = find_downloaded_file(yt_dlp_output)
    assert result == fake_file

def test_find_downloaded_file_invalid():
    """Test returning None for invalid or non-existent output"""
    assert find_downloaded_file("ERROR: Video unavailable") is None
    assert find_downloaded_file(12345) is None

def test_atomic_write(tmp_path):
    """Test the integrity of atomic file write operation"""
    target_file = tmp_path / "playlist.m3u"
    content = "#EXTM3U\n#EXTINF:180,Artist - Track\ntrack.mp3\n"
    
    _atomic_write(target_file, content)
    
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == content