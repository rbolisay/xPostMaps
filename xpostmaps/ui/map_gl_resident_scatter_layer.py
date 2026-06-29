"""GPU-resident scatter layer — full shotpoint detail, pan is transform-only."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from xpostmaps.ui.map_batch import shotpoint_marker_coords
from xpostmaps.ui.map_vector_dots import VectorDotsItem
from xpostmaps.utils.spatial_clip import (
    SCREEN_OVERVIEW_BUDGET,
    clip_arrays_to_bbox,
    screen_scatter_geometry,
)
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
        color_parts: list[np.ndarray] | None = None,
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
        # Second overlay id holds the decimated overview LOD so its visibility can
        # be toggled independently of the full-detail item.
        self._overview_layer_id = ResidentGlScatterLayer._next_layer_id + 1
        ResidentGlScatterLayer._next_layer_id += 2
        self._parts = parts
        self._color_parts = color_parts
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
        self._motion_active = False
        self._has_overview = False
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
    def has_vertex_colors(self) -> bool:
        return self._color_parts is not None

    @property
    def has_pending_uploads(self) -> bool:
        return bool(self._pending_runs)

    @property
    def overview_stroke(self) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
        xs, ys = shotpoint_marker_coords(self._parts)
        return xs, ys, self._rgba

    def upload_pending_batch(self) -> bool:
        """Upload ALL shotpoints as a single GL scatter item (one draw call).

        pyqtgraph pays a fixed Python/GL cost per ``GLScatterPlotItem`` *every
        frame*; with one item per survey run that overhead (not the vertex
        count) dominates pan/zoom on dense surveys. Merging every run into one
        item collapses thousands of per-frame paint calls down to one while the
        uploaded vertex count — and therefore GPU memory — stays identical.
        """
        if not self._pending_runs:
            return False
        marker_x_chunks: list[np.ndarray] = []
        marker_y_chunks: list[np.ndarray] = []
        want_colors = self._color_parts is not None
        color_chunks: list[np.ndarray] = []
        for run_index in self._pending_runs:
            if run_index in self._uploaded_runs:
                continue
            px, py = self._parts[run_index]
            px = np.asarray(px, dtype=np.float64)
            py = np.asarray(py, dtype=np.float64)
            marker_x, marker_y = shotpoint_marker_coords([(px, py)])
            if marker_x.size < 1:
                continue
            marker_x_chunks.append(marker_x)
            marker_y_chunks.append(marker_y)
            if want_colors:
                run_colors: np.ndarray | None = None
                if self._color_parts is not None and run_index < len(self._color_parts):
                    colors = np.asarray(self._color_parts[run_index], dtype=np.float32)
                    finite = np.isfinite(px) & np.isfinite(py)
                    if colors.shape[0] == px.size:
                        run_colors = np.ascontiguousarray(colors[finite], dtype=np.float32)
                if run_colors is None or run_colors.shape[0] != marker_x.size:
                    run_colors = np.empty((marker_x.size, 4), dtype=np.float32)
                    run_colors[:] = self._gl_color
                color_chunks.append(run_colors)
        self._uploaded_runs.update(self._pending_runs)
        self._pending_runs.clear()
        if not marker_x_chunks:
            return False
        merged_x = np.concatenate(marker_x_chunks)
        merged_y = np.concatenate(marker_y_chunks)
        color_arg: tuple[float, float, float, float] | np.ndarray = self._gl_color
        if want_colors and color_chunks:
            merged_colors = np.concatenate(color_chunks, axis=0)
            if merged_colors.shape[0] == merged_x.size:
                color_arg = merged_colors
        self._gl_overlay.add_scatter_run(
            self._layer_id,
            0,
            merged_x,
            merged_y,
            color=color_arg,
            size=self._screen_size,
        )
        # Decimated drag preview (same 40K uniform-pick LOD the CPU overview used),
        # uploaded once as its own GPU-resident item so motion stays transform-only.
        overview_x, overview_y = screen_scatter_geometry(
            merged_x, merged_y, budget=SCREEN_OVERVIEW_BUDGET
        )
        if overview_x.size and overview_x.size < merged_x.size:
            self._gl_overlay.add_scatter_run(
                self._overview_layer_id,
                0,
                overview_x,
                overview_y,
                color=self._gl_color,
                size=self._screen_size,
            )
            self._has_overview = True
        self._apply_visibility()
        return False

    def _apply_visibility(self) -> None:
        """Pick full-detail vs decimated overview item based on motion state."""
        if self._export_mode:
            return
        show_overview = self._visible and self._motion_active and self._has_overview
        show_full = self._visible and not show_overview
        self._gl_overlay.set_scatter_layer_visible(self._layer_id, show_full)
        if self._has_overview:
            self._gl_overlay.set_scatter_layer_visible(self._overview_layer_id, show_overview)

    def set_gl_visible(self, visible: bool) -> None:
        self._visible = visible
        self._apply_visibility()

    def set_motion_overview(self, active: bool) -> None:
        """Swap to the decimated GL preview while dragging (transform-only)."""
        self._motion_active = active
        self._apply_visibility()

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
        if self._has_overview:
            self._gl_overlay.set_scatter_layer_visible(self._overview_layer_id, False)
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
        self._apply_visibility()

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
        self._gl_overlay.clear_scatter_layer(self._overview_layer_id)
        self._clear_cpu_items()
        self._pending_runs.clear()
        self._uploaded_runs.clear()
