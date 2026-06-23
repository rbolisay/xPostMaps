"""True-vector round markers for dotted shotpoints in PDF/vector export.

``pg.ScatterPlotItem(pxMode=True)`` renders through a rasterised symbol atlas, so
an exported PDF embeds hundreds of tiny bitmaps that pixelate (and bloat/slow the
file) when zoomed. This item paints crisp vector round points at a fixed
page-pixel diameter — the same constant on-page size as ``pxMode`` markers, but
as scalable PDF strokes that stay sharp at any zoom.

Used only during export; on-screen dotted layers stay on the GPU scatter path.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QPolygonF

# Collapse markers that land on the same page pixel so dense surveys do not emit
# millions of redundant overlapping markers (keeps the PDF small and fast).
_PIXEL_KEY_STRIDE = 1_000_003
# Upper bound on round points emitted to one page. Beyond this the dots are so dense
# they read as solid coverage, so we coarsen the dedup grid to stay fast and keep
# the PDF a sane size (the on-screen overview itself caps dotted markers too).
_MAX_DOTS = 200_000


class VectorDotsItem(pg.GraphicsObject):
    """Paint fixed page-size round vector points (sharp dotted shotpoints)."""

    def __init__(
        self,
        xs: np.ndarray,
        ys: np.ndarray,
        *,
        color,
        diameter_px: float,
        max_dots: int = _MAX_DOTS,
    ) -> None:
        super().__init__()
        self._xs = np.asarray(xs, dtype=np.float64)
        self._ys = np.asarray(ys, dtype=np.float64)
        if isinstance(color, QColor):
            self._color = QColor(color)
        else:
            r, g, b, a = (list(color) + [255, 255, 255, 255])[:4]
            self._color = QColor(int(r), int(g), int(b), int(a))
        self._diameter = max(float(diameter_px), 0.5)
        self._max_dots = max(int(max_dots), 1_000)
        self._bounds = self._compute_bounds()

    def _compute_bounds(self) -> QRectF:
        finite = np.isfinite(self._xs) & np.isfinite(self._ys)
        if not np.any(finite):
            return QRectF()
        xs = self._xs[finite]
        ys = self._ys[finite]
        x0 = float(xs.min())
        y0 = float(ys.min())
        return QRectF(x0, y0, max(float(xs.max()) - x0, 1e-9), max(float(ys.max()) - y0, 1e-9))

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self._bounds

    @staticmethod
    def _dedupe(px: np.ndarray, py: np.ndarray, cell: float) -> np.ndarray:
        """Indices keeping one marker per ``cell``-sized page grid cell."""
        ix = np.floor(px / cell).astype(np.int64)
        iy = np.floor(py / cell).astype(np.int64)
        keys = ix * _PIXEL_KEY_STRIDE + iy
        _, first = np.unique(keys, return_index=True)
        return first

    def paint(self, painter, option, widget=None) -> None:  # noqa: N802
        if self._xs.size == 0:
            return
        finite = np.isfinite(self._xs) & np.isfinite(self._ys)
        xs = self._xs[finite]
        ys = self._ys[finite]
        if xs.size == 0:
            return

        # Map data -> device pixels with the current (affine) transform, then draw
        # at a constant device diameter so circles keep their page size (like pxMode).
        tr = painter.transform()
        m11, m12 = tr.m11(), tr.m12()
        m21, m22 = tr.m21(), tr.m22()
        dx, dy = tr.dx(), tr.dy()
        px = xs * m11 + ys * m21 + dx
        py = xs * m12 + ys * m22 + dy

        # Deduplicate on a grid sized to the marker so heavily-overlapping points
        # collapse to one. This is visually lossless in dense areas and keeps the
        # PDF small and fast on dense surveys.
        cell = max(1.0, self._diameter * 0.5)
        first = self._dedupe(px, py, cell)
        # If the page is saturated with dots, coarsen the grid once to cap the
        # count — preserves the spatial spread without flooding the PDF.
        if first.size > self._max_dots:
            cell *= float(np.sqrt(first.size / self._max_dots))
            first = self._dedupe(px, py, cell)
        px = px[first]
        py = py[first]

        painter.save()
        try:
            painter.resetTransform()
            pen = QPen(self._color)
            pen.setWidthF(self._diameter)
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # Chunking keeps temporary Qt polygon allocations bounded on very
            # dense dotted exports.
            chunk = 25_000
            for start in range(0, px.size, chunk):
                polygon = QPolygonF(
                    [
                        QPointF(float(x), float(y))
                        for x, y in zip(
                            px[start : start + chunk],
                            py[start : start + chunk],
                        )
                    ]
                )
                painter.drawPoints(polygon)
        finally:
            painter.restore()
