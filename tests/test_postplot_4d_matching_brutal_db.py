"""Brutal Postplot 4D matching checks against real 4030_4D and 7027 databases."""

from __future__ import annotations

import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_matching import (
    _leading_prefix_alias_forms,
    _line_family_forms,
    build_postplot_4d_rows,
)

ROOT = Path(__file__).resolve().parents[1]
DB_4030 = ROOT / "data" / "4030_4D.db"
DB_7027 = ROOT / "data" / "7027.db"

_TRINAV_ROOT_RE = re.compile(r"^(?P<root>\d+)113\d+$")

# 4030 U/V undershoot lines exist in preplot but not in the navplan catalog.
_4030_NAVPLAN_ORPHAN_LINES = frozenset(
    {
        "8114451U-032",
        "8114552U-030",
        "8115057V-035",
        "8115663V-033",
        "8116269V-031",
    }
)

_7027_EXPECTED = {
    "51892": ("51892113001", "3001"),
    "51900": ("51900113003", "3003"),
    "51908": ("51908113005", "3005"),
    "51916": ("51916113007", "3007"),
    "51924": ("51924113009", "3009"),
    "51932": ("51932113011", "3011"),
    "51940": ("51940113013", "3013"),
    "51948": ("51948113015", "3015"),
    "51956": ("51956113018", "3018"),
    "51964": ("51964113020", "3020"),
    "51980": ("51980113002", "3002"),
    "51988": ("51988113004", "3004"),
    "52020": ("52020113006", "3006"),
    "52028": ("52028113008", "3008"),
    "52036": ("52036113010", "3010"),
    "52044": ("52044113012", "3012"),
    "52052": ("52052113014", "3014"),
    "52060": ("52060113016", "3016"),
    "52068": ("52068113017", "3017"),
    "52076": ("52076113019", "3019"),
}


def _load(db_path: Path, project_name: str):
    if not db_path.is_file():
        raise unittest.SkipTest(f"database not found: {db_path}")
    db = Database(db_path)
    settings, map_data = db.load_project(project_name, with_positions=False)
    return settings, map_data


def _match_is_plausible(baseline_name: str, line_name: str) -> bool:
    baseline = baseline_name.upper().strip()
    line = line_name.upper().strip()
    if baseline in line or line.startswith(baseline):
        return True
    if line.startswith("8" + baseline[1:]) or line.startswith("1" + baseline[1:]) or line.startswith("5" + baseline[1:]):
        return True
    trinav = _TRINAV_ROOT_RE.match(line)
    if trinav and trinav.group("root") == baseline:
        return True
    if baseline in _line_family_forms(line):
        return True
    if baseline in _leading_prefix_alias_forms(line):
        return True
    return False


def _audit_rows(rows, sequences, *, allow_orphans: frozenset[str] | None = None):
    matched = [row for row in rows if row.has_match]
    matched_seq_ids = {row.sequence_id for row in matched}
    orphan_lines = [
        seq.line_name
        for seq in sequences
        if seq.seq_id not in matched_seq_ids
    ]
    if allow_orphans is not None:
        unexpected_orphans = sorted(set(orphan_lines) - allow_orphans)
    else:
        unexpected_orphans = sorted(orphan_lines)

    by_seq: dict[str, list[str]] = defaultdict(list)
    for row in matched:
        by_seq[row.sequence_id].append(row.baseline_name)
    multi_baseline = {sid: names for sid, names in by_seq.items() if len(names) > 1}

    suspicious = [
        (row.baseline_name, row.line_name, row.sequence_no)
        for row in matched
        if not _match_is_plausible(row.baseline_name, row.line_name)
    ]

    return {
        "matched": matched,
        "unexpected_orphans": unexpected_orphans,
        "multi_baseline": multi_baseline,
        "suspicious": suspicious,
    }


@unittest.skipUnless(DB_4030.is_file(), "4030_4D.db not available")
class Brutal4030MatchingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings, cls.map_data = _load(DB_4030, "4030_4D")

    def test_navplan_matching_covers_all_imported_except_known_uv_orphans(self) -> None:
        rows = build_postplot_4d_rows(self.map_data, self.settings, "navplan")
        audit = _audit_rows(
            rows,
            self.map_data.sequences,
            allow_orphans=_4030_NAVPLAN_ORPHAN_LINES,
        )
        self.assertEqual(audit["unexpected_orphans"], [])
        self.assertEqual(audit["multi_baseline"], {})
        self.assertEqual(audit["suspicious"], [])
        self.assertEqual(len(audit["matched"]), 66)
        orphan_lines = {
            seq.line_name
            for seq in self.map_data.sequences
            if seq.seq_id not in {row.sequence_id for row in audit["matched"]}
        }
        self.assertEqual(orphan_lines, _4030_NAVPLAN_ORPHAN_LINES)

    def test_preplot_matching_covers_every_imported_sequence(self) -> None:
        rows = build_postplot_4d_rows(self.map_data, self.settings, "preplot")
        audit = _audit_rows(rows, self.map_data.sequences)
        self.assertEqual(len(audit["unexpected_orphans"]), 0, audit["unexpected_orphans"])
        self.assertEqual(len(audit["multi_baseline"]), 0, audit["multi_baseline"])
        self.assertEqual(len(audit["suspicious"]), 0, audit["suspicious"])
        self.assertEqual(len(audit["matched"]), len(self.map_data.sequences))

    def test_preplot_resolves_uv_undershoot_lines(self) -> None:
        rows = build_postplot_4d_rows(self.map_data, self.settings, "preplot")
        matched = {
            (row.baseline_name, row.line_name)
            for row in rows
            if row.has_match
        }
        expected = {
            ("0114451U", "8114451U-032"),
            ("0114552U", "8114552U-030"),
            ("0115057V", "8115057V-035"),
            ("0115663V", "8115663V-033"),
            ("0116269V", "8116269V-031"),
        }
        self.assertTrue(expected.issubset(matched))

    def test_shared_baseline_can_match_multiple_reshoot_lines(self) -> None:
        rows = build_postplot_4d_rows(self.map_data, self.settings, "preplot")
        by_baseline = Counter(row.baseline_name for row in rows if row.has_match)
        for baseline_name in ("0110815A", "0116875A", "0125865A"):
            self.assertGreaterEqual(by_baseline[baseline_name], 2)


@unittest.skipUnless(DB_7027.is_file(), "7027.db not available")
class Brutal7027MatchingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings, cls.map_data = _load(DB_7027, "7027")

    def test_preplot_matching_maps_all_imported_trinav_lines(self) -> None:
        rows = build_postplot_4d_rows(self.map_data, self.settings, "preplot")
        audit = _audit_rows(rows, self.map_data.sequences)
        self.assertEqual(len(audit["unexpected_orphans"]), 0, audit["unexpected_orphans"])
        self.assertEqual(len(audit["multi_baseline"]), 0, audit["multi_baseline"])
        self.assertEqual(len(audit["suspicious"]), 0, audit["suspicious"])
        self.assertEqual(len(audit["matched"]), len(self.map_data.sequences))

    def test_preplot_expected_trinav_pairs(self) -> None:
        rows = build_postplot_4d_rows(self.map_data, self.settings, "preplot")
        matched = {
            row.baseline_name: (row.line_name, row.sequence_no)
            for row in rows
            if row.has_match
        }
        self.assertEqual(matched, _7027_EXPECTED)

    def test_preplot_does_not_match_unrelated_trinav_sequence(self) -> None:
        rows = build_postplot_4d_rows(self.map_data, self.settings, "preplot")
        for row in rows:
            if row.baseline_name == "51892":
                self.assertTrue(row.has_match)
                self.assertEqual(row.line_name, "51892113001")
                self.assertEqual(row.sequence_no, "3001")
                return
        self.fail("Expected preplot baseline 51892 in 7027 rows")


if __name__ == "__main__":
    unittest.main()
