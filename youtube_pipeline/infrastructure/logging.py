from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..config import ConfigurationError

LOGGER_NAME = "youtube_pipeline"
MODEL_CALL_LOGGER_NAME = "youtube_pipeline.model_calls"


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError("%s phải là số nguyên." % name) from exc
    if value < 1:
        raise ConfigurationError("%s phải lớn hơn hoặc bằng 1." % name)
    return value


def configure_logging() -> Path:
    log_path = Path(
        os.getenv("YOUTUBE_PIPELINE_LOG_FILE", "runtime/runtime/logs/youtube_pipeline.log")
    ).expanduser()
    level_name = os.getenv("YOUTUBE_PIPELINE_LOG_LEVEL", "DEBUG").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise ConfigurationError(
            "YOUTUBE_PIPELINE_LOG_LEVEL không hợp lệ: %s" % level_name
        )

    max_bytes = _positive_int("YOUTUBE_PIPELINE_LOG_MAX_BYTES", 10 * 1024 * 1024)
    backup_count = _positive_int("YOUTUBE_PIPELINE_LOG_BACKUP_COUNT", 5)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    except OSError as exc:
        raise ConfigurationError("Không tạo được file log %s: %s" % (log_path, exc)) from exc

    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger = logging.getLogger(LOGGER_NAME)
    for old_handler in root_logger.handlers:
        old_handler.close()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
    root_logger.propagate = False
    return log_path


def configure_model_call_logging() -> Path:
    log_path = Path(
        os.getenv("YOUTUBE_MODEL_CALL_LOG_FILE", "runtime/runtime/logs/model_pipeline_calls.log")
    ).expanduser()
    max_bytes = _positive_int("YOUTUBE_MODEL_CALL_LOG_MAX_BYTES", 10 * 1024 * 1024)
    backup_count = _positive_int("YOUTUBE_MODEL_CALL_LOG_BACKUP_COUNT", 5)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    except OSError as exc:
        raise ConfigurationError(
            "Không tạo được file model call log %s: %s" % (log_path, exc)
        ) from exc

    handler.setFormatter(
        logging.Formatter("%(asctime)s\n%(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    call_logger = logging.getLogger(MODEL_CALL_LOGGER_NAME)
    for old_handler in call_logger.handlers:
        old_handler.close()
    call_logger.handlers.clear()
    call_logger.addHandler(handler)
    call_logger.setLevel(logging.INFO)
    call_logger.propagate = False
    return log_path
