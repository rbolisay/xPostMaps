"""Build line sequences and segments from parsed position records."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from xpostmaps.core.models import (
    LineSegment,
    LineSequence,
    PositionRecord,
    RecordType,
    make_sequence_group_id,
    make_sequence_id,
)
from xpostmaps.utils.numba_accel import infer_line_direction


def _direction_label(direction: int, line_direction: str) -> str:
    if line_direction:
        return line_direction
    return "Up" if direction >= 0 else "Down"


def build_sequences(records: list[PositionRecord]) -> list[LineSequence]:
    grouped: dict[tuple[str, str, str, RecordType], list[PositionRecord]] = defaultdict(list)
    for rec in records:
        if rec.record_type not in (RecordType.SOURCE, RecordType.VESSEL):
            continue
        seq_no = rec.sequence_no or rec.line_name or "1"
        key = (rec.file_name, seq_no, rec.line_name.strip() or "UNNAMED", rec.record_type)
        grouped[key].append(rec)

    sequences: list[LineSequence] = []
    for (file_name, seq_no, line_name, rtype), group in grouped.items():
        group.sort(key=lambda r: r.point_num)
        pnums = [r.point_num for r in group]
        direction = infer_line_direction(np.array(pnums, dtype=np.int64))
        line_dir = group[0].line_direction or _direction_label(direction, "")
        seq_id = make_sequence_id(file_name, seq_no, line_name, rtype)
        sequences.append(
            LineSequence(
                seq_id=seq_id,
                file_name=file_name,
                sequence_no=seq_no,
                line_name=line_name,
                line_direction=line_dir,
                first_sp=min(pnums),
                last_sp=max(pnums),
                record_type=rtype,
            )
        )
    sequences.sort(key=lambda s: (s.file_name, s.sequence_no, s.line_name, s.record_type.value))
    return sequences


def build_display_sequences(records: list[PositionRecord]) -> list[LineSequence]:
    """Merge vessel + source sequences into one row per sequence for legend UI."""
    merged: dict[str, LineSequence] = {}
    for seq in build_sequences(records):
        group_id = make_sequence_group_id(seq.file_name, seq.sequence_no, seq.line_name)
        if group_id not in merged:
            merged[group_id] = LineSequence(
                seq_id=group_id,
                file_name=seq.file_name,
                sequence_no=seq.sequence_no,
                line_name=seq.line_name,
                line_direction=seq.line_direction,
                first_sp=seq.first_sp,
                last_sp=seq.last_sp,
                record_type=seq.record_type,
            )
        else:
            existing = merged[group_id]
            existing.first_sp = min(existing.first_sp, seq.first_sp)
            existing.last_sp = max(existing.last_sp, seq.last_sp)
            if not existing.line_direction and seq.line_direction:
                existing.line_direction = seq.line_direction
    return sorted(
        merged.values(),
        key=lambda s: (s.file_name, s.sequence_no, s.line_name),
    )


def records_to_segments(records: list[PositionRecord]) -> list[LineSegment]:
    grouped: dict[tuple[str, str, str, RecordType], dict[int, PositionRecord]] = defaultdict(dict)
    for rec in records:
        if rec.record_type not in (RecordType.SOURCE, RecordType.VESSEL):
            continue
        seq_no = rec.sequence_no or rec.line_name or "1"
        key = (rec.file_name, seq_no, rec.line_name.strip() or "UNNAMED", rec.record_type)
        bucket = grouped[key]
        if rec.record_type == RecordType.SOURCE:
            bucket[rec.point_num] = rec
        elif rec.point_num not in bucket:
            bucket[rec.point_num] = rec

    segments: list[LineSegment] = []
    for (file_name, seq_no, line_name, rtype), bucket in grouped.items():
        group = sorted(bucket.values(), key=lambda r: r.point_num)
        xs = [r.x for r in group]
        ys = [r.y for r in group]
        pnums = np.array([r.point_num for r in group], dtype=np.int64)
        direction = infer_line_direction(pnums)
        line_dir = group[0].line_direction or _direction_label(direction, "")
        seq_id = make_sequence_id(file_name, seq_no, line_name, rtype)
        segments.append(
            LineSegment(
                line_name=line_name,
                record_type=rtype,
                xs=xs,
                ys=ys,
                direction=direction,
                sequence_id=seq_id,
                file_name=file_name,
                sequence_no=seq_no,
                line_direction=line_dir,
            )
        )
    return segments
