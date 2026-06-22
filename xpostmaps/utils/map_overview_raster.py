"""Overview raster bake for full-survey zoom — hybrid raster + vector God mode."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from xpostmaps.utils.spatial_clip import polyline_runs, SCREEN_OVERVIEW_BUDGET, screen_line_geometry

# Pixel width/height of the overview bitmap (world aspect preserved).
OVERVIEW_RASTER_PX = 2048


def build_overview_strokes(
    strokes: list[tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]],
    *,
    budget: int = SCREEN_OVERVIEW_BUDGET,
) -> list[tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]]:
    """RDP-simplify each legend batch once for overview display."""
    out: list[tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]] = []
    for xs, ys, rgba in strokes:
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        if xs.size < 2:
            continue
        sx, sy = screen_line_geometry(xs, ys, budget=budget)
        if sx.size >= 2:
            out.append((sx, sy, rgba))
    return out


def bake_overview_raster(
    strokes: list[tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]],
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    *,
    pixel_size: int = OVERVIEW_RASTER_PX,
) -> tuple[np.ndarray, tuple[float, float, float, float]] | None:
    """Render overview strokes to an RGBA image in world coordinates.

    Returns ``(image_rgba, (x0, x1, y0, y1))`` for ``pg.ImageItem``.
    """
    if not strokes:
        return None
    x0, x1 = x_range
    y0, y1 = y_range
    span_x = max(x1 - x0, 1.0)
    span_y = max(y1 - y0, 1.0)
    aspect = span_x / span_y
    if aspect >= 1.0:
        width = pixel_size
        height = max(64, int(round(pixel_size / aspect)))
    else:
        height = pixel_size
        width = max(64, int(round(pixel_size * aspect)))

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def to_px(x: float, y: float) -> tuple[float, float]:
        """Map world coords → QImage pixels (row 0 anchored at min northing)."""
        px = (x - x0) / span_x * (width - 1)
        py = (y - y0) / span_y * (height - 1)
        return px, py

    for xs, ys, rgba in strokes:
        color = QColor(rgba[0], rgba[1], rgba[2], rgba[3])
        pen = QPen(color)
        pen.setWidthF(1.0)
        pen.setCosmetic(False)
        painter.setPen(pen)
        for rx, ry in polyline_runs(xs, ys):
            if rx.size < 2:
                continue
            px0, py0 = to_px(float(rx[0]), float(ry[0]))
            for i in range(1, rx.size):
                px1, py1 = to_px(float(rx[i]), float(ry[i]))
                painter.drawLine(px0, py0, px1, py1)
                px0, py0 = px1, py1

    painter.end()

    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = img.width()
    height = img.height()
    bpl = img.bytesPerLine()
    ptr = img.constBits()
    if hasattr(ptr, "setsize"):
        ptr.setsize(bpl * height)
    buffer = np.frombuffer(ptr, dtype=np.uint8, count=bpl * height)
    arr = buffer.reshape((height, bpl // 4, 4))[:, :width, :].copy()
    return arr, (x0, x1, y0, y1)
