"""Central file logging configuration for the application."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILENAME = "app.log"


def setup_logging(log_dir: Optional[Path] = None) -> Path:
    """Write UTF-8 application logs with bounded disk usage."""
    directory = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / LOG_FILENAME

    root_logger = logging.getLogger()
    already_configured = any(
        getattr(handler, "_jp_srt_file_handler", False)
        for handler in root_logger.handlers
    )
    if not already_configured:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler._jp_srt_file_handler = True
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)
    return log_path

