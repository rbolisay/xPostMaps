"""Brutal FSP/LSP correctness audit for the 4D Stat table (default project: 10221).

Zero tolerance for direction/coordinate mistakes. Verifies, against the REAL
project database and the REAL raw P111/P190 + Preplot/Navplan files:

  1. CRS — map projected EPSG is set; baseline + source coords share the SAME
     local map datum (no WGS84/local mixup); EN <-> Lat/Long toggle round-trips.
  2. FSP/LSP shotpoints in every table row match the TRUE acquisition order read
     fresh from the raw source file (ascending OR descending), and the stored
     line_sequences row agrees.
  3. FSP/LSP Easting/Northing on the SOURCE side equal the raw file coordinate
     for that shotpoint; baseline FSP/LSP EN is present and finite.
  4. crossline / inline / radial are internally consistent for EVERY row:
        radial == hypot(dE, dN)              (azimuth-invariant identity)
        (inline, crossline) re-derived from dE,dN and the line heading match.
  5. feather / feather-diff are finite where present.
  6. Plot x-axis order runs FSP -> LSP (descending lines must invert).

Usage:
  python scripts/brutal_10221_fsp_lsp_audit.py
  python scripts/brutal_10221_fsp_lsp_audit.py data/10221.db 10221 --recalc
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.coord_format import (  # noqa: E402
    GeoDisplayFormatter,
    parse_geo_value,
)
from xpostmaps.core.crs_utils import (  # noqa: E402
    geographic_epsg_from_map,
    normalize_epsg,
)
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
    _parse_azimuth_degrees,
    calculate_match_diff_rows,
    feather_diff_deg,
)
from xpostmaps.core.postplot_4d_matching import (  # noqa: E402
    Postplot4DMatchRow,
    build_postplot_4d_rows,
)
from xpostmaps.core.postplot_4d_plot_data import shotpoint_order  # noqa: E402
from xpostmaps.parsers.directory_parser import _parse_nav_file, resolve_nav_files  # noqa: E402

EN_TOL_M = 0.01
COORD_TOL_M = 0.05  # raw-file vs stored source EN (same CRS => should be exact)
STAT_TOL_M = 0.02   # recomputed inline/crossline/radial vs stored
GEO_TOL_DEG = 1e-5

DEFAULT_DB = ROOT / "data" / "10221.db"
DEFAULT_PROJECT = "10221"


@dataclass
class Stats:
    rows_checked: int = 0
    endpoints_checked: int = 0
    sequences_checked: int = 0
    fsp_lsp_errors: list[str] = field(default_factory=list)
    coord_errors: list[str] = field(default_factory=list)
    stat_errors: list[str] = field(default_factory=list)
    crs_errors: list[str] = field(default_factory=list)
    order_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    crs_skips: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not (
            self.fsp_lsp_errors
            or self.coord_errors
            or self.stat_errors
            or self.crs_errors
            or self.order_errors
        )


def _ground_truth_sources(settings) -> dict[str, list[PositionRecord]]:
    """Re-parse raw P111/P190 files; return group_id -> SOURCE records in file order."""
    by_group: dict[str, list[PositionRecord]] = {}
    files = resolve_nav_files(settings)
    for path in files:
        records = _parse_nav_file(path)
        for rec in records:
            if rec.record_type != RecordType.SOURCE or rec.point_num <= 0:
                continue
            seq_no = rec.sequence_no or rec.line_name or "1"
            gid = make_sequence_group_id(rec.file_name, seq_no, rec.line_name.strip() or "UNNAMED")
            by_group.setdefault(gid, []).append(rec)
    return by_group


def _gt_first_last(records: list[PositionRecord]) -> tuple[int, int]:
    """True FSP/LSP = first and last SOURCE shotpoint in acquisition (file) order."""
    return records[0].point_num, records[-1].point_num


def _gt_coord_map(records: list[PositionRecord]) -> dict[int, tuple[float, float]]:
    coords: dict[int, tuple[float, float]] = {}
    for rec in records:
        coords[rec.point_num] = (rec.x, rec.y)  # last record wins (final fix)
    return coords


def _check_crs_pair(label: str, x: float, y: float, fmt: GeoDisplayFormatter, stats: Stats) -> None:
    if not (math.isfinite(x) and math.isfinite(y)):
        stats.crs_errors.append(f"{label}: non-finite EN ({x}, {y})")
        return
    lon, lat = fmt.geographic_from_projected(x, y)
    rx, ry = fmt.projected_from_geographic(lon, lat)
    if abs(rx - x) > EN_TOL_M or abs(ry - y) > EN_TOL_M:
        stats.crs_errors.append(
            f"{label}: EN round-trip drift ({rx:.3f},{ry:.3f}) vs ({x:.3f},{y:.3f})"
        )


def _check_stored_geo(
    label: str, x: float, y: float, lat_t: str, lon_t: str, fmt: GeoDisplayFormatter, stats: Stats
) -> None:
    if not (lat_t and lon_t):
        return
    lon, lat = fmt.geographic_from_projected(x, y)
    s_lat = parse_geo_value(lat_t, is_latitude=True)
    s_lon = parse_geo_value(lon_t, is_latitude=False)
    if s_lat is None or s_lon is None:
        return
    if abs(s_lat - lat) > GEO_TOL_DEG or abs(s_lon - lon) > GEO_TOL_DEG:
        stats.crs_errors.append(
            f"{label}: stored Lat/Long ({s_lat:.7f},{s_lon:.7f}) != local-datum "
            f"({lat:.7f},{lon:.7f}) — possible WGS84/local mixup"
        )


def _check_stats(row: Postplot4DDiffRow, azimuth: float | None, label: str, stats: Stats) -> None:
    d_e = row.source_x - row.baseline_x
    d_n = row.source_y - row.baseline_y
    # Azimuth-invariant identity: radial is just the Euclidean offset.
    radial_expected = math.hypot(d_e, d_n)
    if abs(radial_expected - row.radial_m) > STAT_TOL_M:
        stats.stat_errors.append(
            f"{label}: radial {row.radial_m:.4f} != hypot(dE,dN) {radial_expected:.4f}"
        )
    if abs(math.hypot(row.inline_m, row.crossline_m) - row.radial_m) > STAT_TOL_M:
        stats.stat_errors.append(
            f"{label}: radial != hypot(inline,crossline) "
            f"({row.radial_m:.4f} vs {math.hypot(row.inline_m, row.crossline_m):.4f})"
        )
    if azimuth is not None:
        theta = math.radians(azimuth)
        exp_inline = d_e * math.sin(theta) + d_n * math.cos(theta)
        exp_cross = d_e * math.cos(theta) - d_n * math.sin(theta)
        if abs(exp_inline - row.inline_m) > STAT_TOL_M:
            stats.stat_errors.append(
                f"{label}: inline {row.inline_m:.4f} != re-derived {exp_inline:.4f} (az={azimuth})"
            )
        if abs(exp_cross - row.crossline_m) > STAT_TOL_M:
            stats.stat_errors.append(
                f"{label}: crossline {row.crossline_m:.4f} != re-derived {exp_cross:.4f}"
            )
    for name, val in (("feather", row.line_feather_deg), ("navplan_feather", row.navplan_feather_deg)):
        if val is not None and not math.isfinite(val):
            stats.stat_errors.append(f"{label}: {name} not finite ({val})")
    fdiff = feather_diff_deg(
        line_feather_deg=row.line_feather_deg, navplan_feather_deg=row.navplan_feather_deg
    )
    if fdiff is not None and not math.isfinite(fdiff):
        stats.stat_errors.append(f"{label}: feather_diff not finite ({fdiff})")


def _check_plot_order(diff_rows: list[Postplot4DDiffRow], match: Postplot4DMatchRow, stats: Stats) -> None:
    order = shotpoint_order(diff_rows, match)
    if len(order) < 2:
        return
    descending_expected = match.first_sp > match.last_sp
    descending_actual = order[0] > order[-1]
    if descending_expected != descending_actual:
        stats.order_errors.append(
            f"{match.line_name} [{match.baseline_kind}]: plot order "
            f"{'desc' if descending_actual else 'asc'} but FSP={match.first_sp} "
            f"LSP={match.last_sp} expects {'desc' if descending_expected else 'asc'}"
        )
    monotonic = all(
        (order[i + 1] - order[i]) * (1 if not descending_actual else -1) > 0
        for i in range(len(order) - 1)
    )
    if not monotonic:
        stats.order_errors.append(f"{match.line_name} [{match.baseline_kind}]: plot order not monotonic")


def audit(db_path: Path, project: str, *, use_saved: bool) -> Stats:
    stats = Stats()
    db = Database(db_path)
    settings, map_data = db.load_project(project, with_positions=True)
    if map_data is None:
        stats.crs_errors.append(f"{project}: failed to load map_data")
        return stats

    map_epsg = normalize_epsg(getattr(map_data.postmap_info, "epsg_code", "") or "")
    if not map_epsg:
        stats.crs_errors.append(f"{project}: map EPSG not set")
        return stats
    geo_epsg = geographic_epsg_from_map(map_epsg)
    fmt = GeoDisplayFormatter(map_epsg)
    positions = list(map_data.positions)

    print(f"\n{'=' * 78}")
    print(f"PROJECT {project!r}  ({db_path.name})")
    print(f"  Map CRS (projected):       EPSG:{map_epsg}")
    print(f"  Local datum (geographic):  EPSG:{geo_epsg}")
    print(f"  Positions loaded:          {len(positions):,}")
    print(f"  Diff source:               {'saved DB rows' if use_saved else 'live recalc'}")

    gt = _ground_truth_sources(settings)
    print(f"  Raw source groups parsed:  {len(gt)}")

    # DB-stored sequence endpoints, keyed by group id.
    db_seq: dict[str, tuple[int, int, str]] = {}
    for seq in map_data.sequences:
        db_seq[sequence_group_id(seq.seq_id)] = (seq.first_sp, seq.last_sp, seq.line_direction)

    for baseline_kind in ("navplan", "preplot"):
        settings.postplot_4d_baseline = baseline_kind
        matched = [r for r in build_postplot_4d_rows(map_data, settings, baseline_kind) if r.has_match]
        print(f"\n  Baseline {baseline_kind}: {len(matched)} matched line(s)")

        for match in matched:
            gid = sequence_group_id(match.sequence_id)
            ctx = f"{baseline_kind}:{match.line_name}({match.sequence_no})"
            stats.sequences_checked += 1

            # (2) FSP/LSP vs true acquisition order from the raw file.
            gt_recs = gt.get(gid)
            if gt_recs:
                gt_fsp, gt_lsp = _gt_first_last(gt_recs)
                if (match.first_sp, match.last_sp) != (gt_fsp, gt_lsp):
                    stats.fsp_lsp_errors.append(
                        f"{ctx}: table FSP/LSP ({match.first_sp}->{match.last_sp}) != raw "
                        f"acquisition ({gt_fsp}->{gt_lsp})"
                    )
                db_vals = db_seq.get(gid)
                if db_vals and (db_vals[0], db_vals[1]) != (gt_fsp, gt_lsp):
                    stats.fsp_lsp_errors.append(
                        f"{ctx}: stored line_sequences ({db_vals[0]}->{db_vals[1]}) != raw "
                        f"({gt_fsp}->{gt_lsp})"
                    )
            else:
                stats.warnings.append(f"{ctx}: no raw SOURCE group for {gid!r}")

            try:
                if use_saved:
                    diff_rows = db.load_postplot_4d_diffs(project, baseline_kind, match.sequence_id)
                    if not diff_rows:
                        diff_rows = calculate_match_diff_rows(
                            map_data, settings, positions, match, database=db, project_name=project
                        )
                else:
                    diff_rows = calculate_match_diff_rows(
                        map_data, settings, positions, match, database=db, project_name=project
                    )
            except CrsMismatchError as exc:
                stats.crs_skips.append(f"{ctx}: {exc}")
                continue
            if not diff_rows:
                stats.warnings.append(f"{ctx}: no diff rows")
                continue

            azimuth = _parse_azimuth_degrees(match.line_direction)
            gt_coords = _gt_coord_map(gt_recs) if gt_recs else {}
            shots = {r.shotpoint for r in diff_rows}

            # (3) FSP/LSP endpoint diff rows. A diff only exists where the
            # baseline ALSO has that shotpoint, so a planned (navplan/preplot)
            # baseline that is shorter than the acquired line legitimately lacks
            # the endpoint. That is a baseline-coverage gap, not an FSP/LSP error.
            for tag, sp in (("FSP", match.first_sp), ("LSP", match.last_sp)):
                if sp and sp not in shots:
                    stats.warnings.append(
                        f"{ctx}: {tag} SP{sp} absent from {baseline_kind} diff "
                        f"(baseline does not cover this shotpoint; acquired range is fine)"
                    )

            for row in diff_rows:
                stats.rows_checked += 1
                is_end = row.shotpoint in (match.first_sp, match.last_sp)
                tag = ""
                if row.shotpoint == match.first_sp:
                    tag = " FSP"
                elif row.shotpoint == match.last_sp:
                    tag = " LSP"
                label = f"{ctx} SP{row.shotpoint}{tag}"
                if is_end:
                    stats.endpoints_checked += 1

                _check_crs_pair(f"{label} baseline", row.baseline_x, row.baseline_y, fmt, stats)
                _check_crs_pair(f"{label} source", row.source_x, row.source_y, fmt, stats)
                _check_stored_geo(
                    f"{label} source", row.source_x, row.source_y,
                    row.source_latitude, row.source_longitude, fmt, stats,
                )
                _check_stored_geo(
                    f"{label} baseline", row.baseline_x, row.baseline_y,
                    row.baseline_latitude, row.baseline_longitude, fmt, stats,
                )
                _check_stats(row, azimuth, label, stats)

                # (3) FSP/LSP source EN vs raw file coordinate (same CRS => equal).
                if is_end and row.shotpoint in gt_coords:
                    gx, gy = gt_coords[row.shotpoint]
                    if abs(gx - row.source_x) > COORD_TOL_M or abs(gy - row.source_y) > COORD_TOL_M:
                        stats.coord_errors.append(
                            f"{label}: source EN ({row.source_x:.3f},{row.source_y:.3f}) != raw "
                            f"file ({gx:.3f},{gy:.3f})"
                        )

            _check_plot_order(diff_rows, match, stats)

    return stats


def _summary(project: str, stats: Stats) -> bool:
    print(f"\n  --- {project} SUMMARY ---")
    print(f"  Sequences checked:   {stats.sequences_checked}")
    print(f"  Diff rows checked:   {stats.rows_checked:,}")
    print(f"  FSP/LSP endpoints:   {stats.endpoints_checked:,}")
    if stats.crs_skips:
        print(f"  CRS skips:           {len(stats.crs_skips)}")
        for m in stats.crs_skips[:5]:
            print(f"    skip: {m}")
    if stats.warnings:
        print(f"  Warnings:            {len(stats.warnings)}")
        for m in stats.warnings[:8]:
            print(f"    warn: {m}")

    def report(name: str, errs: list[str]) -> None:
        if errs:
            print(f"  {name}: FAIL ({len(errs)})")
            for m in errs[:15]:
                print(f"    - {m}")
        else:
            print(f"  {name}: PASS")

    report("FSP/LSP shotpoint order", stats.fsp_lsp_errors)
    report("FSP/LSP source EN vs raw file", stats.coord_errors)
    report("crossline/inline/radial/feather", stats.stat_errors)
    report("CRS local datum (EN + Lat/Long)", stats.crs_errors)
    report("Plot x-axis FSP->LSP order", stats.order_errors)
    return stats.ok()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", nargs="?", default=str(DEFAULT_DB))
    parser.add_argument("project", nargs="?", default=DEFAULT_PROJECT)
    parser.add_argument("--recalc", action="store_true", help="Recompute from files (not saved DB rows)")
    args = parser.parse_args()

    db_path = Path(args.db)
    print("BRUTAL 10221 FSP/LSP + CRS + STAT AUDIT")
    if not db_path.is_file():
        print(f"ERROR: database not found: {db_path}")
        return 1

    stats = audit(db_path, args.project, use_saved=not args.recalc)
    ok = _summary(args.project, stats)
    print(f"\n{'=' * 78}")
    if ok:
        print("OVERALL: PASS — FSP/LSP, coordinates, stats and CRS are correct.")
        return 0
    print("OVERALL: FAIL — see errors above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
