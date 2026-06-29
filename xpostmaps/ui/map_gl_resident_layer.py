"""GPU-resident line layer — one GL strip per survey segment, pan is transform-only."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QPen

from xpostmaps.core.models import LineStyle
from xpostmaps.ui.map_batch import concat_polylines, normalize_line_style
from xpostmaps.ui.map_gl_overlay import MapGlLineOverlay
from xpostmaps.utils.spatial_clip import (
    SCREEN_OVERVIEW_BUDGET,
    clip_arrays_to_bbox,
    polyline_runs,
    screen_line_geometry,
)
from xpostmaps.utils.vector_export import (
    VectorExportContext,
    merge_line_parts,
    prepare_vector_line_geometry,
)


# Upload this many GL line strips per UI tick (legend apply stays responsive).
_GL_UPLOADS_PER_TICK = 128


def _bbox_intersects(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    ax0, ax1, ay0, ay1 = a
    bx0, bx1, by0, by1 = b
    return ax1 >= bx0 and ax0 <= bx1 and ay1 >= by0 and ay0 <= by1


def _run_bbox(
    rx: np.ndarray,
    ry: np.ndarray,
) -> tuple[float, float, float, float] | None:
    finite = np.isfinite(rx) & np.isfinite(ry)
    if not np.any(finite):
        return None
    return (
        float(np.min(rx[finite])),
        float(np.max(rx[finite])),
        float(np.min(ry[finite])),
        float(np.max(ry[finite])),
    )


class ResidentGlLineLayer:
    """Full-detail solid lines on GPU — no spatial tile grid on screen."""

    _next_layer_id = 1

    def __init__(
        self,
        *,
        parts: list[tuple[np.ndarray, np.ndarray]],
        color_parts: list[np.ndarray] | None = None,
        pen: QPen,
        export_pen: QPen,
        line_style: LineStyle = LineStyle.SOLID,
        dash_on_world: float = 0.0,
        dash_gap_world: float = 0.0,
        map_layer: str = "postplot",
        plot_item: pg.PlotItem,
        gl_overlay: MapGlLineOverlay,
        line_items: list[dict],
        plot_items: list[pg.GraphicsItem],
    ) -> None:
        self._layer_id = ResidentGlLineLayer._next_layer_id
        # Second overlay id holds the decimated overview LOD, toggled during motion.
        self._overview_layer_id = ResidentGlLineLayer._next_layer_id + 1
        ResidentGlLineLayer._next_layer_id += 2
        self._parts = parts
        self._color_parts = color_parts
        self._map_layer = map_layer
        index_x, index_y = concat_polylines(parts)
        self._index_x = index_x
        self._index_y = index_y
        self._pen = pen
        self._export_pen = export_pen
        self._line_style = normalize_line_style(line_style)
        self._dash_on_world = max(0.0, float(dash_on_world))
        self._dash_gap_world = max(0.0, float(dash_gap_world))
        self._dash_period = self._dash_on_world + self._dash_gap_world
        self._plot_item = plot_item
        self._gl_overlay = gl_overlay
        self._line_items = line_items
        self._plot_items = plot_items
        self._cpu_items: list[pg.PlotCurveItem] = []
        self._settle_cpu_items: list[pg.PlotCurveItem] = []
        self._export_mode = False
        self._visible = True
        self._motion_active = False
        self._has_overview = False
        rgba = pen.color()
        self._gl_color = (
            rgba.redF(),
            rgba.greenF(),
            rgba.blueF(),
            rgba.alphaF(),
        )
        self._gl_width = max(1.0, float(pen.widthF()))
        self._pending_runs = [
            index
            for index, (px, py) in enumerate(parts)
            if np.asarray(px).size >= 2
        ]
        self._uploaded_runs: set[int] = set()
        # Colored runs split one source polyline into several uniform-color GL
        # strips; each needs its own overlay key. Start past the source run
        # indices so the derived keys never collide with a plain run.
        self._next_gl_run_key = len(parts)

    @property
    def _baked_dash(self) -> bool:
        """Dash drawn as GPU-resident geometry (gaps baked into the vertices)."""
        return self._line_style == LineStyle.DASH and self._dash_period > 0.0

    def _dash_segments(
        self,
        px: np.ndarray,
        py: np.ndarray,
        colors: np.ndarray | None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None] | None:
        """Bake a world-space dash pattern into independent GL line segments.

        The "on" portions of the pattern become drawn segments; the gaps are
        simply omitted. Because the result is plain GPU geometry, pan/zoom stay
        transform-only (identical cost to a solid line) and the dash never
        collapses back to a solid stroke when the view settles.
        """
        n = px.size
        if n < 2:
            return None
        on_world = self._dash_on_world
        period = self._dash_period
        seg = np.hypot(np.diff(px), np.diff(py))
        s_start = np.empty(n - 1, dtype=np.float64)
        s_start[0] = 0.0
        if n > 2:
            np.cumsum(seg[:-1], out=s_start[1:])
        on_edge = np.mod(s_start, period) < on_world
        finite = (
            np.isfinite(px[:-1])
            & np.isfinite(py[:-1])
            & np.isfinite(px[1:])
            & np.isfinite(py[1:])
        )
        draw = on_edge & finite
        if not np.any(draw):
            return None
        x0 = px[:-1][draw]
        x1 = px[1:][draw]
        y0 = py[:-1][draw]
        y1 = py[1:][draw]
        xp = np.empty(x0.size * 2, dtype=np.float64)
        xp[0::2] = x0
        xp[1::2] = x1
        yp = np.empty(y0.size * 2, dtype=np.float64)
        yp[0::2] = y0
        yp[1::2] = y1
        color_pairs: np.ndarray | None = None
        if colors is not None and colors.shape[0] == n:
            edge_colors = colors[:-1][draw].astype(np.float32, copy=False)
            color_pairs = np.repeat(edge_colors, 2, axis=0)
        return xp, yp, color_pairs

    @staticmethod
    def _segment_gl_geometry(
        px: np.ndarray,
        py: np.ndarray,
        colors: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Expand a colored polyline into independent colored GL segments."""
        if px.size < 2 or colors.shape[0] != px.size:
            empty = np.empty(0, dtype=np.float64)
            return empty, empty, np.empty((0, 4), dtype=np.float32)
        finite = np.isfinite(px[:-1]) & np.isfinite(py[:-1]) & np.isfinite(px[1:]) & np.isfinite(py[1:])
        if not np.any(finite):
            empty = np.empty(0, dtype=np.float64)
            return empty, empty, np.empty((0, 4), dtype=np.float32)
        x_pairs = np.column_stack((px[:-1][finite], px[1:][finite])).reshape(-1)
        y_pairs = np.column_stack((py[:-1][finite], py[1:][finite])).reshape(-1)
        edge_colors = colors[:-1][finite].astype(np.float32, copy=False)
        color_pairs = np.repeat(edge_colors, 2, axis=0)
        return x_pairs, y_pairs, color_pairs

    @staticmethod
    def _colored_runs(
        px: np.ndarray,
        py: np.ndarray,
        colors: np.ndarray,
    ) -> list[tuple[np.ndarray, np.ndarray, tuple[float, float, float, float]]]:
        """Group consecutive line segments that share the same RGBA color."""
        if px.size < 2 or colors.shape[0] != px.size:
            return []
        runs: list[tuple[np.ndarray, np.ndarray, tuple[float, float, float, float]]] = []
        start: int | None = None
        active_color: tuple[float, float, float, float] | None = None
        for i in range(px.size - 1):
            if not (
                np.isfinite(px[i])
                and np.isfinite(py[i])
                and np.isfinite(px[i + 1])
                and np.isfinite(py[i + 1])
            ):
                if start is not None and active_color is not None and i + 1 - start >= 2:
                    runs.append((px[start : i + 1], py[start : i + 1], active_color))
                start = None
                active_color = None
                continue
            color = tuple(float(v) for v in colors[i])
            if start is None:
                start = i
                active_color = color
                continue
            if color != active_color:
                if i + 1 - start >= 2 and active_color is not None:
                    runs.append((px[start : i + 1], py[start : i + 1], active_color))
                start = i
                active_color = color
        if start is not None and active_color is not None and px.size - start >= 2:
            runs.append((px[start:], py[start:], active_color))
        return runs

    @property
    def layer_id(self) -> int:
        return self._layer_id

    @property
    def map_layer(self) -> str:
        return self._map_layer

    @property
    def has_vertex_colors(self) -> bool:
        return self._color_parts is not None

    @property
    def has_pending_uploads(self) -> bool:
        return bool(self._pending_runs)

    @property
    def overview_stroke(self) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
        rgba = self._pen.color()
        return (
            self._index_x,
            self._index_y,
            (rgba.red(), rgba.green(), rgba.blue(), rgba.alpha()),
        )

    @staticmethod
    def _expand_segment_pairs(
        px: np.ndarray,
        py: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Polyline -> GL_LINES vertex pairs, dropping pairs that touch NaN gaps."""
        if px.size < 2:
            return None
        finite = (
            np.isfinite(px[:-1])
            & np.isfinite(py[:-1])
            & np.isfinite(px[1:])
            & np.isfinite(py[1:])
        )
        if not np.any(finite):
            return None
        x0 = px[:-1][finite]
        x1 = px[1:][finite]
        y0 = py[:-1][finite]
        y1 = py[1:][finite]
        xp = np.empty(x0.size * 2, dtype=np.float64)
        xp[0::2] = x0
        xp[1::2] = x1
        yp = np.empty(y0.size * 2, dtype=np.float64)
        yp[0::2] = y0
        yp[1::2] = y1
        return xp, yp

    def _run_segments(
        self,
        px: np.ndarray,
        py: np.ndarray,
        colors: np.ndarray | None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None] | None:
        """Expand one polyline into GL_LINES vertex pairs (optionally colored)."""
        if self._baked_dash:
            return self._dash_segments(px, py, colors)
        if colors is not None and colors.shape[0] == px.size:
            xp, yp, cp = self._segment_gl_geometry(px, py, colors)
            if xp.size == 0:
                return None
            return xp, yp, cp
        pairs = self._expand_segment_pairs(px, py)
        if pairs is None:
            return None
        return pairs[0], pairs[1], None

    def upload_pending_batch(self) -> bool:
        """Upload ALL line runs as a single ``GLLinePlotItem`` (one draw call).

        pyqtgraph repaints each GL item with a fixed per-item Python/GL cost
        every frame, so one item per survey segment makes pan/zoom scale with
        the *number of segments* rather than the GPU's vertex throughput.
        Merging every run into one ``mode="lines"`` item (GL_LINES vertex pairs)
        collapses thousands of per-frame paint calls to one; per-vertex colors
        keep conditional layers identical without splitting into many strips.
        """
        if not self._pending_runs:
            return False
        x_chunks: list[np.ndarray] = []
        y_chunks: list[np.ndarray] = []
        want_colors = self._color_parts is not None
        color_chunks: list[np.ndarray] = []
        for run_index in self._pending_runs:
            if run_index in self._uploaded_runs:
                continue
            px, py = self._parts[run_index]
            px = np.asarray(px, dtype=np.float64)
            py = np.asarray(py, dtype=np.float64)
            if px.size < 2:
                continue
            colors = None
            if want_colors and self._color_parts is not None and run_index < len(
                self._color_parts
            ):
                candidate = np.asarray(self._color_parts[run_index], dtype=np.float32)
                if candidate.shape[0] == px.size:
                    colors = candidate
            seg = self._run_segments(px, py, colors)
            if seg is None:
                continue
            xp, yp, cp = seg
            x_chunks.append(xp)
            y_chunks.append(yp)
            if want_colors:
                if cp is None or cp.shape[0] != xp.size:
                    cp = np.empty((xp.size, 4), dtype=np.float32)
                    cp[:] = self._gl_color
                color_chunks.append(cp)
        self._uploaded_runs.update(self._pending_runs)
        self._pending_runs.clear()
        if not x_chunks:
            return False
        merged_x = np.concatenate(x_chunks)
        merged_y = np.concatenate(y_chunks)
        color_arg: tuple[float, float, float, float] | np.ndarray = self._gl_color
        if want_colors and color_chunks:
            merged_colors = np.concatenate(color_chunks, axis=0)
            if merged_colors.shape[0] == merged_x.size:
                color_arg = merged_colors
        self._gl_overlay.add_line_run(
            self._layer_id,
            0,
            merged_x,
            merged_y,
            color=color_arg,
            width=self._gl_width,
            mode="lines",
        )
        # Decimated drag preview (same 40K RDP overview LOD the CPU curve used),
        # uploaded once as a uniform-color GL_LINES item so motion stays
        # transform-only instead of redrawing full detail every frame.
        if self._index_x.size > SCREEN_OVERVIEW_BUDGET:
            ov_x, ov_y = screen_line_geometry(
                self._index_x, self._index_y, budget=SCREEN_OVERVIEW_BUDGET
            )
            if ov_x.size and ov_x.size < self._index_x.size:
                pairs = self._expand_segment_pairs(
                    np.asarray(ov_x, dtype=np.float64),
                    np.asarray(ov_y, dtype=np.float64),
                )
                if pairs is not None:
                    self._gl_overlay.add_line_run(
                        self._overview_layer_id,
                        0,
                        pairs[0],
                        pairs[1],
                        color=self._gl_color,
                        width=self._gl_width,
                        mode="lines",
                    )
                    self._has_overview = True
        self._apply_visibility()
        return False

    def _upload_uniform_run(
        self,
        run_key: int,
        px: np.ndarray,
        py: np.ndarray,
        color: tuple[float, float, float, float],
    ) -> None:
        """Upload one uniform-color polyline (solid line_strip or baked dash)."""
        px = np.asarray(px, dtype=np.float64)
        py = np.asarray(py, dtype=np.float64)
        if px.size < 2:
            return
        mode = "line_strip"
        if self._baked_dash:
            dashed = self._dash_segments(px, py, None)
            if dashed is None:
                return
            px, py, _ = dashed
            mode = "lines"
        self._gl_overlay.add_line_run(
            self._layer_id,
            run_key,
            px,
            py,
            color=color,
            width=self._gl_width,
            mode=mode,
        )

    def _apply_visibility(self) -> None:
        """Pick full-detail vs decimated overview item based on motion state."""
        if self._export_mode or self._settle_cpu_items:
            return
        show_overview = self._visible and self._motion_active and self._has_overview
        show_full = self._visible and not show_overview
        self._gl_overlay.set_layer_visible(self._layer_id, show_full)
        if self._has_overview:
            self._gl_overlay.set_layer_visible(self._overview_layer_id, show_overview)

    def set_gl_visible(self, visible: bool) -> None:
        self._visible = visible
        self._apply_visibility()

    def set_motion_overview(self, active: bool) -> None:
        """Swap to the decimated GL preview while dragging (transform-only)."""
        self._motion_active = active
        self._apply_visibility()

    def apply_settled_detail(
        self,
        bbox: tuple[float, float, float, float],
        *,
        zoomed_in: bool,
    ) -> None:
        """Dash lines use full-resolution CPU curves when zoomed in (GL cannot stipple).

        When the dash pattern is baked into the GL geometry there is nothing to
        do on settle: the resident layer already shows true gaps at GPU speed, so
        we keep it visible and skip the costly CPU curve rebuild entirely.
        """
        self.clear_settled_detail()
        if self._baked_dash:
            return
        if self._export_mode or self._line_style != LineStyle.DASH or not zoomed_in:
            return
        bx0, bx1, by0, by1 = bbox
        pad_x = max((bx1 - bx0) * 0.02, 1.0)
        pad_y = max((by1 - by0) * 0.02, 1.0)
        view_bbox = (bx0 - pad_x, bx1 + pad_x, by0 - pad_y, by1 + pad_y)
        self._gl_overlay.set_layer_visible(self._layer_id, False)
        if self._has_overview:
            self._gl_overlay.set_layer_visible(self._overview_layer_id, False)
        for run_index, (px, py) in enumerate(self._parts):
            px = np.asarray(px, dtype=np.float64)
            py = np.asarray(py, dtype=np.float64)
            run_bbox = _run_bbox(px, py)
            if run_bbox is None or not _bbox_intersects(run_bbox, view_bbox):
                continue
            colored_runs = []
            if self._color_parts is not None and run_index < len(self._color_parts):
                colored_runs = self._colored_runs(
                    px,
                    py,
                    np.asarray(self._color_parts[run_index], dtype=np.float32),
                )
            if not colored_runs:
                colored_runs = [(px, py, self._gl_color)]
            for rx, ry, color in colored_runs:
                cx, cy = clip_arrays_to_bbox(rx, ry, bbox, kind="line")
                if cx.size < 2:
                    continue
                pen = QPen(self._pen)
                pen_color = pen.color()
                pen_color.setRgbF(color[0], color[1], color[2], color[3])
                pen.setColor(pen_color)
                curve = pg.PlotCurveItem(
                    cx,
                    cy,
                    pen=pen,
                    connect="finite",
                    antialias=False,
                    skipFiniteCheck=True,
                )
                curve.setSegmentedLineMode("off")
                self._plot_item.addItem(curve)
                self._plot_items.append(curve)
                self._settle_cpu_items.append(curve)

    def clear_settled_detail(self) -> None:
        for item in self._settle_cpu_items:
            try:
                self._plot_item.removeItem(item)
            except Exception:  # noqa: BLE001
                pass
            if item in self._plot_items:
                self._plot_items.remove(item)
        self._settle_cpu_items.clear()
        self._apply_visibility()

    def _pdf_line_pen(self, pen_scale: float) -> QPen:
        """Screen-matched cosmetic width for vector PDF device coordinates."""
        pdf_pen = QPen(self._pen)
        pdf_pen.setWidthF(max(1.0, float(self._pen.widthF())) * pen_scale)
        pdf_pen.setCosmetic(True)
        return pdf_pen

    def prepare_export(
        self,
        bbox: tuple[float, float, float, float],
        *,
        vector_ctx: VectorExportContext | None = None,
        pen_scale: float = 1.0,
    ) -> None:
        """Swap to CPU curves for PDF/vector export (decimated at print resolution)."""
        self.clear_settled_detail()
        self._export_mode = True
        self._gl_overlay.set_layer_visible(self._layer_id, False)
        if self._has_overview:
            self._gl_overlay.set_layer_visible(self._overview_layer_id, False)
        self._clear_cpu_items()
        line_pen = self._export_pen
        if vector_ctx is not None:
            decimated_parts: list[tuple[np.ndarray, np.ndarray]] = []
            for px, py in self._parts:
                sx, sy = prepare_vector_line_geometry(
                    np.asarray(px, dtype=np.float64),
                    np.asarray(py, dtype=np.float64),
                    vector_ctx,
                )
                for rx, ry in polyline_runs(sx, sy):
                    if rx.size >= 2:
                        decimated_parts.append((rx, ry))
            if decimated_parts:
                lx, ly = merge_line_parts(decimated_parts)
                curve = pg.PlotCurveItem(
                    lx,
                    ly,
                    pen=line_pen,
                    connect="finite",
                    antialias=False,
                    skipFiniteCheck=True,
                )
                curve.setSegmentedLineMode("off")
                self._plot_item.addItem(curve)
                self._plot_items.append(curve)
                self._cpu_items.append(curve)
                self._line_items.append(
                    {
                        "item": curve,
                        "pen": self._pen,
                        "export_pen": self._export_pen,
                    }
                )
            return
        for px, py in self._parts:
            cx, cy = clip_arrays_to_bbox(
                np.asarray(px, dtype=np.float64),
                np.asarray(py, dtype=np.float64),
                bbox,
                kind="line",
            )
            if cx.size < 2:
                continue
            curve = pg.PlotCurveItem(
                cx,
                cy,
                pen=line_pen,
                connect="finite",
                antialias=False,
                skipFiniteCheck=True,
            )
            curve.setSegmentedLineMode("off")
            self._plot_item.addItem(curve)
            self._plot_items.append(curve)
            self._cpu_items.append(curve)
            self._line_items.append(
                {
                    "item": curve,
                    "pen": self._pen,
                    "export_pen": self._export_pen,
                }
            )

    def end_export(self) -> None:
        self._export_mode = False
        self._clear_cpu_items()
        self._apply_visibility()

    def _clear_cpu_items(self) -> None:
        for item in self._cpu_items:
            try:
                self._plot_item.removeItem(item)
            except Exception:  # noqa: BLE001
                pass
            if item in self._plot_items:
                self._plot_items.remove(item)
        self._cpu_items.clear()

    def set_pen(self, pen: QPen, *, export: bool = False) -> None:
        if export:
            self._export_pen = pen
        else:
            self._pen = pen
            rgba = pen.color()
            self._gl_color = (
                rgba.redF(),
                rgba.greenF(),
                rgba.blueF(),
                rgba.alphaF(),
            )
            self._gl_width = max(1.0, float(pen.widthF()))
        target = self._export_pen if export else self._pen
        for item in self._cpu_items:
            item.setPen(target)

    def clear(self) -> None:
        self.clear_settled_detail()
        self._gl_overlay.clear_layer(self._layer_id)
        self._gl_overlay.clear_layer(self._overview_layer_id)
        self._clear_cpu_items()
        self._pending_runs.clear()
        self._uploaded_runs.clear()
