from __future__ import annotations

import threading
import time
from collections.abc import Callable
from logging import Logger
from typing import Optional

import keyboard

from clipboard_manager import ClipboardManager
from config import AppConfig, load_config
from corrector import TextCorrector
from logger import setup_logger


class HotkeyListener:
    def __init__(
        self,
        config: Optional[AppConfig] = None,
        clipboard_manager: Optional[ClipboardManager] = None,
        corrector: Optional[TextCorrector] = None,
        log: Optional[Logger] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        loading_callback: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        self.config = config or load_config()
        self.log = log or setup_logger()
        self.clipboard_manager = clipboard_manager or ClipboardManager(self.config, self.log)
        self.corrector = corrector or TextCorrector(config=self.config, log=self.log)
        self.status_callback = status_callback
        self.loading_callback = loading_callback
        self._job_lock = threading.Lock()
        self._hotkey_handle: object | None = None

    def start(self) -> None:
        self._hotkey_handle = keyboard.add_hotkey(
            self.config.hotkey,
            self._on_hotkey,
            suppress=False,
            trigger_on_release=False,
        )
        self.log.info("Global hotkey registered: %s", self.config.hotkey)

    def stop(self) -> None:
        if self._hotkey_handle is not None:
            keyboard.remove_hotkey(self._hotkey_handle)
            self._hotkey_handle = None
        self.log.info("Global hotkey listener stopped")

    def _on_hotkey(self) -> None:
        if not self._job_lock.acquire(blocking=False):
            self.log.info("Correction already running; hotkey press ignored")
            return

        worker = threading.Thread(target=self._run_correction_workflow, daemon=True)
        worker.start()

    def _run_correction_workflow(self) -> None:
        show_loading_overlay = self.config.show_loading_overlay
        try:
            self.log.info("Correction requested")
            self._emit_status("correcting")
            if show_loading_overlay:
                self._emit_loading(True, "Correcting...")
                self.log.info("Correction started, loading overlay shown")

            time.sleep(0.08)
            selected_text, snapshot = self.clipboard_manager.capture_selected_text()

            if not selected_text:
                return

            self.log.info("Selected text length: %s", len(selected_text))
            corrected_text = self.corrector.correct(selected_text)

            if corrected_text == "":
                self.log.info("No replacement needed")
                return

            if corrected_text == selected_text and not self.config.paste_if_unchanged:
                self.log.info("No replacement needed")
                return

            replaced = self.clipboard_manager.replace_selected_text(corrected_text, snapshot)
            if replaced:
                self.log.info("Correction completed")
            else:
                self.log.warning("Correction was not pasted")
        except Exception as exc:
            self.log.exception("Correction workflow failed: %s", exc)
        finally:
            if show_loading_overlay:
                self._emit_loading(False, "")
                self.log.info("Correction finished, loading overlay hidden")
            self._emit_status("running" if self._hotkey_handle is not None else "stopped")
            self._job_lock.release()

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
