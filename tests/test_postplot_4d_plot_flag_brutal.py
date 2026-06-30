"""Brutal tests: survey-spec flag colours, render speed, PDF export."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import (
    PlotSeries,
    SequenceDiffSet,
    build_plot_series,
    default_source_styles,
)
from xpostmaps.core.postplot_4d_plot_pdf import (
    Postplot4DStatPlotPdfOptions,
    export_4d_stat_plot_pdf,
)
from xpostmaps.core.postplot_4d_survey_spec import (
    Severity,
    StatType,
    SurveySpecRow,
    flag_map_for_kind,
)
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import Postplot4DStatPlotView
from xpostmaps.ui.postplot_4d_stat_plot.plot_widget import (
    TimeSeriesPlotWidget,
    _FLAG_ERROR_COLOR,
    _FLAG_WARNING_COLOR,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _match_row(*, first_sp: int = 1000, last_sp: int = 1100) -> Postplot4DMatchRow:
    return Postplot4DMatchRow(
        baseline_name="LineA",
        baseline_kind="navplan",
        line_name="LineA",
        subline="070",
        sequence_no="070",
        first_sp=first_sp,
        last_sp=last_sp,
        line_direction="Up-line",
        sequence_id="test|070|LineA",
    )


def _diff_rows(count: int = 41) -> list[Postplot4DDiffRow]:
    rows: list[Postplot4DDiffRow] = []
    for index in range(count):
        sp = 1000 + index
        rows.append(
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
                crossline_m=float(15.0 if sp == 1010 else 2.0),
                inline_m=1.0,
                radial_m=float(14.0 if sp == 1010 else 2.0),
                firing_source_id="001",
            )
        )
    return rows


def _pixel_at_data(
    plot: TimeSeriesPlotWidget,
    shotpoint: float,
    value: float,
) -> tuple[int, int]:
    vb = plot.getViewBox()
    scene_pt = vb.mapViewToScene(pg.Point(shotpoint, value))
    widget_pt = plot.mapFromScene(scene_pt)
    return int(round(widget_pt.x())), int(round(widget_pt.y()))


def _sample_flag_color(
    plot: TimeSeriesPlotWidget,
    shotpoint: float,
    value: float,
) -> QColor:
    plot.repaint()
    QApplication.processEvents()
    image = plot.grab().toImage()
    x, y = _pixel_at_data(plot, shotpoint, value)
    x = max(0, min(image.width() - 1, x))
    y = max(0, min(image.height() - 1, y))
    best = image.pixelColor(x, y)
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            sx = max(0, min(image.width() - 1, x + dx))
            sy = max(0, min(image.height() - 1, y + dy))
            color = image.pixelColor(sx, sy)
            if color.red() > best.red():
                best = color
    return best


def _is_near_color(sample: QColor, expected: str, *, tolerance: int = 80) -> bool:
    target = QColor(expected)
    return (
        abs(sample.red() - target.red()) <= tolerance
        and abs(sample.green() - target.green()) <= tolerance
        and abs(sample.blue() - target.blue()) <= tolerance
    )


def test_stat_plot_uses_cpu_not_opengl() -> None:
    import pyqtgraph as pg_mod

    assert pg_mod.getConfigOption("useOpenGL") is False


def test_flag_overlay_items_created(qapp) -> None:
    match = _match_row()
    rows = _diff_rows()
    plot = TimeSeriesPlotWidget("radial")
    plot.resize(900, 480)
    series = build_plot_series(rows, match, "radial", "G01")
    flags = {"G01": {1010: Severity.WARNING}}
    plot.render(
        [series],
        default_source_styles(["G01"]),
        [],
        y_min=None,
        y_max=None,
        auto_y=True,
        flags=flags,
    )
    qapp.processEvents()
    assert len(plot._flag_items) == 1
    xs, _ys = plot._flag_items[0].getData()
    assert 1010.0 in list(xs or [])


def test_flag_colors_visible_in_capture(qapp) -> None:
    match = _match_row()
    rows = _diff_rows()
    plot = TimeSeriesPlotWidget("radial")
    plot.resize(900, 480)
    series = build_plot_series(rows, match, "radial", "G01")
    warn_sp = 1010
    err_sp = 1011
    rows[err_sp - 1000] = Postplot4DDiffRow(
        shotpoint=err_sp,
        baseline_x=0.0,
        baseline_y=0.0,
        baseline_latitude="",
        baseline_longitude="",
        source_x=0.0,
        source_y=0.0,
        source_latitude="",
        source_longitude="",
        crossline_m=20.0,
        inline_m=1.0,
        radial_m=20.0,
        firing_source_id="001",
    )
    series = build_plot_series(rows, match, "radial", "G01")
    flags = {"G01": {warn_sp: Severity.WARNING, err_sp: Severity.ERROR}}
    plot.render(
        [series],
        default_source_styles(["G01"]),
        [],
        y_min=None,
        y_max=None,
        auto_y=True,
        flags=flags,
    )
    qapp.processEvents()

    warn_value = series.values[series.shotpoints.index(warn_sp)]
    err_value = series.values[series.shotpoints.index(err_sp)]

    warn_px = _sample_flag_color(plot, warn_sp, warn_value)
    err_px = _sample_flag_color(plot, err_sp, err_value)

    assert _is_near_color(warn_px, _FLAG_WARNING_COLOR), (
        f"warning pixel {warn_px.red()},{warn_px.green()},{warn_px.blue()}"
    )
    assert _is_near_color(err_px, _FLAG_ERROR_COLOR), (
        f"error pixel {err_px.red()},{err_px.green()},{err_px.blue()}"
    )
    flagged_xs: set[float] = set()
    for item in plot._flag_items:
        xs, _ys = item.getData()
        flagged_xs.update(float(x) for x in (xs or []))
    assert 1005.0 not in flagged_xs, "unflagged shot must not get an overlay marker"


def test_flag_map_integrates_with_plot_view(qapp) -> None:
    match = _match_row()
    rows = _diff_rows()
    diff_set = SequenceDiffSet(match_row=match, diff_rows=rows)
    specs = [
        SurveySpecRow(
            statistic=StatType.MAX_VALUE,
            metric="radial",
            stat_value=12.0,
            absolute=True,
            severity=Severity.WARNING,
        )
    ]
    flags = flag_map_for_kind([diff_set], specs, "radial")
    assert flags
    assert 1010 in next(iter(flags.values()))


def test_render_speed_with_flags(qapp) -> None:
    match = _match_row(first_sp=1000, last_sp=2000)
    rows: list[Postplot4DDiffRow] = []
    for sp in range(1000, 2001):
        rows.append(
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
                crossline_m=float(np.sin(sp / 20.0) * 5.0),
                inline_m=1.0,
                radial_m=abs(float(np.sin(sp / 20.0) * 5.0)),
                firing_source_id="001",
            )
        )
    plot = TimeSeriesPlotWidget("radial")
    plot.resize(900, 480)
    series = build_plot_series(rows, match, "radial", "G01")
    flags = {"G01": {sp: Severity.WARNING for sp in range(1100, 1200, 5)}}
    styles = default_source_styles(["G01"])

    iterations = 30
    start = time.perf_counter()
    for _ in range(iterations):
        plot.render(
            [series],
            styles,
            [],
            y_min=None,
            y_max=None,
            auto_y=True,
            flags=flags,
        )
    qapp.processEvents()
    ms_per_render = (time.perf_counter() - start) / iterations * 1000.0
    assert ms_per_render < 120.0, f"render too slow: {ms_per_render:.1f} ms"


def test_pdf_export_with_flags_unchanged(qapp, tmp_path: Path) -> None:
    match = _match_row()
    rows = _diff_rows()
    view = Postplot4DStatPlotView()
    view.resize(1100, 820)
    view.set_data(match, rows, streamers_detected=False)
    view._survey_panel.set_rows(
        [
            SurveySpecRow(
                statistic=StatType.MAX_VALUE,
                metric="radial",
                stat_value=12.0,
                absolute=True,
                severity=Severity.WARNING,
            )
        ]
    )
    view._evaluate_survey()
    view._refresh_all_tabs()
    qapp.processEvents()

    canvas = view.canvas_for_kind("radial")
    assert canvas is not None
    assert canvas._combined_plot is not None
    assert canvas._combined_plot._flag_items, "flags should render before PDF"

    pdf_path = tmp_path / "flag_test.pdf"
    options = Postplot4DStatPlotPdfOptions(
        output_dir=tmp_path,
        filename=pdf_path.name,
        include_crossline=False,
        include_inline=False,
        include_radial=True,
        include_feather=False,
        include_feather_diff=False,
    )
    export_4d_stat_plot_pdf(view, pdf_path, options)
    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 5000

    image = canvas.capture_image(width=900, height=420, for_pdf=True, dpi=120)
    assert not image.isNull()
    assert _non_white_fraction(image) > 0.01


def _non_white_fraction(image: QImage) -> float:
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        return 0.0
    non_white = 0
    sampled = 0
    for y in range(0, height, 3):
        for x in range(0, width, 3):
            sampled += 1
            color = image.pixelColor(x, y)
            if color.red() < 250 or color.green() < 250 or color.blue() < 250:
                non_white += 1
    return non_white / max(sampled, 1)
