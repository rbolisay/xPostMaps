"""Spatial tiling for GPU/CPU-resident map line layers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xpostmaps.utils.spatial_clip import (
    SpatialGridIndex,
    clip_arrays_to_bbox,
    polyline_runs,
    screen_line_geometry,
)


_TILE_RUN_VERTEX_CAP = 500_000
_NAN = np.array([np.nan], dtype=np.float64)


@dataclass(frozen=True, slots=True)
class SpatialLineTile:
    key: tuple[int, int]
    bbox: tuple[float, float, float, float]
    xs: np.ndarray
    ys: np.ndarray

    @property
    def runs(self) -> list[tuple[np.ndarray, np.ndarray]]:
        return polyline_runs(self.xs, self.ys)


def _segment_intersects_bbox(
    xs: np.ndarray,
    ys: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> bool:
    bx0, bx1, by0, by1 = bbox
    finite = np.isfinite(xs) & np.isfinite(ys)
    if not np.any(finite):
        return False
    fx = xs[finite]
    fy = ys[finite]
    return not (
        float(fx.max()) < bx0
        or float(fx.min()) > bx1
        or float(fy.max()) < by0
        or float(fy.min()) > by1
    )


def _merge_clip_chunks(
    chunks: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray] | None:
    if not chunks:
        return None
    if len(chunks) == 1:
        return chunks[0]
    parts_x: list[np.ndarray] = []
    parts_y: list[np.ndarray] = []
    for cx, cy in chunks:
        parts_x.extend((cx, _NAN))
        parts_y.extend((cy, _NAN))
    return np.concatenate(parts_x[:-1]), np.concatenate(parts_y[:-1])


def _cell_vertex_runs(
    xs: np.ndarray,
    ys: np.ndarray,
    indices: np.ndarray,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Contiguous index runs along the parent polyline (no min→max span)."""
    if indices.size < 2:
        return []
    idx = np.asarray(indices, dtype=np.int64)
    breaks = np.where(np.diff(idx) > 1)[0] + 1
    runs: list[tuple[np.ndarray, np.ndarray]] = []
    for chunk in np.split(idx, breaks):
        if chunk.size < 2:
            continue
        lo = int(chunk[0])
        hi = int(chunk[-1])
        rx = xs[lo : hi + 1]
        ry = ys[lo : hi + 1]
        if rx.size >= 2:
            runs.append((rx, ry))
    return runs


def _expand_indices_halo(
    xs: np.ndarray,
    indices: np.ndarray,
    *,
    steps: int = 2,
) -> np.ndarray:
    """Include neighbor vertices along the polyline so lines cross cell edges smoothly."""
    if indices.size == 0:
        return indices
    n = xs.size
    expanded = {int(i) for i in indices}
    frontier = set(expanded)
    for _ in range(steps):
        new: set[int] = set()
        for i in frontier:
            for j in (i - 1, i + 1):
                if 0 <= j < n and np.isfinite(xs[j]):
                    new.add(j)
        new -= expanded
        if not new:
            break
        expanded |= new
        frontier = new
    return np.fromiter(sorted(expanded), dtype=np.int64)


def build_spatial_line_tile_vertex(
    xs: np.ndarray,
    ys: np.ndarray,
    grid: SpatialGridIndex,
    key: tuple[int, int],
    *,
    halo_steps: int = 2,
    run_vertex_cap: int = _TILE_RUN_VERTEX_CAP,
) -> SpatialLineTile | None:
    """Build one seamless tile from grid vertices (no rectangular bbox clip)."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)

    if not grid.use_index:
        finite = np.isfinite(xs) & np.isfinite(ys)
        if np.count_nonzero(finite) < 2:
            return None
        bbox = (
            float(np.nanmin(xs)),
            float(np.nanmax(xs)),
            float(np.nanmin(ys)),
            float(np.nanmax(ys)),
        )
        return SpatialLineTile((0, 0), bbox, xs, ys)

    padding = max(grid.cell_size * 0.05, 1.0)
    bbox = grid.cell_bbox(key, padding=padding)
    indices = grid.cell_indices(key)
    if indices.size < 2:
        return None
    halo = _expand_indices_halo(xs, indices, steps=halo_steps)
    runs = _cell_vertex_runs(xs, ys, halo)
    merged = _merge_clip_chunks(runs)
    if merged is None:
        return None
    cx, cy = merged
    if cx.size > run_vertex_cap:
        cx, cy = screen_line_geometry(cx, cy, budget=run_vertex_cap)
    if cx.size < 2:
        return None
    return SpatialLineTile(key, bbox, cx, cy)


def build_spatial_line_tile_from_parts(
    parts: list[tuple[np.ndarray, np.ndarray]],
    grid: SpatialGridIndex,
    key: tuple[int, int],
    *,
    padding_fraction: float = 0.15,
    run_vertex_cap: int = _TILE_RUN_VERTEX_CAP,
    for_export: bool = False,
) -> SpatialLineTile | None:
    """Clip each survey segment to a grid cell and merge with NaN gaps (one draw item per cell)."""
    if not parts:
        return None

    if not grid.use_index:
        all_x: list[np.ndarray] = []
        all_y: list[np.ndarray] = []
        for px, py in parts:
            px = np.asarray(px, dtype=np.float64)
            py = np.asarray(py, dtype=np.float64)
            if px.size >= 2:
                all_x.append(px)
                all_y.append(py)
        if not all_x:
            return None
        merged = _merge_clip_chunks(list(zip(all_x, all_y)))
        if merged is None:
            return None
        cx, cy = merged
        bbox = (
            float(np.nanmin(cx)),
            float(np.nanmax(cx)),
            float(np.nanmin(cy)),
            float(np.nanmax(cy)),
        )
        return SpatialLineTile((0, 0), bbox, cx, cy)

    padding = max(grid.cell_size * padding_fraction, 1.0)
    bbox = grid.cell_bbox(key, padding=padding)
    chunks: list[tuple[np.ndarray, np.ndarray]] = []
    for px, py in parts:
        px = np.asarray(px, dtype=np.float64)
        py = np.asarray(py, dtype=np.float64)
        if px.size < 2 or not _segment_intersects_bbox(px, py, bbox):
            continue
        cx, cy = clip_arrays_to_bbox(px, py, bbox, kind="line")
        if cx.size >= 2:
            chunks.append((cx, cy))

    merged = _merge_clip_chunks(chunks)
    if merged is None:
        return None
    cx, cy = merged
    if not for_export and cx.size > run_vertex_cap:
        cx, cy = screen_line_geometry(cx, cy, budget=run_vertex_cap)
    if cx.size < 2:
        return None
    return SpatialLineTile(key, bbox, cx, cy)


def build_spatial_line_tile(
    xs: np.ndarray,
    ys: np.ndarray,
    grid: SpatialGridIndex,
    key: tuple[int, int],
    *,
    padding_fraction: float = 0.15,
    run_vertex_cap: int = _TILE_RUN_VERTEX_CAP,
    for_export: bool = False,
) -> SpatialLineTile | None:
    """Legacy single-array entry — splits on NaN runs then delegates to parts builder."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    parts = [(rx, ry) for rx, ry in polyline_runs(xs, ys) if rx.size >= 2]
    return build_spatial_line_tile_from_parts(
        parts,
        grid,
        key,
        padding_fraction=padding_fraction,
        run_vertex_cap=run_vertex_cap,
        for_export=for_export,
    )
