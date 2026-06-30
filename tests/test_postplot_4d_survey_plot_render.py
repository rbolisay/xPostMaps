"""Render tests for survey-wide 4D plots view."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet
from xpostmaps.ui.postplot_4d_survey_plots.survey_plots_view import Postplot4DSurveyPlotsView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _sample_set() -> SequenceDiffSet:
    match = Postplot4DMatchRow(
        baseline_name="1065P1A",
        baseline_kind="navplan",
        line_name="1065P1A",
        subline="070",
        sequence_no="070",
        first_sp=1000,
        last_sp=1010,
        line_direction="Up-line",
        sequence_id="seq-070",
    )
    rows = [
        Postplot4DDiffRow(
            shotpoint=1000 + index,
            baseline_x=0.0,
            baseline_y=0.0,
            baseline_latitude="",
            baseline_longitude="",
            source_x=0.0,
            source_y=0.0,
            source_latitude="",
            source_longitude="",
            crossline_m=float(index) * 0.5,
            inline_m=float(index) * 0.2,
            radial_m=float(index) * 0.3,
            firing_source_id="001",
        )
        for index in range(11)
    ]
    return SequenceDiffSet(match_row=match, diff_rows=rows)


def _build_load_result(sets, kinds):
    from xpostmaps.core.postplot_4d_survey_plot_data import (
        build_survey_aerial_heatmap_cache,
        build_survey_histogram_cache,
        build_survey_metrics_cache,
        infer_streamers_detected,
        survey_spec_pie_charts,
    )
    from xpostmaps.core.postplot_4d_survey_plots_worker import SurveyPlotsLoadResult

    metric_values = build_survey_metrics_cache(sets, kinds)
    return SurveyPlotsLoadResult(
        sets=sets,
        streamers_detected=infer_streamers_detected(sets),
        available_kinds=kinds,
        metric_values=metric_values,
        heatmap_cache=build_survey_aerial_heatmap_cache(sets, kinds),
        histogram_cache=build_survey_histogram_cache(metric_values, kinds),
        pie_charts=survey_spec_pie_charts(sets, metric_cache=metric_values),
        sequence_count=len(sets),
        shotpoint_count=sum(len(s.diff_rows) for s in sets),
    )


def test_survey_plots_view_renders_tabs(qapp) -> None:
    view = Postplot4DSurveyPlotsView()
    view.resize(1024, 720)
    sample = _sample_set()
    kinds = ["crossline", "inline", "radial"]
    result = _build_load_result([sample], kinds)
    view.apply_load_result(result)
    view.show()
    qapp.processEvents()
    assert view.available_plot_kinds() == ["crossline", "inline", "radial"]
    assert view._tabs.count() == 6
    panel = view._metric_panels["crossline"]
    assert panel.sub_tabs.count() == 2
    aerial = view.aerial_canvas("crossline")
    assert aerial is not None
    hist = view.histogram_canvas("crossline")
    assert hist is not None
    view.refresh_current_tab()
    qapp.processEvents()
    from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_navigation import SurveyPlotViewBox

    assert isinstance(aerial._viewbox, SurveyPlotViewBox)
    assert isinstance(hist._viewbox, SurveyPlotViewBox)
    image = aerial.capture_image(width=640, height=360, title="Test")
    assert not image.isNull()
    image = hist.capture_image(width=640, height=360, title="Test")
    assert not image.isNull()
