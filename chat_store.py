from __future__ import annotations

import json
from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import Any


MAX_CHAT_MESSAGES = 200


class ChatStore:
    def __init__(self, data_dir: Path, log: Logger | None = None) -> None:
        self.data_dir = data_dir
        self.log = log
        self.chat_file = self.data_dir / "chat_history.json"
        self._ensure_file()

    def load_messages(self) -> list[dict[str, str]]:
        try:
            content = self.chat_file.read_text(encoding="utf-8").strip()
            if not content:
                return []
            raw_messages = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            if self.log:
                self.log.warning("Could not read chat history: %s", exc)
            return []

        if not isinstance(raw_messages, list):
            return []

        messages: list[dict[str, str]] = []
        for item in raw_messages[-MAX_CHAT_MESSAGES:]:
            if not isinstance(item, dict):
                continue

            role = item.get("role")
            text = item.get("text")
            timestamp = item.get("timestamp")
            if isinstance(role, str) and isinstance(text, str):
                messages.append(
                    {
                        "role": role,
                        "text": text,
                        "timestamp": timestamp if isinstance(timestamp, str) else "",
                    }
                )

        return messages

    def add_message(self, role: str, text: str) -> None:
        if role not in {"user", "assistant", "system", "error"}:
            role = "system"

        messages = self.load_messages()
        messages.append(
            {
                "role": role,
                "text": text,
                "timestamp": datetime.now().replace(microsecond=0).isoformat(),
            }
        )
        self._write_messages(messages[-MAX_CHAT_MESSAGES:])

    def clear(self) -> None:
        self._write_messages([])

    def _ensure_file(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.chat_file.exists():
            self._write_messages([])

    def _write_messages(self, messages: list[dict[str, Any]]) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.chat_file.write_text(
                json.dumps(messages[-MAX_CHAT_MESSAGES:], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            if self.log:
                self.log.error("Could not write chat history: %s", exc)
