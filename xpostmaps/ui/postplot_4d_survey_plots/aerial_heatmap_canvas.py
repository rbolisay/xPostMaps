"""Sequence × shotpoint aerial heatmap for survey-wide 4D plots."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QImage, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from xpostmaps.core.postplot_4d_plot_data import PLOT_KIND_UNITS, PlotKind
from xpostmaps.core.postplot_4d_survey_plot_data import (
    AerialHeatmapData,
    fill_aerial_heatmap_gaps,
)
from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_navigation import (
    apply_plot_extent,
    create_survey_plot_widget,
)
from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_pdf_render import (
    draw_survey_plot_title,
    render_pyqtgraph_plot_for_pdf,
)
from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_title_edit import SurveyPlotTitleEdit

_PLOT_BG = "#ffffff"
_PLOT_FG = "#111827"
_MIN_HEIGHT = 320
_MIN_PX_PER_SEQUENCE = 4
_MIN_HEATMAP_WIDTH = 640
_LEGEND_WIDTH = 96
_LEGEND_BAR_WIDTH = 22
_LEGEND_AXIS_WIDTH = 54


def _legend_unit_label(kind: PlotKind) -> str:
    unit = PLOT_KIND_UNITS.get(kind, "")
    return {"meter": "m", "degree": "°"}.get(unit, unit)


def _configure_pyqtgraph() -> None:
    try:
        pg.setConfigOptions(antialias=True, useOpenGL=False, foreground=_PLOT_FG)
    except Exception:  # noqa: BLE001
        pg.setConfigOptions(antialias=True, useOpenGL=False)


_configure_pyqtgraph()


def _diverging_colormap() -> pg.ColorMap:
    positions = [0.0, 0.22, 0.5, 0.78, 1.0]
    colors = [
        (185, 28, 28, 255),
        (234, 179, 8, 255),
        (29, 78, 216, 255),
        (234, 179, 8, 255),
        (185, 28, 28, 255),
    ]
    return pg.ColorMap(positions, colors)


def _display_grid(grid: np.ndarray) -> np.ndarray:
    """Flip shot axis so low shot numbers are at the bottom."""
    return np.flipud(np.asarray(grid, dtype=np.float64))


def _paintable_grid(grid: np.ndarray) -> np.ndarray:
    """Fill vertical shot gaps within each packed sequence column."""
    return fill_aerial_heatmap_gaps(_display_grid(grid))


class AerialHeatmapCanvas(QWidget):
    """Heatmap: x = sequence numbers, y = shot numbers, legend = signed values."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._scroll_root = QWidget()
        scroll_layout = QVBoxLayout(self._scroll_root)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(4)

        self._title = SurveyPlotTitleEdit()
        self._title.textChanged.connect(lambda *_args: self._sync_legend_layout())
        scroll_layout.addWidget(self._title)

        self._plot, self._viewbox = create_survey_plot_widget(background=_PLOT_BG)
        self._plot.showGrid(x=False, y=False)
        self._plot.setLabel("bottom", "Sequence numbers")
        self._plot.setLabel("left", "Shot number")
        self._plot.getPlotItem().hideAxis("top")
        self._plot.getPlotItem().hideAxis("right")
        self._plot.setMenuEnabled(False)
        tick_font = QFont("Arial", 8)
        self._plot.getAxis("bottom").setStyle(tickFont=tick_font, tickTextOffset=10)
        self._plot.getAxis("left").setStyle(tickFont=tick_font)
        scroll_layout.addWidget(self._plot, stretch=1)

        self._legend_root = QWidget()
        self._legend_root.setFixedWidth(_LEGEND_WIDTH)
        legend_layout = QVBoxLayout(self._legend_root)
        legend_layout.setContentsMargins(0, 0, 2, 0)
        legend_layout.setSpacing(0)
        self._legend_spacer = QWidget()
        self._legend_spacer.setFixedHeight(0)
        legend_layout.addWidget(self._legend_spacer)
        self._legend_unit = QLabel("")
        self._legend_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._legend_unit.setStyleSheet(
            f"color: {_PLOT_FG}; font-size: 10px; font-weight: 600; padding: 0 2px;"
        )
        legend_layout.addWidget(self._legend_unit)
        self._legend_plot, _legend_viewbox = create_survey_plot_widget(background=_PLOT_BG)
        self._legend_plot.setMenuEnabled(False)
        self._legend_plot.hideAxis("bottom")
        self._legend_plot.hideAxis("left")
        self._legend_plot.getPlotItem().hideAxis("top")
        self._legend_plot.getPlotItem().hideAxis("right")
        self._legend_plot.setFixedWidth(_LEGEND_WIDTH)
        self._legend_plot.setYLink(self._plot)
        legend_layout.addWidget(self._legend_plot, stretch=1)

        self._cmap = _diverging_colormap()
        self._image = pg.ImageItem(axisOrder="row-major", autoDownsample=False)
        self._image.setColorMap(self._cmap)
        self._image.setOpacity(1.0)
        self._plot.addItem(self._image)
        legend_tick_font = QFont("Arial", 8)
        self._colorbar = pg.ColorBarItem(
            values=(-15.0, 15.0),
            colorMap=self._cmap,
            label="",
            interactive=False,
            width=_LEGEND_BAR_WIDTH,
            rounding=1,
        )
        self._colorbar.getAxis("right").setStyle(
            tickFont=legend_tick_font,
            autoExpandTextSpace=True,
            tickTextOffset=2,
        )
        self._colorbar.getAxis("right").setWidth(_LEGEND_AXIS_WIDTH)
        self._colorbar.getAxis("left").setStyle(showValues=False)
        self._colorbar.hideAxis("left")
        self._colorbar.setImageItem(self._image, insert_in=self._legend_plot.getPlotItem())

        self._data: AerialHeatmapData | None = None
        self._data_key: tuple[int, int, int, float] | None = None
        self._viewbox.sigRangeChanged.connect(lambda *_args: self._sync_legend_layout())

    def scroll_widget(self) -> QWidget:
        """Plot + title for horizontal scrolling (legend stays fixed separately)."""
        return self._scroll_root

    def legend_widget(self) -> QWidget:
        """Fixed color legend panel (always visible beside the scroll area)."""
        return self._legend_root

    def _sync_legend_layout(self) -> None:
        title_height = self._title.height() if self._title.text().strip() else 0
        if title_height <= 0:
            title_height = self._title.sizeHint().height() if self._title.text().strip() else 0
        top = title_height + (4 if title_height else 0)
        self._legend_spacer.setFixedHeight(top)
        unit_text = self._legend_unit.text().strip()
        unit_height = self._legend_unit.sizeHint().height() if unit_text else 0
        self._legend_unit.setVisible(bool(unit_text))
        plot_height = max(self._plot.height(), self._plot.sizeHint().height())
        self._legend_root.setMinimumHeight(top + unit_height + plot_height)

    def render(self, data: AerialHeatmapData | None) -> None:
        if data is None:
            self._data = None
            self._data_key = None
            self._image.clear()
            self._title.reset_default("")
            self._legend_unit.setText("")
            return

        grid = np.asarray(data.image, dtype=np.float64)
        limit = float(data.value_limit)
        cache_key = (id(data), grid.shape[0], grid.shape[1], limit)
        if cache_key == self._data_key:
            self._sync_legend_layout()
            return
        self._data = data
        self._data_key = cache_key

        n_cols = grid.shape[1]
        n_rows = grid.shape[0]
        shot_min = int(data.shot_min)
        shot_max = int(data.shot_max)

        self._title.reset_default(data.map_label)
        self._scroll_root.setMinimumWidth(max(_MIN_HEATMAP_WIDTH, n_cols * _MIN_PX_PER_SEQUENCE))

        painted = _paintable_grid(grid)
        self._image.setColorMap(self._cmap)
        self._image.setImage(painted, autoLevels=False)
        self._image.setLevels((-limit, limit))
        self._image.setRect(0, shot_min, n_cols, n_rows)
        self._colorbar.setLevels((-limit, limit))
        unit_label = _legend_unit_label(data.kind)
        self._legend_unit.setText(unit_label)

        x_ticks = _sequence_axis_ticks(data.sequence_labels)
        self._plot.getAxis("bottom").setTicks([x_ticks])
        y_ticks = _shot_axis_ticks(shot_min, shot_max)
        self._plot.getAxis("left").setTicks([y_ticks])
        apply_plot_extent(
            self._viewbox,
            (-0.5, n_cols - 0.5),
            (shot_min - 0.5, shot_max + 0.5),
        )
        self._sync_legend_layout()

    def title_text(self) -> str:
        return self._title.title_text()

    def capture_image(
        self,
        *,
        width: int,
        height: int,
        title: str = "",
        subtitle: str = "",
        for_pdf: bool = False,
        dpi: int = 120,
    ) -> QImage:
        self._sync_legend_layout()
        if not for_pdf:
            plot_image = self._plot.grab().toImage()
            legend_image = self._legend_root.grab().toImage()
            combined = QImage(
                plot_image.width() + legend_image.width(),
                max(plot_image.height(), legend_image.height()),
                QImage.Format.Format_ARGB32,
            )
            combined.fill(Qt.GlobalColor.white)
            painter = QPainter(combined)
            painter.drawImage(0, 0, plot_image)
            painter.drawImage(plot_image.width(), 0, legend_image)
            painter.end()
            return combined.scaled(
                width,
                height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        title_text = title.strip() or self._title.title_text()
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        top_pad = draw_survey_plot_title(
            painter,
            x=8,
            y=0,
            width=width,
            title=title_text,
            dpi=dpi,
        )
        painter.end()

        body_h = max(1, height - top_pad)
        plot_w = max(1, width - _LEGEND_WIDTH)
        plot_body = render_pyqtgraph_plot_for_pdf(
            self._plot,
            width=plot_w,
            height=body_h,
            dpi=dpi,
        )
        legend_body = self._legend_root.grab().toImage().scaled(
            _LEGEND_WIDTH,
            body_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        composed = QImage(width, height, QImage.Format.Format_ARGB32)
        composed.fill(Qt.GlobalColor.white)
        composer = QPainter(composed)
        composer.drawImage(0, 0, image)
        composer.drawImage(0, top_pad, plot_body)
        composer.drawImage(plot_w, top_pad, legend_body)
        composer.end()
        return composed


def _sequence_axis_ticks(labels: list[str], max_ticks: int = 24) -> list[tuple[float, str]]:
    """Packed column positions labeled with actual sequence numbers (no empty slots)."""
    if not labels:
        return []
    count = len(labels)
    if count <= max_ticks:
        return [(index + 0.5, label) for index, label in enumerate(labels)]
    step = max(1, count // max_ticks)
    ticks: list[tuple[float, str]] = []
    for index in range(0, count, step):
        ticks.append((index + 0.5, labels[index]))
    if count - 1 not in {int(position) for position, _label in ticks}:
        ticks.append((count - 0.5, labels[-1]))
    return ticks


def _shot_axis_ticks(shot_min: int, shot_max: int, max_ticks: int = 12) -> list[tuple[float, str]]:
    span = shot_max - shot_min
    if span <= 0:
        return [(float(shot_min), str(shot_min))]
    step = max(1, span // max(1, max_ticks - 1))
    step = int(round(step / 32.0)) * 32 or step
    ticks: list[tuple[float, str]] = []
    value = shot_min
    while value <= shot_max:
        ticks.append((float(value), str(value)))
        value += step
    if ticks[-1][0] != float(shot_max):
        ticks.append((float(shot_max), str(shot_max)))
    return ticks
