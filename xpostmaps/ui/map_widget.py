"""PyQtGraph postplot map widget — plot area only (print white theme)."""

from __future__ import annotations

import pyqtgraph as pg
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from xpostmaps.core.models import (
    DisplayMode,
    LegendConfig,
    LineSegment,
    LineStyle,
    MapData,
    NavDataType,
    PostplotLegendEntry,
    RecordType,
    sequence_id_matches,
)
from xpostmaps.ui.theme import (
    BG_MAP_PRINT,
    DOWN_LINE,
    OVERLAY_LINE,
    PREPLOT_LINE,
    SURVEY_BOUNDARY,
    TEXT_PRINT,
    UP_LINE,
)


try:
    pg.setConfigOptions(antialias=True, useOpenGL=False, foreground=TEXT_PRINT)
except Exception:
    pg.setConfigOptions(antialias=True, useOpenGL=False, foreground=TEXT_PRINT)


def _color_with_opacity(color: str, opacity: float) -> tuple[int, int, int, int]:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, opacity)))
    return c.red(), c.green(), c.blue(), c.alpha()


class NorthArrow(pg.GraphicsObject):
    def __init__(self) -> None:
        super().__init__()
        self._picture = None
        self._generate()

    def _generate(self) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainter, QPicture, QPolygonF

        pic = QPicture()
        painter = QPainter(pic)
        painter.setPen(pg.mkPen(TEXT_PRINT, width=1.5))
        painter.setBrush(pg.mkBrush(TEXT_PRINT))
        arrow = QPolygonF(
            [QPointF(0, -18), QPointF(-7, 6), QPointF(0, 2), QPointF(7, 6)]
        )
        painter.drawPolygon(arrow)
        painter.drawText(-5, 22, "N")
        painter.end()
        self._picture = pic

    def paint(self, painter, *args) -> None:
        if self._picture:
            self._picture.play(painter)

    def boundingRect(self):  # noqa: N802
        from PySide6.QtCore import QRectF

        return QRectF(-12, -22, 24, 30)


class PostplotMapWidget(QWidget):
    """High-performance map canvas — survey plot area only."""

    _NAV_TYPES = frozenset({RecordType.SOURCE, RecordType.VESSEL})

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._display_mode = DisplayMode.LINES
        self._legend = LegendConfig.default()
        self._plot_items: list[pg.GraphicsItem] = []

        self.setStyleSheet(f"background: {BG_MAP_PRINT};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget(background=BG_MAP_PRINT)
        self._plot_item = self._plot.getPlotItem()
        self._plot.setAspectLocked(True)
        self._plot.showGrid(x=False, y=False)
        self._plot_item.hideButtons()
        self._plot.setLabel("bottom", "Easting", color=TEXT_PRINT)
        self._plot.setLabel("left", "Northing", color=TEXT_PRINT)

        for axis in ("bottom", "left"):
            ax = self._plot_item.getAxis(axis)
            ax.setPen(pg.mkPen(TEXT_PRINT))
            ax.setTextPen(pg.mkPen(TEXT_PRINT))

        vb = self._plot.getViewBox()
        vb.setBackgroundColor(BG_MAP_PRINT)
        vb.setMouseMode(pg.ViewBox.PanMode)
        vb.enableAutoRange(False)
        layout.addWidget(self._plot)

        self._north = NorthArrow()
        self._north.setParentItem(self._plot_item)
        self._north.setZValue(100)
        vb.sigRangeChanged.connect(self._reposition_overlays)

    def set_display_mode(self, mode: DisplayMode) -> None:
        self._display_mode = mode

    def set_legend(self, legend: LegendConfig) -> None:
        self._legend = legend

    def clear(self) -> None:
        for item in self._plot_items:
            self._plot_item.removeItem(item)
        self._plot_items.clear()

    @staticmethod
    def _record_type_for_data_type(data_type: NavDataType) -> RecordType:
        return (
            RecordType.VESSEL
            if data_type == NavDataType.VESSEL
            else RecordType.SOURCE
        )

    def _entry_for_segment(self, segment: LineSegment) -> PostplotLegendEntry | None:
        if segment.record_type in (RecordType.OVERLAY, RecordType.PREPLOT, RecordType.NAVPLAN):
            return None

        if segment.sequence_id:
            for entry in self._legend.postplot_lines:
                if not sequence_id_matches(segment.sequence_id, entry.sequence_ids):
                    continue
                required = self._record_type_for_data_type(entry.data_type)
                if segment.record_type == required:
                    return entry
            return None

        default_name = "Up Line" if segment.direction >= 0 else "Down Line"
        for entry in self._legend.postplot_lines:
            if entry.sequence_ids:
                continue
            required = self._record_type_for_data_type(entry.data_type)
            if segment.record_type not in self._NAV_TYPES:
                return entry
            if segment.record_type != required:
                continue
            if entry.name.lower() == default_name.lower():
                return entry
        for entry in self._legend.postplot_lines:
            if entry.sequence_ids:
                continue
            required = self._record_type_for_data_type(entry.data_type)
            if segment.record_type in self._NAV_TYPES and segment.record_type != required:
                continue
            if "up" in entry.name.lower() and segment.direction >= 0:
                return entry
            if "down" in entry.name.lower() and segment.direction < 0:
                return entry
        unassigned = [e for e in self._legend.postplot_lines if not e.sequence_ids]
        idx = 0 if segment.direction >= 0 else min(1, len(unassigned) - 1)
        if unassigned:
            entry = unassigned[idx]
            required = self._record_type_for_data_type(entry.data_type)
            if segment.record_type in self._NAV_TYPES and segment.record_type != required:
                return None
            return entry
        return None

    def _style_for_segment(
        self, segment: LineSegment
    ) -> tuple[str, LineStyle, float]:
        if segment.record_type == RecordType.OVERLAY:
            return OVERLAY_LINE, LineStyle.SOLID, 1.0
        if segment.record_type in (RecordType.PREPLOT, RecordType.NAVPLAN):
            return PREPLOT_LINE, LineStyle.SOLID, 1.0

        entry = self._entry_for_segment(segment)
        if entry:
            return entry.color, entry.line_style, entry.opacity

        default_color = UP_LINE if segment.direction >= 0 else DOWN_LINE
        return default_color, LineStyle.SOLID, 1.0

    def _segment_should_draw(self, segment: LineSegment) -> bool:
        if segment.record_type not in self._NAV_TYPES:
            return True

        assigned_entries = [e for e in self._legend.postplot_lines if e.sequence_ids]
        if not assigned_entries:
            entry = self._entry_for_segment(segment)
            return entry is not None

        for entry in assigned_entries:
            if not sequence_id_matches(segment.sequence_id, entry.sequence_ids):
                continue
            required = self._record_type_for_data_type(entry.data_type)
            if segment.record_type == required:
                return True
        return False

    def _add_segment(self, segment: LineSegment, width: float = 1.2) -> None:
        if not segment.xs:
            return
        xs = np.asarray(segment.xs, dtype=np.float64)
        ys = np.asarray(segment.ys, dtype=np.float64)
        color, line_style, opacity = self._style_for_segment(segment)
        rgba = _color_with_opacity(color, opacity)

        if line_style == LineStyle.DOTTED or self._display_mode == DisplayMode.DOTS:
            item = pg.ScatterPlotItem(
                xs,
                ys,
                pen=pg.mkPen(rgba, width=1),
                brush=pg.mkBrush(rgba),
                size=5,
                pxMode=True,
                symbol="o",
            )
        else:
            qt_style = (
                Qt.PenStyle.DashLine
                if line_style == LineStyle.DASH
                else Qt.PenStyle.SolidLine
            )
            item = pg.PlotDataItem(
                xs,
                ys,
                pen=pg.mkPen(rgba, width=width, style=qt_style),
                connect="all",
                antialias=True,
                clipToView=False,
            )
        self._plot_item.addItem(item)
        self._plot_items.append(item)

    def _add_boundary(self, map_data: MapData) -> None:
        if not map_data.bounds.is_valid:
            return
        b = map_data.bounds
        pad_x = (b.xmax - b.xmin) * 0.01 or 100
        pad_y = (b.ymax - b.ymin) * 0.01 or 100
        xs = [b.xmin - pad_x, b.xmax + pad_x, b.xmax + pad_x, b.xmin - pad_x, b.xmin - pad_x]
        ys = [b.ymin - pad_y, b.ymin - pad_y, b.ymax + pad_y, b.ymax + pad_y, b.ymin - pad_y]
        boundary = pg.PlotDataItem(
            xs,
            ys,
            pen=pg.mkPen(SURVEY_BOUNDARY, width=1.5),
            connect="all",
            clipToView=False,
        )
        self._plot_item.addItem(boundary)
        self._plot_items.append(boundary)

    def _reposition_overlays(self) -> None:
        vb = self._plot.getViewBox()
        if vb is None:
            return
        view_range = vb.viewRange()
        x0, x1 = view_range[0]
        y0, y1 = view_range[1]
        self._north.setPos(x0 + (x1 - x0) * 0.04, y0 + (y1 - y0) * 0.06)

    def render(self, map_data: MapData | None) -> None:
        vb = self._plot.getViewBox()
        vb.blockSignals(True)
        try:
            self.clear()
            if map_data is None or not map_data.segments:
                return

            for seg in map_data.segments:
                if not self._segment_should_draw(seg):
                    continue
                self._add_segment(seg)
            for seg in map_data.overlay_segments:
                self._add_segment(seg, width=1.0)
            for seg in map_data.preplot_segments:
                self._add_segment(seg, width=0.9)

            self._add_boundary(map_data)

            if map_data.bounds.is_valid:
                b = map_data.bounds
                margin_x = (b.xmax - b.xmin) * 0.05 or 500
                margin_y = (b.ymax - b.ymin) * 0.05 or 500
                self._plot.setRange(
                    xRange=(b.xmin - margin_x, b.xmax + margin_x),
                    yRange=(b.ymin - margin_y, b.ymax + margin_y),
                    padding=0,
                )
            self._reposition_overlays()
        finally:
            vb.blockSignals(False)
