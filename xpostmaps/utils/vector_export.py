"""Print-resolution geometry for vector PDF export.

Applies pixel-space decimation, spatial grid deduplication, sub-pixel
clustering, coordinate precision reduction, and view culling so exported
postplot vectors stay sharp without redundant paths or hidden vertices.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xpostmaps.utils.spatial_clip import (
    _apply_keep_mask,
    _rdp_keep_mask,
    clip_arrays_to_bbox,
    polyline_runs,
)

# RDP tolerance in device pixels (Douglas–Peucker in pixel space) at 50% line detail.
_PIXEL_RDP_EPS = 0.45
_DEFAULT_LINE_DETAIL_PERCENT = 70
# Packed grid key multiplier (must exceed max device dimension).
_GRID_KEY_STRIDE = 4_000_003


@dataclass(frozen=True)
class VectorExportContext:
    """Maps world coordinates to PDF device pixels for the plot viewport."""

    view_bbox: tuple[float, float, float, float]
    clip_bbox: tuple[float, float, float, float]
    view_w: int
    view_h: int
    device_w: float
    device_h: float
    line_detail_percent: int = _DEFAULT_LINE_DETAIL_PERCENT

    @classmethod
    def from_view(
        cls,
        *,
        view_bbox: tuple[float, float, float, float],
        clip_bbox: tuple[float, float, float, float],
        view_w: int,
        view_h: int,
        device_w: float,
        device_h: float,
        line_detail_percent: int = _DEFAULT_LINE_DETAIL_PERCENT,
    ) -> VectorExportContext:
        return cls(
            view_bbox=view_bbox,
            clip_bbox=clip_bbox,
            view_w=max(int(view_w), 1),
            view_h=max(int(view_h), 1),
            device_w=max(float(device_w), 1.0),
            device_h=max(float(device_h), 1.0),
            line_detail_percent=max(0, min(100, int(line_detail_percent))),
        )

    @property
    def rdp_epsilon(self) -> float:
        """Douglas–Peucker tolerance in device pixels (0 = keep all pixel steps)."""
        if self.line_detail_percent >= 100:
            return 0.0
        return _PIXEL_RDP_EPS * (100 - self.line_detail_percent) / 50.0

    @property
    def scatter_cell_px_scale(self) -> float:
        """Scatter grid coarseness; 0 requests minimal one-pixel deduplication."""
        if self.line_detail_percent >= 100:
            return 0.0
        return max(0.25, (100 - self.line_detail_percent) / 50.0)

    @property
    def world_per_pixel_x(self) -> float:
        x0, x1, _, _ = self.view_bbox
        return max((x1 - x0) / self.device_w, 1e-12)

    @property
    def world_per_pixel_y(self) -> float:
        _, _, y0, y1 = self.view_bbox
        return max((y1 - y0) / self.device_h, 1e-12)

    @property
    def world_quantum(self) -> float:
        """Smallest meaningful world step at print resolution."""
        return max(self.world_per_pixel_x, self.world_per_pixel_y)


def _filter_visible_scatter(
    xs: np.ndarray,
    ys: np.ndarray,
    view_bbox: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Drop shotpoints outside the visible view (hidden off-screen points)."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size == 0:
        return xs, ys
    x0, x1, y0, y1 = view_bbox
    mask = (
        np.isfinite(xs)
        & np.isfinite(ys)
        & (xs >= x0)
        & (xs <= x1)
        & (ys >= y0)
        & (ys <= y1)
    )
    return xs[mask], ys[mask]


def _world_to_device(
    xs: np.ndarray,
    ys: np.ndarray,
    ctx: VectorExportContext,
) -> tuple[np.ndarray, np.ndarray]:
    x0, _, y0, _ = ctx.view_bbox
    px = (xs - x0) / ctx.world_per_pixel_x
    py = (ys - y0) / ctx.world_per_pixel_y
    return px, py


def _device_to_world(
    px: np.ndarray,
    py: np.ndarray,
    ctx: VectorExportContext,
) -> tuple[np.ndarray, np.ndarray]:
    x0, _, y0, _ = ctx.view_bbox
    xs = px * ctx.world_per_pixel_x + x0
    ys = py * ctx.world_per_pixel_y + y0
    return reduce_coordinate_precision(xs, ys, ctx)


def reduce_coordinate_precision(
    xs: np.ndarray,
    ys: np.ndarray,
    ctx: VectorExportContext,
) -> tuple[np.ndarray, np.ndarray]:
    """Snap world coordinates to the print pixel grid."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size == 0:
        return xs, ys
    quantum = ctx.world_quantum
    if quantum <= 0.0:
        return xs, ys
    x0, _, y0, _ = ctx.view_bbox
    px = np.round((xs - x0) / quantum)
    py = np.round((ys - y0) / quantum)
    return px * quantum + x0, py * quantum + y0


def _dedupe_pixel_grid(
    px: np.ndarray,
    py: np.ndarray,
    *,
    cell_px: float,
) -> np.ndarray:
    """Return indices keeping one point per ``cell_px`` device-pixel cell."""
    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    n = px.size
    if n <= 1:
        return np.arange(n, dtype=np.int64)
    cell = max(float(cell_px), 1.0)
    cx = np.floor(px / cell).astype(np.int64)
    cy = np.floor(py / cell).astype(np.int64)
    keys = cx * _GRID_KEY_STRIDE + cy
    _, first_idx = np.unique(keys, return_index=True)
    return np.sort(first_idx)


def _dedupe_consecutive_pixels(
    px: np.ndarray,
    py: np.ndarray,
) -> np.ndarray:
    """Drop consecutive vertices that occupy the same device pixel."""
    n = px.size
    if n <= 1:
        return np.arange(n, dtype=np.int64)
    ix = np.floor(px).astype(np.int64)
    iy = np.floor(py).astype(np.int64)
    keep = np.zeros(n, dtype=np.bool_)
    keep[0] = True
    last_x = ix[0]
    last_y = iy[0]
    count = 1
    for i in range(1, n):
        if ix[i] != last_x or iy[i] != last_y:
            keep[i] = True
            last_x = ix[i]
            last_y = iy[i]
            count += 1
    if not keep[n - 1]:
        keep[n - 1] = True
    return np.flatnonzero(keep)


def _pixel_rdp(
    px: np.ndarray,
    py: np.ndarray,
    *,
    epsilon: float = _PIXEL_RDP_EPS,
) -> tuple[np.ndarray, np.ndarray]:
    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    if px.size <= 2:
        return px, py
    keep = _rdp_keep_mask(px, py, epsilon)
    return _apply_keep_mask(px, py, keep)


def _decimate_line_run(
    xs: np.ndarray,
    ys: np.ndarray,
    ctx: VectorExportContext,
) -> tuple[np.ndarray, np.ndarray]:
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size < 2:
        return xs[:0], ys[:0]
    px, py = _world_to_device(xs, ys, ctx)
    eps = ctx.rdp_epsilon
    if eps > 0.0:
        px, py = _pixel_rdp(px, py, epsilon=eps)
    if px.size >= 2:
        idx = _dedupe_consecutive_pixels(px, py)
        px, py = px[idx], py[idx]
    if px.size < 2:
        return xs[:0], ys[:0]
    return _device_to_world(px, py, ctx)


def prepare_vector_line_geometry(
    xs: np.ndarray,
    ys: np.ndarray,
    ctx: VectorExportContext,
) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-base line decimation for vector PDF export."""
    cx, cy = clip_arrays_to_bbox(
        np.asarray(xs, dtype=np.float64),
        np.asarray(ys, dtype=np.float64),
        ctx.clip_bbox,
        kind="line",
    )
    if cx.size < 2:
        return cx[:0], cy[:0]

    chunks_x: list[np.ndarray] = []
    chunks_y: list[np.ndarray] = []
    for rx, ry in polyline_runs(cx, cy):
        sx, sy = _decimate_line_run(rx, ry, ctx)
        if sx.size < 2:
            continue
        if chunks_x:
            chunks_x.append(np.array([np.nan], dtype=np.float64))
            chunks_y.append(np.array([np.nan], dtype=np.float64))
        chunks_x.append(sx)
        chunks_y.append(sy)
    if not chunks_x:
        return cx[:0], cy[:0]
    return np.concatenate(chunks_x), np.concatenate(chunks_y)


def prepare_vector_scatter_geometry(
    xs: np.ndarray,
    ys: np.ndarray,
    ctx: VectorExportContext,
    *,
    symbol_px: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Pixel grid dedup, sub-resolution clustering, and view culling for markers."""
    cx, cy = clip_arrays_to_bbox(
        np.asarray(xs, dtype=np.float64),
        np.asarray(ys, dtype=np.float64),
        ctx.clip_bbox,
        kind="scatter",
    )
    cx, cy = _filter_visible_scatter(cx, cy, ctx.view_bbox)
    if cx.size == 0:
        return cx, cy

    px, py = _world_to_device(cx, cy, ctx)
    # Symbols smaller than one print pixel collapse to a single representative.
    if ctx.scatter_cell_px_scale <= 0.0:
        cell_px = 1.0
    else:
        cell_px = max(1.0, float(symbol_px) * 0.85 * ctx.scatter_cell_px_scale)
    if cell_px > 1.0 or cx.size > max(ctx.device_w * ctx.device_h * 0.5, 8_000):
        idx = _dedupe_pixel_grid(px, py, cell_px=cell_px)
        px, py = px[idx], py[idx]
        cx, cy = cx[idx], cy[idx]
    else:
        idx = _dedupe_pixel_grid(px, py, cell_px=1.0)
        px, py = px[idx], py[idx]
        cx, cy = cx[idx], cy[idx]

    return reduce_coordinate_precision(cx, cy, ctx)


def merge_line_parts(
    parts: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """Merge decimated line runs into one NaN-separated polyline (symbol reuse)."""
    chunks_x: list[np.ndarray] = []
    chunks_y: list[np.ndarray] = []
    for xs, ys in parts:
        if xs.size < 2:
            continue
        if chunks_x:
            chunks_x.append(np.array([np.nan], dtype=np.float64))
            chunks_y.append(np.array([np.nan], dtype=np.float64))
        chunks_x.append(xs)
        chunks_y.append(ys)
    if not chunks_x:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    return np.concatenate(chunks_x), np.concatenate(chunks_y)
