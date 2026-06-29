"""FSP/LSP must follow acquisition direction (ascending OR descending)."""

from __future__ import annotations

from xpostmaps.core.models import PositionRecord, RecordType
from xpostmaps.parsers.sequence_builder import (
    build_display_sequences,
    build_sequences,
)


def _rec(point_num: int, rtype: RecordType = RecordType.SOURCE) -> PositionRecord:
    return PositionRecord(
        file_name="line.p190",
        record_type=rtype,
        line_name="0103643A",
        vessel_id="V1",
        source_id="S1",
        point_num=point_num,
        x=float(point_num),
        y=0.0,
        sequence_no="1",
    )


def test_ascending_acquisition_keeps_fsp_lt_lsp():
    records = [_rec(pn) for pn in range(1489, 1509)]  # 1489 -> 1508
    [seq] = build_sequences(records)
    assert seq.first_sp == 1489
    assert seq.last_sp == 1508


def test_descending_acquisition_reports_fsp_gt_lsp():
    records = [_rec(pn) for pn in range(1508, 1488, -1)]  # 1508 -> 1489
    [seq] = build_sequences(records)
    assert seq.first_sp == 1508
    assert seq.last_sp == 1489


def test_display_merge_preserves_descending_direction():
    # Source + vessel of the same descending line must stay descending.
    records = [_rec(pn, RecordType.SOURCE) for pn in range(1508, 1488, -1)]
    records += [_rec(pn, RecordType.VESSEL) for pn in range(1508, 1488, -1)]
    [seq] = build_display_sequences(records)
    assert seq.first_sp == 1508
    assert seq.last_sp == 1489
