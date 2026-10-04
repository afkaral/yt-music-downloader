"""
Embedded Audio Preview Player Widget for GUI.
Uses core.player.MpvPlayer for in-process, audio-only playback.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, 
    QSlider, QLabel, QFrame
)
from PySide6.QtCore import Qt, Signal, QObject
import logging

try:
    from ..core.player import MpvPlayer, format_time
except ImportError:
    from core.player import MpvPlayer, format_time

logger = logging.getLogger(__name__)


class PlayerSignals(QObject):
    time_updated = Signal(float)
    duration_updated = Signal(float)
    playback_ended = Signal()


class AudioPlayerWidget(QWidget):
    """Bottom bar audio preview player."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0.0
        self._is_seeking = False
        
        # Thread-safe signals to communicate from mpv callbacks to Qt main thread
        self._signals = PlayerSignals()
        self._signals.time_updated.connect(self._on_time_updated)
        self._signals.duration_updated.connect(self._on_duration_updated)
        self._signals.playback_ended.connect(self._on_playback_ended)

        self._player = MpvPlayer(
            on_time_pos=self._signals.time_updated.emit,
            on_duration=self._signals.duration_updated.emit,
            on_end_file=self._signals.playback_ended.emit
        )

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(2)

        # Subtle separator frame at top
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line)

        # Track title label
        self.title_label = QLabel("No track playing")
        self.title_label.setStyleSheet("font-size: 11px; color: #555;")
        main_layout.addWidget(self.title_label)

        # Controls row
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(6)

        # Play / Pause
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(36)
        self.play_btn.setFixedHeight(36)
        self.play_btn.setToolTip("Play / Pause")
        self.play_btn.clicked.connect(self.toggle_play_pause)
        ctrl_layout.addWidget(self.play_btn)

        # Stop
        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedWidth(36)
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setToolTip("Stop")
        self.stop_btn.clicked.connect(self.stop)
        ctrl_layout.addWidget(self.stop_btn)

        # Time: current
        self.current_time_label = QLabel("0:00")
        self.current_time_label.setFixedWidth(36)
        self.current_time_label.setFixedHeight(36)
        self.current_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ctrl_layout.addWidget(self.current_time_label)

        # Seek Slider
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        ctrl_layout.addWidget(self.seek_slider)

        # Time: duration
        self.total_time_label = QLabel("0:00")
        self.total_time_label.setFixedWidth(36)
        self.total_time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ctrl_layout.addWidget(self.total_time_label)

        # Volume label & slider
        vol_label = QLabel("🔊")
        ctrl_layout.addWidget(vol_label)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self._player.get_volume())
        self.volume_slider.setFixedWidth(75)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        ctrl_layout.addWidget(self.volume_slider)

        main_layout.addLayout(ctrl_layout)

    def play_url(self, url: str, title: str = ""):
        """Load and play a given audio stream URL."""
        if title:
            self.title_label.setText(title)
        else:
            self.title_label.setText(url)

        self._duration = 0.0
        self.seek_slider.setValue(0)
        self.current_time_label.setText("0:00")
        self.total_time_label.setText("0:00")
        self.play_btn.setText("⏸")
        self._player.play(url)

    def toggle_play_pause(self):
        """Toggle pause/play state."""
        is_paused = self._player.toggle_pause()
        self.play_btn.setText("▶" if is_paused else "⏸")

    def stop(self):
        """Stop playback."""
        self._player.stop()
        self.play_btn.setText("▶")
        self.seek_slider.setValue(0)
        self.current_time_label.setText("0:00")
        self.title_label.setText("Stopped")

    def _on_time_updated(self, current: float):
        if not self._is_seeking:
            if self._duration > 0:
                slider_pos = int((current / self._duration) * 1000)
                self.seek_slider.setValue(slider_pos)
            self.current_time_label.setText(format_time(current))

    def _on_duration_updated(self, duration: float):
        self._duration = duration
        self.total_time_label.setText(format_time(duration))

    def _on_playback_ended(self):
        self.play_btn.setText("▶")
        self.seek_slider.setValue(0)
        self.current_time_label.setText("0:00")

    def _on_seek_pressed(self):
        self._is_seeking = True

    def _on_seek_released(self):
        if self._duration > 0:
            target_seconds = (self.seek_slider.value() / 1000.0) * self._duration
            self._player.seek(target_seconds)
            self.current_time_label.setText(format_time(target_seconds))
        self._is_seeking = False

    def _on_volume_changed(self, value: int):
        self._player.set_volume(value)

    def cleanup(self):
        """Terminate mpv on window close."""
        self._player.terminate()
