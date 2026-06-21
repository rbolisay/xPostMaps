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

    @property
    def cell_size(self) -> float:
        return self._cell_size

    @property
    def origin(self) -> tuple[float, float]:
        return self._x0, self._y0

    def iter_cell_bboxes(
        self,
        padding: float = 0.0,
    ):
        """Yield ``((ix, iy), (x0, x1, y0, y1))`` for each populated grid cell."""
        if not self.use_index or not self._cells:
            return
        size = self._cell_size
        for ix, iy in self._cells:
            x0 = self._x0 + ix * size - padding
            x1 = self._x0 + (ix + 1) * size + padding
            y0 = self._y0 + iy * size - padding
            y1 = self._y0 + (iy + 1) * size + padding
            yield (ix, iy), (x0, x1, y0, y1)

    def cell_keys_for_bbox(
        self,
        bx0: float,
        bx1: float,
        by0: float,
        by1: float,
        *,
        margin_cells: int = 1,
    ) -> set[tuple[int, int]]:
        """Return populated cell keys intersecting a world bounding box."""
        if not self.use_index or not self._cells:
            return {(0, 0)}
        size = self._cell_size
        ix0 = int(math.floor((bx0 - self._x0) / size)) - margin_cells
        ix1 = int(math.floor((bx1 - self._x0) / size)) + margin_cells
        iy0 = int(math.floor((by0 - self._y0) / size)) - margin_cells
        iy1 = int(math.floor((by1 - self._y0) / size)) + margin_cells
        keys: set[tuple[int, int]] = set()
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                if (ix, iy) in self._cells:
                    keys.add((ix, iy))
        return keys

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


# --- Screen LOD (shape-preserving lines, uniform scatter pick) ----------------

# Solid lines: use full view-clipped detail up to this cap when motion stops.
# Simplification (RDP) only runs above the cap — e.g. million-point edge cases.
SCREEN_LINE_HARD_CAP = 400_000
SCREEN_SCATTER_BUDGET = 40_000
# Shape-preserving Douglas–Peucker budget for pan/zoom motion LOD (not uniform pick).
MOTION_LINE_BUDGET = 32_000
# Only pre-filter before RDP on extremely large single runs (keeps RDP fast).
_LINE_PREFILTER_MIN = 900_000


@njit(cache=True)
def _perpendicular_distance(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> float:
    dx = x2 - x1
    dy = y2 - y1
    denom = dx * dx + dy * dy
    if denom == 0.0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / denom
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


@njit(cache=True)
def _rdp_keep_mask(xs: np.ndarray, ys: np.ndarray, epsilon: float) -> np.ndarray:
    n = xs.size
    keep = np.zeros(n, dtype=np.bool_)
    if n == 0:
        return keep
    if n <= 2:
        keep[:n] = True
        return keep
    keep[0] = True
    keep[n - 1] = True
    stack_start = np.empty(n, dtype=np.int64)
    stack_end = np.empty(n, dtype=np.int64)
    depth = 1
    stack_start[0] = 0
    stack_end[0] = n - 1
    while depth > 0:
        depth -= 1
        start = stack_start[depth]
        end = stack_end[depth]
        if end <= start + 1:
            continue
        max_dist = -1.0
        max_idx = start + 1
        x1 = xs[start]
        y1 = ys[start]
        x2 = xs[end]
        y2 = ys[end]
        for i in range(start + 1, end):
            dist = _perpendicular_distance(xs[i], ys[i], x1, y1, x2, y2)
            if dist > max_dist:
                max_dist = dist
                max_idx = i
        if max_dist > epsilon:
            keep[max_idx] = True
            stack_start[depth] = start
            stack_end[depth] = max_idx
            depth += 1
            stack_start[depth] = max_idx
            stack_end[depth] = end
            depth += 1
    return keep


def _apply_keep_mask(
    xs: np.ndarray,
    ys: np.ndarray,
    keep: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    return xs[keep], ys[keep]


def _polyline_runs(
    xs: np.ndarray,
    ys: np.ndarray,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Split a batch polyline on NaN separators."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size == 0:
        return []
    nan_break = ~np.isfinite(xs) | ~np.isfinite(ys)
    if not np.any(nan_break):
        return [(xs, ys)]
    indices = np.flatnonzero(nan_break)
    runs: list[tuple[np.ndarray, np.ndarray]] = []
    start = 0
    for stop in indices:
        if stop > start:
            runs.append((xs[start:stop], ys[start:stop]))
        start = stop + 1
    if start < xs.size:
        runs.append((xs[start:], ys[start:]))
    return [run for run in runs if run[0].size >= 2]


polyline_runs = _polyline_runs


def _simplify_run_to_budget(
    xs: np.ndarray,
    ys: np.ndarray,
    budget: int,
) -> tuple[np.ndarray, np.ndarray]:
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size <= budget:
        return xs, ys
    if xs.size > _LINE_PREFILTER_MIN:
        prelimit = max(budget * 2, _LINE_PREFILTER_MIN)
        xs, ys = build_coarse_preview(xs, ys, max_points=prelimit)
    span = max(
        float(np.nanmax(xs) - np.nanmin(xs)),
        float(np.nanmax(ys) - np.nanmin(ys)),
        1.0,
    )
    lo = 0.0
    hi = span
    best_x, best_y = xs, ys
    for _ in range(18):
        eps = (lo + hi) * 0.5
        keep = _rdp_keep_mask(xs, ys, eps)
        sx, sy = _apply_keep_mask(xs, ys, keep)
        if sx.size > budget:
            lo = eps
        else:
            hi = eps
            best_x, best_y = sx, sy
            if sx.size >= budget * 0.95:
                break
    return best_x, best_y


def motion_line_geometry(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    budget: int = MOTION_LINE_BUDGET,
) -> tuple[np.ndarray, np.ndarray]:
    """RDP simplification for motion preview — preserves curves unlike uniform pick."""
    return screen_line_geometry(xs, ys, budget=budget)


def screen_line_geometry(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    budget: int = SCREEN_LINE_HARD_CAP,
) -> tuple[np.ndarray, np.ndarray]:
    """Pass through full view-clipped lines; RDP only if above the hard cap."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size <= budget:
        return xs, ys
    runs = _polyline_runs(xs, ys)
    if not runs:
        return xs[:0], ys[:0]
    total = sum(run[0].size for run in runs)
    if total <= budget:
        return xs, ys
    chunks_x: list[np.ndarray] = []
    chunks_y: list[np.ndarray] = []
    remaining = budget
    for index, (rx, ry) in enumerate(runs):
        if index == len(runs) - 1:
            run_budget = max(2, remaining)
        else:
            run_budget = max(2, int(round(budget * rx.size / total)))
            remaining -= run_budget
        sx, sy = _simplify_run_to_budget(rx, ry, run_budget)
        if chunks_x:
            chunks_x.append(np.array([np.nan], dtype=np.float64))
            chunks_y.append(np.array([np.nan], dtype=np.float64))
        chunks_x.append(sx)
        chunks_y.append(sy)
    return np.concatenate(chunks_x), np.concatenate(chunks_y)


def screen_scatter_geometry(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    budget: int = SCREEN_SCATTER_BUDGET,
) -> tuple[np.ndarray, np.ndarray]:
    """Uniform pick for shotpoint markers — dotted style already looks good."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size <= budget:
        return xs, ys
    return build_coarse_preview(xs, ys, max_points=budget)


def prepare_screen_clip_results(
    items: list[dict],
    results: list[tuple[np.ndarray, np.ndarray]],
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Convert clipped full-resolution arrays to screen-safe geometry off the UI thread."""
    prepared: list[tuple[np.ndarray, np.ndarray]] = []
    for rec, (cx, cy) in zip(items, results):
        if rec.get("kind") == "scatter":
            cx, cy = screen_scatter_geometry(cx, cy)
        else:
            cx, cy = screen_line_geometry(cx, cy)
        prepared.append((cx, cy))
    return prepared


def clip_and_prepare_items(
    items: list[dict],
    bbox: tuple[float, float, float, float],
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Clip to view then build screen LOD in one worker pass."""
    return prepare_screen_clip_results(items, clip_items_to_bbox(items, bbox))


def prepare_motion_lod(
    items: list[dict],
) -> list[tuple[int, np.ndarray, np.ndarray]]:
    """Precompute shape-preserving motion geometry for dense line layers."""
    prepared: list[tuple[int, np.ndarray, np.ndarray]] = []
    for index, rec in enumerate(items):
        if rec.get("kind") != "line":
            continue
        cx, cy = motion_line_geometry(rec["xs"], rec["ys"])
        prepared.append((index, cx, cy))
    return prepared
