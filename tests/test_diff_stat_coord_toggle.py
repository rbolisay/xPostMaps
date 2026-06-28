"""Brutal Diff Stat Easting/Northing <-> Lat/Long toggle verification."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from xpostmaps.core.coord_format import (
    GeoDisplayFormatter,
    format_dd_mm,
    format_geo_from_projected,
)
from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_diff import (
    CrsMismatchError,
    Postplot4DDiffRow,
    calculate_match_diff_rows,
)
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows

ROOT = Path(__file__).resolve().parents[1]
DB_10221 = ROOT / "data" / "10221.db"
DB_4030 = ROOT / "data" / "4030_4D.db"
EN_TOL_M = 0.001


def _format_en(value: float) -> str:
    return f"{value:.3f}"


def _format_diff_row_lat_mode(
    row: Postplot4DDiffRow,
    fmt: GeoDisplayFormatter,
) -> tuple[str, str, str, str]:
    """Mirror postplot_4d_dialog.refresh_diff_table lat-mode formatting."""
    return (
        format_geo_from_projected(
            row.baseline_x,
            row.baseline_y,
            is_latitude=True,
            formatter=fmt,
        ),
        format_geo_from_projected(
            row.baseline_x,
            row.baseline_y,
            is_latitude=False,
            formatter=fmt,
        ),
        format_geo_from_projected(
            row.source_x,
            row.source_y,
            is_latitude=True,
            formatter=fmt,
        ),
        format_geo_from_projected(
            row.source_x,
            row.source_y,
            is_latitude=False,
            formatter=fmt,
        ),
    )


def _expected_lat_lon_display(
    easting: float,
    northing: float,
    fmt: GeoDisplayFormatter,
) -> tuple[str, str]:
    lon, lat = fmt.geographic_from_projected(easting, northing)
    return (
        format_dd_mm(lat, is_latitude=True),
        format_dd_mm(lon, is_latitude=False),
    )


def _verify_toggle_pair(
    easting: float,
    northing: float,
    lat_display: str,
    lon_display: str,
    fmt: GeoDisplayFormatter,
) -> list[str]:
    errors: list[str] = []
    exp_lat, exp_lon = _expected_lat_lon_display(easting, northing, fmt)
    if lat_display != exp_lat:
        errors.append(f"latitude display {lat_display!r} != expected {exp_lat!r}")
    if lon_display != exp_lon:
        errors.append(f"longitude display {lon_display!r} != expected {exp_lon!r}")

    lon, lat = fmt.geographic_from_projected(easting, northing)
    rx, ry = fmt.projected_from_geographic(lon, lat)
    if abs(rx - easting) > EN_TOL_M or abs(ry - northing) > EN_TOL_M:
        errors.append(
            "lat/long round-trip to EN exceeds tolerance: "
            f"({rx:.3f},{ry:.3f}) vs ({easting:.3f},{northing:.3f})"
        )
    return errors


def _verify_diff_rows(
    rows: list[Postplot4DDiffRow],
    fmt: GeoDisplayFormatter,
    *,
    label: str,
) -> None:
    failures: list[str] = []
    total_pairs = 0
    for diff_row in rows:
        lat = _format_diff_row_lat_mode(diff_row, fmt)
        if _format_en(diff_row.baseline_x) != f"{diff_row.baseline_x:.3f}":
            failures.append(f"SP{diff_row.shotpoint}: baseline easting EN mismatch")
        if _format_en(diff_row.baseline_y) != f"{diff_row.baseline_y:.3f}":
            failures.append(f"SP{diff_row.shotpoint}: baseline northing EN mismatch")
        if _format_en(diff_row.source_x) != f"{diff_row.source_x:.3f}":
            failures.append(f"SP{diff_row.shotpoint}: source easting EN mismatch")
        if _format_en(diff_row.source_y) != f"{diff_row.source_y:.3f}":
            failures.append(f"SP{diff_row.shotpoint}: source northing EN mismatch")

        for easting, northing, lat_disp, lon_disp in (
            (diff_row.baseline_x, diff_row.baseline_y, lat[0], lat[1]),
            (diff_row.source_x, diff_row.source_y, lat[2], lat[3]),
        ):
            total_pairs += 1
            pair_errors = _verify_toggle_pair(
                easting,
                northing,
                lat_disp,
                lon_disp,
                fmt,
            )
            if pair_errors:
                failures.append(
                    f"SP{diff_row.shotpoint}: " + "; ".join(pair_errors)
                )

    assert rows, f"expected diff rows for {label}"
    assert failures == [], (
        f"{label}: {len(failures)} coordinate toggle failures across "
        f"{len(rows)} rows / {total_pairs} EN<->lat pairs"
    )


def _load_saved_diff_rows(
    db: Database,
    project: str,
    baseline_kinds: tuple[str, ...],
) -> list[Postplot4DDiffRow]:
    rows: list[Postplot4DDiffRow] = []
    for baseline_kind in baseline_kinds:
        saved = db.load_all_postplot_4d_diffs(project, baseline_kind)
        for diff_rows in saved.values():
            rows.extend(diff_rows)
    return rows


def _load_recalc_diff_rows(
    db: Database,
    project: str,
    map_data,
    settings,
    baseline_kinds: tuple[str, ...],
) -> list[Postplot4DDiffRow]:
    rows: list[Postplot4DDiffRow] = []
    positions = map_data.positions
    for baseline_kind in baseline_kinds:
        settings.postplot_4d_baseline = baseline_kind
        matched = [
            row
            for row in build_postplot_4d_rows(map_data, settings, baseline_kind)
            if row.has_match
        ]
        assert matched, f"expected matches for {baseline_kind} baseline"
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
                raise AssertionError(
                    f"CRS mismatch for {baseline_kind}/{match_row.baseline_name}: {exc}"
                ) from exc
            rows.extend(diff_rows)
    return rows


@unittest.skipUnless(DB_10221.is_file(), "10221.db not available")
class Brutal10221DiffStatCoordToggleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        db = Database(DB_10221)
        settings, map_data = db.load_project("10221", with_positions=True)
        if map_data is None:
            raise unittest.SkipTest("failed to load 10221 map data")
        cls.db = db
        cls.settings = settings
        cls.map_data = map_data
        cls.map_epsg = str(getattr(map_data.postmap_info, "epsg_code", "") or "")
        cls.fmt = GeoDisplayFormatter(cls.map_epsg)

    def test_10221_all_matches_en_lat_toggle_is_exact(self) -> None:
        rows = _load_recalc_diff_rows(
            self.db,
            "10221",
            self.map_data,
            self.settings,
            ("navplan", "preplot"),
        )
        _verify_diff_rows(rows, self.fmt, label="10221 recalc")

    def test_format_geo_from_projected_swapped_args_would_fail(self) -> None:
        match_row = next(
            row
            for row in build_postplot_4d_rows(
                self.map_data,
                self.settings,
                "navplan",
            )
            if row.has_match
        )
        row = next(
            iter(
                calculate_match_diff_rows(
                    self.map_data,
                    self.settings,
                    self.map_data.positions,
                    match_row,
                    database=self.db,
                    project_name="10221",
                )
            )
        )
        x, y = row.baseline_x, row.baseline_y
        wrong_lat = format_geo_from_projected(y, x, is_latitude=True, formatter=self.fmt)
        wrong_lon = format_geo_from_projected(y, x, is_latitude=False, formatter=self.fmt)
        right_lat, right_lon = _expected_lat_lon_display(x, y, self.fmt)
        self.assertNotEqual(wrong_lat, right_lat)
        self.assertNotEqual(wrong_lon, right_lon)
        lon, lat = self.fmt.geographic_from_projected(y, x)
        rx, ry = self.fmt.projected_from_geographic(lon, lat)
        drift = math.hypot(rx - x, ry - y)
        self.assertGreater(drift, 1.0, "swapped args should move point by >1 m")


@unittest.skipUnless(DB_4030.is_file(), "4030_4D.db not available")
class Brutal4030DiffStatCoordToggleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        db = Database(DB_4030)
        settings, map_data = db.load_project("4030_4D", with_positions=False)
        if map_data is None:
            raise unittest.SkipTest("failed to load 4030 map data")
        cls.db = db
        cls.settings = settings
        cls.map_data = map_data
        cls.map_epsg = str(getattr(map_data.postmap_info, "epsg_code", "") or "")
        cls.fmt = GeoDisplayFormatter(cls.map_epsg)

    def test_4030_saved_navplan_diff_rows_en_lat_toggle_is_exact(self) -> None:
        rows = _load_saved_diff_rows(self.db, "4030_4D", ("navplan",))
        if not rows:
            self.skipTest("no saved navplan diffs in 4030_4D.db")
        _verify_diff_rows(
            rows,
            self.fmt,
            label=f"4030 saved navplan ({len(rows)} rows)",
        )

    def test_4030_preplot_recalc_en_lat_toggle_is_exact(self) -> None:
        _, map_data = self.db.load_project("4030_4D", with_positions=True)
        assert map_data is not None
        rows = _load_recalc_diff_rows(
            self.db,
            "4030_4D",
            map_data,
            self.settings,
            ("preplot",),
        )
        _verify_diff_rows(
            rows,
            self.fmt,
            label=f"4030 preplot recalc ({len(rows)} rows)",
        )

    def test_4030_live_recalc_sample_matches_saved_toggle(self) -> None:
        """Spot-check live recalc against saved rows for one matched sequence."""
        saved = self.db.load_all_postplot_4d_diffs("4030_4D", "navplan")
        if not saved:
            self.skipTest("no saved navplan diffs in 4030_4D.db")

        sequence_id = next(iter(saved))
        saved_rows = saved[sequence_id]
        self.assertTrue(saved_rows)

        _, map_data = self.db.load_project("4030_4D", with_positions=True)
        assert map_data is not None
        self.settings.postplot_4d_baseline = "navplan"
        match_row = next(
            row
            for row in build_postplot_4d_rows(map_data, self.settings, "navplan")
            if row.has_match and row.sequence_id == sequence_id
        )
        live_rows = calculate_match_diff_rows(
            map_data,
            self.settings,
            map_data.positions,
            match_row,
            database=self.db,
            project_name="4030_4D",
        )
        self.assertEqual(len(live_rows), len(saved_rows))
        for live, saved in zip(live_rows, saved_rows):
            self.assertEqual(live.shotpoint, saved.shotpoint)
            self.assertAlmostEqual(live.baseline_x, saved.baseline_x, places=3)
            self.assertAlmostEqual(live.baseline_y, saved.baseline_y, places=3)
            self.assertAlmostEqual(live.source_x, saved.source_x, places=3)
            self.assertAlmostEqual(live.source_y, saved.source_y, places=3)
        _verify_diff_rows(live_rows, self.fmt, label="4030 live recalc sample")

    def test_4030_recalc_stored_geographic_metadata_matches_map_datum(self) -> None:
        _, map_data = self.db.load_project("4030_4D", with_positions=True)
        assert map_data is not None
        rows = _load_recalc_diff_rows(
            self.db,
            "4030_4D",
            map_data,
            self.settings,
            ("navplan", "preplot"),
        )
        failures: list[str] = []
        for diff_row in rows:
            for label, x, y, lat_t, lon_t in (
                ("baseline", diff_row.baseline_x, diff_row.baseline_y, diff_row.baseline_latitude, diff_row.baseline_longitude),
                ("source", diff_row.source_x, diff_row.source_y, diff_row.source_latitude, diff_row.source_longitude),
            ):
                try:
                    stored_lat = float(lat_t)
                    stored_lon = float(lon_t)
                except ValueError:
                    failures.append(f"SP{diff_row.shotpoint} {label}: non-decimal {lat_t!r}/{lon_t!r}")
                    continue
                lon, lat = self.fmt.geographic_from_projected(x, y)
                if abs(stored_lat - lat) > 1e-4 or abs(stored_lon - lon) > 1e-4:
                    failures.append(
                        f"SP{diff_row.shotpoint} {label}: stored ({stored_lat},{stored_lon}) "
                        f"!= map ({lat:.6f},{lon:.6f})"
                    )
                if len(failures) >= 20:
                    break
            if len(failures) >= 20:
                break
        assert failures == [], "4030 stored geographic metadata mismatches:\n" + "\n".join(failures)
