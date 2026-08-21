# src/main.py
import sys
import subprocess
import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QLabel, QWidget, QVBoxLayout, 
    QLineEdit, QPushButton, QListWidget, 
    QListWidgetItem, QFileDialog, QHBoxLayout,
    QDialog, QComboBox, QSpinBox
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
from utils import *
from threads import (
    SearchThread,
    DownloadThread,
    VideoPlayer,
    MusicTaggerThread,
)
from constants import *


# Logging setup
log_dir = Path.home() / ".local" / "share" / "music-downloader"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ],
    force=True,
)

logger = logging.getLogger(__name__)

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.config = load_config()

        self.setWindowTitle("Ayarlar")
        self.setWindowIcon(QIcon("resources/icon.png"))
        self.resize(480, 350)

        layout = QVBoxLayout(self)

        # Player
        layout.addWidget(QLabel("Oynatıcı"))
        self.player = QComboBox()
        self.player.addItems(["mpv", "vlc", "celluloid", "clementine"])
        self.player.setCurrentText(self.config["player"])
        layout.addWidget(self.player)

        # Download path
        layout.addWidget(QLabel("Varsayılan indirme klasörü"))
        path_layout = QHBoxLayout()
        self.path = QLineEdit(self.config["download_path"])
        self.path.setReadOnly(True)
        browse = QPushButton("...")
        path_layout.addWidget(self.path)
        path_layout.addWidget(browse)
        layout.addLayout(path_layout)
        browse.clicked.connect(self.select_folder)

        # Search limit
        layout.addWidget(QLabel("Arama sonucu"))
        self.limit = QSpinBox()
        self.limit.setRange(5, 200)
        self.limit.setSingleStep(5)
        self.limit.setValue(self.config["search_limit"])
        layout.addWidget(self.limit)

        # M3U creation
        from PySide6.QtWidgets import QCheckBox
        self.create_m3u = QCheckBox("İndirdikten sonra M3U playlist oluştur")
        self.create_m3u.setChecked(self.config.get("create_m3u", True))
        layout.addWidget(self.create_m3u)

        # AcoustID API Key
        layout.addWidget(QLabel("AcoustID API Key (ücretsiz: acoustid.org/api-key)"))
        self.api_key = QLineEdit(self.config.get("acoustid_api_key", "v8pQ6oyB"))
        self.api_key.setPlaceholderText("Kendi API key'inizi alın (opsiyonel)")
        layout.addWidget(self.api_key)

        # Save button
        save = QPushButton("Kaydet")
        save.clicked.connect(self.save)
        layout.addWidget(save)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Varsayılan klasör"
        )

        if folder:
            self.path.setText(folder)

    def save(self):
        self.config["player"] = self.player.currentText()
        self.config["download_path"] = self.path.text()
        self.config["search_limit"] = self.limit.value()
        self.config["create_m3u"] = self.create_m3u.isChecked()
        self.config["acoustid_api_key"] = self.api_key.text().strip()

        save_config(self.config)

        self.accept()

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.config = load_config()
        self.download_path = self.config["download_path"]

        self.setWindowTitle(WINDOW_TITLE)
        self.setGeometry(100, 100, 550, 500)

        layout = QVBoxLayout()

        search_layout = QHBoxLayout()

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Ara")
        self.search_bar.returnPressed.connect(self.search_videos)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedWidth(36)
        self.settings_button.clicked.connect(self.open_settings)

        self.stop_button = QPushButton("X")
        self.stop_button.setFixedWidth(32)
        self.stop_button.clicked.connect(self.stop_search)
        self.stop_button.setEnabled(False)

        search_layout.addWidget(self.search_bar)
        search_layout.addWidget(self.settings_button)
        search_layout.addWidget(self.stop_button)

        layout.addLayout(search_layout)

        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self.play_video)
        layout.addWidget(self.result_list)

        button_layout = QHBoxLayout()

        self.play_button = QPushButton("Oynat")
        self.play_button.clicked.connect(self.play_selected)

        self.download_button = QPushButton("İndir")
        self.download_button.clicked.connect(self.download_selected)

        button_layout.addWidget(self.play_button)
        button_layout.addWidget(self.download_button)

        layout.addLayout(button_layout)

        self.folder_button = QPushButton("Klasör Seç")
        self.folder_button.clicked.connect(self.select_folder)
        layout.addWidget(self.folder_button)

        footer_layout = QHBoxLayout()

        self.path_label = QLabel("Varsayılan Klasör")
        self.path_label.setWordWrap(True)

        self.status_label = QLabel("")

        footer_layout.addWidget(self.path_label)
        footer_layout.addWidget(self.status_label)

        layout.addLayout(footer_layout)

        self.player_thread = None

        self.setLayout(layout)

    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.config = load_config()
            self.download_path = self.config["download_path"]
            self.path_label.setText(self.download_path)

    def search_videos(self):
        self.status_label.setText("Aranıyor...")
        self.stop_button.setEnabled(True)
        if hasattr(self, "search_thread") and self.search_thread.isRunning():
            return
        self.result_list.clear()
        query = self.search_bar.text().strip()

        if not query:
            return

        self.search_thread = SearchThread(query, self.config["search_limit"])
        self.search_thread.result.connect(self.add_result)
        self.search_thread.finished.connect(self.search_finished)
        self.search_thread.error.connect(self.search_failed)
        self.search_thread.start()

    def add_result(self, title, uploader, url):
        try:
            item = QListWidgetItem(f"{title} - {uploader}")
            item.setData(Qt.UserRole, url)
            self.result_list.addItem(item)

        except Exception as e:
            logger.error(f"Arama sonucu eklenirken hata: {e}")

    def search_finished(self):
        self.status_label.setText("Arama Bitti")
        self.stop_button.setEnabled(False)

    def stop_search(self):
        if hasattr(self, "search_thread"):
            self.search_thread.stop()

    def search_failed(self, error):
        self.status_label.setText("Arama Başarısız")
        logger.error(f"Arama hatası: {error}")

    def play_video(self, item):
        if self.player_thread and self.player_thread.isRunning():
            return

        url = item.data(Qt.UserRole)

        if not url:
            return

        self.play_button.setEnabled(False)

        self.player_thread = VideoPlayer(
            self.config["player"],
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
            "İndirme klasörü seç"
        )

        if folder:
            self.download_path = folder

            self.config["download_path"] = folder
            save_config(self.config)
            self.path_label.setText(folder)
            logger.info(f"İndirme klasörü değiştirildi: {folder}")

    def download_selected(self):
        if hasattr(self, "download_thread") and self.download_thread.isRunning():
            return
        item = self.result_list.currentItem()

        if not item:
            return

        url = item.data(Qt.UserRole)

        if not url:
            return

        logger.info(f"İndirme başlatılıyor: {url}")

        command = [
            "yt-dlp",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--embed-thumbnail",
            "--embed-metadata",
        ]

        self.download_button.setText("İndiriliyor... %0")

        if self.download_path:
            command += [
                "-o",
                f"{self.download_path}/%(title)s.%(ext)s"
            ]

        command.append(url)

        self.download_button.setEnabled(False)

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
        self.download_button.setText(f"İndiriliyor... %{percent}")

    def download_failed(self, error):
        logger.error(f"İndirme hatası: {error}")
        self.download_button.setEnabled(True)
        self.download_button.setText("İndir")

    def after_download(self, output):
        logger.info("İndirme başarıyla tamamlandı")

        filepath = find_downloaded_file(output)

        if filepath:
            logger.info(f"Etiketleme başlatılıyor: {filepath}")
            self.status_label.setText("Müzik etiketleniyor...")

            # MusicTagger ile etiketleme (config'den API key)
            api_key = self.config.get("acoustid_api_key", "v8pQ6oyB")
            self.tagger_thread = MusicTaggerThread(filepath, api_key=api_key)
            self.tagger_thread.finished.connect(
                lambda output: self.tagging_finished(output)
            )
            self.tagger_thread.error.connect(
                lambda error: self.tagging_failed(error)
            )
            self.tagger_thread.start()        
        
        else:
            logger.error("İndirilen dosya yolu bulunamadı")
            self.status_label.setText("Dosya bulunamadı")
            if self.config.get("create_m3u", True):
                rebuild_m3u(self.download_path)
                logger.info("Playlist yenilendi")
            self.download_button.setEnabled(True)
            self.download_button.setText("İndir")

    def tagging_finished(self, output):
        logger.info("✓ Müzik başarıyla etiketlendi")
        self.status_label.setText("Etiketleme tamamlandı")
        
        if self.config.get("create_m3u", True):
            rebuild_m3u(self.download_path)
            logger.info("Playlist güncellendi")
        
        self.download_button.setEnabled(True)
        self.download_button.setText("İndir")

    def tagging_failed(self, error):
        logger.warning(f"Etiketleme başarısız: {error}")
        self.status_label.setText("Etiketleme başarısız")
        
        if self.config.get("create_m3u", True):
            rebuild_m3u(self.download_path)
            logger.info("Playlist güncellendi")
        
        self.download_button.setEnabled(True)
        self.download_button.setText("İndir")

    def closeEvent(self, event):
        if hasattr(self, "download_thread") and self.download_thread.isRunning():
            self.download_thread.terminate()
        if hasattr(self, "search_thread") and self.search_thread.isRunning():
            self.search_thread.stop()
        if hasattr(self, "player_thread") and self.player_thread.isRunning():
            self.player_thread.terminate()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName("Yt Music Downloader")
    app.setDesktopFileName("music-downloader")
    app.setApplicationDisplayName("Music Downloader")
    app.setApplicationVersion("1.1.0-musicbrainz")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())