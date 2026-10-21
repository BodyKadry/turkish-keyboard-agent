from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import Any, Optional

from config import AppConfig, load_config
from logger import setup_logger


WORD_BOUNDARY = r"[A-Za-z0-9_ÇĞİÖŞÜçğıöşü]"
MAX_STORED_EXAMPLES = 1000


def _preserve_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()

    if len(source) > 1 and source[0].isupper() and source[1:].islower():
        return replacement[:1].upper() + replacement[1:]

    return replacement


class LearningStore:
    def __init__(
        self,
        config: Optional[AppConfig] = None,
        log: Optional[Logger] = None,
    ) -> None:
        self.config = config or load_config()
        self.log = log or setup_logger()
        self._lock = threading.Lock()
        self._ensure_data_files()

    def _ensure_data_files(self) -> None:
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_json_file(self.config.corrections_file, [])
        self._ensure_json_file(self.config.custom_dictionary_file, {})

    def _ensure_json_file(self, path: Path, default_value: Any) -> None:
        if path.exists():
            return

        path.write_text(
            json.dumps(default_value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_json(self, path: Path, default_value: Any) -> Any:
        try:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                return default_value
            return json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            self.log.warning("Could not read learning data file %s: %s", path.name, exc)
            return default_value

    def _write_json(self, path: Path, value: Any) -> None:
        try:
            path.write_text(
                json.dumps(value, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self.log.error("Could not write learning data file %s: %s", path.name, exc)

    def load_recent_examples(self, limit: int = 20) -> list[dict[str, str]]:
        with self._lock:
            raw_examples = self._read_json(self.config.corrections_file, [])

        if not isinstance(raw_examples, list):
            return []

        examples: list[dict[str, str]] = []
        for item in raw_examples:
            if not isinstance(item, dict):
                continue

            input_text = item.get("input")
            output_text = item.get("output")
            if isinstance(input_text, str) and isinstance(output_text, str):
                examples.append({"input": input_text, "output": output_text})

        return examples[-max(limit, 0) :]

    def add_correction_example(self, input_text: str, output_text: str) -> None:
        if not self.config.save_correction_examples:
            return

        if not input_text or not output_text or input_text == output_text:
            return

        max_chars = self.config.max_saved_example_chars
        if len(input_text) > max_chars or len(output_text) > max_chars:
            return

        with self._lock:
            examples = self._read_json(self.config.corrections_file, [])
            if not isinstance(examples, list):
                examples = []

            duplicate = any(
                isinstance(item, dict)
                and item.get("input") == input_text
                and item.get("output") == output_text
                for item in examples
            )
            if duplicate:
                return

            examples.append(
                {
                    "input": input_text,
                    "output": output_text,
                    "created_at": datetime.now().replace(microsecond=0).isoformat(),
                }
            )

            if len(examples) > MAX_STORED_EXAMPLES:
                examples = examples[-MAX_STORED_EXAMPLES:]

            self._write_json(self.config.corrections_file, examples)

        self.log.info("Correction example saved")

    def load_custom_dictionary(self) -> dict[str, str]:
        with self._lock:
            raw_dictionary = self._read_json(self.config.custom_dictionary_file, {})

        if not isinstance(raw_dictionary, dict):
            return {}

        dictionary: dict[str, str] = {}
        for wrong, correct in raw_dictionary.items():
            if isinstance(wrong, str) and isinstance(correct, str) and wrong and correct:
                dictionary[wrong] = correct

        return dictionary

    def add_custom_dictionary_entry(self, wrong: str, correct: str) -> None:
        wrong = wrong.strip()
        correct = correct.strip()

        if not wrong or not correct:
            return

        with self._lock:
            dictionary = self._read_json(self.config.custom_dictionary_file, {})
            if not isinstance(dictionary, dict):
                dictionary = {}

            dictionary[wrong] = correct
            self._write_json(
                self.config.custom_dictionary_file,
                dict(sorted(dictionary.items(), key=lambda item: item[0].casefold())),
            )

        self.log.info("Custom dictionary entry saved")

    def apply_custom_dictionary_first(self, text: str) -> str:
        dictionary = self.load_custom_dictionary()
        if not dictionary:
            return text

        keys = sorted(dictionary.keys(), key=len, reverse=True)
        lookup = {key.casefold(): value for key, value in dictionary.items()}
        pattern = re.compile(
            rf"(?<!{WORD_BOUNDARY})({'|'.join(re.escape(key) for key in keys)})(?!{WORD_BOUNDARY})",
            flags=re.IGNORECASE,
        )

        def replace(match: re.Match[str]) -> str:
            matched_text = match.group(0)
            replacement = lookup.get(matched_text.casefold(), matched_text)
            return _preserve_case(matched_text, replacement)

        return pattern.sub(replace, text)


_default_store: LearningStore | None = None
_default_store_lock = threading.Lock()


def get_default_store() -> LearningStore:
    global _default_store

    with _default_store_lock:
        if _default_store is None:
            _default_store = LearningStore()
        return _default_store


def load_recent_examples(limit: int = 20) -> list[dict[str, str]]:
    return get_default_store().load_recent_examples(limit)


def add_correction_example(input_text: str, output_text: str) -> None:
    get_default_store().add_correction_example(input_text, output_text)


def load_custom_dictionary() -> dict[str, str]:
    return get_default_store().load_custom_dictionary()


def add_custom_dictionary_entry(wrong: str, correct: str) -> None:
    get_default_store().add_custom_dictionary_entry(wrong, correct)


def apply_custom_dictionary_first(text: str) -> str:
    return get_default_store().apply_custom_dictionary_first(text)
