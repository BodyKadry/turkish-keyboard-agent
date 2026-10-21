from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from logging import Logger
from typing import Optional

import requests

from config import AppConfig, load_config
from logger import setup_logger


MAX_PROMPT_EXAMPLES = 20
MAX_DICTIONARY_HINTS = 120


def _format_examples(examples: list | None) -> str:
    if not examples:
        return "No recent examples."

    lines: list[str] = []
    for index, example in enumerate(examples[:MAX_PROMPT_EXAMPLES], start=1):
        if not isinstance(example, dict):
            continue

        input_text = example.get("input")
        output_text = example.get("output")
        if not isinstance(input_text, str) or not isinstance(output_text, str):
            continue

        lines.append(
            f"Example {index} Input:\n{input_text}\n"
            f"Example {index} Output:\n{output_text}"
        )

    return "\n\n".join(lines) if lines else "No recent examples."


def _format_dictionary(custom_dictionary: dict | None) -> str:
    if not custom_dictionary:
        return "No custom dictionary entries."

    lines: list[str] = []
    for wrong, correct in list(custom_dictionary.items())[:MAX_DICTIONARY_HINTS]:
        if isinstance(wrong, str) and isinstance(correct, str) and wrong and correct:
            lines.append(f"- {wrong} -> {correct}")

    return "\n".join(lines) if lines else "No custom dictionary entries."


def build_ollama_prompt(
    text: str,
    examples: list | None = None,
    custom_dictionary: dict | None = None,
) -> str:
    recent_examples = _format_examples(examples)
    dictionary_hints = _format_dictionary(custom_dictionary)

    return f"""Role:
You are a professional Turkish writing correction engine.

Task:
Correct the selected Turkish text.

Correction scope:
- Restore missing Turkish characters: ç, ğ, ü, ş, ö, ı, İ.
- Correct spelling mistakes.
- Correct simple grammar/writing mistakes.
- Fix obvious typos.
- Improve Turkish orthography only when the intended meaning is clear.

Strict output rules:
- Return only the corrected text.
- Do not explain.
- Do not add comments.
- Do not use Markdown.
- Do not wrap the answer in quotes.
- Do not add "Output:".
- Do not translate.
- Do not add new information.
- Do not remove information.
- Do not change meaning.
- Do not change names, URLs, emails, code, numbers, technical terms, IDs, paths, or commands.
- Preserve line breaks.
- Preserve spacing as much as possible.
- Preserve punctuation as much as possible.
- Preserve tone and formality level.
- If the text is already correct, return it unchanged.

Examples:
Input:
dunku yemek cok guzeldi
Output:
dünkü yemek çok güzeldi

Input:
Bugun universiteye gidecegim ve hocayla gorusecegim
Output:
Bugün üniversiteye gideceğim ve hocayla görüşeceğim

Input:
ben yarin okula gidicem
Output:
ben yarın okula gideceğim

Input:
size bekliyorum
Output:
sizi bekliyorum

Input:
bu konu hakinda bilgi alabilirmiyim
Output:
bu konu hakkında bilgi alabilir miyim

But be careful:
- Do not overcorrect casual messages too aggressively.
- Keep informal style informal.
- Only fix grammar when it is clearly wrong.
- Treat custom dictionary entries as hints, not permission to rewrite unrelated text.
- Treat recent examples as style guidance for similar corrections only.

Recent correction examples:
{recent_examples}

Custom dictionary hints:
{dictionary_hints}

Text to correct starts after BEGIN_TEXT and ends before END_TEXT.
BEGIN_TEXT
{text}
END_TEXT"""


def correct_text_with_ollama(
    text: str,
    examples: list | None = None,
    custom_dictionary: dict | None = None,
    *,
    config: Optional[AppConfig] = None,
    log: Optional[Logger] = None,
) -> str:
    """Return Ollama API corrected text, or the input text on failure."""
    app_config = config or load_config()
    logger = log or setup_logger()
    correct_text_with_ollama.last_error = False

    ollama_api_key = getattr(app_config, "ollama_api_key", "")

    if not ollama_api_key:
        correct_text_with_ollama.last_error = True
        logger.error("OLLAMA_API_KEY is not set.")
        return text

    prompt = build_ollama_prompt(text, examples, custom_dictionary)

    ollama_base_url = getattr(
        app_config,
        "ollama_base_url",
        "https://ollama.com/api",
    ).rstrip("/")

    ollama_model = getattr(
        app_config,
        "ollama_model",
        "gpt-oss:120b",
    )

    ollama_timeout = getattr(
        app_config,
        "ollama_timeout_seconds",
        60,
    )

    def _request() -> str:
        response = requests.post(
            f"{ollama_base_url}/generate",
            headers={
                "Authorization": f"Bearer {ollama_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "top_p": 0.1,
                    "num_predict": 8192,
                },
            },
            timeout=ollama_timeout,
        )

        response.raise_for_status()

        data = response.json()
        response_text = data.get("response")

        if not isinstance(response_text, str) or not response_text.strip():
            raise ValueError("Ollama returned an empty response")

        return response_text.strip()

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_request)

    try:
        return future.result(timeout=ollama_timeout)
    except FutureTimeoutError:
        future.cancel()
        correct_text_with_ollama.last_error = True
        logger.error("Ollama API error: request timed out after %s seconds", ollama_timeout)
        return text
    except requests.exceptions.HTTPError as exc:
        correct_text_with_ollama.last_error = True
        response_body = exc.response.text if exc.response is not None else ""
        if response_body:
            logger.error("Ollama API error: %s - %s", exc, response_body)
        else:
            logger.error("Ollama API error: %s", exc)
        return text
    except requests.exceptions.RequestException as exc:
        correct_text_with_ollama.last_error = True
        logger.error("Ollama API error: %s", exc)
        return text
    except Exception as exc:
        correct_text_with_ollama.last_error = True
        logger.error("Ollama API error: %s", exc)
        return text
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


correct_text_with_ollama.last_error = False
