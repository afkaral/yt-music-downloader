# src/threads.py
from PySide6.QtCore import QThread, Signal
from constants import SEARCH_LIMIT
from config import * 
import subprocess
import logging
import re
import os
from music_tagger import MusicTagger

logger = logging.getLogger(__name__)

class VideoPlayer(QThread):
    finished_playing = Signal()
    def __init__(self, player, url):
        super().__init__()
        self.player = player
        self.url = url

    def run(self):
        try:
            command = [self.player]
            if self.player == "mpv":
                command += [
                    "--vo=gpu",
                    "--gpu-api=opengl",
                ]
            command.append(self.url)

            subprocess.Popen(command)

            logger.info(f"Video oynatılıyor: {self.url}")
            self.finished_playing.emit()

        except Exception as e:
            logger.error(f"Video oynatma hatası: {e}")

class SearchThread(QThread):
    result = Signal(str, str, str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, query, limit):
        super().__init__()
        self.query = query
        self._stop = False
        self.process = None
        self.limit = limit

    
    def stop(self):
        self._stop = True

        if self.process and self.process.poll() is None:
            self.process.kill()

    def run(self):
        self.process = subprocess.Popen(
            [
                "yt-dlp",
                f"ytsearch{self.limit}:{self.query}",
                "--print",
                "%(id)s\t%(title)s\t%(uploader)s",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        if self.process.stdout:
            for line in self.process.stdout:
                try:
                    if self._stop:
                        break
                    video_id, title, uploader = line.rstrip().split("\t", 2)
                    url = f"https://youtu.be/{video_id}"
                    self.result.emit(title, uploader, url)
                except ValueError:
                    logger.debug(f"Beklenmeyen arama çıktısı: {line}")

        stderr = self.process.stderr.read() if self.process.stderr else ""

        if self.process.wait() != 0:
            self.error.emit(stderr)

        self.finished.emit()

class DownloadThread(QThread):
    finished = Signal(str)
    progress = Signal(int)
    error = Signal(str)

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        output = []

        if process.stdout:
            for line in process.stdout:
                output.append(line)

                if "%" in line:
                    try:
                        m = re.search(r"(\d+(?:\.\d+)?)%", line)
                        if m:
                            self.progress.emit(int(float(m.group(1))))
                    except Exception as e:
                        logger.debug(f"İlerleme parse hatası: {e}")

        if process.wait() == 0:
            self.finished.emit("".join(output))
        else:
            self.error.emit("".join(output))

class MusicTaggerThread(QThread):
    finished = Signal(str)
    error = Signal(str)
    
    def __init__(self, file_path, api_key=None):
        super().__init__()
        self.file_path = file_path
        self.api_key = api_key

    def run(self):
        try:
            logger.info(f"MusicBrainz etiketleme başlatılıyor: {self.file_path}")
            
            # MusicTagger instance oluştur
            tagger = MusicTagger(
                user_agent="YtMusicDownloader/1.0",
                api_key=self.api_key
            )
            
            # Dosyayı etiketle
            success = tagger.process_file(self.file_path, save_cover=False)
            
            if success:
                logger.info("✓ Etiketleme tamamlandı")
                self.finished.emit("Etiketleme başarılı")
            else:
                logger.warning("Etiketleme başarısız oldu")
                self.error.emit("Etiketleme başarısız")
                
        except Exception as e:
            logger.error(f"MusicTagger kritik hatası: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self.error.emit(str(e))

# Geriye dönük uyumluluk için alias
PicardTaggingThread = MusicTaggerThread
