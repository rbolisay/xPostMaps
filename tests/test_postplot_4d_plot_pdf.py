"""Tests for 4D Stat plot PDF options."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from xpostmaps.core.postplot_4d_plot_pdf import (
    DEFAULT_4D_STAT_PDF_REPORT_TITLE,
    STAT_PLOT_PDF_DEFAULT_DPI,
    Postplot4DStatPlotPdfOptions,
    _page_layout_pixels,
    compose_4d_stat_plot_pages,
    render_4d_stat_plot_preview_pages,
    resolve_4d_stat_output_path,
    resolve_logo_path,
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
    assert not pages[0].image.isNull()


def test_resolve_4d_stat_output_path_adds_extension() -> None:
    options = Postplot4DStatPlotPdfOptions(
        output_dir=Path("/tmp"),
        filename="line_plot",
    )
    assert resolve_4d_stat_output_path(options) == Path("/tmp/line_plot.pdf")


def test_landscape_layout_is_wider_than_tall() -> None:
    options = Postplot4DStatPlotPdfOptions(
        output_dir=Path("."),
        filename="out.pdf",
        landscape=True,
    )
    page_w, page_h, *_ = _page_layout_pixels(options, dpi=120)
    assert page_w > page_h


def test_portrait_layout_is_taller_than_wide() -> None:
    options = Postplot4DStatPlotPdfOptions(
        output_dir=Path("."),
        filename="out.pdf",
        landscape=False,
    )
    page_w, page_h, *_ = _page_layout_pixels(options, dpi=120)
    assert page_h > page_w


def test_resolve_logo_path_falls_back_to_repo_logo() -> None:
    logo = resolve_logo_path("")
    assert logo is not None
    assert logo.is_file()


def test_default_report_title() -> None:
    options = Postplot4DStatPlotPdfOptions(
        output_dir=Path("."),
        filename="out.pdf",
    )
    assert options.report_title == DEFAULT_4D_STAT_PDF_REPORT_TITLE
    assert options.landscape is True
    assert options.dpi == STAT_PLOT_PDF_DEFAULT_DPI
