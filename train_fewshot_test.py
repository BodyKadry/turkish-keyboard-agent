from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


from sklearn.model_selection import train_test_split

    


load_dotenv()

API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()
BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/api").strip().rstrip("/")
MODEL_NAME = os.getenv("OLLAMA_MODEL", "gpt-oss:120b").strip()
TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))

EXAMPLES_FILE = "examples.json"
TEST_SIZE = 0.30
RANDOM_STATE = 42

MAX_TRAIN_EXAMPLES_IN_PROMPT = 140


def load_examples(path: str) -> list[dict[str, str]]:
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"Examples file not found: {path}")

    with open(file_path, "r", encoding="utf-8") as f:
        examples = json.load(f)

    clean_examples: list[dict[str, str]] = []

    if not isinstance(examples, list):
        raise ValueError("examples.json must contain a list of objects.")

    for item in examples:
        if not isinstance(item, dict):
            continue

        input_text = str(item.get("input", "")).strip()
        output_text = str(item.get("output", "")).strip()

        if input_text and output_text:
            clean_examples.append(
                {
                    "input": input_text,
                    "output": output_text,
                }
            )

    return clean_examples


def format_examples(examples: list[dict[str, str]]) -> str:
    formatted: list[str] = []

    for ex in examples:
        formatted.append(f"Input: {ex['input']}\nOutput: {ex['output']}")

    return "\n\n".join(formatted)


def build_prompt(text: str, train_examples: list[dict[str, str]]) -> str:
    examples_text = format_examples(train_examples[:MAX_TRAIN_EXAMPLES_IN_PROMPT])

    prompt = f"""
Role:
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

But be careful:
- Do not rewrite the sentence creatively.
- Do not make the text more formal unless the input is already formal.
- Do not overcorrect casual messages too aggressively.
- Keep informal style informal.
- Only fix grammar when it is clearly wrong.
- If a word can have multiple Turkish meanings, choose the most natural one based on context.

Examples:

{examples_text}

Now correct the following text.

Input:
{text}

Output:
""".strip()

    return prompt


def clean_response(response_text: str) -> str:
    if not response_text:
        return ""

    text = response_text.strip()

    # Remove common wrappers.
    text = re.sub(r"^Output\s*:\s*", "", text, flags=re.IGNORECASE).strip()

    # Remove quotes if model wraps output.
    if len(text) >= 2:
        if (text[0] == '"' and text[-1] == '"') or (
            text[0] == "'" and text[-1] == "'"
        ):
            text = text[1:-1].strip()

    return text


def call_ollama_generate(prompt: str) -> str:
    """
    Calls Ollama Cloud API, not local Ollama.

    Required .env:
        OLLAMA_API_KEY=your_key_here

    Optional .env:
        OLLAMA_BASE_URL=https://ollama.com/api
        OLLAMA_MODEL=gpt-oss:120b
        OLLAMA_TIMEOUT_SECONDS=60
    """
    if not API_KEY:
        raise ValueError("OLLAMA_API_KEY is not set.")

    if not MODEL_NAME:
        raise ValueError("OLLAMA_MODEL is missing.")

    url = f"{BASE_URL}/generate"

    payload: dict[str, Any] = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0,
            "top_p": 0.1,
            "num_predict": 8192,
        },
    }

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    data = response.json()
    response_text = data.get("response")

    if not isinstance(response_text, str):
        raise ValueError(f"Unexpected Ollama response format: {data}")

    return response_text


def correct_text(text: str, train_examples: list[dict[str, str]]) -> str:
    prompt = build_prompt(text, train_examples)

    try:
        response_text = call_ollama_generate(prompt)
        corrected = clean_response(response_text)

        if not corrected:
            return text

        return corrected

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        body = e.response.text if e.response is not None else ""
        print(f"Ollama API error: status={status_code} body={body}")
        return text
    except requests.exceptions.RequestException as e:
        print(f"Ollama API error: {e}")
        return text
    except Exception as e:
        print(f"Ollama API error: {e}")
        return text


def normalize_for_eval(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def exact_match(predicted: str, expected: str) -> bool:
    return normalize_for_eval(predicted) == normalize_for_eval(expected)


def character_accuracy(predicted: str, expected: str) -> float:
    predicted = normalize_for_eval(predicted)
    expected = normalize_for_eval(expected)

    if not expected:
        return 0.0

    max_len = max(len(predicted), len(expected))
    min_len = min(len(predicted), len(expected))

    correct_chars = 0

    for i in range(min_len):
        if predicted[i] == expected[i]:
            correct_chars += 1

    return correct_chars / max_len


def evaluate(
    test_examples: list[dict[str, str]],
    train_examples: list[dict[str, str]],
) -> None:
    total = len(test_examples)
    exact_correct = 0
    char_scores: list[float] = []

    results: list[dict[str, Any]] = []

    for index, item in enumerate(test_examples, start=1):
        input_text = item["input"]
        expected = item["output"]

        predicted = correct_text(input_text, train_examples)

        is_exact = exact_match(predicted, expected)
        char_score = character_accuracy(predicted, expected)

        if is_exact:
            exact_correct += 1

        char_scores.append(char_score)

        results.append(
            {
                "input": input_text,
                "expected": expected,
                "predicted": predicted,
                "exact_match": is_exact,
                "character_accuracy": round(char_score, 4),
            }
        )

        print("=" * 60)
        print(f"Test {index}/{total}")
        print(f"Input    : {input_text}")
        print(f"Expected : {expected}")
        print(f"Predicted: {predicted}")
        print(f"Exact    : {is_exact}")
        print(f"Char Acc : {round(char_score * 100, 2)}%")

        time.sleep(0.5)

    exact_accuracy = exact_correct / total if total else 0
    avg_char_accuracy = sum(char_scores) / total if total else 0

    report = {
        "total_examples": total,
        "exact_correct": exact_correct,
        "exact_accuracy": round(exact_accuracy, 4),
        "average_character_accuracy": round(avg_char_accuracy, 4),
        "results": results,
    }

    with open("evaluation_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "#" * 60)
    print("Evaluation Finished")
    print(f"Total Test Examples       : {total}")
    print(f"Exact Match Accuracy      : {round(exact_accuracy * 100, 2)}%")
    print(f"Character Level Accuracy  : {round(avg_char_accuracy * 100, 2)}%")
    print("Report saved to           : evaluation_report.json")
    print("#" * 60)


def main() -> None:
    if not API_KEY:
        raise ValueError("OLLAMA_API_KEY is not set.")

    
    examples = load_examples(EXAMPLES_FILE)

    if len(examples) < 10:
        raise ValueError("You need at least 10 examples. Recommended: 200 examples.")

    train_examples, test_examples = train_test_split(
        examples,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        shuffle=True,
    )

    print(f"Ollama base URL: {BASE_URL}")
    print(f"Ollama model   : {MODEL_NAME}")
    print(f"Total examples : {len(examples)}")
    print(f"Train examples : {len(train_examples)}")
    print(f"Test examples  : {len(test_examples)}")
    print(f"Test size      : {int(TEST_SIZE * 100)}%")

    evaluate(test_examples, train_examples)


if __name__ == "__main__":
    main()
