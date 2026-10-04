"""
Audio player module using python-mpv.
Provides non-blocking audio-only playback with volume, seek, and state control.
"""

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def format_time(seconds: Optional[float]) -> str:
    """Format seconds into M:SS or H:MM:SS string."""
    if seconds is None or seconds < 0:
        return "0:00"
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class MpvPlayer:
    """Non-blocking audio player wrapping python-mpv."""

    def __init__(self, on_time_pos: Optional[Callable[[float], None]] = None,
                 on_duration: Optional[Callable[[float], None]] = None,
                 on_end_file: Optional[Callable[[], None]] = None):
        self.on_time_pos = on_time_pos
        self.on_duration = on_duration
        self.on_end_file = on_end_file
        self._mpv = None
        self._current_url = None
        self._init_mpv()

    def _init_mpv(self):
        try:
            import mpv
            # Audio only: vo=null, video=no prevents opening any window
            self._mpv = mpv.MPV(
                vo="null",
                video=False,
                audio_display=False,
                ytdl=True,
                loglevel="error"
            )

            @self._mpv.property_observer("time-pos")
            def _time_observer(_name, value):
                if value is not None and self.on_time_pos:
                    self.on_time_pos(float(value))

            @self._mpv.property_observer("duration")
            def _duration_observer(_name, value):
                if value is not None and self.on_duration:
                    self.on_duration(float(value))

            @self._mpv.event_callback("end-file")
            def _end_file_cb(_event):
                if self.on_end_file:
                    self.on_end_file()

        except Exception as e:
            logger.error(f"Failed to initialize python-mpv: {e}")
            self._mpv = None

    @property
    def is_available(self) -> bool:
        return self._mpv is not None

    def play(self, url: str):
        """Start playing given URL (audio only)."""
        if not self._mpv:
            logger.warning("mpv is not initialized.")
            return
        self._current_url = url
        try:
            self._mpv.pause = False
            self._mpv.loadfile(url, "replace")
            logger.info(f"Playback started for: {url}")
        except Exception as e:
            logger.error(f"Error loading URL into mpv: {e}")

    def toggle_pause(self) -> bool:
        """Toggle play/pause state. Returns True if now paused."""
        if not self._mpv:
            return False
        try:
            self._mpv.pause = not self._mpv.pause
            return bool(self._mpv.pause)
        except Exception as e:
            logger.error(f"Error toggling pause: {e}")
            return False

    def is_paused(self) -> bool:
        if not self._mpv:
            return True
        try:
            return bool(self._mpv.pause)
        except Exception:
            return True

    def stop(self):
        """Stop playback and clear current track."""
        if not self._mpv:
            return
        try:
            self._mpv.stop()
        except Exception as e:
            logger.error(f"Error stopping mpv: {e}")

    def seek(self, seconds: float):
        """Seek to absolute position in seconds."""
        if not self._mpv:
            return
        try:
            self._mpv.seek(seconds, reference="absolute")
        except Exception as e:
            logger.error(f"Error seeking: {e}")

    def set_volume(self, volume: int):
        """Set volume (0 - 100)."""
        if not self._mpv:
            return
        try:
            self._mpv.volume = max(0, min(100, volume))
        except Exception as e:
            logger.error(f"Error setting volume: {e}")

    def get_volume(self) -> int:
        if not self._mpv:
            return 100
        try:
            return int(self._mpv.volume or 100)
        except Exception:
            return 100

    def terminate(self):
        """Cleanup and terminate mpv instance."""
        if self._mpv:
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None