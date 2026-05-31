"""Scale bar widget matching postplot card layout."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from xpostmaps.ui.theme import BG_PRINT, TEXT_PRINT, TEXT_PRIMARY


class ScaleBarWidget(QWidget):
    def __init__(self, km: float = 40.0, print_theme: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._km = km
        self._print_theme = print_theme
        self.setFixedHeight(36)

    def set_km(self, km: float) -> None:
        self._km = max(km, 1.0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        margin = 8
        bar_y = 22
        bar_h = 8
        bar_w = w - 2 * margin
        x0 = margin

        ink = QColor(TEXT_PRINT if self._print_theme else TEXT_PRIMARY)
        alt = QColor(BG_PRINT if self._print_theme else "#1a2332")

        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        painter.setPen(QPen(ink))

        mid_km = self._km / 2
        for label, frac in (("0", 0.0), (f"{mid_km:.0f}", 0.5), (f"{self._km:.0f} km", 1.0)):
            x = x0 + bar_w * frac
            tw = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(int(x - tw / 2), 14, label)

        segments = 4
        seg_w = bar_w / segments
        for i in range(segments):
            fill = ink if i % 2 == 0 else alt
            painter.fillRect(int(x0 + i * seg_w), bar_y, int(seg_w + 1), bar_h, fill)
        painter.setPen(QPen(ink, 1))
        painter.drawRect(int(x0), bar_y, int(bar_w), bar_h)
        painter.end()
