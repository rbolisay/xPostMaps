"""Directory scanner and batch parser for P111/P190 navigation files."""

from __future__ import annotations

import os
import ctypes
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from xpostmaps.core.models import (
    GeoBounds,
    LineSegment,
    MapData,
    PositionRecord,
    PostmapInfo,
    ProjectSettings,
    RecordType,
    SurveyBounds,
    SurveyPerimeter,
)
from xpostmaps.core.sequence_utils import (
    nav_file_cache_key,
    nav_file_signature,
    navplan_file_signature,
    preplot_file_signature,
)
from xpostmaps.core.navplan_catalog_utils import resolve_navplan_files
from xpostmaps.parsers.metadata_parser import collect_postmap_metadata
from xpostmaps.parsers.p111_parser import parse_p111_file, scan_vessel_id
from xpostmaps.parsers.p190_parser import parse_p190_file
from xpostmaps.parsers.preplot_parser import (
    parse_navplan_source_file,
    parse_preplot_file,
    resolve_preplot_files,
)
from xpostmaps.parsers.sequence_builder import build_display_sequences, records_to_segments
from xpostmaps.parsers.survey_perimeter_parser import parse_survey_perimeters
from xpostmaps.utils.numba_accel import compute_bounds

NAV_EXTENSIONS = {".p111", ".p190", ".P111", ".P190", ".txt", ".nav"}
_MAX_NAV_PARSE_WORKERS = 8
_DRIVE_REMOTE = 4


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
    if settings.nav_files_explicit or settings.nav_files:
        files = [Path(f) for f in settings.nav_files if Path(f).is_file()]
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


def _nav_parse_worker(args: tuple[int, Path, str | None]) -> tuple[int, Path, list[PositionRecord]]:
    index, path, vessel_id = args
    return index, path, _parse_nav_file(path, vessel_id=vessel_id)


def _is_remote_path(path: Path) -> bool:
    text = str(path)
    if text.startswith("\\\\"):
        return True
    if os.name != "nt":
        return False
    try:
        root = path.drive + "\\"
        if not path.drive:
            return False
        return ctypes.windll.kernel32.GetDriveTypeW(root) == _DRIVE_REMOTE
    except Exception:  # noqa: BLE001
        return False


def _nav_parse_worker_count(file_count: int, files: list[Path] | None = None) -> int:
    if file_count <= 1:
        return 1
    if files and any(_is_remote_path(path) for path in files):
        # Network/SMB reads are latency-bound, not CPU-bound: each worker spends
        # most of its time awaiting round-trips, so running several in parallel
        # hides that latency and scales near-linearly (measured ~2.3x for 5
        # large P111s). Decouple from cpu_count and cap concurrent streams so we
        # do not saturate the share on huge batches.
        return max(1, min(file_count, _MAX_NAV_PARSE_WORKERS))
    cpu_count = os.cpu_count() or 2
    return max(1, min(file_count, cpu_count, _MAX_NAV_PARSE_WORKERS))


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
        collect_postmap_metadata(nav_paths[:1], settings, preplot_info)
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


def _segments_for_file(segments: list[LineSegment], path: Path) -> list[LineSegment]:
    name = path.name
    ref = str(path)
    return [
        segment
        for segment in segments
        if segment.file_name == name or segment.file_name == ref
    ]


def _perimeters_for_file(
    perimeters: list[SurveyPerimeter],
    path: Path,
) -> list[SurveyPerimeter]:
    name = path.name
    ref = str(path)
    return [
        perimeter
        for perimeter in perimeters
        if perimeter.file_name == name or perimeter.file_name == ref
    ]


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
    navplan_files = resolve_navplan_files(settings)
    total_steps = max(len(main_files) + len(preplot_files) + len(navplan_files), 1)
    step = 0
    shared_vessel_id = _scan_shared_vessel_id(main_files)

    nav_cache: dict[str, tuple[float, int, str]] = dict(
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

    for path in navplan_files:
        map_data.source_files.append(str(path))

    for path in main_files:
        map_data.source_files.append(str(path))

    parsed_results: dict[int, tuple[Path, list[PositionRecord]]] = {}
    if files_to_parse:
        worker_count = _nav_parse_worker_count(len(files_to_parse), files_to_parse)
        if progress_callback:
            mode = "multi-threaded" if worker_count > 1 else "single-threaded"
            progress_callback(
                int(100 * step / total_steps),
                f"Parsing {len(files_to_parse)} nav file(s) ({mode}, {worker_count} worker(s))",
            )

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(_nav_parse_worker, (index, path, shared_vessel_id))
                for index, path in enumerate(files_to_parse)
            ]
            for future in as_completed(futures):
                index, path, records = future.result()
                parsed_results[index] = (path, records)
                if progress_callback:
                    progress_callback(
                        int(100 * step / total_steps),
                        f"Parsed {path.name}",
                    )
                step += 1

    for index in range(len(files_to_parse)):
        path, records = parsed_results[index]
        all_records.extend(records)
        for rec in records:
            all_x.append(rec.x)
            all_y.append(rec.y)
        nav_cache[nav_file_cache_key(path)] = nav_file_signature(path)

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

    if not main_files:
        if settings.nav_files_explicit:
            map_data.positions = []
            map_data.sequences = []
            map_data.segments = []
            map_data.nav_file_cache = {}
        elif existing_map_data:
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
    skipped_preplot = 0
    parsed_preplot = 0
    if settings.show_preplots and preplot_files:
        preplot_cache: dict[str, tuple[float, int, str]] = dict(
            existing_map_data.preplot_file_cache if existing_map_data else {}
        )
        active_preplot_keys = {nav_file_cache_key(path) for path in preplot_files}
        preplot_cache = {
            key: value for key, value in preplot_cache.items() if key in active_preplot_keys
        }
        preplot_segments: list[LineSegment] = []
        survey_perimeters: list[SurveyPerimeter] = []
        for path in preplot_files:
            cache_key = nav_file_cache_key(path)
            signature = preplot_file_signature(path)
            if existing_map_data and preplot_cache.get(cache_key) == signature:
                preplot_segments.extend(
                    _segments_for_file(existing_map_data.preplot_segments, path)
                )
                survey_perimeters.extend(
                    _perimeters_for_file(existing_map_data.survey_perimeters, path)
                )
                skipped_preplot += 1
                if progress_callback:
                    progress_callback(
                        int(100 * step / total_steps),
                        f"Skipping preplot {path.name} (unchanged)",
                    )
                step += 1
                continue
            if progress_callback:
                progress_callback(
                    int(100 * step / total_steps),
                    f"Parsing preplot {path.name}",
                )
            result = parse_preplot_file(path)
            preplot_segments.extend(result.segments)
            survey_perimeters.extend(parse_survey_perimeters([path]))
            preplot_cache[cache_key] = signature
            parsed_preplot += 1
            preplot_stats["preplot_files"] = preplot_stats.get("preplot_files", 0) + 1
            preplot_stats["preplot_lines"] = preplot_stats.get("preplot_lines", 0) + len(
                result.segments
            )
            preplot_stats["total_points"] = preplot_stats.get("total_points", 0) + len(
                result.records
            )
            step += 1
        map_data.preplot_segments = preplot_segments
        map_data.survey_perimeters = survey_perimeters
        map_data.preplot_file_order = [str(path) for path in preplot_files]
        map_data.preplot_file_cache = preplot_cache
        for seg in preplot_segments:
            all_x.extend(seg.xs)
            all_y.extend(seg.ys)
        for perimeter in survey_perimeters:
            all_x.extend(perimeter.xs)
            all_y.extend(perimeter.ys)
    elif existing_map_data and not settings.preplot_files_explicit:
        map_data.preplot_segments = list(existing_map_data.preplot_segments)
        map_data.survey_perimeters = list(existing_map_data.survey_perimeters)
        map_data.preplot_file_order = list(existing_map_data.preplot_file_order)
        map_data.preplot_file_cache = dict(existing_map_data.preplot_file_cache)
        if not map_data.preplot_file_order and map_data.preplot_segments:
            seen: list[str] = []
            for segment in map_data.preplot_segments:
                if segment.file_name and segment.file_name not in seen:
                    seen.append(segment.file_name)
            map_data.preplot_file_order = seen
        for seg in map_data.preplot_segments:
            all_x.extend(seg.xs)
            all_y.extend(seg.ys)
        for perimeter in map_data.survey_perimeters:
            all_x.extend(perimeter.xs)
            all_y.extend(perimeter.ys)
    else:
        map_data.preplot_segments = []
        map_data.survey_perimeters = []
        map_data.preplot_file_order = []
        map_data.preplot_file_cache = {}

    navplan_stats: dict[str, int] = {}
    skipped_navplan = 0
    parsed_navplan = 0
    if settings.show_preplots and navplan_files:
        navplan_cache: dict[str, tuple[float, int, str]] = dict(
            existing_map_data.navplan_file_cache if existing_map_data else {}
        )
        active_navplan_keys = {nav_file_cache_key(path) for path in navplan_files}
        navplan_cache = {
            key: value for key, value in navplan_cache.items() if key in active_navplan_keys
        }
        navplan_segments: list[LineSegment] = []
        for path in navplan_files:
            cache_key = nav_file_cache_key(path)
            signature = navplan_file_signature(path)
            if existing_map_data and navplan_cache.get(cache_key) == signature:
                navplan_segments.extend(
                    _segments_for_file(existing_map_data.navplan_segments, path)
                )
                skipped_navplan += 1
                if progress_callback:
                    progress_callback(
                        int(100 * step / total_steps),
                        f"Skipping navplan {path.name} (unchanged)",
                    )
                step += 1
                continue
            if progress_callback:
                progress_callback(
                    int(100 * step / total_steps),
                    f"Parsing navplan {path.name}",
                )
            result = parse_navplan_source_file(path)
            navplan_segments.extend(result.segments)
            navplan_cache[cache_key] = signature
            parsed_navplan += 1
            navplan_stats["navplan_files"] = navplan_stats.get("navplan_files", 0) + 1
            navplan_stats["navplan_lines"] = navplan_stats.get("navplan_lines", 0) + len(
                result.segments
            )
            navplan_stats["navplan_points"] = navplan_stats.get("navplan_points", 0) + len(
                result.records
            )
            step += 1
        map_data.navplan_segments = navplan_segments
        map_data.navplan_file_order = [str(path) for path in navplan_files]
        map_data.navplan_file_cache = navplan_cache
        for seg in navplan_segments:
            all_x.extend(seg.xs)
            all_y.extend(seg.ys)
    elif existing_map_data and not settings.navplan_files_explicit:
        map_data.navplan_segments = list(existing_map_data.navplan_segments)
        map_data.navplan_file_order = list(existing_map_data.navplan_file_order)
        map_data.navplan_file_cache = dict(existing_map_data.navplan_file_cache)
        if not map_data.navplan_file_order and map_data.navplan_segments:
            seen: list[str] = []
            for segment in map_data.navplan_segments:
                if segment.file_name and segment.file_name not in seen:
                    seen.append(segment.file_name)
            map_data.navplan_file_order = seen
        for seg in map_data.navplan_segments:
            all_x.extend(seg.xs)
            all_y.extend(seg.ys)
    else:
        map_data.navplan_segments = []
        map_data.navplan_file_order = []
        map_data.navplan_file_cache = {}

    xs_arr = np.array(all_x, dtype=np.float64)
    ys_arr = np.array(all_y, dtype=np.float64)
    map_data.bounds = _merge_bounds(SurveyBounds(), xs_arr, ys_arr)
    map_data.geo_bounds = _compute_geo_bounds(all_records)
    map_data.postmap_info = _merge_postmap_info(
        existing_postmap,
        main_files,
        preplot_files + navplan_files,
        settings,
    )
    map_data.stats = {
        "total_records": len(all_records),
        "total_segments": len(map_data.segments),
        "total_sequences": len(map_data.sequences),
        "source_files": len(main_files),
        "nav_files_parsed": len(files_to_parse),
        "nav_files_skipped": skipped_files,
        "nav_files_active_names": [path.name for path in main_files],
        "nav_files_parsed_names": [path.name for path in files_to_parse],
        "preplot_files": preplot_stats.get("preplot_files", parsed_preplot + skipped_preplot),
        "preplot_files_parsed": parsed_preplot,
        "preplot_files_skipped": skipped_preplot,
        "preplot_lines": preplot_stats.get("preplot_lines", 0),
        "navplan_files": navplan_stats.get("navplan_files", parsed_navplan + skipped_navplan),
        "navplan_files_parsed": parsed_navplan,
        "navplan_files_skipped": skipped_navplan,
        "navplan_lines": navplan_stats.get("navplan_lines", 0),
        "navplan_points": navplan_stats.get("navplan_points", 0),
        "survey_perimeters": len(map_data.survey_perimeters),
    }
    if progress_callback:
        progress_callback(100, "Parse complete")
    return map_data
