"""Tests for navplan-to-legend assignment helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.navplan_catalog_utils import (
    assignments_to_row_navplan_indices,
    row_navplan_indices_to_assignments,
)


def main() -> int:
    names = ["Navplan Upline", "Navplan Downline"]
    row_indices = [[0, 1], [2]]
    assignments = row_navplan_indices_to_assignments(names, row_indices)
    assert assignments == {0: "Navplan Upline", 1: "Navplan Upline", 2: "Navplan Downline"}
    rebuilt = assignments_to_row_navplan_indices(names, assignments)
    assert rebuilt == row_indices
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
