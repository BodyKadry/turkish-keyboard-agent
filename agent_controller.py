from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import Optional

from clipboard_manager import ClipboardManager
from config import AppConfig, load_config
from corrector import TextCorrector
from hotkey_listener import HotkeyListener
from learning_store import LearningStore
from logger import setup_logger
from ollama_client import correct_text_with_ollama


StatusCallback = Callable[[str], None]
LoadingCallback = Callable[[bool, str], None]


@dataclass(frozen=True)
class CorrectionResult:
    text: str
    failed: bool = False


class AgentController:
    def __init__(
        self,
        config: Optional[AppConfig] = None,
        log: Optional[Logger] = None,
        status_callback: Optional[StatusCallback] = None,
        loading_callback: Optional[LoadingCallback] = None,
    ) -> None:
        self.config = config or load_config()
        self.log = log or setup_logger()
        self.status_callback = status_callback
        self.loading_callback = loading_callback
        self.clipboard_manager: ClipboardManager | None = None
        self.learning_store: LearningStore | None = None
        self.corrector: TextCorrector | None = None
        self.listener: HotkeyListener | None = None
        self._running = False
        self.last_correction_failed = False

    def start(self) -> None:
        if self._running:
            self.log.info("Agent is already running")
            self._emit_status("running")
            return

        self.log.info("Turkish Keyboard Correction Agent starting")
        self.log.info("Hotkey: %s", self.config.hotkey)
        self.log.info("Provider: Ollama API")
        self.log.info("Ollama base URL: %s", self.config.ollama_base_url)
        self.log.info("Model: %s", self.config.ollama_model)
        self.log.info("Select text anywhere, then press %s to correct it.", self.config.hotkey)

        if not self.config.ollama_api_key:
            self.log.warning(
                "OLLAMA_API_KEY is not set. Corrections will be skipped until it is configured."
            )

        self.clipboard_manager = ClipboardManager(self.config, self.log)
        self.learning_store = LearningStore(self.config, self.log)
        dictionary_count = len(self.learning_store.load_custom_dictionary())
        examples_count = len(
            self.learning_store.load_recent_examples(self.config.recent_examples_limit)
        )
        self.log.info("Custom dictionary loaded: %s entries", dictionary_count)
        self.log.info("Recent correction examples available: %s", examples_count)

        self.corrector = TextCorrector(self.config, self.learning_store, self.log)
        self.listener = HotkeyListener(
            self.config,
            self.clipboard_manager,
            self.corrector,
            self.log,
            status_callback=self._emit_status,
            loading_callback=self._emit_loading,
        )
        self.listener.start()
        self._running = True
        self._emit_status("running")
        self.log.info("Agent is running")

    def stop(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            self.listener = None

        self._running = False
        self._emit_status("stopped")
        self.log.info("Agent stopped")

    def is_running(self) -> bool:
        return self._running

    def reload_config(self, config: Optional[AppConfig] = None) -> None:
        was_running = self.is_running()
        if was_running:
            self.stop()

        self.config = config or load_config()
        self.clipboard_manager = None
        self.learning_store = None
        self.corrector = None

        if was_running:
            self.start()

    def correct_text(self, text: str) -> str:
        return self.correct_text_result(text).text

    def correct_text_result(self, text: str) -> CorrectionResult:
        self.last_correction_failed = False
        learning_store = self.learning_store or LearningStore(self.config, self.log)
        corrector = TextCorrector(self.config, learning_store, self.log)
        corrected = corrector.correct(text)
        self.last_correction_failed = bool(getattr(correct_text_with_ollama, "last_error", False))
        return CorrectionResult(corrected, self.last_correction_failed)

    def _emit_status(self, status: str) -> None:
        if not self.status_callback:
            return

        try:
            self.status_callback(status)
        except Exception as exc:
            self.log.warning("Status callback failed: %s", exc)

    def _emit_loading(self, visible: bool, message: str) -> None:
        if not self.loading_callback:
            return

        try:
            self.loading_callback(visible, message)
        except Exception as exc:
            self.log.warning("Loading callback failed: %s", exc)
