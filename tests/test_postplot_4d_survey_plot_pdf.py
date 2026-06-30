"""Tests for survey plot PDF options."""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet
from xpostmaps.core.postplot_4d_survey_plot_data import AerialHeatmapData
from xpostmaps.core.postplot_4d_survey_plot_pdf import (
    Postplot4DSurveyPlotPdfOptions,
    iter_survey_plot_page_specs,
    resolve_survey_plot_output_path,
)
from xpostmaps.core.survey_plot_pdf_guardrails import validate_aerial_plot_body
from xpostmaps.ui.postplot_4d_survey_plots.aerial_heatmap_canvas import (
    AerialHeatmapCanvas,
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


def _synthetic_aerial_heatmap() -> AerialHeatmapData:
    rows, cols = 48, 28
    grid = np.linspace(-12.0, 12.0, rows * cols, dtype=np.float64).reshape(rows, cols)
    return AerialHeatmapData(
        image=grid,
        sequence_labels=[str(1000 + index) for index in range(cols)],
        sequence_min=1000,
        sequence_max=1000 + cols - 1,
        shot_min=500,
        shot_max=500 + rows - 1,
        value_limit=15.0,
        source_no="001",
        kind="crossline",
        map_label="Synthetic aerial regression grid",
    )


@pytest.mark.parametrize("dpi", [150, 600])
def test_aerial_pdf_capture_fills_plot_band_at_export_sizes(dpi: int) -> None:
    """Guardrail: PDF aerial raster must fill the plot band even on a small widget."""
    qapp = QApplication.instance() or QApplication([])
    canvas = AerialHeatmapCanvas()
    canvas.resize(320, 240)
    canvas.show()
    qapp.processEvents()

    canvas.render(_synthetic_aerial_heatmap())
    qapp.processEvents()

    plot_w = 1800 if dpi >= 600 else 900
    plot_h = 1100 if dpi >= 600 else 650
    body = canvas.capture_image(
        width=plot_w,
        height=plot_h,
        for_pdf=True,
        dpi=dpi,
    )
    assert not body.isNull()

    errors = validate_aerial_plot_body(body, page_key=f"aerial@{dpi}dpi")
    assert not errors, "; ".join(errors)
