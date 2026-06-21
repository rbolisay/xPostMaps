"""Spatial indexing and Numba-accelerated view clipping for large map layers."""

from __future__ import annotations

import math

import numpy as np
from numba import njit

# Target finite points per grid cell when auto-sizing the index.
_TARGET_POINTS_PER_CELL = 8_000


@njit(cache=True)
def _clip_line_to_bbox(
    xs: np.ndarray,
    ys: np.ndarray,
    bx0: float,
    bx1: float,
    by0: float,
    by1: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Clip a polyline batch preserving vertex order and NaN separators."""
    n = xs.size
    if n == 0:
        return xs, ys

    count = 0
    for i in range(n):
        x = xs[i]
        if not np.isfinite(x):
            count += 1
        elif x >= bx0 and x <= bx1 and ys[i] >= by0 and ys[i] <= by1:
            count += 1

    out_x = np.empty(count, dtype=np.float64)
    out_y = np.empty(count, dtype=np.float64)
    pos = 0
    for i in range(n):
        x = xs[i]
        if not np.isfinite(x):
            out_x[pos] = x
            out_y[pos] = ys[i]
            pos += 1
        elif x >= bx0 and x <= bx1 and ys[i] >= by0 and ys[i] <= by1:
            out_x[pos] = x
            out_y[pos] = ys[i]
            pos += 1
    return out_x, out_y


@njit(cache=True)
def _clip_scatter_to_bbox(
    xs: np.ndarray,
    ys: np.ndarray,
    bx0: float,
    bx1: float,
    by0: float,
    by1: float,
) -> tuple[np.ndarray, np.ndarray]:
    n = xs.size
    if n == 0:
        return xs, ys

    count = 0
    for i in range(n):
        x = xs[i]
        if not np.isfinite(x):
            continue
        y = ys[i]
        if x >= bx0 and x <= bx1 and y >= by0 and y <= by1:
            count += 1

    out_x = np.empty(count, dtype=np.float64)
    out_y = np.empty(count, dtype=np.float64)
    pos = 0
    for i in range(n):
        x = xs[i]
        if not np.isfinite(x):
            continue
        y = ys[i]
        if x >= bx0 and x <= bx1 and y >= by0 and y <= by1:
            out_x[pos] = x
            out_y[pos] = y
            pos += 1
    return out_x, out_y


@njit(cache=True)
def _clip_line_candidates(
    xs: np.ndarray,
    ys: np.ndarray,
    candidate_indices: np.ndarray,
    bx0: float,
    bx1: float,
    by0: float,
    by1: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Clip using spatial candidates for finite points plus all NaN separators."""
    n = xs.size
    if n == 0:
        return xs, ys

    is_candidate = np.zeros(n, dtype=np.bool_)
    for idx in candidate_indices:
        is_candidate[idx] = True

    count = 0
    for i in range(n):
        x = xs[i]
        if not np.isfinite(x):
            count += 1
        elif (
            is_candidate[i]
            and x >= bx0
            and x <= bx1
            and ys[i] >= by0
            and ys[i] <= by1
        ):
            count += 1

    out_x = np.empty(count, dtype=np.float64)
    out_y = np.empty(count, dtype=np.float64)
    pos = 0
    for i in range(n):
        x = xs[i]
        if not np.isfinite(x):
            out_x[pos] = x
            out_y[pos] = ys[i]
            pos += 1
        elif (
            is_candidate[i]
            and x >= bx0
            and x <= bx1
            and ys[i] >= by0
            and ys[i] <= by1
        ):
            out_x[pos] = x
            out_y[pos] = ys[i]
            pos += 1
    return out_x, out_y


@njit(cache=True)
def _clip_scatter_candidates(
    xs: np.ndarray,
    ys: np.ndarray,
    candidate_indices: np.ndarray,
    bx0: float,
    bx1: float,
    by0: float,
    by1: float,
) -> tuple[np.ndarray, np.ndarray]:
    count = 0
    for idx in candidate_indices:
        x = xs[idx]
        if not np.isfinite(x):
            continue
        y = ys[idx]
        if x >= bx0 and x <= bx1 and y >= by0 and y <= by1:
            count += 1

    out_x = np.empty(count, dtype=np.float64)
    out_y = np.empty(count, dtype=np.float64)
    pos = 0
    for idx in candidate_indices:
        x = xs[idx]
        if not np.isfinite(x):
            continue
        y = ys[idx]
        if x >= bx0 and x <= bx1 and y >= by0 and y <= by1:
            out_x[pos] = x
            out_y[pos] = y
            pos += 1
    return out_x, out_y


class SpatialGridIndex:
    """Uniform grid over finite points for sub-linear view clipping."""

    __slots__ = (
        "_cell_size",
        "_cells",
        "_x0",
        "_y0",
        "use_index",
    )

    def __init__(
        self,
        xs: np.ndarray,
        ys: np.ndarray,
        *,
        cell_size: float | None = None,
        min_points_for_index: int = 50_000,
    ) -> None:
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        finite = np.isfinite(xs) & np.isfinite(ys)
        finite_count = int(np.count_nonzero(finite))

        self.use_index = finite_count >= min_points_for_index
        if not self.use_index or finite_count == 0:
            self._cells = {}
            self._cell_size = 1.0
            self._x0 = 0.0
            self._y0 = 0.0
            return

        fx = xs[finite]
        fy = ys[finite]
        fidx = np.flatnonzero(finite)
        xmin = float(fx.min())
        xmax = float(fx.max())
        ymin = float(fy.min())
        ymax = float(fy.max())
        span_x = max(xmax - xmin, 1.0)
        span_y = max(ymax - ymin, 1.0)

        if cell_size is None or cell_size <= 0.0:
            target_cells = max(1, int(math.ceil(finite_count / _TARGET_POINTS_PER_CELL)))
            side = max(1, int(math.ceil(math.sqrt(target_cells))))
            cell_size = max(span_x / side, span_y / side, 1.0)

        self._cell_size = float(cell_size)
        self._x0 = xmin
        self._y0 = ymin

        cell_ix = np.floor((fx - self._x0) / self._cell_size).astype(np.int32)
        cell_iy = np.floor((fy - self._y0) / self._cell_size).astype(np.int32)
        order = np.lexsort((fidx, cell_iy, cell_ix))
        sorted_ix = cell_ix[order]
        sorted_iy = cell_iy[order]
        sorted_idx = fidx[order]

        cells: dict[tuple[int, int], list[int]] = {}
        start = 0
        while start < sorted_idx.size:
            key = (int(sorted_ix[start]), int(sorted_iy[start]))
            end = start + 1
            while (
                end < sorted_idx.size
                and sorted_ix[end] == key[0]
                and sorted_iy[end] == key[1]
            ):
                end += 1
            cells[key] = sorted_idx[start:end].copy()
            start = end

        self._cells = cells

    def query_candidate_indices(
        self,
        bx0: float,
        bx1: float,
        by0: float,
        by1: float,
    ) -> np.ndarray:
        if not self.use_index or not self._cells:
            return np.empty(0, dtype=np.int64)

        ix0 = int(math.floor((bx0 - self._x0) / self._cell_size))
        ix1 = int(math.floor((bx1 - self._x0) / self._cell_size))
        iy0 = int(math.floor((by0 - self._y0) / self._cell_size))
        iy1 = int(math.floor((by1 - self._y0) / self._cell_size))

        chunks: list[np.ndarray] = []
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                chunk = self._cells.get((ix, iy))
                if chunk is not None and chunk.size:
                    chunks.append(chunk)
        if not chunks:
            return np.empty(0, dtype=np.int64)
        if len(chunks) == 1:
            return chunks[0]
        return np.concatenate(chunks)


def build_coarse_preview(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    max_points: int = 10_000,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a lightweight preview for snappy pan/zoom (QGIS-style LOD)."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size == 0:
        return xs, ys
    finite = np.isfinite(xs) & np.isfinite(ys)
    finite_count = int(np.count_nonzero(finite))
    if finite_count <= max_points:
        return xs, ys
    step = max(1, int(np.ceil(finite_count / max_points)))
    finite_indices = np.flatnonzero(finite)
    picked = finite_indices[::step]
    return xs[picked], ys[picked]


def clip_arrays_to_bbox(
    xs: np.ndarray,
    ys: np.ndarray,
    bbox: tuple[float, float, float, float],
    *,
    kind: str,
    grid: SpatialGridIndex | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return coordinate arrays clipped to ``bbox = (x0, x1, y0, y1)``."""
    bx0, bx1, by0, by1 = bbox
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)

    if grid is not None and grid.use_index:
        candidates = grid.query_candidate_indices(bx0, bx1, by0, by1)
        if kind == "line":
            return _clip_line_candidates(xs, ys, candidates, bx0, bx1, by0, by1)
        return _clip_scatter_candidates(xs, ys, candidates, bx0, bx1, by0, by1)

    if kind == "line":
        return _clip_line_to_bbox(xs, ys, bx0, bx1, by0, by1)
    return _clip_scatter_to_bbox(xs, ys, bx0, bx1, by0, by1)


def clip_items_to_bbox(
    items: list[dict],
    bbox: tuple[float, float, float, float],
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Clip a list of registered map clip records."""
    results: list[tuple[np.ndarray, np.ndarray]] = []
    for rec in items:
        cx, cy = clip_arrays_to_bbox(
            rec["xs"],
            rec["ys"],
            bbox,
            kind=rec["kind"],
            grid=rec.get("grid"),
        )
        results.append((cx, cy))
    return results
