#!/usr/bin/env python3
"""
Music Tagger - Automated metadata tagging using AcoustID, MusicBrainz, and Genius
Supports: MP3, FLAC, OGG, M4A

Tuned for Navidrome libraries built from playlists (.m3u) or flat directories:
every track is normalized so that tracks of one album always merge into one
album, and album-splitting identifiers are purged from the files.
"""

import os
import json
import time
import logging
import re
import subprocess
import shutil
import base64
from typing import Optional, Dict, List, Tuple
import requests

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TDOR, TRCK, APIC, TPE2, TCON, TPUB, TSRC, TMED, TSOP, TXXX
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis


class MusicTagger:
    """Automated music metadata tagger with multi-source fallback"""
    
    RATE_LIMIT_ACOUSTID = 0.33  # 3 req/sec
    RATE_LIMIT_MB = 1.0  # 1 req/sec (MusicBrainz allows 1/sec)
    SUPPORTED_FORMATS = {'.mp3', '.flac', '.ogg', '.oga', '.m4a', '.mp4', '.m4b', '.m4p'}

    # If True, date / originaldate / originalyear are all collapsed to the release
    # group's original YEAR (falling back to the release year). This keeps every
    # track of one album on the same year so Navidrome never splits it because a
    # digital release is dated a few days/months after the physical one, while a
    # 2014 EP and a 2017 album with the same title still stay distinct.
    # Set to False to keep the full dates exactly as MusicBrainz/Genius return them.
    UNIFY_RELEASE_YEAR = True

    # --- Album-splitting identifiers to purge -------------------------------
    # ID3 frames removed by frame id (UFID = MusicBrainz recording id container)
    ID3_PURGE_FRAMES = ('UFID', 'TPOS', 'TSST')

    # TXXX descriptions removed (compared case-insensitively)
    ID3_PURGE_TXXX = (
        'MusicBrainz Album Id',
        'MusicBrainz Release Group Id',
        'MusicBrainz Track Id',
        'MusicBrainz Release Track Id',
        'MusicBrainz Artist Id',
        'MusicBrainz Album Artist Id',
        'MusicBrainz Original Album Id',
        'BARCODE',
        'CATALOGNUMBER',
        'AcoustID Fingerprint',
        'AcoustID Id',
    )

    # Vorbis comment keys (FLAC / OGG) that cause the same splitting
    VORBIS_PURGE_KEYS = (
        'musicbrainz_albumid', 'musicbrainz_releasegroupid', 'musicbrainz_trackid',
        'musicbrainz_releasetrackid', 'musicbrainz_artistid', 'musicbrainz_albumartistid',
        'barcode', 'catalognumber', 'acoustid_fingerprint', 'acoustid_id',
        'discnumber', 'totaldiscs', 'disctotal', 'discsubtitle',
    )

    # MP4 freeform atoms (names after "----:com.apple.iTunes:"), compared case-insensitively
    MP4_PURGE_FREEFORM = (
        'musicbrainz album id', 'musicbrainz release group id', 'musicbrainz track id',
        'musicbrainz release track id', 'musicbrainz artist id', 'musicbrainz album artist id',
        'barcode', 'catalognumber', 'acoustid fingerprint', 'acoustid id',
    )

    # Trailing MusicBrainz disambiguation in parentheses, e.g. "Gına (TUR)",
    # "Sagopa Kajmer (2)", "Artist (Turkish Hip Hop Group)". Only matches at the end
    # of a name (or right before a list separator) and never eats "(feat. ...)".
    ARTIST_DISAMBIGUATION_RE = re.compile(
        r'\s*\((?!\s*(?:feat|ft|featuring)\b)[^()]*\)\s*(?=$|[,;&])',
        flags=re.IGNORECASE
    )

    # "Primary Artist feat. Someone" -> "Primary Artist" (used for albumartist only)
    FEATURING_RE = re.compile(
        r'\s*[\(\[]?\s*\b(?:feat|ft|featuring)\b\.?.*$',
        flags=re.IGNORECASE
    )

    # Edition / remaster / publisher noise in album titles.
    # A bracket, or a hyphen preceded by whitespace, must start the suffix, so
    # words like "Pre-Deluxe" are not cut in the middle.
    ALBUM_NOISE_RE = re.compile(
        r'(?:\s+[-–—]\s*|\s*[\(\[\{]\s*)'
        r'(?:\d{4}\s*edit|remaster(?:ed)?|deluxe|edition|cd\s*\d+|disc\s*\d+)'
        r'[\)\]\}]?.*$',
        flags=re.IGNORECASE
    )
    
    def __init__(self, logger: logging.Logger = None, acoustid_key: str = None, genius_token: str = None,
                 options: Optional[Dict] = None):
        """
        Initialize tagger with API credentials
        
        Args:
            logger: Custom logger instance
            acoustid_key: AcoustID API key (defaults to public key)
            genius_token: Genius API access token
        """
        self.acoustid_key = acoustid_key or os.getenv('ACOUSTID_API_KEY', 'v8pQ6oyB')
        self.genius_token = genius_token or os.getenv('GENIUS_TOKEN')
        self.mb_base = "https://musicbrainz.org/ws/2"
        self.caa_base = "https://coverartarchive.org"
        
        # Source toggles; everything is enabled unless explicitly turned off
        options = options or {}
        self.use_acoustid = options.get('use_acoustid', True)
        self.use_mb_search = options.get('use_musicbrainz_search', True)
        self.use_genius = options.get('use_genius', True)
        self.use_caa = options.get('use_caa', True)
        self.use_itunes = options.get('use_itunes', True)
        self.use_genius_cover = options.get('use_genius_cover', True)
        
        # Smart rate limiting: track last request time instead of always sleeping
        self._last_mb_request = 0
        self._last_acoustid_request = 0
        
        # Setup HTTP session with connection pooling
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'MusicTagger/2.0'})
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=1
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(__name__)
            if not self.logger.handlers and not logging.getLogger().handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
                self.logger.addHandler(handler)
                self.logger.setLevel(logging.INFO)

    @staticmethod
    def options_from_config(config: Dict) -> Dict:
        """Map app config keys to tagger source toggles (everything defaults to enabled)"""
        return {
            'use_acoustid': config.get('tag_use_acoustid', True),
            'use_musicbrainz_search': config.get('tag_use_musicbrainz_search', True),
            'use_genius': config.get('tag_use_genius', True),
            'use_caa': config.get('cover_use_caa', True),
            'use_itunes': config.get('cover_use_itunes', True),
            'use_genius_cover': config.get('cover_use_genius', True),
        }

    # ------------------------------------------------------------------
    # Normalization helpers (Navidrome-safe metadata)
    # ------------------------------------------------------------------

    def _clean_artist_name(self, name: Optional[str]) -> str:
        """Strip MusicBrainz disambiguation suffixes: 'Gına (TUR)' -> 'Gına', 'X (2)' -> 'X'"""
        if not name:
            return ''
        original = str(name).strip()
        cleaned = original
        # Loop so stacked suffixes like "X (2) (TUR)" are fully removed
        while True:
            stripped = self.ARTIST_DISAMBIGUATION_RE.sub('', cleaned).strip()
            if stripped == cleaned:
                break
            cleaned = stripped
        return cleaned or original

    def _strip_featuring(self, name: Optional[str]) -> str:
        """Reduce 'Artist feat. Guest' to the primary artist (used for albumartist)"""
        if not name:
            return ''
        original = str(name).strip()
        cleaned = self.FEATURING_RE.sub('', original).strip()
        return cleaned or original

    def _clean_album_name(self, album: Optional[str]) -> str:
        """Strip trailing dots/ellipses and edition/remaster/publisher suffixes"""
        if not album:
            return ''
        original = str(album).strip()
        cleaned = original

        def strip_trailing_dots(text: str) -> str:
            return re.sub(r'[.\u2026\s]+$', '', text).strip()

        cleaned = strip_trailing_dots(cleaned)
        cleaned = self.ALBUM_NOISE_RE.sub('', cleaned).strip()
        cleaned = strip_trailing_dots(cleaned)
        return cleaned or original

    @staticmethod
    def _year_only(value) -> Optional[str]:
        """Extract a 4-digit year from '2014', '2014-03' or '2014-03-21'"""
        if not value:
            return None
        match = re.match(r'\s*(\d{4})', str(value))
        return match.group(1) if match else None

    def _normalize_metadata(self, metadata: Dict) -> Dict:
        """
        Uniform normalization applied to every metadata dict right before tagging,
        regardless of which source (MusicBrainz / Genius) produced it.
        """
        meta = dict(metadata)

        # Artist / AlbumArtist: strip disambiguation, albumartist always the clean primary artist
        artist = self._clean_artist_name(meta.get('artist'))
        if artist:
            meta['artist'] = artist

        albumartist = self._clean_artist_name(meta.get('albumartist'))
        if not albumartist and artist:
            albumartist = artist
        albumartist = self._strip_featuring(albumartist)
        if albumartist:
            meta['albumartist'] = albumartist

        if artist != (metadata.get('artist') or '') or albumartist != (metadata.get('albumartist') or ''):
            self.logger.debug(
                f"Artist normalized: '{metadata.get('artist')}' -> '{meta.get('artist')}', "
                f"albumartist -> '{meta.get('albumartist')}'"
            )

        # Album: strip publisher / re-issue noise
        if meta.get('album'):
            album_clean = self._clean_album_name(meta['album'])
            if album_clean != meta['album']:
                self.logger.debug(f"Album normalized: '{meta['album']}' -> '{album_clean}'")
            if album_clean:
                meta['album'] = album_clean
            else:
                meta.pop('album', None)

        # Release year: keep it (distinguishes 2014 EP from 2017 album), but make it
        # identical for every track of the same release group
        if self.UNIFY_RELEASE_YEAR:
            year = (self._year_only(meta.get('originaldate'))
                    or self._year_only(meta.get('originalyear'))
                    or self._year_only(meta.get('date')))
            if year:
                meta['date'] = year
                meta['originaldate'] = year
                meta['originalyear'] = year

        # Disc info makes Navidrome create "Disc 1" / "Disc 2" sub-albums
        for key in ('discnumber', 'totaldiscs', 'discsubtitle'):
            meta.pop(key, None)

        return meta

    def _api_call(self, url: str, params: Dict = None, data: Dict = None, 
                  timeout: int = 5, rate_limit: float = 0, max_retries: int = 2) -> Optional[Dict]:
        """Generic API call handler with smart rate limiting and retries"""
        if rate_limit > 0:
            if 'musicbrainz.org' in url:
                elapsed = time.time() - self._last_mb_request
                if elapsed < rate_limit:
                    time.sleep(rate_limit - elapsed)
                self._last_mb_request = time.time()
            elif 'acoustid.org' in url:
                elapsed = time.time() - self._last_acoustid_request
                if elapsed < rate_limit:
                    time.sleep(rate_limit - elapsed)
                self._last_acoustid_request = time.time()
        
        method = self.session.post if data else self.session.get
        kwargs = {"data": data} if data else {"params": params}
        
        for attempt in range(max_retries):
            try:
                response = method(url, timeout=timeout, **kwargs)
                
                if response.status_code == 429:
                    self.logger.warning(f"Rate limit hit: {url}")
                    return None
                
                if response.status_code == 503:
                    if attempt < max_retries - 1:
                        self.logger.debug(f"Server 503 (retry {attempt + 1}/{max_retries})")
                        time.sleep(2)
                        continue
                    self.logger.error(f"Server 503 persistent after {max_retries} attempts")
                    return None
                
                response.raise_for_status()
                return response.json() if response.text else None
                
            except requests.exceptions.Timeout:
                self.logger.warning(f"Timeout: {url}")
                if attempt == max_retries - 1:
                    return None

            except requests.exceptions.RequestException as e:
                self.logger.debug(f"Request failed: {url} - {e}")
                if attempt == max_retries - 1:
                    return None
        
        return None

    def get_fingerprint(self, filepath: str) -> Optional[Tuple[str, int]]:
        """Extract AcoustID fingerprint using fpcalc"""
        fpcalc = shutil.which('fpcalc')
        if not fpcalc:
            self.logger.error("fpcalc not found (install chromaprint)")
            return None
        
        try:
            result = subprocess.run(
                [fpcalc, '-json', '-length', '120', filepath],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode not in (0, 3):
                return None
            
            stdout = result.stdout.strip()
            start = stdout.find('{')
            end = stdout.rfind('}')
            if start == -1 or end == -1:
                return None
            
            data = json.loads(stdout[start:end+1])
            fingerprint = data.get('fingerprint')
            duration = int(float(data.get('duration', 0)))
            
            return (fingerprint, duration) if fingerprint and duration else None
            
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            self.logger.debug(f"Fingerprint extraction failed: {e}")
            return None

    def search_musicbrainz(self, artist: str, title: str) -> Optional[Dict]:
        """Search MusicBrainz by artist and title when AcoustID fails"""
        try:
            clean_artist = re.sub(r'[\(\[].*?[\)\]]', '', artist).strip()
            clean_title = re.sub(r'[\(\[].*?[\)\]]', '', title).strip()
            
            query = f'artist:"{clean_artist}" AND recording:"{clean_title}"'
            params = {
                'fmt': 'json',
                'query': query,
                'limit': 5
            }
            
            self.logger.debug(f"MusicBrainz search: {query}")
            
            data = self._api_call(
                f"{self.mb_base}/recording",
                params=params,
                rate_limit=self.RATE_LIMIT_MB
            )
            
            if not data or not data.get('recordings'):
                return None
            
            recordings = data['recordings']
            self.logger.debug(f"MusicBrainz found {len(recordings)} recordings")
            
            best_match = None
            best_score = 0
            
            for rec in recordings:
                score = 0
                rec_title = rec.get('title', '').lower()
                rec_artist = rec.get('artist-credit', [{}])[0].get('name', '').lower() if rec.get('artist-credit') else ''
                
                if clean_title.lower() in rec_title or rec_title in clean_title.lower():
                    score += 2
                if clean_artist.lower() in rec_artist or rec_artist in clean_artist.lower():
                    score += 2
                
                if score > best_score and rec.get('releases'):
                    best_score = score
                    best_match = rec
            
            if best_match:
                self.logger.info(f"MusicBrainz search match: {best_match.get('title')} (score: {best_score})")
                releases = best_match.get('releases', [])
                if releases:
                    return {
                        'recording_id': best_match.get('id'),
                        'release_id': releases[0].get('id'),
                        'title': best_match.get('title'),
                        'artist': best_match.get('artist-credit', [{}])[0].get('name', '') if best_match.get('artist-credit') else ''
                    }
            
            return None
            
        except Exception as e:
            self.logger.debug(f"MusicBrainz search error: {e}")
            return None

    def lookup_acoustid(self, filepath: str) -> Optional[Dict]:
        """Query AcoustID for MusicBrainz metadata"""
        result = self.get_fingerprint(filepath)
        if not result:
            return None
        
        fingerprint, duration = result
        params = {
            'client': self.acoustid_key,
            'meta': 'recordings releases releasegroups compress',
            'fingerprint': fingerprint,
            'duration': str(duration)
        }
        
        data = self._api_call('https://api.acoustid.org/v2/lookup', data=params, 
                             rate_limit=self.RATE_LIMIT_ACOUSTID)
        
        if not data or data.get('status') != 'ok':
            return None
        
        results = data.get('results', [])
        if not results:
            return None
        
        with_recordings = [r for r in results if r.get('recordings')]
        return max(with_recordings or results, key=lambda x: x.get('score', 0))

    def _genius_track_number(self, album_id, song_id, headers: Dict) -> Optional[Dict]:
        """Fetch an album's tracklist from Genius and locate a song's position in it"""
        try:
            resp = self.session.get(
                f"https://api.genius.com/albums/{album_id}/tracks",
                params={"per_page": 50},
                headers=headers, timeout=3
            )
            resp.raise_for_status()
            tracks = resp.json().get("response", {}).get("tracks", [])
            
            if not tracks:
                return None
            
            for track in tracks:
                track_song = track.get("song", {})
                if track_song.get("id") == song_id:
                    number = track.get("number")
                    if number is None:
                        return None
                    return {
                        "tracknumber": str(number),
                        "totaltracks": str(len(tracks)),
                    }
            
            return None
        except Exception as e:
            self.logger.debug(f"Genius track number lookup error: {e}")
            return None

    def search_genius(self, artist: str, title: str) -> Optional[Dict]:
        """Search Genius for track metadata with fuzzy matching"""
        if not self.use_genius:
            self.logger.debug("Genius disabled in settings")
            return None
        if not self.genius_token:
            return None
        
        headers = {"Authorization": f"Bearer {self.genius_token}"}
        
        clean_title = title
        clean_title = re.sub(r'[\(\[\{](?:official|music|lyric)?\s*(?:video|audio|hd|hq)[\)\]\}]', '', clean_title, flags=re.IGNORECASE)
        clean_title = re.sub(r'[\(\[\{]\s*\d{4}\s*[\)\]\}]', '', clean_title)
        clean_title = ' '.join(clean_title.split())
        
        self.logger.debug(f"Genius search cleaned: '{title}' → '{clean_title}'")
        
        try:
            resp = self.session.get("https://api.genius.com/search", 
                                   params={"q": f"{artist} {clean_title}"}, 
                                   headers=headers, timeout=3)
            resp.raise_for_status()
            hits = resp.json().get("response", {}).get("hits", [])
            
            self.logger.debug(f"Genius search: '{artist} {clean_title}' returned {len(hits)} results")
            
            if not hits:
                self.logger.debug("No Genius results found")
                return None
            
            best_match = None
            best_score = 0
            
            for hit in hits[:5]:
                result = hit.get("result", {})
                result_title = result.get("title", "").lower()
                result_artist = result.get("primary_artist", {}).get("name", "").lower()
                
                score = 0
                if clean_title.lower() in result_title or result_title in clean_title.lower():
                    score += 1
                if artist.lower() in result_artist or result_artist in artist.lower():
                    score += 1
                if result_title == clean_title.lower():
                    score += 2
                
                if score > best_score:
                    best_score = score
                    best_match = result
            
            if not best_match:
                best_match = hits[0]["result"]
            
            self.logger.debug(f"Best Genius match: {best_match.get('title')} by {best_match.get('primary_artist', {}).get('name')} (score: {best_score})")
            song_api_url = best_match["api_path"]
        except Exception as e:
            self.logger.debug(f"Genius search error: {e}")
            return None
        
        try:
            resp = self.session.get(f"https://api.genius.com{song_api_url}", 
                                   headers=headers, timeout=3)
            resp.raise_for_status()
            song = resp.json().get("response", {}).get("song", {})
            
            result = {
                "title": song.get("title"),
                "artist": song.get("primary_artist", {}).get("name"),
                "album": None,
                "year": None,
                "release_date": None,
                "producer": None,
                "writer": None,
                "cover_art_url": song.get("song_art_image_url"),
            }
            
            album = song.get("album")
            if album:
                result["album"] = album.get("name") or album.get("title")
                release_date = album.get("release_date_components")
                if release_date and release_date.get("year"):
                    try:
                        year = int(release_date["year"])
                        result["year"] = str(year)
                        result["release_date"] = f"{year:04d}"
                        if release_date.get("month"):
                            result["release_date"] += f"-{int(release_date['month']):02d}"
                        if release_date.get("day"):
                            result["release_date"] += f"-{int(release_date['day']):02d}"
                    except (ValueError, TypeError):
                        pass
            
            if not result["year"]:
                release_date_str = song.get("release_date") or song.get("release_date_for_display")
                if release_date_str:
                    year_match = re.search(r'\b(19|20)\d{2}\b', release_date_str)
                    if year_match:
                        result["year"] = year_match.group(0)
                        result["release_date"] = result["year"]
            
            producer_artists = song.get("producer_artists", [])
            if producer_artists:
                result["producer"] = ", ".join([p["name"] for p in producer_artists if p.get("name")])
            
            writer_artists = song.get("writer_artists", [])
            if writer_artists:
                result["writer"] = ", ".join([w["name"] for w in writer_artists if w.get("name")])
            
            if not result["producer"] or not result["writer"]:
                for perf in song.get("custom_performances", []):
                    label = perf.get("label", "").lower()
                    artists = ", ".join([a["name"] for a in perf.get("artists", []) if a.get("name")])
                    if not result["producer"] and "produc" in label:
                        result["producer"] = artists
                    if not result["writer"] and ("writ" in label or "lyr" in label):
                        result["writer"] = artists
            
            album_id = song.get("album", {}).get("id") if song.get("album") else None
            song_id = song.get("id")
            if album_id and song_id:
                track_info = self._genius_track_number(album_id, song_id, headers)
                if track_info:
                    result["tracknumber"] = track_info["tracknumber"]
                    result["totaltracks"] = track_info["totaltracks"]
            
            return result
            
        except Exception as e:
            self.logger.debug(f"Genius detail error: {e}")
            return None

    def get_cover_art(self, release_id: str, release_group_id: str = None, 
                     artist: str = None, title: str = None) -> List[Tuple[bytes, str]]:
        """Download cover art with multi-source fallback"""
        headers = {'User-Agent': 'MusicTagger/2.0'}
        
        if release_id and self.use_caa:
            try:
                url = f"{self.caa_base}/release/{release_id}"
                resp = self.session.get(url, headers=headers, timeout=2)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and 'images' in data:
                        for image in data['images']:
                            if image.get('front') or len(data['images']) == 1:
                                img_url = image.get('image') or image.get('thumbnails', {}).get('large')
                                if img_url:
                                    img_resp = self.session.get(img_url, headers=headers, timeout=2)
                                    if img_resp.status_code == 200:
                                        return [(img_resp.content, img_resp.headers.get('content-type', 'image/jpeg'))]
            except Exception:
                self.logger.debug("Cover Art Archive timeout, trying iTunes")

        if release_group_id and self.use_caa:
            try:
                url = f"{self.caa_base}/release-group/{release_group_id}"
                resp = self.session.get(url, headers=headers, timeout=2)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and 'images' in data:
                        for image in data['images']:
                            if image.get('front') or len(data['images']) == 1:
                                img_url = image.get('image') or image.get('thumbnails', {}).get('large')
                                if img_url:
                                    img_resp = self.session.get(img_url, headers=headers, timeout=2)
                                    if img_resp.status_code == 200:
                                        return [(img_resp.content, img_resp.headers.get('content-type', 'image/jpeg'))]
            except Exception:
                self.logger.debug("Release-Group CAA timeout/fail, trying iTunes")
        
        if artist and title and self.use_itunes:
            try:
                res = self.session.get("https://itunes.apple.com/search", 
                                      params={"term": f"{artist} {title}", "entity": "song", "limit": 1},
                                      timeout=3)
                if res.status_code == 200:
                    results = res.json().get('results', [])
                    if results:
                        artwork_url = results[0].get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                        if artwork_url:
                            img_res = self.session.get(artwork_url, headers=headers, timeout=3)
                            if img_res.status_code == 200:
                                return [(img_res.content, img_res.headers.get('Content-Type', 'image/jpeg'))]
            except Exception:
                pass
        
        return []

    def _read_existing_tags(self, filepath: str) -> Tuple[Optional[str], Optional[str]]:
        """Read artist/title directly from the file's own tags, if both are present"""
        try:
            audio = MutagenFile(filepath, easy=True)
        except Exception as e:
            self.logger.debug(f"Could not read existing tags: {e}")
            return None, None

        if not audio:
            return None, None

        artist_list = audio.get('artist')
        title_list = audio.get('title')

        artist = artist_list[0].strip() if artist_list and artist_list[0].strip() else None
        title = title_list[0].strip() if title_list and title_list[0].strip() else None

        if artist and title:
            return artist, title
        return None, None

    def _guess_artist_from_path(self, filepath: str) -> str:
        """
        Infer the artist from the directory hierarchy when the filename alone
        has no 'Artist - Title' separator. Standard layout is
        Artist/Album/Track, so the artist is two levels up whenever that
        level exists; falls back to the immediate parent for a flat
        Artist/Track layout with no album folder.
        """
        parent_dir = os.path.dirname(filepath)
        grandparent_dir = os.path.dirname(parent_dir)

        parent = os.path.basename(parent_dir)
        grandparent = os.path.basename(grandparent_dir)

        if grandparent and grandparent_dir not in (os.sep, ''):
            return grandparent.strip() or "Unknown Artist"

        return parent.strip() or "Unknown Artist"

    def _extract_search_guesses(self, filepath: str) -> Tuple[str, str]:
        """
        Two-tier artist/title guess used before AcoustID/MusicBrainz/Genius search.

        Tier 1: if the file already carries artist+title tags (re-tagging an
        already-organized library), use them directly - no filename/path parsing.
        Tier 2: otherwise parse the filename, stripping a leading track number,
        splitting on ' - ' when present, and falling back to the directory
        hierarchy for the artist when it isn't.
        """
        existing_artist, existing_title = self._read_existing_tags(filepath)
        if existing_artist and existing_title:
            self.logger.debug(f"Using existing tags: '{existing_artist}' - '{existing_title}'")
            return existing_artist, existing_title

        filename = os.path.basename(filepath)
        base_name = os.path.splitext(filename)[0]
        cleaned = re.sub(r'^\d+[\s\.\-_]+', '', base_name).strip()

        if ' - ' in cleaned:
            artist_guess, title_guess = cleaned.split(' - ', 1)
            return artist_guess.strip() or "Unknown Artist", title_guess.strip() or cleaned

        title_guess = cleaned or base_name
        artist_guess = self._guess_artist_from_path(filepath)
        return artist_guess, title_guess

    def _locate_track_in_media(self, media: List[Dict], target_recording_id: Optional[str], title: str) -> Optional[Dict]:
        """
        Find a track across all discs of a release, matching by recording ID first
        and by title only as a fallback. Returns a cumulative track number
        spanning every disc.
        """
        total_tracks = sum(len(medium.get('tracks', [])) for medium in media)
        title_lower = (title or '').lower()

        for by_id in (True, False):
            offset = 0
            for medium in media:
                tracks = medium.get('tracks', [])
                for track_idx, track in enumerate(tracks):
                    track_rec = track.get('recording') or {}
                    if by_id:
                        hit = bool(target_recording_id) and track_rec.get('id') == target_recording_id
                    else:
                        track_title = track_rec.get('title') or track.get('title') or ''
                        hit = bool(title_lower) and track_title.lower() == title_lower
                    if not hit:
                        continue

                    try:
                        position = int(track.get('position') or track_idx + 1)
                    except (ValueError, TypeError):
                        position = track_idx + 1

                    result = {
                        'tracknumber': str(offset + position),
                        'totaltracks': str(total_tracks),
                        'media': medium.get('format', ''),
                    }
                    isrcs = track_rec.get('isrcs', [])
                    if isrcs:
                        result['isrc'] = isrcs[0]
                    if track_rec.get('title'):
                        result['title'] = track_rec['title']
                    return result
                offset += len(tracks)

        self.logger.warning(f"Track not found in release media (recording id: {target_recording_id}, title: '{title}')")
        return None

    def _extract_musicbrainz_from_search(self, release_data: Dict, recording_id: str, artist: str, title: str) -> Dict:
        """Extract metadata from MusicBrainz when found via text search (not AcoustID)"""
        metadata = {
            'title': title,
            'artist': artist,
            'album': release_data.get('title', 'Unknown Album'),
            'date': release_data.get('date', ''),
        }
        
        if release_data:
            metadata.update({
                'releasecountry': release_data.get('country', ''),
                'barcode': release_data.get('barcode', ''),
            })
            
            label_info = release_data.get('label-info', [])
            if label_info and label_info[0].get('label'):
                metadata['label'] = label_info[0]['label'].get('name', '')
            
            artist_credit = release_data.get('artist-credit', [])
            if artist_credit and artist_credit[0].get('artist'):
                metadata['albumartist'] = artist_credit[0]['artist'].get('name', '')
            
            media = release_data.get('media', [])
            if media:
                match = self._locate_track_in_media(media, recording_id, title)
                if match:
                    metadata['tracknumber'] = match['tracknumber']
                    metadata['totaltracks'] = match['totaltracks']
                    metadata['media'] = match['media']
                    if match.get('isrc'):
                        metadata['isrc'] = match['isrc']
                    if match.get('title'):
                        metadata['title'] = match['title']
            
            rg = release_data.get('release-group', {})
            if rg:
                metadata['musicbrainz_releasegroupid'] = rg.get('id', '')
                rg_date = rg.get('first-release-date')
                if rg_date:
                    metadata['originaldate'] = rg_date
                    metadata['originalyear'] = rg_date.split('-')[0]
                if rg.get('primary-type'):
                    metadata['genre'] = rg['primary-type']

            metadata.setdefault('originaldate', release_data.get('date', ''))
        
        return metadata

    def _extract_musicbrainz_metadata(self, acoustid_result: Dict, release_data: Dict, target_rec_id: str = None) -> Dict:
        """Extract metadata from MusicBrainz response"""
        metadata = {}
        
        recordings = acoustid_result.get('recordings', [])
        recording = None
        
        if recordings:
            recording = next((r for r in recordings if r.get('id') == target_rec_id), None)
        if not recording:
            recording = next((r for r in recordings if r.get('title') or r.get('artists')), None)

        if recording:
            metadata['title'] = recording.get('title', 'Unknown Title')
            artists = recording.get('artists', [])
            if artists:
                metadata['artist'] = artists[0].get('name', 'Unknown Artist')
        
        if release_data:
            metadata.update({
                'album': release_data.get('title', 'Unknown Album'),
                'date': release_data.get('date', ''),
                'releasecountry': release_data.get('country', ''),
                'barcode': release_data.get('barcode', ''),
            })
            
            label_info = release_data.get('label-info', [])
            if label_info and label_info[0].get('label'):
                metadata['label'] = label_info[0]['label'].get('name', '')
            
            artist_credit = release_data.get('artist-credit', [])
            if artist_credit and artist_credit[0].get('artist'):
                metadata['albumartist'] = artist_credit[0]['artist'].get('name', '')
            
            media = release_data.get('media', [])
            if media:
                target_recording_id = recording.get('id') if recording else None
                match = self._locate_track_in_media(media, target_recording_id, metadata.get('title', ''))
                if match:
                    metadata['tracknumber'] = match['tracknumber']
                    metadata['totaltracks'] = match['totaltracks']
                    metadata['media'] = match['media']
                    if match.get('isrc'):
                        metadata['isrc'] = match['isrc']
            
            rg = release_data.get('release-group', {})
            if rg:
                metadata['musicbrainz_releasegroupid'] = rg.get('id', '')
                rg_date = rg.get('first-release-date')
                if rg_date:
                    metadata['originaldate'] = rg_date
                    metadata['originalyear'] = rg_date.split('-')[0]
                if rg.get('primary-type'):
                    metadata['genre'] = rg['primary-type']

            metadata.setdefault('originaldate', release_data.get('date', ''))
        
        return metadata

    def _build_genius_metadata(self, genius_data: Dict, artist_guess: str, title_guess: str) -> Dict:
        """Build metadata dict from Genius response"""
        return {
            'title': genius_data.get('title') or title_guess,
            'artist': genius_data.get('artist') or artist_guess,
            'album': genius_data.get('album', ''),
            'date': genius_data.get('release_date', ''),
            'originalyear': genius_data.get('year', ''),
            'producer': genius_data.get('producer', ''),
            'writer': genius_data.get('writer', ''),
            'tracknumber': genius_data.get('tracknumber', ''),
            'totaltracks': genius_data.get('totaltracks', ''),
        }

    def _fetch_genius_covers(self, genius_data: Dict, artist: str, title: str) -> List[Tuple[bytes, str]]:
        """Fetch cover art from Genius or iTunes"""
        if self.use_genius_cover and genius_data.get('cover_art_url'):
            try:
                res = self.session.get(genius_data['cover_art_url'], timeout=10)
                if res.status_code == 200:
                    return [(res.content, res.headers.get('Content-Type', 'image/jpeg'))]
            except Exception:
                pass
        
        return self.get_cover_art('', None, artist, title)

    def tag_file(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Apply metadata tags to audio file"""
        ext = os.path.splitext(filepath)[1].lower()
        
        taggers = {
            '.mp3': self._tag_mp3,
            '.flac': self._tag_flac,
            '.ogg': self._tag_ogg,
            '.oga': self._tag_ogg,
            '.m4a': self._tag_m4a,
            '.mp4': self._tag_m4a,
            '.m4b': self._tag_m4a,
            '.m4p': self._tag_m4a,
        }
        
        tagger = taggers.get(ext)
        if not tagger:
            self.logger.error(f"Unsupported format: {ext}")
            return False
        
        try:
            return tagger(filepath, metadata, covers)
        except Exception as e:
            self.logger.error(f"Tagging failed: {e}")
            return False

    def _purge_id3_frames(self, audio: ID3) -> None:
        """Remove every frame that makes Navidrome split one album into several"""
        for frame_id in self.ID3_PURGE_FRAMES:
            audio.delall(frame_id)
        
        purge_descs = {d.lower() for d in self.ID3_PURGE_TXXX}
        for key in list(audio.keys()):
            if key.startswith('TXXX:') and key[5:].lower() in purge_descs:
                del audio[key]

    def _tag_mp3(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Tag MP3 file with ID3v2.4 while purging album-splitting frames"""
        try:
            audio = ID3(filepath)
        except Exception:
            audio = ID3()

        # Purge UFID, MusicBrainz IDs, barcode, catalog number, AcoustID data, TPOS, TSST
        self._purge_id3_frames(audio)

        clean = {k: v for k, v in metadata.items() if v and str(v).strip()}
        
        tag_map = {
            'title': TIT2, 'artist': TPE1, 'album': TALB, 'albumartist': TPE2,
            'date': TDRC, 'originaldate': TDOR, 'genre': TCON, 'label': TPUB,
            'isrc': TSRC, 'media': TMED, 'albumartistsort': TSOP
        }
        
        for key, frame_cls in tag_map.items():
            if key in clean:
                try:
                    audio.add(frame_cls(encoding=3, text=clean[key]))
                except Exception as e:
                    self.logger.warning(f"Tag error ({key}): {e}")
        
        if 'tracknumber' in clean:
            total = clean.get('totaltracks')
            track_text = f"{clean['tracknumber']}/{total}" if total else str(clean['tracknumber'])
            audio.add(TRCK(encoding=3, text=track_text))
        
        txxx_map = {
            'originalyear': 'originalyear',
            'producer': 'PRODUCER', 'writer': 'WRITER',
        }
        
        for key, desc in txxx_map.items():
            if key in clean:
                audio.add(TXXX(encoding=3, desc=desc, text=clean[key]))
        
        if covers:
            for idx, (data, mime) in enumerate(covers):
                audio.add(APIC(
                    encoding=3,
                    mime='image/png' if 'png' in mime.lower() else 'image/jpeg',
                    type=3,
                    desc='Album cover' if idx == 0 else 'Cover',
                    data=data
                ))
        
        # v2.4 keeps TDRC/TDOR intact (v2.3 would downgrade them to TYER/TORY)
        audio.save(filepath, v2_version=4)
        return True

    def _tag_flac(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Tag FLAC file with Vorbis comments"""
        try:
            audio = FLAC(filepath)
        except Exception as e:
            self.logger.error(f"Cannot open FLAC: {e}")
            return False
        
        # Purge album-splitting identifiers and disc info
        for key in self.VORBIS_PURGE_KEYS:
            if key in audio:
                del audio[key]
        
        for key in ['title', 'artist', 'album', 'albumartist', 'date', 'originaldate', 'originalyear',
                   'tracknumber', 'totaltracks', 'genre', 'label', 'isrc', 'producer', 'writer']:
            if key in metadata and metadata[key] and str(metadata[key]).strip():
                audio[key] = str(metadata[key])
        
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
            self.logger.error(f"FLAC save failed: {e}")
            return False

    def _tag_ogg(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Tag OGG file with Vorbis comments"""
        try:
            audio = OggVorbis(filepath)
        except Exception as e:
            self.logger.error(f"Cannot open OGG: {e}")
            return False
        
        # Purge album-splitting identifiers and disc info
        for key in self.VORBIS_PURGE_KEYS:
            if key in audio:
                del audio[key]
        
        for key in ['title', 'artist', 'album', 'albumartist', 'date', 'originaldate', 'tracknumber', 
                   'genre', 'label', 'producer', 'writer']:
            if key in metadata and metadata[key] and str(metadata[key]).strip():
                audio[key] = str(metadata[key])
        
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
            self.logger.error(f"OGG save failed: {e}")
            return False

    def _tag_m4a(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Tag M4A file with MP4 atoms"""
        try:
            audio = MP4(filepath)
        except Exception as e:
            self.logger.error(f"Cannot open M4A: {e}")
            return False
        
        # Purge disc number atom and freeform MusicBrainz / barcode / AcoustID atoms
        purge_names = set(self.MP4_PURGE_FREEFORM)
        for key in list(audio.keys()):
            if key == 'disk':
                del audio[key]
            elif key.startswith('----:') and key.split(':', 2)[-1].lower() in purge_names:
                del audio[key]
        
        m4a_map = {
            'title': '\xa9nam', 'artist': '\xa9ART', 'album': '\xa9alb',
            'albumartist': 'aART', 'date': '\xa9day', 'genre': '\xa9gen'
        }
        
        for key, atom in m4a_map.items():
            if key in metadata and metadata[key]:
                audio[atom] = [str(metadata[key])]
        
        if 'tracknumber' in metadata and metadata['tracknumber']:
            try:
                track_num = int(metadata['tracknumber'])
                total = int(metadata.get('totaltracks', track_num))
                audio['trkn'] = [(track_num, total)]
            except (ValueError, TypeError):
                pass
        
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
            self.logger.error(f"M4A save failed: {e}")
            return False

    def process_file(self, filepath: str) -> bool:
        """Main entry point: tag a single audio file with multi-source fallback"""
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filepath)[1].lower()
        
        if ext not in self.SUPPORTED_FORMATS:
            self.logger.error(f"Unsupported format: {ext}")
            return False
        
        self.logger.info(f"Processing: {filename}")
        
        artist_guess, title_guess = self._extract_search_guesses(filepath)
        self.logger.debug(f"Search guess: artist='{artist_guess}', title='{title_guess}'")
        
        # Step 1: Try AcoustID + MusicBrainz
        acoustid_result = self.lookup_acoustid(filepath) if self.use_acoustid else None
        release_id = None
        recording_id = None
        from_search = False

        if acoustid_result:
            score = acoustid_result.get('score', 0) * 100
            self.logger.info(f"AcoustID match: {score:.1f}%")
            
            recordings = acoustid_result.get('recordings', [])
            if recordings:
                for rec in recordings:
                    recording_id = rec.get('id')
                    for rg in rec.get('releasegroups', []):
                        releases = rg.get('releases', [])
                        if releases:
                            release_id = releases[0]['id']
                            break
                    if release_id:
                        break
        
        # Step 2: If AcoustID failed, try MusicBrainz text search
        if not release_id and self.use_mb_search:
            if acoustid_result:
                self.logger.warning("AcoustID found but no release - trying MusicBrainz search")
            elif self.use_acoustid:
                self.logger.warning("No AcoustID match - trying MusicBrainz search")
            else:
                self.logger.info("AcoustID disabled - trying MusicBrainz search")
            
            mb_search = self.search_musicbrainz(artist_guess, title_guess)
            if mb_search:
                from_search = True
                release_id = mb_search.get('release_id')
                recording_id = mb_search.get('recording_id')
                artist_guess = mb_search.get('artist', artist_guess)
                title_guess = mb_search.get('title', title_guess)
        
        # Step 3: If still no MusicBrainz data, fall back to Genius only
        if not release_id:
            self.logger.warning("No MusicBrainz data - trying Genius fallback")
            genius_data = self.search_genius(artist_guess, title_guess)
            if genius_data:
                metadata = self._build_genius_metadata(genius_data, artist_guess, title_guess)
                covers = self._fetch_genius_covers(genius_data, metadata['artist'], metadata['title'])
                
                self.logger.info(f"Genius: {metadata['artist']} - {metadata['title']} ({metadata.get('album', 'N/A')})")
                
                metadata = self._normalize_metadata(metadata)

                success = self.tag_file(filepath, metadata, covers)
                self.logger.info(f"{'[OK]' if success else '[FAIL]'} {filename}")
                return success

            self.logger.error("No metadata found from any source")
            return False

        # Step 4: Fetch full release data from MusicBrainz
        self.logger.info("Fetching MusicBrainz metadata...")
        release_data = self._api_call(
            f"{self.mb_base}/release/{release_id}",
            params={'fmt': 'json', 'inc': 'artists+recordings+release-groups+labels+media+isrcs'},
            timeout=15,
            rate_limit=self.RATE_LIMIT_MB
        )
        
        if not release_data:
            self.logger.error("MusicBrainz fetch failed - falling back to Genius")
            genius_data = self.search_genius(artist_guess, title_guess)
            if genius_data:
                metadata = self._build_genius_metadata(genius_data, artist_guess, title_guess)
                covers = self._fetch_genius_covers(genius_data, metadata['artist'], metadata['title'])
                
                metadata = self._normalize_metadata(metadata)

                return self.tag_file(filepath, metadata, covers)
            return False
        
        # Extract metadata
        if acoustid_result and acoustid_result.get('recordings') and not from_search:
            metadata = self._extract_musicbrainz_metadata(acoustid_result, release_data, target_rec_id=recording_id)
        else:
            metadata = self._extract_musicbrainz_from_search(release_data, recording_id, artist_guess, title_guess)
        
        artist_name = metadata.get('artist', artist_guess)
        track_title = metadata.get('title', title_guess)
        
        self.logger.info(f"Found: {artist_name} - {track_title} ({metadata.get('album', 'N/A')})")
        
        rg_id = metadata.get('musicbrainz_releasegroupid') or release_data.get('release-group', {}).get('id')
        covers = self.get_cover_art(release_id, rg_id, artist_name, track_title)
        
        if covers:
            self.logger.info(f"Cover art fetched ({len(covers)} image(s))")
        else:
            self.logger.warning("No cover art found")

        # Uniform metadata normalization before tagging
        metadata = self._normalize_metadata(metadata)

        success = self.tag_file(filepath, metadata, covers)
        self.logger.info(f"{'[OK]' if success else '[FAIL]'} {filename}")
        return success

    def process_directory(self, directory: str, recursive: bool = False, on_success=None) -> Dict[str, int]:
        """Process all supported audio files in a directory"""
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
                self.logger.error(f"Cannot read directory: {e}")
                return {'success': 0, 'failed': 0}
        
        if not files:
            self.logger.warning("No supported audio files found")
            return {'success': 0, 'failed': 0}
        
        self.logger.info(f"Found {len(files)} file(s)")
        
        results = {'success': 0, 'failed': 0}
        
        for filepath in files:
            try:
                if self.process_file(filepath):
                    results['success'] += 1
                    if on_success:
                        try:
                            on_success(filepath)
                        except Exception as e:
                            self.logger.error(f"Post-tag step failed for {filepath}: {e}")
                else:
                    results['failed'] += 1
            except Exception as e:
                self.logger.error(f"Error processing {filepath}: {e}")
                results['failed'] += 1
        
        self.logger.info(f"Complete: {results['success']} success, {results['failed']} failed")
        return results
