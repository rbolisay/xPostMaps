"""PyQtGraph postplot map widget — plot area only (print white theme)."""

from __future__ import annotations

import pyqtgraph as pg
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsItem, QGraphicsView, QVBoxLayout, QWidget

from xpostmaps.core.area_utils import resolve_area_polygon
from xpostmaps.core.polygon_import_service import is_imported_polygon
from xpostmaps.core.preplot_catalog_utils import (
    resolve_preplot_file_order,
    segments_for_preplot_source,
)
from xpostmaps.core.models import (
    DisplayMode,
    LegendConfig,
    LineSegment,
    LineStyle,
    MapData,
    NavDataType,
    PostplotLegendEntry,
    PreplotLegendEntry,
    RecordType,
    sequence_id_matches,
)
from xpostmaps.ui.map_batch import LineBatchKey, concat_points, concat_polylines
from xpostmaps.ui.map_view_box import MapViewBox
from xpostmaps.ui.theme import (
    BG_MAP_PRINT,
    DOWN_LINE,
    OVERLAY_LINE,
    PREPLOT_LINE,
    SURVEY_BOUNDARY,
    TEXT_PRINT,
    UP_LINE,
)


def _configure_pyqtgraph() -> None:
    pg.setConfigOptions(antialias=False, useOpenGL=False, foreground=TEXT_PRINT)


_configure_pyqtgraph()


def _color_with_opacity(color: str, opacity: float) -> tuple[int, int, int, int]:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, opacity)))
    return c.red(), c.green(), c.blue(), c.alpha()


class NorthArrow(pg.GraphicsObject):
    def __init__(self) -> None:
        super().__init__()
        self._picture = None
        self._generate()
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

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
        self._extent_x: tuple[float, float] | None = None
        self._extent_y: tuple[float, float] | None = None
        self._cached_signature: tuple | None = None

        self.setStyleSheet(f"background: {BG_MAP_PRINT};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget(viewBox=MapViewBox(), background=BG_MAP_PRINT)
        self._plot_item = self._plot.getPlotItem()
        self._plot.setMenuEnabled(False)
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
        vb.enableAutoRange(False)
        vb.setMouseEnabled(x=True, y=True)
        self._plot.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        layout.addWidget(self._plot)

        self._north = NorthArrow()
        self._north.setParentItem(self._plot_item)
        self._north.setZValue(100)

        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.setInterval(32)
        self._overlay_timer.timeout.connect(self._reposition_overlays)
        vb.sigRangeChanged.connect(self._schedule_overlay_reposition)

    def set_display_mode(self, mode: DisplayMode) -> None:
        self._display_mode = mode
        self._cached_signature = None

    def set_legend(self, legend: LegendConfig) -> None:
        self._legend = legend
        self._cached_signature = None

    def clear(self) -> None:
        view_box = self._plot.getViewBox()
        scene = self._plot.scene()
        for item in self._plot_items:
            try:
                view_box.removeItem(item)
            except Exception:
                pass
            try:
                self._plot_item.removeItem(item)
            except Exception:
                pass
            try:
                scene.removeItem(item)
            except Exception:
                pass
        self._plot_items.clear()

    @staticmethod
    def _record_type_for_data_type(data_type: NavDataType) -> RecordType:
        return (
            RecordType.VESSEL
            if data_type == NavDataType.VESSEL
            else RecordType.SOURCE
        )

    def _segment_matches_postplot_entry(
        self,
        segment: LineSegment,
        entry: PostplotLegendEntry,
    ) -> bool:
        if entry.hidden:
            return False
        if segment.record_type in (RecordType.OVERLAY, RecordType.PREPLOT, RecordType.NAVPLAN):
            return False

        required = self._record_type_for_data_type(entry.data_type)
        if segment.record_type in self._NAV_TYPES and segment.record_type != required:
            return False

        # P111/P190 imports are project data, not automatically visible layers.
        # A PostPlot row draws only after the user selects sequences for it.
        if not entry.sequence_filter_active or not entry.sequence_ids:
            return False
        if not segment.sequence_id:
            return False
        return sequence_id_matches(segment.sequence_id, entry.sequence_ids)

    def _entry_for_segment(self, segment: LineSegment) -> PostplotLegendEntry | None:
        if segment.record_type in (RecordType.OVERLAY, RecordType.PREPLOT, RecordType.NAVPLAN):
            return None

        for entry in reversed(self._legend.postplot_lines):
            if self._segment_matches_postplot_entry(segment, entry):
                return entry
        return None

    def _style_for_segment(
        self, segment: LineSegment, *, width_override: float | None = None
    ) -> tuple[str, LineStyle, float, float, float]:
        if segment.record_type == RecordType.OVERLAY:
            return OVERLAY_LINE, LineStyle.SOLID, 1.0, width_override or 1.0, 3.0
        if segment.record_type in (RecordType.PREPLOT, RecordType.NAVPLAN):
            return PREPLOT_LINE, LineStyle.SOLID, 1.0, width_override or 0.9, 3.0

        entry = self._entry_for_segment(segment)
        if entry:
            return (
                entry.color,
                entry.line_style,
                entry.opacity,
                width_override or entry.line_width,
                entry.dot_radius,
            )

        default_color = UP_LINE if segment.direction >= 0 else DOWN_LINE
        return default_color, LineStyle.SOLID, 1.0, width_override or 1.2, 3.0

    def _segment_should_draw(self, segment: LineSegment) -> bool:
        if segment.record_type not in self._NAV_TYPES:
            return True
        return self._entry_for_segment(segment) is not None

    def _style_fn_for_batch(self, width_override: float | None = None):
        def style_fn(segment: LineSegment) -> tuple[str, LineStyle, float]:
            color, line_style, opacity, width, _dot_radius = self._style_for_segment(
                segment, width_override=width_override
            )
            _ = width
            return color, line_style, opacity

        return style_fn

    def _add_batched_segments(
        self,
        segments: list[LineSegment],
        *,
        width_override: float | None = None,
    ) -> None:
        if not segments:
            return
        dotted = self._display_mode == DisplayMode.DOTS
        style_fn = self._style_fn_for_batch(width_override)
        batches: dict[LineBatchKey, list[tuple[np.ndarray, np.ndarray]]] = {}
        for segment in segments:
            if not segment.xs:
                continue
            color, line_style, opacity = style_fn(segment)
            rgba = _color_with_opacity(color, opacity)
            _, _, _, width, dot_radius = self._style_for_segment(
                segment,
                width_override=width_override,
            )
            key = LineBatchKey(
                color=rgba,
                line_style=line_style,
                width=width,
                dotted=dotted or line_style == LineStyle.DOTTED,
                dot_radius=dot_radius,
            )
            xs = np.asarray(segment.xs, dtype=np.float64)
            ys = np.asarray(segment.ys, dtype=np.float64)
            batches.setdefault(key, []).append((xs, ys))

        for key, parts in batches.items():
            self._add_batch_item(key, parts)

    def _add_batch_item(
        self,
        key: LineBatchKey,
        parts: list[tuple[np.ndarray, np.ndarray]],
    ) -> None:
        rgba = key.color
        if key.dotted:
            xs, ys = concat_points(parts)
            if xs.size == 0:
                return
            item = pg.ScatterPlotItem(
                xs,
                ys,
                pen=None,
                brush=pg.mkBrush(rgba),
                size=max(1.0, key.dot_radius * 2.0),
                pxMode=True,
                symbol="o",
            )
        else:
            xs, ys = concat_polylines(parts)
            if xs.size == 0:
                return
            qt_style = (
                Qt.PenStyle.DashLine
                if key.line_style == LineStyle.DASH
                else Qt.PenStyle.SolidLine
            )
            item = pg.PlotDataItem(
                xs,
                ys,
                pen=pg.mkPen(rgba, width=key.width, style=qt_style),
                connect="finite",
                antialias=False,
                clipToView=False,
                skipFiniteCheck=True,
            )

        self._plot.getViewBox().addItem(item)
        self._plot_items.append(item)

    def _add_batched_segments_styled(
        self,
        segments: list[LineSegment],
        *,
        color: str,
        line_style: LineStyle,
        opacity: float,
        width: float = 0.9,
        dot_radius: float = 3.0,
    ) -> None:
        if not segments:
            return
        dotted = self._display_mode == DisplayMode.DOTS
        rgba = _color_with_opacity(color, opacity)
        key = LineBatchKey(
            color=rgba,
            line_style=line_style,
            width=width,
            dotted=dotted or line_style == LineStyle.DOTTED,
            dot_radius=dot_radius,
        )
        parts: list[tuple[np.ndarray, np.ndarray]] = []
        for segment in segments:
            if not segment.xs:
                continue
            parts.append(
                (np.asarray(segment.xs, dtype=np.float64), np.asarray(segment.ys, dtype=np.float64))
            )
        if parts:
            self._add_batch_item(key, parts)

    def _add_legend_preplot_segments(self, map_data: MapData | None) -> None:
        if map_data is None or not map_data.preplot_segments:
            return
        file_paths = resolve_preplot_file_order(map_data)
        # The legend is the single source of truth: only preplot sources that
        # have a visible legend row are drawn. Removing a row in the legend
        # therefore removes those lines from the map (data stays in the DB).
        for entry in self._legend.preplot_lines:
            if entry.hidden:
                continue
            segments = segments_for_preplot_source(
                map_data.preplot_segments,
                file_paths,
                entry.preplot_source_index,
            )
            if not segments:
                continue
            style = entry.line_style
            if style not in (LineStyle.SOLID, LineStyle.DASH, LineStyle.DOTTED):
                style = LineStyle.SOLID
            self._add_batched_segments_styled(
                segments,
                color=entry.color,
                line_style=style,
                opacity=entry.opacity,
                width=entry.line_width,
                dot_radius=entry.dot_radius,
            )

    def _add_area_polygons(self, map_data: MapData | None) -> None:
        legend_areas = self._legend.areas
        for entry in legend_areas:
            if entry.hidden or is_imported_polygon(entry):
                continue
            xs, ys = resolve_area_polygon(entry, map_data, legend_areas)
            if len(xs) < 2:
                continue
            rgba = _color_with_opacity(entry.color, entry.opacity)
            qt_style = (
                Qt.PenStyle.DashLine
                if entry.border_style == LineStyle.DASH
                else Qt.PenStyle.SolidLine
            )
            boundary = pg.PlotDataItem(
                np.asarray(xs, dtype=np.float64),
                np.asarray(ys, dtype=np.float64),
                pen=pg.mkPen(rgba, width=entry.border_width, style=qt_style),
                connect="all",
                antialias=False,
                clipToView=False,
            )
            self._plot.getViewBox().addItem(boundary)
            self._plot_items.append(boundary)

    def _add_boundary(self, map_data: MapData) -> None:
        if not map_data.bounds.is_valid:
            return
        b = map_data.bounds
        pad_x = (b.xmax - b.xmin) * 0.01 or 100
        pad_y = (b.ymax - b.ymin) * 0.01 or 100
        xs = np.array(
            [b.xmin - pad_x, b.xmax + pad_x, b.xmax + pad_x, b.xmin - pad_x, b.xmin - pad_x],
            dtype=np.float64,
        )
        ys = np.array(
            [b.ymin - pad_y, b.ymin - pad_y, b.ymax + pad_y, b.ymax + pad_y, b.ymin - pad_y],
            dtype=np.float64,
        )
        boundary = pg.PlotDataItem(
            xs,
            ys,
            pen=pg.mkPen(SURVEY_BOUNDARY, width=1.5),
            connect="all",
            antialias=False,
            clipToView=False,
        )
        self._plot.getViewBox().addItem(boundary)
        self._plot_items.append(boundary)

    def _schedule_overlay_reposition(self) -> None:
        self._overlay_timer.start()

    def _reposition_overlays(self) -> None:
        vb = self._plot.getViewBox()
        if vb is None:
            return
        view_range = vb.viewRange()
        x0, x1 = view_range[0]
        y0, y1 = view_range[1]
        self._north.setPos(x0 + (x1 - x0) * 0.04, y0 + (y1 - y0) * 0.06)

    def zoom_to_extent(self) -> None:
        vb = self._plot.getViewBox()
        if isinstance(vb, MapViewBox):
            vb.zoom_to_extent()

    def _visible_extent_ranges(
        self,
        map_data: MapData,
        nav_segments: list[LineSegment] | None = None,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        all_x: list[float] = []
        all_y: list[float] = []

        for segment in nav_segments if nav_segments is not None else []:
            all_x.extend(segment.xs)
            all_y.extend(segment.ys)

        file_paths = resolve_preplot_file_order(map_data)
        for entry in self._legend.preplot_lines:
            if entry.hidden:
                continue
            for segment in segments_for_preplot_source(
                map_data.preplot_segments,
                file_paths,
                entry.preplot_source_index,
            ):
                all_x.extend(segment.xs)
                all_y.extend(segment.ys)

        for entry in self._legend.areas:
            if entry.hidden or is_imported_polygon(entry):
                continue
            xs, ys = resolve_area_polygon(entry, map_data, self._legend.areas)
            all_x.extend(xs)
            all_y.extend(ys)

        if not all_x or not all_y:
            return None

        xs_arr = np.asarray(all_x, dtype=np.float64)
        ys_arr = np.asarray(all_y, dtype=np.float64)
        valid = np.isfinite(xs_arr) & np.isfinite(ys_arr)
        if not np.any(valid):
            return None

        xmin = float(np.min(xs_arr[valid]))
        xmax = float(np.max(xs_arr[valid]))
        ymin = float(np.min(ys_arr[valid]))
        ymax = float(np.max(ys_arr[valid]))
        margin_x = (xmax - xmin) * 0.05 or 500
        margin_y = (ymax - ymin) * 0.05 or 500
        return (
            (xmin - margin_x, xmax + margin_x),
            (ymin - margin_y, ymax + margin_y),
        )

    def _update_extent(
        self,
        map_data: MapData,
        nav_segments: list[LineSegment] | None = None,
    ) -> None:
        vb = self._plot.getViewBox()
        ranges = self._visible_extent_ranges(map_data, nav_segments)
        if ranges is None:
            self._extent_x = None
            self._extent_y = None
            if isinstance(vb, MapViewBox):
                vb.set_extent_range(None, None)
            return

        self._extent_x, self._extent_y = ranges
        if isinstance(vb, MapViewBox):
            vb.set_extent_range(self._extent_x, self._extent_y)

    def _postplot_signature(self) -> tuple:
        return tuple(
            (
                entry.name,
                entry.data_type.value,
                entry.sequence_filter_active,
                tuple(entry.sequence_ids),
                entry.line_style.value,
                entry.color,
                entry.opacity,
                entry.line_width,
                entry.dot_radius,
                entry.hidden,
            )
            for entry in self._legend.postplot_lines
        )

    def _area_signature(self) -> tuple:
        return tuple(
            (
                entry.name,
                entry.coordinate_mode.value,
                entry.survey_perimeter_index,
                entry.imported_polygon_index,
                entry.border_style.value,
                entry.color,
                entry.opacity,
                entry.border_width,
                entry.hidden,
                tuple((p.x, p.y) for p in entry.custom_points),
            )
            for entry in self._legend.areas
        )

    def _render_signature(self, map_data: MapData | None) -> tuple:
        if map_data is None:
            return ("empty", self._display_mode, self._area_signature(), self._postplot_signature())
        bounds = (
            map_data.bounds.xmin,
            map_data.bounds.xmax,
            map_data.bounds.ymin,
            map_data.bounds.ymax,
        )
        return (
            len(map_data.segments),
            len(map_data.preplot_segments),
            len(map_data.overlay_segments),
            len(self._legend.preplot_lines),
            tuple(
                (
                    entry.name,
                    entry.preplot_source_index,
                    entry.line_style.value,
                    entry.color,
                    entry.opacity,
                    entry.line_width,
                    entry.dot_radius,
                    entry.hidden,
                )
                for entry in self._legend.preplot_lines
            ),
            bounds,
            self._display_mode,
            self._area_signature(),
            self._postplot_signature(),
        )

    def render(
        self,
        map_data: MapData | None,
        *,
        force: bool = False,
    ) -> None:
        signature = self._render_signature(map_data)
        if not force and signature == self._cached_signature and self._plot_items:
            return

        vb = self._plot.getViewBox()
        current_range = vb.viewRange() if self._plot_items else None

        self.clear()
        if map_data is None:
            self._extent_x = None
            self._extent_y = None
            if isinstance(vb, MapViewBox):
                vb.set_extent_range(None, None)
            self._cached_signature = signature
            return

        nav_segments = [
            seg for seg in map_data.segments if self._segment_should_draw(seg)
        ]
        visible_preplot = any(
            not entry.hidden
            and bool(
                segments_for_preplot_source(
                    map_data.preplot_segments,
                    resolve_preplot_file_order(map_data),
                    entry.preplot_source_index,
                )
            )
            for entry in self._legend.preplot_lines
        )
        visible_areas = any(
            not entry.hidden
            and not is_imported_polygon(entry)
            and len(resolve_area_polygon(entry, map_data, self._legend.areas)[0]) >= 2
            for entry in self._legend.areas
        )
        has_nav = bool(nav_segments)

        if not has_nav and not visible_preplot and not visible_areas:
            self._extent_x = None
            self._extent_y = None
            if isinstance(vb, MapViewBox):
                vb.set_extent_range(None, None)
            self._cached_signature = signature
            return

        extent_ranges = self._visible_extent_ranges(map_data, nav_segments)
        if current_range is None and extent_ranges is not None:
            x_range, y_range = extent_ranges
            self._plot.setRange(
                xRange=x_range,
                yRange=y_range,
                padding=0,
            )

        self._add_batched_segments(nav_segments)
        self._add_legend_preplot_segments(map_data)

        self._add_area_polygons(map_data)

        self._update_extent(map_data, nav_segments)

        if current_range is not None:
            self._plot.setRange(
                xRange=current_range[0],
                yRange=current_range[1],
                padding=0,
            )

        self._reposition_overlays()
        self._cached_signature = signature
