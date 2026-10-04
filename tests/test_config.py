import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
from src.utils.config_io import load_config, save_config, _validate_config

def test_validate_config_defaults():
    """Test fallback to default values when invalid types are provided"""
    invalid_data = {
        "download_path": 12345,
        "search_limit": 999,
        "create_m3u": "yes",
        "search_platform": "Spotify"
    }
    validated = _validate_config(invalid_data)
    
    assert isinstance(validated["download_path"], str)
    assert validated["search_limit"] == 50
    assert validated["create_m3u"] is True
    assert validated["search_platform"] == "YouTube"

def test_validate_config_valid_data():
    """Test preservation of valid configuration values"""
    valid_data = {
        "download_path": "/mnt/storage/Music",
        "search_limit": 25,
        "create_m3u": False,
        "search_platform": "SoundCloud",
        "acoustid_api_key": "test_key_123"
    }
    validated = _validate_config(valid_data)
    
    assert validated["download_path"] == "/mnt/storage/Music"
    assert validated["search_limit"] == 25
    assert validated["create_m3u"] is False
    assert validated["search_platform"] == "SoundCloud"
    assert validated["acoustid_api_key"] == "test_key_123"

def test_save_and_load_config(tmp_path):
    """Test saving configuration to disk and reloading it"""
    test_config_file = tmp_path / "config.json"
    test_config_dir = tmp_path
    
    config_payload = {
        "download_path": str(tmp_path),
        "search_limit": 30,
        "create_m3u": True,
        "search_platform": "YouTube",
        "acoustid_api_key": "v8pQ6oyB",
        "genius_token": "",
        "window_title": "Test Downloader"
    }
    
    with patch("src.utils.config_io.CONFIG_FILE", test_config_file), \
         patch("src.utils.config_io.CONFIG_DIR", test_config_dir):
        save_config(config_payload)
        assert test_config_file.exists()
        
        loaded = load_config()
        assert loaded["search_limit"] == 30
        assert loaded["download_path"] == str(tmp_path)