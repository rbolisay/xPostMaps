"""Profile the per-row '4D Stat' button click against the real 3190 project DB.

Replicates Postplot4DDialog.show_diff_stat -> load_saved_diffs so we can see
whether the lag is the DB read or the per-click position enrichment scan.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.core.postplot_4d_diff import (  # noqa: E402
    enrich_diff_rows_from_positions,
    source_shotpoints_for_match,
    vessel_shotpoints_for_match,
)
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows  # noqa: E402
from xpostmaps.core.models import RecordType  # noqa: E402


def main() -> None:
    db_path = ROOT / "data" / "3190.db"
    db = Database(db_path)
    names = db.list_projects()
    print("projects:", names)
    name = "3190" if "3190" in names else (names[0] if names else "")
    if not name:
        print("no projects in db")
        return

    settings, map_data = db.load_project(name, with_positions=False)

    t = time.perf_counter()
    positions = db.load_positions(name)
    t_positions = time.perf_counter() - t
    print(f"\nload_positions: {t_positions * 1000:8.0f} ms  ({len(positions):,} records)")

    baseline = settings.postplot_4d_baseline or "preplot"
    rows = build_postplot_4d_rows(map_data, settings, baseline)
    matched = [r for r in rows if r.has_match]
    print(f"baseline={baseline}  matched rows={len(matched)}")
    if not matched:
        for alt in ("navplan", "preplot"):
            rows = build_postplot_4d_rows(map_data, settings, alt)
            matched = [r for r in rows if r.has_match]
            if matched:
                baseline = alt
                break
    if not matched:
        print("no matched rows to profile")
        db.close()
        return

    match_row = matched[0]
    print(f"profiling match: {match_row.line_name}.{match_row.subline} seq={match_row.sequence_no}")

    t = time.perf_counter()
    saved = db.load_postplot_4d_diffs(name, match_row.baseline_kind, match_row.sequence_id)
    t_load = time.perf_counter() - t
    print(f"\nload_postplot_4d_diffs (pure DB read): {t_load * 1000:8.0f} ms  ({len(saved):,} rows)")

    have_ids = sum(1 for r in saved if r.vessel_id and r.firing_source_id)
    print(f"  rows with both vessel_id+firing_source_id already saved: {have_ids}/{len(saved)}")

    t = time.perf_counter()
    _ = list(map_data.positions) if map_data.positions else list(positions)
    t_copy = time.perf_counter() - t
    print(f"positions list() copy: {t_copy * 1000:8.0f} ms")

    t = time.perf_counter()
    _src = source_shotpoints_for_match(positions, match_row)
    t_src = time.perf_counter() - t
    t = time.perf_counter()
    _ves = vessel_shotpoints_for_match(positions, match_row)
    t_ves = time.perf_counter() - t
    print(f"source_shotpoints_for_match scan: {t_src * 1000:8.0f} ms")
    print(f"vessel_shotpoints_for_match scan: {t_ves * 1000:8.0f} ms")

    t = time.perf_counter()
    _ = enrich_diff_rows_from_positions(saved, positions, match_row)
    t_enrich = time.perf_counter() - t
    print(f"enrich_diff_rows_from_positions (full): {t_enrich * 1000:8.0f} ms")

    # New targeted path used by the dialog: load only this sequence's
    # SOURCE/VESSEL records instead of all 1.5M project positions.
    t = time.perf_counter()
    targeted = db.load_source_positions_for_sequence_ids(
        name,
        [match_row.sequence_id],
        record_types=(RecordType.SOURCE, RecordType.VESSEL),
    )
    _ = enrich_diff_rows_from_positions(saved, targeted, match_row)
    t_targeted = time.perf_counter() - t
    print(
        f"targeted load + enrich (new dialog path): {t_targeted * 1000:8.0f} ms"
        f"  ({len(targeted):,} records)"
    )

    print("\nSUMMARY (cost of one '4D Stat' click after positions are in memory):")
    print(f"  DB read only:           {t_load * 1000:8.0f} ms")
    print(f"  + positions copy:       {t_copy * 1000:8.0f} ms")
    print(f"  + enrichment scans:     {t_enrich * 1000:8.0f} ms")
    print(f"  => click total approx:  {(t_load + t_copy + t_enrich) * 1000:8.0f} ms")
    db.close()


if __name__ == "__main__":
    main()
