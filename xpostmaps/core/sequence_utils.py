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

# Bump when navigation parsing logic changes (invalidates incremental nav cache).
NAV_PARSE_VERSION = "p190-header-v3"
PREPLOT_PARSE_VERSION = "preplot-v1"
NAVPLAN_PARSE_VERSION = "navplan-v1"


def import_file_signature(path: Path, version: str) -> tuple[float, int, str]:
    stat = path.stat()
    return stat.st_mtime, stat.st_size, version


def nav_file_signature(path: Path) -> tuple[float, int, str]:
    return import_file_signature(path, NAV_PARSE_VERSION)


def preplot_file_signature(path: Path) -> tuple[float, int, str]:
    return import_file_signature(path, PREPLOT_PARSE_VERSION)


def navplan_file_signature(path: Path) -> tuple[float, int, str]:
    return import_file_signature(path, NAVPLAN_PARSE_VERSION)


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


def nav_cache_to_json(cache: dict[str, tuple[float, int, str]]) -> dict[str, list[float | int | str]]:
    return {path: [mtime, size, version] for path, (mtime, size, version) in cache.items()}


def nav_cache_from_json(data: dict | None) -> dict[str, tuple[float, int, str]]:
    return import_file_cache_from_json(data, NAV_PARSE_VERSION)


def preplot_cache_from_json(data: dict | None) -> dict[str, tuple[float, int, str]]:
    return import_file_cache_from_json(data, PREPLOT_PARSE_VERSION)


def navplan_cache_from_json(data: dict | None) -> dict[str, tuple[float, int, str]]:
    return import_file_cache_from_json(data, NAVPLAN_PARSE_VERSION)


def import_file_cache_from_json(
    data: dict | None,
    version: str,
) -> dict[str, tuple[float, int, str]]:
    if not data:
        return {}
    result: dict[str, tuple[float, int, str]] = {}
    for path, values in data.items():
        if not isinstance(values, (list, tuple)) or len(values) < 2:
            continue
        mtime = float(values[0])
        size = int(values[1])
        cached_version = str(values[2]) if len(values) >= 3 else ""
        if cached_version != version:
            continue
        result[path] = (mtime, size, cached_version)
    return result


def row_sequence_ids_to_assignments(
    postplot_names: list[str],
    row_sequence_ids: list[list[str]],
) -> dict[str, str]:
    """Map each sequence id to its assigned postplot legend row name."""
    assignments: dict[str, str] = {}
    for name, seq_ids in zip(postplot_names, row_sequence_ids):
        if not name:
            continue
        for seq_id in seq_ids:
            assignments[str(seq_id)] = name
    return assignments


def assignments_to_row_sequence_ids(
    postplot_names: list[str],
    assignments: dict[str, str],
) -> list[list[str]]:
    """Rebuild per-postplot sequence id lists from a flat assignment map."""
    result: list[list[str]] = [[] for _ in postplot_names]
    index_by_name = {name: index for index, name in enumerate(postplot_names) if name}
    for seq_id, postplot_name in assignments.items():
        row_index = index_by_name.get(postplot_name)
        if row_index is None:
            continue
        bucket = result[row_index]
        if seq_id not in bucket:
            bucket.append(seq_id)
    return result
