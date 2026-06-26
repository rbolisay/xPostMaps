"""Profile 3190.db project load bottlenecks."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows  # noqa: E402
from xpostmaps.ui.main_window import MainWindow  # noqa: E402


def ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def table_stats(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    print("\n--- DATABASE SIZE ---")
    print(f"File: {db_path}")
    print(f"Size: {db_path.stat().st_size / (1024 * 1024):.1f} MB")

    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    print("\n--- TABLE ROW COUNTS ---")
    for name in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
        except sqlite3.Error:
            count = "?"
        print(f"  {name}: {count:,}" if isinstance(count, int) else f"  {name}: {count}")

    print("\n--- POSTPLOT 4D DIFF STATS ---")
    try:
        row = conn.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT sequence_id),
                   SUM(LENGTH(baseline_latitude) + LENGTH(source_latitude))
            FROM postplot_4d_diffs
            """
        ).fetchone()
        print(f"  diff rows: {row[0]:,}")
        print(f"  distinct sequences: {row[1]:,}")
    except sqlite3.Error as exc:
        print(f"  (no postplot_4d_diffs: {exc})")

    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM postplot_4d_preplot_shotpoints"
        ).fetchone()
        print(f"  preplot shotpoint cache rows: {row[0]:,}")
    except sqlite3.Error:
        pass

    conn.close()


def profile_load(db_path: Path) -> None:
    print("\n--- LOAD TIMING ---")
    t0 = time.perf_counter()
    db = Database(db_path)
    print(f"  Database() init + migrate: {ms(t0):.0f} ms")

    t0 = time.perf_counter()
    projects = db.list_projects()
    project_name = projects[0]
    print(f"  list_projects: {ms(t0):.0f} ms  -> {project_name!r}")

    t0 = time.perf_counter()
    loaded = db.load_project(project_name, with_positions=False)
    print(f"  load_project(with_positions=False): {ms(t0):.0f} ms")
    if not loaded:
        print("  FAILED to load project")
        db.close()
        return
    settings, map_data = loaded

    t0 = time.perf_counter()
    positions = db.load_positions(project_name)
    print(f"  load_positions (on demand): {ms(t0):.0f} ms  ({len(positions):,} rows)")

    t0 = time.perf_counter()
    bulk = db.load_all_postplot_4d_diffs(project_name, settings.postplot_4d_baseline)
    diff_rows = sum(len(v) for v in bulk.values())
    print(
        f"  load_all_postplot_4d_diffs: {ms(t0):.0f} ms  "
        f"({len(bulk)} sequences, {diff_rows:,} diff rows)"
    )

    t0 = time.perf_counter()
    match_rows = build_postplot_4d_rows(map_data, settings, settings.postplot_4d_baseline)
    matched = [r for r in match_rows if r.has_match]
    print(f"  build_postplot_4d_rows: {ms(t0):.0f} ms  ({len(matched)} matched)")

    t0 = time.perf_counter()
    window = MainWindow.__new__(MainWindow)
    window._settings = settings
    window._map_data = map_data
    window._db = db
    window._match_diff_cache = {}
    window._match_diff_cache_version = -1
    window._conditional_data_version = 0
    window._conditional_points_signature_cache = None
    window._refresh_conditional_postplot_points = MainWindow._refresh_conditional_postplot_points.__get__(
        window, MainWindow
    )
    window._bulk_saved_postplot_diffs = MainWindow._bulk_saved_postplot_diffs.__get__(
        window, MainWindow
    )
    window._cached_match_diff_rows = MainWindow._cached_match_diff_rows.__get__(
        window, MainWindow
    )
    window._current_positions = lambda: positions  # noqa: E731
    window._map = type("M", (), {"set_conditional_postplot_points": lambda *a, **k: None})()
    t1 = time.perf_counter()
    window._refresh_conditional_postplot_points()
    print(f"  refresh_conditional_postplot_points: {ms(t1):.0f} ms")

    seg_counts = {
        "main": len(map_data.segments),
        "preplot": len(map_data.preplot_segments),
        "navplan": len(map_data.navplan_segments),
        "sequences": len(map_data.sequences),
    }
    print(f"\n--- MAP DATA ---")
    for key, val in seg_counts.items():
        print(f"  {key}: {val:,}")

    active_cond = [
        e
        for e in settings.legend_config.postplot_lines
        if not e.hidden
        and e.sequence_filter_active
        and e.sequence_ids
        and any(not r.disabled and r.range_value.strip() for r in e.conditional_colors)
    ]
    print(f"  conditional legend entries: {len(active_cond)}")

    db.close()


def main() -> None:
    db_path = ROOT / "data" / "3190.db"
    if not db_path.is_file():
        print(f"Missing {db_path}")
        sys.exit(1)
    print("=" * 60)
    print("3190 LOAD PROFILE")
    print("=" * 60)
    table_stats(db_path)
    profile_load(db_path)


if __name__ == "__main__":
    main()
