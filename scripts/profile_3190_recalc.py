"""Profile 3190.db Postplot 4D Diff Stat recalculation phases."""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.core.postplot_4d_diff import calculate_match_diff_rows  # noqa: E402
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows  # noqa: E402
from xpostmaps.core.postplot_4d_diff_worker import diff_stat_worker_count  # noqa: E402


def ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def main() -> None:
    db_path = ROOT / "data" / "3190.db"
    if not db_path.is_file():
        print(f"Missing {db_path}")
        sys.exit(1)

    db = Database(db_path)
    project_name = "3190"
    loaded = db.load_project(project_name, with_positions=False)
    if loaded is None:
        print("Failed to load 3190")
        sys.exit(1)
    settings, map_data = loaded
    baseline = "preplot"

    print("=" * 60)
    print("3190 DIFF STAT RECALC PROFILE")
    print("=" * 60)

    t0 = time.perf_counter()
    match_rows = [
        row for row in build_postplot_4d_rows(map_data, settings, baseline) if row.has_match
    ]
    print(f"matched rows: {len(match_rows)} ({ms(t0):.0f} ms)")

    t0 = time.perf_counter()
    source_positions = db.load_source_positions_for_sequence_ids(
        project_name,
        [row.sequence_id for row in match_rows],
    )
    print(
        "targeted source position load: "
        f"{ms(t0):.0f} ms ({len(source_positions):,} rows)"
    )

    t0 = time.perf_counter()
    all_positions = db.load_positions(project_name)
    print(f"old full position load: {ms(t0):.0f} ms ({len(all_positions):,} rows)")

    sample = match_rows[: min(8, len(match_rows))]
    if not sample:
        return

    def compute_with_shared_source_positions(row):
        return calculate_match_diff_rows(
            map_data,
            settings,
            source_positions,
            row,
            database=None,
            project_name=project_name,
        )

    def compute_with_per_match_load(row):
        positions = db.load_source_positions_for_sequence_ids(project_name, [row.sequence_id])
        return calculate_match_diff_rows(
            map_data,
            settings,
            positions,
            row,
            database=None,
            project_name=project_name,
        )

    t0 = time.perf_counter()
    single_counts = [len(compute_with_shared_source_positions(row)) for row in sample]
    print(
        f"single-thread dry compute with preloaded sources ({len(sample)} rows): "
        f"{ms(t0):.0f} ms ({sum(single_counts):,} diff rows)"
    )

    workers = diff_stat_worker_count(len(sample))
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        multi_counts = [
            len(rows) for rows in executor.map(compute_with_shared_source_positions, sample)
        ]
    print(
        f"{workers}-thread dry compute with preloaded sources ({len(sample)} rows): "
        f"{ms(t0):.0f} ms ({sum(multi_counts):,} diff rows)"
    )

    t0 = time.perf_counter()
    per_match_counts = [len(compute_with_per_match_load(row)) for row in sample]
    print(
        f"single-thread per-match load+compute ({len(sample)} rows): "
        f"{ms(t0):.0f} ms ({sum(per_match_counts):,} diff rows)"
    )

    thread_local = threading.local()

    def compute_with_thread_db(row):
        local_db = getattr(thread_local, "db", None)
        if local_db is None:
            local_db = Database(db_path)
            thread_local.db = local_db
        positions = local_db.load_source_positions_for_sequence_ids(
            project_name,
            [row.sequence_id],
        )
        return calculate_match_diff_rows(
            map_data,
            settings,
            positions,
            row,
            database=None,
            project_name=project_name,
        )

    db_load_workers = min(workers, 2)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=db_load_workers) as executor:
        per_match_multi_counts = [
            len(rows) for rows in executor.map(compute_with_thread_db, sample)
        ]
    print(
        f"{db_load_workers}-thread per-match load+compute ({len(sample)} rows): "
        f"{ms(t0):.0f} ms ({sum(per_match_multi_counts):,} diff rows)"
    )

    db.close()


if __name__ == "__main__":
    main()
