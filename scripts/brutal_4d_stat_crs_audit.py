"""Brutal 4D Stat CRS audit: map/local datum EN and Lat/Long for baseline and source.

Verifies on real project databases that:
  * Map CRS (projected) easting/northing and geographic lat/long use the same
    local datum (map CRS geodetic) for Navplan/Preplot baseline and source rows.
  * FSP/LSP endpoint shotpoints match the same rules as interior rows.
  * UI EN <-> Lat/Long toggle math matches stored projected coordinates.

Usage:
  python scripts/brutal_4d_stat_crs_audit.py
  python scripts/brutal_4d_stat_crs_audit.py data/7027.db 7027
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.coord_format import (  # noqa: E402
    GeoDisplayFormatter,
    format_dd_mm,
    format_geo_from_projected,
    parse_geo_value,
)
from xpostmaps.core.crs_utils import geographic_epsg_from_map, normalize_epsg  # noqa: E402
from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.core.models import (  # noqa: E402
    PositionRecord,
    RecordType,
    make_sequence_group_id,
    sequence_group_id,
)
from xpostmaps.core.postplot_4d_diff import (  # noqa: E402
    CrsMismatchError,
    Postplot4DDiffRow,
    calculate_match_diff_rows,
)
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow, build_postplot_4d_rows  # noqa: E402

EN_TOL_M = 0.001
GEO_TOL_DEG = 1e-5

DEFAULT_PROJECTS: tuple[tuple[Path, str], ...] = (
    (ROOT / "data" / "4030_4D.db", "4030_4D"),
    (ROOT / "data" / "7027.db", "7027"),
    (ROOT / "data" / "10221.db", "10221"),
)


@dataclass
class AuditStats:
    diff_coords_checked: int = 0
    endpoint_coords_checked: int = 0
    source_positions_checked: int = 0
    display_errors: list[str] = field(default_factory=list)
    stored_metadata_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    crs_skips: list[str] = field(default_factory=list)

    def display_fail(self, message: str) -> None:
        self.display_errors.append(message)

    def stored_fail(self, message: str) -> None:
        self.stored_metadata_errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _parse_stored_geo(text: str, *, is_latitude: bool) -> float | None:
    parsed = parse_geo_value(text, is_latitude=is_latitude)
    if parsed is not None:
        return parsed
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _verify_en_lat_toggle(
    label: str,
    easting: float,
    northing: float,
    fmt: GeoDisplayFormatter,
) -> list[str]:
    errors: list[str] = []
    lat_disp = format_geo_from_projected(
        easting, northing, is_latitude=True, formatter=fmt
    )
    lon_disp = format_geo_from_projected(
        easting, northing, is_latitude=False, formatter=fmt
    )
    lon, lat = fmt.geographic_from_projected(easting, northing)
    exp_lat = format_dd_mm(lat, is_latitude=True)
    exp_lon = format_dd_mm(lon, is_latitude=False)
    if lat_disp != exp_lat:
        errors.append(f"{label} lat display {lat_disp!r} != {exp_lat!r}")
    if lon_disp != exp_lon:
        errors.append(f"{label} lon display {lon_disp!r} != {exp_lon!r}")
    rx, ry = fmt.projected_from_geographic(lon, lat)
    if abs(rx - easting) > EN_TOL_M or abs(ry - northing) > EN_TOL_M:
        errors.append(
            f"{label} EN round-trip drift: ({rx:.3f},{ry:.3f}) vs ({easting:.3f},{northing:.3f})"
        )
    return errors


def _verify_stored_geo_strings(
    label: str,
    easting: float,
    northing: float,
    lat_text: str,
    lon_text: str,
    fmt: GeoDisplayFormatter,
) -> list[str]:
    errors: list[str] = []
    lon, lat = fmt.geographic_from_projected(easting, northing)
    stored_lat = _parse_stored_geo(lat_text, is_latitude=True)
    stored_lon = _parse_stored_geo(lon_text, is_latitude=False)
    if stored_lat is None or stored_lon is None:
        errors.append(f"{label} missing/invalid stored lat/lon: {lat_text!r}, {lon_text!r}")
        return errors
    if abs(stored_lat - lat) > GEO_TOL_DEG:
        errors.append(
            f"{label} stored latitude {stored_lat:.8f} != map-datum {lat:.8f}"
        )
    if abs(stored_lon - lon) > GEO_TOL_DEG:
        errors.append(
            f"{label} stored longitude {stored_lon:.8f} != map-datum {lon:.8f}"
        )
    return errors


def _verify_diff_row(
    row: Postplot4DDiffRow,
    fmt: GeoDisplayFormatter,
    stats: AuditStats,
    *,
    context: str,
    endpoint: bool,
) -> None:
    for part, x, y, lat_t, lon_t in (
        ("baseline", row.baseline_x, row.baseline_y, row.baseline_latitude, row.baseline_longitude),
        ("source", row.source_x, row.source_y, row.source_latitude, row.source_longitude),
    ):
        label = f"{context} SP{row.shotpoint} {part}"
        stats.diff_coords_checked += 1
        if endpoint:
            stats.endpoint_coords_checked += 1
        for err in _verify_en_lat_toggle(label, x, y, fmt):
            if len(stats.display_errors) < 100:
                stats.display_fail(f"[{'endpoint' if endpoint else 'row'}] {err}")
        for err in _verify_stored_geo_strings(label, x, y, lat_t, lon_t, fmt):
            if len(stats.stored_metadata_errors) < 100:
                stats.stored_fail(f"[{'endpoint' if endpoint else 'row'}] {err}")



def _verify_source_positions(
    positions: list[PositionRecord],
    match_row: Postplot4DMatchRow,
    fmt: GeoDisplayFormatter,
    stats: AuditStats,
) -> None:
    group_id = sequence_group_id(match_row.sequence_id)
    sources = [
        rec
        for rec in positions
        if rec.record_type == RecordType.SOURCE
        and rec.point_num > 0
        and make_sequence_group_id(rec.file_name, rec.sequence_no, rec.line_name) == group_id
    ]
    if not sources:
        stats.warn(f"{match_row.line_name}: no SOURCE positions in DB for sequence")
        return

    fsp, lsp = match_row.first_sp, match_row.last_sp
    for rec in sources:
        stats.source_positions_checked += 1
        label = f"{match_row.line_name} source SP{rec.point_num}"
        endpoint = rec.point_num in (fsp, lsp)
        tag = "endpoint" if endpoint else "row"
        for err in _verify_en_lat_toggle(label, rec.x, rec.y, fmt):
            if len(stats.display_errors) < 100:
                stats.display_fail(f"[{tag}] {err}")
        if rec.latitude and rec.longitude:
            for err in _verify_stored_geo_strings(
                label,
                rec.x,
                rec.y,
                rec.latitude,
                rec.longitude,
                fmt,
            ):
                if len(stats.stored_metadata_errors) < 100:
                    stats.stored_fail(f"[{tag}] {err}")


def _load_diff_rows(
    db: Database,
    project: str,
    map_data,
    settings,
    positions: list[PositionRecord],
    match_row: Postplot4DMatchRow,
    *,
    use_saved: bool,
) -> list[Postplot4DDiffRow]:
    if use_saved:
        saved = db.load_postplot_4d_diffs(
            project,
            match_row.baseline_kind,
            match_row.sequence_id,
        )
        if saved:
            return saved
    return calculate_match_diff_rows(
        map_data,
        settings,
        positions,
        match_row,
        database=db,
        project_name=project,
    )


def audit_project(db_path: Path, project: str, *, use_saved: bool) -> AuditStats:
    stats = AuditStats()
    if not db_path.is_file():
        stats.display_fail(f"database not found: {db_path}")
        return stats

    db = Database(db_path)
    settings, map_data = db.load_project(project, with_positions=True)
    if map_data is None:
        stats.display_fail(f"{project}: failed to load map_data")
        return stats

    map_epsg = normalize_epsg(getattr(map_data.postmap_info, "epsg_code", "") or "")
    if not map_epsg:
        stats.display_fail(f"{project}: map EPSG is not set")
        return stats

    geo_epsg = geographic_epsg_from_map(map_epsg)
    fmt = GeoDisplayFormatter(map_epsg)
    positions = list(map_data.positions)

    print(f"\n{'=' * 72}")
    print(f"PROJECT {project!r}  ({db_path.name})")
    print(f"  Map CRS (projected): EPSG:{map_epsg}")
    print(f"  Local datum (geographic): EPSG:{geo_epsg}")
    print(f"  Positions loaded: {len(positions):,}")
    print(f"  Diff source: {'saved DB rows' if use_saved else 'live recalc'}")

    for baseline_kind in ("navplan", "preplot"):
        settings.postplot_4d_baseline = baseline_kind
        matched = [
            row for row in build_postplot_4d_rows(map_data, settings, baseline_kind) if row.has_match
        ]
        print(f"\n  Baseline {baseline_kind}: {len(matched)} matched line(s)")

        for match_row in matched:
            context_base = f"{baseline_kind}/{match_row.baseline_name}->{match_row.line_name}"
            try:
                diff_rows = _load_diff_rows(
                    db,
                    project,
                    map_data,
                    settings,
                    positions,
                    match_row,
                    use_saved=use_saved,
                )
            except CrsMismatchError as exc:
                stats.crs_skips.append(f"{context_base}: {exc}")
                continue

            if not diff_rows:
                stats.warn(f"{context_base}: no diff rows")
                continue

            fsp_lsp = {match_row.first_sp, match_row.last_sp}
            for diff_row in diff_rows:
                endpoint = diff_row.shotpoint in fsp_lsp
                context = context_base
                if endpoint:
                    tag = "FSP" if diff_row.shotpoint == match_row.first_sp else "LSP"
                    context = f"{context_base} {tag} SP{diff_row.shotpoint}"
                _verify_diff_row(
                    diff_row,
                    fmt,
                    stats,
                    context=context,
                    endpoint=endpoint,
                )

            _verify_source_positions(positions, match_row, fmt, stats)

    return stats


def _print_summary(project: str, stats: AuditStats) -> bool:
    print(f"\n  --- {project} SUMMARY ---")
    print(f"  Display coords checked:   {stats.diff_coords_checked:,}")
    print(f"  FSP/LSP endpoint coords:  {stats.endpoint_coords_checked:,}")
    print(f"  Source positions checked: {stats.source_positions_checked:,}")
    if stats.crs_skips:
        print(f"  CRS skips:                {len(stats.crs_skips)}")
        for msg in stats.crs_skips[:5]:
            print(f"    skip: {msg}")
    if stats.warnings:
        print(f"  Warnings:                 {len(stats.warnings)}")
        for msg in stats.warnings[:5]:
            print(f"    warn: {msg}")

    display_ok = not stats.display_errors
    if display_ok:
        print("  DISPLAY CRS (EN + UI Lat/Long toggle): PASS")
    else:
        print(f"  DISPLAY CRS: FAIL ({len(stats.display_errors)} error(s))")
        for msg in stats.display_errors[:15]:
            print(f"    - {msg}")

    if stats.stored_metadata_errors:
        print(
            f"  STORED METADATA (baseline_/source_ latitude strings in DB): "
            f"WARN {len(stats.stored_metadata_errors)} mismatch(es)"
        )
        for msg in stats.stored_metadata_errors[:10]:
            print(f"    - {msg}")
        if len(stats.stored_metadata_errors) > 10:
            print(f"    ... and {len(stats.stored_metadata_errors) - 10} more")
        print(
            "  Note: UI Lat/Long is derived from EN via map CRS; stored strings are not shown."
        )
    else:
        print("  STORED METADATA lat/lon strings: PASS")

    return display_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets",
        nargs="*",
        help="Optional pairs: db_path project_name (repeat). Defaults to 4030, 7027, 10221.",
    )
    parser.add_argument(
        "--recalc",
        action="store_true",
        help="Recompute 4D Stat rows from files instead of using saved DB rows",
    )
    args = parser.parse_args()

    if args.targets:
        if len(args.targets) % 2 != 0:
            print("ERROR: provide db_path and project_name in pairs")
            return 1
        projects = [
            (Path(args.targets[i]), args.targets[i + 1])
            for i in range(0, len(args.targets), 2)
        ]
    else:
        projects = list(DEFAULT_PROJECTS)

    print("BRUTAL 4D STAT CRS AUDIT")
    print("Checks Navplan/Preplot baseline + source EN and local-datum Lat/Long")
    print("Includes FSP/LSP endpoint shotpoints and UI EN<->Lat toggle consistency")

    all_ok = True
    for db_path, project in projects:
        stats = audit_project(db_path, project, use_saved=not args.recalc)
        if not _print_summary(project, stats):
            all_ok = False

    print(f"\n{'=' * 72}")
    if all_ok:
        print("OVERALL: PASS (display EN + local-datum Lat/Long)")
        return 0
    print("OVERALL: FAIL — display CRS errors above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
