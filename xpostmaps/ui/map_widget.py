"""PyQtGraph postplot map widget — plot area only (print white theme)."""

from __future__ import annotations

import math

import pyqtgraph as pg
import numpy as np
from PySide6.QtCore import Qt, QTimer, QPoint, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF, QRegion
from PySide6.QtWidgets import QGraphicsView, QVBoxLayout, QWidget

from xpostmaps.core.area_utils import resolve_area_polygon
from xpostmaps.core.navplan_catalog_utils import (
    resolve_navplan_file_order,
    segments_for_navplan_source,
)
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
    NavplanLegendEntry,
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

_MAX_LINE_POINTS = 500_000
_MAX_SCATTER_POINTS = 200_000
# Only items larger than this are worth view-clipping; below it the overhead is
# not worth the extra bookkeeping.
_CLIP_REGISTER_MIN = 20_000
# Fraction of the visible span added as margin on every side when clipping so a
# short pan does not blank the line edges before the debounced reclip fires.
_CLIP_MARGIN = 0.6
# Max vertices kept per nav item for the current view. Above this, points are
# sub-pixel dense so decimating is visually lossless but much faster to paint.
_CLIP_TARGET_POINTS = 90_000


def _color_with_opacity(color: str, opacity: float) -> tuple[int, int, int, int]:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, opacity)))
    return c.red(), c.green(), c.blue(), c.alpha()


def _thin_points_for_scatter(
    xs: np.ndarray,
    ys: np.ndarray,
    max_points: int = _MAX_SCATTER_POINTS,
) -> tuple[np.ndarray, np.ndarray]:
    if xs.size <= max_points:
        return xs, ys
    stride = max(1, int(np.ceil(xs.size / max_points)))
    return xs[::stride], ys[::stride]


def _thin_polyline_for_navigation(
    xs: np.ndarray,
    ys: np.ndarray,
    max_points: int = _MAX_LINE_POINTS,
) -> tuple[np.ndarray, np.ndarray]:
    if xs.size <= max_points:
        return xs, ys
    finite = np.isfinite(xs) & np.isfinite(ys)
    finite_count = int(np.count_nonzero(finite))
    if finite_count <= max_points:
        return xs, ys
    stride = max(1, int(np.ceil(finite_count / max_points)))
    keep = ~finite
    finite_indices = np.flatnonzero(finite)
    keep[finite_indices[::stride]] = True
    return xs[keep], ys[keep]


class NorthArrow(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(56, 78)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import QPointF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setPen(QPen(QColor(TEXT_PRINT), 1))
        font = QFont("Segoe UI", 14, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(0, 0, self.width(), 22, Qt.AlignmentFlag.AlignCenter, "N")

        main = QPolygonF(
            [
                QPointF(30, 24),
                QPointF(48, 70),
                QPointF(30, 56),
                QPointF(22, 70),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#050505"))
        painter.drawPolygon(main)

        hatch = QPolygonF(
            [
                QPointF(27, 26),
                QPointF(8, 70),
                QPointF(24, 58),
            ]
        )
        painter.setBrush(QColor("#7a7a7a"))
        painter.drawPolygon(hatch)

        painter.setPen(QPen(QColor("#f5f5f5"), 1))
        for offset in range(0, 17, 3):
            painter.drawLine(24 - offset // 3, 31 + offset, 10 + offset // 4, 68)
        painter.end()


_FRAME_BAND = 8
_FRAME_BLACK = QColor("#000000")
_FRAME_WHITE = QColor("#ffffff")
# Reserved margin (px) for the rotated Northing labels on the left/right edges.
_FRAME_SIDE_MARGIN = 66
# Reserved margin (px) for the Easting labels on the top/bottom edges.
_FRAME_TOPBOT_MARGIN = 30


def _format_full_value(value: float, spacing: float) -> str:
    """Full coordinate value (e.g. 6990000) — never scientific notation."""
    places = 0
    if spacing and spacing > 0:
        places = max(0, int(math.ceil(-math.log10(spacing))))
    return f"{value:.{places}f}"


class MapFrameOverlay(QWidget):
    """QGIS-style zebra neatline drawn on top of the plot edges.

    Alternating black/white blocks switch colour at every major grid tick, so
    the frame stays aligned with the coordinate grid as the map is panned and
    zoomed. It is a transparent, mouse-through child of the plot widget.
    """

    def __init__(self, plot_widget: pg.PlotWidget, plot_item, parent=None) -> None:
        super().__init__(parent or plot_widget)
        self._plot = plot_widget
        self._plot_item = plot_item
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    @staticmethod
    def _major_ticks(axis, lo: float, hi: float, size: float) -> list[float]:
        try:
            levels = axis.tickValues(lo, hi, size)
        except Exception:  # noqa: BLE001
            return []
        if not levels:
            return []
        return [float(v) for v in levels[0][1]]

    def _plot_rect(self):
        vb = self._plot.getViewBox()
        if vb is None:
            return None
        scene_rect = vb.sceneBoundingRect()
        if scene_rect.width() <= 4 or scene_rect.height() <= 4:
            return None
        top_left = self._plot.mapFromScene(scene_rect.topLeft())
        bottom_right = self._plot.mapFromScene(scene_rect.bottomRight())
        return (
            float(top_left.x()),
            float(top_left.y()),
            float(bottom_right.x()),
            float(bottom_right.y()),
            vb,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import QRectF

        info = self._plot_rect()
        if info is None:
            return
        left, top, right, bottom, vb = info
        try:
            (x0, x1), (y0, y1) = vb.viewRange()
        except Exception:  # noqa: BLE001
            return
        if x1 <= x0 or y1 <= y0 or right <= left or bottom <= top:
            return

        width = right - left
        height = bottom - top
        x_ticks = self._major_ticks(
            self._plot_item.getAxis("bottom"), x0, x1, width
        )
        y_ticks = self._major_ticks(
            self._plot_item.getAxis("left"), y0, y1, height
        )

        def px(value: float) -> float:
            return left + (value - x0) / (x1 - x0) * width

        def py(value: float) -> float:
            return bottom - (value - y0) / (y1 - y0) * height

        x_bounds = [left]
        x_bounds += sorted(p for v in x_ticks if left < (p := px(v)) < right)
        x_bounds.append(right)
        y_bounds = [top]
        y_bounds += sorted(p for v in y_ticks if top < (p := py(v)) < bottom)
        y_bounds.append(bottom)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)

        band = float(_FRAME_BAND)
        # Horizontal edges (top + bottom) span the full width.
        for i in range(len(x_bounds) - 1):
            colour = _FRAME_BLACK if i % 2 == 0 else _FRAME_WHITE
            x_a = x_bounds[i]
            seg_w = x_bounds[i + 1] - x_a
            painter.fillRect(QRectF(x_a, top, seg_w, band), colour)
            painter.fillRect(QRectF(x_a, bottom - band, seg_w, band), colour)

        # Vertical edges (left + right) fill only the middle so the corners
        # belong cleanly to the horizontal bands.
        inner_top = top + band
        inner_bottom = bottom - band
        v_bounds = [inner_top]
        v_bounds += [p for p in y_bounds if inner_top < p < inner_bottom]
        v_bounds.append(inner_bottom)
        for i in range(len(v_bounds) - 1):
            colour = _FRAME_BLACK if i % 2 == 0 else _FRAME_WHITE
            y_a = v_bounds[i]
            seg_h = v_bounds[i + 1] - y_a
            painter.fillRect(QRectF(left, y_a, band, seg_h), colour)
            painter.fillRect(QRectF(right - band, y_a, band, seg_h), colour)

        pen = QPen(_FRAME_BLACK, 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(left, top, width, height))
        painter.drawRect(
            QRectF(left + band, top + band, width - 2 * band, height - 2 * band)
        )

        self._draw_side_labels(painter, left, right, top, bottom, y_ticks, py)
        self._draw_easting_labels(painter, left, right, top, bottom, x_ticks, px)
        painter.end()

    def _draw_easting_labels(self, painter, left, right, top, bottom, x_ticks, px):
        """Easting labels drawn horizontally in the top/bottom margins."""
        if not x_ticks:
            return
        from PySide6.QtCore import QRectF

        ordered = sorted(x_ticks)
        spacing = abs(ordered[1] - ordered[0]) if len(ordered) >= 2 else 0.0
        painter.setPen(QPen(QColor(TEXT_PRINT), 1))
        painter.setFont(QFont("Segoe UI", 8))
        top_cy = top / 2.0
        bottom_cy = (bottom + self.height()) / 2.0
        for value in x_ticks:
            cx = px(value)
            if not (left < cx < right):
                continue
            text = _format_full_value(value, spacing)
            for cy in (top_cy, bottom_cy):
                painter.drawText(
                    QRectF(cx - 60, cy - 10, 120, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )

    def _draw_side_labels(self, painter, left, right, top, bottom, y_ticks, py):
        """Northing labels rotated 90° (parallel to the side borders)."""
        if not y_ticks:
            return
        ordered = sorted(y_ticks)
        spacing = abs(ordered[1] - ordered[0]) if len(ordered) >= 2 else 0.0

        painter.setPen(QPen(QColor(TEXT_PRINT), 1))
        painter.setFont(QFont("Segoe UI", 8))
        left_cx = left / 2.0
        right_cx = (right + self.width()) / 2.0
        for value in y_ticks:
            cy = py(value)
            if not (top < cy < bottom):
                continue
            text = _format_full_value(value, spacing)
            self._draw_vertical_text(painter, left_cx, cy, text)
            self._draw_vertical_text(painter, right_cx, cy, text)

    @staticmethod
    def _draw_vertical_text(painter, cx: float, cy: float, text: str) -> None:
        from PySide6.QtCore import QRectF

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(-90)
        painter.drawText(
            QRectF(-60, -10, 120, 20),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )
        painter.restore()


class PostplotMapWidget(QWidget):
    """High-performance map canvas — survey plot area only."""

    view_changed = Signal(dict)

    _NAV_TYPES = frozenset({RecordType.SOURCE, RecordType.VESSEL})

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._display_mode = DisplayMode.LINES
        self._legend = LegendConfig.default()
        self._suppress_view_changed = False
        self._plot_items: list[pg.GraphicsItem] = []
        # Dense nav line items keep their full coordinate arrays here so the map
        # can paint only the portion inside the current view (fast pan/zoom on
        # million-point surveys) without the monotonic-x assumption that breaks
        # pyqtgraph's built-in clipToView for weaving survey lines.
        self._clip_items: list[dict] = []
        self._clip_bbox: tuple[float, float, float, float] | None = None
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

        # Coordinate labels on all four sides (full values, no grid), matching a
        # printed survey map. The zebra neatline and the rotated Northing labels
        # are drawn by MapFrameOverlay.
        for axis in ("bottom", "left", "top", "right"):
            self._plot.showAxis(axis)
            ax = self._plot_item.getAxis(axis)
            # Transparent pen: the zebra neatline (MapFrameOverlay) is the real border,
            # so pyqtgraph's axis baseline/ticks must not draw — otherwise they appear as
            # thin "ruler" lines just inside the frame in the vector PDF.
            ax.setPen(pg.mkPen(None))
            ax.setTextPen(pg.mkPen(TEXT_PRINT))
            ax.setZValue(0.5)
            ax.enableAutoSIPrefix(False)

        # Easting (horizontal) labels are drawn by MapFrameOverlay (same as the
        # northing labels) so they render identically on screen and in the vector PDF.
        # pyqtgraph's own axis text is hidden because, as a scene item, it inherits the
        # PDF painter's point-size font and balloons ~6× on a high-DPI page; the overlay
        # is rendered in widget coordinates and stays correctly sized. The axis height is
        # still reserved so the labels sit in the margin outside the neatline.
        for axis in ("bottom", "top"):
            ax = self._plot_item.getAxis(axis)
            ax.setStyle(showValues=False)
            ax.setHeight(_FRAME_TOPBOT_MARGIN)

        # Northing (vertical) labels: hidden here and redrawn rotated by the
        # overlay; reserve margin width so they sit outside the frame.
        for axis in ("left", "right"):
            ax = self._plot_item.getAxis(axis)
            ax.setStyle(showValues=False)
            ax.setWidth(_FRAME_SIDE_MARGIN)

        vb = self._plot.getViewBox()
        vb.setBackgroundColor(BG_MAP_PRINT)
        vb.enableAutoRange(False)
        vb.setMouseEnabled(x=True, y=True)
        self._plot.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        layout.addWidget(self._plot)

        self._frame = MapFrameOverlay(self._plot, self._plot_item)
        vb.sigRangeChanged.connect(lambda *_a: self._frame.update())

        self._north = NorthArrow(self._plot)
        self._north.raise_()

        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.setInterval(32)
        self._overlay_timer.timeout.connect(self._reposition_overlays)
        QTimer.singleShot(0, self._reposition_overlays)

        self._clip_timer = QTimer(self)
        self._clip_timer.setSingleShot(True)
        self._clip_timer.setInterval(45)
        self._clip_timer.timeout.connect(self._apply_view_clip)
        vb.sigRangeChanged.connect(self._on_view_range_changed)
        vb.sigRangeChangedManually.connect(self._emit_view_changed)

    def set_display_mode(self, mode: DisplayMode) -> None:
        self._display_mode = mode
        self._cached_signature = None

    def set_legend(self, legend: LegendConfig) -> None:
        self._legend = legend
        self._cached_signature = None

    def prepare_for_export(self) -> None:
        """Refresh map overlays before PDF/raster capture."""
        self._reposition_overlays()
        self._frame.update()
        self.repaint()

    def render_vector(self, painter: QPainter, target: QRectF) -> None:
        """Paint the map as scalable vector content into ``target`` (PDF export).

        The pyqtgraph scene (nav lines, axes, coordinate labels) is rendered as true
        vector paths/text; the zebra frame and north arrow are widget overlays drawn
        on top at the matching transform so the whole map stays sharp when zoomed.
        """
        self._reposition_overlays()
        plot = self._plot
        scene = plot.scene()
        source = plot.mapToScene(plot.viewport().rect()).boundingRect()
        painter.save()
        scene.render(painter, target, source, Qt.AspectRatioMode.IgnoreAspectRatio)
        painter.restore()

        plot_w = max(plot.width(), 1)
        plot_h = max(plot.height(), 1)
        sx = target.width() / plot_w
        sy = target.height() / plot_h
        for overlay in (self._frame, self._north):
            if overlay is None or not overlay.isVisible():
                continue
            ow = max(overlay.width(), 1)
            oh = max(overlay.height(), 1)
            painter.save()
            painter.translate(target.x() + overlay.x() * sx, target.y() + overlay.y() * sy)
            painter.scale((ow * sx) / ow, (oh * sy) / oh)
            QWidget.render(
                overlay,
                painter,
                QPoint(0, 0),
                QRegion(overlay.rect()),
                QWidget.RenderFlag.DrawWindowBackground | QWidget.RenderFlag.DrawChildren,
            )
            painter.restore()

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
        self._clip_items.clear()
        self._clip_bbox = None

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
            self._add_batch_item(key, parts, clipable=True)

    def _add_batch_item(
        self,
        key: LineBatchKey,
        parts: list[tuple[np.ndarray, np.ndarray]],
        *,
        clipable: bool = False,
    ) -> None:
        rgba = key.color
        if key.dotted:
            xs, ys = concat_points(parts)
            if xs.size == 0:
                return
            xs, ys = _thin_points_for_scatter(xs, ys)
            item = pg.ScatterPlotItem(
                xs,
                ys,
                pen=None,
                brush=pg.mkBrush(rgba),
                size=max(1.0, key.dot_radius * 2.0),
                pxMode=True,
                symbol="o",
            )
            kind = "scatter"
        else:
            xs, ys = concat_polylines(parts)
            if xs.size == 0:
                return
            xs, ys = _thin_polyline_for_navigation(xs, ys)
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
            kind = "line"

        self._plot_item.addItem(item)
        self._plot_items.append(item)

        # Register dense nav items for view-dependent clipping. Worth it only
        # above a threshold; small/sparse layers (preplot, areas) stay fully
        # drawn so long straight segments never disappear at the view edge.
        if clipable and xs.size > _CLIP_REGISTER_MIN:
            self._clip_items.append(
                {"item": item, "xs": xs, "ys": ys, "kind": kind}
            )

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

    def _add_legend_navplan_segments(self, map_data: MapData | None) -> None:
        if map_data is None or not map_data.navplan_segments:
            return
        file_paths = resolve_navplan_file_order(map_data)
        for entry in self._legend.navplan_lines:
            if entry.hidden:
                continue
            # Navplans are only drawn when explicitly selected for this legend row
            # (individually or by group via "Select Navplans"). No selection = nothing.
            source_indices = entry.navplan_source_indices
            segments: list[LineSegment] = []
            for source_index in source_indices:
                segments.extend(
                    segments_for_navplan_source(
                        map_data.navplan_segments,
                        file_paths,
                        source_index,
                    )
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
            self._plot_item.addItem(boundary)
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
        self._plot_item.addItem(boundary)
        self._plot_items.append(boundary)

    def _on_view_range_changed(self, *_args) -> None:
        if self._clip_items:
            self._clip_timer.start()

    def _apply_view_clip(self) -> None:
        """Limit dense nav items to the points inside the (padded) view.

        Painting only what is on screen keeps pan/zoom fast on million-point
        surveys. A boolean mask is used (not pyqtgraph's clipToView) because
        survey lines are not monotonic in x; the padding keeps the cut off
        screen so lines look continuous.
        """
        if not self._clip_items:
            return
        vb = self._plot.getViewBox()
        (x0, x1), (y0, y1) = vb.viewRange()
        mx = (x1 - x0) * _CLIP_MARGIN
        my = (y1 - y0) * _CLIP_MARGIN
        bx0, bx1 = x0 - mx, x1 + mx
        by0, by1 = y0 - my, y1 + my

        prev = self._clip_bbox
        if prev is not None:
            px0, px1, py0, py1 = prev
            # Skip when the new padded box is essentially the same region (no
            # wasted reclip on tiny pans / re-emitted signals).
            if (
                px0 <= bx0
                and bx1 <= px1
                and py0 <= by0
                and by1 <= py1
                and (bx1 - bx0) >= (px1 - px0) * 0.5
                and (by1 - by0) >= (py1 - py0) * 0.5
            ):
                return
        self._clip_bbox = (bx0, bx1, by0, by1)

        for rec in self._clip_items:
            xs = rec["xs"]
            ys = rec["ys"]
            mask = (xs >= bx0) & (xs <= bx1) & (ys >= by0) & (ys <= by1)
            if rec["kind"] == "line":
                # Keep NaN separators so segment breaks survive the mask.
                np.logical_or(mask, np.isnan(xs), out=mask)
                cx = xs[mask]
                cy = ys[mask]
                # When the visible slice still has far more vertices than the
                # screen can resolve (e.g. fully zoomed out), decimate it. This
                # only triggers when points-per-pixel is high, so it is visually
                # lossless; zoomed-in slices stay below the cap and keep every
                # vertex.
                cx, cy = _thin_polyline_for_navigation(cx, cy, _CLIP_TARGET_POINTS)
            else:
                cx = xs[mask]
                cy = ys[mask]
                cx, cy = _thin_points_for_scatter(cx, cy, _CLIP_TARGET_POINTS)
            rec["item"].setData(cx, cy)

    def _schedule_overlay_reposition(self) -> None:
        self._overlay_timer.start()

    def _reposition_overlays(self) -> None:
        self._frame.setGeometry(0, 0, self._plot.width(), self._plot.height())
        self._frame.raise_()
        self._frame.update()

        inset = _FRAME_BAND + 8
        info = self._frame._plot_rect()
        if info is not None:
            left, top, right, bottom, _vb = info
            x = int(right - inset - self._north.width())
            y = int(top + inset)
        else:
            margin = 14
            x = self._plot.width() - self._north.width() - margin
            y = margin
        self._north.move(x, y)
        self._north.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reposition_overlays()

    def zoom_to_extent(self) -> None:
        vb = self._plot.getViewBox()
        if isinstance(vb, MapViewBox):
            vb.zoom_to_extent()

    def _emit_view_changed(self, *_args) -> None:
        if self._suppress_view_changed:
            return
        self.view_changed.emit(self.current_view())

    def current_view(self) -> dict[str, float]:
        (x0, x1), (y0, y1) = self._plot.getViewBox().viewRange()
        return {
            "x_min": float(x0),
            "x_max": float(x1),
            "y_min": float(y0),
            "y_max": float(y1),
        }

    @staticmethod
    def _valid_saved_view(
        view: dict | None,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if not isinstance(view, dict):
            return None
        try:
            x_min = float(view.get("x_min", 0.0))
            x_max = float(view.get("x_max", 0.0))
            y_min = float(view.get("y_min", 0.0))
            y_max = float(view.get("y_max", 0.0))
        except (TypeError, ValueError):
            return None
        if x_max <= x_min or y_max <= y_min:
            return None
        return (x_min, x_max), (y_min, y_max)

    def restore_view(self, view: dict | None) -> None:
        """Restore a saved view, falling back to the data extent when absent."""
        ranges = self._valid_saved_view(view)
        self._suppress_view_changed = True
        try:
            if ranges is None:
                self.zoom_to_extent()
            else:
                x_range, y_range = ranges
                vb = self._plot.getViewBox()
                vb.disableAutoRange()
                vb.setRange(xRange=x_range, yRange=y_range, padding=0, update=True)
        finally:
            self._suppress_view_changed = False

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

        navplan_paths = resolve_navplan_file_order(map_data)
        for entry in self._legend.navplan_lines:
            if entry.hidden:
                continue
            source_indices = entry.navplan_source_indices
            for source_index in source_indices:
                for segment in segments_for_navplan_source(
                    map_data.navplan_segments,
                    navplan_paths,
                    source_index,
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
            len(map_data.navplan_segments),
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
            tuple(
                (
                    entry.name,
                    tuple(entry.navplan_source_indices),
                    entry.navplan_filter_active,
                    entry.line_style.value,
                    entry.color,
                    entry.opacity,
                    entry.line_width,
                    entry.dot_radius,
                    entry.hidden,
                )
                for entry in self._legend.navplan_lines
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
        navplan_paths = resolve_navplan_file_order(map_data)
        visible_navplan = any(
            not entry.hidden
            and bool(
                [
                    segment
                    for source_index in entry.navplan_source_indices
                    for segment in segments_for_navplan_source(
                        map_data.navplan_segments,
                        navplan_paths,
                        source_index,
                    )
                ]
            )
            for entry in self._legend.navplan_lines
        )
        visible_areas = any(
            not entry.hidden
            and not is_imported_polygon(entry)
            and len(resolve_area_polygon(entry, map_data, self._legend.areas)[0]) >= 2
            for entry in self._legend.areas
        )
        has_nav = bool(nav_segments)

        if not has_nav and not visible_preplot and not visible_navplan and not visible_areas:
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
        self._add_legend_navplan_segments(map_data)

        self._add_area_polygons(map_data)

        self._update_extent(map_data, nav_segments)

        if current_range is not None:
            self._plot.setRange(
                xRange=current_range[0],
                yRange=current_range[1],
                padding=0,
            )

        self._reposition_overlays()
        if self._clip_items:
            self._apply_view_clip()
        self._cached_signature = signature
