from __future__ import annotations

from logging import Logger
from typing import Optional


class CursorManager:
    """
    Deprecated compatibility shim.

    The app no longer changes Windows system cursors. Loading feedback is handled by
    loading_overlay.LoadingOverlay.
    """

    def __init__(self, log: Optional[Logger] = None) -> None:
        self.log = log

    def set_busy(self) -> None:
        return

    def restore(self) -> None:
        return
