"""Application mediator – central event bus for decoupled components."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, Signal


class Mediator(QObject):
    """Singleton-style mediator for cross-component communication."""

    project_loaded = Signal(object)
    project_saved = Signal(str)
    settings_changed = Signal(object)
    map_data_updated = Signal(object)
    display_mode_changed = Signal(str)
    parse_progress = Signal(int, str)
    parse_finished = Signal(object)
    parse_error = Signal(str)
    status_message = Signal(str)

    _instance: Mediator | None = None

    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[str, list[Callable[..., Any]]] = {}

    @classmethod
    def instance(cls) -> Mediator:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def subscribe(self, event: str, handler: Callable[..., Any]) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def publish(self, event: str, *args: Any, **kwargs: Any) -> None:
        for handler in self._handlers.get(event, []):
            handler(*args, **kwargs)
