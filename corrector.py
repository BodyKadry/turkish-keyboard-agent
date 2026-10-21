from __future__ import annotations

import re
from logging import Logger
from typing import Optional

from config import AppConfig, load_config
from learning_store import LearningStore
from logger import setup_logger
from ollama_client import correct_text_with_ollama


OUTPUT_LABEL_MARKERS = (
    "output:",
    "corrected:",
    "corrected text:",
    "düzeltilmiş:",
    "düzeltilmiş metin:",
    "sonuç:",
    "result:",
)

EXPLANATION_MARKERS = (
    "explanation:",
    "açıklama:",
    "aciklama:",
    "input:",
    "note:",
    "not:",
    "reason:",
    "gerekçe:",
    "changes:",
    "değişiklikler:",
)

EXPLANATION_PHRASES = (
    "here is the corrected",
    "the corrected text is",
    "i corrected",
    "işte düzeltilmiş",
    "düzeltilmiş metin aşağıdaki",
    "metnin düzeltilmiş hali",
    "şu şekilde düzelttim",
)

PROTECTED_TOKEN_PATTERN = re.compile(
    r"""
    (?:https?://|www\.)[^\s<>"']+
    |[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}
    |\b[\w.-]+\.(?:com|net|org|edu|gov|io|co|dev|app|tr)(?:/[^\s<>"']*)?
    |\b[A-Za-z]:\\[^\s]+
    |(?:^|[\s])(?:\.{1,2}[\\/]|[A-Za-z0-9_.-]+[\\/])[^\s]+
    |(?<!\w)[+-]?\d+(?:[.,:/-]\d+)*(?!\w)
    |\b[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)+\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _first_nonempty_line(value: str) -> str:
    for line in value.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _starts_with_marker(value: str, markers: tuple[str, ...]) -> bool:
    lowered = value.casefold().lstrip()
    return any(lowered.startswith(marker.casefold()) for marker in markers)


def _strip_wrapping_quotes(value: str, original: str) -> str:
    stripped = value.strip()
    original_stripped = original.strip()
    quote_pairs = (
        ('"', '"'),
        ("'", "'"),
        ("“", "”"),
        ("‘", "’"),
    )

    for opening, closing in quote_pairs:
        if stripped.startswith(opening) and stripped.endswith(closing):
            original_is_quoted = original_stripped.startswith(opening) and original_stripped.endswith(
                closing
            )
            if not original_is_quoted:
                return stripped[1:-1]
    return value


def _strip_output_label(value: str, original: str) -> str:
    stripped_left = value.lstrip()
    leading = value[: len(value) - len(stripped_left)]
    original_first_line = _first_nonempty_line(original)

    for marker in OUTPUT_LABEL_MARKERS:
        if stripped_left.casefold().startswith(marker.casefold()):
            if _starts_with_marker(original_first_line, (marker,)):
                return value
            return leading + stripped_left[len(marker) :].lstrip()

    return value


def _leading_whitespace(value: str) -> str:
    return value[: len(value) - len(value.lstrip())]


def _trailing_whitespace(value: str) -> str:
    return value[len(value.rstrip()) :]


def _restore_outer_whitespace(original: str, corrected: str) -> str:
    original_leading = _leading_whitespace(original)
    original_trailing = _trailing_whitespace(original)

    core = corrected.strip()
    return f"{original_leading}{core}{original_trailing}"


def _restore_newline_style(original: str, corrected: str) -> str:
    if "\r\n" in original and "\r\n" not in corrected:
        return corrected.replace("\n", "\r\n")
    return corrected


def _contains_added_code_fence(original: str, corrected: str) -> bool:
    return "```" in corrected and "```" not in original


def _looks_like_explanation(value: str, original: str) -> bool:
    first_line = _first_nonempty_line(value)
    original_first_line = _first_nonempty_line(original)

    if _starts_with_marker(first_line, EXPLANATION_MARKERS) and not _starts_with_marker(
        original_first_line,
        EXPLANATION_MARKERS,
    ):
        return True

    lowered_start = value.casefold().strip()[:240]
    return any(phrase.casefold() in lowered_start for phrase in EXPLANATION_PHRASES)


def _is_extremely_longer(original: str, corrected: str) -> bool:
    original_length = len(original.strip())
    corrected_length = len(corrected.strip())

    if original_length == 0:
        return corrected_length > 0

    if original_length < 20:
        return corrected_length > 80

    return corrected_length > original_length * 3


def _removes_too_much_content(original: str, corrected: str) -> bool:
    original_core = original.strip()
    corrected_core = corrected.strip()

    if not corrected_core:
        return True

    if len(original_core) >= 30 and len(corrected_core) < len(original_core) * 0.35:
        return True

    original_lines = [line for line in original_core.splitlines() if line.strip()]
    corrected_lines = [line for line in corrected_core.splitlines() if line.strip()]
    if len(original_lines) >= 3 and len(corrected_lines) < max(1, len(original_lines) // 2):
        return True

    return False


def _normalize_protected_token(value: str) -> str:
    return value.strip().strip(".,;:!?()[]{}<>\"'").casefold()


def _extract_protected_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for match in PROTECTED_TOKEN_PATTERN.finditer(value):
        token = _normalize_protected_token(match.group(0))
        if token:
            tokens.add(token)
    return tokens


def _removes_protected_tokens(original: str, corrected: str) -> bool:
    original_tokens = _extract_protected_tokens(original)
    if not original_tokens:
        return False

    corrected_normalized = corrected.casefold()
    return any(token not in corrected_normalized for token in original_tokens)


def clean_ai_output(raw_output: str, original_text: str) -> str:
    cleaned = _strip_output_label(raw_output, original_text)
    cleaned = _strip_wrapping_quotes(cleaned, original_text)
    cleaned = _restore_outer_whitespace(original_text, cleaned)
    cleaned = _restore_newline_style(original_text, cleaned)
    return cleaned


class TextCorrector:
    def __init__(
        self,
        config: Optional[AppConfig] = None,
        learning_store: Optional[LearningStore] = None,
        log: Optional[Logger] = None,
    ) -> None:
        self.config = config or load_config()
        self.log = log or setup_logger()
        self.learning_store = learning_store or LearningStore(self.config, self.log)

    def correct(self, text: str) -> str:
        if not isinstance(text, str):
            self.log.warning("Selected content is not text")
            return ""

        if text == "":
            self.log.info("Selected text is empty")
            return text

        if text.strip() == "":
            self.log.info("Selected text contains only whitespace")
            return text

        if len(text) > self.config.max_chars:
            self.log.warning("Selected text is too long: %s chars", len(text))
            return text

        custom_dictionary = self.learning_store.load_custom_dictionary()
        self.log.info("Custom dictionary loaded: %s entries", len(custom_dictionary))

        text_for_ai = text
        if self.config.apply_custom_dictionary_first:
            text_for_ai = self.learning_store.apply_custom_dictionary_first(text)

        examples = self.learning_store.load_recent_examples(self.config.recent_examples_limit)

        raw_output = correct_text_with_ollama(
            text_for_ai,
            examples=examples,
            custom_dictionary=custom_dictionary,
            config=self.config,
            log=self.log,
        )

        if getattr(correct_text_with_ollama, "last_error", False):
            return text

        if _contains_added_code_fence(text_for_ai, raw_output):
            self.log.warning("Ollama response rejected because it included a code fence")
            return text

        cleaned = clean_ai_output(raw_output, text_for_ai)

        if cleaned.strip() == "":
            self.log.warning("Ollama returned empty corrected text")
            return text

        if _looks_like_explanation(cleaned, text_for_ai):
            self.log.warning("Ollama response rejected because it included explanation text")
            return text

        if _is_extremely_longer(text_for_ai, cleaned):
            self.log.warning("Ollama response rejected because it was too long")
            return text

        if _removes_too_much_content(text_for_ai, cleaned):
            self.log.warning("Ollama response rejected because it removed too much content")
            return text

        if _removes_protected_tokens(text_for_ai, cleaned):
            self.log.warning("Ollama response rejected because it removed protected content")
            return text

        if cleaned != text:
            self.learning_store.add_correction_example(text, cleaned)

        return cleaned
