"""Navigation tests for survey plot pan/zoom."""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_navigation import (
    SurveyPlotViewBox,
    apply_plot_extent,
    create_survey_plot_widget,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_survey_plot_viewbox_menu_source_has_reset_only() -> None:
    source = inspect.getsource(SurveyPlotViewBox._show_pending_menu)
    assert "Reset Zoom" in source
    assert "Zoom Window" not in source
    assert "Zoom Extent" not in source


def test_survey_plot_pan_scroll_and_reset_extent(qapp) -> None:
    plot, viewbox = create_survey_plot_widget(background="#ffffff")
    plot.resize(800, 600)
    plot.show()
    qapp.processEvents()

    apply_plot_extent(viewbox, (0.0, 10.0), (0.0, 100.0))
    start_x, start_y = viewbox.viewRange()

    viewbox.translateBy(x=1.0, y=5.0)
    panned_x, panned_y = viewbox.viewRange()
    assert panned_x != pytest.approx(start_x, rel=0, abs=1e-6)
    assert panned_y != pytest.approx(start_y, rel=0, abs=1e-6)

    viewbox.scaleBy((0.5, 0.5))
    qapp.processEvents()
    zoomed_x, zoomed_y = viewbox.viewRange()
    assert (zoomed_x[1] - zoomed_x[0]) < (start_x[1] - start_x[0])
    assert (zoomed_y[1] - zoomed_y[0]) < (start_y[1] - start_y[0])

    viewbox.zoom_to_extent()
    reset_x, reset_y = viewbox.viewRange()
    assert reset_x == pytest.approx(start_x)
    assert reset_y == pytest.approx(start_y)
