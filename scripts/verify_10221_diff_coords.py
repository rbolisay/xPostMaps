"""Brutal verification of Diff Stat EN/Lat coordinate toggle on 10221.db."""

from __future__ import annotations

import math
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
    Postplot4DDiffRow,
    calculate_match_diff_rows,
)
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows  # noqa: E402

DB_PATH = ROOT / "data" / "10221.db"
PROJECT = "10221"
EN_TOL = 0.001


def _format_en(value: float) -> str:
    return f"{value:.3f}"


def _dialog_lat_lon(
    row: Postplot4DDiffRow,
    fmt: GeoDisplayFormatter,
) -> tuple[str, str, str, str]:
    """Mirror postplot_4d_dialog.refresh_diff_table lat-mode calls."""
    return (
        format_geo_from_projected(
            row.baseline_x, row.baseline_y, is_latitude=True, formatter=fmt
        ),
        format_geo_from_projected(
            row.baseline_x, row.baseline_y, is_latitude=False, formatter=fmt
        ),
        format_geo_from_projected(
            row.source_x, row.source_y, is_latitude=True, formatter=fmt
        ),
        format_geo_from_projected(
            row.source_x, row.source_y, is_latitude=False, formatter=fmt
        ),
    )


def _expected_lat_lon_display(
    x: float,
    y: float,
    fmt: GeoDisplayFormatter,
) -> tuple[str, str]:
    lon, lat = fmt.geographic_from_projected(x, y)
    return (
        format_dd_mm(lat, is_latitude=True),
        format_dd_mm(lon, is_latitude=False),
    )


def _verify_row(
    row: Postplot4DDiffRow,
    fmt: GeoDisplayFormatter,
) -> list[str]:
    errors: list[str] = []

    bla, blb, sla, slb = _dialog_lat_lon(row, fmt)

    for label, display_lat, display_lon, x, y in (
        ("baseline", bla, blb, row.baseline_x, row.baseline_y),
        ("source", sla, slb, row.source_x, row.source_y),
    ):
        exp_lat, exp_lon = _expected_lat_lon_display(x, y, fmt)
        if display_lat != exp_lat:
            errors.append(f"{label} lat: {display_lat!r} != {exp_lat!r}")
        if display_lon != exp_lon:
            errors.append(f"{label} lon: {display_lon!r} != {exp_lon!r}")

        lon, lat = fmt.geographic_from_projected(x, y)
        rx, ry = fmt.projected_from_geographic(lon, lat)
        if abs(rx - x) > EN_TOL or abs(ry - y) > EN_TOL:
            errors.append(
                f"{label} lat/lon round-trip EN mismatch: "
                f"({rx:.3f},{ry:.3f}) vs ({x:.3f},{y:.3f})"
            )

    return errors


def main() -> int:
    if not DB_PATH.is_file():
        print(f"ERROR: database not found: {DB_PATH}")
        return 1

    db = Database(DB_PATH)
    settings, map_data = db.load_project(PROJECT, with_positions=True)
    if map_data is None:
        print("ERROR: failed to load map_data")
        return 1

    positions = map_data.positions
    baseline = settings.postplot_4d_baseline or "navplan"
    map_epsg = str(getattr(map_data.postmap_info, "epsg_code", "") or "")
    fmt = GeoDisplayFormatter(map_epsg)

    match_rows = build_postplot_4d_rows(map_data, settings, baseline)
    matched = [row for row in match_rows if row.has_match]
    print(f"10221.db: {len(matched)} matched lines, map EPSG {map_epsg}, baseline {baseline}")

    total_diff_rows = 0
    failed_rows = 0
    all_errors: list[tuple[str, int, list[str]]] = []

    for match_row in matched:
        diff_rows = calculate_match_diff_rows(
            map_data,
            settings,
            positions,
            match_row,
            database=db,
            project_name=PROJECT,
        )
        for diff_row in diff_rows:
            total_diff_rows += 1
            errors = _verify_row(diff_row, fmt)
            if errors:
                failed_rows += 1
                if len(all_errors) < 20:
                    all_errors.append((match_row.baseline_name, diff_row.shotpoint, errors))

    print(f"Verified {total_diff_rows} diff rows across {len(matched)} matches")
    if failed_rows:
        print(f"FAILED: {failed_rows} rows with coordinate errors")
        for name, sp, errors in all_errors:
            print(f"  {name} SP{sp}:")
            for err in errors:
                print(f"    - {err}")
        return 1

    print("PASS: all Diff Stat EN/Lat coordinates are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
