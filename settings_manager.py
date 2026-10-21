from __future__ import annotations

from pathlib import Path
from typing import Mapping

from config import BASE_DIR


MANAGED_ENV_KEYS = (
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "OLLAMA_TIMEOUT_SECONDS",
    "HOTKEY",
    "COPY_DELAY",
    "PASTE_DELAY",
    "SHOW_LOADING_OVERLAY",
)


class SettingsManager:
    def __init__(self, env_path: Path | None = None) -> None:
        self.env_path = env_path or BASE_DIR / ".env"

    def read_values(self) -> dict[str, str]:
        if not self.env_path.exists():
            return {}

        values: dict[str, str] = {}
        for line in self.env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()

        return values

    def update_values(self, updates: Mapping[str, str]) -> None:
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        existing_lines = (
            self.env_path.read_text(encoding="utf-8").splitlines()
            if self.env_path.exists()
            else []
        )

        remaining_updates = {key: str(value) for key, value in updates.items()}
        output_lines: list[str] = []

        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                output_lines.append(line)
                continue

            key, _value = stripped.split("=", 1)
            key = key.strip()
            if key in remaining_updates:
                output_lines.append(f"{key}={remaining_updates.pop(key)}")
            else:
                output_lines.append(line)

        if remaining_updates:
            if output_lines and output_lines[-1].strip():
                output_lines.append("")

            for key in MANAGED_ENV_KEYS:
                if key in remaining_updates:
                    output_lines.append(f"{key}={remaining_updates.pop(key)}")

            for key, value in remaining_updates.items():
                output_lines.append(f"{key}={value}")

        self.env_path.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")


def mask_api_key(api_key: str | None) -> str:
    if not api_key:
        return "(not set)"

    value = api_key.strip()
    if len(value) <= 8:
        return "****"

    return f"{value[:3]}****{value[-4:]}"
