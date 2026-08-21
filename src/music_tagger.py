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

from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TDRC, TDOR, TRCK, APIC, TPE2, TCON, TPOS,
    TPUB, TSRC, TMED, TSOP, TXXX
)
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis


class MusicTagger:
    """MusicBrainz-based music tagger"""
    
    RATE_LIMIT_ACOUSTID = 0.33  # 3 req/sec
    RATE_LIMIT_MB = 1.0  # 1 req/sec
    SUPPORTED_FORMATS = {'.mp3', '.flac', '.ogg', '.oga', '.m4a', '.mp4', '.m4b', '.m4p'}
    
    def __init__(self, user_agent: str = "MusicTagger/1.0", logger=None, api_key: str = None):
        self.api_key = api_key or 'v8pQ6oyB'
        self.user_agent = user_agent
        self.mb_base = "https://musicbrainz.org/ws/2"
        self.caa_base = "https://coverartarchive.org"
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})
        self.logger = logger or logging.getLogger(__name__)
    
    def _api_call(self, url: str, params: dict = None, data: dict = None, timeout: int = 10, rate_limit: float = 0) -> Optional[Dict]:
        """Generic API call handler with rate limiting and error logging"""
        try:
            if rate_limit:
                time.sleep(rate_limit)
            
            if data:
                response = self.session.post(url, data=data, timeout=timeout)
            else:
                response = self.session.get(url, params=params, timeout=timeout)
            
            response.raise_for_status()
            return response.json() if response.text else None
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
            else:
                self.logger.error(f"fpcalc error: {result.stderr}")
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
            if best_match.get('score', 0) > 0.5:
                return best_match
        
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
                self.logger.info(f"Checking {url} for cover art...")
                data = self._api_call(url, timeout=10)
            
                if data and 'images' in data:
                    for image in data['images']:
                        if image.get('front', False) or len(data['images']) == 1:
                            img_url = image.get('image') or image.get('thumbnails', {}).get('large')
                            if img_url:
                                self.logger.info(f"Downloading cover art from {img_url}...")
                                res = self.session.get(img_url, headers=headers, allow_redirects=True, timeout=15)
                                if res.status_code == 200:
                                    mime_type = res.headers.get('content-type', 'image/jpeg')
                                    self.logger.info("Cover art downloaded successfully from CAA.")
                                    return [(res.content, mime_type)]
                                else:
                                    self.logger.warning(f"Cover art download failed with status code {res.status_code}")
            except Exception as e:
                self.logger.debug(f"Cover art download error for {url}: {e}")
                continue

        direct_urls = [
            f"{self.caa_base}/release/{release_id}/front",
            f"{self.caa_base}/release/{release_id}/front-500"
        ]
        if release_group_id:
            direct_urls.append(f"{self.caa_base}/release-group/{release_group_id}/front")

        for direct_url in direct_urls:
            try:
                self.logger.info(f"Downloading cover art from direct URL: {direct_url}")
                res = self.session.get(direct_url, headers=headers, allow_redirects=True, timeout=10)
                if res.status_code == 200:
                    mime_type = res.headers.get('content-type', 'image/jpeg')
                    self.logger.info("Cover art downloaded successfully from direct CAA URL.")
                    return [(res.content, mime_type)]
            except Exception as e:
                self.logger.debug(f"Cover art download error for direct URL: {e}")

        if artist and title:
            try:
                query = f"{artist} {title}"
                self.logger.info(f"Caa empty. Searching iTunes API for: {query}")
                itunes_url = "https://itunes.apple.com/search"
                params = {"term": query, "entity": "song", "limit": 1}
                res = self.session.get(itunes_url, params=params, timeout=10)

                if res.status_code == 200:
                    result = res.json().get('results', [])
                    if result:
                        artwork_url = result[0].get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                        if artwork_url:
                            self.logger.info(f"Cover art URL found in iTunes API: {artwork_url}")
                            img_res = self.session.get(artwork_url, headers=headers, timeout=10)
                            if img_res.status_code == 200:
                                mime_type = img_res.headers.get('Content-Type', 'image/jpeg')
                                self.logger.info("Cover art downloaded successfully from iTunes API")
                                return [(img_res.content, mime_type)]
                        else:
                            self.logger.error("Failed to download cover art from iTunes API")
                    else:
                        self.logger.warning("No results found in iTunes API")
                
            except Exception as e:
                self.logger.error(f"Error fetching cover art from iTunes API: {e}")

        
        self.logger.warning("No cover art found in Cover Art Archive")
        return []
    
    def extract_metadata(self, acoustid_result: Dict, release_data: Dict, recording_id: str) -> Dict:
        """Parse AcoustID and MusicBrainz response objects into normalized metadata dict"""
        metadata = {'acoustid_id': acoustid_result.get('id', '')}
        
        # Track recording metadata
        recordings = acoustid_result.get('recordings', [])
        if recordings:
            recording = recordings[0]
            metadata.update({
                'title': recording.get('title', ''),
                'musicbrainz_recordingid': recording.get('id', '')
            })
            
            artists = recording.get('artists', [])
            if artists:
                artist = artists[0]
                artist_id = artist.get('id', '')
                metadata['artist'] = artist.get('name', '')
                metadata['musicbrainz_artistid'] = artist_id
                
                # Retrieve artist sort name
                if artist_id:
                    artist_data = self.get_musicbrainz_data('artist', artist_id)
                    metadata['artistsort'] = artist_data.get('sort-name', metadata['artist']) if artist_data else metadata['artist']
                else:
                    metadata['artistsort'] = metadata['artist']
        
        # Release metadata
        if release_data:
            metadata.update({
                'album': release_data.get('title', ''),
                'musicbrainz_albumid': release_data.get('id', ''),
                'date': release_data.get('date', ''),
                'releasecountry': release_data.get('country', ''),
                'barcode': release_data.get('barcode', '')
            })
            
            # Script representation
            text_rep = release_data.get('text-representation', {})
            if text_rep.get('script'):
                metadata['script'] = text_rep['script']
            
            # Record label
            label_info = release_data.get('label-info', [])
            if label_info and label_info[0].get('label'):
                metadata['label'] = label_info[0]['label'].get('name', '')
            
            # Album artist credit
            artist_credit = release_data.get('artist-credit', [])
            if artist_credit and artist_credit[0].get('artist'):
                album_artist = artist_credit[0]['artist']
                metadata['albumartist'] = album_artist.get('name', '')
                metadata['musicbrainz_albumartistid'] = album_artist.get('id', '')
                metadata['albumartistsort'] = album_artist.get('sort-name', metadata['albumartist'])
            
            # Media & Track structure
            media = release_data.get('media', [])
            if media:
                medium = media[0]
                metadata['media'] = medium.get('format', '')
                metadata['discnumber'] = '1'
                metadata['totaldiscs'] = str(len(media))
                
                tracks = medium.get('tracks', [])
                for idx, track in enumerate(tracks, 1):
                    track_rec = track.get('recording', {})
                    if track_rec.get('title') == metadata.get('title') or track_rec.get('id') == recording_id:
                        metadata['tracknumber'] = str(idx)
                        metadata['totaltracks'] = str(len(tracks))
                        metadata['musicbrainz_releasetrackid'] = track.get('id', '')
                        
                        isrcs = track_rec.get('isrcs', [])
                        if isrcs:
                            metadata['isrc'] = isrcs[0]
                        break
            
            # Release group attributes
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
        
        clean_meta = {}
        for k, v in metadata.items():
            if v is not None and str(v).strip() != '':
                clean_meta[k] = v

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
        audio = FLAC(filepath)
        
        keys = [
            'title', 'artist', 'album', 'albumartist', 'date', 'originaldate',
            'tracknumber', 'totaltracks', 'discnumber', 'totaldiscs', 'genre',
            'label', 'isrc', 'media', 'barcode', 'originalyear',
            'musicbrainz_albumid', 'musicbrainz_artistid', 'musicbrainz_albumartistid',
            'musicbrainz_releasegroupid', 'musicbrainz_releasetrackid', 'acoustid_id'
        ]
        for key in keys:
            if key in metadata:
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
        
        audio.save()
        return True
    
    def _tag_ogg(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Apply Vorbis comments and METADATA_BLOCK_PICTURE to OGG container"""
        audio = OggVorbis(filepath)
        
        keys = [
            'title', 'artist', 'album', 'albumartist', 'date', 'originaldate',
            'tracknumber', 'genre', 'label', 'isrc', 'musicbrainz_albumid', 'acoustid_id'
        ]
        for key in keys:
            if key in metadata:
                audio[key] = metadata[key]
        
        if covers:
            import base64
            pic = Picture()
            pic.type = 3
            pic.mime = 'image/png' if 'png' in covers[0][1].lower() else 'image/jpeg'
            pic.desc = 'Album cover'
            pic.data = covers[0][0]
            audio['metadata_block_picture'] = base64.b64encode(pic.write()).decode('ascii')
        
        audio.save()
        return True
    
    def _tag_m4a(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """Apply MP4 atoms to M4A container"""
        audio = MP4(filepath)
        
        m4a_map = {
            'title': '\xa9nam', 'artist': '\xa9ART', 'album': '\xa9alb',
            'albumartist': 'aART', 'date': '\xa9day', 'genre': '\xa9gen'
        }
        
        for meta_key, tag_key in m4a_map.items():
            if meta_key in metadata:
                audio[tag_key] = metadata[meta_key]
        
        if 'tracknumber' in metadata:
            total = int(metadata.get('totaltracks', 0))
            audio['trkn'] = [(int(metadata['tracknumber']), total)]
        
        if 'discnumber' in metadata and 'totaldiscs' in metadata:
            audio['disk'] = [(int(metadata['discnumber']), int(metadata['totaldiscs']))]
        
        if covers:
            audio['covr'] = [
                MP4Cover(data, imageformat=MP4Cover.FORMAT_PNG if 'png' in mime.lower() else MP4Cover.FORMAT_JPEG)
                for data, mime in covers
            ]
        
        audio.save()
        return True
    
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
        self.logger.info(f"Tagging started: {os.path.basename(filepath)}")
        
        # 1. Lookup Fingerprint
        acoustid_result = self.lookup_acoustid(filepath)
        if not acoustid_result:
            self.logger.warning("No AcoustID match found")
            return False
        
        score = acoustid_result.get('score', 0)
        self.logger.info(f"AcoustID match: {score*100:.1f}%")
        
        # 2. Extract release parameters
        release_id = None
        recording_id = None
        
        recordings = acoustid_result.get('recordings', [])
        if recordings:
            rec = recordings[0]
            recording_id = rec.get('id')
            
            for rg in rec.get('releasegroups', []):
                releases = rg.get('releases', [])
                if releases:
                    release_id = releases[0]['id']
                    break
        
        if not release_id:
            self.logger.warning("No MusicBrainz release found")
            return False
        
        release_data = self.get_musicbrainz_data(
            'release', release_id,
            'artists+recordings+release-groups+labels+media+isrcs+artist-credits'
        )
        
        if not release_data:
            self.logger.error("Failed to fetch release metadata")
            return False
        
        # 3. Consolidate metadata
        metadata = self.extract_metadata(acoustid_result, release_data, recording_id)
        
        if metadata.get('title') and metadata.get('artist'):
            self.logger.info(f"Metadata match: {metadata['artist']} - {metadata['title']}")
        
        # 4. Fetch cover art
        rg_id = metadata.get('musicbrainz_releasegroupid')
        artist_name = metadata.get('artist')
        track_title = metadata.get('title')

        covers = self.get_cover_art(
            release_id, 
            release_group_id=rg_id,
            artist=artist_name,
            title=track_title
        )
        if covers:
            self.logger.info(f"{len(covers)} cover image(s) fetched")
            
            if save_cover:
                for idx, (data, mime) in enumerate(covers):
                    ext = 'png' if 'png' in mime.lower() else 'jpg'
                    cover_path = os.path.join(
                        os.path.dirname(filepath), 
                        f'cover{idx if idx > 0 else ""}.{ext}'
                    )
                    with open(cover_path, 'wb') as f:
                        f.write(data)
                    self.logger.info(f"Cover image saved: {cover_path}")
        
        # 5. Write metadata tags
        success = self.tag_file(filepath, metadata, covers)
        
        if success:
            self.logger.info("✓ Tagging completed successfully")
        else:
            self.logger.error("Failed to write metadata tags")
        
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
            files = [
                os.path.join(directory, f) for f in os.listdir(directory)
                if os.path.splitext(f)[1].lower() in self.SUPPORTED_FORMATS
            ]
        
        if not files:
            self.logger.warning("No supported music files found")
            return
        
        self.logger.info(f"{len(files)} audio file(s) located")
        
        results = {'success': 0, 'failed': 0}
        for filepath in files:
            try:
                if self.process_file(filepath, save_cover):
                    results['success'] += 1
                else:
                    results['failed'] += 1
            except Exception as e:
                self.logger.error(f"Error processing {filepath}: {e}")
                results['failed'] += 1
        
        self.logger.info(f"Batch processing complete: {results['success']} successful, {results['failed']} failed")


def main():
    parser = argparse.ArgumentParser(description='MusicBrainz Audio Tagger CLI')
    parser.add_argument('path', help='Target audio file or directory path')
    parser.add_argument('-r', '--recursive', action='store_true', help='Scan target directory recursively')
    parser.add_argument('-c', '--save-cover', action='store_true', help='Save cover art as a standalone file')
    parser.add_argument('-u', '--user-agent', default='MusicTagger/1.0', help='Custom HTTP User-Agent string')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.path):
        print(f"Error: Target path '{args.path}' does not exist")
        sys.exit(1)
    
    tagger = MusicTagger(args.user_agent)
    
    if os.path.isfile(args.path):
        tagger.process_file(args.path, args.save_cover)
    elif os.path.isdir(args.path):
        tagger.process_directory(args.path, args.recursive, args.save_cover)
    else:
        print(f"Error: '{args.path}' is neither a file nor a directory")
        sys.exit(1)


if __name__ == '__main__':
    main()