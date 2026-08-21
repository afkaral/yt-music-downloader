#!/usr/bin/env python3
"""
MusicBrainz Audio Tagger - Picard alternatifi CLI aracı
AcoustID fingerprint + MusicBrainz metadata + Cover Art Archive
"""

import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import requests
import subprocess
import shutil
import mutagen
from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TDRC, TDOR, TRCK, APIC, TPE2, TCON, TPOS,
    TPUB, TSRC, TMED, TSOP, TXXX, UFID, COMM, TLAN
)
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis


class MusicTagger:
    """MusicBrainz tabanlı müzik etiketleyici"""
    
    def __init__(self, user_agent: str = "MusicTagger/1.0", logger=None, api_key: str = None):
        self.api_key = api_key or 'v8pQ6oyB'  # Fallback to Picard's key
        self.user_agent = user_agent
        self.mb_base = "https://musicbrainz.org/ws/2"
        self.caa_base = "https://coverartarchive.org"
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})
        self.logger = logger or logging.getLogger(__name__)
        
    def get_fingerprint(self, filepath: str) -> Optional[Tuple[str, int]]:
        """Dosyanın AcoustID parmak izini al (fpcalc kullanarak)"""
        fpcalc = shutil.which('fpcalc')
        if not fpcalc:
            self.logger.error("fpcalc bulunamadı (libchromaprint-tools gerekli)")
            return None
        
        try:
            result = subprocess.run(
                [fpcalc, '-json', '-length', '120', filepath],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode in (0, 3):  # 0=success, 3=decoding errors but fingerprint ok
                data = json.loads(result.stdout)
                fingerprint = data.get('fingerprint')
                duration = int(data.get('duration', 0))
                if fingerprint and duration:
                    return fingerprint, duration
            else:
                self.logger.error(f"fpcalc hatası: {result.stderr}")
        except subprocess.TimeoutExpired:
            self.logger.error("fpcalc zaman aşımı")
        except Exception as e:
            self.logger.error(f"Parmak izi alınamadı: {e}")
        
        return None
    
    def lookup_acoustid(self, filepath: str) -> Optional[Dict]:
        """AcoustID ile MusicBrainz'de ara"""
        result = self.get_fingerprint(filepath)
        if not result:
            return None
            
        fingerprint, duration = result
        
        # AcoustID API'ye direkt istek at
        url = 'https://api.acoustid.org/v2/lookup'
        params = {
            'client': self.api_key,
            'meta': 'recordings releases releasegroups compress',
            'fingerprint': fingerprint,
            'duration': str(duration)
        }
        
        try:
            time.sleep(0.33)  # AcoustID rate limit (3 req/sec)
            response = self.session.post(url, data=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'ok' and data.get('results'):
                # En yüksek skorlu sonucu al
                best_match = max(data['results'], key=lambda x: x.get('score', 0))
                if best_match.get('score', 0) > 0.5:  # %50'den yüksek eşleşme
                    return best_match
        except Exception as e:
            self.logger.error(f"AcoustID API hatası: {e}")
        
        return None
    
    def get_musicbrainz_release(self, release_id: str) -> Optional[Dict]:
        """MusicBrainz'den release bilgilerini al"""
        url = f"{self.mb_base}/release/{release_id}"
        params = {
            'fmt': 'json',
            'inc': 'artists+recordings+release-groups+labels+media+isrcs+artist-credits'
        }
        
        try:
            time.sleep(1)  # MusicBrainz rate limit (1 request/second)
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"MusicBrainz release hatası: {e}")
            return None
    
    def get_musicbrainz_artist(self, artist_id: str) -> Optional[Dict]:
        """MusicBrainz'den artist bilgilerini al"""
        url = f"{self.mb_base}/artist/{artist_id}"
        params = {'fmt': 'json'}
        
        try:
            time.sleep(1)
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.debug(f"Artist bilgisi alınamadı: {e}")
            return None
    
    def get_musicbrainz_release_group(self, rg_id: str) -> Optional[Dict]:
        """Release group'tan orijinal tarih al"""
        url = f"{self.mb_base}/release-group/{rg_id}"
        params = {'fmt': 'json', 'inc': 'releases'}
        
        try:
            time.sleep(1)
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.debug(f"Release group hatası: {e}")
            return None
    
    def get_cover_art(self, release_id: str) -> List[Tuple[bytes, str]]:
        """Cover Art Archive'den albüm kapaklarını indir"""
        covers = []
        
        # JSON endpoint'den kapak listesini al
        try:
            url = f"{self.caa_base}/release/{release_id}"
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                for image in data.get('images', []):
                    if image.get('front'):  # Front cover
                        # Thumbnails yerine orjinal boyutu kullan
                        img_url = image.get('image')
                        if img_url:
                            try:
                                img_response = self.session.get(img_url, timeout=15)
                                if img_response.status_code == 200:
                                    mime_type = img_response.headers.get('content-type', 'image/jpeg')
                                    covers.append((img_response.content, mime_type))
                            except:
                                pass
                        break  # Sadece front cover
        except Exception as e:
            self.logger.debug(f"Kapak indirme hatası: {e}")
        
        return covers
    
    def extract_metadata(self, acoustid_result: Dict, release_data: Dict, recording_id: str) -> Dict:
        """AcoustID ve MusicBrainz verilerinden metadata çıkar"""
        metadata = {}
        
        # AcoustID ID
        if 'id' in acoustid_result:
            metadata['acoustid_id'] = acoustid_result['id']
        
        # Recording bilgisi
        if 'recordings' in acoustid_result and acoustid_result['recordings']:
            recording = acoustid_result['recordings'][0]
            metadata['title'] = recording.get('title', '')
            metadata['musicbrainz_recordingid'] = recording.get('id', '')
            
            if 'artists' in recording and recording['artists']:
                artist = recording['artists'][0]
                metadata['artist'] = artist.get('name', '')
                artist_id = artist.get('id', '')
                metadata['musicbrainz_artistid'] = artist_id
                
                # Artist sort order (API'den detaylı bilgi al)
                if artist_id:
                    artist_data = self.get_musicbrainz_artist(artist_id)
                    if artist_data and 'sort-name' in artist_data:
                        metadata['artistsort'] = artist_data['sort-name']
                    else:
                        metadata['artistsort'] = metadata['artist']
                else:
                    metadata['artistsort'] = metadata['artist']
        
        # Release bilgisi
        if release_data:
            metadata['album'] = release_data.get('title', '')
            metadata['musicbrainz_albumid'] = release_data.get('id', '')
            
            # Release tarihi (recording date)
            if 'date' in release_data:
                metadata['date'] = release_data['date']
            
            # Release country
            if 'country' in release_data:
                metadata['releasecountry'] = release_data['country']
            
            # Barcode
            if 'barcode' in release_data and release_data['barcode']:
                metadata['barcode'] = release_data['barcode']
            
            # Script
            if 'text-representation' in release_data:
                script = release_data['text-representation'].get('script')
                if script:
                    metadata['script'] = script
            
            # Label
            if 'label-info' in release_data and release_data['label-info']:
                for label_info in release_data['label-info']:
                    if 'label' in label_info and label_info['label']:
                        metadata['label'] = label_info['label'].get('name', '')
                        break
            
            # Album artist
            if 'artist-credit' in release_data and release_data['artist-credit']:
                album_artist = release_data['artist-credit'][0]
                if 'artist' in album_artist:
                    metadata['albumartist'] = album_artist['artist'].get('name', '')
                    metadata['musicbrainz_albumartistid'] = album_artist['artist'].get('id', '')
                    
                    # Album artist sort (MusicBrainz'den sort-name kullan)
                    metadata['albumartistsort'] = album_artist['artist'].get('sort-name', metadata['albumartist'])
            
            # Media (disc format)
            if 'media' in release_data and release_data['media']:
                medium = release_data['media'][0]
                if 'format' in medium and medium['format']:
                    metadata['media'] = medium['format']
                
                # Disc number
                metadata['discnumber'] = '1'
                metadata['totaldiscs'] = str(len(release_data['media']))
                
                # Track bilgisi
                if 'tracks' in medium:
                    for idx, track in enumerate(medium['tracks'], 1):
                        track_recording = track.get('recording', {})
                        if track_recording.get('title') == metadata.get('title') or \
                           track_recording.get('id') == recording_id:
                            metadata['tracknumber'] = str(idx)
                            metadata['totaltracks'] = str(len(medium['tracks']))
                            metadata['musicbrainz_releasetrackid'] = track.get('id', '')
                            
                            # ISRC
                            if 'isrcs' in track_recording and track_recording['isrcs']:
                                metadata['isrc'] = track_recording['isrcs'][0]
                            break
            
            # Release group bilgisi
            if 'release-group' in release_data:
                rg = release_data['release-group']
                metadata['musicbrainz_releasegroupid'] = rg.get('id', '')
                
                # Primary type
                if 'primary-type' in rg:
                    metadata['releasetype'] = rg['primary-type'].lower()
                    metadata['genre'] = rg['primary-type']
                
                # Release status
                if 'status' in release_data:
                    metadata['releasestatus'] = release_data['status'].lower()
                
                # Orijinal yayın tarihi (release group'tan)
                if rg.get('first-release-date'):
                    metadata['originaldate'] = rg['first-release-date']
                    metadata['originalyear'] = rg['first-release-date'].split('-')[0]
        
        return metadata
    
    def tag_file(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]] = None) -> bool:
        """Dosyayı etiketle (MP3, FLAC, OGG, M4A destekli)"""
        try:
            ext = os.path.splitext(filepath)[1].lower()
            
            if ext == '.mp3':
                return self._tag_mp3(filepath, metadata, covers)
            elif ext == '.flac':
                return self._tag_flac(filepath, metadata, covers)
            elif ext in ['.ogg', '.oga']:
                return self._tag_ogg(filepath, metadata, covers)
            elif ext in ['.m4a', '.mp4', '.m4b', '.m4p']:
                return self._tag_m4a(filepath, metadata, covers)
            else:
                self.logger.error(f"Desteklenmeyen format: {ext}")
                return False
                
        except Exception as e:
            self.logger.error(f"Etiketleme hatası: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return False
    
    def _tag_mp3(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """MP3 dosyasını etiketle"""
        try:
            audio = ID3(filepath)
        except:
            audio = ID3()
        
        # Temel taglar
        if 'title' in metadata:
            audio.add(TIT2(encoding=3, text=metadata['title']))
        if 'artist' in metadata:
            audio.add(TPE1(encoding=3, text=metadata['artist']))
        if 'album' in metadata:
            audio.add(TALB(encoding=3, text=metadata['album']))
        if 'albumartist' in metadata:
            audio.add(TPE2(encoding=3, text=metadata['albumartist']))
        if 'date' in metadata:
            audio.add(TDRC(encoding=3, text=metadata['date']))
        if 'originaldate' in metadata:
            audio.add(TDOR(encoding=3, text=metadata['originaldate']))
        if 'genre' in metadata:
            audio.add(TCON(encoding=3, text=metadata['genre']))
        
        # Track/Disc numbers
        if 'tracknumber' in metadata:
            track = metadata['tracknumber']
            if 'totaltracks' in metadata:
                track = f"{track}/{metadata['totaltracks']}"
            audio.add(TRCK(encoding=3, text=track))
        
        if 'discnumber' in metadata:
            disc = metadata['discnumber']
            if 'totaldiscs' in metadata:
                disc = f"{disc}/{metadata['totaldiscs']}"
            audio.add(TPOS(encoding=3, text=disc))
        
        # Publisher/Label
        if 'label' in metadata:
            audio.add(TPUB(encoding=3, text=metadata['label']))
        
        # ISRC
        if 'isrc' in metadata:
            audio.add(TSRC(encoding=3, text=metadata['isrc']))
        
        # Media
        if 'media' in metadata:
            audio.add(TMED(encoding=3, text=metadata['media']))
        
        # Script (TLAN tag'ı language içindir, script için TXXX kullanılmalı)
        if 'script' in metadata:
            audio.add(TXXX(encoding=3, desc='SCRIPT', text=metadata['script']))
        
        # Sort orders (Picard TSOP'u album artist sort için kullanıyor)
        if 'albumartistsort' in metadata:
            audio.add(TSOP(encoding=3, text=metadata['albumartistsort']))
        if 'artistsort' in metadata:
            from mutagen.id3 import TSOP as TSOP_FRAME
            # Performer sort order için de TSOP kullan (Picard uyumluluğu)
            audio.add(TXXX(encoding=3, desc='ARTISTSORT', text=metadata['artistsort']))
        
        # Original year
        if 'originalyear' in metadata:
            audio.add(TXXX(encoding=3, desc='ORIGINALYEAR', text=metadata['originalyear']))
        
        # Barcode
        if 'barcode' in metadata:
            audio.add(TXXX(encoding=3, desc='BARCODE', text=metadata['barcode']))
        
        # Artists (for multi-artist)
        if 'artist' in metadata:
            audio.add(TXXX(encoding=3, desc='ARTISTS', text=metadata['artist']))
        
        # MusicBrainz IDs
        if 'musicbrainz_albumid' in metadata:
            audio.add(TXXX(encoding=3, desc='MusicBrainz Album Id', text=metadata['musicbrainz_albumid']))
        if 'musicbrainz_artistid' in metadata:
            audio.add(TXXX(encoding=3, desc='MusicBrainz Artist Id', text=metadata['musicbrainz_artistid']))
        if 'musicbrainz_albumartistid' in metadata:
            audio.add(TXXX(encoding=3, desc='MusicBrainz Album Artist Id', text=metadata['musicbrainz_albumartistid']))
        if 'musicbrainz_releasegroupid' in metadata:
            audio.add(TXXX(encoding=3, desc='MusicBrainz Release Group Id', text=metadata['musicbrainz_releasegroupid']))
        if 'musicbrainz_releasetrackid' in metadata:
            audio.add(TXXX(encoding=3, desc='MusicBrainz Release Track Id', text=metadata['musicbrainz_releasetrackid']))
        
        # Release type & status
        if 'releasetype' in metadata:
            audio.add(TXXX(encoding=3, desc='MusicBrainz Album Type', text=metadata['releasetype']))
        if 'releasestatus' in metadata:
            audio.add(TXXX(encoding=3, desc='MusicBrainz Album Status', text=metadata['releasestatus']))
        if 'releasecountry' in metadata:
            audio.add(TXXX(encoding=3, desc='MusicBrainz Album Release Country', text=metadata['releasecountry']))
        
        # AcoustID
        if 'acoustid_id' in metadata:
            audio.add(TXXX(encoding=3, desc='Acoustid Id', text=metadata['acoustid_id']))
        
        # Kapak fotoğrafları
        if covers:
            for idx, (cover_data, mime_type) in enumerate(covers):
                # Mime type'ı düzelt
                if 'png' in mime_type.lower():
                    mime = 'image/png'
                else:
                    mime = 'image/jpeg'
                
                desc = 'Album cover' if idx == 0 else 'Cover'
                audio.add(APIC(
                    encoding=3,
                    mime=mime,
                    type=3,  # Front cover
                    desc=desc,
                    data=cover_data
                ))
        
        audio.save(filepath, v2_version=4)
        return True
    
    def _tag_flac(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """FLAC dosyasını etiketle"""
        audio = FLAC(filepath)
        
        # Temel taglar
        if 'title' in metadata:
            audio['title'] = metadata['title']
        if 'artist' in metadata:
            audio['artist'] = metadata['artist']
        if 'album' in metadata:
            audio['album'] = metadata['album']
        if 'albumartist' in metadata:
            audio['albumartist'] = metadata['albumartist']
        if 'date' in metadata:
            audio['date'] = metadata['date']
        if 'originaldate' in metadata:
            audio['originaldate'] = metadata['originaldate']
        if 'tracknumber' in metadata:
            audio['tracknumber'] = metadata['tracknumber']
        if 'totaltracks' in metadata:
            audio['totaltracks'] = metadata['totaltracks']
        if 'discnumber' in metadata:
            audio['discnumber'] = metadata['discnumber']
        if 'totaldiscs' in metadata:
            audio['totaldiscs'] = metadata['totaldiscs']
        if 'genre' in metadata:
            audio['genre'] = metadata['genre']
        if 'label' in metadata:
            audio['label'] = metadata['label']
        if 'isrc' in metadata:
            audio['isrc'] = metadata['isrc']
        if 'media' in metadata:
            audio['media'] = metadata['media']
        if 'barcode' in metadata:
            audio['barcode'] = metadata['barcode']
        if 'originalyear' in metadata:
            audio['originalyear'] = metadata['originalyear']
        
        # MusicBrainz tags
        if 'musicbrainz_albumid' in metadata:
            audio['musicbrainz_albumid'] = metadata['musicbrainz_albumid']
        if 'musicbrainz_artistid' in metadata:
            audio['musicbrainz_artistid'] = metadata['musicbrainz_artistid']
        if 'musicbrainz_albumartistid' in metadata:
            audio['musicbrainz_albumartistid'] = metadata['musicbrainz_albumartistid']
        if 'musicbrainz_releasegroupid' in metadata:
            audio['musicbrainz_releasegroupid'] = metadata['musicbrainz_releasegroupid']
        if 'musicbrainz_releasetrackid' in metadata:
            audio['musicbrainz_releasetrackid'] = metadata['musicbrainz_releasetrackid']
        if 'acoustid_id' in metadata:
            audio['acoustid_id'] = metadata['acoustid_id']
        
        # Kapak fotoğrafları
        if covers:
            audio.clear_pictures()
            for idx, (cover_data, mime_type) in enumerate(covers):
                picture = Picture()
                picture.type = 3  # Front cover
                picture.mime = 'image/png' if 'png' in mime_type.lower() else 'image/jpeg'
                picture.desc = 'Album cover' if idx == 0 else 'Cover'
                picture.data = cover_data
                audio.add_picture(picture)
        
        audio.save()
        return True
    
    def _tag_ogg(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """OGG Vorbis dosyasını etiketle"""
        audio = OggVorbis(filepath)
        
        # Temel taglar
        if 'title' in metadata:
            audio['title'] = metadata['title']
        if 'artist' in metadata:
            audio['artist'] = metadata['artist']
        if 'album' in metadata:
            audio['album'] = metadata['album']
        if 'albumartist' in metadata:
            audio['albumartist'] = metadata['albumartist']
        if 'date' in metadata:
            audio['date'] = metadata['date']
        if 'originaldate' in metadata:
            audio['originaldate'] = metadata['originaldate']
        if 'tracknumber' in metadata:
            audio['tracknumber'] = metadata['tracknumber']
        if 'genre' in metadata:
            audio['genre'] = metadata['genre']
        if 'label' in metadata:
            audio['label'] = metadata['label']
        if 'isrc' in metadata:
            audio['isrc'] = metadata['isrc']
        
        # MusicBrainz tags
        if 'musicbrainz_albumid' in metadata:
            audio['musicbrainz_albumid'] = metadata['musicbrainz_albumid']
        if 'acoustid_id' in metadata:
            audio['acoustid_id'] = metadata['acoustid_id']
        
        # OGG için kapak FLAC Picture formatında
        if covers:
            import base64
            for idx, (cover_data, mime_type) in enumerate(covers):
                picture = Picture()
                picture.type = 3
                picture.mime = 'image/png' if 'png' in mime_type.lower() else 'image/jpeg'
                picture.desc = 'Album cover' if idx == 0 else 'Cover'
                picture.data = cover_data
                
                encoded_data = base64.b64encode(picture.write())
                audio[f'metadata_block_picture'] = encoded_data.decode('ascii')
                break  # OGG genelde tek kapak destekler
        
        audio.save()
        return True
    
    def _tag_m4a(self, filepath: str, metadata: Dict, covers: List[Tuple[bytes, str]]) -> bool:
        """M4A/MP4 dosyasını etiketle"""
        audio = MP4(filepath)
        
        # M4A tag mapping
        if 'title' in metadata:
            audio['\xa9nam'] = metadata['title']
        if 'artist' in metadata:
            audio['\xa9ART'] = metadata['artist']
        if 'album' in metadata:
            audio['\xa9alb'] = metadata['album']
        if 'albumartist' in metadata:
            audio['aART'] = metadata['albumartist']
        if 'date' in metadata:
            audio['\xa9day'] = metadata['date']
        if 'tracknumber' in metadata and 'totaltracks' in metadata:
            audio['trkn'] = [(int(metadata['tracknumber']), int(metadata['totaltracks']))]
        elif 'tracknumber' in metadata:
            audio['trkn'] = [(int(metadata['tracknumber']), 0)]
        if 'discnumber' in metadata and 'totaldiscs' in metadata:
            audio['disk'] = [(int(metadata['discnumber']), int(metadata['totaldiscs']))]
        if 'genre' in metadata:
            audio['\xa9gen'] = metadata['genre']
        
        # Kapak fotoğrafları
        if covers:
            cover_list = []
            for cover_data, mime_type in covers:
                if 'png' in mime_type.lower():
                    cover_list.append(MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_PNG))
                else:
                    cover_list.append(MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG))
            audio['covr'] = cover_list
        
        audio.save()
        return True
    
    def process_file(self, filepath: str, save_cover: bool = False) -> bool:
        """Tek bir dosyayı işle"""
        self.logger.info(f"Etiketleme başlatıldı: {os.path.basename(filepath)}")
        
        # 1. Parmak izi al
        self.logger.debug("AcoustID fingerprint alınıyor...")
        acoustid_result = self.lookup_acoustid(filepath)
        
        if not acoustid_result:
            self.logger.warning("AcoustID eşleşmesi bulunamadı")
            return False
        
        score = acoustid_result.get('score', 0)
        self.logger.info(f"AcoustID eşleşme: %{score*100:.1f}")
        
        # 2. Release bilgilerini al
        release_id = None
        recording_id = None
        
        if 'recordings' in acoustid_result and acoustid_result['recordings']:
            recording = acoustid_result['recordings'][0]
            recording_id = recording.get('id')
            
            if 'releasegroups' in recording and recording['releasegroups']:
                for rg in recording['releasegroups']:
                    if 'releases' in rg and rg['releases']:
                        release_id = rg['releases'][0]['id']
                        break
        
        if not release_id:
            self.logger.warning("MusicBrainz release bulunamadı")
            return False
        
        self.logger.debug(f"MusicBrainz release: {release_id}")
        release_data = self.get_musicbrainz_release(release_id)
        
        if not release_data:
            self.logger.error("Release bilgileri alınamadı")
            return False
        
        # 3. Metadata hazırla
        metadata = self.extract_metadata(acoustid_result, release_data, recording_id)
        
        if metadata.get('title') and metadata.get('artist'):
            self.logger.info(f"Bulundu: {metadata['artist']} - {metadata['title']}")
        
        # 4. Kapak fotoğraflarını indir
        covers = self.get_cover_art(release_id)
        
        if covers:
            self.logger.debug(f"{len(covers)} kapak indirildi")
            
            if save_cover and covers:
                for idx, (cover_data, mime_type) in enumerate(covers):
                    ext = 'png' if 'png' in mime_type.lower() else 'jpg'
                    cover_path = os.path.join(
                        os.path.dirname(filepath),
                        f'cover{idx if idx > 0 else ""}.{ext}'
                    )
                    with open(cover_path, 'wb') as f:
                        f.write(cover_data)
                    self.logger.info(f"Kapak kaydedildi: {cover_path}")
        
        # 5. Dosyayı etiketle
        success = self.tag_file(filepath, metadata, covers)
        
        if success:
            self.logger.info("✓ Etiketleme başarılı")
            return True
        else:
            self.logger.error("Etiketleme başarısız")
            return False
    
    def process_directory(self, directory: str, recursive: bool = False, save_cover: bool = False):
        """Dizindeki tüm müzik dosyalarını işle"""
        supported_extensions = ['.mp3', '.flac', '.ogg', '.oga', '.m4a', '.mp4', '.m4b']
        
        if recursive:
            files = []
            for root, _, filenames in os.walk(directory):
                for filename in filenames:
                    if os.path.splitext(filename)[1].lower() in supported_extensions:
                        files.append(os.path.join(root, filename))
        else:
            files = [
                os.path.join(directory, f)
                for f in os.listdir(directory)
                if os.path.splitext(f)[1].lower() in supported_extensions
            ]
        
        if not files:
            self.logger.warning("Müzik dosyası bulunamadı")
            return
        
        self.logger.info(f"{len(files)} dosya bulundu")
        
        success_count = 0
        fail_count = 0
        
        for filepath in files:
            try:
                if self.process_file(filepath, save_cover):
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                print(f"Hata: {e}")
                fail_count += 1
        
        self.logger.info(f"Toplu etiketleme tamamlandı: {success_count} başarılı, {fail_count} başarısız")


def main():
    parser = argparse.ArgumentParser(
        description='MusicBrainz Audio Tagger - Picard alternatifi CLI aracı'
    )
    parser.add_argument(
        'path',
        help='İşlenecek dosya veya dizin'
    )
    parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        help='Alt dizinleri de tara'
    )
    parser.add_argument(
        '-c', '--save-cover',
        action='store_true',
        help='Kapak fotoğrafını ayrı dosya olarak da kaydet'
    )
    parser.add_argument(
        '-u', '--user-agent',
        default='MusicTagger/1.0',
        help='User-Agent string (varsayılan: MusicTagger/1.0)'
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.path):
        print(f"Hata: '{args.path}' bulunamadı")
        sys.exit(1)
    
    tagger = MusicTagger(args.user_agent)
    
    if os.path.isfile(args.path):
        tagger.process_file(args.path, args.save_cover)
    elif os.path.isdir(args.path):
        tagger.process_directory(args.path, args.recursive, args.save_cover)
    else:
        print(f"Hata: '{args.path}' geçerli bir dosya veya dizin değil")
        sys.exit(1)


if __name__ == '__main__':
    main()