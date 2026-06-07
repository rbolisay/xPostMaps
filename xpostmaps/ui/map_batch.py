"""Batch map geometry for fast PyQtGraph rendering."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xpostmaps.core.models import LineSegment, LineStyle


@dataclass(frozen=True)
class LineBatchKey:
    color: tuple[int, int, int, int]
    line_style: LineStyle
    width: float
    dotted: bool
    dot_radius: float = 3.0


def _rgba_tuple(color: str, opacity: float) -> tuple[int, int, int, int]:
    from PySide6.QtGui import QColor

    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, opacity)))
    return c.red(), c.green(), c.blue(), c.alpha()


def normalize_line_style(style: LineStyle | str) -> LineStyle:
    if isinstance(style, LineStyle):
        return style
    try:
        return LineStyle(str(style))
    except ValueError:
        return LineStyle.SOLID


def renders_as_scatter(line_style: LineStyle | str) -> bool:
    """Dotted legend style: one circle marker per shotpoint, never a connected line."""
    return normalize_line_style(line_style) == LineStyle.DOTTED


def shotpoint_marker_coords(
    parts: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """Flatten segment vertices to one (x, y) pair per navigation shotpoint."""
    chunks_x: list[np.ndarray] = []
    chunks_y: list[np.ndarray] = []
    for xs, ys in parts:
        if len(xs) == 0:
            continue
        arr_x = np.asarray(xs, dtype=np.float64)
        arr_y = np.asarray(ys, dtype=np.float64)
        if arr_x.size != arr_y.size:
            count = min(arr_x.size, arr_y.size)
            arr_x = arr_x[:count]
            arr_y = arr_y[:count]
        valid = np.isfinite(arr_x) & np.isfinite(arr_y)
        if not np.any(valid):
            continue
        chunks_x.append(arr_x[valid])
        chunks_y.append(arr_y[valid])
    if not chunks_x:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    return np.concatenate(chunks_x), np.concatenate(chunks_y)


def concat_polylines(segments: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    """Join polyline arrays with NaN separators for a single PlotDataItem."""
    if not segments:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

    total_points = sum(len(xs) for xs, _ in segments)
    gaps = max(len(segments) - 1, 0)
    out_x = np.empty(total_points + gaps, dtype=np.float64)
    out_y = np.empty(total_points + gaps, dtype=np.float64)
    pos = 0
    for index, (xs, ys) in enumerate(segments):
        count = len(xs)
        if count == 0:
            continue
        out_x[pos : pos + count] = xs
        out_y[pos : pos + count] = ys
        pos += count
        if index < len(segments) - 1:
            out_x[pos] = np.nan
            out_y[pos] = np.nan
            pos += 1
    return out_x[:pos], out_y[:pos]


def concat_points(segments: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    if not segments:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    xs = [x for x, _ in segments if len(x)]
    ys = [y for _, y in segments if len(y)]
    if not xs:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    return np.concatenate(xs), np.concatenate(ys)


def build_line_batches(
    segments: list[LineSegment],
    style_fn,
) -> dict[LineBatchKey, list[tuple[np.ndarray, np.ndarray]]]:
    """Group segment coordinate arrays by rendered style."""
    batches: dict[LineBatchKey, list[tuple[np.ndarray, np.ndarray]]] = {}
    for segment in segments:
        if not segment.xs:
            continue
        color, line_style, opacity = style_fn(segment)
        rgba = _rgba_tuple(color, opacity)
        width = 1.2
        key = LineBatchKey(
            color=rgba,
            line_style=line_style,
            width=width,
            dotted=renders_as_scatter(line_style),
            dot_radius=3.0,
        )
        xs = np.asarray(segment.xs, dtype=np.float64)
        ys = np.asarray(segment.ys, dtype=np.float64)
        batches.setdefault(key, []).append((xs, ys))
    return batches
