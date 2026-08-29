# src/music_tagger.py
#!/usr/bin/env python3
"""
MusicBrainz Audio Tagger
AcoustID fingerprint + MusicBrainz metadata + Cover Art Archive
"""

import os
import sys
import json
import time
import argparse
import logging
from typing import Optional, Dict, List, Tuple
import requests
import subprocess
import shutil
import base64
from pathlib import Path

from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TDRC, TDOR, TRCK, APIC, TPE2, TCON, TPOS,
    TPUB, TSRC, TMED, TSOP, TXXX
)
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis


# --- Custom Log Formatter for Clean Output ---
class CleanFormatter(logging.Formatter):
    """Provides a concise, color-coded log format."""
    COLORS = {
        'DEBUG': '\033[90m',  # Gray
        'INFO': '\033[92m',   # Green
        'WARNING': '\033[93m',# Yellow
        'ERROR': '\033[91m',  # Red
        'CRITICAL': '\033[95m' # Magenta
    }
    RESET = '\033[0m'
    FORMAT = "[%(levelname)s] %(message)s"

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, '')
        record.msg = f"{log_color}{record.msg}{self.RESET}"
        return super().format(record)


class MusicTagger:
    """MusicBrainz-based music tagger"""
    
    RATE_LIMIT_ACOUSTID = 0.33  # 3 req/sec
    RATE_LIMIT_MB = 2.0  # * req/sec
    SUPPORTED_FORMATS = {'.mp3', '.flac', '.ogg', '.oga', '.m4a', '.mp4', '.m4b', '.m4p'}
    
    def __init__(self, user_agent: str = "MusicTagger/1.0", logger=None, api_key: str = None):
        self.api_key = api_key or 'v8pQ6oyB'
        self.user_agent = user_agent
        self.mb_base = "https://musicbrainz.org/ws/2"
        self.caa_base = "https://coverartarchive.org"
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})
        
        # Setup clean logger
        self.logger = logger or logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(CleanFormatter())
            self.logger.addHandler(handler)
        # Use the passed-in logger
        self.logger = logger or logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        if not any(isinstance(h, logging.StreamHandler) for h in self.logger.handlers):
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(CleanFormatter())
            self.logger.addHandler(handler)

    def _api_call(self, url: str, params: dict | None = None, data: dict | None = None, 
                  timeout: int = 10, rate_limit: float = 0, max_retries: int = 3) -> Optional[Dict]:
        """Generic API call handler with rate limiting"""
        attempt = 0
        while True:
            if rate_limit:
                time.sleep(rate_limit)
            method = self.session.post if data else self.session.get
            kwargs = {"data": data} if data else {"params": params}

            try:
                response = method(url, timeout=timeout, **kwargs)

                if response.status_code == 429:
                    self.logger.warning("Rate limit hit for %s", url)
                    return None
                
                if response.status_code == 503:
                    attempt += 1
                    if attempt <= max_retries:
                        self.logger.warning("Server 503 error for %s (retry %d/%d)...", url, attempt, max_retries)
                        time.sleep(5)
                        continue
                    else:
                        self.logger.error("Server 503 persistent for %s after %d attempts, giving up", url, max_retries)
                        return None

                response.raise_for_status()
                return response.json() if response.text else None
            except requests.exceptions.Timeout:
                self.logger.warning(f"Connection timed out for {url}")
                return None
            except requests.exceptions.ConnectionError as e:
                self.logger.warning(f"Connection failed for {url}: {e}")
                return None
            except requests.RequestException as e:
                self.logger.debug(f"API call failed: {url} - {e}")
                return None
    
    def get_fingerprint(self, filepath: str) -> Optional[Tuple[str, int]]:
        """Extract AcoustID fingerprint using fpcalc binary"""
        fpcalc = shutil.which('fpcalc')
        if not fpcalc:
            self.logger.error("fpcalc binary not found (install chromaprint)")
            return None
        
        try:
            result = subprocess.run(
                [fpcalc, '-json', '-length', '120', filepath],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode in (0, 3):
                data = json.loads(result.stdout)
                fingerprint = data.get('fingerprint')
                duration = int(data.get('duration', 0))
                if fingerprint and duration:
                    return fingerprint, duration
        except subprocess.TimeoutExpired:
            self.logger.error("fpcalc execution timed out")
        except Exception as e:
            self.logger.error(f"Failed to generate fingerprint: {e}")
        
        return None
    
    def lookup_acoustid(self, filepath: str) -> Optional[Dict]:
        """Query AcoustID service for matching MusicBrainz metadata"""
        result = self.get_fingerprint(filepath)
        if not result:
            return None
        
        fingerprint, duration = result
        url = 'https://api.acoustid.org/v2/lookup'
        params = {
            'client': self.api_key,
            'meta': 'recordings releases releasegroups compress',
            'fingerprint': fingerprint,
            'duration': str(duration)
        }
        
        data = self._api_call(url, data=params, rate_limit=self.RATE_LIMIT_ACOUSTID)
        if data and data.get('status') == 'ok' and data.get('results'):
            best_match = max(data['results'], key=lambda x: x.get('score', 0))
            if best_match.get('score', 0) > 0.3:
                return best_match
                # Guard against a "best match" that lacks recordings
                if best_match.get('recordings'):
                    return best_match
                self.logger.debug("AcoustID best match has no recordings, discarding")
        
        return None
    
    def get_musicbrainz_data(self, entity: str, entity_id: str, inc: str = '') -> Optional[Dict]:
        """Fetch data from MusicBrainz API for specified entity type"""
        url = f"{self.mb_base}/{entity}/{entity_id}"
        params = {'fmt': 'json'}
        if inc:
            params['inc'] = inc
        return self._api_call(url, params=params, rate_limit=self.RATE_LIMIT_MB)
    
    def get_cover_art(self, release_id: str, release_group_id: str = None, artist: str = None, title: str = None) -> List[Tuple[bytes, str]]:
        """Download front cover image from Cover Art Archive with fallback to release-group"""
        headers = {'User-Agent': self.user_agent}
        endpoints = [f"{self.caa_base}/release/{release_id}"]
        if release_group_id:
            endpoints.append(f"{self.caa_base}/release-group/{release_group_id}")

        for url in endpoints:
            try:
                data = self._api_call(url, timeout=10)
                if data and 'images' in data:
                    for image in data['images']:
                        if image.get('front', False) or len(data['images']) == 1:
                            img_url = image.get('image') or image.get('thumbnails', {}).get('large')
                            if img_url:
                                res = self.session.get(img_url, headers=headers, allow_redirects=True, timeout=15)
                                if res.status_code == 200:
                                    mime_type = res.headers.get('content-type', 'image/jpeg')
                                    return [(res.content, mime_type)]
            except Exception as e:
                self.logger.debug(f"Cover art download error for {url}: {e}")
                continue

        # Direct URL fallbacks
        direct_urls = [
            f"{self.caa_base}/release/{release_id}/front",
            f"{self.caa_base}/release/{release_id}/front-500"
        ]
        if release_group_id:
            direct_urls.append(f"{self.caa_base}/release-group/{release_group_id}/front")

        for direct_url in direct_urls:
            try:
                res = self.session.get(direct_url, headers=headers, allow_redirects=True, timeout=10)
                if res.status_code == 200:
                    mime_type = res.headers.get('content-type', 'image/jpeg')
                    return [(res.content, mime_type)]
            except Exception as e:
                self.logger.debug(f"Cover art download error for direct URL: {e}")

        # iTunes fallback
        if artist and title:
            try:
                query = f"{artist} {title}"
                itunes_url = "https://itunes.apple.com/search"
                params = {"term": query, "entity": "song", "limit": 1}
                res = self.session.get(itunes_url, params=params, timeout=10)

                if res.status_code == 200:
                    result = res.json().get('results', [])
                    if result:
                        artwork_url = result[0].get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                        if artwork_url:
                            img_res = self.session.get(artwork_url, headers=headers, timeout=10)
                            if img_res.status_code == 200:
                                mime_type = img_res.headers.get('Content-Type', 'image/jpeg')
                                return [(img_res.content, mime_type)]
            except Exception as e:
                self.logger.error(f"Error fetching cover art from iTunes API: {e}")

        return []

    def extract_metadata(self, acoustid_result: Dict, release_data: Dict, recording_id: str) -> Dict:
        """Parse AcoustID and MusicBrainz response objects into normalized metadata dict"""
        metadata = {'acoustid_id': acoustid_result.get('id', '')}
        
        # 1. Try to get Title/Artist from Recordings first
        recordings = acoustid_result.get('recordings', [])
        found_recording = None
        
        # Iterate through all recordings to find the best match (non-empty title/artist)
        for rec in recordings:
            if rec.get('title') or rec.get('artists'):
                found_recording = rec
                break
        
        if found_recording:
            metadata['musicbrainz_recordingid'] = found_recording.get('id', '')
            metadata['title'] = found_recording.get('title', 'Unknown Title')
            
            artists = found_recording.get('artists', [])
            if artists:
                # Use the first artist as primary
                main_artist = artists[0]
                metadata['artist'] = main_artist.get('name', 'Unknown Artist')
                metadata['musicbrainz_artistid'] = main_artist.get('id', '')
                
                # Get sort name for the main artist
                if main_artist.get('id'):
                    artist_data = self.get_musicbrainz_data('artist', main_artist['id'])
                    metadata['artistsort'] = artist_data.get('sort-name', metadata['artist']) if artist_data else metadata['artist']
                else:
                    metadata['artistsort'] = metadata['artist']
        else:
            # Fallback: If no recording data, use placeholders
            metadata['title'] = metadata.get('title', 'Unknown Title')
            metadata['artist'] = metadata.get('artist', 'Unknown Artist')

        # 2. Get Album/Release Data
        if release_data:
            metadata['album'] = release_data.get('title', 'Unknown Album')
            metadata['musicbrainz_albumid'] = release_data.get('id', '')
            metadata['date'] = release_data.get('date', '')
            metadata['releasecountry'] = release_data.get('country', '')
            metadata['barcode'] = release_data.get('barcode', '')
            
            text_rep = release_data.get('text-representation', {})
            if text_rep.get('script'):
                metadata['script'] = text_rep['script']
            
            # Label Info
            label_info = release_data.get('label-info', [])
            if label_info and label_info[0].get('label'):
                metadata['label'] = label_info[0]['label'].get('name', '')
            
            # Album Artist & Sort Name
            artist_credit = release_data.get('artist-credit', [])
            if artist_credit and artist_credit[0].get('artist'):
                album_artist_obj = artist_credit[0]['artist']
                metadata['albumartist'] = album_artist_obj.get('name', 'Unknown Artist')
                metadata['musicbrainz_albumartistid'] = album_artist_obj.get('id', '')
                metadata['albumartistsort'] = album_artist_obj.get('sort-name', metadata['albumartist'])
            
            # Media/Track Info
            media = release_data.get('media', [])
            if media:
                medium = media[0]
                metadata['media'] = medium.get('format', '')
                metadata['discnumber'] = '1'
                metadata['totaldiscs'] = str(len(media))
                
                tracks = medium.get('tracks', [])
                matched_track_idx = -1
                
                # Try to match by Recording ID first
                for idx, track in enumerate(tracks):
                    track_rec = track.get('recording', {})
                    if found_recording and track_rec.get('id') == found_recording.get('id'):
                        matched_track_idx = idx
                        break
                
                # Fallback: If no ID match, assume it's the first track (common for singles)
                if matched_track_idx == -1 and tracks:
                    matched_track_idx = 0
                
                if matched_track_idx != -1:
                    track = tracks[matched_track_idx]
                    metadata['tracknumber'] = str(matched_track_idx + 1)
                    metadata['totaltracks'] = str(len(tracks))
                    metadata['musicbrainz_releasetrackid'] = track.get('id', '')
                    
                    isrcs = track.get('recording', {}).get('isrcs', [])
                    if isrcs:
                        metadata['isrc'] = isrcs[0]
            
            # Release Group Info
            rg = release_data.get('release-group', {})
            if rg:
                metadata['musicbrainz_releasegroupid'] = rg.get('id', '')
                
                if rg.get('primary-type'):
                    metadata['releasetype'] = rg['primary-type'].lower()
                    metadata['genre'] = rg['primary-type']
                
                if release_data.get('status'):
                    metadata['releasestatus'] = release_data['status'].lower()
                
                if rg.get('first-release-date'):
                    metadata['originaldate'] = rg['first-release-date']
                    metadata['originalyear'] = rg['first-release-date'].split('-')[0]
        
        return metadata

    def _tag_mp3(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Apply ID3 tags to MP3 container"""
        try:
            audio = ID3(filepath)
        except Exception:
            audio = ID3()
        
        clean_meta = {k: v for k, v in metadata.items() if v is not None and str(v).strip()}

        tag_map = {
            'title': lambda a, v: a.add(TIT2(encoding=3, text=v)),
            'artist': lambda a, v: a.add(TPE1(encoding=3, text=v)),
            'album': lambda a, v: a.add(TALB(encoding=3, text=v)),
            'albumartist': lambda a, v: a.add(TPE2(encoding=3, text=v)),
            'date': lambda a, v: a.add(TDRC(encoding=3, text=v)),
            'originaldate': lambda a, v: a.add(TDOR(encoding=3, text=v)),
            'genre': lambda a, v: a.add(TCON(encoding=3, text=v)),
            'label': lambda a, v: a.add(TPUB(encoding=3, text=v)),
            'isrc': lambda a, v: a.add(TSRC(encoding=3, text=v)),
            'media': lambda a, v: a.add(TMED(encoding=3, text=v)),
            'albumartistsort': lambda a, v: a.add(TSOP(encoding=3, text=v)),
        }

        for key, func in tag_map.items():
            if key in clean_meta:
                try:
                    func(audio, clean_meta[key])
                except Exception as e:
                    self.logger.warning(f"Error tagging {key}: {e}")

        if 'tracknumber' in clean_meta:
            track = f"{clean_meta['tracknumber']}/{clean_meta.get('totaltracks', '')}"
            audio.add(TRCK(encoding=3, text=track))

        if 'discnumber' in clean_meta:
            disc = f"{clean_meta['discnumber']}/{clean_meta.get('totaldiscs', '')}"
            audio.add(TPOS(encoding=3, text=disc))

        txxx_map = {
            'script': 'SCRIPT',
            'artistsort': 'ARTISTSORT',
            'originalyear': 'ORIGINALYEAR',
            'barcode': 'BARCODE',
            'musicbrainz_albumid': 'MusicBrainz Album Id',
            'musicbrainz_artistid': 'MusicBrainz Artist Id',
            'musicbrainz_albumartistid': 'MusicBrainz Album Artist Id',
            'musicbrainz_releasegroupid': 'MusicBrainz Release Group Id',
            'musicbrainz_releasetrackid': 'MusicBrainz Release Track Id',
            'releasetype': 'MusicBrainz Album Type',
            'releasestatus': 'MusicBrainz Album Status',
            'releasecountry': 'MusicBraz Album Release Country',
            'acoustid_id': 'Acoustid Id',
        }

        for meta_key, desc in txxx_map.items():
            if meta_key in clean_meta:
                audio.add(TXXX(encoding=3, desc=desc, text=clean_meta[meta_key]))

        if covers:
            for idx, (data, mime) in enumerate(covers):
                audio.add(APIC(
                    encoding=3,
                    mime='image/png' if 'png' in mime.lower() else 'image/jpeg',
                    type=3,
                    desc='Album cover' if idx == 0 else 'Cover',
                    data=data
                ))

        audio.save(filepath, v2_version=4)
        return True

    def _tag_flac(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Apply Vorbis comments and embedded pictures to FLAC container"""
        try:
            audio = FLAC(filepath)
        except Exception:
            self.logger.error(f"Could not open FLAC file for tagging: {filepath}")
            return False
        
        keys = [
            'title', 'artist', 'album', 'albumartist', 'date', 'originaldate',
            'tracknumber', 'totaltracks', 'discnumber', 'totaldiscs', 'genre',
            'label', 'isrc', 'media', 'barcode', 'originalyear',
            'musicbrainz_albumid', 'musicbrainz_artistid', 'musicbrainz_albumartistid',
            'musicbrainz_releasegroupid', 'musicbrainz_releasetrackid', 'acoustid_id'
        ]
        for key in keys:
            if key in metadata and metadata[key] is not None and str(metadata[key]).strip():
                audio[key] = metadata[key]
        
        if covers:
            audio.clear_pictures()
            for idx, (data, mime) in enumerate(covers):
                pic = Picture()
                pic.type = 3
                pic.mime = 'image/png' if 'png' in mime.lower() else 'image/jpeg'
                pic.desc = 'Album cover' if idx == 0 else 'Cover'
                pic.data = data
                audio.add_picture(pic)
        
        try:
            audio.save()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save FLAC tags: {e}")
            return False
    
    def _tag_ogg(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Apply Vorbis comments and METADATA_BLOCK_PICTURE to OGG container"""
        try:
            audio = OggVorbis(filepath)
        except Exception:
            self.logger.error(f"Could not open OGG file for tagging: {filepath}")
            return False
        
        keys = [
            'title', 'artist', 'album', 'albumartist', 'date', 'originaldate',
            'tracknumber', 'genre', 'label', 'isrc', 'musicbrainz_albumid', 'acoustid_id'
        ]
        for key in keys:
            if key in metadata and metadata[key] is not None and str(metadata[key]).strip():
                audio[key] = metadata[key]
        
        if covers:
            pic = Picture()
            pic.type = 3
            pic.mime = 'image/png' if 'png' in covers[0][1].lower() else 'image/jpeg'
            pic.desc = 'Album cover'
            pic.data = covers[0][0]
            audio['metadata_block_picture'] = base64.b64encode(pic.write()).decode('ascii')
        
        try:
            audio.save()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save OGG tags: {e}")
            return False
    
    def _tag_m4a(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Apply MP4 atoms to M4A container"""
        try:
            audio = MP4(filepath)
        except Exception:
            self.logger.error(f"Could not open M4A file for tagging: {filepath}")
            return False
        
        m4a_map = {
            'title': '\xa9nam', 'artist': '\xa9ART', 'album': '\xa9alb',
            'albumartist': 'aART', 'date': '\xa9day', 'genre': '\xa9gen'
        }
        
        for meta_key, tag_key in m4a_map.items():
            if meta_key in metadata and metadata[meta_key] is not None:
                audio[tag_key] = [metadata[meta_key]] if not isinstance(metadata[meta_key], list) else metadata[meta_key]
        
        if 'tracknumber' in metadata and metadata['tracknumber'] is not None:
            total_tracks = int(metadata.get('totaltracks', 0))
            if total_tracks == 0:
                total_tracks = int(metadata['tracknumber'])
            audio['trkn'] = [(int(metadata['tracknumber']), total)]
        
        if 'discnumber' in metadata and metadata.get('discnumber') is not None and metadata.get('totaldiscs') is not None:
            audio['disk'] = [(int(metadata['discnumber']), int(metadata['totaldiscs']))]
        
        if covers:
            m4a_covers = []
            for data, mime in covers:
                fmt = MP4Cover.FORMAT_PNG if 'png' in mime.lower() else MP4Cover.FORMAT_JPEG
                m4a_covers.append(MP4Cover(data, imageformat=fmt))
            audio['covr'] = m4a_covers
        
        try:
            audio.save()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save M4A tags: {e}")
            return False
    
    def tag_file(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]] = None) -> bool:
        """Dispatch tagging logic based on audio file extension"""
        try:
            ext = os.path.splitext(filepath)[1].lower()
            
            taggers = {
                '.mp3': self._tag_mp3,
                '.flac': self._tag_flac,
                '.ogg': self._tag_ogg, '.oga': self._tag_ogg,
                '.m4a': self._tag_m4a, '.mp4': self._tag_m4a, '.m4b': self._tag_m4a, '.m4p': self._tag_m4a
            }
            
            tagger = taggers.get(ext)
            if not tagger:
                self.logger.error(f"Unsupported audio format: {ext}")
                return False
            
            return tagger(filepath, metadata, covers or [])
        
        except Exception as e:
            self.logger.error(f"Tagging operation failed: {e}")
            return False
    
    def process_file(self, filepath: str, save_cover: bool = False) -> bool:
        """Execute full pipeline for fingerprinting, fetching metadata, and tagging a file"""
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in self.SUPPORTED_FORMATS:
            self.logger.error(f"Unsupported file type: {ext}")
            return False
        self.logger.info(f"Processing: {filename}")
        
        # 1. Lookup Fingerprint
        acoustid_result = self.lookup_acoustid(filepath)
        if not acoustid_result:
            self.logger.warning("No AcoustID match found")
            return False
        
        score = acoustid_result.get('score', 0) * 100
        self.logger.info(f"Match Score: {score:.1f}%")
        
        # 2. Extract release parameters - IMPROVED LOGIC
        release_id = None
        recording_id = None
        
        recordings = acoustid_result.get('recordings', [])
        
        # Iterate through ALL recordings in the result to find a valid release
        for rec in recordings:
            recording_id = rec.get('id')
            
            # Check all releasegroups in this recording
            releasegroups = rec.get('releasegroups', [])
            for rg in releasegroups:
                releases = rg.get('releases', [])
                if releases:
                    # Take the first valid release found
                    release_id = releases[0]['id']
                    break
            
            # If we found a release, stop searching other recordings
            if release_id:
                break
        
        if not release_id:
            self.logger.warning("No MusicBrainz release found for any recording/rg")
            return False
        
        # 3. Fetch Release Data
        self.logger.info("Fetching metadata from MusicBrainz...")
        release_data = self.get_musicbrainz_data(
            'release', release_id,
            'artists+recordings+release-groups+labels+media+isrcs+artist-credits'
        )
        
        if not release_data:
            self.logger.error("Failed to fetch release metadata")
            return False
        
        # 4. Consolidate metadata
        metadata = self.extract_metadata(acoustid_result, release_data, recording_id)

        if metadata.get('title') in (None, 'Unknown Title') and release_data:
            for medium in release_data.get('media', []):
                for track in medium.get('tracks', []):
                    rec = track.get('recording', {})
                    if rec.get('id') == recording_id or recording_id is None:
                        metadata['title'] = rec.get('title') or track.get('title') or metadata['title']
                        # Artist info for compilations is stored in the track‑artist‑credit
                        if not metadata.get('artist') or metadata['artist'] == 'Unknown Artist':
                            # Prefer the track‑artist credit if present
                            if rec.get('artist-credit'):
                                metadata['artist'] = rec['artist-credit'][0].get('name', metadata['artist'])
                        break
                if metadata.get('title') and metadata.get('artist'):
                    break
        
        artist_name = metadata.get('artist', 'Unknown Artist')
        track_title = metadata.get('title', 'Unknown Title')
        album_name = metadata.get('album', 'Unknown Album')
        
        self.logger.info(f"Found: {artist_name} - {track_title} ({album_name})")
        
        # 5. Fetch cover art
        rg_id = metadata.get('musicbrainz_releasegroupid')
        self.logger.info("Fetching cover art...")
        
        covers = self.get_cover_art(
            release_id, 
            release_group_id=rg_id,
            artist=artist_name,
            title=track_title
        )
        
        if covers:
            self.logger.info(f"Cover art fetched ({len(covers)} image(s))")
            
            if save_cover:
                for idx, (data, mime) in enumerate(covers):
                    ext = 'png' if 'png' in mime.lower() else 'jpg'
                    cover_path = os.path.join(
                        os.path.dirname(filepath), 
                        f'cover{idx if idx > 0 else ""}.{ext}'
                    )
                    try:
                        with open(cover_path, 'wb') as f:
                            f.write(data)
                        self.logger.info(f"Cover saved: {cover_path}")
                    except Exception as e:
                        self.logger.error(f"Failed to save cover art: {e}")
        else:
            self.logger.warning("No cover art found")
        
        # 6. Write metadata tags
        self.logger.info("Writing tags...")
        success = self.tag_file(filepath, metadata, covers)
        
        if success:
            self.logger.info(f"[OK] Tagged successfully: {filename}")
        else:
            self.logger.error(f"[FAIL] Failed to tag: {filename}")
        
        return success
    
    def process_directory(self, directory: str, recursive: bool = False, save_cover: bool = False):
        """Batch process supported audio files within a directory"""
        files = []
        
        if recursive:
            for root, _, filenames in os.walk(directory):
                files.extend(
                    os.path.join(root, f) for f in filenames
                    if os.path.splitext(f)[1].lower() in self.SUPPORTED_FORMATS
                )
        else:
            try:
                files = [
                    os.path.join(directory, f) for f in os.listdir(directory)
                    if os.path.splitext(f)[1].lower() in self.SUPPORTED_FORMATS
                ]
            except Exception as e:
                self.logger.error(f"Error reading directory {directory}: {e}")
                return
        
        if not files:
            self.logger.warning("No supported music files found")
            return
        
        self.logger.info(f"Found {len(files)} file(s) in {directory}")
        
        results = {'success': 0, 'failed': 0}
        try:
           from tqdm import tqdm
        except ImportError:   # fallback – tqdm is optional
           tqdm = lambda x, **kw: x
        for filepath in tqdm(files, desc="Tagging files", unit="file"):
            try:
                if self.process_file(filepath, save_cover):
                    results['success'] += 1
                else:
                    results['failed'] += 1
            except Exception as e:
                self.logger.error(f"Error processing {filepath}: {e}")
                results['failed'] += 1
        self.logger.info(f"Batch complete: {results['success']} success, {results['failed']} failed")

def main():
    DEFAULT_ACOUSTID_KEY = "v8pQ6oyB"
    parser = argparse.ArgumentParser(
        description='MusicBrainz Audio Tagger CLI',
        prog='music_tagger',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="AcoustID API key can also be supplied via the ACOUSTID_API_KEY env var."
        )
    # Global flags
    parser.add_argument("-u", "--user-agent", default="MusicTagger/1.0",
                        help="Custom HTTP User‑Agent string")
    parser.add_argument("-k", "--acoustid-key", default=os.getenv("ACOUSTID_API_KEY", DEFAULT_ACOUSTID_KEY),
                        help="AcoustID API key (env ACOUSTID_API_KEY overrides)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress console output (logs still go to app.log)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable DEBUG‑level logging")

    subparsers = parser.add_subparsers(dest="command", required=True)


    # tag (single file)
    tag_parser = subparsers.add_parser("tag", help="Tag a single audio file")
    tag_parser.add_argument("path", help="Path to the audio file")
    tag_parser.add_argument("-c", "--save-cover", action="store_true",
                            help="Save cover art as a separate file")

    # batch (directory)
    batch_parser = subparsers.add_parser('batch', help='Recursively tag a directory')
    batch_parser.add_argument('directory', help='Root folder containing audio files')
    batch_parser.add_argument('-r', '--recursive', action='store_true',help='Descend into sub-folders')
    batch_parser.add_argument('-c', '--save-cover', action='store_true', help='Save cover art as seperate files')

    args = parser.parse_args()

    # Set up a module‑level logger (simple console + file)
    logger = logging.getLogger("music_tagger")
    logger.setLevel(logging.DEBUG)                     # internal logger stays DEBUG
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        # File log (always present)
        log_dir = Path.home() / ".local" / "share" / "music-downloader"
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.addHandler(logging.FileHandler(log_dir / "app.log", encoding="utf-8"))
    # Console handler – respect --quiet / --verbose
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(CleanFormatter())
        logger.addHandler(console_handler)

    if args.verbose:
        logger.setLevel(logging.DEBUG)
    elif args.quiet:
        logger.setLevel(logging.ERROR)
    else:
        logger.setLevel(logging.INFO)

    tagger = MusicTagger(args.user_agent, api_key=args.acoustid_key)

    # Dispatch sub-commands
    if args.command == 'tag':
        if not os.path.isfile(args.path):
            logger.error(f"File not found: {args.path}")
            sys.exit(2)
        success = tagger.process_file(args.path, save_cover=args.save_cover)
        sys.exit(0 if success else 1)
    
    elif args.command == 'batch':
        if not os.path.isdir(args.directory):
            logger.error(f"Directory not found: {args.directory}")
            sys.exit(2)
        tagger.process_directory(
            args.directory,
            recursive=args.recursive,
            save_cover=args.save_cover
        )
        sys.exit(0)

if __name__ == '__main__':
    main()