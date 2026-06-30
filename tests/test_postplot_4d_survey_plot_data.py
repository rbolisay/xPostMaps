"""Tests for survey-wide 4D plot data helpers."""

import numpy as np

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet
from xpostmaps.core.postplot_4d_survey_plot_data import (
    cumulative_histogram,
    survey_metric_values,
    survey_spec_pie_charts,
)
from xpostmaps.core.postplot_4d_survey_spec import Severity, StatType, SurveySpecRow


def _make_set(values: list[float]) -> SequenceDiffSet:
    match = Postplot4DMatchRow(
        baseline_name="LineA",
        baseline_kind="navplan",
        line_name="LineA",
        subline="001",
        sequence_no="001",
        first_sp=1000,
        last_sp=1000 + len(values) - 1,
        line_direction="Up-line",
        sequence_id="seq-001",
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
            crossline_m=value,
            inline_m=value * 0.5,
            radial_m=abs(value),
            firing_source_id="001",
        )
        for index, value in enumerate(values)
    ]
    return SequenceDiffSet(match_row=match, diff_rows=rows)


def test_fill_aerial_heatmap_gaps() -> None:
    from xpostmaps.core.postplot_4d_survey_plot_data import fill_aerial_heatmap_gaps

    grid = np.full((3, 3), np.nan, dtype=np.float64)
    grid[0, 0] = 1.0
    grid[2, 0] = 3.0
    grid[0, 2] = 5.0
    grid[2, 2] = 7.0
    filled = fill_aerial_heatmap_gaps(grid)
    assert np.isfinite(filled[1, 0])
    assert np.isfinite(filled[1, 2])
    assert not np.isfinite(filled[0, 1])
    assert filled[0, 0] == 1.0
    assert filled[2, 2] == 7.0


def test_combined_survey_extent_axes() -> None:
    from xpostmaps.core.postplot_4d_survey_plot_data import (
        build_survey_aerial_heatmap,
        combined_survey_extent,
        validate_aerial_heatmap_axes,
    )

    sets = [_make_set([1.0, -2.0, 3.0])]
    extent = combined_survey_extent(sets)
    assert extent.sequence_count == 1
    assert extent.sequence_labels == ["LineA"]
    assert extent.shot_min == 1000
    assert extent.shot_max == 1002
    assert extent.shotpoint_row_count == 3
    heatmap = build_survey_aerial_heatmap(sets, "crossline")
    assert heatmap is not None
    assert heatmap.sequence_labels == ["LineA"]
    assert heatmap.shot_min == 1000
    assert heatmap.shot_max == 1002
    assert validate_aerial_heatmap_axes(heatmap, extent) == []


def test_build_survey_aerial_heatmap_axes() -> None:
    from xpostmaps.core.postplot_4d_survey_plot_data import build_survey_aerial_heatmap

    sets = [_make_set([1.0, -2.0, 3.0])]
    heatmap = build_survey_aerial_heatmap(sets, "crossline")
    assert heatmap is not None
    assert heatmap.sequence_labels == ["LineA"]
    assert heatmap.shot_min == 1000
    assert heatmap.shot_max == 1002
    assert heatmap.image.shape == (3, 1)


def test_preplot_column_layers_sequences() -> None:
    from xpostmaps.core.postplot_4d_survey_plot_data import build_survey_aerial_heatmap

    def _set_for_sequence(
        sequence_no: str,
        *,
        shotpoint: int,
        value: float,
    ) -> SequenceDiffSet:
        match = Postplot4DMatchRow(
            baseline_name="1305R1",
            baseline_kind="navplan",
            line_name="AcqLine",
            subline="001",
            sequence_no=sequence_no,
            first_sp=shotpoint,
            last_sp=shotpoint,
            line_direction="Up-line",
            sequence_id=f"seq-{sequence_no}",
        )
        row = Postplot4DDiffRow(
            shotpoint=shotpoint,
            baseline_x=0.0,
            baseline_y=0.0,
            baseline_latitude="",
            baseline_longitude="",
            source_x=0.0,
            source_y=0.0,
            source_latitude="",
            source_longitude="",
            crossline_m=value,
            inline_m=value,
            radial_m=value,
            firing_source_id="001",
        )
        return SequenceDiffSet(match_row=match, diff_rows=[row])

    sets = [
        _set_for_sequence("1", shotpoint=1000, value=1.0),
        _set_for_sequence("1", shotpoint=1001, value=11.0),
        _set_for_sequence("3", shotpoint=1000, value=3.0),
        _set_for_sequence("5", shotpoint=1000, value=5.0),
    ]
    heatmap = build_survey_aerial_heatmap(sets, "crossline")
    assert heatmap is not None
    assert heatmap.sequence_labels == ["1305R1"]
    assert heatmap.image.shape == (2, 1)
    grid = np.asarray(heatmap.image)
    assert float(grid[1, 0]) == 5.0
    assert float(grid[0, 0]) == 11.0


def test_cumulative_histogram_degrees_axis() -> None:
    from xpostmaps.core.postplot_4d_survey_plot_data import cumulative_histogram_degrees

    hist = cumulative_histogram_degrees([-13.6, -5.0, 0.0, 17.0])
    assert hist.x_axis_unit == "degrees"
    assert hist.bucket_labels == [str(value) for value in range(-14, 18)]
    assert hist.x_positions == [float(value) for value in range(-14, 18)]
    assert len(hist.bucket_labels) == 32
    assert hist.cumulative_pct[-1] == 100.0
    for earlier, later in zip(hist.cumulative_pct, hist.cumulative_pct[1:], strict=False):
        assert later >= earlier


def test_cumulative_histogram_monotonic() -> None:
    hist = cumulative_histogram([0.2, 0.8, 1.5, 4.0, 20.0])
    assert hist.sample_count == 5
    assert len(hist.bucket_labels) == 17
    assert hist.cumulative_pct[0] == 40.0
    assert hist.cumulative_pct[-1] == 100.0
    for earlier, later in zip(hist.cumulative_pct, hist.cumulative_pct[1:], strict=False):
        assert later >= earlier


def test_histogram_plot_title_format() -> None:
    from xpostmaps.core.postplot_4d_survey_plot_data import (
        aerial_map_label,
        histogram_plot_title,
    )

    sets = [_make_set([1.0, 2.0])]
    assert (
        histogram_plot_title(sets, "crossline")
        == "Cumulative Histogram: Source Position Crossline vs Baseline (Absolute Values)"
    )
    assert (
        histogram_plot_title(sets, "inline")
        == "Cumulative Histogram: Source Position Inline vs Baseline (Absolute Values)"
    )
    assert aerial_map_label(sets, "crossline") == (
        "Areal Map: Position Crossline [meter] for G01 vs. Baseline (absolute values)"
    )
    sets = [_make_set([1.0, 2.0]), _make_set([3.0])]
    values = survey_metric_values(sets, "crossline")
    assert values == [1.0, 2.0, 3.0]


def test_survey_spec_pie_pass_fail_slices() -> None:
    sets = [_make_set([0.5, 1.0, 2.0, 5.0])]
    specs = [
        SurveySpecRow(
            metric="crossline",
            statistic=StatType.MAX_VALUE,
            stat_value=1.5,
            absolute=True,
        )
    ]
    charts = survey_spec_pie_charts(sets, specs)
    assert len(charts) == 1
    assert charts[0].headline == "4D Survey Statistic"
    assert charts[0].stats is not None
    assert charts[0].stats.pass_count + charts[0].stats.fail_count == 4
    labels = {slice_.label: slice_.value for slice_ in charts[0].slices}
    assert labels["Pass"] == 50.0
    assert labels["Fail"] == 50.0
    fail_slice = next(slice_ for slice_ in charts[0].slices if slice_.label == "Fail")
    assert fail_slice.color == "#ef4444"


def test_survey_spec_pie_warning_fail_color() -> None:
    sets = [_make_set([0.5, 1.0, 2.0, 5.0])]
    specs = [
        SurveySpecRow(
            metric="crossline",
            statistic=StatType.MAX_VALUE,
            stat_value=1.5,
            absolute=True,
            severity=Severity.WARNING,
        )
    ]
    charts = survey_spec_pie_charts(sets, specs)
    fail_slice = next(slice_ for slice_ in charts[0].slices if slice_.label == "Fail")
    assert fail_slice.color == "#f97316"
    assert charts[0].fail_color == "#f97316"
    assert charts[0].severity == Severity.WARNING
