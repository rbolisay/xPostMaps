"""GPU-resident line layer — one GL strip per survey segment, pan is transform-only."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QPen

from xpostmaps.core.models import LineStyle
from xpostmaps.ui.map_batch import concat_polylines, normalize_line_style
from xpostmaps.ui.map_gl_overlay import MapGlLineOverlay
from xpostmaps.utils.spatial_clip import clip_arrays_to_bbox, polyline_runs
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
        pen: QPen,
        export_pen: QPen,
        line_style: LineStyle = LineStyle.SOLID,
        map_layer: str = "postplot",
        plot_item: pg.PlotItem,
        gl_overlay: MapGlLineOverlay,
        line_items: list[dict],
        plot_items: list[pg.GraphicsItem],
    ) -> None:
        self._layer_id = ResidentGlLineLayer._next_layer_id
        ResidentGlLineLayer._next_layer_id += 1
        self._parts = parts
        self._map_layer = map_layer
        index_x, index_y = concat_polylines(parts)
        self._index_x = index_x
        self._index_y = index_y
        self._pen = pen
        self._export_pen = export_pen
        self._line_style = normalize_line_style(line_style)
        self._plot_item = plot_item
        self._gl_overlay = gl_overlay
        self._line_items = line_items
        self._plot_items = plot_items
        self._cpu_items: list[pg.PlotCurveItem] = []
        self._settle_cpu_items: list[pg.PlotCurveItem] = []
        self._export_mode = False
        self._visible = True
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

    @property
    def layer_id(self) -> int:
        return self._layer_id

    @property
    def map_layer(self) -> str:
        return self._map_layer

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

    def upload_pending_batch(self) -> bool:
        """Upload the next batch of line strips to GL. Returns True if more remain."""
        if not self._pending_runs:
            return False
        batch = self._pending_runs[:_GL_UPLOADS_PER_TICK]
        del self._pending_runs[: len(batch)]
        for run_index in batch:
            if run_index in self._uploaded_runs:
                continue
            px, py = self._parts[run_index]
            px = np.asarray(px, dtype=np.float64)
            py = np.asarray(py, dtype=np.float64)
            if px.size < 2:
                continue
            self._gl_overlay.add_line_run(
                self._layer_id,
                run_index,
                px,
                py,
                color=self._gl_color,
                width=self._gl_width,
            )
            self._uploaded_runs.add(run_index)
        self._gl_overlay.set_layer_visible(self._layer_id, self._visible and not self._export_mode)
        return bool(self._pending_runs)

    def set_gl_visible(self, visible: bool) -> None:
        self._visible = visible
        if not self._export_mode and not self._settle_cpu_items:
            self._gl_overlay.set_layer_visible(self._layer_id, visible)

    def apply_settled_detail(
        self,
        bbox: tuple[float, float, float, float],
        *,
        zoomed_in: bool,
    ) -> None:
        """Dash lines use full-resolution CPU curves when zoomed in (GL cannot stipple)."""
        self.clear_settled_detail()
        if self._export_mode or self._line_style != LineStyle.DASH or not zoomed_in:
            return
        bx0, bx1, by0, by1 = bbox
        pad_x = max((bx1 - bx0) * 0.02, 1.0)
        pad_y = max((by1 - by0) * 0.02, 1.0)
        view_bbox = (bx0 - pad_x, bx1 + pad_x, by0 - pad_y, by1 + pad_y)
        self._gl_overlay.set_layer_visible(self._layer_id, False)
        for px, py in self._parts:
            px = np.asarray(px, dtype=np.float64)
            py = np.asarray(py, dtype=np.float64)
            run_bbox = _run_bbox(px, py)
            if run_bbox is None or not _bbox_intersects(run_bbox, view_bbox):
                continue
            cx, cy = clip_arrays_to_bbox(px, py, bbox, kind="line")
            if cx.size < 2:
                continue
            curve = pg.PlotCurveItem(
                cx,
                cy,
                pen=self._pen,
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
        if not self._export_mode:
            self._gl_overlay.set_layer_visible(self._layer_id, self._visible)

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
        self._gl_overlay.set_layer_visible(self._layer_id, self._visible)

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
        self._clear_cpu_items()
        self._pending_runs.clear()
        self._uploaded_runs.clear()
