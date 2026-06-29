"""Headless render tests for 4D Stat plot widgets."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import BoundaryRow, build_plot_series, default_source_styles
from xpostmaps.ui.postplot_4d_stat_plot.plot_widget import (
    PlotCanvas,
    TimeSeriesPlotWidget,
    nearest_pick_point,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _sample_match_and_rows() -> tuple[Postplot4DMatchRow, list[Postplot4DDiffRow]]:
    match = Postplot4DMatchRow(
        baseline_name="LineA",
        baseline_kind="navplan",
        line_name="LineA",
        subline="",
        sequence_no="1",
        first_sp=100,
        last_sp=110,
        line_direction="Up-line",
        sequence_id="file|1|LineA",
    )
    rows = [
        Postplot4DDiffRow(
            shotpoint=sp,
            baseline_x=0.0,
            baseline_y=0.0,
            baseline_latitude="",
            baseline_longitude="",
            source_x=0.0,
            source_y=0.0,
            source_latitude="",
            source_longitude="",
            crossline_m=float(np.sin(sp)),
            inline_m=0.0,
            radial_m=1.0,
            firing_source_id="001",
        )
        for sp in range(100, 111)
    ]
    return match, rows


def _non_white_fraction(image) -> float:
    width = image.width()
    height = image.height()
    non_white = 0
    for y in range(0, height, 3):
        for x in range(0, width, 3):
            color = image.pixelColor(x, y)
            if color.red() < 250 or color.green() < 250 or color.blue() < 250:
                non_white += 1
    sampled = ((width + 2) // 3) * ((height + 2) // 3)
    return non_white / max(sampled, 1)


def test_nearest_pick_point_selects_closest_shotpoint() -> None:
    picked = nearest_pick_point(
        [(100.0, 1.0, "G01"), (101.0, 5.0, "G01")],
        mouse_x=100.4,
        mouse_y=1.1,
        x_tol=1.0,
        y_tol=1.0,
    )
    assert picked == (100.0, 1.0, "G01")


def test_time_series_plot_shows_selection_text(qapp) -> None:
    match, rows = _sample_match_and_rows()
    plot = TimeSeriesPlotWidget("crossline")
    plot.resize(800, 480)
    styles = default_source_styles(["G01"])
    series = build_plot_series(rows, match, "crossline", "G01")
    plot.render([series], styles, [], y_min=None, y_max=None, auto_y=True)
    plot.show()
    qapp.processEvents()
    assert len(plot._pick_points) == 11
    plot._show_pick(100.0, float(np.sin(100)), "G01")
    qapp.processEvents()
    assert plot._selection_edit.isVisible()
    assert "SP 100" in plot._selection_edit.text()
    assert "G01" in plot._selection_edit.text()


def test_capture_image_for_pdf_draws_bottom_legend(qapp) -> None:
    match, rows = _sample_match_and_rows()
    plot = TimeSeriesPlotWidget("crossline")
    styles = default_source_styles(["G01", "G02"])
    series_g01 = build_plot_series(rows, match, "crossline", "G01")
    rows_g02 = [
        Postplot4DDiffRow(
            shotpoint=row.shotpoint,
            baseline_x=row.baseline_x,
            baseline_y=row.baseline_y,
            baseline_latitude=row.baseline_latitude,
            baseline_longitude=row.baseline_longitude,
            source_x=row.source_x,
            source_y=row.source_y,
            source_latitude=row.source_latitude,
            source_longitude=row.source_longitude,
            crossline_m=row.crossline_m + 1.5,
            inline_m=row.inline_m,
            radial_m=row.radial_m,
            firing_source_id="002",
        )
        for row in rows
    ]
    series_g02 = build_plot_series(rows_g02, match, "crossline", "G02")
    plot.render(
        [series_g01, series_g02],
        styles,
        [BoundaryRow(abs_boundary=6.0)],
        y_min=None,
        y_max=None,
        auto_y=True,
    )
    image = plot.capture_image(
        width=800,
        height=480,
        for_pdf=True,
        dpi=120,
    )
    bottom_band = image.copy(QRect(0, 455, 800, 25))
    assert _non_white_fraction(bottom_band) > 0.02


def test_capture_image_for_pdf_draws_black_border(qapp) -> None:
    match, rows = _sample_match_and_rows()
    plot = TimeSeriesPlotWidget("crossline")
    styles = default_source_styles(["G01"])
    series = build_plot_series(rows, match, "crossline", "G01")
    plot.render(
        [series],
        styles,
        [BoundaryRow(abs_boundary=6.0)],
        y_min=None,
        y_max=None,
        auto_y=True,
    )
    image = plot.capture_image(width=800, height=480, for_pdf=True, dpi=120)
    edge = image.pixelColor(1, 1)
    assert edge.red() < 20 and edge.green() < 20 and edge.blue() < 20


def test_plot_canvas_renders_crossline_with_boundaries(qapp) -> None:
    match, rows = _sample_match_and_rows()
    canvas = PlotCanvas("crossline")
    canvas.resize(800, 480)
    styles = default_source_styles(["G01"])
    series = build_plot_series(rows, match, "crossline", "G01")
    canvas.render(
        [series],
        styles,
        [BoundaryRow(abs_boundary=5.0), BoundaryRow(abs_boundary=9.0)],
        y_min=None,
        y_max=None,
        auto_y=True,
    )
    qapp.processEvents()
    assert canvas.has_data()
    image = canvas.capture_image(width=800, height=480)
    assert _non_white_fraction(image) > 0.01


def test_plot_canvas_source_tabs_when_uncombined(qapp) -> None:
    match, rows = _sample_match_and_rows()
    rows_two_sources: list[Postplot4DDiffRow] = []
    for row in rows:
        rows_two_sources.append(row)
        rows_two_sources.append(
            Postplot4DDiffRow(
                shotpoint=row.shotpoint,
                baseline_x=row.baseline_x,
                baseline_y=row.baseline_y,
                baseline_latitude=row.baseline_latitude,
                baseline_longitude=row.baseline_longitude,
                source_x=row.source_x,
                source_y=row.source_y,
                source_latitude=row.source_latitude,
                source_longitude=row.source_longitude,
                crossline_m=row.crossline_m + 2.0,
                inline_m=row.inline_m,
                radial_m=row.radial_m,
                firing_source_id="002",
            )
        )
    canvas = PlotCanvas("crossline")
    canvas.set_combine_sources(False)
    canvas.resize(800, 480)
    styles = default_source_styles(["G01", "G02"])
    series_g01 = build_plot_series(rows_two_sources, match, "crossline", "G01")
    series_g02 = build_plot_series(rows_two_sources, match, "crossline", "G02")
    canvas.render(
        [series_g01, series_g02],
        styles,
        [BoundaryRow(abs_boundary=5.0)],
        y_min=None,
        y_max=None,
        auto_y=True,
    )
    qapp.processEvents()
    assert canvas._source_tabs is not None
    assert len(canvas._source_tabs.all_plots()) == 2
    assert canvas.has_data()
