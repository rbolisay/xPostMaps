"""Spatially tiled GPU-resident line layer — geometry uploaded once, pan is transform-only."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QPen

from xpostmaps.ui.map_gl_overlay import MapGlLineOverlay
from xpostmaps.ui.map_batch import concat_polylines
from xpostmaps.ui.map_tile_worker import MapTileWorker
from xpostmaps.utils.spatial_clip import (
    SpatialGridIndex,
    _TILE_TARGET_POINTS_PER_CELL,
    clip_arrays_to_bbox,
)
from xpostmaps.utils.spatial_tiles import (
    SpatialLineTile,
    _merge_clip_chunks,
    build_spatial_line_tile_vertex,
)

# Materialize this many new grid cells per UI tick (legend apply / initial load).
_TILE_KEYS_PER_TICK = 24


class TiledLineLayer:
    """Resident GL tile layer for dense postplot/navplan solid lines."""

    _next_layer_id = 1

    def __init__(
        self,
        *,
        parts: list[tuple[np.ndarray, np.ndarray]],
        pen: QPen,
        export_pen: QPen,
        plot_item: pg.PlotItem,
        gl_overlay: MapGlLineOverlay | None,
        use_gl: bool,
        line_items: list[dict],
        plot_items: list[pg.GraphicsItem],
        tile_worker: MapTileWorker | None = None,
    ) -> None:
        self._layer_id = TiledLineLayer._next_layer_id
        TiledLineLayer._next_layer_id += 1
        self._parts = parts
        index_x, index_y = concat_polylines(parts)
        self._index_x = index_x
        self._index_y = index_y
        self._pen = pen
        self._export_pen = export_pen
        self._plot_item = plot_item
        self._gl_overlay = gl_overlay
        self._tile_worker = tile_worker
        self._build_generation = 0
        self._use_gl = bool(
            use_gl
            and gl_overlay is not None
            and gl_overlay.available
        )
        self._line_items = line_items
        self._plot_items = plot_items
        self._grid = SpatialGridIndex(
            index_x,
            index_y,
            target_points_per_cell=_TILE_TARGET_POINTS_PER_CELL,
        )
        self._tiles_by_key: dict[tuple[int, int], SpatialLineTile] = {}
        self._cpu_items: dict[tuple[int, int], list[pg.PlotCurveItem]] = {}
        self._visible_keys: set[tuple[int, int]] = set()
        self._target_keys: set[tuple[int, int]] = set()
        self._pending_keys: list[tuple[int, int]] = []
        self._inflight_keys: set[tuple[int, int]] = set()
        self._export_mode = False
        rgba = pen.color()
        self._gl_color = (
            rgba.redF(),
            rgba.greenF(),
            rgba.blueF(),
            rgba.alphaF(),
        )
        self._gl_width = max(1.0, float(pen.widthF()))

    @property
    def layer_id(self) -> int:
        return self._layer_id

    @property
    def uses_gl(self) -> bool:
        return self._use_gl

    @property
    def has_pending_tiles(self) -> bool:
        return bool(self._pending_keys) or bool(self._inflight_keys)

    @property
    def overview_stroke(self) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
        """Full layer arrays + pen colour for overview raster bake."""
        rgba = self._pen.color()
        return (
            self._index_x,
            self._index_y,
            (rgba.red(), rgba.green(), rgba.blue(), rgba.alpha()),
        )

    def update_visibility(
        self,
        bbox: tuple[float, float, float, float],
        *,
        for_export: bool = False,
        incremental: bool = True,
    ) -> bool:
        """Update visible tiles. Returns True if more tiles remain (incremental mode)."""
        bx0, bx1, by0, by1 = bbox
        keys = self._grid.cell_keys_for_bbox(bx0, bx1, by0, by1, margin_cells=2)
        if for_export != self._export_mode:
            self._hide_all()
            self._visible_keys.clear()
            self._pending_keys.clear()
            self._inflight_keys.clear()
            self._export_mode = for_export
            if not for_export:
                self._tiles_by_key.clear()
                if not self._use_gl:
                    self._cpu_items.clear()

        self._target_keys = keys
        for key in self._visible_keys - keys:
            self._hide_tile(key)
        self._visible_keys &= keys

        new_keys = [
            key
            for key in keys
            if key not in self._visible_keys
            and key not in self._inflight_keys
        ]
        if not incremental or for_export:
            for key in new_keys:
                self._show_tile(key, for_export=for_export)
                self._visible_keys.add(key)
            self._pending_keys.clear()
            return False

        for key in new_keys:
            if key not in self._pending_keys:
                self._pending_keys.append(key)
        return self._materialize_pending_batch(for_export=for_export)

    def materialize_pending(self, *, for_export: bool = False) -> bool:
        """Show the next batch of pending tiles. Returns True if more remain."""
        if not self._pending_keys and not self._inflight_keys:
            return False
        if self._inflight_keys:
            return True
        return self._materialize_pending_batch(for_export=for_export)

    def apply_built_tiles(
        self,
        generation: int,
        built: list[tuple[tuple[int, int], SpatialLineTile]],
    ) -> None:
        """Apply worker-built tiles (main thread only)."""
        if generation != self._build_generation:
            return
        for key, tile in built:
            self._inflight_keys.discard(key)
            if key not in self._target_keys:
                continue
            self._tiles_by_key[key] = tile
            self._upload_tile(key, tile)
            self._visible_keys.add(key)
        if self._gl_overlay is not None and self._use_gl:
            self._gl_overlay.sync_geometry()

    def _materialize_pending_batch(self, *, for_export: bool) -> bool:
        batch = self._pending_keys[:_TILE_KEYS_PER_TICK]
        del self._pending_keys[: len(batch)]
        if not batch:
            return bool(self._pending_keys)

        if (
            not for_export
            and self._use_gl
            and self._tile_worker is not None
        ):
            for key in batch:
                if key in self._target_keys:
                    self._inflight_keys.add(key)
            self._build_generation = self._tile_worker.next_generation()
            self._tile_worker.submit(
                self._build_generation,
                self._layer_id,
                batch,
                self._index_x,
                self._index_y,
            )
            return bool(self._pending_keys) or bool(self._inflight_keys)

        for key in batch:
            if key in self._target_keys:
                self._show_tile(key, for_export=for_export)
                self._visible_keys.add(key)
        return bool(self._pending_keys)

    def _hide_all(self) -> None:
        for key in list(self._visible_keys):
            self._hide_tile(key)
        self._visible_keys.clear()
        self._pending_keys.clear()
        self._inflight_keys.clear()

    def _hide_tile(self, key: tuple[int, int]) -> None:
        if self._use_gl and self._gl_overlay is not None and not self._export_mode:
            self._gl_overlay.set_tile_visible(self._layer_id, key, False)
            return
        for item in self._cpu_items.get(key, []):
            item.setVisible(False)

    def _show_tile(self, key: tuple[int, int], *, for_export: bool) -> None:
        tile = self._tile_data(key, for_export=for_export)
        if tile is None:
            return
        self._upload_tile(key, tile, for_export=for_export)

    def _upload_tile(
        self,
        key: tuple[int, int],
        tile: SpatialLineTile,
        *,
        for_export: bool = False,
    ) -> None:
        if self._use_gl and self._gl_overlay is not None and not for_export:
            for run_index, (rx, ry) in enumerate(tile.runs):
                self._gl_overlay.add_tile_run(
                    self._layer_id,
                    key,
                    run_index,
                    rx,
                    ry,
                    color=self._gl_color,
                    width=self._gl_width,
                )
            self._gl_overlay.set_tile_visible(self._layer_id, key, True)
            return

        if key not in self._cpu_items:
            self._cpu_items[key] = self._create_cpu_items(tile, for_export=for_export)
        pen = self._export_pen if for_export else self._pen
        for item in self._cpu_items[key]:
            item.setPen(pen)
            item.setVisible(True)

    def _tile_data(
        self,
        key: tuple[int, int],
        *,
        for_export: bool,
    ) -> SpatialLineTile | None:
        if not for_export and key in self._tiles_by_key:
            return self._tiles_by_key[key]
        if for_export:
            padding = max(self._grid.cell_size * 0.15, 1.0)
            bbox = self._grid.cell_bbox(key, padding=padding)
            chunks = []
            for px, py in self._parts:
                cx, cy = clip_arrays_to_bbox(
                    np.asarray(px, dtype=np.float64),
                    np.asarray(py, dtype=np.float64),
                    bbox,
                    kind="line",
                    grid=self._grid,
                )
                if cx.size >= 2:
                    chunks.append((cx, cy))
            if not chunks:
                return None
            merged = _merge_clip_chunks(chunks)
            if merged is None:
                return None
            cx, cy = merged
            return SpatialLineTile(key, bbox, cx, cy)

        tile = build_spatial_line_tile_vertex(
            self._index_x,
            self._index_y,
            self._grid,
            key,
        )
        if tile is not None:
            self._tiles_by_key[key] = tile
        return tile

    def _create_cpu_items(
        self,
        tile: SpatialLineTile,
        *,
        for_export: bool,
    ) -> list[pg.PlotCurveItem]:
        pen = self._export_pen if for_export else self._pen
        curve = pg.PlotCurveItem(
            tile.xs,
            tile.ys,
            pen=pen,
            connect="finite",
            antialias=False,
            skipFiniteCheck=True,
        )
        curve.setSegmentedLineMode("off")
        self._plot_item.addItem(curve)
        self._plot_items.append(curve)
        self._line_items.append(
            {
                "item": curve,
                "pen": self._pen,
                "export_pen": self._export_pen,
            }
        )
        return [curve]

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
        for items in self._cpu_items.values():
            for item in items:
                item.setPen(target)

    def set_gl_visible(self, visible: bool) -> None:
        if not self._use_gl or self._gl_overlay is None:
            return
        for key in self._visible_keys:
            self._gl_overlay.set_tile_visible(self._layer_id, key, visible)

    def clear(self) -> None:
        if self._use_gl and self._gl_overlay is not None:
            self._gl_overlay.clear_layer(self._layer_id)
        for items in self._cpu_items.values():
            for item in items:
                try:
                    self._plot_item.removeItem(item)
                except Exception:  # noqa: BLE001
                    pass
                if item in self._plot_items:
                    self._plot_items.remove(item)
        self._cpu_items.clear()
        self._tiles_by_key.clear()
        self._visible_keys.clear()
        self._pending_keys.clear()
        self._inflight_keys.clear()
