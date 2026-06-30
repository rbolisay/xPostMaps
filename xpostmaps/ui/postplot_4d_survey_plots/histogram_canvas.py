"""Cumulative histogram canvas for survey-wide 4D metrics."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QSizePolicy, QVBoxLayout, QWidget

from xpostmaps.core.postplot_4d_survey_plot_data import CumulativeHistogram
from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_navigation import (
    apply_plot_extent,
    create_survey_plot_widget,
)
from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_pdf_render import (
    apply_screen_axis_styles,
    compose_survey_plot_image,
)

_PLOT_BG = "#ffffff"
_PLOT_FG = "#111827"
_BAR_FILL = "#6ea8fe"
_BAR_BORDER = "#1e3a8a"
_MIN_HEIGHT = 240


def _configure_pyqtgraph() -> None:
    try:
        pg.setConfigOptions(antialias=True, useOpenGL=False, foreground=_PLOT_FG)
    except Exception:  # noqa: BLE001
        pg.setConfigOptions(antialias=True, useOpenGL=False)


def _display_degree_axis_ticks(
    positions: list[float],
    labels: list[str],
    *,
    max_ticks: int = 24,
) -> list[tuple[float, str]]:
    """Show a readable subset of degree labels when the span is wide."""
    if len(positions) <= max_ticks:
        return list(zip(positions, labels, strict=True))
    step = max(1, len(positions) // max_ticks)
    ticks = [(positions[index], labels[index]) for index in range(0, len(positions), step)]
    if positions[-1] != ticks[-1][0]:
        ticks.append((positions[-1], labels[-1]))
    return ticks


_configure_pyqtgraph()


class HistogramCanvas(QWidget):
    """Cumulative percentage histogram (0–15 m, >15)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._plot, self._viewbox = create_survey_plot_widget(background=_PLOT_BG)
        self._plot.showGrid(x=False, y=False)
        self._plot.setLabel("left", "%")
        self._plot.setLabel("bottom", "meter")
        self._plot.getAxis("left").setStyle(tickTextOffset=4)
        self._plot.getAxis("bottom").setStyle(tickTextOffset=4)
        layout.addWidget(self._plot, stretch=1)
        self._bars: pg.BarGraphItem | None = None
        self._title = ""
        self._histogram: CumulativeHistogram | None = None

    def set_title(self, title: str) -> None:
        self._title = title.strip()

    def render(self, histogram: CumulativeHistogram) -> None:
        self._histogram = histogram
        apply_screen_axis_styles(self._plot, bottom_tick_offset=4)
        if self._bars is not None:
            self._plot.removeItem(self._bars)
            self._bars = None

        labels = histogram.bucket_labels
        heights = histogram.cumulative_pct
        if not labels:
            self._plot.clear()
            return

        self._plot.setLabel("bottom", histogram.x_axis_unit)
        if histogram.x_positions is not None:
            x = np.asarray(histogram.x_positions, dtype=np.float64)
            step = float(x[1] - x[0]) if len(x) > 1 else 1.0
            bar_width = step * 0.85
        else:
            x = np.arange(len(labels), dtype=np.float64)
            bar_width = 0.85

        brush = pg.mkBrush(_BAR_FILL)
        pen = pg.mkPen(_BAR_BORDER, width=1)
        self._bars = pg.BarGraphItem(
            x=x,
            height=heights,
            width=bar_width,
            brush=brush,
            pen=pen,
        )
        self._plot.addItem(self._bars)
        axis = self._plot.getAxis("bottom")
        if histogram.x_positions is not None:
            tick_pairs = list(
                zip(histogram.x_positions, labels, strict=True),
            )
            if histogram.x_axis_unit == "degrees":
                tick_pairs = _display_degree_axis_ticks(
                    [float(position) for position in histogram.x_positions],
                    labels,
                )
            axis.setTicks([[ (position, label) for position, label in tick_pairs ]])
            half = bar_width * 0.5
            x_range = (float(x[0]) - half, float(x[-1]) + half)
        else:
            axis.setTicks([[(index, label) for index, label in enumerate(labels)]])
            x_range = (-0.5, len(labels) - 0.5)
        apply_plot_extent(self._viewbox, x_range, (0.0, 100.0))

    def capture_image(
        self,
        *,
        width: int,
        height: int,
        title: str = "",
        for_pdf: bool = False,
        dpi: int = 120,
    ) -> QImage:
        if not for_pdf:
            plot_image = self._plot.grab().toImage()
            return plot_image.scaled(
                width,
                height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        width = max(int(width), 1)
        height = max(int(height), 1)
        old_size = self._plot.size()
        try:
            self._plot.resize(width, height)
            if self._histogram is not None:
                self.render(self._histogram)
            QApplication.processEvents()
            return compose_survey_plot_image(
                self._plot,
                width=width,
                height=height,
                dpi=dpi,
                include_title=False,
            )
        finally:
            self._plot.resize(old_size)
            if self._histogram is not None:
                self.render(self._histogram)
            apply_screen_axis_styles(self._plot, bottom_tick_offset=4)
            QApplication.processEvents()
