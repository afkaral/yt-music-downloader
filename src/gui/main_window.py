#!/usr/bin/env python3
"""
GUI module for Music Downloader
"""

import os
import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QLabel, QWidget, QVBoxLayout, 
    QLineEdit, QPushButton, QListWidget, 
    QListWidgetItem, QFileDialog, QHBoxLayout,
    QDialog, QComboBox, QSpinBox, QCheckBox,
    QTabWidget, QMessageBox,
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt

try:
    from ..utils import load_config, save_config, find_downloaded_file, get_library_path
    from .player_widget import AudioPlayerWidget
    from .workers import (
        SearchThread,
        DownloadThread,
        MusicTaggerThread,
        M3URebuildThread,
        OrganizeThread,
    )
except ImportError:
    from utils import load_config, save_config, find_downloaded_file, get_library_path
    from gui.player_widget import AudioPlayerWidget
    from gui.workers import (
        SearchThread,
        DownloadThread,
        MusicTaggerThread,
        M3URebuildThread,
        OrganizeThread,
    )

logger = logging.getLogger(__name__)

DEFAULT_ACOUSTID_KEY = "v8pQ6oyB"

def get_app_icon() -> QIcon:
    """
    Resolve application icon from system theme or fallback local assets directory.
    """
    # 1. Try system icon theme (installed desktop packages)
    icon = QIcon.fromTheme("music-downloader")
    if not icon.isNull():
        return icon

    # 2. Try project relative path
    root_dir = Path(__file__).resolve().parents[2]
    local_icon_path = root_dir / "assets" / "music-downloader.png"
    if local_icon_path.exists():
        return QIcon(str(local_icon_path))

    # 3. Try standard system install location
    system_icon_path = Path("/usr/share/icons/hicolor/256x256/apps/music-downloader.png")
    if system_icon_path.exists():
        return QIcon(str(system_icon_path))

    return QIcon()

class SettingsDialog(QDialog):
    """Settings dialog for application configuration"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = load_config()
        self._checkboxes = {}
        self.setWindowTitle("Settings")
        self.resize(520, 480)
        self._setup_ui()

    def _setup_ui(self):
        """Setup settings dialog UI"""
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_download_tab(), "Download")
        tabs.addTab(self._build_tagging_tab(), "Tagging")
        tabs.addTab(self._build_library_tab(), "Library")
        layout.addWidget(tabs)

        save = QPushButton("Save")
        save.clicked.connect(self.save)
        layout.addWidget(save)

    def _add_checkbox(self, layout, label, key, default=True):
        """Add a checkbox bound to a boolean config key"""
        box = QCheckBox(label)
        box.setChecked(self.config.get(key, default))
        layout.addWidget(box)
        self._checkboxes[key] = box

    def _build_download_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("Search platform"))
        self.platform_selector = QComboBox()
        self.platform_selector.addItems(["YouTube", "SoundCloud"])
        saved_platform = self.config.get("search_platform", "YouTube")
        idx = self.platform_selector.findText(saved_platform)
        if idx >= 0:
            self.platform_selector.setCurrentIndex(idx)
        layout.addWidget(self.platform_selector)

        layout.addWidget(QLabel("Default download folder"))
        path_layout = QHBoxLayout()
        self.path = QLineEdit(self.config.get("download_path", str(Path.home() / "Music")))
        self.path.setReadOnly(True)
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._browse_into(self.path, "Select default folder"))
        path_layout.addWidget(self.path)
        path_layout.addWidget(browse)
        layout.addLayout(path_layout)

        layout.addWidget(QLabel("Search results limit"))
        self.limit = QSpinBox()
        self.limit.setRange(5, 200)
        self.limit.setSingleStep(5)
        self.limit.setValue(self.config.get("search_limit", 50))
        layout.addWidget(self.limit)

        self._add_checkbox(layout, "Generate M3U playlist after download", "create_m3u")

        layout.addStretch()
        return tab

    def _build_tagging_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("Metadata sources"))
        self._add_checkbox(layout, "AcoustID fingerprint lookup", "tag_use_acoustid")
        self._add_checkbox(layout, "MusicBrainz text search (when no fingerprint match)", "tag_use_musicbrainz_search")
        self._add_checkbox(layout, "Genius fallback (needs API token)", "tag_use_genius")

        layout.addWidget(QLabel("Cover art sources"))
        self._add_checkbox(layout, "Cover Art Archive", "cover_use_caa")
        self._add_checkbox(layout, "iTunes", "cover_use_itunes")
        self._add_checkbox(layout, "Genius", "cover_use_genius")

        layout.addWidget(QLabel("AcoustID API Key (free: acoustid.org/api-key)"))
        self.api_key = QLineEdit(self.config.get("acoustid_api_key", DEFAULT_ACOUSTID_KEY))
        self.api_key.setPlaceholderText("Get your own API key (optional)")
        layout.addWidget(self.api_key)

        layout.addWidget(QLabel("Genius API Token (free: genius.com/api-clients)"))
        self.genius_token = QLineEdit(self.config.get("genius_token", ""))
        self.genius_token.setPlaceholderText("Optional: for better metadata fallback")
        self.genius_token.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.genius_token)

        layout.addStretch()
        return tab

    def _build_library_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("Library folder (empty = use the download folder)"))
        lib_layout = QHBoxLayout()
        self.library_path = QLineEdit(self.config.get("library_path", ""))
        self.library_path.setPlaceholderText("Same as download folder")
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._browse_into(self.library_path, "Select library folder"))
        lib_layout.addWidget(self.library_path)
        lib_layout.addWidget(browse)
        layout.addLayout(lib_layout)

        self._add_checkbox(
            layout,
            "After successful tagging, move the file to Artist/Album/NN - Title",
            "organize_after_tag",
            default=False,
        )

        layout.addStretch()
        return tab

    def _browse_into(self, line_edit, title):
        """Open folder selection dialog and write the result into a line edit"""
        folder = QFileDialog.getExistingDirectory(self, title)
        if folder:
            line_edit.setText(folder)

    def save(self):
        """Save settings and close dialog"""
        self.config["download_path"] = self.path.text().rstrip('/')
        self.config["library_path"] = self.library_path.text().strip().rstrip('/')
        self.config["search_limit"] = self.limit.value()
        self.config["acoustid_api_key"] = self.api_key.text().strip()
        self.config["genius_token"] = self.genius_token.text().strip()
        self.config["search_platform"] = self.platform_selector.currentText()
        for key, box in self._checkboxes.items():
            self.config[key] = box.isChecked()
        
        save_config(self.config)
        self.accept()

class MainWindow(QWidget):
    """Main application window"""
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
        self.m3u_thread_auto = None
        self.organize_thread = None
        
        self._setup_ui()

    def _setup_ui(self):
        """Setup main window UI"""
        self.setWindowTitle(self.config.get("window_title", "Yt Music Downloader"))
        self.setGeometry(100, 100, 650, 600)
        self.setWindowIcon(QIcon(get_app_icon()))
        
        layout = QVBoxLayout(self)

        # Search bar
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

        # Results list
        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self.play_video)
        self.result_list.currentItemChanged.connect(self.on_item_selection_changed)
        layout.addWidget(self.result_list)

        # Action buttons - Row 1
        button_layout1 = QHBoxLayout()
        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.play_selected)
        self.play_button.setEnabled(False)
        
        self.download_button = QPushButton("⬇ Download")
        self.download_button.clicked.connect(self.download_selected)

        button_layout1.addWidget(self.play_button)
        button_layout1.addWidget(self.download_button)
        layout.addLayout(button_layout1)
        
        # Action buttons - Row 2
        button_layout2 = QHBoxLayout()
        
        self.tag_button = QPushButton("🏷 Tag File")
        self.tag_button.clicked.connect(self.tag_file)
        self.tag_button.setToolTip("Tag a music file with metadata")
        
        self.rebuild_m3u_button = QPushButton("📝 Build M3U")
        self.rebuild_m3u_button.clicked.connect(self.rebuild_m3u_manual)
        self.rebuild_m3u_button.setToolTip("Build M3U playlist for download folder")
        
        self.organize_button = QPushButton("🗂 Organize")
        self.organize_button.clicked.connect(self.organize_library)
        self.organize_button.setToolTip("Move tagged files into Artist/Album/NN - Title in the library folder")
        
        button_layout2.addWidget(self.tag_button)
        button_layout2.addWidget(self.organize_button)
        button_layout2.addWidget(self.rebuild_m3u_button)
        layout.addLayout(button_layout2)

        # Folder selection
        folder_layout = QHBoxLayout()
        self.folder_button = QPushButton("Select Download Folder")
        self.folder_button.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.folder_button)
        layout.addLayout(folder_layout)

        # Audio preview player footer
        self.audio_player = AudioPlayerWidget()
        layout.addWidget(self.audio_player)

        # Status footer
        status_layout = QHBoxLayout()
        self.path_label = QLabel(f"Path: {self.download_path}")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("color: gray; font-size: 12px;")
        
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-weight: bold; color: #007A33;")
        
        status_layout.addWidget(self.path_label)
        status_layout.addStretch()
        status_layout.addWidget(self.status_label)
        layout.addLayout(status_layout)

    def on_item_selection_changed(self, current, previous):
        """Enable/disable play button based on selection"""
        self.play_button.setEnabled(bool(current))

    def open_settings(self):
        """Open settings dialog"""
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.config = load_config()
            self.download_path = self.config.get("download_path", str(Path.home() / "Music"))
            self.path_label.setText(f"Path: {self.download_path}")
            logger.info("Settings updated")

    def search_videos(self):
        """Start video search"""
        query = self.search_bar.text().strip()
        if not query:
            return

        self.set_status("Searching...", "blue")
        self.stop_button.setEnabled(True)

        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.stop()
            self.search_thread.wait()

        self.result_list.clear()
        limit = self.config.get("search_limit", 50)
        
        platform_name = self.config.get("search_platform", "YouTube")
        platforms = ["ytsearch"] if platform_name == "YouTube" else ["scsearch"]
        
        logger.info(f"Searching for '{query}' (limit {limit}) on {platforms}")
        
        self.search_thread = SearchThread(query, limit, platforms)
        self.search_thread.result.connect(self.add_result)
        self.search_thread.finished.connect(self.search_finished)
        self.search_thread.error.connect(self.search_failed)
        self.search_thread.start()

    def add_result(self, title, uploader, url, platform):
        """Add search result to list"""
        if not url or url in ("NA", "None", ""):
            return
        
        display = f"[{platform}] {title} - {uploader}"
        item = QListWidgetItem(display)
        item.setData(Qt.UserRole, url)
        item.setData(Qt.UserRole + 1, platform)
        self.result_list.addItem(item)

    def search_finished(self):
        """Handle search completion"""
        count = self.result_list.count()
        self.set_status(f"Search Complete: {count} results found", "#007A33")
        self.stop_button.setEnabled(False)

    def stop_search(self):
        """Stop ongoing search"""
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.stop()
            self.set_status("Search Stopped", "orange")
            logger.info("Search stopped by user")

    def search_failed(self, error):
        """Handle search error"""
        self.set_status(f"Search Failed: {error}", "red")
        logger.error(f"Search error: {error}")
        error_item = QListWidgetItem(f"Error: {error}")
        error_item.setData(Qt.UserRole, "")
        self.result_list.addItem(error_item)

    def play_video(self, item):
        """Play selected track in embedded audio preview player"""
        url = item.data(Qt.UserRole)
        if not url or url in ("NA", "None"):
            logger.warning("Invalid URL for playback")
            self.set_status("Invalid URL", "red")
            return

        self.set_status(f"Playing preview: {item.text()}", "#005A9C")
        self.audio_player.play_url(url, title=item.text())

    def play_selected(self):
        """Play currently selected item"""
        item = self.result_list.currentItem()
        if item:
            self.play_video(item)

    def tag_file(self):
        """Open file dialog and tag selected audio file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File to Tag",
            self.download_path,
            "Audio Files (*.mp3 *.flac *.m4a *.ogg *.wav);;All Files (*.*)"
        )
        
        if not file_path:
            return
        
        if self.tagger_thread and self.tagger_thread.isRunning():
            self.set_status("Tagging already in progress", "orange")
            return
        
        from pathlib import Path as PPath
        if not PPath(file_path).exists():
            self.set_status("File not found", "red")
            return
        
        logger.info(f"Manual tagging: {file_path}")
        self.set_status(f"Tagging: {PPath(file_path).name}...", "purple")
        self.tag_button.setEnabled(False)
        self.tag_button.setText("Tagging...")
        
        self.tagger_thread = MusicTaggerThread(file_path, self.config)
        self.tagger_thread.finished.connect(lambda msg: self._on_manual_tag_complete(file_path, True))
        self.tagger_thread.error.connect(lambda err: self._on_manual_tag_complete(file_path, False, err))
        self.tagger_thread.start()
    
    def _on_manual_tag_complete(self, filepath, success, error=None):
        """Handle manual tagging completion"""
        from pathlib import Path as PPath
        filename = PPath(filepath).name
        
        if success:
            self.set_status(f"✓ Tagged: {filename}", "#007A33")
            logger.info(f"Successfully tagged: {filepath}")
        else:
            self.set_status(f"✗ Tagging failed: {error}", "red")
            logger.error(f"Tagging failed for {filepath}: {error}")
        
        self.tag_button.setEnabled(True)
        self.tag_button.setText("🏷 Tag File")
    
    def organize_library(self):
        """Pick a folder and move its tagged audio files into the library layout"""
        if self.organize_thread and self.organize_thread.isRunning():
            self.set_status("Organize already in progress", "orange")
            return

        source = QFileDialog.getExistingDirectory(self, "Select folder to organize", self.download_path)
        if not source:
            return

        library = get_library_path(self.config)
        answer = QMessageBox.question(
            self,
            "Organize library",
            f"Move tagged audio files from:\n{source}\n\ninto:\n{library}\n\n"
            "Layout: Artist/Album/NN - Title\n"
            "Files with incomplete tags stay where they are."
        )
        if answer != QMessageBox.Yes:
            return

        logger.info(f"Organizing {source} -> {library}")
        self.set_status("Organizing library...", "purple")
        self.organize_button.setEnabled(False)
        self.organize_button.setText("Organizing...")

        self.organize_thread = OrganizeThread(source, library)
        self.organize_thread.finished.connect(self._on_organize_complete)
        self.organize_thread.error.connect(self._on_organize_error)
        self.organize_thread.start()

    def _on_organize_complete(self, organized, skipped):
        """Handle organize completion"""
        self.set_status(f"✓ Organized {organized} file(s), {skipped} skipped", "#007A33")
        logger.info(f"Organize finished: {organized} organized, {skipped} skipped")
        self.organize_button.setEnabled(True)
        self.organize_button.setText("🗂 Organize")

    def _on_organize_error(self, error):
        """Handle organize failure"""
        self.set_status(f"✗ Organize failed: {error}", "red")
        self.organize_button.setEnabled(True)
        self.organize_button.setText("🗂 Organize")

    def rebuild_m3u_manual(self):
        """Manually rebuild M3U playlist for download folder"""
        if self.m3u_thread and self.m3u_thread.isRunning():
            self.set_status("M3U build already in progress", "orange")
            return
        
        from pathlib import Path as PPath
        folder = PPath(self.download_path)
        
        if not folder.exists() or not folder.is_dir():
            self.set_status("Download folder not found", "red")
            return
        
        logger.info(f"Manual M3U rebuild: {folder}")
        self.set_status("Building M3U playlist...", "purple")
        self.rebuild_m3u_button.setEnabled(False)
        self.rebuild_m3u_button.setText("Building...")
        
        self.m3u_thread = M3URebuildThread(str(folder))
        self.m3u_thread.progress.connect(self._on_m3u_progress)
        self.m3u_thread.finished.connect(self._on_m3u_complete)
        self.m3u_thread.error.connect(self._on_m3u_error)
        self.m3u_thread.start()
    
    def _on_m3u_progress(self, current, total):
        """Update M3U build progress"""
        percent = int((current / total) * 100) if total > 0 else 0
        self.set_status(f"Building M3U: {current}/{total} ({percent}%)", "purple")
        self.rebuild_m3u_button.setText(f"Building... {percent}%")
    
    def _on_m3u_complete(self, playlist_path):
        """Handle M3U build completion"""
        from pathlib import Path as PPath
        filename = PPath(playlist_path).name
        self.set_status(f"✓ M3U created: {filename}", "#007A33")
        logger.info(f"M3U playlist created: {playlist_path}")
        self.rebuild_m3u_button.setEnabled(True)
        self.rebuild_m3u_button.setText("📝 Build M3U")
    
    def _on_m3u_error(self, error):
        """Handle M3U build error"""
        self.set_status(f"✗ M3U build failed: {error}", "red")
        logger.error(f"M3U build error: {error}")
        self.rebuild_m3u_button.setEnabled(True)
        self.rebuild_m3u_button.setText("📝 Build M3U")

    def select_folder(self):
        """Open folder selection dialog"""
        folder = QFileDialog.getExistingDirectory(self, "Select download folder")
        if folder:
            self.download_path = folder
            self.config["download_path"] = folder
            save_config(self.config)
            self.path_label.setText(f"Path: {folder}")
            logger.info(f"Download folder changed to: {folder}")
            self.set_status(f"Folder set to: {folder}", "#007A33")

    def download_selected(self):
        """Download selected track"""
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

        target_dir = os.path.normpath(self.download_path) if self.download_path else "."
        out_template = os.path.join(target_dir, "%(title)s.%(ext)s")

        command = [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-thumbnail",
            "--embed-metadata",
            "--no-playlist",
            "--extractor-args", "youtube:player_client=ios,android,mweb",
            "-o", out_template,
            url,
        ]

        self.download_button.setEnabled(False)
        self.download_button.setText("Downloading...")

        self.download_thread = DownloadThread(command)
        self.download_thread.progress.connect(self.update_progress)
        self.download_thread.finished.connect(self.after_download)
        self.download_thread.error.connect(self.download_failed)
        self.download_thread.start()

    def update_progress(self, percent):
        """Update download progress"""
        self.set_status(f"Downloading... {percent}%")
        self.download_button.setText(f"Downloading... {percent}%")

    def download_failed(self, error):
        """Handle download failure"""
        logger.error(f"Download error: {error}")
        self.set_status(f"Download Failed: {error}", "red")
        self.download_button.setEnabled(True)
        self.download_button.setText("Download")
        
        if self.download_thread:
            self.download_thread.wait()
            self.download_thread = None

    def after_download(self, output):
        """Handle post-download tagging"""
        logger.info("Download completed successfully")
        self.set_status("Tagging music...", "purple")

        filepath = find_downloaded_file(output)
        if not filepath:
            logger.warning("Could not determine downloaded file path")
            self._finalize_download(None, is_error=True, error_msg="Could not find downloaded file")
            return

        from pathlib import Path as PPath
        p_path = PPath(filepath)
        if not p_path.exists() or p_path.stat().st_size == 0:
            logger.warning(f"Downloaded file not found or empty: {filepath}")
            self._finalize_download(None, is_error=True, error_msg="Downloaded file missing or empty")
            return
        
        self.tagger_thread = MusicTaggerThread(filepath, self.config)
        
        current_item_text = self.result_list.currentItem().text() if self.result_list.currentItem() else "Unknown"
        
        self.tagger_thread.finished.connect(
            lambda success: self._finalize_download(success, is_error=False, item_name=current_item_text)
        )
        self.tagger_thread.error.connect(
            lambda error: self._finalize_download(error, is_error=True, error_msg=str(error))
        )
        
        self.tagger_thread.start()

    def _finalize_download(self, output=None, is_error=False, error_msg=None, item_name="Unknown"):
        """Finalize download and tagging process"""
        if is_error:
            msg = f"Tagging Failed: {error_msg}"
            logger.warning(f"Tagging failed for {item_name}: {output}")
            self.set_status(msg, "red")
        else:
            msg = f"Success: {item_name} tagged"
            logger.info(f"Music tagged successfully: {item_name}")
            self.set_status(msg, "#007A33")
        
        # Rebuild M3U playlist (automatic after download)
        if self.config.get("create_m3u", True) and not self.config.get("organize_after_tag", False):
            try:
                # Don't show progress for automatic rebuild, just log
                self.m3u_thread_auto = M3URebuildThread(self.download_path)
                self.m3u_thread_auto.finished.connect(
                    lambda path: logger.info(f"M3U playlist auto-rebuilt at: {path}")
                )
                self.m3u_thread_auto.error.connect(
                    lambda err: logger.error(f"Failed to rebuild M3U: {err}")
                )
                self.m3u_thread_auto.start()
            except Exception as e:
                logger.error(f"Failed to start M3U rebuild thread: {e}")
        
        # Reset UI
        self.download_button.setEnabled(True)
        self.download_button.setText("Download")

    def set_status(self, message, color="#007A33"):
        """Update status label with color"""
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"font-weight: bold; color: {color};")

    def closeEvent(self, event):
        """Handle application close"""
        logger.info("Application closing...")
        
        if hasattr(self, "audio_player"):
            self.audio_player.cleanup()
            
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.stop()
            self.search_thread.wait()
            
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

        if self.m3u_thread_auto and self.m3u_thread_auto.isRunning():
            self.m3u_thread_auto.wait()

        if self.organize_thread and self.organize_thread.isRunning():
            self.organize_thread.wait()
                    
        logger.info("Threads stopped. Exiting.")
        event.accept()