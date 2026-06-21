"""Spatially tiled line layer — geometry uploaded once, pan is transform-only."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QPen

from xpostmaps.utils.spatial_clip import SpatialGridIndex, clip_arrays_to_bbox, polyline_runs
from xpostmaps.utils.spatial_tiles import SpatialLineTile, build_spatial_line_tile

from xpostmaps.ui.map_gl_overlay import MapGlLineOverlay


class TiledLineLayer:
    """Resident tile layer for dense postplot/navplan solid lines."""

    _next_layer_id = 1

    def __init__(
        self,
        *,
        xs,
        ys,
        pen: QPen,
        export_pen: QPen,
        plot_item: pg.PlotItem,
        gl_overlay: MapGlLineOverlay | None,
        use_gl: bool,
        line_items: list[dict],
        plot_items: list[pg.GraphicsItem],
    ) -> None:
        self._layer_id = TiledLineLayer._next_layer_id
        TiledLineLayer._next_layer_id += 1
        self._xs = xs
        self._ys = ys
        self._pen = pen
        self._export_pen = export_pen
        self._plot_item = plot_item
        self._gl_overlay = gl_overlay
        self._use_gl = bool(use_gl and gl_overlay is not None and gl_overlay.available)
        self._line_items = line_items
        self._plot_items = plot_items
        self._grid = SpatialGridIndex(xs, ys)
        self._tiles_by_key: dict[tuple[int, int], SpatialLineTile] = {}
        self._cpu_items: dict[tuple[int, int], list[pg.PlotCurveItem]] = {}
        self._visible_keys: set[tuple[int, int]] = set()
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

    def update_visibility(
        self,
        bbox: tuple[float, float, float, float],
        *,
        for_export: bool = False,
    ) -> None:
        bx0, bx1, by0, by1 = bbox
        keys = self._grid.cell_keys_for_bbox(bx0, bx1, by0, by1)
        if for_export != self._export_mode:
            self._hide_all()
            self._visible_keys.clear()
            self._export_mode = for_export
            if not for_export:
                self._tiles_by_key.clear()
                self._cpu_items.clear()

        for key in self._visible_keys - keys:
            self._hide_tile(key)
        for key in keys - self._visible_keys:
            self._show_tile(key, for_export=for_export)
        self._visible_keys = keys

    def _hide_all(self) -> None:
        for key in list(self._visible_keys):
            self._hide_tile(key)
        self._visible_keys.clear()

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
        if self._use_gl and self._gl_overlay is not None and not for_export:
            self._gl_overlay.add_tile(
                self._layer_id,
                key,
                tile.xs,
                tile.ys,
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
            base = self._tiles_by_key.get(key)
            if base is None:
                base = build_spatial_line_tile(
                    self._xs, self._ys, self._grid, key, for_export=False
                )
            if base is None:
                return None
            cx, cy = clip_arrays_to_bbox(
                self._xs,
                self._ys,
                base.bbox,
                kind="line",
                grid=self._grid,
            )
            if cx.size < 2:
                return None
            return SpatialLineTile(key, base.bbox, cx, cy)

        tile = build_spatial_line_tile(self._xs, self._ys, self._grid, key)
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
        items: list[pg.PlotCurveItem] = []
        for rx, ry in polyline_runs(tile.xs, tile.ys):
            if rx.size < 2:
                continue
            curve = pg.PlotCurveItem(
                rx,
                ry,
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
            items.append(curve)
        return items

    def set_pen(self, pen: QPen, *, export: bool = False) -> None:
        if export:
            self._export_pen = pen
        else:
            self._pen = pen
        target = self._export_pen if export else self._pen
        for items in self._cpu_items.values():
            for item in items:
                item.setPen(target)

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
