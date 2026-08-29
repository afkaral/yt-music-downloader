# src/main.py
import sys
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QLabel, QWidget, QVBoxLayout, 
    QLineEdit, QPushButton, QListWidget, 
    QListWidgetItem, QFileDialog, QHBoxLayout,
    QDialog, QComboBox, QSpinBox, QCheckBox,
    QGroupBox, QFormLayout
)
from PySide6.QtGui import QIcon, QFont
from PySide6.QtCore import Qt, QThread, Signal
# Import specific functions to avoid namespace pollution
from utils import load_config, save_config, find_downloaded_file
from threads import (
    SearchThread,
    DownloadThread,
    VideoPlayer,
    MusicTaggerThread,
    M3URebuildThread,
)
from logging_config import configure_logging

# Configure logging
logger = configure_logging()

# Centralized fallback values
DEFAULT_ACoustID_KEY = "v8pQ6oyB"

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.config = load_config()

        self.setWindowTitle("Settings")
        icon_path = "resources/icon.png"
        if Path(icon_path).exists():
            self.setWindowIcon(QIcon(icon_path))
        self.resize(480, 350)

        layout = QVBoxLayout(self)

        # Player
        layout.addWidget(QLabel("Player"))
        self.player = QComboBox()
        self.player.addItems(["mpv", "vlc", "celluloid", "clementine"])
        self.player.setCurrentText(self.config.get("player", "mpv"))
        layout.addWidget(self.player)

        # ---- Exclusive platform selector ---------------------------------
        self.platform_selector = QComboBox()
        self.platform_selector.addItems(["YouTube", "SoundCloud"])
        # Load the saved value (default to YouTube)
        saved_platform = self.config.get("search_platform", "YouTube")
        idx = self.platform_selector.findText(saved_platform)
        if idx >= 0:
            self.platform_selector.setCurrentIndex(idx)

        layout.addWidget(QLabel("Search platform"))
        layout.addWidget(self.platform_selector)

        # Download path
        layout.addWidget(QLabel("Default download folder"))
        path_layout = QHBoxLayout()
        self.path = QLineEdit(self.config.get("download_path", str(Path.home() / "Music")))
        self.path.setReadOnly(True)
        browse = QPushButton("...")
        path_layout.addWidget(self.path)
        path_layout.addWidget(browse)
        layout.addLayout(path_layout)
        browse.clicked.connect(self.select_folder)

        # Search limit
        layout.addWidget(QLabel("Search results limit"))
        self.limit = QSpinBox()
        self.limit.setRange(5, 200)
        self.limit.setSingleStep(5)
        self.limit.setValue(self.config.get("search_limit", 50))
        layout.addWidget(self.limit)

        # M3U creation
        self.create_m3u = QCheckBox("Generate M3U playlist after download")
        self.create_m3u.setChecked(self.config.get("create_m3u", True))
        layout.addWidget(self.create_m3u)

        # AcoustID API Key
        layout.addWidget(QLabel("AcoustID API Key (free: acoustid.org/api-key)"))
        self.api_key = QLineEdit(self.config.get("acoustid_api_key", DEFAULT_ACoustID_KEY))
        self.api_key.setPlaceholderText("Get your own API key (optional)")
        layout.addWidget(self.api_key)

        # Save button
        save = QPushButton("Save")
        save.clicked.connect(self.save)
        layout.addWidget(save)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select default folder"
        )

        if folder:
            self.path.setText(folder)

    def save(self):
        self.config["player"] = self.player.currentText()
        self.config["download_path"] = self.path.text()
        self.config["search_limit"] = self.limit.value()
        self.config["create_m3u"] = self.create_m3u.isChecked()
        self.config["acoustid_api_key"] = self.api_key.text().strip()
        self.config["search_platform"] = self.platform_selector.currentText()

        save_config(self.config)

        self.accept()

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.config = load_config()
        self.download_path = self.config.get("download_path", str(Path.home() / "Music"))

        # Thread references
        self.search_thread = None
        self.download_thread = None
        self.player_thread = None
        self.tagger_thread = None
        self.m3u_thread = None

        self.setWindowTitle(self.config.get("window_title", "Yt Music Downloader"))
        self.setGeometry(100, 100, 650, 600) # Slightly wider for better layout
        
        # Main UI
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)

        # Search Area
        search_layout = QHBoxLayout()

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search for music...")
        self.search_bar.returnPressed.connect(self.search_videos)
        search_layout.addWidget(self.search_bar)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedWidth(36)
        self.settings_button.clicked.connect(self.open_settings)
        search_layout.addWidget(self.settings_button)

        self.stop_button = QPushButton("X")
        self.stop_button.setFixedWidth(32)
        self.stop_button.clicked.connect(self.stop_search)
        self.stop_button.setEnabled(False)
        search_layout.addWidget(self.stop_button)

        layout.addLayout(search_layout)

        # Results List
        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self.play_video)
        self._seen_urls = set()
        layout.addWidget(self.result_list)

        # Action Buttons
        button_layout = QHBoxLayout()

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.play_selected)
        self.play_button.setEnabled(False) # Disabled until item selected

        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self.download_selected)
        
        button_layout.addWidget(self.play_button)
        button_layout.addWidget(self.download_button)
        layout.addLayout(button_layout)

        # Folder Selection
        folder_layout = QHBoxLayout()
        self.folder_button = QPushButton("Select Download Folder")
        self.folder_button.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.folder_button)
        layout.addLayout(folder_layout)

        # Status Footer
        status_layout = QHBoxLayout()
        
        self.path_label = QLabel(f"Path: {self.download_path}")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("color: gray; font-size: 12px;")
        
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-weight: bold; color: #007A33;") # Green
        
        status_layout.addWidget(self.path_label)
        status_layout.addStretch() # Push status to right
        status_layout.addWidget(self.status_label)
        
        layout.addLayout(status_layout)

        self.setLayout(layout)

        # Connect selection change to enable/disable play button
        self.result_list.currentItemChanged.connect(self.on_item_selection_changed)

    def on_item_selection_changed(self, current, previous):
        if current:
            self.play_button.setEnabled(True)
        else:
            self.play_button.setEnabled(False)

    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.config = load_config()
            self.download_path = self.config.get("download_path", str(Path.home() / "Music"))
            self.path_label.setText(f"Path: {self.download_path}")
            logger.info("Settings updated")

    def search_videos(self):
        query = self.search_bar.text().strip()
        if not query:
            return

        self.set_status("Searching...", "blue")
        self.stop_button.setEnabled(True)

        # Stop any previous search
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.stop()
            self.search_thread.wait()

        self.result_list.clear()

        limit = self.config.get("search_limit", 50)

        # -----------------------------------------------------------------
        # ONE platform ONLY – read the setting saved by SettingsDialog
        # -----------------------------------------------------------------
        platform_name = self.config.get("search_platform", "YouTube")
        if platform_name == "YouTube":
            platforms = ["ytsearch"]
        else:   # SoundCloud
            platforms = ["scsearch"]

        logger.info(f"Starting search for '{query}' (limit {limit}) on {platforms}")

        self.search_thread = SearchThread(query, limit, platforms)
        self.search_thread.result.connect(self.add_result)
        self.search_thread.finished.connect(self.search_finished)
        self.search_thread.error.connect(self.search_failed)
        self.search_thread.start()

    def add_result(self, title, uploader, url, platform):
        """Add a single search result to the list widget."""
        if not url or url in ("NA", "None", ""):
            return
                
        prefix = f"[{platform}]"
        display = f"{prefix}{title} - {uploader}"
            
        item = QListWidgetItem(display)
        item.setData(Qt.UserRole, url)
        item.setData(Qt.UserRole + 1, platform)
        self.result_list.addItem(item)

    def search_finished(self):
        count = self.result_list.count()
        self.set_status(f"Search Complete: {count} results found", "#007A33") # Green
        self.stop_button.setEnabled(False)

    def stop_search(self):
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.stop()
            self.set_status("Search Stopped", "orange")
            logger.info("Search stopped by user.")

    def search_failed(self, error):
        self.set_status(f"Search Failed: {error}", "red")
        logger.error(f"Search error: {error}")
        error_item = QListWidgetItem(f"Error: {error}")
        error_item.setData(Qt.UserRole, "")
        self.result_list.addItem(error_item)

    def play_video(self, item):
        if self.player_thread and self.player_thread.isRunning():
            return

        url = item.data(Qt.UserRole)

        if not url or url in ("NA", "None"):
            logger.warning("Invalid URL for playback")
            self.set_status("Invalid URL", "red")
            return

        self.play_button.setEnabled(False)
        self.set_status(f"Playing: {item.text()}", "#005A9C") # Blue

        self.player_thread = VideoPlayer(
            self.config.get("player", "mpv"),
            url
        )
        self.player_thread.finished_playing.connect(
            lambda: self.play_button.setEnabled(True)
        )
        self.player_thread.start()

    def play_selected(self):
        item = self.result_list.currentItem()
        if item:
            self.play_video(item)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select download folder"
        )

        if folder:
            self.download_path = folder
            self.config["download_path"] = folder
            save_config(self.config)
            self.path_label.setText(f"Path: {folder}")
            logger.info(f"Download folder changed to: {folder}")
            self.set_status(f"Folder set to: {folder}", "#007A33")

    def download_selected(self):
        if self.download_thread and self.download_thread.isRunning():
            return
            
        item = self.result_list.currentItem()

        if not item:
            self.set_status("Please select a track first", "orange")
            return

        url = item.data(Qt.UserRole)

        if not url or url in ("NA", "None"):
            logger.warning("Invalid URL for download")
            self.set_status("Invalid URL", "red")
            return

        logger.info(f"Starting download: {url}")
        self.set_status("Downloading...", "#005A9C")

        command = [
            "yt-dlp",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--embed-thumbnail",
            "--embed-metadata",
            "--no-playlist",
        ]

        if self.download_path:
            command += [
                "-o",
                f"{self.download_path}/%(title)s.%(ext)s"
            ]

        command.append(url)

        self.download_button.setEnabled(False)
        self.download_button.setText("Downloading...")

        self.download_thread = DownloadThread(command)
        self.download_thread.progress.connect(
            self.update_progress
        )

        self.download_thread.finished.connect(
            self.after_download
        )

        self.download_thread.error.connect(
            self.download_failed
        )
        
        self.download_thread.start()

    def update_progress(self, percent):
        self.set_status(f"Downloading... {percent}%")
        self.download_button.setText(f"Downloading... {percent}%")

    def download_failed(self, error):
        logger.error(f"Download error: {error}")
        self.set_status(f"Download Failed: {error}", "red")
        self.download_button.setEnabled(True)
        self.download_button.setText("Download")
        
        if self.download_thread:
            self.download_thread.wait()
            self.download_thread = None

    def after_download(self, output):
        logger.info("Download completed successfully")
        self.set_status("Tagging music...", "purple") # Purple for tagging phase

        filepath = find_downloaded_file(output)

        if not filepath:
             logger.warning("yt-dlp did not provide a valid file path in output.")
             self._finalize_download(None, is_error=True, error_msg="Could not determine downloaded file path")
             return

        from pathlib import Path as PPath
        p_path = PPath(filepath)
        if not p_path.exists() or p_path.stat().st_size == 0:
            logger.warning(f"Downloaded file not found or empty: {filepath}")
            self._finalize_download(None, is_error=True, error_msg="Downloaded file missing or empty")
            return
        
        api_key = self.config.get("acoustid_api_key", DEFAULT_ACoustID_KEY)
        self.tagger_thread = MusicTaggerThread(filepath, api_key=api_key)
        
        # Connect tagging signals
        # We pass the current item text to show what is being tagged in status
        current_item_text = self.result_list.currentItem().text() if self.result_list.currentItem() else "Unknown"
        
        self.tagger_thread.finished.connect(
            lambda success: self._finalize_download(success, is_error=False, item_name=current_item_text)
        )
        self.tagger_thread.error.connect(
            lambda error: self._finalize_download(error, is_error=True, error_msg=str(error))
        )
        
        self.tagger_thread.start()

    def _finalize_download(self, output=None, is_error=False, error_msg=None, item_name="Unknown"):
        """Common cleanup and post-processing logic for download/tagging completion."""
        
        if is_error:
            msg = f"Tagging Failed: {error_msg}"
            logger.warning(f"Tagging failed for {item_name}: {output}")
            self.set_status(msg, "red")
        else:
            msg = f"Success: {item_name} tagged"
            logger.info(f"Music tagged successfully: {item_name}")
            self.set_status(msg, "#007A33") # Green
        
        # M3U Rebuild
        if self.config.get("create_m3u", True):
            try:
                self.m3u_thread = M3URebuildThread(self.download_path)
                self.m3u_thread.finished.connect(
                    lambda path: logger.info(f"M3U playlist rebuilt at: {path}")
                )
                self.m3u_thread.error.connect(
                    lambda err: logger.error(f"Failed to rebuild M3U: {err}")
                )
                self.m3u_thread.start()
            except Exception as e:
                logger.error(f"Failed to start M3U rebuild thread: {e}")
        
        # Reset UI
        self.download_button.setEnabled(True)
        self.download_button.setText("Download")

    def set_status(self, message, color="#007A33"):
        """Helper to update status bar with color."""
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"font-weight: bold; color: {color};")

    def closeEvent(self, event):
        logger.info("Application closing...")
        
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.stop()
            
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.stop()
            self.download_thread.wait()
            
        if self.player_thread and hasattr(self.player_thread, "_proc"):
            try:
                self.player_thread._proc.terminate()
                self.player_thread._proc.wait(timeout=3)
            except Exception:
                pass
            
        if self.tagger_thread and self.tagger_thread.isRunning():
            self.tagger_thread.wait()

        if self.m3u_thread and self.m3u_thread.isRunning():
            self.m3u_thread.wait()
                        
        logger.info("Threads stopped. Exiting.")
        event.accept()

def get_version():
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "1.2.0"

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName("Yt Music Downloader")
    app.setDesktopFileName("music-downloader")
    app.setApplicationDisplayName("Music Downloader")
    app.setApplicationVersion(get_version())
    
    # Set application icon if available
    icon_path = "resources/icon.png"
    if Path(icon_path).exists():
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())