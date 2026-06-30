"""Tests for survey plot database cache."""

from __future__ import annotations

import numpy as np
import pytest

from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet
from xpostmaps.core.postplot_4d_survey_plot_cache import (
    compute_source_fingerprint,
    deserialize_survey_plot_cache,
    merge_cache_with_sets,
    serialize_survey_plot_cache,
)
from xpostmaps.core.postplot_4d_survey_plot_data import (
    AerialHeatmapData,
    CumulativeHistogram,
    SurveyPlotsLoadResult,
)


def _make_match() -> Postplot4DMatchRow:
    return Postplot4DMatchRow(
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


def _make_result() -> SurveyPlotsLoadResult:
    match = _make_match()
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
    sets = [SequenceDiffSet(match_row=match, diff_rows=rows)]
    grid = np.array([[1.0, np.nan], [0.5, 1.5]], dtype=np.float64)
    heatmap = AerialHeatmapData(
        image=grid,
        sequence_labels=["1", "2"],
        sequence_min=1,
        sequence_max=2,
        shot_min=1000,
        shot_max=1001,
        value_limit=15.0,
        source_no="G01",
        kind="crossline",
        map_label="Test map",
    )
    histogram = CumulativeHistogram(
        bucket_labels=["0", "1"],
        cumulative_pct=[50.0, 100.0],
        sample_count=1,
    )
    return SurveyPlotsLoadResult(
        sets=sets,
        streamers_detected=False,
        available_kinds=["crossline"],
        metric_values={"crossline": [1.0]},
        heatmap_cache={"crossline": heatmap},
        histogram_cache={"crossline": histogram},
        pie_charts=[],
        sequence_count=1,
        shotpoint_count=1,
    )


def test_survey_plot_cache_roundtrip() -> None:
    result = _make_result()
    fingerprint = "abc123"
    payload = serialize_survey_plot_cache(result, fingerprint=fingerprint)
    restored = deserialize_survey_plot_cache(payload)
    assert restored is not None
    assert restored.fingerprint == fingerprint
    assert restored.available_kinds == ["crossline"]
    assert restored.heatmap_cache["crossline"].map_label == "Test map"
    image = np.asarray(restored.heatmap_cache["crossline"].image)
    assert image.shape == (2, 2)
    assert np.isnan(image[0, 1])


def test_merge_cache_with_sets_uses_fresh_sets() -> None:
    result = _make_result()
    cached = deserialize_survey_plot_cache(
        serialize_survey_plot_cache(result, fingerprint="fp1")
    )
    assert cached is not None
    merged = merge_cache_with_sets(cached, result)
    assert merged.sets == result.sets
    assert merged.heatmap_cache["crossline"].map_label == "Test map"


def test_database_save_and_load_survey_plot_cache(tmp_path) -> None:
    from xpostmaps.core.models import MapData, ProjectSettings

    db_path = tmp_path / "cache.db"
    database = Database(db_path)
    database.save_project(ProjectSettings(name="Demo"), MapData())

    payload = serialize_survey_plot_cache(_make_result(), fingerprint="demo")
    database.save_survey_plot_cache("Demo", "navplan", fingerprint="demo", payload=payload)
    loaded = database.load_survey_plot_cache("Demo", "navplan")
    assert loaded == payload


def test_source_fingerprint_changes_when_match_rows_change() -> None:
    match_a = _make_match()
    match_b = Postplot4DMatchRow(
        baseline_name="LineB",
        baseline_kind="navplan",
        line_name="LineB",
        subline="002",
        sequence_no="002",
        first_sp=2000,
        last_sp=2001,
        line_direction="Up-line",
        sequence_id="seq-002",
    )
    fp_a = compute_source_fingerprint(
        baseline_kind="navplan",
        match_rows=[match_a],
        diff_signature="sig",
    )
    fp_b = compute_source_fingerprint(
        baseline_kind="navplan",
        match_rows=[match_a, match_b],
        diff_signature="sig",
    )
    assert fp_a != fp_b
