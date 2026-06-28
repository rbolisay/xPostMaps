"""Tests for 4D Stat plot PDF options."""

from pathlib import Path

from xpostmaps.core.postplot_4d_plot_pdf import (
    Postplot4DStatPlotPdfOptions,
    resolve_4d_stat_output_path,
    resolved_plot_kinds,
)


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


def test_resolve_4d_stat_output_path_adds_extension() -> None:
    options = Postplot4DStatPlotPdfOptions(
        output_dir=Path("/tmp"),
        filename="line_plot",
    )
    assert resolve_4d_stat_output_path(options) == Path("/tmp/line_plot.pdf")
