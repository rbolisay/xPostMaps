"""Scale bar widget at true map scale (postplot card layout)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from xpostmaps.core.map_grid_interval import SCALE_BAR_SEGMENTS
from xpostmaps.ui.theme import BG_PRINT, TEXT_PRINT, TEXT_PRIMARY

_MARGIN = 8


class ScaleBarWidget(QWidget):
    def __init__(self, km: float = 40.0, print_theme: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._km = km
        self._bar_width_px = 0.0
        self._print_theme = print_theme
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_km(self, km: float) -> None:
        self._km = max(float(km), 0.001)
        self._bar_width_px = 0.0
        self.update()

    def set_map_scale(self, total_km: float, bar_width_px: float) -> None:
        """Set labels and drawn width so the bar matches map scale on screen."""
        self._km = max(float(total_km), 0.001)
        self._bar_width_px = max(float(bar_width_px), 1.0)
        self.update()

    def km(self) -> float:
        return self._km

    def max_bar_width_px(self) -> float:
        return max(float(self.width()) - 2 * _MARGIN, 40.0)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        margin = _MARGIN
        bar_y = 22
        bar_h = 8
        available = max(w - 2 * margin, 1)
        bar_w = self._bar_width_px if self._bar_width_px > 0 else available
        bar_w = min(bar_w, available)
        x0 = (w - bar_w) / 2.0

        ink = QColor(TEXT_PRINT if self._print_theme else TEXT_PRIMARY)
        alt = QColor(BG_PRINT if self._print_theme else "#1a2332")

        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        painter.setPen(QPen(ink))

        mid_km = self._km / 2
        for label, frac in (
            ("0", 0.0),
            (self._distance_label(mid_km), 0.5),
            (self._distance_label(self._km), 1.0),
        ):
            x = x0 + bar_w * frac
            tw = painter.fontMetrics().horizontalAdvance(label)
            label_x = max(margin, min(x - tw / 2, w - margin - tw))
            painter.drawText(int(label_x), 14, label)

        segments = SCALE_BAR_SEGMENTS
        seg_w = bar_w / segments
        for i in range(segments):
            fill = ink if i % 2 == 0 else alt
            painter.fillRect(int(x0 + i * seg_w), bar_y, int(seg_w + 1), bar_h, fill)
        painter.setPen(QPen(ink, 1))
        painter.drawRect(int(x0), bar_y, int(bar_w), bar_h)
        painter.end()

    @staticmethod
    def _distance_label(km: float) -> str:
        if km >= 1:
            if km >= 10:
                return f"{km:.0f} km"
            text = f"{km:.1f}".rstrip("0").rstrip(".")
            return f"{text} km"
        meters = km * 1000
        if meters >= 10:
            return f"{meters:.0f} m"
        text = f"{meters:.1f}".rstrip("0").rstrip(".")
        return f"{text} m"
