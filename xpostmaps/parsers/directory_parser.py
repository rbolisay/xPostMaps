"""Directory scanner and batch parser for P111/P190 navigation files."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from xpostmaps.core.models import (
    GeoBounds,
    MapData,
    PositionRecord,
    PostmapInfo,
    ProjectSettings,
    RecordType,
    SurveyBounds,
)
from xpostmaps.core.sequence_utils import nav_file_cache_key, nav_file_signature
from xpostmaps.parsers.metadata_parser import collect_postmap_metadata
from xpostmaps.parsers.p111_parser import parse_p111_file, scan_vessel_id
from xpostmaps.parsers.p190_parser import parse_p190_file
from xpostmaps.parsers.preplot_parser import parse_preplot_files, resolve_preplot_files
from xpostmaps.parsers.sequence_builder import build_display_sequences, records_to_segments
from xpostmaps.utils.numba_accel import compute_bounds

NAV_EXTENSIONS = {".p111", ".p190", ".P111", ".P190", ".txt", ".nav"}


def _detect_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".p111",):
        return "p111"
    if suffix in (".p190",):
        return "p190"
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for _ in range(20):
            line = handle.readline()
            if not line:
                break
            if line.startswith("H") and "," in line[1:10]:
                return "p111"
            if line.startswith(("S", "V", "E")) and "," in line:
                return "p111"
            if line.startswith(("S", "V", "E")) and len(line) > 55:
                return "p190"
    return "p190"


def _collect_files(directory: str, extensions: set[str]) -> list[Path]:
    root = Path(directory)
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in extensions:
            files.append(path)
    return sorted(files)


def resolve_nav_files(settings: ProjectSettings) -> list[Path]:
    if settings.nav_files:
        files = [Path(f) for f in settings.nav_files if Path(f).is_file()]
        if files:
            return sorted(files)
    if settings.p111_p190_dir:
        return _collect_files(settings.p111_p190_dir, NAV_EXTENSIONS)
    return []


def _parse_nav_file(path: Path, vessel_id: str | None = None) -> list[PositionRecord]:
    fmt = _detect_format(path)
    if fmt == "p111":
        return parse_p111_file(path, vessel_id=vessel_id)
    records = parse_p190_file(path)
    for rec in records:
        if not rec.sequence_no:
            rec.sequence_no = rec.line_name.strip() or "1"
    return records


def _records_to_segments(
    records: list[PositionRecord],
    default_type: RecordType | None = None,
) -> list:
    if default_type is not None:
        filtered = [
            PositionRecord(
                file_name=r.file_name,
                record_type=default_type,
                line_name=r.line_name,
                vessel_id=r.vessel_id,
                source_id=r.source_id,
                point_num=r.point_num,
                x=r.x,
                y=r.y,
                depth=r.depth,
                latitude=r.latitude,
                longitude=r.longitude,
                sequence_no=r.sequence_no,
                line_direction=r.line_direction,
                subline=r.subline,
            )
            for r in records
        ]
        return records_to_segments(filtered)
    return records_to_segments(records)


def _merge_bounds(current: SurveyBounds, xs: np.ndarray, ys: np.ndarray) -> SurveyBounds:
    if xs.size == 0:
        return current
    xmin, xmax, ymin, ymax = compute_bounds(xs, ys)
    if not current.is_valid:
        return SurveyBounds(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax)
    return SurveyBounds(
        xmin=min(current.xmin, xmin),
        xmax=max(current.xmax, xmax),
        ymin=min(current.ymin, ymin),
        ymax=max(current.ymax, ymax),
    )


def _parse_lat_lon(value: str) -> float | None:
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None


def _compute_geo_bounds(records: list[PositionRecord]) -> GeoBounds:
    lats: list[float] = []
    lons: list[float] = []
    for rec in records:
        lat = _parse_lat_lon(rec.latitude)
        lon = _parse_lat_lon(rec.longitude)
        if lat is not None and lon is not None:
            lats.append(lat)
            lons.append(lon)
    if not lats:
        return GeoBounds()
    return GeoBounds(
        lat_min=min(lats),
        lat_max=max(lats),
        lon_min=min(lons),
        lon_max=max(lons),
    )


def _merge_postmap_info(
    existing: PostmapInfo | None,
    nav_paths: list[Path],
    preplot_paths: list[Path],
    settings: ProjectSettings,
) -> PostmapInfo:
    """Prefer preplot/navplan metadata, then navigation file headers."""
    preplot_info = (
        collect_postmap_metadata(preplot_paths, settings, existing)
        if preplot_paths
        else (existing or PostmapInfo())
    )
    return (
        collect_postmap_metadata(nav_paths, settings, preplot_info)
        if nav_paths
        else preplot_info
    )


def _scan_shared_vessel_id(files: list[Path]) -> str | None:
    """Scan first P111 file header for vessel ID (xp111.py uses first file in batch)."""
    for path in files:
        if _detect_format(path) == "p111":
            vessel_id = scan_vessel_id(path)
            if vessel_id:
                return vessel_id
    return None


def parse_navigation_directory(
    settings: ProjectSettings,
    progress_callback=None,
    existing_postmap: PostmapInfo | None = None,
    existing_map_data: MapData | None = None,
) -> MapData:
    """Parse navigation and preplot/navplan files.

    Navigation files already parsed with the same mtime/size are skipped.
    Updated files replace their previous sequence data.
    """
    map_data = MapData()
    all_x: list[float] = []
    all_y: list[float] = []

    main_files = resolve_nav_files(settings)
    preplot_files = resolve_preplot_files(settings)
    total_steps = max(len(main_files) + len(preplot_files), 1)
    step = 0
    shared_vessel_id = _scan_shared_vessel_id(main_files)

    nav_cache: dict[str, tuple[float, int]] = dict(
        existing_map_data.nav_file_cache if existing_map_data else {}
    )
    active_cache_keys = {nav_file_cache_key(path) for path in main_files}
    nav_cache = {k: v for k, v in nav_cache.items() if k in active_cache_keys}

    files_to_parse: list[Path] = []
    unchanged_names: set[str] = set()
    skipped_files = 0

    for path in main_files:
        cache_key = nav_file_cache_key(path)
        signature = nav_file_signature(path)
        if existing_map_data and nav_cache.get(cache_key) == signature:
            unchanged_names.add(path.name)
            skipped_files += 1
            if progress_callback:
                progress_callback(
                    int(100 * step / total_steps),
                    f"Skipping {path.name} (unchanged)",
                )
            step += 1
            continue
        files_to_parse.append(path)

    carried_records: list[PositionRecord] = []
    if existing_map_data and unchanged_names:
        carried_records = [
            rec
            for rec in existing_map_data.positions
            if rec.file_name in unchanged_names
        ]

    all_records: list[PositionRecord] = list(carried_records)

    for path in preplot_files:
        map_data.source_files.append(str(path))

    for path in main_files:
        map_data.source_files.append(str(path))

    for path in files_to_parse:
        if progress_callback:
            progress_callback(int(100 * step / total_steps), f"Parsing {path.name}")
        records = _parse_nav_file(path, vessel_id=shared_vessel_id)
        all_records.extend(records)
        for rec in records:
            all_x.append(rec.x)
            all_y.append(rec.y)
        nav_cache[nav_file_cache_key(path)] = nav_file_signature(path)
        step += 1

    for rec in carried_records:
        all_x.append(rec.x)
        all_y.append(rec.y)

    map_data.positions = all_records
    map_data.sequences = build_display_sequences(all_records)
    map_data.nav_file_cache = nav_cache

    if settings.show_source:
        src_recs = [r for r in all_records if r.record_type == RecordType.SOURCE]
        map_data.segments.extend(_records_to_segments(src_recs))
    if settings.show_vessel:
        ves_recs = [r for r in all_records if r.record_type == RecordType.VESSEL]
        map_data.segments.extend(_records_to_segments(ves_recs))
    if not map_data.segments and all_records:
        map_data.segments = _records_to_segments(all_records)

    if not main_files and existing_map_data:
        map_data.positions = list(existing_map_data.positions)
        map_data.sequences = list(existing_map_data.sequences)
        map_data.segments = list(existing_map_data.segments)
        map_data.nav_file_cache = dict(existing_map_data.nav_file_cache)
        for rec in map_data.positions:
            all_x.append(rec.x)
            all_y.append(rec.y)
        for seg in map_data.segments:
            all_x.extend(seg.xs)
            all_y.extend(seg.ys)

    preplot_stats: dict[str, int] = {}
    if settings.show_preplots and preplot_files:
        if progress_callback:
            progress_callback(int(100 * step / total_steps), "Parsing preplot/navplan…")
        segments, _meta, preplot_stats = parse_preplot_files(preplot_files)
        map_data.preplot_segments = segments
        for seg in segments:
            all_x.extend(seg.xs)
            all_y.extend(seg.ys)
        step += len(preplot_files)
    elif existing_map_data and not preplot_files:
        map_data.preplot_segments = list(existing_map_data.preplot_segments)
        for seg in map_data.preplot_segments:
            all_x.extend(seg.xs)
            all_y.extend(seg.ys)

    xs_arr = np.array(all_x, dtype=np.float64)
    ys_arr = np.array(all_y, dtype=np.float64)
    map_data.bounds = _merge_bounds(SurveyBounds(), xs_arr, ys_arr)
    map_data.geo_bounds = _compute_geo_bounds(all_records)
    map_data.postmap_info = _merge_postmap_info(
        existing_postmap,
        main_files,
        preplot_files,
        settings,
    )
    map_data.stats = {
        "total_records": len(all_records),
        "total_segments": len(map_data.segments),
        "total_sequences": len(map_data.sequences),
        "source_files": len(main_files),
        "nav_files_parsed": len(files_to_parse),
        "nav_files_skipped": skipped_files,
        "preplot_files": preplot_stats.get("preplot_files", 0),
        "preplot_lines": preplot_stats.get("preplot_lines", 0),
        "navplan_files": preplot_stats.get("navplan_files", 0),
    }
    if progress_callback:
        progress_callback(100, "Parse complete")
    return map_data
