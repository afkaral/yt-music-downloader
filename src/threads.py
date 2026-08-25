# src/threads.py
from PySide6.QtCore import QThread, Signal
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
                    "--force-window=yes",
                ]
            command.append(self.url)

            subprocess.Popen(command)
            logger.info(f"Video playback started: {self.url}")
            self.finished_playing.emit()

        except Exception as e:
            logger.error(f"Video playback error: {e}")

class SearchThread(QThread):
    # title, uploader, url, platform
    result = Signal(str, str, str, str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, query, limit, platforms=None):
        """Search thread using yt‑dlp.

        Parameters
        ----------
        query: str – Search term.
        limit: int – Max results.
        platforms: list[str] or None – yt‑dlp search prefixes. If ``None`` a default list is used.
        """
        super().__init__()
        self.query = query
        self._stop = False
        self.process = None
        self.limit = limit
        # Platforms to query; defaults to YouTube, SoundCloud and Vimeo.
        self.platforms = platforms or ["ytsearch", "scsearch", "gvsearch"]

    def stop(self):
        self._stop = True
        if self.process and self.process.poll() is None:
            self.process.kill()

    def run(self):
        logger.info(
            f"Running composite search for query: '{self.query}', total limit: {self.limit}"
        )

        # Perform a search on a single platform and return list of
        #(title, uploader, url, platform) tuples
        def fetch_platform_results(platform):
            search_expr = f"{platform}{self.limit}:{self.query}"
            cmd = [
                "yt-dlp",
                "--flat-playlist",
                "--dump-json",
                f"--max-downloads={self.limit}",
                search_expr,
            ]

            logger.info(f"Executing {platform} command: {' '.join(cmd)}")
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONENCODING"] = "utf-8"

            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
            )
            import json
            results = []
            for line in completed.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                title = data.get("title") or ""
                uploader = data.get("uploader") or ""
                url = data.get("webpage_url") or data.get("url") or ""
                if not url:
                    # fallback to YouTube short link if id present
                    video_id = data.get("id")
                    if video_id:
                            url = f"https://youtu.be/{video_id}"
                if url:
                    results.append((title, uploader, url, platform))
            if completed.returncode != 0:
                logger.error(f"{platform} search failed: {completed.stderr}")
                self.error.emit(completed.stderr)
            return results

        # Gather results from each platform in the order defined in self.platforms
        platform_results = {p: fetch_platform_results(p) for p in self.platforms}

        # Merge results: take up to two items from each platform per round
        merged = []
        idx = {p: 0 for p in self.platforms}
        while len(merged) < self.limit:
            made_progress = False
            for p in self.platforms:
                for _ in range(2):
                    i = idx[p]
                    if i < len(platform_results[p]):
                        merged.append(platform_results[p][i])
                        idx[p] += 1
                        made_progress = True
                        if len(merged) >= self.limit:
                            break
                if len(merged) >= self.limit:
                    break
            if not made_progress:
                break

        # Emit the combined, ordered results
        logger.info(f"Merged {len(merged)} results to emit")
        for title, uploader, url, platform in merged:
            logger.info(f"Emitting result: [{platform}] {title} - {uploader}")
            self.result.emit(title, uploader, url, platform)

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
                        logger.debug(f"Parse error: {e}")

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
            logger.info(f"Starting MusicBrainz tagging: {self.file_path}")
            
            # MusicTagger instance oluştur
            tagger = MusicTagger(
                user_agent="YtMusicDownloader/1.0",
                api_key=self.api_key
            )
            
            # Tag the file
            success = tagger.process_file(self.file_path, save_cover=False)
            
            if success:
                logger.info("Tagging complete")
                self.finished.emit("Tagging complete")
            else:
                logger.warning("Tagging failed")
                self.error.emit("Tagging failed")
                
        except Exception as e:
            logger.error(f"MusicTagger critical error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self.error.emit(str(e))

# Alias for backward compatibility
PicardTaggingThread = MusicTaggerThread

