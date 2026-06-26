"""Tests for parallel Diff Stat recalculation worker helpers."""

from __future__ import annotations

from xpostmaps.core.models import MapData, PositionRecord, ProjectSettings, RecordType
from xpostmaps.core.postplot_4d_diff_worker import diff_stat_worker_count
from xpostmaps.core.postplot_4d_diff_worker import DiffStatRecalcWorker
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow


def test_diff_stat_worker_count_single_task() -> None:
    assert diff_stat_worker_count(0) == 1
    assert diff_stat_worker_count(1) == 1


def test_diff_stat_worker_count_caps_at_eight() -> None:
    assert diff_stat_worker_count(100) <= 8
    assert diff_stat_worker_count(100) >= 1


def test_worker_filters_positions_by_sequence_group() -> None:
    worker = DiffStatRecalcWorker(
        lambda: MapData(),
        ProjectSettings(),
        lambda: [],
    )
    positions = [
        PositionRecord(
            file_name="line.p190",
            record_type=RecordType.SOURCE,
            line_name="LINE01",
            vessel_id="",
            source_id="1",
            point_num=1001,
            x=1.0,
            y=2.0,
            sequence_no="0001",
        ),
        PositionRecord(
            file_name="line.p190",
            record_type=RecordType.VESSEL,
            line_name="LINE01",
            vessel_id="",
            source_id="",
            point_num=1001,
            x=1.0,
            y=2.0,
            sequence_no="0001",
        ),
        PositionRecord(
            file_name="other.p190",
            record_type=RecordType.SOURCE,
            line_name="LINE02",
            vessel_id="",
            source_id="1",
            point_num=2001,
            x=3.0,
            y=4.0,
            sequence_no="0002",
        ),
    ]
    worker._source_positions_by_group = worker._build_source_index(positions)

    match = Postplot4DMatchRow(
        baseline_name="LINE01",
        baseline_kind="preplot",
        line_name="LINE01",
        subline="",
        sequence_no="0001",
        first_sp=1001,
        last_sp=1001,
        line_direction="",
        sequence_id="line.p190|0001|LINE01|source",
    )

    assert worker._positions_for_match(match) == [positions[0]]
