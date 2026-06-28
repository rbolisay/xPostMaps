"""PyQtGraph time-series plot widgets for 4D Stat."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QLabel,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_plot_data import (
    BoundaryRow,
    PLOT_KIND_UNITS,
    PlotKind,
    PlotSeries,
    SourceStyleRow,
)
from xpostmaps.ui.postplot_4d_stat_plot.plot_pen import boundary_pen, source_pen
from xpostmaps.ui.postplot_4d_stat_plot.stat_plot_view_box import StatPlotViewBox
from xpostmaps.ui.postplot_4d_stat_plot.theme import STAT_PLOT_SOURCE_TAB_STYLE

_PLOT_BG = "#ffffff"
_PLOT_FG = "#111827"
_MIN_PLOT_HEIGHT = 420
_PICK_RADIUS_PX = 12
_OVERLAY_STYLE = (
    "background: rgba(255, 255, 255, 0.88);"
    "color: #111827;"
    "border: 1px solid #cbd5e1;"
    "border-radius: 3px;"
    "padding: 2px 6px;"
    "font-size: 11px;"
)


def _configure_stat_pyqtgraph() -> None:
    """Stat plots use CPU raster (no GL) so embedded tabs render reliably."""
    try:
        pg.setConfigOptions(antialias=True, useOpenGL=False, foreground=_PLOT_FG)
    except Exception:  # noqa: BLE001
        pg.setConfigOptions(antialias=True, useOpenGL=False)


_configure_stat_pyqtgraph()


def _configure_plot(plot: pg.PlotWidget, *, y_label: str) -> None:
    plot.setBackground(_PLOT_BG)
    plot.showGrid(x=False, y=False)
    plot.setLabel("bottom", "Shot Number", color=_PLOT_FG)
    plot.setLabel("left", y_label, color=_PLOT_FG)
    plot.setMinimumHeight(_MIN_PLOT_HEIGHT)
    plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    for axis_name in ("left", "bottom"):
        axis = plot.getAxis(axis_name)
        axis.setPen(pg.mkPen(_PLOT_FG))
        axis.setTextPen(pg.mkPen(_PLOT_FG))
    legend = plot.getPlotItem().legend
    if legend is not None:
        legend.setLabelTextColor(_PLOT_FG)
        legend.setBrush(pg.mkBrush(255, 255, 255, 220))
        legend.setPen(pg.mkPen("#cccccc"))


def _style_lookup(styles: list[SourceStyleRow]) -> dict[str, SourceStyleRow]:
    return {row.source_no: row for row in styles}


def _pick_tolerance(
    viewbox: pg.ViewBox,
    *,
    radius_px: float = _PICK_RADIUS_PX,
) -> tuple[float, float]:
    (x_range, y_range) = viewbox.viewRange()
    x_span = x_range[1] - x_range[0]
    y_span = y_range[1] - y_range[0]
    view_rect = viewbox.sceneBoundingRect()
    width = max(view_rect.width(), 1.0)
    height = max(view_rect.height(), 1.0)
    return x_span * radius_px / width, y_span * radius_px / height


def nearest_pick_point(
    pick_points: list[tuple[float, float, str]],
    mouse_x: float,
    mouse_y: float,
    x_tol: float,
    y_tol: float,
) -> tuple[float, float, str] | None:
    """Return the nearest data point within *radius_px* (ellipse in data space)."""
    if not pick_points or x_tol <= 0.0 or y_tol <= 0.0:
        return None
    best: tuple[float, float, str] | None = None
    best_dist = 1.0
    for shotpoint, value, source_no in pick_points:
        dx = (shotpoint - mouse_x) / x_tol
        dy = (value - mouse_y) / y_tol
        dist = dx * dx + dy * dy
        if dist < best_dist:
            best_dist = dist
            best = (shotpoint, value, source_no)
    return best


def _format_pick_value(kind: PlotKind, value: float) -> str:
    if kind in ("feather", "feather_diff"):
        return f"{value:.2f}"
    return f"{value:.3f}"


class TimeSeriesPlotWidget(pg.PlotWidget):
    """Single time-series plot with navigation, point pick, and stats overlay."""

    def __init__(self, kind: PlotKind, parent=None) -> None:
        self._viewbox = StatPlotViewBox()
        self._kind = kind
        self._curve_items: list[pg.PlotDataItem] = []
        self._boundary_items: list[pg.InfiniteLine] = []
        self._pick_points: list[tuple[float, float, str]] = []
        self._extent_x: tuple[float, float] | None = None
        self._extent_y: tuple[float, float] | None = None
        self._selection_marker = pg.ScatterPlotItem(
            size=11,
            pen=pg.mkPen("#111827", width=1.5),
            brush=pg.mkBrush(255, 255, 255, 230),
            symbol="o",
        )
        self._selection_marker.setZValue(200)
        self._selection_edit = QLineEdit()
        self._stats_label = QLabel()
        super().__init__(parent=parent, background=_PLOT_BG, viewBox=self._viewbox)
        _configure_plot(self, y_label=PLOT_KIND_UNITS[kind])
        self._selection_edit.setParent(self)
        self._stats_label.setParent(self)
        self._selection_edit.setReadOnly(True)
        self._selection_edit.setStyleSheet(_OVERLAY_STYLE)
        self._selection_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._selection_edit.hide()
        self._stats_label.setStyleSheet(_OVERLAY_STYLE)
        self.addItem(self._selection_marker)
        self._selection_marker.hide()
        self._viewbox.set_handlers(
            center_average=self._center_average,
            reset_zoom=self._reset_zoom,
        )
        scene = self.scene()
        if scene is not None:
            scene.sigMouseClicked.connect(self._on_scene_mouse_clicked)
        self._position_overlays()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_overlays()

    def _position_overlays(self) -> None:
        if not hasattr(self, "_selection_edit"):
            return
        margin = 8
        self._selection_edit.adjustSize()
        self._selection_edit.setFixedWidth(min(300, max(180, self.width() // 3)))
        self._selection_edit.move(margin, margin)
        self._selection_edit.raise_()

        self._stats_label.adjustSize()
        stats_y = self.height() - self._stats_label.height() - margin
        self._stats_label.move(margin, max(margin, stats_y))
        self._stats_label.raise_()

    def _set_selection_text(self, text: str) -> None:
        self._selection_edit.setText(text)
        if text:
            self._selection_edit.show()
            self._position_overlays()
        else:
            self._selection_edit.hide()
            self._selection_marker.hide()

    def _show_pick(self, shotpoint: float, value: float, source_no: str) -> None:
        sp_text = str(int(shotpoint)) if shotpoint == int(shotpoint) else f"{shotpoint:.1f}"
        unit = PLOT_KIND_UNITS[self._kind]
        self._set_selection_text(
            f"SP {sp_text}: {_format_pick_value(self._kind, value)} {unit}  ({source_no})"
        )
        self._selection_marker.setData([shotpoint], [value])
        self._selection_marker.show()

    def _on_scene_mouse_clicked(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton or ev.double():
            return
        if self._viewbox.left_click_was_drag():
            return
        vb = self._viewbox
        mouse = vb.mapSceneToView(ev.scenePos())
        x_tol, y_tol = _pick_tolerance(vb)
        picked = nearest_pick_point(
            self._pick_points,
            mouse.x(),
            mouse.y(),
            x_tol,
            y_tol,
        )
        if picked is None:
            self._set_selection_text("")
            return
        shotpoint, value, source_no = picked
        self._show_pick(shotpoint, value, source_no)

    def _bind_curve_pick(self, curve: pg.PlotDataItem, source_no: str) -> None:
        if not hasattr(curve, "sigPointsClicked"):
            return

        def on_points_clicked(_item, points, _ev) -> None:
            if not points:
                return
            pos = points[0].pos()
            self._show_pick(pos.x(), pos.y(), source_no)

        curve.sigPointsClicked.connect(on_points_clicked)

    def _center_average(self) -> None:
        if self._extent_x is None or self._extent_y is None:
            return
        if not self._pick_points:
            return
        shotpoints = [point[0] for point in self._pick_points]
        values = [point[1] for point in self._pick_points]
        avg_x = sum(shotpoints) / len(shotpoints)
        avg_y = sum(values) / len(values)
        (x0, x1), (y0, y1) = self._viewbox.viewRange()
        x_span = x1 - x0
        y_span = y1 - y0
        self._viewbox.disableAutoRange()
        self._viewbox.setRange(
            xRange=(avg_x - x_span / 2, avg_x + x_span / 2),
            yRange=(avg_y - y_span / 2, avg_y + y_span / 2),
            padding=0,
            update=True,
        )

    def _reset_zoom(self) -> None:
        self._viewbox.zoom_to_extent()

    def _update_stats_overlay(self, values: list[float]) -> None:
        if not values:
            self._stats_label.setText("")
            return
        v_min = min(values)
        v_max = max(values)
        v_avg = sum(values) / len(values)
        self._stats_label.setText(f"Max: {v_max:.2f}   Min: {v_min:.2f}   Avg: {v_avg:.2f}")
        self._position_overlays()

    def render(
        self,
        series_list: list[PlotSeries],
        styles: list[SourceStyleRow],
        boundaries: list[BoundaryRow],
        *,
        y_min: float | None,
        y_max: float | None,
        auto_y: bool,
    ) -> None:
        for item in self._curve_items:
            self.removeItem(item)
        for item in self._boundary_items:
            self.removeItem(item)
        self._curve_items.clear()
        self._boundary_items.clear()
        self._pick_points.clear()
        self._set_selection_text("")
        self._selection_marker.hide()

        style_by_source = _style_lookup(styles)
        all_values: list[float] = []
        all_x: list[float] = []

        for series in series_list:
            if not series.shotpoints:
                continue
            style = style_by_source.get(series.source_no)
            if style is None:
                style = SourceStyleRow(source_no=series.source_no)
            pen = source_pen(style)
            x_data = np.asarray(series.shotpoints, dtype=np.float64)
            y_data = np.asarray(series.values, dtype=np.float64)
            show_symbols = True
            symbol_size = 5 if style.line_style == LineStyle.SOLID else 6
            curve = self.plot(
                x_data,
                y_data,
                pen=pen,
                name=series.source_no,
                symbol="o" if show_symbols else None,
                symbolSize=symbol_size,
                symbolBrush=QColor(style.color),
                symbolPen=pg.mkPen(style.color, width=1),
                connect="all",
            )
            self._curve_items.append(curve)
            self._bind_curve_pick(curve, series.source_no)
            all_values.extend(y_data.tolist())
            all_x.extend(x_data.tolist())
            for shotpoint, value in zip(x_data.tolist(), y_data.tolist(), strict=False):
                self._pick_points.append((shotpoint, value, series.source_no))

        for boundary in boundaries:
            limit = abs(float(boundary.abs_boundary))
            if limit <= 0:
                continue
            pen = boundary_pen(boundary)
            for y_value in (limit, -limit):
                line = pg.InfiniteLine(
                    pos=y_value,
                    angle=0,
                    pen=pen,
                )
                self.addItem(line)
                self._boundary_items.append(line)

        y_range: tuple[float, float] | None = None
        if auto_y:
            if all_values:
                data_min = min(all_values)
                data_max = max(all_values)
                span = max(data_max - data_min, 1.0)
                pad = span * 0.08
                y_range = (data_min - pad, data_max + pad)
                self.setYRange(y_range[0], y_range[1], padding=0.02)
            else:
                self.enableAutoRange(axis="y")
        elif y_min is not None and y_max is not None and y_min < y_max:
            y_range = (y_min, y_max)
            self.setYRange(y_min, y_max, padding=0.0)
        else:
            self.enableAutoRange(axis="y")

        x_range: tuple[float, float] | None = None
        if all_x:
            x_min = min(all_x)
            x_max = max(all_x)
            x_pad = max((x_max - x_min) * 0.02, 1.0)
            x_range = (x_min - x_pad, x_max + x_pad)
            self.setXRange(x_range[0], x_range[1], padding=0.0)
        else:
            self.enableAutoRange(axis="x")

        if x_range is None or y_range is None:
            (xr, yr) = self._viewbox.viewRange()
            if x_range is None:
                x_range = (xr[0], xr[1])
            if y_range is None:
                y_range = (yr[0], yr[1])
        self._extent_x = x_range
        self._extent_y = y_range
        self._viewbox.set_extent_range(x_range, y_range)
        self._viewbox.zoom_to_extent()

        self._update_stats_overlay(all_values)
        self._schedule_repaint()

    def _schedule_repaint(self) -> None:
        def _repaint() -> None:
            vb = self.getPlotItem().getViewBox()
            vb.updateAutoRange()
            self.update()
            self.repaint()
            self._position_overlays()
            app = QApplication.instance()
            if app is not None:
                app.processEvents()

        QTimer.singleShot(0, _repaint)

    def capture_image(self, *, width: int, height: int) -> QImage:
        """Render plot scene to an image (pyqtgraph-safe)."""
        self.resize(max(width, 320), max(height, _MIN_PLOT_HEIGHT))
        self._position_overlays()
        QApplication.processEvents()
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        scene = self.scene()
        if scene is None:
            return image
        source = self.mapToScene(self.viewport().rect()).boundingRect()
        if source.isEmpty():
            source = QRectF(0, 0, self.width(), self.height())
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scene.render(
            painter,
            QRectF(0, 0, width, height),
            source,
            Qt.AspectRatioMode.IgnoreAspectRatio,
        )
        scale_x = width / max(self.width(), 1)
        scale_y = height / max(self.height(), 1)
        for widget in (self._selection_edit, self._stats_label):
            if not widget.isVisible() or not widget.text():
                continue
            geo = widget.geometry()
            target = QRectF(
                geo.x() * scale_x,
                geo.y() * scale_y,
                geo.width() * scale_x,
                geo.height() * scale_y,
            )
            painter.fillRect(target, QColor(255, 255, 255, 225))
            painter.setPen(QColor(_PLOT_FG))
            painter.drawText(
                target.adjusted(4, 2, -4, -2),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                widget.text() if isinstance(widget, QLabel) else widget.text(),
            )
        painter.end()
        return image


class SourceTabPlotHost(QWidget):
    """Nested source tabs — one full-size plot per source."""

    def __init__(self, kind: PlotKind, parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(STAT_PLOT_SOURCE_TAB_STYLE)
        layout.addWidget(self._tabs, stretch=1)
        self._plots: dict[str, TimeSeriesPlotWidget] = {}

    def render(
        self,
        series_list: list[PlotSeries],
        styles: list[SourceStyleRow],
        boundaries: list[BoundaryRow],
        *,
        y_min: float | None,
        y_max: float | None,
        auto_y: bool,
    ) -> None:
        while self._tabs.count():
            widget = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        self._plots.clear()

        style_by_source = _style_lookup(styles)
        for series in series_list:
            if not series.shotpoints:
                continue
            plot = TimeSeriesPlotWidget(self._kind, parent=self)
            plot.setMinimumHeight(_MIN_PLOT_HEIGHT)
            style = style_by_source.get(
                series.source_no,
                SourceStyleRow(source_no=series.source_no),
            )
            plot.render(
                [series],
                [style],
                boundaries,
                y_min=y_min,
                y_max=y_max,
                auto_y=auto_y,
            )
            self._tabs.addTab(plot, series.source_no)
            self._plots[series.source_no] = plot

    def current_plot(self) -> TimeSeriesPlotWidget | None:
        widget = self._tabs.currentWidget()
        if isinstance(widget, TimeSeriesPlotWidget):
            return widget
        return None

    def all_plots(self) -> list[TimeSeriesPlotWidget]:
        return list(self._plots.values())

    def capture_image(self, *, width: int, height: int) -> QImage:
        plot = self.current_plot()
        if plot is not None:
            return plot.capture_image(width=width, height=height)
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        return image


class PlotCanvas(QWidget):
    """Combined or per-source tabbed plot canvas; white plot on dark surround."""

    def __init__(self, kind: PlotKind, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statPlotCanvasHost")
        self._kind = kind
        self._combine = True
        self._frame = QWidget(self)
        self._frame.setObjectName("statPlotWhiteFrame")
        self._frame_layout = QVBoxLayout(self._frame)
        self._frame_layout.setContentsMargins(4, 4, 4, 4)
        self._frame_layout.setSpacing(0)

        self._direct_host = QWidget(self._frame)
        self._direct_layout = QVBoxLayout(self._direct_host)
        self._direct_layout.setContentsMargins(0, 0, 0, 0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._frame, stretch=1)

        self._combined_plot: TimeSeriesPlotWidget | None = None
        self._source_tabs: SourceTabPlotHost | None = None
        self._frame_layout.addWidget(self._direct_host, stretch=1)

    def set_combine_sources(self, combine: bool) -> None:
        self._combine = combine

    def render(
        self,
        series_list: list[PlotSeries],
        styles: list[SourceStyleRow],
        boundaries: list[BoundaryRow],
        *,
        y_min: float | None,
        y_max: float | None,
        auto_y: bool,
    ) -> None:
        while self._direct_layout.count():
            item = self._direct_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._combined_plot = None
        self._source_tabs = None

        if self._combine:
            plot = TimeSeriesPlotWidget(self._kind, parent=self._direct_host)
            plot.setMinimumHeight(_MIN_PLOT_HEIGHT)
            plot.render(
                series_list,
                styles,
                boundaries,
                y_min=y_min,
                y_max=y_max,
                auto_y=auto_y,
            )
            self._direct_layout.addWidget(plot, stretch=1)
            self._combined_plot = plot
        else:
            tabs = SourceTabPlotHost(self._kind, parent=self._direct_host)
            tabs.render(
                series_list,
                styles,
                boundaries,
                y_min=y_min,
                y_max=y_max,
                auto_y=auto_y,
            )
            self._direct_layout.addWidget(tabs, stretch=1)
            self._source_tabs = tabs

    def content_widget(self) -> QWidget | None:
        if self._combined_plot is not None:
            return self._combined_plot
        if self._source_tabs is not None:
            return self._source_tabs
        return None

    def capture_image(self, *, width: int, height: int) -> QImage:
        if self._combined_plot is not None:
            return self._combined_plot.capture_image(width=width, height=height)
        if self._source_tabs is not None:
            return self._source_tabs.capture_image(width=width, height=height)
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        return image

    def has_data(self) -> bool:
        if self._combined_plot is not None:
            return bool(self._combined_plot._curve_items)
        if self._source_tabs is not None:
            return bool(self._source_tabs.all_plots())
        return False

    def plot_for_source(self, source_no: str) -> TimeSeriesPlotWidget | None:
        if self._source_tabs is None:
            return None
        return self._source_tabs._plots.get(source_no)

    def select_source_tab(self, source_no: str) -> None:
        if self._source_tabs is None:
            return
        for index in range(self._source_tabs._tabs.count()):
            if self._source_tabs._tabs.tabText(index) == source_no:
                self._source_tabs._tabs.setCurrentIndex(index)
                return
