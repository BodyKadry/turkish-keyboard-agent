from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CORRECTIONS_FILE = DATA_DIR / "corrections.json"
CUSTOM_DICTIONARY_FILE = DATA_DIR / "custom_dictionary.json"


HOTKEY = "ctrl+alt+t"
MAX_CHARS = 5000
COPY_DELAY = 0.2
PASTE_DELAY = 0.2
RESTORE_DELAY = 0.3
RESTORE_CLIPBOARD = True
SHOW_LOADING_OVERLAY = True

# Ollama API settings
# For Ollama Cloud API, use: https://ollama.com/api
# For a self-hosted Ollama-compatible server, override OLLAMA_BASE_URL in .env.
OLLAMA_BASE_URL = "https://ollama.com/api"
OLLAMA_MODEL = "gpt-oss:120b"
OLLAMA_TIMEOUT_SECONDS = 60.0

SAVE_CORRECTION_EXAMPLES = True
MAX_SAVED_EXAMPLE_CHARS = 500
RECENT_EXAMPLES_LIMIT = 20
APPLY_CUSTOM_DICTIONARY_FIRST = True
PASTE_IF_UNCHANGED = False


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    data_dir: Path
    corrections_file: Path
    custom_dictionary_file: Path
    hotkey: str
    max_chars: int
    copy_delay: float
    paste_delay: float
    restore_delay: float
    restore_clipboard: bool
    show_loading_overlay: bool
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: float
    ollama_api_key: str | None
    save_correction_examples: bool
    max_saved_example_chars: int
    recent_examples_limit: int
    apply_custom_dictionary_first: bool
    paste_if_unchanged: bool


def load_config() -> AppConfig:
    load_dotenv(BASE_DIR / ".env", override=True)

    return AppConfig(
        base_dir=BASE_DIR,
        data_dir=DATA_DIR,
        corrections_file=CORRECTIONS_FILE,
        custom_dictionary_file=CUSTOM_DICTIONARY_FILE,
        hotkey=os.getenv("HOTKEY", HOTKEY),
        max_chars=_get_int("MAX_CHARS", MAX_CHARS),
        copy_delay=_get_float("COPY_DELAY", COPY_DELAY),
        paste_delay=_get_float("PASTE_DELAY", PASTE_DELAY),
        restore_delay=_get_float("RESTORE_DELAY", RESTORE_DELAY),
        restore_clipboard=_get_bool("RESTORE_CLIPBOARD", RESTORE_CLIPBOARD),
        show_loading_overlay=_get_bool(
            "SHOW_LOADING_OVERLAY",
            _get_bool("SHOW_BUSY_CURSOR", SHOW_LOADING_OVERLAY),
        ),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL).rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", OLLAMA_MODEL),
        ollama_timeout_seconds=_get_float(
            "OLLAMA_TIMEOUT_SECONDS",
            OLLAMA_TIMEOUT_SECONDS,
        ),
        ollama_api_key=os.getenv("OLLAMA_API_KEY"),
        save_correction_examples=_get_bool(
            "SAVE_CORRECTION_EXAMPLES",
            SAVE_CORRECTION_EXAMPLES,
        ),
        max_saved_example_chars=_get_int(
            "MAX_SAVED_EXAMPLE_CHARS",
            MAX_SAVED_EXAMPLE_CHARS,
        ),
        recent_examples_limit=_get_int("RECENT_EXAMPLES_LIMIT", RECENT_EXAMPLES_LIMIT),
        apply_custom_dictionary_first=_get_bool(
            "APPLY_CUSTOM_DICTIONARY_FIRST",
            APPLY_CUSTOM_DICTIONARY_FIRST,
        ),
        paste_if_unchanged=_get_bool("PASTE_IF_UNCHANGED", PASTE_IF_UNCHANGED),
    )
