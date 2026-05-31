"""Solid white panel for printable postplot sheet areas."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QVBoxLayout

from xpostmaps.ui.theme import BG_PRINT, BORDER_PRINT


class PrintPanel(QFrame):
    """White background panel for map companion content (PDF-ready)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("printPanel")
        self.setAutoFillBackground(True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(8)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._layout

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(BG_PRINT))
        painter.setPen(QPen(QColor(BORDER_PRINT), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        super().paintEvent(event)
