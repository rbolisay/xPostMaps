"""Non-modal single-instance popup base."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout

from xpostmaps.ui.glass_widget import GlassPanel
from xpostmaps.ui.theme import app_stylesheet


class SingleInstanceDialog(QDialog):
    """Non-modal dialog that reuses one window instance."""

    _instances: dict[str, SingleInstanceDialog] = {}

    def __init__(self, key: str, title: str, parent=None, width: int = 420, height: int = 520) -> None:
        super().__init__(parent)
        self._key = key
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setModal(False)
        self.resize(width, height)
        self.setStyleSheet(app_stylesheet())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        self._glass = GlassPanel(self)
        outer.addWidget(self._glass)

        SingleInstanceDialog._instances[key] = self
        self.finished.connect(self._on_finished)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._glass.content_layout

    def _on_finished(self) -> None:
        if SingleInstanceDialog._instances.get(self._key) is self:
            del SingleInstanceDialog._instances[self._key]

    @classmethod
    def show_dialog(
        cls,
        key: str,
        title: str,
        builder,
        parent=None,
        width: int = 420,
        height: int = 520,
    ) -> SingleInstanceDialog:
        existing = cls._instances.get(key)
        if existing is not None:
            builder(existing)
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing

        dialog = cls(key, title, parent, width, height)
        builder(dialog)
        dialog.show()
        return dialog

    def closeEvent(self, event) -> None:  # noqa: N802
        self._on_finished()
        super().closeEvent(event)
