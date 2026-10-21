from __future__ import annotations

import logging
import sys
from pathlib import Path


LOGGER_NAME = "turkish_keyboard_agent"
BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "app.log"


def setup_logger(debug: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)

    if logger.handlers:
        logger.setLevel(logging.DEBUG if debug else logging.INFO)
        return logger

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(handler)
    logger.addHandler(file_handler)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    return logger


def get_logs_dir() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def get_log_file() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_FILE


def clear_log_file() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")
