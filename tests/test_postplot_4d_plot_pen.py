"""Tests for 4D Stat plot pen helpers."""

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_plot_data import BoundaryRow, SourceStyleRow
from xpostmaps.ui.postplot_4d_stat_plot.plot_pen import boundary_pen, pen_from_style, source_pen


def test_boundary_pens_with_same_width_use_equal_pixel_width() -> None:
    row_a = BoundaryRow(abs_boundary=6.0, line_width_mm=0.35)
    row_b = BoundaryRow(abs_boundary=9.0, line_width_mm=0.35)
    assert boundary_pen(row_a).widthF() == boundary_pen(row_b).widthF()


def test_all_stat_pens_are_cosmetic() -> None:
    source = source_pen(SourceStyleRow(source_no="G01", line_style=LineStyle.DASH))
    boundary = boundary_pen(BoundaryRow())
    solid = pen_from_style("#000000", 1.0, LineStyle.SOLID)
    for pen in (source, boundary, solid):
        assert pen.isCosmetic()
        assert pen.widthF() >= 1.0
