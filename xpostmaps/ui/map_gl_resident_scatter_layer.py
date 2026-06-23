"""GPU-resident scatter layer — full shotpoint detail, pan is transform-only."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from xpostmaps.ui.map_batch import shotpoint_marker_coords
from xpostmaps.ui.map_vector_dots import VectorDotsItem
from xpostmaps.utils.spatial_clip import clip_arrays_to_bbox
from xpostmaps.utils.vector_export import VectorExportContext, prepare_vector_scatter_geometry


_GL_UPLOADS_PER_TICK = 128
_EXPORT_DOT_SIZE_SCALE = 0.5


class ResidentGlScatterLayer:
    """Full-detail dotted shotpoints on GPU — no 40K screen cap."""

    _next_layer_id = 1

    def __init__(
        self,
        *,
        parts: list[tuple[np.ndarray, np.ndarray]],
        rgba: tuple[int, int, int, int],
        screen_size: float,
        export_size: float,
        map_layer: str = "postplot",
        plot_item: pg.PlotItem,
        gl_overlay,
        scatter_items: list[dict],
        plot_items: list[pg.GraphicsItem],
    ) -> None:
        self._layer_id = ResidentGlScatterLayer._next_layer_id
        ResidentGlScatterLayer._next_layer_id += 1
        self._parts = parts
        self._map_layer = map_layer
        self._rgba = rgba
        self._screen_size = screen_size
        self._export_size = export_size
        self._plot_item = plot_item
        self._gl_overlay = gl_overlay
        self._scatter_items = scatter_items
        self._plot_items = plot_items
        self._cpu_items: list[pg.GraphicsItem] = []
        self._export_mode = False
        self._visible = True
        self._gl_color = (
            rgba[0] / 255.0,
            rgba[1] / 255.0,
            rgba[2] / 255.0,
            rgba[3] / 255.0,
        )
        self._pending_runs = [
            index
            for index, (px, py) in enumerate(parts)
            if np.asarray(px).size >= 1
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
        xs, ys = shotpoint_marker_coords(self._parts)
        return xs, ys, self._rgba

    def upload_pending_batch(self) -> bool:
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
            marker_x, marker_y = shotpoint_marker_coords([(px, py)])
            if marker_x.size < 1:
                continue
            self._gl_overlay.add_scatter_run(
                self._layer_id,
                run_index,
                marker_x,
                marker_y,
                color=self._gl_color,
                size=self._screen_size,
            )
            self._uploaded_runs.add(run_index)
        self._gl_overlay.set_scatter_layer_visible(
            self._layer_id,
            self._visible and not self._export_mode,
        )
        return bool(self._pending_runs)

    def set_gl_visible(self, visible: bool) -> None:
        self._visible = visible
        if not self._export_mode:
            self._gl_overlay.set_scatter_layer_visible(self._layer_id, visible)

    def prepare_export(
        self,
        bbox: tuple[float, float, float, float],
        *,
        vector_ctx: VectorExportContext | None = None,
        pen_scale: float = 1.0,
        dot_budget: int | None = None,
    ) -> None:
        """Swap GPU scatter for crisp vector circles sized to match the screen."""
        self._export_mode = True
        self._gl_overlay.set_scatter_layer_visible(self._layer_id, False)
        self._clear_cpu_items()
        diameter_px = max(float(self._export_size) * _EXPORT_DOT_SIZE_SCALE, 1.25)
        if vector_ctx is not None:
            marker_x, marker_y = shotpoint_marker_coords(self._parts)
            cx, cy = prepare_vector_scatter_geometry(
                marker_x,
                marker_y,
                vector_ctx,
                symbol_px=diameter_px,
            )
        else:
            xs_chunks: list[np.ndarray] = []
            ys_chunks: list[np.ndarray] = []
            for px, py in self._parts:
                ax, ay = clip_arrays_to_bbox(
                    np.asarray(px, dtype=np.float64),
                    np.asarray(py, dtype=np.float64),
                    bbox,
                    kind="scatter",
                )
                if ax.size:
                    xs_chunks.append(ax)
                    ys_chunks.append(ay)
            if xs_chunks:
                cx = np.concatenate(xs_chunks)
                cy = np.concatenate(ys_chunks)
            else:
                cx = np.empty(0, dtype=np.float64)
                cy = np.empty(0, dtype=np.float64)
        if cx.size < 1:
            return
        dots_kwargs = {} if dot_budget is None else {"max_dots": int(dot_budget)}
        item = VectorDotsItem(
            cx,
            cy,
            color=self._rgba,
            diameter_px=diameter_px,
            **dots_kwargs,
        )
        self._plot_item.addItem(item)
        self._plot_items.append(item)
        self._cpu_items.append(item)

    def end_export(self) -> None:
        self._export_mode = False
        self._clear_cpu_items()
        self._gl_overlay.set_scatter_layer_visible(self._layer_id, self._visible)

    def _clear_cpu_items(self) -> None:
        for item in self._cpu_items:
            try:
                self._plot_item.removeItem(item)
            except Exception:  # noqa: BLE001
                pass
            if item in self._plot_items:
                self._plot_items.remove(item)
            self._scatter_items[:] = [
                rec for rec in self._scatter_items if rec.get("item") is not item
            ]
        self._cpu_items.clear()

    def clear(self) -> None:
        self._gl_overlay.clear_scatter_layer(self._layer_id)
        self._clear_cpu_items()
        self._pending_runs.clear()
        self._uploaded_runs.clear()
