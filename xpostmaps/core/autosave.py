"""Debounced autosave helper."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer


class AutosaveController(QObject):
    """Schedules debounced silent saves after project changes."""

    def __init__(
        self,
        save_callback: Callable[[], bool],
        parent: QObject | None = None,
        delay_ms: int = 2000,
    ) -> None:
        super().__init__(parent)
        self._save_callback = save_callback
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._run_save)
        self._enabled = True

    def schedule(self) -> None:
        if self._enabled:
            self._timer.start()

    def save_now(self) -> bool:
        self._timer.stop()
        return self._run_save()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._timer.stop()

    def _run_save(self) -> bool:
        if not self._enabled:
            return False
        return self._save_callback()
