from __future__ import annotations

import sys

from logger import setup_logger


def main() -> int:
    log = setup_logger()

    try:
        from app_ui import run_app
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            message = (
                "PySide6 is not installed. Install dependencies with: "
                "pip install -r requirements.txt"
            )
            log.error(message)
            print(message)
            return 1
        raise

    return run_app()


if __name__ == "__main__":
    sys.exit(main())
