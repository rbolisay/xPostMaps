"""Navplan catalog, parsing, and legend sync helpers."""

from __future__ import annotations

import os
from pathlib import Path

from xpostmaps.core.crs_utils import normalize_epsg
from xpostmaps.core.models import (
    LegendConfig,
    LineSegment,
    NavplanCatalogEntry,
)
from xpostmaps.parsers.preplot_parser import (
    NAVPLAN_IMPORT_EXTENSIONS,
    parse_navplan_source_file,
)
from xpostmaps.parsers.p190_parser import format_line_direction


def line_direction_from_metadata(metadata: dict[str, str]) -> str:
    """Return formatted navplan line direction from parsed file metadata."""
    for key in ("line direction", "line heading"):
        value = (metadata.get(key) or "").strip()
        if not value:
            continue
        if "°" in value:
            return value
        formatted = format_line_direction(value)
        return formatted or value
    for key, raw in metadata.items():
        normalized = key.lower().replace(" ", "")
        if "line" in normalized and "direction" in normalized:
            formatted = format_line_direction(raw)
            if formatted:
                return formatted
    return ""


def navplan_source_labels(count: int) -> list[str]:
    return [f"Navplan {index}" for index in range(1, count + 1)]


def is_navplan_import_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix in NAVPLAN_IMPORT_EXTENSIONS


def collect_navplan_files_from_folder(folder: str) -> list[str]:
    root = Path(folder)
    if not root.is_dir():
        return []
    return [
        str(path.resolve())
        for path in sorted(root.rglob("*"))
        if path.is_file() and is_navplan_import_file(path)
    ]


def resolve_navplan_files(settings) -> list[Path]:
    if getattr(settings, "navplan_files_explicit", False) or getattr(settings, "navplan_files", []):
        return sorted(Path(f) for f in settings.navplan_files if Path(f).is_file())
    folder = getattr(settings, "navplans_dir", "") or ""
    if folder:
        return [Path(path) for path in collect_navplan_files_from_folder(folder)]
    return []


def renumber_navplan_catalog(entries: list[NavplanCatalogEntry]) -> None:
    for index, entry in enumerate(entries, start=1):
        entry.navplan_number = index


def catalog_path_key(path: str | Path) -> str:
    """Normalize catalog file paths for stable lookup without network resolve."""
    return os.path.normcase(os.path.normpath(str(path)))


def _file_fingerprint(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _entry_matches_file(entry: NavplanCatalogEntry, path: Path) -> bool:
    if entry.file_mtime_ns <= 0 and entry.file_size <= 0:
        return False
    mtime_ns, size = _file_fingerprint(path)
    return mtime_ns == entry.file_mtime_ns and size == entry.file_size


def build_navplan_catalog_entry(path: Path) -> NavplanCatalogEntry | None:
    if not path.is_file():
        return None
    result = parse_navplan_source_file(path)
    crs = (
        result.metadata.get("epsg code")
        or result.metadata.get("epsg")
        or result.metadata.get("authority")
        or ""
    )
    navplan_name = (
        result.metadata.get("preplot line number")
        or result.metadata.get("linename/subline")
        or path.stem
    )
    fsp, lsp = _fsp_lsp_from_records(result.records)
    mtime_ns, size = _file_fingerprint(path)
    return NavplanCatalogEntry(
        navplan_name=navplan_name.strip("/ ") or path.stem,
        line_direction=line_direction_from_metadata(result.metadata),
        file_path=str(path),
        crs_code=normalize_epsg(crs) or crs,
        fsp=fsp,
        lsp=lsp,
        total_points=len(result.records),
        file_mtime_ns=mtime_ns,
        file_size=size,
    )


def catalog_for_saved_files(
    file_paths: list[str],
    saved_catalog: list[NavplanCatalogEntry],
) -> list[NavplanCatalogEntry]:
    """Return saved catalog rows for known files without touching the filesystem."""
    by_path = {catalog_path_key(entry.file_path): entry for entry in saved_catalog}
    catalog: list[NavplanCatalogEntry] = []
    for raw_path in sorted(file_paths, key=lambda value: catalog_path_key(value)):
        entry = by_path.get(catalog_path_key(raw_path))
        if entry is not None:
            catalog.append(entry)
    renumber_navplan_catalog(catalog)
    return catalog


def refresh_navplan_catalog(
    file_paths: list[str],
    saved_catalog: list[NavplanCatalogEntry] | None = None,
    *,
    force: bool = False,
) -> list[NavplanCatalogEntry]:
    """Rebuild catalog entries, reusing saved rows when files are unchanged."""
    saved = saved_catalog or []
    by_path = {catalog_path_key(entry.file_path): entry for entry in saved}
    catalog: list[NavplanCatalogEntry] = []
    for raw_path in sorted(file_paths, key=lambda value: catalog_path_key(value)):
        path = Path(raw_path)
        if not path.is_file():
            continue
        key = catalog_path_key(path)
        if not force:
            saved_entry = by_path.get(key)
            if saved_entry is not None and _entry_matches_file(saved_entry, path):
                catalog.append(saved_entry)
                continue
        entry = build_navplan_catalog_entry(path)
        if entry is not None:
            catalog.append(entry)
    renumber_navplan_catalog(catalog)
    return catalog


def build_navplan_catalog(paths: list[Path]) -> list[NavplanCatalogEntry]:
    return refresh_navplan_catalog(
        [str(path) for path in paths],
        force=True,
    )


def _fsp_lsp_from_records(records) -> tuple[int, int]:
    points = [record.point_num for record in records if record.point_num]
    if not points:
        return 0, 0
    return min(points), max(points)


def build_navplan_catalog_from_segments(
    paths: list[str],
    segments: list[LineSegment],
    fallback_crs: str = "",
) -> list[NavplanCatalogEntry]:
    segments_by_name: dict[str, list[LineSegment]] = {}
    for segment in segments:
        if segment.file_name:
            segments_by_name.setdefault(Path(segment.file_name).name, []).append(segment)

    catalog: list[NavplanCatalogEntry] = []
    for index, raw_path in enumerate(sorted(paths), start=1):
        path = Path(raw_path)
        if not path.is_file():
            continue
        result = parse_navplan_source_file(path)
        crs = (
            result.metadata.get("epsg code")
            or result.metadata.get("epsg")
            or result.metadata.get("authority")
            or fallback_crs
        )
        navplan_name = (
            result.metadata.get("preplot line number")
            or result.metadata.get("linename/subline")
            or path.stem
        )
        file_segments = segments_by_name.get(path.name, result.segments)
        fsp, lsp = _fsp_lsp_from_records(result.records)
        total_points = sum(len(segment.xs) for segment in file_segments) or len(result.records)
        mtime_ns, size = _file_fingerprint(path)
        catalog.append(
            NavplanCatalogEntry(
                navplan_number=index,
                navplan_name=navplan_name.strip("/ ") or path.stem,
                line_direction=line_direction_from_metadata(result.metadata),
                file_path=str(path),
                crs_code=normalize_epsg(crs) or crs,
                fsp=fsp,
                lsp=lsp,
                total_points=total_points,
                file_mtime_ns=mtime_ns,
                file_size=size,
            )
        )
    renumber_navplan_catalog(catalog)
    return catalog


def sync_navplan_legend_entries(
    legend: LegendConfig,
    catalog: list[NavplanCatalogEntry],
) -> None:
    """Prune stale navplan selections without auto-creating legend rows."""
    count = len(catalog)
    legend.navplan_lines = [
        row
        for row in legend.navplan_lines
        if any(0 <= index < count for index in row.navplan_source_indices)
    ]


def resolve_navplan_file_order(map_data, settings=None) -> list[str]:
    if map_data is not None and map_data.navplan_file_order:
        return list(map_data.navplan_file_order)
    if settings is not None:
        if settings.navplan_files:
            return [
                str(Path(raw).resolve())
                for raw in sorted(settings.navplan_files)
                if Path(raw).is_file()
            ]
        catalog = getattr(settings, "navplan_catalog", None) or []
        if catalog:
            return [
                entry.file_path
                for entry in sorted(catalog, key=lambda item: item.navplan_number)
            ]
    if map_data is not None and map_data.navplan_segments:
        seen: list[str] = []
        for segment in map_data.navplan_segments:
            if segment.file_name and segment.file_name not in seen:
                seen.append(segment.file_name)
        return seen
    return []


def segments_for_navplan_source(
    segments: list[LineSegment],
    file_paths: list[str],
    source_index: int,
) -> list[LineSegment]:
    if source_index < 0 or source_index >= len(file_paths):
        return []
    target_ref = file_paths[source_index]
    target_name = Path(target_ref).name
    return [
        segment
        for segment in segments
        if segment.file_name == target_name
        or segment.file_name == target_ref
        or Path(segment.file_name).name == target_name
    ]


def parse_navplan_files(paths: list[Path]) -> tuple[list[LineSegment], dict[str, str], dict[str, int]]:
    all_segments: list[LineSegment] = []
    all_metadata: dict[str, str] = {}
    stats = {"navplan_files": 0, "navplan_lines": 0, "navplan_points": 0}
    for path in paths:
        result = parse_navplan_source_file(path)
        all_segments.extend(result.segments)
        for key, value in result.metadata.items():
            if key not in all_metadata or not all_metadata[key]:
                all_metadata[key] = value
        stats["navplan_files"] += 1
        stats["navplan_lines"] += len(result.segments)
        stats["navplan_points"] += len(result.records)
    return all_segments, all_metadata, stats


def navplan_catalog_to_json(catalog: list[NavplanCatalogEntry]) -> list[dict]:
    return [
        {
            "navplan_number": entry.navplan_number,
            "navplan_name": entry.navplan_name,
            "line_direction": entry.line_direction,
            "file_path": entry.file_path,
            "crs_code": entry.crs_code,
            "fsp": entry.fsp,
            "lsp": entry.lsp,
            "total_points": entry.total_points,
            "file_mtime_ns": entry.file_mtime_ns,
            "file_size": entry.file_size,
        }
        for entry in catalog
    ]


def navplan_catalog_from_json(data: list[dict] | None) -> list[NavplanCatalogEntry]:
    if not data:
        return []
    return [
        NavplanCatalogEntry(
            navplan_number=int(item.get("navplan_number", 0)),
            navplan_name=str(item.get("navplan_name", "")),
            line_direction=str(item.get("line_direction", "")),
            file_path=str(item.get("file_path", "")),
            crs_code=str(item.get("crs_code", "")),
            fsp=int(item.get("fsp", 0)),
            lsp=int(item.get("lsp", 0)),
            total_points=int(item.get("total_points", 0)),
            file_mtime_ns=int(item.get("file_mtime_ns", 0)),
            file_size=int(item.get("file_size", 0)),
        )
        for item in data
    ]


def row_navplan_indices_to_assignments(
    navplan_legend_names: list[str],
    row_navplan_indices: list[list[int]],
) -> dict[int, str]:
    """Map each navplan source index to its assigned legend row name."""
    assignments: dict[int, str] = {}
    for name, indices in zip(navplan_legend_names, row_navplan_indices):
        if not name:
            continue
        for source_index in indices:
            assignments[int(source_index)] = name
    return assignments


def assignments_to_row_navplan_indices(
    navplan_legend_names: list[str],
    assignments: dict[int, str],
) -> list[list[int]]:
    """Rebuild per-legend-row navplan source index lists from a flat assignment map."""
    result: list[list[int]] = [[] for _ in navplan_legend_names]
    index_by_name = {
        name: index for index, name in enumerate(navplan_legend_names) if name
    }
    for source_index, legend_name in assignments.items():
        row_index = index_by_name.get(legend_name)
        if row_index is None:
            continue
        bucket = result[row_index]
        idx = int(source_index)
        if idx not in bucket:
            bucket.append(idx)
    return result
