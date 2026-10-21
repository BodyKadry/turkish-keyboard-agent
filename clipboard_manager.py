from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from logging import Logger
from typing import Optional

import pyautogui
import pyperclip

from config import AppConfig, load_config
from logger import setup_logger


@dataclass(frozen=True)
class ClipboardSnapshot:
    text: str
    captured: bool


class ClipboardManager:
    def __init__(
        self,
        config: Optional[AppConfig] = None,
        log: Optional[Logger] = None,
    ) -> None:
        self.config = config or load_config()
        self.log = log or setup_logger()
        pyautogui.PAUSE = 0.02

    def _read_text(self) -> str:
        try:
            value = pyperclip.paste()
            return value if isinstance(value, str) else ""
        except pyperclip.PyperclipException as exc:
            self.log.error("Clipboard read failed: %s", exc)
            return ""

    def _set_text(self, value: str) -> bool:
        try:
            pyperclip.copy(value)
            return True
        except pyperclip.PyperclipException as exc:
            self.log.error("Clipboard write failed: %s", exc)
            return False

    def snapshot(self) -> ClipboardSnapshot:
        try:
            value = pyperclip.paste()
            return ClipboardSnapshot(text=value if isinstance(value, str) else "", captured=True)
        except pyperclip.PyperclipException as exc:
            self.log.error("Clipboard snapshot failed: %s", exc)
            return ClipboardSnapshot(text="", captured=False)

    def restore(self, snapshot: ClipboardSnapshot, delay: float = 0.0) -> None:
        if not self.config.restore_clipboard or not snapshot.captured:
            return

        if delay > 0:
            time.sleep(delay)

        if self._set_text(snapshot.text):
            self.log.debug("Clipboard restored")

    def capture_selected_text(self) -> tuple[Optional[str], ClipboardSnapshot]:
        snapshot = self.snapshot()
        sentinel = f"__TKCA_CLIPBOARD_SENTINEL_{uuid.uuid4()}__"

        if not self._set_text(sentinel):
            return None, snapshot

        time.sleep(0.03)
        pyautogui.hotkey("ctrl", "c")

        selected_text = self._wait_for_clipboard_change(sentinel)

        if selected_text is None or selected_text == "":
            self.log.info("No selected text found")
            self.restore(snapshot, delay=0.0)
            return None, snapshot

        self.restore(snapshot, delay=0.0)
        return selected_text, snapshot

    def replace_selected_text(self, corrected_text: str, snapshot: ClipboardSnapshot) -> bool:
        if not corrected_text:
            self.restore(snapshot, delay=0.0)
            return False

        if not self._set_text(corrected_text):
            self.restore(snapshot, delay=0.0)
            return False

        time.sleep(0.03)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(self.config.paste_delay)
        self.restore(snapshot, delay=self.config.restore_delay)
        return True

    def _wait_for_clipboard_change(self, sentinel: str) -> Optional[str]:
        deadline = time.monotonic() + max(self.config.copy_delay, 0.05)
        latest_value = sentinel

        while time.monotonic() < deadline:
            latest_value = self._read_text()
            if latest_value != sentinel:
                return latest_value
            time.sleep(0.02)

        latest_value = self._read_text()
        if latest_value == sentinel:
            return None
        return latest_value
