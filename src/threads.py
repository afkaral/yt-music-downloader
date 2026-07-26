# src/threads.py

from PySide6.QtCore import QThread, Signal
from constants import SEARCH_LIMIT
from config import * 
import subprocess
import logging
import re

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

            logging.info(f"Oynatılan URL: {self.url}")
            self.finished_playing.emit()

        except Exception as e:
            logging.error(f"Hata: {e}")

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
                    logging.warning(f"Beklenmeyen çıktı: {line}")

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
                        logging.debug(e)

        if process.wait() == 0:
            self.finished.emit("".join(output))
        else:
            self.error.emit("".join(output))