"""PyQtGraph pen helpers for 4D Stat plots."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_plot_data import BoundaryRow, SourceStyleRow
from xpostmaps.utils.symbology_units import DEFAULT_SCREEN_DPI, mm_to_pixels, scatter_size_px


def _width_px(line_width_mm: float) -> float:
    return max(1.0, mm_to_pixels(DEFAULT_SCREEN_DPI, line_width_mm))


def pen_from_style(
    color: str,
    opacity: float,
    line_style: LineStyle,
    *,
    line_width_mm: float = 0.35,
    dot_radius_mm: float = 0.8,
    dash_length_mm: float = 3.0,
) -> QPen:
    """Build a cosmetic pen (pixel width) so boundaries stay thin in meter space."""
    qcolor = QColor(color)
    qcolor.setAlphaF(max(0.0, min(1.0, opacity)))
    width_px = _width_px(line_width_mm)

    if line_style == LineStyle.DOTTED:
        dot_px = max(2.0, scatter_size_px(DEFAULT_SCREEN_DPI, dot_radius_mm))
        pen = QPen(qcolor, width_px)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([0.01, max(1.0, dot_px / width_px)])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    if line_style == LineStyle.DASH:
        dash_px = max(2.0, mm_to_pixels(DEFAULT_SCREEN_DPI, dash_length_mm))
        gap_px = max(2.0, dash_px * 0.75)
        pen = QPen(qcolor, width_px)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([dash_px / width_px, gap_px / width_px])
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        return pen

    pen = QPen(qcolor, width_px)
    pen.setCosmetic(True)
    pen.setStyle(Qt.PenStyle.SolidLine)
    return pen


def source_pen(style: SourceStyleRow) -> QPen:
    return pen_from_style(
        style.color,
        style.opacity,
        style.line_style,
        line_width_mm=style.line_width_mm,
        dot_radius_mm=style.dot_radius_mm,
        dash_length_mm=style.dash_length_mm,
    )


def boundary_pen(row: BoundaryRow) -> QPen:
    return pen_from_style(
        row.color,
        row.opacity,
        row.line_style,
        line_width_mm=row.line_width_mm,
        dot_radius_mm=row.dot_radius_mm,
        dash_length_mm=row.dash_length_mm,
    )
