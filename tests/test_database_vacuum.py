"""Tests for database compaction after large deletes."""

from __future__ import annotations

from pathlib import Path

from xpostmaps.core.database import Database
from xpostmaps.core.models import MapData, ProjectSettings, RecordType


def _seed_preplot_cache(db: Database, project_name: str, rows: int) -> None:
    project_id = db.get_project_id(project_name)
    assert project_id is not None
    now = db._now()
    payload = [
        (
            project_id,
            "preplot/test.190",
            "test.190",
            "LINE01",
            1.0,
            1000,
            float(i),
            1,
            0,
            float(i),
            float(i),
            None,
            None,
            25.0,
            "090",
            1,
            12.5,
            now,
        )
        for i in range(rows)
    ]
    db._conn.executemany(
        """
        INSERT INTO postplot_4d_preplot_shotpoints (
            project_id, file_path, file_name, line_name, file_mtime, file_size,
            shotpoint, source_id, source_index, x, y, latitude, longitude,
            shotpoint_interval_m, line_direction, source_count,
            source_separation_m, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    db._conn.commit()


def test_clear_preplot_cache_and_vacuum_shrinks_file(tmp_path: Path) -> None:
    db_path = tmp_path / "compact_test.db"
    db = Database(db_path)
    project_name = "VacuumTest"
    db.save_project(ProjectSettings(name=project_name), MapData())

    _seed_preplot_cache(db, project_name, rows=5_000)
    size_before = db.file_size_bytes()
    assert size_before > 0

    deleted = db.clear_postplot_4d_preplot_shotpoints(project_name)
    assert deleted == 5_000

    size_after_delete = db.file_size_bytes()
    assert size_after_delete >= size_before * 0.9

    size_after_vacuum = db.vacuum()
    assert size_after_vacuum < size_after_delete


def test_load_source_positions_for_sequence_ids_only_returns_requested_sources(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "source_positions.db")
    project_name = "SourceLoadTest"
    db.save_project(ProjectSettings(name=project_name), MapData())
    project_id = db.get_project_id(project_name)
    assert project_id is not None

    db._conn.executemany(
        """
        INSERT INTO positions (
            project_id, file_name, record_type, sequence_no, line_name,
            line_direction, subline, point_num, x, y, depth, latitude,
            longitude, vessel_id, source_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                project_id,
                "line.p190",
                RecordType.SOURCE.value,
                "0001",
                "LINE01",
                "",
                "",
                1001,
                1.0,
                2.0,
                None,
                "",
                "",
                "",
                "1",
            ),
            (
                project_id,
                "line.p190",
                RecordType.VESSEL.value,
                "0001",
                "LINE01",
                "",
                "",
                1001,
                1.0,
                2.0,
                None,
                "",
                "",
                "",
                "",
            ),
            (
                project_id,
                "other.p190",
                RecordType.SOURCE.value,
                "0002",
                "LINE02",
                "",
                "",
                2001,
                3.0,
                4.0,
                None,
                "",
                "",
                "",
                "1",
            ),
        ],
    )
    db._conn.commit()

    rows = db.load_source_positions_for_sequence_ids(
        project_name,
        ["line.p190|0001|LINE01|source"],
    )

    assert len(rows) == 1
    assert rows[0].record_type == RecordType.SOURCE
    assert rows[0].file_name == "line.p190"
    assert rows[0].point_num == 1001
