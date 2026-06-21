"""Spatial tiling for GPU/CPU-resident map line layers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xpostmaps.utils.spatial_clip import (
    SpatialGridIndex,
    clip_arrays_to_bbox,
    screen_line_geometry,
)


# Per-tile vertex cap — tiles inherit ~8k points from the spatial grid by default.
_TILE_VERTEX_CAP = 100_000


@dataclass(frozen=True, slots=True)
class SpatialLineTile:
    key: tuple[int, int]
    bbox: tuple[float, float, float, float]
    xs: np.ndarray
    ys: np.ndarray


def _full_extent_bbox(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    padding: float = 1.0,
) -> tuple[float, float, float, float]:
    finite = np.isfinite(xs) & np.isfinite(ys)
    if not np.any(finite):
        return (0.0, 1.0, 0.0, 1.0)
    fx = xs[finite]
    fy = ys[finite]
    return (
        float(fx.min()) - padding,
        float(fx.max()) + padding,
        float(fy.min()) - padding,
        float(fy.max()) + padding,
    )


def build_spatial_line_tile(
    xs: np.ndarray,
    ys: np.ndarray,
    grid: SpatialGridIndex,
    key: tuple[int, int],
    *,
    padding_fraction: float = 0.5,
    vertex_cap: int = _TILE_VERTEX_CAP,
    for_export: bool = False,
) -> SpatialLineTile | None:
    """Build geometry for one spatial tile (lazy — called when the tile enters view)."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    budget = None if for_export else vertex_cap

    if not grid.use_index:
        bbox = _full_extent_bbox(xs, ys)
        cx, cy = clip_arrays_to_bbox(xs, ys, bbox, kind="line")
        if cx.size < 2:
            return None
        if budget is not None:
            cx, cy = screen_line_geometry(cx, cy, budget=budget)
        return SpatialLineTile((0, 0), bbox, cx, cy)

    padding = max(grid.cell_size * padding_fraction, 1.0)
    for tile_key, bbox in grid.iter_cell_bboxes(padding):
        if tile_key != key:
            continue
        cx, cy = clip_arrays_to_bbox(xs, ys, bbox, kind="line", grid=grid)
        if cx.size < 2:
            return None
        if budget is not None:
            cx, cy = screen_line_geometry(cx, cy, budget=budget)
        return SpatialLineTile(key, bbox, cx, cy)
    return None


def build_spatial_line_tiles(
    xs: np.ndarray,
    ys: np.ndarray,
    grid: SpatialGridIndex,
    *,
    padding_fraction: float = 0.5,
    vertex_cap: int = _TILE_VERTEX_CAP,
    for_export: bool = False,
) -> list[SpatialLineTile]:
    """Split a batched polyline into spatial tiles with geometry set once per tile."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size == 0:
        return []

    tiles: list[SpatialLineTile] = []
    budget = None if for_export else vertex_cap

    if not grid.use_index:
        bbox = _full_extent_bbox(xs, ys)
        cx, cy = clip_arrays_to_bbox(xs, ys, bbox, kind="line")
        if cx.size >= 2:
            if budget is not None:
                cx, cy = screen_line_geometry(cx, cy, budget=budget)
            tiles.append(SpatialLineTile((0, 0), bbox, cx, cy))
        return tiles

    padding = max(grid.cell_size * padding_fraction, 1.0)
    for key, bbox in grid.iter_cell_bboxes(padding):
        cx, cy = clip_arrays_to_bbox(xs, ys, bbox, kind="line", grid=grid)
        if cx.size < 2:
            continue
        if budget is not None:
            cx, cy = screen_line_geometry(cx, cy, budget=budget)
        tiles.append(SpatialLineTile(key, bbox, cx, cy))
    return tiles
