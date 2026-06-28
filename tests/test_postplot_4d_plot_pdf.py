"""Tests for 4D Stat plot PDF options."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from xpostmaps.core.postplot_4d_plot_pdf import (
    Postplot4DStatPlotPdfOptions,
    render_4d_stat_plot_preview_pages,
    resolve_4d_stat_output_path,
    resolved_plot_kinds,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakePlotView:
    def __init__(self, kinds: list[str]) -> None:
        self._kinds = kinds

    def available_plot_kinds(self) -> list[str]:
        return list(self._kinds)


def test_resolved_plot_kinds_respects_checkboxes() -> None:
    view = _FakePlotView(["crossline", "inline", "radial"])
    options = Postplot4DStatPlotPdfOptions(
        output_dir=Path("."),
        filename="out.pdf",
        include_crossline=True,
        include_inline=False,
        include_radial=True,
        include_feather=True,
    )
    assert resolved_plot_kinds(view, options) == ["crossline", "radial"]


def test_resolved_plot_kinds_skips_unavailable_feather() -> None:
    view = _FakePlotView(["crossline", "inline", "radial"])
    options = Postplot4DStatPlotPdfOptions(
        output_dir=Path("."),
        filename="out.pdf",
        include_feather=True,
    )
    assert resolved_plot_kinds(view, options) == ["crossline", "inline", "radial"]


def test_render_preview_pages_without_selection_returns_placeholder(qapp) -> None:
    view = _FakePlotView(["crossline", "inline"])
    options = Postplot4DStatPlotPdfOptions(
        output_dir=Path("."),
        filename="out.pdf",
        include_crossline=False,
        include_inline=False,
        include_radial=False,
        include_feather=False,
        include_feather_diff=False,
    )
    pages = render_4d_stat_plot_preview_pages(view, options)
    assert len(pages) == 1
    assert not pages[0].isNull()


def test_resolve_4d_stat_output_path_adds_extension() -> None:
    options = Postplot4DStatPlotPdfOptions(
        output_dir=Path("/tmp"),
        filename="line_plot",
    )
    assert resolve_4d_stat_output_path(options) == Path("/tmp/line_plot.pdf")
