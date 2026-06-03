"""Navplan catalog, parsing, and legend sync helpers."""

from __future__ import annotations

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


def build_navplan_catalog(paths: list[Path]) -> list[NavplanCatalogEntry]:
    catalog: list[NavplanCatalogEntry] = []
    for index, path in enumerate(sorted(paths), start=1):
        resolved = path.resolve()
        if not resolved.is_file():
            continue
        result = parse_navplan_source_file(resolved)
        crs = (
            result.metadata.get("epsg code")
            or result.metadata.get("epsg")
            or result.metadata.get("authority")
            or ""
        )
        navplan_name = (
            result.metadata.get("preplot line number")
            or result.metadata.get("linename/subline")
            or resolved.stem
        )
        fsp, lsp = _fsp_lsp_from_records(result.records)
        catalog.append(
            NavplanCatalogEntry(
                navplan_number=index,
                navplan_name=navplan_name.strip("/ ") or resolved.stem,
                file_path=str(resolved),
                crs_code=normalize_epsg(crs) or crs,
                fsp=fsp,
                lsp=lsp,
                total_points=len(result.records),
            )
        )
    renumber_navplan_catalog(catalog)
    return catalog


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
        catalog.append(
            NavplanCatalogEntry(
                navplan_number=index,
                navplan_name=navplan_name.strip("/ ") or path.stem,
                file_path=str(path.resolve()),
                crs_code=normalize_epsg(crs) or crs,
                fsp=fsp,
                lsp=lsp,
                total_points=total_points,
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
            "file_path": entry.file_path,
            "crs_code": entry.crs_code,
            "fsp": entry.fsp,
            "lsp": entry.lsp,
            "total_points": entry.total_points,
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
            file_path=str(item.get("file_path", "")),
            crs_code=str(item.get("crs_code", "")),
            fsp=int(item.get("fsp", 0)),
            lsp=int(item.get("lsp", 0)),
            total_points=int(item.get("total_points", 0)),
        )
        for item in data
    ]
