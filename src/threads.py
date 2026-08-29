# src/threads.py
from PySide6.QtCore import QThread, Signal
import subprocess
import logging
import re
import os
import json
from pathlib import Path
from music_tagger import MusicTagger
from utils import _get_duration_ffprobe, _atomic_write

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

            # Store the Popen object so we can terminate it on close
            self._proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"Video playback started: {self.url}")
        except Exception as e:
            logger.error(f"Video playback error: {e}")
        finally:
            self.finished_playing.emit()

#  SearchThread – streams results from YouTube (ytsearch) and SoundCloud (scsearch)
class SearchThread(QThread):
    result   = Signal(str, str, str, str)
    finished = Signal()
    error    = Signal(str)

    def __init__(self, query: str, limit: int, platforms: list | None = None):
        super().__init__()
        self.query   = query
        self.limit   = limit
        self._stop   = False
        self.platforms = platforms or ["ytsearch", "scsearch"]

    # Public API – ask the thread to stop ASAP
    def stop(self):
        self._stop = True

    # Make sure subprocesses output unbuffered UTF‑8 JSON lines
    @staticmethod
    def _env() -> dict:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONENCODING"]   = "utf-8"
        env["PYTHONUNBUFFERED"] = "1" 
        return env

    # Build the yt‑dlp command for a given platform
    def _build_cmd(self, platform: str) -> list[str]:
        expr = f"{platform}{self.limit}:{self.query}"
        cmd = [
            "yt-dlp",
            "--dump-json",
            f"--max-downloads={self.limit}",
            expr,
        ]
        if platform == "ytsearch":
            cmd.insert(1, "--flat-playlist")
        return cmd

    # Core – launch a subprocess per platform, read them concurrently
    def run(self):
        logger.info(
            f"Starting streaming search for '{self.query}' on {self.platforms} "
            f"(global limit={self.limit})"
        )
        emitted = 0                     # total results emitted so far
        processes = {}                  # platform → subprocess.Popen

        # Spawn a subprocess for each requested platform
        for platform in self.platforms:
            try:
                cmd = self._build_cmd(platform)
                logger.debug(f"Launching {platform}: {' '.join(cmd)}")
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,          # line‑buffered output
                    env=self._env(),
                )
                processes[platform] = proc
            except Exception as exc:
                logger.error(f"Failed to start {platform} search: {exc}")
                self.error.emit(f"{platform} start error: {exc}")

        if not processes:
            # Nothing could be started – finish immediately
            self.finished.emit()
            return

        import selectors

        selector = selectors.DefaultSelector()
        for plat, proc in processes.items():
            selector.register(proc.stdout, selectors.EVENT_READ, data=plat)

        while processes and emitted < self.limit and not self._stop:
            events = selector.select(timeout=0.2)
            if not events:
                continue

            for key, _ in events:
                platform = key.data
                proc = processes[platform]
                line = proc.stdout.readline()
                if not line:
                    selector.unregister(proc.stdout)
                    proc.wait()
                    del processes[platform]
                    continue

                line = line.strip()
                if not line:
                    continue

                # Parse the JSON line and emit the result.
                try:
                    data = json.loads(line)
                except Exception:
                    # Occasionally yt‑dlp may emit non‑JSON lines (warnings).
                    continue

                title = data.get("title") or ""
                uploader = data.get("uploader") or ""
                url = (
                    data.get("webpage_url")
                    or data.get("url")
                    or (f"https://youtu.be/{data['id']}" if data.get("id") else "")
                )

                if url:
                    self.result.emit(title, uploader, url, platform)
                    emitted += 1

                # Stop if we have reached the global limit.
                if emitted >= self.limit:
                    break

        # Clean‑up: terminate any still‑running subprocesses.
        for platform, proc in processes.items():
            if proc.poll() is None:               # still alive
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
            # Close the pipes (ignore possible errors)
            try:
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()
            except Exception:
                pass

        logger.info("SearchThread finished – emitted %d results", emitted)
        self.finished.emit()

class DownloadThread(QThread):
    finished = Signal(str)
    progress = Signal(int)
    error = Signal(str)

    def __init__(self, command):
        super().__init__()
        self.command = command
        self._stop = False
        self.process = None

    def stop(self):
        self._stop = True
        if self.process:
            try:
                # Try to terminate gracefully first
                self.process.terminate()
                # Give it a moment to close files
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception as e:
                logger.error(f"Error stopping download process: {e}")

    def run(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        try:
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )

            output_lines = []
            
            if self.process.stdout:
                for line in self.process.stdout:
                    if self._stop:
                        break
                    
                    output_lines.append(line)

                    if "%" in line:
                        try:
                            m = re.search(r"(\d+(?:\.\d+)?)%", line)
                            if m:
                                self.progress.emit(int(float(m.group(1))))
                        except Exception:
                            pass

            # If stopped, kill remaining process
            if self._stop and self.process.poll() is None:
                self.process.kill()
                self.process.wait()
                self.error.emit("Download cancelled by user")
                return

            exit_code = self.process.wait()
            
            if exit_code == 0:
                self.finished.emit("".join(output_lines))
            else:
                error_msg = "".join(output_lines)
                self.error.emit(error_msg)

        except Exception as e:
            logger.error(f"Download thread exception: {e}")
            self.error.emit(str(e))


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
            
            tagger = MusicTagger(
                user_agent="YtMusicDownloader/1.0",
                api_key=self.api_key
            )
            
            success = tagger.process_file(self.file_path, save_cover=False)
            
            if success:
                self.finished.emit("Tagging complete")
            else:
                # Distinguish between "no match found" and actual error
                self.error.emit("No metadata match found or tagging failed")
                
        except Exception as e:
            logger.error(f"MusicTagger critical error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self.error.emit(str(e))


class M3URebuildThread(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, folder):
        super().__init__()
        self.folder = Path(folder).resolve()
        self.audio_extensions = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".wma"}

    def run(self):
        playlist_path = self.folder / f"{self.folder.name}.m3u"

        if not self.folder.is_dir():
            logger.error("Cannot rebuild M3U: '%s' is not a directory", self.folder)
            self.error.emit(f"Directory not found: {self.folder}")
            return

        try:
            current_files = {}
            # Iterate and get duration
            for item in self.folder.iterdir():
                if (
                    item.is_file()
                    and item.suffix.lower() in self.audio_extensions
                    and item != playlist_path
                ):
                    # Use ffprobe, handle errors inside _get_duration_ffprobe
                    duration = _get_duration_ffprobe(item)
                    current_files[item.name] = {
                        "path": item,
                        "duration": duration,
                        "stem": item.stem
                    }

            lines = ["#EXTM3U\n"]
            for filename in sorted(current_files.keys()):
                file_info = current_files[filename]
                lines.append(f"#EXTINF:{file_info['duration']},{file_info['stem']}\n")
                try:
                    rel_path = file_info["path"].relative_to(self.folder)
                    lines.append(f"{rel_path}\n")
                except ValueError:
                    lines.append(f"{file_info['path'].name}\n")

            _atomic_write(playlist_path, "".join(lines))
            logger.debug("Playlist updated with %d tracks", len(current_files))
            self.finished.emit(str(playlist_path))

        except Exception as e:
            logger.error("Failed to rebuild M3U: %s", e)
            self.error.emit(str(e))


PicardTaggingThread = MusicTaggerThread