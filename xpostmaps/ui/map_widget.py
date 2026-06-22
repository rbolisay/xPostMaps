"""PyQtGraph postplot map widget — plot area only (print white theme)."""

from __future__ import annotations

import math

import pyqtgraph as pg
import numpy as np
from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QRect, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF, QRegion
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsView, QVBoxLayout, QWidget

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
from xpostmaps.ui.map_batch import (
    LineBatchKey,
    concat_polylines,
    normalize_line_style,
    renders_as_scatter,
    shotpoint_marker_coords,
)
from xpostmaps.ui.map_view_box import MapViewBox
from xpostmaps.ui.map_clip_worker import MapClipWorker
from xpostmaps.ui.map_gl_overlay import MapGlLineOverlay
from xpostmaps.ui.map_gl_resident_layer import ResidentGlLineLayer
from xpostmaps.ui.map_gl_resident_scatter_layer import ResidentGlScatterLayer
from xpostmaps.ui.theme import (
    BG_MAP_PRINT,
    DOWN_LINE,
    OVERLAY_LINE,
    PREPLOT_LINE,
    SURVEY_BOUNDARY,
    TEXT_PRINT,
    UP_LINE,
)
from xpostmaps.utils.spatial_clip import (
    SpatialGridIndex,
    MOTION_SCATTER_BUDGET,
    MOTION_VIEW_ZOOM_RATIO,
    SCREEN_LINE_HARD_CAP,
    SCREEN_OVERVIEW_BUDGET,
    build_coarse_preview,
    clip_and_prepare_items,
    clip_arrays_to_bbox,
    clip_items_to_bbox,
    prepare_screen_clip_results,
    screen_line_budget_for_view,
    screen_line_geometry,
    screen_scatter_geometry,
)
from xpostmaps.utils.symbology_units import (
    PDF_EXPORT_DPI,
    migrate_dot_radius_mm,
    migrate_line_width_mm,
    scatter_size_px,
    mm_to_pixels,
    widget_screen_dpi,
)


def _configure_pyqtgraph() -> None:
    try:
        pg.setConfigOptions(antialias=False, useOpenGL=True, foreground=TEXT_PRINT)
    except Exception:  # noqa: BLE001
        pg.setConfigOptions(antialias=False, useOpenGL=False, foreground=TEXT_PRINT)


_configure_pyqtgraph()

# Items larger than this register for level-of-detail: the dense P111/P190 nav
# layers use QGIS-style coarse geometry during pan; full detail after settle.
_CLIP_REGISTER_MIN = 6_000
# Fraction of the visible span added as margin on every side when clipping so a
# short pan does not blank the line edges before the debounced reclip fires.
_CLIP_MARGIN = 0.6
# Faster restore after pan stops (still debounced through wheel bursts).
_CLIP_SETTLE_MS = 16
# QGIS-style motion LOD: shape-preserving RDP paths; layers hidden while panning.
_MOTION_LINE_BUDGET = MOTION_SCATTER_BUDGET
_MOTION_SCATTER_BUDGET = MOTION_SCATTER_BUDGET
# Settled view: overview uses the same cap as dotted scatter; zoomed-in allows more.
_SCREEN_LINE_HARD_CAP = SCREEN_LINE_HARD_CAP
_SCREEN_SCATTER_BUDGET = SCREEN_OVERVIEW_BUDGET
# PDF deliverables should use print-weight lines, not the heavier on-screen
# minimum needed for interactive visibility.
_EXPORT_LINE_WIDTH_SCALE = 0.35
_EXPORT_MIN_LINE_WIDTH = 0.25


def _color_with_opacity(color: str, opacity: float) -> tuple[int, int, int, int]:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, opacity)))
    return c.red(), c.green(), c.blue(), c.alpha()


def _make_nav_pen(
    rgba: tuple[int, int, int, int],
    width_mm: float,
    line_style: LineStyle,
    *,
    dpi: float,
) -> QPen:
    """Legend widths are millimeters on screen, like QGIS canvas symbology."""
    color = QColor(rgba[0], rgba[1], rgba[2], rgba[3])
    pen = QPen(color)
    pen.setWidthF(mm_to_pixels(dpi, width_mm))
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    style = normalize_line_style(line_style)
    pen.setStyle(
        Qt.PenStyle.DashLine if style == LineStyle.DASH else Qt.PenStyle.SolidLine
    )
    return pen


def _make_export_pen(
    rgba: tuple[int, int, int, int],
    width_mm: float,
    line_style: LineStyle,
) -> QPen:
    pen = _make_nav_pen(rgba, width_mm, line_style, dpi=PDF_EXPORT_DPI)
    export_pen = QPen(pen)
    export_pen.setWidthF(
        max(_EXPORT_MIN_LINE_WIDTH, pen.widthF() * _EXPORT_LINE_WIDTH_SCALE)
    )
    export_pen.setCosmetic(True)
    return export_pen


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
        self._origin_x = 0.0
        self._origin_y = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_coord_origin(self, origin_x: float, origin_y: float) -> None:
        self._origin_x = origin_x
        self._origin_y = origin_y

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
            text = _format_full_value(value + self._origin_x, spacing)
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
            text = _format_full_value(value + self._origin_y, spacing)
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
        self._origin_x = 0.0
        self._origin_y = 0.0
        self._suppress_view_changed = False
        self._plot_items: list[pg.GraphicsItem] = []
        self._line_items: list[dict] = []
        self._scatter_items: list[dict] = []
        # Preplot + navplan — hidden during pan/zoom; postplot stays on screen.
        self._preplot_navplan_items: list[pg.GraphicsItem] = []
        # Dense nav line items keep their full coordinate arrays here so the map
        # can paint only the portion inside the current view (fast pan/zoom on
        # million-point surveys) without the monotonic-x assumption that breaks
        # pyqtgraph's built-in clipToView for weaving survey lines.
        self._clip_items: list[dict] = []
        self._gl_line_layers: list[ResidentGlLineLayer] = []
        self._gl_scatter_layers: list[ResidentGlScatterLayer] = []
        self._overview_cpu_items: list[pg.GraphicsItem] = []
        self._overview_strokes: list[tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]] = []
        self._clip_bbox: tuple[float, float, float, float] | None = None
        # True while the user is actively panning/zooming; dense layers keep their
        # last clipped geometry on screen for a sharp, snappy interaction.
        self._interacting = False
        self._clip_worker = MapClipWorker(self)
        self._clip_worker.signals.finished.connect(self._on_clip_finished)
        self._clip_worker.signals.motion_prepared.connect(self._on_motion_prepared)
        self._motion_lod_generation = 0
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
        # SmartViewportUpdate: TierSeis found MinimalViewportUpdate leaves ghost
        # geometry when pyqtgraph does not mark the full viewport dirty on pan/zoom.
        self._plot.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self._plot.setOptimizationFlags(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing)
        self._plot.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        layout.addWidget(self._plot)

        self._gl_overlay = MapGlLineOverlay(self._plot, parent=self._plot)

        self._frame = MapFrameOverlay(self._plot, self._plot_item)
        self._frame_timer = QTimer(self)
        self._frame_timer.setSingleShot(True)
        self._frame_timer.setInterval(48)
        self._frame_timer.timeout.connect(self._frame.update)
        vb.sigRangeChanged.connect(self._schedule_frame_update)

        self._north = NorthArrow(self._plot)
        self._north.raise_()

        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.setInterval(32)
        self._overlay_timer.timeout.connect(self._reposition_overlays)
        QTimer.singleShot(0, self._reposition_overlays)

        self._clip_timer = QTimer(self)
        self._clip_timer.setSingleShot(True)
        # Settle delay: how long after the last pan/zoom event full detail is
        # restored. Long enough to ride through wheel-notch bursts and brief
        # pauses mid-drag, short enough to feel instant once the user stops.
        self._clip_timer.setInterval(_CLIP_SETTLE_MS)
        self._clip_timer.timeout.connect(self._apply_view_clip)
        self._gl_upload_timer = QTimer(self)
        self._gl_upload_timer.setSingleShot(True)
        self._gl_upload_timer.timeout.connect(self._apply_next_gl_upload)
        self._gl_settle_timer = QTimer(self)
        self._gl_settle_timer.setSingleShot(True)
        self._gl_settle_timer.setInterval(_CLIP_SETTLE_MS)
        self._gl_settle_timer.timeout.connect(self._on_gl_view_settled)
        self._pending_clip_bbox: tuple[float, float, float, float] | None = None
        self._pending_clip_layers: list[tuple[dict, tuple[np.ndarray, np.ndarray]]] = []
        self._pending_clip_layer_index = 0
        vb.sigRangeChanged.connect(self._on_view_range_changed)
        vb.sigRangeChangedManually.connect(self._emit_view_changed)

    def _screen_dpi(self) -> float:
        return widget_screen_dpi(self._plot)

    def _restore_screen_scatter_sizes(self) -> None:
        for rec in self._scatter_items:
            rec["item"].setSize(rec["screen_size"])

    def _apply_export_scatter_sizes(self) -> None:
        for rec in self._scatter_items:
            rec["item"].setSize(rec["export_size"])

    def _set_coord_origin(self, map_data: MapData | None) -> None:
        """Shift large projected coordinates near zero so polylines render solid."""
        if map_data is not None and map_data.bounds.is_valid:
            bounds = map_data.bounds
            self._origin_x = (bounds.xmin + bounds.xmax) * 0.5
            self._origin_y = (bounds.ymin + bounds.ymax) * 0.5
        else:
            self._origin_x = 0.0
            self._origin_y = 0.0
        self._frame.set_coord_origin(self._origin_x, self._origin_y)

    def _localize_array(self, xs, ys) -> tuple[np.ndarray, np.ndarray]:
        return (
            np.asarray(xs, dtype=np.float64) - self._origin_x,
            np.asarray(ys, dtype=np.float64) - self._origin_y,
        )

    @staticmethod
    def _localize_range(
        x_range: tuple[float, float],
        y_range: tuple[float, float],
        origin_x: float,
        origin_y: float,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        return (
            (x_range[0] - origin_x, x_range[1] - origin_x),
            (y_range[0] - origin_y, y_range[1] - origin_y),
        )

    @staticmethod
    def _world_range(
        x_range: tuple[float, float],
        y_range: tuple[float, float],
        origin_x: float,
        origin_y: float,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        return (
            (x_range[0] + origin_x, x_range[1] + origin_x),
            (y_range[0] + origin_y, y_range[1] + origin_y),
        )

    def set_display_mode(self, mode: DisplayMode) -> None:
        self._display_mode = mode
        self._cached_signature = None

    def set_legend(self, legend: LegendConfig) -> None:
        self._legend = legend
        self._cached_signature = None

    def prepare_for_export(self, *, full_detail: bool = True) -> None:
        """Refresh map overlays before PDF/raster capture.

        ``full_detail=True`` (real export) swaps in full-resolution visible
        geometry for crisp deliverables. ``full_detail=False`` (low-DPI preview)
        keeps the current screen geometry so opening/adjusting the export dialog
        stays snappy and never bogs the live map down with the full dataset.
        """
        if full_detail:
            self._gl_overlay.hide_for_export()
            for item in self._overview_cpu_items:
                item.setVisible(False)
            bbox = self._view_clip_bbox()
            if bbox is not None:
                for layer in self._gl_line_layers:
                    layer.prepare_export(bbox)
                for layer in self._gl_scatter_layers:
                    layer.prepare_export(bbox)
            self._restore_export_detail()
        else:
            self._restore_screen_pens()
            self._restore_screen_scatter_sizes()
        self._reposition_overlays()
        self._frame.update()
        self.repaint()

    def end_export(self) -> None:
        """Restore interactive screen detail and pens after a PDF/raster capture."""
        self._restore_screen_pens()
        self._restore_screen_scatter_sizes()
        self._clip_bbox = None
        for rec in self._clip_items:
            rec.pop("_clip_sig", None)
        if self._gl_overlay.available:
            self._gl_overlay.sync_geometry()
        bbox = self._view_clip_bbox()
        if bbox is not None:
            for layer in self._gl_line_layers:
                layer.end_export()
            for layer in self._gl_scatter_layers:
                layer.end_export()
            self._update_overview_visibility(bbox)
        if self._clip_items:
            self._apply_view_clip()

    def render_vector(self, painter: QPainter, target: QRectF) -> None:
        """Paint the map as scalable vector content into ``target`` (PDF export).

        The pyqtgraph scene (nav lines, axes, coordinate labels) is rendered as true
        vector paths/text; the zebra frame and north arrow are widget overlays drawn
        on top at the matching transform so the whole map stays sharp when zoomed.
        """
        self._restore_export_detail(use_export_pens=True)
        self._reposition_overlays()
        plot = self._plot
        scene = plot.scene()
        source = plot.mapToScene(plot.viewport().rect()).boundingRect()
        painter.save()
        try:
            scene.render(painter, target, source, Qt.AspectRatioMode.IgnoreAspectRatio)
        finally:
            painter.restore()
            self.end_export()

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
        self._line_items.clear()
        self._scatter_items.clear()
        self._preplot_navplan_items.clear()
        self._clip_items.clear()
        for layer in self._gl_line_layers:
            layer.clear()
        self._gl_line_layers.clear()
        for layer in self._gl_scatter_layers:
            layer.clear()
        self._gl_scatter_layers.clear()
        self._overview_cpu_items.clear()
        self._overview_strokes.clear()
        self._gl_overlay.clear()
        self._clip_bbox = None
        self._pending_clip_layers.clear()
        self._pending_clip_bbox = None
        self._pending_clip_layer_index = 0
        self._gl_upload_timer.stop()
        self._gl_settle_timer.stop()
        self._interacting = False
        self._motion_lod_generation += 1

    def _has_motion_lod_layers(self) -> bool:
        return (
            bool(self._preplot_navplan_items)
            or bool(self._clip_items)
            or bool(self._all_gl_layers())
        )

    @staticmethod
    def _is_reference_map_layer(map_layer: str) -> bool:
        return map_layer in ("preplot", "navplan")

    def _hide_reference_layers(self) -> None:
        """Hide preplot/navplan while the user pans or zooms."""
        for item in self._preplot_navplan_items:
            item.setVisible(False)
        for layer in self._gl_line_layers:
            if self._is_reference_map_layer(layer.map_layer):
                layer.clear_settled_detail()
                layer.set_gl_visible(False)
        for layer in self._gl_scatter_layers:
            if self._is_reference_map_layer(layer.map_layer):
                layer.set_gl_visible(False)

    def _show_reference_layers(self) -> None:
        """Restore preplot/navplan after pan/zoom settles."""
        for item in self._preplot_navplan_items:
            item.setVisible(True)
        bbox = self._view_clip_bbox()
        if bbox is None or not self._gl_layers_ready():
            for layer in self._all_gl_layers():
                if self._is_reference_map_layer(layer.map_layer):
                    layer.set_gl_visible(True)
            return
        overview = self._is_overview_zoom(bbox)
        zoomed_in = not overview
        for layer in self._gl_line_layers:
            if not self._is_reference_map_layer(layer.map_layer):
                continue
            if layer._line_style == LineStyle.DASH and zoomed_in:
                layer.apply_settled_detail(bbox, zoomed_in=True)
            else:
                layer.set_gl_visible(True)
        for layer in self._gl_scatter_layers:
            if self._is_reference_map_layer(layer.map_layer):
                layer.set_gl_visible(True)

    def _on_gl_view_settled(self) -> None:
        self._finish_pan_interaction()
        bbox = self._view_clip_bbox()
        if bbox is not None:
            self._refresh_settled_gl_detail(bbox)
        self._show_reference_layers()

    def _all_gl_layers(self) -> list[ResidentGlLineLayer | ResidentGlScatterLayer]:
        return [*self._gl_line_layers, *self._gl_scatter_layers]

    def _uses_gl_motion_path(self) -> bool:
        return bool(self._all_gl_layers()) and not self._clip_items

    def _gl_layers_ready(self) -> bool:
        layers = self._all_gl_layers()
        return bool(layers) and all(not layer.has_pending_uploads for layer in layers)

    def _refresh_settled_gl_detail(
        self,
        bbox: tuple[float, float, float, float],
    ) -> None:
        """Swap to full GPU detail after pan/zoom stops — pan itself stays transform-only."""
        self._update_overview_visibility(bbox)
        if not self._gl_overlay.available or not self._gl_layers_ready():
            self._frame.update()
            return
        zoomed_in = not self._is_overview_zoom(bbox)
        self._gl_overlay.set_viewport_cull(zoomed_in)
        for layer in self._gl_line_layers:
            layer.apply_settled_detail(bbox, zoomed_in=zoomed_in)
        self._gl_overlay.sync_geometry()
        view = self._gl_overlay._view
        if view is not None:
            view.update()
        self._frame.update()

    def _enter_gl_motion_mode(self) -> None:
        """Fast placeholder while dragging; full GPU detail restores on settle."""
        if not self._gl_layers_ready():
            return
        self._hide_reference_layers()
        for layer in self._gl_line_layers:
            layer.clear_settled_detail()
        bbox = self._view_clip_bbox()
        if bbox is not None and self._is_overview_zoom(bbox):
            for item in self._overview_cpu_items:
                item.setVisible(True)
            for layer in self._gl_line_layers:
                layer.set_gl_visible(False)
            for layer in self._gl_scatter_layers:
                layer.set_gl_visible(False)
            return
        self._gl_overlay.set_viewport_cull(False)
        for item in self._overview_cpu_items:
            item.setVisible(False)
        for layer in self._gl_line_layers:
            layer.set_gl_visible(True)
        for layer in self._gl_scatter_layers:
            layer.set_gl_visible(True)

    def _is_overview_zoom(
        self,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> bool:
        bbox = bbox or self._view_clip_bbox()
        if bbox is None or not self._overview_strokes:
            return False
        bx0, bx1, by0, by1 = bbox
        view_span = max(bx1 - bx0, by1 - by0, 1.0)
        xs = np.concatenate([s[0] for s in self._overview_strokes if s[0].size])
        ys = np.concatenate([s[1] for s in self._overview_strokes if s[1].size])
        finite = np.isfinite(xs) & np.isfinite(ys)
        if not np.any(finite):
            return False
        data_span = max(
            float(np.max(xs[finite]) - np.min(xs[finite])),
            float(np.max(ys[finite]) - np.min(ys[finite])),
            1.0,
        )
        return view_span >= data_span * MOTION_VIEW_ZOOM_RATIO

    def _update_overview_visibility(
        self,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> None:
        if not self._all_gl_layers() and not self._overview_cpu_items:
            return
        bbox = bbox or self._view_clip_bbox()
        # GPU holds full vertex detail once uploaded — never keep RDP overview on screen.
        if self._gl_layers_ready():
            for item in self._overview_cpu_items:
                item.setVisible(False)
            for layer in self._gl_line_layers:
                if self._interacting and self._is_reference_map_layer(layer.map_layer):
                    layer.set_gl_visible(False)
                else:
                    layer.set_gl_visible(True)
            for layer in self._gl_scatter_layers:
                if self._interacting and self._is_reference_map_layer(layer.map_layer):
                    layer.set_gl_visible(False)
                else:
                    layer.set_gl_visible(True)
            return
        overview = self._is_overview_zoom(bbox)
        for item in self._overview_cpu_items:
            item.setVisible(overview)
        for layer in self._gl_line_layers:
            layer.set_gl_visible(not overview and not layer.has_pending_uploads)
        for layer in self._gl_scatter_layers:
            layer.set_gl_visible(not overview and not layer.has_pending_uploads)

    def _start_gl_upload_pump(self) -> None:
        if not self._all_gl_layers():
            return
        self._gl_upload_timer.start(0)

    def _apply_next_gl_upload(self) -> None:
        pending = False
        for layer in self._all_gl_layers():
            if layer.has_pending_uploads:
                layer.upload_pending_batch()
                if layer.has_pending_uploads:
                    pending = True
        if pending:
            self._gl_upload_timer.start(0)
        else:
            bbox = self._view_clip_bbox()
            if bbox is not None:
                self._refresh_settled_gl_detail(bbox)
            else:
                self._frame.update()

    def _enter_motion_lod(self) -> None:
        """Keep line and scatter geometry on screen during pan."""
        self._hide_reference_layers()
        self._clip_worker.next_generation()
        self._pending_clip_layers.clear()
        self._pending_clip_bbox = None
        self._pending_clip_layer_index = 0
        for rec in self._clip_items:
            if rec.get("motion_active"):
                continue
            rec["motion_active"] = True
            item = rec["item"]
            item.setVisible(True)
            if rec["kind"] == "line":
                item.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    def _finish_pan_interaction(self) -> None:
        self._interacting = False
        viewport = self._plot.viewport()
        if viewport is not None:
            viewport.update()

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
            return OVERLAY_LINE, LineStyle.SOLID, 1.0, width_override or 0.35, 0.8
        if segment.record_type in (RecordType.PREPLOT, RecordType.NAVPLAN):
            return PREPLOT_LINE, LineStyle.SOLID, 1.0, width_override or 0.35, 0.8

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
        return default_color, LineStyle.SOLID, 1.0, width_override or 0.35, 0.8

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

    def _register_plot_item(self, item: pg.GraphicsItem, *, layer: str) -> None:
        self._plot_item.addItem(item)
        self._plot_items.append(item)
        if layer in ("preplot", "navplan"):
            self._preplot_navplan_items.append(item)

    def _add_batched_segments(
        self,
        segments: list[LineSegment],
        *,
        width_override: float | None = None,
        layer: str = "postplot",
    ) -> None:
        if not segments:
            return
        style_fn = self._style_fn_for_batch(width_override)
        batches: dict[LineBatchKey, list[tuple[np.ndarray, np.ndarray]]] = {}
        for segment in segments:
            if not segment.xs:
                continue
            color, line_style, opacity = style_fn(segment)
            line_style = normalize_line_style(line_style)
            rgba = _color_with_opacity(color, opacity)
            _, _, _, width, dot_radius = self._style_for_segment(
                segment,
                width_override=width_override,
            )
            key = LineBatchKey(
                color=rgba,
                line_style=line_style,
                width=width,
                dotted=renders_as_scatter(line_style),
                dot_radius=dot_radius,
            )
            xs = np.asarray(segment.xs, dtype=np.float64)
            ys = np.asarray(segment.ys, dtype=np.float64)
            batches.setdefault(key, []).append((xs, ys))

        for key, parts in batches.items():
            self._add_batch_item(
                key,
                parts,
                clipable=not key.dotted,
                layer=layer,
            )

    def _add_batch_item(
        self,
        key: LineBatchKey,
        parts: list[tuple[np.ndarray, np.ndarray]],
        *,
        clipable: bool = False,
        layer: str = "postplot",
    ) -> None:
        rgba = key.color
        line_style = normalize_line_style(key.line_style)
        if key.dotted:
            local_parts = [self._localize_array(xs, ys) for xs, ys in parts]
            xs, ys = shotpoint_marker_coords(local_parts)
            if xs.size == 0:
                return
            radius_mm = migrate_dot_radius_mm(key.dot_radius)
            screen_size = scatter_size_px(self._screen_dpi(), radius_mm)
            export_size = scatter_size_px(PDF_EXPORT_DPI, radius_mm)
            dense_gl_scatter = (
                layer in ("postplot", "navplan")
                and xs.size > _CLIP_REGISTER_MIN
                and self._gl_overlay.available
            )
            if dense_gl_scatter:
                overview_x, overview_y = screen_scatter_geometry(
                    xs, ys, budget=SCREEN_OVERVIEW_BUDGET
                )
                overview_scatter = pg.ScatterPlotItem(
                    overview_x,
                    overview_y,
                    pen=None,
                    brush=pg.mkBrush(rgba),
                    size=screen_size,
                    pxMode=True,
                    symbol="o",
                )
                self._register_plot_item(overview_scatter, layer=layer)
                self._overview_cpu_items.append(overview_scatter)
                self._overview_strokes.append((xs, ys, rgba))
                gl_layer = ResidentGlScatterLayer(
                    parts=local_parts,
                    rgba=rgba,
                    screen_size=screen_size,
                    export_size=export_size,
                    map_layer=layer,
                    plot_item=self._plot_item,
                    gl_overlay=self._gl_overlay,
                    scatter_items=self._scatter_items,
                    plot_items=self._plot_items,
                )
                self._gl_scatter_layers.append(gl_layer)
                self._start_gl_upload_pump()
                bbox = self._view_clip_bbox()
                if bbox is not None:
                    self._update_overview_visibility(bbox)
                return
            screen_x, screen_y = screen_scatter_geometry(
                xs, ys, budget=_SCREEN_SCATTER_BUDGET
            )
            item = pg.ScatterPlotItem(
                screen_x,
                screen_y,
                pen=None,
                brush=pg.mkBrush(rgba),
                size=screen_size,
                pxMode=True,
                symbol="o",
            )
            kind = "scatter"
            self._register_plot_item(item, layer=layer)
            self._scatter_items.append(
                {
                    "item": item,
                    "radius_mm": radius_mm,
                    "screen_size": screen_size,
                    "export_size": export_size,
                }
            )
            if (
                layer in ("postplot", "navplan")
                and xs.size > _CLIP_REGISTER_MIN
            ):
                coarse_x, coarse_y = build_coarse_preview(
                    xs, ys, max_points=_MOTION_SCATTER_BUDGET
                )
                self._clip_items.append(
                    {
                        "item": item,
                        "xs": xs,
                        "ys": ys,
                        "kind": "scatter",
                        "grid": SpatialGridIndex(xs, ys),
                        "layer": layer,
                        "coarse_xs": coarse_x,
                        "coarse_ys": coarse_y,
                        "motion_active": False,
                        "motion_lod_ready": True,
                    }
                )
            return

        width_mm = migrate_line_width_mm(key.width)
        pen = _make_nav_pen(rgba, width_mm, line_style, dpi=self._screen_dpi())
        local_parts: list[tuple[np.ndarray, np.ndarray]] = []
        for part_xs, part_ys in parts:
            lx, ly = self._localize_array(part_xs, part_ys)
            if lx.size >= 2:
                local_parts.append((lx, ly))
        if not local_parts:
            return
        if len(local_parts) == 1:
            lx, ly = local_parts[0]
        else:
            lx, ly = concat_polylines(local_parts)

        dense_gl_line = (
            clipable
            and layer in ("postplot", "navplan")
            and lx.size > _CLIP_REGISTER_MIN
            and line_style in (LineStyle.SOLID, LineStyle.DASH)
        )
        if dense_gl_line and self._gl_overlay.available:
            export_pen = _make_export_pen(rgba, width_mm, line_style)
            overview_x, overview_y = screen_line_geometry(
                lx,
                ly,
                budget=SCREEN_OVERVIEW_BUDGET,
            )
            overview_curve = pg.PlotCurveItem(
                overview_x,
                overview_y,
                pen=pen,
                connect="finite",
                antialias=False,
                skipFiniteCheck=True,
            )
            overview_curve.setSegmentedLineMode("off")
            self._register_plot_item(overview_curve, layer=layer)
            self._overview_cpu_items.append(overview_curve)
            self._overview_strokes.append((lx, ly, rgba))
            gl_layer = ResidentGlLineLayer(
                parts=local_parts,
                pen=pen,
                export_pen=export_pen,
                line_style=line_style,
                map_layer=layer,
                plot_item=self._plot_item,
                gl_overlay=self._gl_overlay,
                line_items=self._line_items,
                plot_items=self._plot_items,
            )
            self._gl_line_layers.append(gl_layer)
            self._start_gl_upload_pump()
            bbox = self._view_clip_bbox()
            if bbox is not None:
                self._update_overview_visibility(bbox)
            return

        display_budget = screen_line_budget_for_view(
            lx,
            ly,
            self._view_clip_bbox(),
        )
        clip_bbox = self._view_clip_bbox()
        if display_budget is None and clip_bbox is not None:
            display_x, display_y = clip_arrays_to_bbox(
                lx,
                ly,
                clip_bbox,
                kind="line",
            )
        elif display_budget is None:
            display_x, display_y = lx, ly
        else:
            display_x, display_y = screen_line_geometry(lx, ly, budget=display_budget)
        curve = pg.PlotCurveItem(
            pen=pen,
            connect="finite",
            antialias=False,
            skipFiniteCheck=True,
        )
        # Render as one connected path (single drawPath) rather than thousands of
        # individual line segments. With the round join this stays solid (no gap
        # artefacts) and is markedly cheaper to repaint while panning/zooming.
        curve.setSegmentedLineMode("off")
        self._register_plot_item(curve, layer=layer)
        self._line_items.append(
            {
                "item": curve,
                "pen": pen,
                "export_pen": _make_export_pen(rgba, width_mm, line_style),
            }
        )

        def _apply_line_geometry() -> None:
            curve.setData(display_x, display_y)

        if lx.size > _CLIP_REGISTER_MIN:
            QTimer.singleShot(0, _apply_line_geometry)
        else:
            _apply_line_geometry()
        if (
            clipable
            and layer in ("postplot", "navplan")
            and lx.size > _CLIP_REGISTER_MIN
        ):
            coarse_x, coarse_y = build_coarse_preview(
                lx, ly, max_points=_MOTION_LINE_BUDGET
            )
            self._clip_items.append(
                {
                    "item": curve,
                    "xs": lx,
                    "ys": ly,
                    "kind": "line",
                    "grid": SpatialGridIndex(lx, ly),
                    "layer": layer,
                    "coarse_xs": coarse_x,
                    "coarse_ys": coarse_y,
                    "motion_active": False,
                    "motion_lod_ready": False,
                }
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
        layer: str = "preplot",
    ) -> None:
        if not segments:
            return
        rgba = _color_with_opacity(color, opacity)
        line_style = normalize_line_style(line_style)
        key = LineBatchKey(
            color=rgba,
            line_style=line_style,
            width=width,
            dotted=renders_as_scatter(line_style),
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
            self._add_batch_item(key, parts, clipable=not key.dotted, layer=layer)

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
                layer="preplot",
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
                layer="navplan",
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
            lx, ly = self._localize_array(xs, ys)
            pen = _make_nav_pen(rgba, migrate_line_width_mm(entry.border_width), entry.border_style, dpi=self._screen_dpi())
            boundary = pg.PlotCurveItem(
                lx,
                ly,
                pen=pen,
                connect="all",
                antialias=False,
                skipFiniteCheck=True,
            )
            boundary.setSegmentedLineMode("off")
            self._plot_item.addItem(boundary)
            self._plot_items.append(boundary)
            self._line_items.append(
                {
                    "item": boundary,
                    "pen": pen,
                    "export_pen": _make_export_pen(
                        rgba,
                        migrate_line_width_mm(entry.border_width),
                        entry.border_style,
                    ),
                }
            )

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

    def _schedule_frame_update(self, *_args) -> None:
        if self._interacting:
            return
        self._frame_timer.start()

    def _swap_to_coarse_preview(self) -> None:
        """Stress-test hook — same path as interactive motion LOD."""
        self._enter_motion_lod()

    def _clear_pan_render_cache(self) -> None:
        for rec in self._clip_items:
            rec["motion_active"] = False
            rec["item"].setCacheMode(QGraphicsItem.CacheMode.NoCache)
            rec["item"].setVisible(True)

    def _view_clip_bbox(self) -> tuple[float, float, float, float] | None:
        vb = self._plot.getViewBox()
        if vb is None:
            return None
        (x0, x1), (y0, y1) = vb.viewRange()
        mx = (x1 - x0) * _CLIP_MARGIN
        my = (y1 - y0) * _CLIP_MARGIN
        return x0 - mx, x1 + mx, y0 - my, y1 + my

    @staticmethod
    def _should_skip_reclip(
        prev: tuple[float, float, float, float],
        bbox: tuple[float, float, float, float],
    ) -> bool:
        bx0, bx1, by0, by1 = bbox
        px0, px1, py0, py1 = prev
        return (
            px0 <= bx0
            and bx1 <= px1
            and py0 <= by0
            and by1 <= py1
            and (bx1 - bx0) >= (px1 - px0) * 0.5
            and (by1 - by0) >= (py1 - py0) * 0.5
        )

    def _apply_clipped_data(
        self,
        bbox: tuple[float, float, float, float],
        results: list[tuple[np.ndarray, np.ndarray]],
    ) -> None:
        for rec, (cx, cy) in zip(self._clip_items, results):
            sig = (bbox, int(cx.size))
            if rec.get("_clip_sig") == sig:
                rec["item"].setVisible(True)
                continue
            rec["_clip_sig"] = sig
            rec["item"].setData(cx, cy)
            rec["item"].setVisible(True)
        self._clear_pan_render_cache()

    def _sync_clip_to_bbox(
        self,
        bbox: tuple[float, float, float, float],
        *,
        for_export: bool = False,
    ) -> None:
        results = clip_items_to_bbox(self._clip_items, bbox)
        if not for_export:
            results = prepare_screen_clip_results(
                self._clip_items,
                results,
                bbox=bbox,
            )
        self._apply_clipped_data(bbox, results)

    def _submit_prepare_motion(self) -> None:
        """Precompute shape-preserving motion LOD off the UI thread."""
        if not self._clip_items:
            return
        if not any(rec.get("kind") == "line" for rec in self._clip_items):
            return
        self._motion_lod_generation += 1
        generation = self._motion_lod_generation
        self._clip_worker.submit_prepare_motion(generation, self._clip_items)

    def _on_motion_prepared(
        self,
        generation: int,
        results: object,
    ) -> None:
        if generation != self._motion_lod_generation:
            return
        if not isinstance(results, list):
            return
        for index, coarse_x, coarse_y in results:
            if index >= len(self._clip_items):
                continue
            rec = self._clip_items[index]
            rec["coarse_xs"] = coarse_x
            rec["coarse_ys"] = coarse_y
            rec["motion_lod_ready"] = True

    def _submit_screen_clip(self) -> None:
        """Refresh on-screen geometry off the UI thread (clip math only)."""
        if self._interacting or not self._clip_items:
            return
        bbox = self._view_clip_bbox()
        if bbox is None:
            return
        self._clip_bbox = bbox
        generation = self._clip_worker.next_generation()
        self._clip_worker.submit(generation, self._clip_items, bbox)

    def _on_view_range_changed(self, *_args) -> None:
        if self._gl_overlay.available:
            self._gl_overlay.sync_geometry()
        if self._uses_gl_motion_path():
            if not self._interacting:
                self._interacting = True
                self._enter_gl_motion_mode()
            else:
                self._hide_reference_layers()
            self._gl_settle_timer.start()
            return
        if not self._has_motion_lod_layers():
            return
        if not self._interacting:
            self._interacting = True
            self._hide_reference_layers()
        if self._clip_items:
            self._enter_motion_lod()
        else:
            self._hide_reference_layers()
        self._clip_timer.start()

    def _restore_export_detail(self, *, use_export_pens: bool = False) -> None:
        """Force full-resolution visible geometry for client PDF/vector output."""
        self._clip_timer.stop()
        self._finish_pan_interaction()
        self._clip_bbox = None
        for rec in self._line_items:
            rec["item"].setPen(rec["export_pen"] if use_export_pens else rec["pen"])
        if use_export_pens:
            self._apply_export_scatter_sizes()
        if not self._clip_items:
            return
        bbox = self._view_clip_bbox()
        if bbox is None:
            return
        self._clip_bbox = bbox
        self._sync_clip_to_bbox(bbox, for_export=True)

    def _restore_screen_pens(self) -> None:
        for rec in self._line_items:
            rec["item"].setPen(rec["pen"])

    def _on_clip_finished(
        self,
        generation: int,
        bbox: object,
        results: object,
    ) -> None:
        if generation != self._clip_worker.generation:
            return
        if self._interacting:
            return
        if not isinstance(bbox, tuple) or bbox != self._clip_bbox:
            return
        if not isinstance(results, list):
            return
        self._apply_clipped_data(bbox, results)
        self._frame.update()

    def _apply_view_clip(self) -> None:
        """End motion LOD; refresh full GPU detail on settle."""
        bbox = self._view_clip_bbox()
        self._finish_pan_interaction()
        if bbox is not None:
            if self._uses_gl_motion_path():
                self._refresh_settled_gl_detail(bbox)
            else:
                self._update_overview_visibility(bbox)
        self._show_reference_layers()
        if bbox is None or not self._clip_items:
            if bbox is not None:
                self._clip_bbox = bbox
            self._clear_pan_render_cache()
            self._frame.update()
            return

        prev = self._clip_bbox
        self._clip_bbox = bbox
        if prev is not None and self._should_skip_reclip(prev, bbox):
            self._clear_pan_render_cache()
            self._frame.update()
            return

        generation = self._clip_worker.next_generation()
        self._clip_worker.submit(generation, self._clip_items, bbox)

    def _schedule_overlay_reposition(self) -> None:
        self._overlay_timer.start()

    def _reposition_overlays(self) -> None:
        self._gl_overlay.sync_geometry()
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
        wx_range, wy_range = self._world_range((x0, x1), (y0, y1), self._origin_x, self._origin_y)
        return {
            "x_min": float(wx_range[0]),
            "x_max": float(wx_range[1]),
            "y_min": float(wy_range[0]),
            "y_max": float(wy_range[1]),
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
                local_x, local_y = self._localize_range(
                    x_range,
                    y_range,
                    self._origin_x,
                    self._origin_y,
                )
                vb = self._plot.getViewBox()
                vb.disableAutoRange()
                vb.setRange(xRange=local_x, yRange=local_y, padding=0, update=True)
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

        local_ranges = self._localize_range(
            ranges[0],
            ranges[1],
            self._origin_x,
            self._origin_y,
        )
        self._extent_x, self._extent_y = local_ranges
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
        current_world_range = None
        if self._plot_items:
            (x0, x1), (y0, y1) = vb.viewRange()
            current_world_range = self._world_range(
                (x0, x1),
                (y0, y1),
                self._origin_x,
                self._origin_y,
            )

        self.clear()
        if map_data is None:
            self._extent_x = None
            self._extent_y = None
            self._origin_x = 0.0
            self._origin_y = 0.0
            self._frame.set_coord_origin(0.0, 0.0)
            if isinstance(vb, MapViewBox):
                vb.set_extent_range(None, None)
            self._cached_signature = signature
            return

        self._set_coord_origin(map_data)

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

        self._add_batched_segments(nav_segments)
        self._add_legend_preplot_segments(map_data)
        self._add_legend_navplan_segments(map_data)

        self._add_area_polygons(map_data)

        self._update_extent(map_data, nav_segments)

        if current_world_range is not None:
            x_range, y_range = self._localize_range(
                current_world_range[0],
                current_world_range[1],
                self._origin_x,
                self._origin_y,
            )
            self._plot.setRange(
                xRange=x_range,
                yRange=y_range,
                padding=0,
            )
        elif extent_ranges is not None:
            x_range, y_range = self._localize_range(
                extent_ranges[0],
                extent_ranges[1],
                self._origin_x,
                self._origin_y,
            )
            self._plot.setRange(
                xRange=x_range,
                yRange=y_range,
                padding=0,
            )

        self._reposition_overlays()
        if self._all_gl_layers():
            bbox = self._view_clip_bbox()
            if bbox is not None:
                self._update_overview_visibility(bbox)
            self._start_gl_upload_pump()
        if self._clip_items:
            bbox = self._view_clip_bbox()
            if bbox is not None:
                self._clip_bbox = bbox
                QTimer.singleShot(0, self._submit_prepare_motion)
                QTimer.singleShot(0, self._submit_screen_clip)
        self._cached_signature = signature
