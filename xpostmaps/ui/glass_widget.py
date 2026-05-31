"""Frosted glass panel widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QVBoxLayout

from xpostmaps.ui.theme import GLASS_BG, GLASS_BORDER


class GlassPanel(QFrame):
    """Semi-transparent panel with subtle border and shadow."""

    def __init__(self, parent=None, radius: int = 14) -> None:
        super().__init__(parent)
        self._radius = radius
        self.setObjectName("glassPanel")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._layout

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor(30, 40, 56, 190))
        gradient.setColorAt(1.0, QColor(18, 26, 38, 210))

        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(GLASS_BORDER), 1))
        painter.drawRoundedRect(rect, self._radius, self._radius)
        super().paintEvent(event)
