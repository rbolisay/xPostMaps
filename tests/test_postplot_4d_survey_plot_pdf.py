"""Tests for survey plot PDF options."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet
from xpostmaps.core.postplot_4d_survey_plot_pdf import (
    Postplot4DSurveyPlotPdfOptions,
    iter_survey_plot_page_specs,
    resolve_survey_plot_output_path,
)


def _make_set() -> SequenceDiffSet:
    match = Postplot4DMatchRow(
        baseline_name="LineA",
        baseline_kind="navplan",
        line_name="LineA",
        subline="001",
        sequence_no="001",
        first_sp=1000,
        last_sp=1001,
        line_direction="Up-line",
        sequence_id="seq-001",
    )
    rows = [
        Postplot4DDiffRow(
            shotpoint=1000,
            baseline_x=0.0,
            baseline_y=0.0,
            baseline_latitude="",
            baseline_longitude="",
            source_x=0.0,
            source_y=0.0,
            source_latitude="",
            source_longitude="",
            crossline_m=1.0,
            inline_m=0.5,
            radial_m=1.0,
            firing_source_id="001",
        )
    ]
    return SequenceDiffSet(match_row=match, diff_rows=rows)


from types import SimpleNamespace

class _FakeSurveyView:
    def __init__(self, kinds: list[str]) -> None:
        self._kinds = kinds
        self._sets = [_make_set()]

    def diff_sets(self) -> list:
        return self._sets

    def aerial_title(self, kind: str) -> str:
        return f"{kind} aerial"

    def histogram_title(self, kind: str) -> str:
        return f"{kind} histogram"

    def available_plot_kinds(self) -> list[str]:
        return list(self._kinds)

    def metric_cache(self) -> dict:
        return {}

    def heatmap_cache(self) -> dict:
        return {
            kind: SimpleNamespace(header_title="Aerial View", map_label=f"{kind} aerial")
            for kind in self._kinds
        }

    def histogram_cache(self) -> dict:
        return {kind: object() for kind in self._kinds}

    def pie_charts(self) -> list:
        return []


def test_resolve_survey_plot_output_path_adds_extension() -> None:
    options = Postplot4DSurveyPlotPdfOptions(
        output_dir=Path("out"),
        filename="report",
    )
    assert resolve_survey_plot_output_path(options) == Path("out/report.pdf")


def test_render_pyqtgraph_plot_for_pdf_restores_axis_font() -> None:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_navigation import (
        create_survey_plot_widget,
    )
    from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_pdf_render import (
        _SCREEN_AXIS_FONT,
        render_pyqtgraph_plot_for_pdf,
    )

    qapp = QApplication.instance() or QApplication([])
    plot, _viewbox = create_survey_plot_widget(background="#ffffff")
    plot.resize(640, 420)
    plot.show()
    qapp.processEvents()

    left_axis = plot.getPlotItem().getAxis("left")
    left_axis.setStyle(tickFont=QFont(_SCREEN_AXIS_FONT))
    before = left_axis.style["tickFont"].pixelSize()

    render_pyqtgraph_plot_for_pdf(plot, width=900, height=500, dpi=150)
    QApplication.processEvents()

    after = left_axis.style["tickFont"].pixelSize()
    assert after == before


def test_iter_survey_plot_page_specs_respects_flags() -> None:
    view = _FakeSurveyView(["crossline", "inline"])
    options = Postplot4DSurveyPlotPdfOptions(
        output_dir=Path("."),
        filename="out.pdf",
        include_aerial_crossline=True,
        include_aerial_inline=False,
        include_histogram_crossline=False,
        include_histogram_inline=True,
        include_survey_specs_pie=False,
    )
    specs = iter_survey_plot_page_specs(view, options)
    keys = [spec.page_key for spec in specs]
    assert keys == ["aerial:crossline", "histogram:inline"]
    titles = {spec.page_key: spec.plot_title for spec in specs}
    assert titles["aerial:crossline"] == "crossline aerial"
    assert titles["histogram:inline"] == "inline histogram"
