"""Helpers for sequence grouping, matching, and nav file cache signatures."""

from __future__ import annotations

from pathlib import Path

from xpostmaps.core.models import (
    LineSegment,
    LineSequence,
    PositionRecord,
    make_sequence_group_id,
    sequence_group_id,
    sequence_id_matches,
)


def nav_file_signature(path: Path) -> tuple[float, int]:
    stat = path.stat()
    return stat.st_mtime, stat.st_size


def nav_file_cache_key(path: Path) -> str:
    return str(path.resolve())


def position_belongs_to_group(pos: PositionRecord, group_id: str) -> bool:
    seq_no = pos.sequence_no or pos.line_name or "1"
    line_name = pos.line_name.strip() or "UNNAMED"
    gid = make_sequence_group_id(pos.file_name, seq_no, line_name)
    return gid == group_id or sequence_group_id(group_id) == gid


def segment_belongs_to_group(segment: LineSegment, group_id: str) -> bool:
    return sequence_id_matches(segment.sequence_id, [group_id])


def sequence_belongs_to_group(sequence: LineSequence, group_id: str) -> bool:
    return (
        sequence.seq_id == group_id
        or sequence_group_id(sequence.seq_id) == group_id
        or make_sequence_group_id(
            sequence.file_name, sequence.sequence_no, sequence.line_name
        )
        == group_id
    )


def filter_positions_by_groups(
    positions: list[PositionRecord], group_ids: set[str]
) -> list[PositionRecord]:
    if not group_ids:
        return positions
    return [p for p in positions if not any(position_belongs_to_group(p, g) for g in group_ids)]


def filter_segments_by_groups(
    segments: list[LineSegment], group_ids: set[str]
) -> list[LineSegment]:
    if not group_ids:
        return segments
    return [s for s in segments if not any(segment_belongs_to_group(s, g) for g in group_ids)]


def filter_sequences_by_groups(
    sequences: list[LineSequence], group_ids: set[str]
) -> list[LineSequence]:
    if not group_ids:
        return sequences
    return [s for s in sequences if not any(sequence_belongs_to_group(s, g) for g in group_ids)]


def positions_for_file_name(
    positions: list[PositionRecord], file_name: str
) -> list[PositionRecord]:
    return [p for p in positions if p.file_name == file_name]


def nav_cache_to_json(cache: dict[str, tuple[float, int]]) -> dict[str, list[float | int]]:
    return {path: [mtime, size] for path, (mtime, size) in cache.items()}


def nav_cache_from_json(data: dict | None) -> dict[str, tuple[float, int]]:
    if not data:
        return {}
    result: dict[str, tuple[float, int]] = {}
    for path, values in data.items():
        if isinstance(values, (list, tuple)) and len(values) >= 2:
            result[path] = (float(values[0]), int(values[1]))
    return result
