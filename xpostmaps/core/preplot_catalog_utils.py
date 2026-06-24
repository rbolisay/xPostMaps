"""Preplot catalog and legend sync helpers."""

from __future__ import annotations

from pathlib import Path

from xpostmaps.core.crs_utils import normalize_epsg
from xpostmaps.core.models import (
    LegendConfig,
    LineSegment,
    LineStyle,
    PreplotCatalogEntry,
    PreplotLegendEntry,
)
from xpostmaps.parsers.preplot_parser import parse_preplot_file
from xpostmaps.ui.theme import PREPLOT_LINE


def preplot_source_labels(count: int) -> list[str]:
    return [f"Preplot {index}" for index in range(1, count + 1)]


def renumber_preplot_catalog(entries: list[PreplotCatalogEntry]) -> None:
    for index, entry in enumerate(entries, start=1):
        entry.preplot_number = index


def build_preplot_catalog(paths: list[Path]) -> list[PreplotCatalogEntry]:
    catalog: list[PreplotCatalogEntry] = []
    for index, path in enumerate(sorted(paths), start=1):
        resolved = path.resolve()
        if not resolved.is_file():
            continue
        result = parse_preplot_file(resolved)
        crs = (
            result.metadata.get("epsg code")
            or result.metadata.get("epsg")
            or result.metadata.get("authority")
            or ""
        )
        catalog.append(
            PreplotCatalogEntry(
                preplot_number=index,
                file_path=str(resolved),
                crs_code=normalize_epsg(crs) or crs,
                total_lines=len(result.segments),
            )
        )
    renumber_preplot_catalog(catalog)
    return catalog


def build_preplot_catalog_from_segments(
    paths: list[str],
    segments: list[LineSegment],
    fallback_crs: str = "",
) -> list[PreplotCatalogEntry]:
    line_counts: dict[str, int] = {}
    for segment in segments:
        if segment.file_name:
            line_counts[segment.file_name] = line_counts.get(segment.file_name, 0) + 1

    catalog: list[PreplotCatalogEntry] = []
    for index, raw_path in enumerate(sorted(paths), start=1):
        path = Path(raw_path)
        if not path.is_file():
            continue
        result = parse_preplot_file(path)
        crs = (
            result.metadata.get("epsg code")
            or result.metadata.get("epsg")
            or result.metadata.get("authority")
            or fallback_crs
        )
        catalog.append(
            PreplotCatalogEntry(
                preplot_number=index,
                file_path=str(path.resolve()),
                crs_code=normalize_epsg(crs) or crs,
                total_lines=line_counts.get(path.name, len(result.segments)),
            )
        )
    renumber_preplot_catalog(catalog)
    return catalog


def sync_preplot_legend_entries(
    legend: LegendConfig,
    catalog: list[PreplotCatalogEntry],
) -> None:
    count = len(catalog)
    legend.preplot_lines = [
        row
        for row in legend.preplot_lines
        if 0 <= row.preplot_source_index < count
    ]
    covered = {row.preplot_source_index for row in legend.preplot_lines}
    for entry in catalog:
        source_index = entry.preplot_number - 1
        if source_index in covered:
            continue
        legend.preplot_lines.append(
            PreplotLegendEntry(
                name=Path(entry.file_path).stem,
                preplot_source_index=source_index,
                line_style=LineStyle.SOLID,
                color=PREPLOT_LINE,
                opacity=1.0,
                hidden=False,
            )
        )


def resolve_preplot_file_order(
    map_data,
    settings=None,
) -> list[str]:
    """Return ordered preplot file paths for legend source matching."""
    if settings is not None:
        catalog = getattr(settings, "preplot_catalog", None) or []
        if catalog:
            return [
                entry.file_path
                for entry in sorted(catalog, key=lambda item: item.preplot_number)
            ]
        if settings.preplot_files:
            resolved = [
                str(Path(raw).resolve())
                for raw in sorted(settings.preplot_files)
                if Path(raw).is_file()
            ]
            if resolved:
                return resolved
    if map_data is not None and map_data.preplot_file_order:
        return list(map_data.preplot_file_order)
    if map_data is not None and map_data.preplot_segments:
        seen: list[str] = []
        for segment in map_data.preplot_segments:
            if segment.file_name and segment.file_name not in seen:
                seen.append(segment.file_name)
        return seen
    return []


def segments_for_preplot_source(
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


def catalog_to_json(catalog: list[PreplotCatalogEntry]) -> list[dict]:
    return [
        {
            "preplot_number": entry.preplot_number,
            "file_path": entry.file_path,
            "crs_code": entry.crs_code,
            "total_lines": entry.total_lines,
        }
        for entry in catalog
    ]


def catalog_from_json(data: list[dict] | None) -> list[PreplotCatalogEntry]:
    if not data:
        return []
    return [
        PreplotCatalogEntry(
            preplot_number=int(item.get("preplot_number", 0)),
            file_path=str(item.get("file_path", "")),
            crs_code=str(item.get("crs_code", "")),
            total_lines=int(item.get("total_lines", 0)),
        )
        for item in data
    ]
