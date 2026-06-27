"""Brutal verification of Diff Stat EN/Lat coordinate toggle for a project DB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.coord_format import (  # noqa: E402
    GeoDisplayFormatter,
    format_dd_mm,
    format_geo_from_projected,
)
from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.core.postplot_4d_diff import (  # noqa: E402
    CrsMismatchError,
    Postplot4DDiffRow,
    calculate_match_diff_rows,
)
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows  # noqa: E402

EN_TOL_M = 0.001


def _verify_row(row: Postplot4DDiffRow, fmt: GeoDisplayFormatter) -> list[str]:
    errors: list[str] = []
    for label, x, y in (
        ("baseline", row.baseline_x, row.baseline_y),
        ("source", row.source_x, row.source_y),
    ):
        lat = format_geo_from_projected(x, y, is_latitude=True, formatter=fmt)
        lon = format_geo_from_projected(x, y, is_latitude=False, formatter=fmt)
        exp_lon, exp_lat = fmt.geographic_from_projected(x, y)
        exp_lat_s = format_dd_mm(exp_lat, is_latitude=True)
        exp_lon_s = format_dd_mm(exp_lon, is_latitude=False)
        if lat != exp_lat_s:
            errors.append(f"{label} lat: {lat!r} != {exp_lat_s!r}")
        if lon != exp_lon_s:
            errors.append(f"{label} lon: {lon!r} != {exp_lon_s!r}")
        rx, ry = fmt.projected_from_geographic(exp_lon, exp_lat)
        if abs(rx - x) > EN_TOL_M or abs(ry - y) > EN_TOL_M:
            errors.append(
                f"{label} round-trip EN mismatch: "
                f"({rx:.3f},{ry:.3f}) vs ({x:.3f},{y:.3f})"
            )
    return errors


def _load_diff_rows(
    db: Database,
    project: str,
    map_data,
    settings,
    *,
    baseline_kinds: tuple[str, ...],
    use_saved: bool,
) -> tuple[list[tuple[str, str, Postplot4DDiffRow]], list[str]]:
    """Return (rows, crs_errors) where each row is (baseline_kind, match_name, diff_row)."""
    collected: list[tuple[str, str, Postplot4DDiffRow]] = []
    crs_errors: list[str] = []

    if use_saved:
        for baseline_kind in baseline_kinds:
            saved = db.load_all_postplot_4d_diffs(project, baseline_kind)
            for sequence_id, rows in saved.items():
                for row in rows:
                    collected.append((baseline_kind, sequence_id, row))
        if collected:
            return collected, crs_errors

    positions = map_data.positions
    for baseline_kind in baseline_kinds:
        settings.postplot_4d_baseline = baseline_kind
        matched = [
            row for row in build_postplot_4d_rows(map_data, settings, baseline_kind) if row.has_match
        ]
        for match_row in matched:
            try:
                diff_rows = calculate_match_diff_rows(
                    map_data,
                    settings,
                    positions,
                    match_row,
                    database=db,
                    project_name=project,
                )
            except CrsMismatchError as exc:
                crs_errors.append(f"{baseline_kind}/{match_row.baseline_name}: {exc}")
                continue
            for diff_row in diff_rows:
                collected.append((baseline_kind, match_row.baseline_name, diff_row))
    return collected, crs_errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path, help="Path to project .db file")
    parser.add_argument("project", help="Project name inside the database")
    parser.add_argument(
        "--recalc",
        action="store_true",
        help="Recompute diffs from files instead of using saved DB rows",
    )
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"ERROR: database not found: {args.db}")
        return 1

    db = Database(args.db)
    settings, map_data = db.load_project(args.project, with_positions=True)
    if map_data is None:
        print("ERROR: failed to load map_data")
        return 1

    map_epsg = str(getattr(map_data.postmap_info, "epsg_code", "") or "")
    if not map_epsg:
        print("ERROR: map EPSG is not set")
        return 1

    fmt = GeoDisplayFormatter(map_epsg)
    rows, crs_errors = _load_diff_rows(
        db,
        args.project,
        map_data,
        settings,
        baseline_kinds=("navplan", "preplot"),
        use_saved=not args.recalc,
    )

    source = "saved DB rows" if not args.recalc else "live recalc"
    print(
        f"{args.db.name}: verifying {len(rows)} diff rows ({source}), "
        f"map EPSG {map_epsg}"
    )
    if crs_errors:
        print(f"WARNING: {len(crs_errors)} matches skipped due to CRS mismatch")
        for msg in crs_errors[:10]:
            print(f"  CRS skip: {msg}")

    failed = 0
    samples: list[tuple[str, int, list[str]]] = []
    for baseline_kind, match_name, diff_row in rows:
        errors = _verify_row(diff_row, fmt)
        if errors:
            failed += 1
            if len(samples) < 20:
                samples.append((f"{baseline_kind}/{match_name}", diff_row.shotpoint, errors))

    if failed:
        print(f"FAILED: {failed}/{len(rows)} rows with coordinate errors")
        for name, sp, errors in samples:
            print(f"  {name} SP{sp}:")
            for err in errors:
                print(f"    - {err}")
        return 1

    print(f"PASS: all {len(rows)} Diff Stat EN/Lat coordinates are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
