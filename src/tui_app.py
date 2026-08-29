import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Tuple

# Import core logic
# Note: Adjust import path if running from outside the src directory
try:
    from .core import search_music, download_audio, tag_file
except ImportError:
    # Fallback for direct execution
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core import search_music, download_audio, tag_file

from logging_config import configure_logging

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Input, Label, Static, DataTable, Button
from textual.binding import Binding
from textual.message import Message

logger = logging.getLogger(__name__)

class MusicSearchApp(App):
    """Main Application Class for the Music Downloader TUI."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("enter", "search", "Search"),
        Binding("d", "download_selected", "Download Selected"),
        Binding("p", "play_selected", "Play Selected"),
        Binding("c", "clear_results", "Clear Results"),
    ]

    CSS = """
    Screen {
        background: #1a1b26;
        color: #a9b1d6;
    }

    #search-container {
        height: 3;
        width: 100%;
        padding: 1;
        background: #24283b;
        border: solid #7aa2f7;
        margin-bottom: 1;
    }

    #search-input {
        width: 1fr;
        margin-right: 1;
    }

    #search-button {
        width: 10;
        background: #7aa2f7;
        color: #1a1b26;
        text-align: center;
        content-align: center middle;
    }

    #results-table {
        height: 1fr;
        width: 100%;
        border: solid #414868;
    }

    #status-bar {
        height: 3;
        width: 100%;
        padding: 1;
        background: #24283b;
        border: solid #7aa2f7;
        margin-top: 1;
    }

    DataTable {
        color: #9ece6a;
        background: #1f2335;
        width: 100%;
        height: 100%;
    }

    DataTable > .data-table--header {
        background: #1f2335;
        color: #7aa2f7;
    }

    DataTable > .data-table--cell {
        color: #9ece6a;
    }

    DataTable > .data-table--cell--selected {
        background: #414868;
        color: #c0caf5;
    }
    
    Label {
        text-align: center;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        
        with Container(id="search-container"):
            yield Input(placeholder="Type to search music (e.g., 'coldplay')", id="search-input")
            yield Button("Search", id="search-button")
            
        yield DataTable(id="results-table")
        
        with Container(id="status-bar"):
            yield Label("Ready. Press Enter to search, D to download, P to play, Q to quit.", id="status-label")
            
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the DataTable columns."""
        self.table = self.query_one("#results-table", DataTable)
        self.table.add_columns("Platform", "Title", "Uploader", "URL")
        self.table.cursor_type = "row"
        self.table.zebra_stripes = True

    def on_button_pressed(self) -> None:
        """Handle search button click."""
        self.action_search()

    def action_search(self) -> None:
        """Trigger a search based on input."""
        query = self.query_one("#search-input", Input).value.strip()
        if not query:
            self.update_status("Please enter a search term.")
            return

        self.update_status(f"Searching for '{query}'...")
        
        # Run search in a task to avoid blocking the UI
        self.run_task(self._perform_search, query)

    async def _perform_search(self, query: str) -> None:
        """Perform the actual search logic."""
        try:
            # Clear previous results
            self.table.clear()
            
            # Get results from core.py
            # Note: This runs in a thread/task, so it won't freeze the UI
            results = await asyncio.to_thread(search_music, query=query, limit=50)
            
            if not results:
                self.update_status("No results found.")
                return

            # Add results to the table
            for title, uploader, url, platform in results:
                self.table.add_row(platform, title, uploader, url)
                
            self.update_status(f"Found {len(results)} results. Use arrow keys to select.")
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            self.update_status(f"Error: {str(e)}")

    def action_download_selected(self) -> None:
        """Download the selected row."""
        try:
            row_count = self.table.row_count
            if row_count == 0:
                self.update_status("No results to download.")
                return
            
            cursor_row, _ = self.table.cursor_coordinate
            if cursor_row >= row_count:
                self.update_status("Invalid selection.")
                return

            # Get data from the selected row
            platform, title, uploader, url = self.table.get_row_at(cursor_row)
            
            self.update_status(f"Downloading: {title}...")
            
            # Run download in a task
            asyncio.create_task(self._perform_download(url))
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            self.update_status(f"Error: {str(e)}")

    async def _perform_download(self, url: str) -> None:
        """Perform the download logic."""
        try:
            output_dir = Path("./downloads")
            file_path = await asyncio.to_thread(download_audio, url=url, output_dir=output_dir)
            
            if file_path:
                self.update_status(f"Downloaded: {file_path.name}")
            else:
                self.update_status("Download failed.")
        except Exception as e:
            logger.error(f"Download task error: {e}")
            self.update_status(f"Download error: {str(e)}")

    def action_play_selected(self) -> None:
        """Play the selected URL (placeholder)."""
        try:
            row_count = self.table.row_count
            if row_count == 0:
                self.update_status("No results to play.")
                return
            
            cursor_row, _ = self.table.cursor_coordinate
            if cursor_row >= row_count:
                self.update_status("Invalid selection.")
                return

            platform, title, uploader, url = self.table.get_row_at(cursor_row)
            
            # In a real app, you might open the URL in a browser or player
            self.update_status(f"Opening {url} in default player...")
            import webbrowser
            webbrowser.open(url)
            
        except Exception as e:
            logger.error(f"Play error: {e}")
            self.update_status(f"Error: {str(e)}")

    def action_clear_results(self) -> None:
        """Clear the results table."""
        self.table.clear()
        self.update_status("Results cleared.")

    def update_status(self, message: str) -> None:
        """Update the status bar label."""
        status_label = self.query_one("#status-label", Label)
        status_label.update(message)


if __name__ == "__main__":
    # Run the TUI application
    configure_logging()
    app = MusicSearchApp()
    app.run()