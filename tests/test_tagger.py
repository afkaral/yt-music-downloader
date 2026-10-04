import pytest
from src.core.tagger import MusicTagger

@pytest.fixture
def tagger():
    return MusicTagger(acoustid_key="test_key")

def test_extract_musicbrainz_metadata_recording_info(tagger):
    """Test extracting title and artist metadata from MusicBrainz response"""
    acoustid_result = {
        "recordings": [
            {
                "id": "rec-123",
                "title": "Sample Song Title",
                "artists": [{"id": "art-456", "name": "Sample Artist"}]
            }
        ]
    }
    release_data = {
        "title": "Sample Album Title",
        "id": "rel-789",
        "date": "1984-01-01"
    }
    
    metadata = tagger._extract_musicbrainz_metadata(acoustid_result, release_data, target_rec_id="rec-123")
    
    assert metadata["title"] == "Sample Song Title"
    assert metadata["artist"] == "Sample Artist"
    assert metadata["album"] == "Sample Album Title"

def test_build_genius_metadata(tagger):
    """Test constructing metadata dictionary from Genius response"""
    genius_data = {
        "title": "Dark Metal Track",
        "artist": "Underground Band",
        "album": "Demo 2024",
        "release_date": "2024-05-10",
        "year": "2024",
        "producer": "Producer X",
        "writer": "Writer Y"
    }
    
    metadata = tagger._build_genius_metadata(genius_data, "Unknown Artist", "Unknown Title")
    
    assert metadata["title"] == "Dark Metal Track"
    assert metadata["artist"] == "Underground Band"
    assert metadata["producer"] == "Producer X"
    assert metadata["writer"] == "Writer Y"