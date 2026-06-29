"""Tests for 4D Stat plot data helpers."""

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import (
    build_plot_series,
    compute_series_stats,
    feather_diff_tab_available,
    normalize_source_label,
    shotpoint_order,
    unique_sources_from_diff_rows,
)


def _diff_row(
    shotpoint: int,
    source_id: str,
    *,
    crossline: float = 1.0,
    feather: float | None = None,
    navplan_feather: float | None = None,
) -> Postplot4DDiffRow:
    return Postplot4DDiffRow(
        shotpoint=shotpoint,
        baseline_x=0.0,
        baseline_y=0.0,
        baseline_latitude="",
        baseline_longitude="",
        source_x=0.0,
        source_y=0.0,
        source_latitude="",
        source_longitude="",
        crossline_m=crossline,
        inline_m=0.0,
        radial_m=0.0,
        navplan_feather_deg=navplan_feather,
        line_feather_deg=feather,
        firing_source_id=source_id,
    )


def test_default_pdf_time_series_description_uses_sources_and_metric() -> None:
    from xpostmaps.core.postplot_4d_plot_data import default_pdf_time_series_description

    match = Postplot4DMatchRow(
        baseline_name="Base",
        baseline_kind="navplan",
        line_name="LineA",
        subline="a070",
        sequence_no="1",
        first_sp=100,
        last_sp=110,
        line_direction="Up-line",
        sequence_id="file|1|LineA",
    )
    text = default_pdf_time_series_description(
        match,
        source_nos=["G01", "G02"],
        kind="crossline",
    )
    assert text == "G01, G02 Position Cross-line vs. Baseline (Up-line)"


def test_pdf_page_key_includes_source_when_uncombined() -> None:
    from xpostmaps.core.postplot_4d_plot_data import pdf_page_key

    assert pdf_page_key("inline", "G01", combine=False) == "inline:G01"
    assert pdf_page_key("inline", "G01", combine=True) == "inline"
    assert normalize_source_label("001") == "G01"
    assert normalize_source_label("G002") == "G02"
    assert normalize_source_label("S3") == "G03"


def test_shotpoint_order_follows_fsp_to_lsp_descending() -> None:
    match = Postplot4DMatchRow(
        baseline_name="Base",
        baseline_kind="navplan",
        line_name="0108491B",
        subline="",
        sequence_no="074",
        first_sp=1800,
        last_sp=1500,
        line_direction="Down-line",
        sequence_id="file|074|0108491B",
    )
    rows = [_diff_row(1500, "001"), _diff_row(1600, "001"), _diff_row(1700, "001")]
    assert shotpoint_order(rows, match) == [1700, 1600, 1500]


def test_build_plot_series_groups_by_source() -> None:
    match = Postplot4DMatchRow(
        baseline_name="Base",
        baseline_kind="navplan",
        line_name="Line",
        subline="",
        sequence_no="1",
        first_sp=100,
        last_sp=102,
        line_direction="Up-line",
        sequence_id="file|1|Line",
    )
    rows = [
        _diff_row(100, "001", crossline=1.0),
        _diff_row(101, "002", crossline=2.0),
        _diff_row(102, "001", crossline=3.0),
    ]
    sources = unique_sources_from_diff_rows(rows)
    assert sources == ["G01", "G02"]
    g01 = build_plot_series(rows, match, "crossline", "G01")
    assert g01.shotpoints == [100, 102]
    assert g01.values == [1.0, 3.0]


def test_compute_series_stats() -> None:
    stats = compute_series_stats("G01", [-2.0, 0.0, 2.0])
    assert stats is not None
    assert stats.minimum == -2.0
    assert stats.maximum == 2.0
    assert stats.mean == 0.0
    assert round(stats.rms, 2) == 1.63


def test_build_feather_diff_series() -> None:
    match = Postplot4DMatchRow(
        baseline_name="Base",
        baseline_kind="navplan",
        line_name="Line",
        subline="",
        sequence_no="1",
        first_sp=100,
        last_sp=101,
        line_direction="Up-line",
        sequence_id="file|1|Line",
    )
    rows = [
        _diff_row(100, "001", navplan_feather=1.25, feather=-2.5),
        _diff_row(101, "001", navplan_feather=2.0, feather=0.0),
    ]
    series = build_plot_series(rows, match, "feather_diff", "G01")
    assert series.shotpoints == [100, 101]
    assert series.values == [-3.75, -2.0]


def test_feather_diff_tab_requires_navplan_and_streamers() -> None:
    navplan_match = Postplot4DMatchRow(
        baseline_name="Base",
        baseline_kind="navplan",
        line_name="Line",
        subline="",
        sequence_no="1",
        first_sp=100,
        last_sp=101,
        line_direction="Up-line",
        sequence_id="file|1|Line",
    )
    preplot_match = Postplot4DMatchRow(
        baseline_name="Base",
        baseline_kind="preplot",
        line_name="Line",
        subline="",
        sequence_no="1",
        first_sp=100,
        last_sp=101,
        line_direction="Up-line",
        sequence_id="file|1|Line",
    )
    assert feather_diff_tab_available(navplan_match, streamers_detected=True)
    assert not feather_diff_tab_available(navplan_match, streamers_detected=False)
    assert not feather_diff_tab_available(preplot_match, streamers_detected=True)
    assert not feather_diff_tab_available(None, streamers_detected=True)
