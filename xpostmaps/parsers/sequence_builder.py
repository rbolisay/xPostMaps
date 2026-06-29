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


def _fsp_lsp_for_direction(pnums: np.ndarray, direction: int) -> tuple[int, int]:
    """Return (first_sp, last_sp) honoring acquisition direction.

    Uses the min/max extremes (robust to a stray first/last record) but orders
    them by the majority-vote *direction* so descending lines report FSP > LSP.
    """
    if pnums.size == 0:
        return 0, 0
    lo = int(pnums.min())
    hi = int(pnums.max())
    if direction < 0:
        return hi, lo
    return lo, hi


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
        # Records arrive in acquisition (file) order. Infer direction from that
        # order — NOT a pre-sorted copy — so FSP/LSP reflect how the line was
        # actually shot. Lines acquired with descending shotpoint numbering must
        # report FSP > LSP (e.g. FSP 1508 -> LSP 1489), not always ascending.
        pnums = np.array([r.point_num for r in group], dtype=np.int64)
        direction = infer_line_direction(pnums)
        explicit_dir = next((r.line_direction for r in group if r.line_direction), "")
        line_dir = explicit_dir or _direction_label(direction, "")
        subline = next((r.subline for r in group if r.subline), "")
        first_sp, last_sp = _fsp_lsp_for_direction(pnums, direction)
        seq_id = make_sequence_id(file_name, seq_no, line_name, rtype)
        sequences.append(
            LineSequence(
                seq_id=seq_id,
                file_name=file_name,
                sequence_no=seq_no,
                line_name=line_name,
                subline=subline,
                line_direction=line_dir,
                first_sp=first_sp,
                last_sp=last_sp,
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
                subline=seq.subline,
                line_direction=seq.line_direction,
                first_sp=seq.first_sp,
                last_sp=seq.last_sp,
                record_type=seq.record_type,
            )
        else:
            existing = merged[group_id]
            # Merge the source/vessel extents while preserving acquisition
            # direction: a descending line (FSP > LSP) must stay descending.
            lo = min(existing.first_sp, existing.last_sp, seq.first_sp, seq.last_sp)
            hi = max(existing.first_sp, existing.last_sp, seq.first_sp, seq.last_sp)
            descending = existing.first_sp > existing.last_sp
            existing.first_sp, existing.last_sp = (hi, lo) if descending else (lo, hi)
            if not existing.subline and seq.subline:
                existing.subline = seq.subline
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
        # bucket preserves acquisition (file) insertion order. Infer direction
        # from that order before sorting, so down-lines stay down-lines.
        acq_pnums = np.array([r.point_num for r in bucket.values()], dtype=np.int64)
        direction = infer_line_direction(acq_pnums)
        group = sorted(bucket.values(), key=lambda r: r.point_num)
        xs = [r.x for r in group]
        ys = [r.y for r in group]
        line_dir = (
            next((r.line_direction for r in group if r.line_direction), "")
            or _direction_label(direction, "")
        )
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
