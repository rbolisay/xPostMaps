"""Brutal 3190 DB audit for 3-source preplot side selection.

Uses the real ``data/3190.db`` project. This catches the reverse-line bug where
preplot source offsets were cached from the preplot geometry direction, then
G01/G03 were compared to the wrong side for acquired lines shot 180 degrees
opposite the preplot control direction.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.models import PositionRecord, RecordType
from xpostmaps.core.postplot_4d_diff import (
    BaselineShotpoint,
    compute_postplot_4d_diff_rows,
)

DB_PATH = ROOT / "data" / "3190.db"

CASES = [
    {
        "label": "reverse 1018A003",
        "file_name": "0003.T26A.1018A003.c0003.GFUNREG.VES.p111",
        "sequence_no": "0003",
        "line_name": "1018A003",
        "baseline_name": "1018",
        "line_direction": "247.3",
        "sequence_id": "0003.T26A.1018A003.c0003.GFUNREG.VES.p111|0003|1018A003",
    },
    {
        "label": "reverse 1054A010",
        "file_name": "0010.T26A.1054A010.c0010.GFUNREG.VES.p111",
        "sequence_no": "0010",
        "line_name": "1054A010",
        "baseline_name": "1054",
        "line_direction": "247.3",
        "sequence_id": "0010.T26A.1054A010.c0010.GFUNREG.VES.p111|0010|1054A010",
    },
]

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f"  ::  {detail}" if detail else ""))
    if condition:
        PASS += 1
    else:
        FAIL += 1


def mean_abs(values: list[float]) -> float:
    return sum(abs(value) for value in values) / len(values) if values else float("inf")


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def load_sources(
    conn: sqlite3.Connection,
    case: dict[str, str],
) -> dict[int, PositionRecord]:
    rows = conn.execute(
        """
        SELECT point_num, source_id, x, y, latitude, longitude
        FROM positions
        WHERE project_id=1
          AND file_name=?
          AND sequence_no=?
          AND line_name=?
          AND record_type='source'
          AND point_num > 0
        ORDER BY point_num
        """,
        (case["file_name"], case["sequence_no"], case["line_name"]),
    ).fetchall()
    return {
        int(row["point_num"]): PositionRecord(
            file_name=case["file_name"],
            record_type=RecordType.SOURCE,
            line_name=case["line_name"],
            vessel_id="",
            source_id=row["source_id"] or "",
            point_num=int(row["point_num"]),
            x=float(row["x"]),
            y=float(row["y"]),
            latitude=row["latitude"] or "",
            longitude=row["longitude"] or "",
            sequence_no=case["sequence_no"],
        )
        for row in rows
    }


def load_cached_baseline(
    conn: sqlite3.Connection,
    case: dict[str, str],
    first_sp: int,
    last_sp: int,
) -> dict[tuple[int, str], BaselineShotpoint]:
    rows = conn.execute(
        """
        SELECT shotpoint, source_id, source_index, x, y, latitude, longitude,
               source_count, source_separation_m
        FROM postplot_4d_preplot_shotpoints
        WHERE project_id=1
          AND line_name=?
          AND shotpoint BETWEEN ? AND ?
        ORDER BY shotpoint, source_index
        """,
        (case["baseline_name"], first_sp, last_sp),
    ).fetchall()
    if rows:
        source_counts = {int(row["source_count"] or 0) for row in rows}
        separations = {float(row["source_separation_m"] or 0.0) for row in rows}
        print(
            f"  cached source_count={sorted(source_counts)} "
            f"source_separation={sorted(separations)}"
        )
    return {
        (int(row["shotpoint"]), str(int(row["source_index"]))): BaselineShotpoint(
            shotpoint=int(row["shotpoint"]),
            x=float(row["x"]),
            y=float(row["y"]),
            latitude=row["latitude"] or "",
            longitude=row["longitude"] or "",
            source_id=row["source_id"] or "",
            source_index=int(row["source_index"] or 0),
        )
        for row in rows
    }


def load_saved_crosslines(
    conn: sqlite3.Connection,
    case: dict[str, str],
) -> dict[int, float]:
    rows = conn.execute(
        """
        SELECT shotpoint, crossline_m
        FROM postplot_4d_diffs
        WHERE project_id=1
          AND baseline_kind='preplot'
          AND sequence_id=?
        """,
        (case["sequence_id"],),
    ).fetchall()
    return {int(row["shotpoint"]): float(row["crossline_m"]) for row in rows}


def run_case(conn: sqlite3.Connection, case: dict[str, str]) -> None:
    print("\n---", case["label"], "----------------------------------------")
    sources = load_sources(conn, case)
    check("sources loaded", bool(sources), str(len(sources)))
    if not sources:
        return

    baseline = load_cached_baseline(
        conn,
        case,
        min(sources),
        max(sources),
    )
    check("3-source cached preplot baseline loaded", bool(baseline), str(len(baseline)))
    if not baseline:
        return

    rows = compute_postplot_4d_diff_rows(
        baseline,
        sources,
        case["line_direction"],
    )
    by_source: dict[str, list[float]] = {}
    for row in rows:
        by_source.setdefault(sources[row.shotpoint].source_id, []).append(row.crossline_m)

    saved = load_saved_crosslines(conn, case)
    saved_by_source: dict[str, list[float]] = {}
    for shotpoint, source in sources.items():
        if shotpoint in saved:
            saved_by_source.setdefault(source.source_id, []).append(saved[shotpoint])

    print(f"  recomputed rows={len(rows)} saved_rows={len(saved)}")
    for source_id in ("G01", "G02", "G03"):
        current = by_source.get(source_id, [])
        old = saved_by_source.get(source_id, [])
        print(
            f"  {source_id}: current mean={mean(current):+7.2f} "
            f"mean|.|={mean_abs(current):6.2f} m"
            + (
                f"   saved mean={mean(old):+7.2f} mean|.|={mean_abs(old):6.2f} m"
                if old
                else ""
            )
        )

    check("current G01 crossline mean abs is small", mean_abs(by_source.get("G01", [])) < 12.0)
    check("current G02 crossline mean abs is small", mean_abs(by_source.get("G02", [])) < 12.0)
    check("current G03 crossline mean abs is small", mean_abs(by_source.get("G03", [])) < 12.0)
    if saved_by_source:
        stale_bias = max(
            mean_abs(saved_by_source.get("G01", [])),
            mean_abs(saved_by_source.get("G03", [])),
        )
        if stale_bias > 50.0:
            print("  NOTE: saved DB diff rows still show the old G01/G03 side bias.")


def main() -> int:
    print("=" * 78)
    print("BRUTAL 3190 SOURCE-SIDE DIFF AUDIT (real data/3190.db)")
    print("=" * 78)
    print(f"db: {DB_PATH}")
    check("3190 database exists", DB_PATH.is_file())
    if not DB_PATH.is_file():
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    for case in CASES:
        run_case(conn, case)

    print("\n" + "=" * 78)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
