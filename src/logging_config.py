# src/logging_config.py
import logging
import sys
from pathlib import Path

# Define the directory for log files
# Using ~/.local/share/music-downloader/ for cross-platform compatibility

LOG_DIR = Path.home() / ".local" / "share" / "music-downloader"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


class CleanFormatter(logging.Formatter):
    """
    Console log formatter with color output support.
    """
    COLORS = {
        'DEBUG': '\033[90m',    # Gray
        'INFO': '\033[92m',     # Green
        'WARNING': '\033[93m',  # Yellow
        'ERROR': '\033[91m',    # Red
        'CRITICAL': '\033[95m'  # Magenta
    }
    RESET = '\033[0m'

    def __init__(self, fmt="[%(levelname)s] %(message)s", datefmt=None):
        super().__init__(fmt, datefmt)

    def format(self, record):
        # Save original attributes to restore them after formatting
        orig_levelname = record.levelname
        orig_msg = record.msg
        
        # Colorize the message if output is a TTY
        if sys.stdout.isatty() and record.levelname in self.COLORS:
            color = self.COLORS[record.levelname]
            record.msg = f"{color}{record.msg}{self.RESET}"
            
        formatted_record = super().format(record)
        
        # Restore original attributes
        record.levelname = orig_levelname
        record.msg = orig_msg
        
        return formatted_record


def configure_logging(debug: bool = False, level: int = None) -> logging.Logger:
    """
    Configure the root logger with file and console handlers.
    If debug is True, logger level is set to DEBUG, else INFO.
    If level is explicitly provided, it overrides debug.
    """
    logger = logging.getLogger()
    
    # Calculate desired logging level
    if level is not None:
        log_level = level
    else:
        log_level = logging.DEBUG if debug else logging.INFO
        
    logger.setLevel(logging.DEBUG)  # Keep root at DEBUG so handlers can filter

    # Remove any existing handlers
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(CleanFormatter())
    logger.addHandler(console_handler)

    # File Handler
    try:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        file_formatter = logging.Formatter(LOG_FORMAT, datefmt=DATEFMT)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not create log file {LOG_FILE}: {e}", file=sys.stderr)

    logger.propagate = False
    return logger