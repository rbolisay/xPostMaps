"""Tests for sequence-to-postplot assignment helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.sequence_utils import (
    assignments_to_row_sequence_ids,
    row_sequence_ids_to_assignments,
)


def main() -> int:
    names = ["Source Upline", "Source Downline"]
    row_ids = [["seq-a", "seq-b"], ["seq-c"]]
    assignments = row_sequence_ids_to_assignments(names, row_ids)
    assert assignments == {
        "seq-a": "Source Upline",
        "seq-b": "Source Upline",
        "seq-c": "Source Downline",
    }
    rebuilt = assignments_to_row_sequence_ids(names, assignments)
    assert rebuilt == row_ids

    moved = assignments_to_row_sequence_ids(
        names,
        {"seq-a": "Source Downline", "seq-b": "Source Downline", "seq-c": "Source Upline"},
    )
    assert moved == [["seq-c"], ["seq-a", "seq-b"]]
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
