"""Preplot × shotpoint aerial heatmap for survey-wide 4D plots."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QImage, QPainter
from PySide6.QtWidgets import QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from PySide6.QtWidgets import QApplication

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
    apply_screen_axis_styles,
    render_pyqtgraph_plot_for_pdf,
)
from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_title_edit import SurveyPlotTitleEdit

_PLOT_BG = "#ffffff"
_PLOT_FG = "#111827"
_MIN_HEIGHT = 320
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
        (34, 197, 94, 255),
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


def _legend_pdf_metrics(dpi: int) -> tuple[int, int, int, QFont, int]:
    scale = max(dpi / 96.0, 1.0)
    width = max(136, int(round(152 * scale)))
    bar_width = max(26, int(round(32 * scale)))
    axis_width = max(72, int(round(92 * scale)))
    tick_font = QFont("Arial")
    tick_font.setPixelSize(max(8, int(round(10 * scale))))
    unit_px = max(10, int(round(11 * scale)))
    return width, bar_width, axis_width, tick_font, unit_px


class AerialHeatmapCanvas(QWidget):
    """Heatmap: x = sequence numbers, y = shot numbers, legend = signed values."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._scroll_root = QWidget()
        self._scroll_root.setMinimumWidth(0)
        scroll_layout = QVBoxLayout(self._scroll_root)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(4)

        self._title = SurveyPlotTitleEdit()
        self._title.textChanged.connect(lambda *_args: self._sync_legend_layout())
        scroll_layout.addWidget(self._title)

        self._plot, self._viewbox = create_survey_plot_widget(background=_PLOT_BG)
        self._plot.showGrid(x=False, y=False)
        self._plot.setLabel("bottom", "Preplot number")
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
        self._scroll: QScrollArea | None = None
        self._viewbox.set_after_reset(self._on_reset_extent)
        self._viewbox.sigRangeChanged.connect(lambda *_args: self._sync_legend_layout())

    def set_scroll_area(self, scroll: QScrollArea) -> None:
        self._scroll = scroll

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

    def _on_reset_extent(self) -> None:
        if self._scroll is None:
            return
        self._scroll.horizontalScrollBar().setValue(0)
        self._scroll.verticalScrollBar().setValue(0)
        self._sync_legend_layout()

    def _apply_full_extent(self, *, reset_view: bool) -> None:
        if self._data is None:
            return
        grid = np.asarray(self._data.image, dtype=np.float64)
        n_cols = grid.shape[1]
        shot_min = int(self._data.shot_min)
        shot_max = int(self._data.shot_max)
        apply_plot_extent(
            self._viewbox,
            (-0.5, n_cols - 0.5),
            (shot_min - 0.5, shot_max + 0.5),
            reset_view=reset_view,
        )

    def render(self, data: AerialHeatmapData | None, *, force: bool = False) -> None:
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
        if cache_key == self._data_key and not force:
            self._sync_legend_layout()
            return
        self._data = data
        self._data_key = cache_key

        apply_screen_axis_styles(self._plot, bottom_tick_offset=10)

        n_cols = grid.shape[1]
        n_rows = grid.shape[0]
        shot_min = int(data.shot_min)
        shot_max = int(data.shot_max)

        self._title.reset_default(data.map_label)

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
        self._apply_full_extent(reset_view=True)
        self._sync_legend_layout()

    def _apply_legend_pdf_layout(self, dpi: int) -> tuple[int, int, int, QFont, int]:
        legend_w, bar_w, axis_w, tick_font, unit_px = _legend_pdf_metrics(dpi)
        self._legend_root.setFixedWidth(legend_w)
        self._legend_plot.setFixedWidth(legend_w)
        self._colorbar.layout.setColumnFixedWidth(1, bar_w)
        right_axis = self._colorbar.getAxis("right")
        right_axis.setWidth(axis_w)
        right_axis.setStyle(
            tickFont=tick_font,
            autoExpandTextSpace=True,
            tickTextOffset=max(4, int(round(5 * max(dpi / 96.0, 1.0)))),
        )
        self._sync_legend_layout()
        QApplication.processEvents()
        return legend_w, bar_w, axis_w, tick_font, unit_px

    def _restore_legend_ui_layout(self) -> None:
        self._legend_root.setFixedWidth(_LEGEND_WIDTH)
        self._legend_plot.setFixedWidth(_LEGEND_WIDTH)
        self._colorbar.layout.setColumnFixedWidth(1, _LEGEND_BAR_WIDTH)
        self._colorbar.getAxis("right").setWidth(_LEGEND_AXIS_WIDTH)
        legend_tick_font = QFont("Arial", 8)
        self._colorbar.getAxis("right").setStyle(
            tickFont=legend_tick_font,
            autoExpandTextSpace=True,
            tickTextOffset=2,
        )
        self._sync_legend_layout()
        QApplication.processEvents()

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

        body_h = max(1, height)
        old_plot_size = self._plot.size()
        old_legend_plot_size = self._legend_plot.size()
        self._legend_plot.setYLink(None)
        self._apply_full_extent(reset_view=True)
        self._viewbox.zoom_to_extent()
        QApplication.processEvents()
        legend_w, _bar_w, _axis_w, _tick_font, unit_px = self._apply_legend_pdf_layout(dpi)
        plot_w = max(1, width - legend_w)
        try:
            self._plot.resize(plot_w, body_h)
            self._legend_plot.resize(legend_w, body_h)
            self._apply_full_extent(reset_view=True)
            self._viewbox.zoom_to_extent()
            QApplication.processEvents()
            plot_body = render_pyqtgraph_plot_for_pdf(
                self._plot,
                width=plot_w,
                height=body_h,
                dpi=dpi,
            )
            legend_body = render_pyqtgraph_plot_for_pdf(
                self._legend_plot,
                width=legend_w,
                height=body_h,
                dpi=dpi,
            )
        finally:
            self._plot.resize(old_plot_size)
            self._legend_plot.resize(old_legend_plot_size)
            self._legend_plot.setYLink(self._plot)
            self._restore_legend_ui_layout()
            apply_screen_axis_styles(self._plot, bottom_tick_offset=10)
            apply_screen_axis_styles(self._legend_plot, bottom_tick_offset=4)
            self._apply_full_extent(reset_view=True)

        composed = QImage(width, height, QImage.Format.Format_ARGB32)
        composed.fill(Qt.GlobalColor.white)
        composer = QPainter(composed)
        composer.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        composer.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        composer.drawImage(0, 0, plot_body)
        composer.drawImage(plot_w, 0, legend_body)
        unit_text = self._legend_unit.text().strip()
        if unit_text:
            unit_font = QFont("Arial")
            unit_font.setPixelSize(unit_px)
            unit_font.setWeight(QFont.Weight.DemiBold)
            composer.setFont(unit_font)
            composer.setPen(Qt.GlobalColor.black)
            metrics = composer.fontMetrics()
            unit_y = max(4, int(round(6 * max(dpi / 96.0, 1.0))))
            composer.drawText(
                plot_w,
                unit_y + metrics.ascent(),
                legend_w,
                metrics.height(),
                int(Qt.AlignmentFlag.AlignHCenter),
                unit_text,
            )
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
