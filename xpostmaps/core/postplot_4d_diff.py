"""Postplot 4D diff-stat calculations and persistence helpers."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, replace
from collections import defaultdict
from pathlib import Path

from xpostmaps.core.models import (
    LineSegment,
    MapData,
    PositionRecord,
    ProjectSettings,
    RecordType,
    make_sequence_group_id,
    sequence_group_id,
)
from xpostmaps.core.postplot_4d_matching import (
    BaselineKind,
    Postplot4DMatchRow,
    _text_forms,
)
from xpostmaps.parsers.metadata_parser import parse_file_metadata
from xpostmaps.parsers.p190_parser import parse_p190_header
from xpostmaps.parsers.p111_parser import (
    ReceiverFeatherRecord,
    average_receiver_feathers_by_shotpoint,
    parse_p111_receiver_feathers,
    parse_p190_receiver_feathers,
)
from xpostmaps.parsers.preplot_parser import parse_navplan_source_file, parse_preplot_file
from xpostmaps.core.crs_utils import (
    geographic_epsg_from_map,
    normalize_epsg,
    pyproj_available,
    transform_coordinates,
)

_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")
_AZIMUTH_RE = _NUMBER_RE
_SHOTPOINT_INTERVAL_RE = re.compile(
    r"(?:(?:SHOT\s*POINT|SHOTPOINT|SHOT)\s*(?:INTERVAL|INT|SPACING)|SP\s*(?:INTERVAL|INT))"
    r"[^0-9+\-]*(?P<value>[-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_NUMBER_OF_SOURCES_RE = re.compile(
    r"NUMBER\s+OF\s+SOURCES[^0-9+\-]*(?P<value>\d+)",
    re.IGNORECASE,
)
_SOURCE_SEPARATION_RE = re.compile(
    r"SOURCE\s+SEPARATION[^0-9+\-]*(?P<value>[-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_P190_SOURCE_OFFSET_RE = re.compile(
    r"OFFSET\s+REF\.?\s+TO\s+SOURCE\s*(?P<source>[A-Za-z0-9_-]+)?(?P<rest>.*)",
    re.IGNORECASE,
)
_P111_GUN_ARRAY_RE = re.compile(r"\bGUN\s+ARRAY\s+(?P<source>[A-Za-z0-9_-]+)\b", re.IGNORECASE)
_PREPLOT_DIRECTION_RE = re.compile(
    r"(?:LINE[-\s_]*DIRECTION|LINE\s*HEADING|HEADING|AZIMUTH|BEARING|ROTATION)",
    re.IGNORECASE,
)
_SOURCE_PATH_INDEX_CACHE: dict[tuple, dict[str, Path]] = {}
# Network shares make path.stat()/resolve()/is_file() cost ~1s each, so we
# memoise per-process for the duration of a recalc. Caches are reset at the
# start of each recalc batch (see reset_postplot_4d_path_caches) so a fresh
# import is always picked up.
_FILE_FINGERPRINT_CACHE: dict[str, tuple[str, float, int]] = {}
_RESOLVED_SOURCE_PATH_CACHE: dict[tuple, Path | None] = {}


def _settings_source_key(settings: ProjectSettings | None) -> tuple:
    if settings is None:
        return ((), "")
    return (
        tuple(str(path) for path in settings.nav_files),
        getattr(settings, "p111_p190_dir", "") or "",
    )


def reset_postplot_4d_path_caches() -> None:
    """Drop memoised path/fingerprint caches (call before a recalc batch)."""
    _FILE_FINGERPRINT_CACHE.clear()
    _RESOLVED_SOURCE_PATH_CACHE.clear()
    _SOURCE_PATH_INDEX_CACHE.clear()


class CrsMismatchError(RuntimeError):
    """Raised when a Diff Stat cannot be computed in a single, verified CRS.

    A Diff Stat is only meaningful when the baseline (navplan/preplot) and the
    firing-source (P111/P190) coordinates are differenced inside ONE projected
    CRS (datum + grid). If a CRS is unknown, or two files disagree and cannot be
    reprojected, we refuse rather than emit silently-wrong metres.
    """


@dataclass(frozen=True)
class DiffCrsAssessment:
    """Outcome of validating CRS consistency before a Diff Stat is computed."""

    ok: bool
    reason: str
    map_epsg: str
    baseline_epsg: str
    source_epsgs: tuple[str, ...]


@dataclass(frozen=True)
class BaselineShotpoint:
    shotpoint: int
    x: float
    y: float
    latitude: str = ""
    longitude: str = ""
    source_id: str = ""
    source_index: int = 0


BaselineKey = int | tuple[int, str]


@dataclass(frozen=True)
class PreplotHeaderInfo:
    shotpoint_interval_m: float | None = None
    line_direction: str = ""
    number_of_sources: int = 1
    source_separation_m: float | None = None
    source_offsets_m: tuple[float, ...] = ()


@dataclass(frozen=True)
class Postplot4DDiffRow:
    shotpoint: int
    baseline_x: float
    baseline_y: float
    baseline_latitude: str
    baseline_longitude: str
    source_x: float
    source_y: float
    source_latitude: str
    source_longitude: str
    crossline_m: float
    inline_m: float
    radial_m: float
    navplan_feather_deg: float | None = None
    line_feather_deg: float | None = None
    vessel_id: str = ""
    firing_source_id: str = ""


def feather_diff_deg(
    *,
    line_feather_deg: float | None,
    navplan_feather_deg: float | None,
) -> float | None:
    """Difference between line and navplan feather (line minus navplan, degrees)."""
    if line_feather_deg is None or navplan_feather_deg is None:
        return None
    return line_feather_deg - navplan_feather_deg


def _parse_azimuth_degrees(line_direction: str) -> float | None:
    text = (line_direction or "").strip().replace("°", "")
    if not text:
        return None
    match = _AZIMUTH_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0)) % 360.0
    except ValueError:
        return None


def _parse_hc_parameter_value(text: str) -> float | None:
    fields = [field.strip() for field in (text or "").split(",")]
    if len(fields) <= 7 or fields[0] != "HC":
        return None
    try:
        return float(fields[7])
    except ValueError:
        return None


def parse_shotpoint_interval_m(text: str) -> float | None:
    """Parse P111/P190 shotpoint interval headers such as CC/H2600 variants."""
    normalized = (text or "").replace(",", " ").replace("_", " ")
    if "shot point interval" in normalized.lower():
        hc_value = _parse_hc_parameter_value(text)
        if hc_value is not None:
            return hc_value if hc_value > 0 else None
    match = _SHOTPOINT_INTERVAL_RE.search(normalized)
    if not match:
        return None
    try:
        value = float(match.group("value"))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_number_of_sources(text: str) -> int | None:
    match = _NUMBER_OF_SOURCES_RE.search((text or "").replace(",", " "))
    if not match:
        return None
    try:
        value = int(match.group("value"))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_source_separation_m(text: str) -> float | None:
    match = _SOURCE_SEPARATION_RE.search((text or "").replace(",", " "))
    if not match:
        return None
    try:
        value = float(match.group("value"))
    except ValueError:
        return None
    return value if value >= 0 else None


def _source_offsets_tuple(offsets_by_index: dict[int, float]) -> tuple[float, ...]:
    if not offsets_by_index:
        return ()
    max_index = max(offsets_by_index)
    if max_index <= 0:
        return ()
    if any(index not in offsets_by_index for index in range(1, max_index + 1)):
        return ()
    return tuple(offsets_by_index[index] for index in range(1, max_index + 1))


def parse_p190_source_offset_m(text: str) -> tuple[int, float] | None:
    """Parse P190 ``H0900 OFFSET REF. TO SOURCE`` crossline offset rows."""
    match = _P190_SOURCE_OFFSET_RE.search(text or "")
    if not match:
        return None
    source_index = _source_index_from_id(match.group("source") or "")
    if source_index is None:
        return None
    values = [float(value) for value in _NUMBER_RE.findall(match.group("rest"))]
    # The final two numeric values are crossline/inline offsets; e.g.
    # ``... SOURCE 1  1  1  37.5  0`` -> crossline +37.5 m.
    if len(values) < 2:
        return None
    return source_index, values[-2]


def parse_p111_gun_array_offset_m(text: str) -> tuple[int, float] | None:
    """Parse P111 ``HC,2,3,0,Gun Array`` crossline offset rows."""
    if not (text or "").lstrip().upper().startswith("HC,2,3,0,"):
        return None
    fields = [field.strip() for field in text.split(",")]
    object_type = fields[8].lower().replace("-", " ") if len(fields) > 8 else ""
    if len(fields) < 9 or "air gun array" not in object_type:
        return None
    label_match = _P111_GUN_ARRAY_RE.search(fields[4])
    if label_match:
        source_index = _source_index_from_id(label_match.group("source"))
    else:
        source_index = None
    source_index = source_index or _source_index_from_id(fields[6])
    numeric_values: list[float] = []
    for field in fields[9:]:
        try:
            numeric_values.append(float(field))
        except ValueError:
            # The numeric block is contiguous; labels such as ``COS`` or
            # ``Centre of Source`` mark the end of the coordinate offsets.
            if numeric_values:
                break
            continue
    # After the object type, P111 gun arrays list scale then crossline/inline
    # offsets: ``...,100,37.5,0,0,...``.
    if source_index is None or source_index <= 0 or len(numeric_values) < 2:
        return None
    return source_index, numeric_values[1]


def _read_preplot_generation_info(path: Path) -> PreplotHeaderInfo:
    interval: float | None = None
    line_direction = ""
    number_of_sources = 1
    source_separation_m: float | None = None
    source_offsets_by_index: dict[int, float] = {}
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return PreplotHeaderInfo()
    with handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(("S", "V", "N1", "P1", "R1", "E1")):
                break
            if interval is None:
                interval = parse_shotpoint_interval_m(line)
            parsed_sources = parse_number_of_sources(line)
            if parsed_sources is not None:
                number_of_sources = parsed_sources
            if source_separation_m is None:
                source_separation_m = parse_source_separation_m(line)
            source_offset = parse_p190_source_offset_m(line) or parse_p111_gun_array_offset_m(line)
            if source_offset is not None:
                source_index, offset_m = source_offset
                source_offsets_by_index[source_index] = offset_m
                number_of_sources = max(number_of_sources, source_index)
            direction_match = _PREPLOT_DIRECTION_RE.search(line)
            if not line_direction and direction_match:
                parsed = _parse_hc_parameter_value(line)
                if parsed is None:
                    parsed = _parse_azimuth_degrees(line[direction_match.end() :])
                if parsed is not None:
                    line_direction = f"{parsed:.2f}°"
    source_offsets_m = _source_offsets_tuple(source_offsets_by_index)
    return PreplotHeaderInfo(
        shotpoint_interval_m=interval,
        line_direction=line_direction,
        number_of_sources=number_of_sources,
        source_separation_m=source_separation_m,
        source_offsets_m=source_offsets_m,
    )


def _read_preplot_header_info(path: Path) -> tuple[float | None, str]:
    info = _read_preplot_generation_info(path)
    return info.shotpoint_interval_m, info.line_direction


def _azimuth_from_geometry(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    x0, y0 = points[0]
    x1, y1 = points[-1]
    de = x1 - x0
    dn = y1 - y0
    if abs(de) < 1e-9 and abs(dn) < 1e-9:
        return None
    return math.degrees(math.atan2(de, dn)) % 360.0


def _line_names_match(baseline_name: str, line_name: str) -> bool:
    left = _text_forms(baseline_name)
    right = _text_forms(line_name)
    return bool(left and right and left.intersection(right))


def _resolve_baseline_path(
    settings: ProjectSettings | None,
    baseline_kind: BaselineKind,
    baseline_file_name: str,
) -> Path | None:
    if not baseline_file_name:
        return None
    target_name = Path(baseline_file_name).name
    if baseline_kind == "navplan" and settings:
        for entry in settings.navplan_catalog:
            if Path(entry.file_path).name == target_name:
                path = Path(entry.file_path)
                if path.is_file():
                    return path
    if baseline_kind == "preplot" and settings:
        for entry in settings.preplot_catalog:
            if Path(entry.file_path).name == target_name:
                path = Path(entry.file_path)
                if path.is_file():
                    return path
        for raw in settings.preplot_files:
            path = Path(raw)
            if path.name == target_name and path.is_file():
                return path
    if baseline_kind == "navplan" and settings:
        for raw in settings.navplan_files:
            path = Path(raw)
            if path.name == target_name and path.is_file():
                return path
    return None


def _baseline_catalog_epsg(
    settings: ProjectSettings | None,
    baseline_kind: BaselineKind,
    baseline_file_name: str,
) -> str:
    if settings is None or not baseline_file_name:
        return ""
    target_name = Path(baseline_file_name).name
    if baseline_kind == "preplot":
        for entry in settings.preplot_catalog:
            if Path(entry.file_path).name == target_name:
                return normalize_epsg(entry.crs_code)
    if baseline_kind == "navplan":
        for entry in settings.navplan_catalog:
            if Path(entry.file_path).name == target_name:
                return normalize_epsg(entry.crs_code)
    return ""


def _baseline_file_epsg(
    settings: ProjectSettings | None,
    baseline_kind: BaselineKind,
    baseline_file_name: str,
    path: Path | None,
    *,
    database=None,
    project_name: str = "",
) -> str:
    return _baseline_catalog_epsg(settings, baseline_kind, baseline_file_name) or _file_epsg(
        path,
        database=database,
        project_name=project_name,
    )


def _baseline_from_records(
    records: list[PositionRecord],
    baseline_name: str,
    record_type: RecordType,
) -> dict[int, BaselineShotpoint]:
    result: dict[int, BaselineShotpoint] = {}
    for record in records:
        if record.record_type != record_type:
            continue
        if not _line_names_match(baseline_name, record.line_name):
            continue
        if record.point_num <= 0:
            continue
        result[record.point_num] = BaselineShotpoint(
            shotpoint=record.point_num,
            x=record.x,
            y=record.y,
            latitude=record.latitude,
            longitude=record.longitude,
        )
    return result


def _baseline_from_segment(segment: LineSegment, baseline_name: str) -> dict[int, BaselineShotpoint]:
    if not _line_names_match(baseline_name, segment.line_name):
        return {}
    if len(segment.xs) < 1:
        return {}
    try:
        first_sp = int(float(segment.sequence_no)) if segment.sequence_no else 0
    except (TypeError, ValueError):
        first_sp = 0

    result: dict[int, BaselineShotpoint] = {}
    for index, (x, y) in enumerate(zip(segment.xs, segment.ys)):
        sp = first_sp + index if first_sp else index + 1
        result[int(sp)] = BaselineShotpoint(shotpoint=int(sp), x=float(x), y=float(y))
    return result


def _source_index_from_id(source_id: str) -> int | None:
    match = re.search(r"\d+", source_id or "")
    if not match:
        return None
    try:
        value = int(match.group(0))
    except ValueError:
        return None
    return value if value > 0 else None


def _source_key(source_id: str) -> str:
    index = _source_index_from_id(source_id)
    if index is not None:
        return str(index)
    return (source_id or "").strip().upper()


def _source_id_for_index(source_index: int) -> str:
    return f"G{source_index:02d}"


def _baseline_key(point: BaselineShotpoint) -> BaselineKey:
    if point.source_id or point.source_index:
        return (point.shotpoint, _source_key(point.source_id or str(point.source_index)))
    return point.shotpoint


def _source_key_index(key: BaselineKey) -> int | None:
    if not isinstance(key, tuple) or len(key) != 2:
        return None
    return _source_index_from_id(str(key[1]))


def _baseline_source_count(baseline: dict[BaselineKey, BaselineShotpoint]) -> int:
    indices = [
        index
        for key in baseline
        if (index := _source_key_index(key)) is not None
    ]
    return max(indices, default=0)


def _source_lookup_reversed(
    baseline: dict[BaselineKey, BaselineShotpoint],
    azimuth_deg: float,
) -> bool:
    """Return True when cached preplot source sides oppose the firing direction."""
    source_count = _baseline_source_count(baseline)
    if source_count <= 1:
        return False

    grouped: dict[int, list[tuple[int, BaselineShotpoint]]] = defaultdict(list)
    for key, point in baseline.items():
        index = _source_key_index(key)
        if index is not None:
            grouped[point.shotpoint].append((index, point))

    for points in grouped.values():
        if len(points) < source_count:
            continue
        by_index = {index: point for index, point in points}
        first = by_index.get(1)
        if first is None:
            continue
        center_x = sum(point.x for point in by_index.values()) / len(by_index)
        center_y = sum(point.y for point in by_index.values()) / len(by_index)
        _inline, crossline, _radial = _offset_components(
            first.x - center_x,
            first.y - center_y,
            azimuth_deg,
        )
        if abs(crossline) > 1e-6:
            return crossline < 0.0
    return False


def _remap_source_key_for_direction(
    source_key: str,
    source_count: int,
    reverse_sources: bool,
) -> str:
    if not reverse_sources or source_count <= 1:
        return source_key
    source_index = _source_index_from_id(source_key)
    if source_index is None or source_index < 1 or source_index > source_count:
        return source_key
    return str(source_count + 1 - source_index)


def _source_crossline_offset_m(source_index: int, source_count: int, separation_m: float) -> float:
    center_index = (source_count + 1) / 2.0
    return (center_index - source_index) * separation_m


def _source_offsets_match_spacing(
    source_offsets_m: tuple[float, ...],
    source_separation_m: float | None,
) -> bool:
    if not source_offsets_m:
        return True
    if source_separation_m is None:
        return False
    return all(
        abs(offset - _source_crossline_offset_m(index, len(source_offsets_m), source_separation_m))
        < 1e-6
        for index, offset in enumerate(source_offsets_m, start=1)
    )


def _apply_crossline_offset(
    x: float,
    y: float,
    offset_m: float,
    azimuth_deg: float,
) -> tuple[float, float]:
    theta = math.radians(azimuth_deg)
    return x + offset_m * math.cos(theta), y - offset_m * math.sin(theta)


def load_baseline_shotpoints(
    map_data: MapData | None,
    settings: ProjectSettings | None,
    baseline_kind: BaselineKind,
    baseline_name: str,
    baseline_file_name: str,
    *,
    database=None,
    project_name: str = "",
    map_epsg: str = "",
) -> dict[BaselineKey, BaselineShotpoint]:
    if map_data is None:
        return {}

    path = _resolve_baseline_path(settings, baseline_kind, baseline_file_name)
    record_type = RecordType.NAVPLAN if baseline_kind == "navplan" else RecordType.PREPLOT
    segments = (
        map_data.navplan_segments if baseline_kind == "navplan" else map_data.preplot_segments
    )
    target_name = Path(baseline_file_name).name if baseline_file_name else ""
    # Navplan baselines must be keyed by their real shotpoint numbers so they
    # align with the firing-source point numbers during differencing. Parsing
    # the navplan file gives authoritative point numbers; the segment fallback
    # below only yields a synthetic 1..N index when segment.sequence_no is
    # empty, which never intersects the source shotpoints (=> zero diff rows).
    if path is not None:
        try:
            if baseline_kind == "navplan":
                parsed = parse_navplan_source_file(path)
            else:
                parsed = parse_preplot_file(path)
                generated = _generated_preplot_baseline_from_records(
                    parsed.records,
                    baseline_name,
                    path,
                    database=database,
                    project_name=project_name,
                    map_epsg=map_epsg,
                )
                if generated:
                    return generated
            by_records = _baseline_from_records(parsed.records, baseline_name, record_type)
            if by_records:
                return by_records
        except OSError:
            pass

    merged: dict[BaselineKey, BaselineShotpoint] = {}
    for segment in segments:
        if target_name and segment.file_name and Path(segment.file_name).name != target_name:
            continue
        if baseline_kind == "preplot":
            generated = _generated_preplot_baseline_from_segment(
                segment,
                baseline_name,
                path,
                database=database,
                project_name=project_name,
                map_epsg=map_epsg,
            )
            if generated:
                merged.update(generated)
                continue
        merged.update(_baseline_from_segment(segment, baseline_name))
    return merged


def source_shotpoints_for_match(
    positions: list[PositionRecord],
    match_row: Postplot4DMatchRow,
) -> dict[int, PositionRecord]:
    if not match_row.sequence_id:
        return {}
    target_group = sequence_group_id(match_row.sequence_id)
    result: dict[int, PositionRecord] = {}
    for record in positions:
        if record.record_type != RecordType.SOURCE:
            continue
        group = make_sequence_group_id(record.file_name, record.sequence_no, record.line_name)
        if group != target_group:
            continue
        if match_row.subline and record.subline and record.subline != match_row.subline:
            continue
        if record.point_num <= 0:
            continue
        result[record.point_num] = record
    return result


def vessel_shotpoints_for_match(
    positions: list[PositionRecord],
    match_row: Postplot4DMatchRow,
) -> dict[int, str]:
    if not match_row.sequence_id:
        return {}
    target_group = sequence_group_id(match_row.sequence_id)
    result: dict[int, str] = {}
    for record in positions:
        if record.record_type != RecordType.VESSEL:
            continue
        group = make_sequence_group_id(record.file_name, record.sequence_no, record.line_name)
        if group != target_group:
            continue
        if match_row.subline and record.subline and record.subline != match_row.subline:
            continue
        if record.point_num <= 0 or not record.vessel_id:
            continue
        # Per-shotpoint vessel ID: later records override (same SP should agree).
        result[record.point_num] = record.vessel_id
    return result


def enrich_diff_rows_from_positions(
    rows: list[Postplot4DDiffRow],
    positions: list[PositionRecord],
    match_row: Postplot4DMatchRow,
) -> list[Postplot4DDiffRow]:
    """Fill missing vessel / firing-source IDs on saved diff rows from nav positions."""
    if not rows or not positions:
        return rows
    sources = source_shotpoints_for_match(positions, match_row)
    vessels = vessel_shotpoints_for_match(positions, match_row)
    enriched: list[Postplot4DDiffRow] = []
    changed = False
    for row in rows:
        vessel_id = row.vessel_id
        firing_source_id = row.firing_source_id
        source = sources.get(row.shotpoint)
        if source:
            if not firing_source_id:
                firing_source_id = source.source_id
            if not vessel_id:
                vessel_id = source.vessel_id or vessels.get(row.shotpoint, "")
        elif not vessel_id:
            vessel_id = vessels.get(row.shotpoint, "")
        if vessel_id != row.vessel_id or firing_source_id != row.firing_source_id:
            changed = True
            enriched.append(
                replace(
                    row,
                    vessel_id=vessel_id,
                    firing_source_id=firing_source_id,
                )
            )
        else:
            enriched.append(row)
    return enriched if changed else rows


def _load_baseline_line_direction(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        info = parse_p190_header(path)
    except OSError:
        return ""
    return info.get("line direction") or info.get("linedirection") or ""


def resolve_diff_map_epsg(
    map_data: MapData | None,
    settings: ProjectSettings | None,
) -> str:
    """Return the projected CRS used for map/preplot/nav/postplot diff math."""
    if map_data and map_data.postmap_info.epsg_code:
        code = normalize_epsg(map_data.postmap_info.epsg_code)
        if code:
            return code
    if settings:
        for entry in settings.preplot_catalog:
            if entry.crs_code:
                code = normalize_epsg(entry.crs_code)
                if code:
                    return code
        for entry in settings.navplan_catalog:
            if entry.crs_code:
                code = normalize_epsg(entry.crs_code)
                if code:
                    return code
    return ""


def resolve_line_azimuth_degrees(
    line_direction: str,
    baseline: dict[BaselineKey, BaselineShotpoint],
    baseline_path: Path | None = None,
) -> float:
    for candidate in (line_direction, _load_baseline_line_direction(baseline_path)):
        azimuth = _parse_azimuth_degrees(candidate)
        if azimuth is not None:
            return azimuth
    baseline_geom = sorted(
        ((point.shotpoint, point.x, point.y) for point in baseline.values()),
        key=lambda item: item[0],
    )
    azimuth = _azimuth_from_geometry([(x, y) for _, x, y in baseline_geom])
    if azimuth is not None:
        return azimuth
    return 0.0


def _file_fingerprint(path: Path | None) -> tuple[str, float, int]:
    if path is None:
        return "", 0.0, 0
    cache_key = os.path.abspath(path)
    cached = _FILE_FINGERPRINT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        # A single stat() doubles as the existence check (is_file) and the
        # mtime/size read, halving network round-trips versus is_file()+stat().
        stat = path.stat()
        fingerprint = (str(path.resolve()), float(stat.st_mtime), int(stat.st_size))
    except OSError:
        fingerprint = ("", 0.0, 0)
    _FILE_FINGERPRINT_CACHE[cache_key] = fingerprint
    return fingerprint


def _populate_generated_lat_lon(
    generated: dict[BaselineKey, BaselineShotpoint],
    map_epsg: str,
) -> None:
    code = normalize_epsg(map_epsg)
    if not code:
        return
    ordered_items = list(generated.items())
    ordered = [point for _, point in ordered_items]
    try:
        geo_epsg = geographic_epsg_from_map(code)
        lons, lats = transform_coordinates(
            [point.x for point in ordered],
            [point.y for point in ordered],
            code,
            geo_epsg,
        )
    except Exception:  # noqa: BLE001
        return
    if len(lons) != len(ordered) or len(lats) != len(ordered):
        return
    for (key, point), lat, lon in zip(ordered_items, lats, lons):
        generated[key] = BaselineShotpoint(
            shotpoint=point.shotpoint,
            x=point.x,
            y=point.y,
            latitude=f"{float(lat):.8f}",
            longitude=f"{float(lon):.8f}",
            source_id=point.source_id,
            source_index=point.source_index,
        )


def _generate_preplot_shotpoints(
    controls: list[PositionRecord],
    map_epsg: str,
    source_count: int = 1,
    source_separation_m: float | None = None,
    line_azimuth_deg: float | None = None,
    source_offsets_m: tuple[float, ...] = (),
) -> dict[BaselineKey, BaselineShotpoint]:
    ordered = sorted(
        [record for record in controls if record.point_num > 0],
        key=lambda record: record.point_num,
    )
    generated: dict[BaselineKey, BaselineShotpoint] = {}
    if len(ordered) < 2:
        return generated
    source_offsets_m = tuple(float(offset) for offset in source_offsets_m)
    source_count = max(1, len(source_offsets_m) or int(source_count or 1))
    source_separation_m = float(source_separation_m or 0.0)
    for start, end in zip(ordered, ordered[1:]):
        sp0 = int(start.point_num)
        sp1 = int(end.point_num)
        if sp0 == sp1:
            continue
        step = 1 if sp1 > sp0 else -1
        span = sp1 - sp0
        segment_azimuth = _azimuth_from_geometry([(start.x, start.y), (end.x, end.y)])
        azimuth = segment_azimuth if segment_azimuth is not None else line_azimuth_deg
        if azimuth is None:
            azimuth = 0.0
        for shotpoint in range(sp0, sp1 + step, step):
            fraction = (shotpoint - sp0) / span
            center_x = start.x + (end.x - start.x) * fraction
            center_y = start.y + (end.y - start.y) * fraction
            if source_count <= 1:
                generated[shotpoint] = BaselineShotpoint(
                    shotpoint=shotpoint,
                    x=center_x,
                    y=center_y,
                    source_id="",
                    source_index=0,
                )
                continue
            for source_index in range(1, source_count + 1):
                if source_offsets_m:
                    offset = source_offsets_m[source_index - 1]
                else:
                    offset = _source_crossline_offset_m(
                        source_index,
                        source_count,
                        source_separation_m,
                    )
                x, y = _apply_crossline_offset(center_x, center_y, offset, azimuth)
                source_id = _source_id_for_index(source_index)
                point = BaselineShotpoint(
                    shotpoint=shotpoint,
                    x=x,
                    y=y,
                    source_id=source_id,
                    source_index=source_index,
                )
                generated[_baseline_key(point)] = point
    _populate_generated_lat_lon(generated, map_epsg)
    return generated


def _minimum_generated_preplot_count(
    controls: list[PositionRecord],
    source_count: int,
) -> int:
    ordered = sorted(
        [record for record in controls if record.point_num > 0],
        key=lambda record: record.point_num,
    )
    if len(ordered) < 2:
        return 0
    expected_shots: set[int] = set()
    for start, end in zip(ordered, ordered[1:]):
        sp0 = int(start.point_num)
        sp1 = int(end.point_num)
        if sp0 == sp1:
            continue
        step = 1 if sp1 > sp0 else -1
        expected_shots.update(range(sp0, sp1 + step, step))
    return len(expected_shots) * max(1, int(source_count or 1))


def _generated_preplot_baseline(
    controls: list[PositionRecord],
    path: Path,
    baseline_name: str,
    *,
    database=None,
    project_name: str = "",
    map_epsg: str = "",
) -> dict[BaselineKey, BaselineShotpoint]:
    file_path, file_mtime, file_size = _file_fingerprint(path)
    line_name = controls[0].line_name or baseline_name
    header_info = _read_preplot_generation_info(path)
    if database is not None and project_name.strip():
        # Existing cache rows only record source_count/source_separation, not
        # the explicit per-source offsets from H0900/HC Gun Array rows. Reuse
        # cache when the explicit offsets match the spacing formula; otherwise
        # regenerate so non-uniform future preplots are not silently wrong.
        if _source_offsets_match_spacing(
            header_info.source_offsets_m,
            header_info.source_separation_m,
        ):
            cached = database.load_postplot_4d_preplot_shotpoints(
                project_name.strip(),
                file_path,
                line_name,
                file_mtime,
                file_size,
            )
            if cached:
                expected_count = _minimum_generated_preplot_count(
                    controls,
                    header_info.number_of_sources,
                )
                if not expected_count or len(cached) >= expected_count:
                    return {_baseline_key(point): point for point in cached}

    if header_info.shotpoint_interval_m is None:
        return {}
    header_azimuth = _parse_azimuth_degrees(header_info.line_direction)
    generated = _generate_preplot_shotpoints(
        controls,
        map_epsg,
        source_count=header_info.number_of_sources,
        source_separation_m=header_info.source_separation_m,
        line_azimuth_deg=header_azimuth,
        source_offsets_m=header_info.source_offsets_m,
    )
    if not generated:
        return {}
    if database is not None and project_name.strip():
        database.save_postplot_4d_preplot_shotpoints(
            project_name.strip(),
            file_path,
            path.name,
            line_name,
            file_mtime,
            file_size,
            header_info.shotpoint_interval_m,
            header_info.line_direction,
            header_info.number_of_sources,
            header_info.source_separation_m or 0.0,
            sorted(
                generated.values(),
                key=lambda point: (point.shotpoint, point.source_index, point.source_id),
            ),
        )
    return generated


def _generated_preplot_baseline_from_records(
    records: list[PositionRecord],
    baseline_name: str,
    path: Path,
    *,
    database=None,
    project_name: str = "",
    map_epsg: str = "",
) -> dict[BaselineKey, BaselineShotpoint]:
    controls = [
        record
        for record in records
        if record.record_type == RecordType.PREPLOT
        and _line_names_match(baseline_name, record.line_name)
        and record.point_num > 0
    ]
    if len(controls) < 2:
        return {}
    return _generated_preplot_baseline(
        controls,
        path,
        baseline_name,
        database=database,
        project_name=project_name,
        map_epsg=map_epsg,
    )


def _generated_preplot_baseline_from_segment(
    segment: LineSegment,
    baseline_name: str,
    path: Path | None,
    *,
    database=None,
    project_name: str = "",
    map_epsg: str = "",
) -> dict[BaselineKey, BaselineShotpoint]:
    if path is None or not _line_names_match(baseline_name, segment.line_name):
        return {}
    sparse = _baseline_from_segment(segment, baseline_name)
    controls = [
        PositionRecord(
            file_name=segment.file_name,
            record_type=RecordType.PREPLOT,
            line_name=segment.line_name,
            vessel_id="",
            source_id="",
            point_num=point.shotpoint,
            x=point.x,
            y=point.y,
        )
        for point in sorted(sparse.values(), key=lambda item: item.shotpoint)
    ]
    if len(controls) < 2:
        return {}
    return _generated_preplot_baseline(
        controls,
        path,
        baseline_name,
        database=database,
        project_name=project_name,
        map_epsg=map_epsg,
    )


def _file_epsg(
    path: Path | None,
    *,
    database=None,
    project_name: str = "",
) -> str:
    """Resolve the EPSG (datum + projection) declared in a nav/preplot file."""
    if path is None:
        return ""
    # Network-free fast path: trust the project's imported cache by file name
    # so recalc never has to stat/resolve the (slow) source file.
    if database is not None and project_name.strip() and path.name:
        by_name = database.load_postplot_4d_file_cache_by_name(
            project_name.strip(),
            path.name,
        )
        if by_name and by_name.get("epsg_code"):
            return normalize_epsg(by_name.get("epsg_code", ""))
    if not path.is_file():
        return ""
    file_path, file_mtime, file_size = _file_fingerprint(path)
    if database is not None and project_name.strip() and file_path:
        cached = database.load_postplot_4d_file_cache(
            project_name.strip(),
            file_path,
            file_mtime,
            file_size,
        )
        if cached and cached.get("epsg_code"):
            return normalize_epsg(cached.get("epsg_code", ""))
    try:
        metadata = parse_file_metadata(path)
    except OSError:
        return ""
    epsg = normalize_epsg(metadata.get("epsg code", ""))
    if database is not None and project_name.strip() and file_path:
        database.save_postplot_4d_file_cache(
            project_name.strip(),
            file_path,
            path.name,
            file_mtime,
            file_size,
            epsg_code=epsg,
        )
    return epsg


def _source_path_index(settings: ProjectSettings | None) -> dict[str, Path]:
    if settings is None:
        return {}
    key = (
        tuple(str(path) for path in settings.nav_files),
        getattr(settings, "p111_p190_dir", "") or "",
    )
    cached = _SOURCE_PATH_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    indexed: dict[str, Path] = {}
    for raw in settings.nav_files:
        path = Path(raw)
        indexed.setdefault(path.name, path)
    folder = getattr(settings, "p111_p190_dir", "") or ""
    if folder:
        base = Path(folder)
        for name in list(indexed):
            indexed.setdefault(name, base / name)
    _SOURCE_PATH_INDEX_CACHE[key] = indexed
    return indexed


def _source_file_epsg(
    settings: ProjectSettings | None,
    file_name: str,
    *,
    database=None,
    project_name: str = "",
) -> str:
    if settings is None or not file_name:
        return ""
    path = _resolve_source_path(settings, file_name)
    if path is not None:
        return _file_epsg(path, database=database, project_name=project_name)
    target = Path(file_name).name
    folder = getattr(settings, "p111_p190_dir", "") or ""
    if folder:
        candidate = Path(folder) / target
        if candidate.is_file():
            return _file_epsg(candidate, database=database, project_name=project_name)
    return ""


def _resolve_source_path(settings: ProjectSettings | None, file_name: str) -> Path | None:
    if settings is None or not file_name:
        return None
    target = Path(file_name).name
    cache_key = (_settings_source_key(settings), target)
    if cache_key in _RESOLVED_SOURCE_PATH_CACHE:
        return _RESOLVED_SOURCE_PATH_CACHE[cache_key]
    # Resolve the candidate path purely from the in-memory index (no network
    # is_file() probe). Callers that must actually read the file verify
    # existence lazily; cache hits (recalc) never touch the filesystem.
    indexed = _source_path_index(settings)
    resolved = indexed.get(target)
    if resolved is None:
        folder = getattr(settings, "p111_p190_dir", "") or ""
        if folder:
            resolved = Path(folder) / target
    _RESOLVED_SOURCE_PATH_CACHE[cache_key] = resolved
    return resolved


def _parse_receiver_feathers(path: Path) -> list:
    """Parse receiver feathers from P111 (CSV R1) or P190 (fixed-width R) files."""
    suffix = path.suffix.lower()
    if suffix in (".p111", ".111"):
        return parse_p111_receiver_feathers(path)
    if suffix in (".p190", ".190", ".navplan"):
        return parse_p190_receiver_feathers(path)
    # Unknown extension: sniff the first records to pick the right parser.
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for _ in range(200):
                line = handle.readline()
                if not line:
                    break
                if line.startswith("R1,") or line.startswith("S1,"):
                    return parse_p111_receiver_feathers(path)
                if line[:1] in ("R", "S") and "," not in line[:6]:
                    return parse_p190_receiver_feathers(path)
    except OSError:
        return []
    return parse_p111_receiver_feathers(path)


def _receiver_records_from_cache_rows(rows: list[dict]) -> list[ReceiverFeatherRecord]:
    return [
        ReceiverFeatherRecord(
            shotpoint=int(row.get("shotpoint", 0)),
            line_name=str(row.get("line_name", "")),
            streamer_id="AVG",
            feather_deg=float(row.get("feather_deg", 0.0)),
            sequence_no=str(row.get("sequence_no", "")),
            subline=str(row.get("subline", "")),
            preplot_no=str(row.get("preplot_no", "")),
        )
        for row in rows
    ]


def _receiver_cache_rows(records: list[ReceiverFeatherRecord]) -> list[dict]:
    grouped: dict[tuple[str, str, str, str, int], list[float]] = {}
    for record in records:
        key = (
            record.sequence_no,
            record.line_name,
            record.subline,
            record.preplot_no,
            record.shotpoint,
        )
        grouped.setdefault(key, []).append(record.feather_deg)
    return [
        {
            "sequence_no": sequence_no,
            "line_name": line_name,
            "subline": subline,
            "preplot_no": preplot_no,
            "shotpoint": shotpoint,
            "feather_deg": sum(values) / len(values),
        }
        for (sequence_no, line_name, subline, preplot_no, shotpoint), values
        in grouped.items()
        if values
    ]


def _filter_receiver_feather_records(
    path: Path,
    records: list[ReceiverFeatherRecord],
    *,
    line_name: str = "",
    sequence_group: str = "",
    subline: str = "",
) -> list[ReceiverFeatherRecord]:
    if line_name:
        by_line = [
            record
            for record in records
            if _line_names_match(line_name, record.line_name)
        ]
        # The resolved path is already the file for this match; keep all records
        # rather than dropping everything if the name forms do not intersect.
        if by_line:
            records = by_line
    if sequence_group:
        filtered = [
            record
            for record in records
            if make_sequence_group_id(path.name, record.sequence_no, record.line_name)
            == sequence_group
        ]
        # P190 line files are single-sequence and may not reproduce the exact
        # sequence id; keep the unfiltered set rather than dropping everything.
        if filtered:
            records = filtered
    if subline:
        by_subline = [
            record
            for record in records
            if not record.subline or record.subline == subline
        ]
        # A navplan baseline carries its own subline (e.g. "1") that differs
        # from the acquired line's subline (e.g. "a070"); don't let that empty
        # the per-shotpoint feathers for an already file-scoped path.
        if by_subline:
            records = by_subline
    return records


def source_has_streamers(
    path: Path | None,
    *,
    max_shot_probe: int = 16,
    hard_line_cap: int = 4_000_000,
    database=None,
    project_name: str = "",
) -> bool:
    """Fast probe: does this firing-source file carry receiver/streamer records?

    Firing-source-only P111/P190 files (e.g. 4030/7027 ``P111V`` exports) hold
    only S/P shot positions and yield no streamer feather. Streamer surveys
    (e.g. 0085 12-streamer, 10221 8-streamer) emit receiver (``R1,`` / fixed
    ``R``) records from the very first shotpoint of DATA.

    The header block can be very large (e.g. 10221 P190 sources have ~15k header
    lines), so the probe must not bound on raw line count alone. It returns as
    soon as a receiver record is seen and otherwise bails after ``max_shot_probe``
    *data* shot records (headers are skipped for free), keeping source-only files
    cheap on UI load. ``hard_line_cap`` is only a pathological-file safety valve.
    """
    if path is None:
        return False
    # Network-free fast path: a cached marker (from import) tells us whether the
    # file carries streamers without re-probing the source over the network.
    if database is not None and project_name.strip() and path.name:
        by_name = database.load_postplot_4d_file_cache_by_name(
            project_name.strip(),
            path.name,
        )
        if by_name and (
            by_name.get("has_streamers") or by_name.get("receiver_feathers_cached")
        ):
            return bool(by_name.get("has_streamers"))
    if not path.is_file():
        return False
    file_path, file_mtime, file_size = _file_fingerprint(path)
    if database is not None and project_name.strip() and file_path:
        cached = database.load_postplot_4d_file_cache(
            project_name.strip(),
            file_path,
            file_mtime,
            file_size,
        )
        if cached and cached.get("has_streamers"):
            return True
    suffix = path.suffix.lower()
    if suffix in (".p111", ".111"):
        fmt = "p111"
    elif suffix in (".p190", ".190", ".navplan"):
        fmt = "p190"
    else:
        fmt = ""
    shots_seen = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, raw in enumerate(handle):
                if index >= hard_line_cap:
                    break
                if fmt == "p111" and raw.startswith(("H", "C")):
                    header_text = raw.lower()
                    if "receiver group definition" in header_text:
                        if database is not None and project_name.strip() and file_path:
                            database.save_postplot_4d_file_cache(
                                project_name.strip(),
                                file_path,
                                path.name,
                                file_mtime,
                                file_size,
                                has_streamers=True,
                            )
                        return True
                if fmt == "p111" or raw.startswith(("R1,", "S1,")):
                    if raw.startswith("R1,"):
                        if database is not None and project_name.strip() and file_path:
                            database.save_postplot_4d_file_cache(
                                project_name.strip(),
                                file_path,
                                path.name,
                                file_mtime,
                                file_size,
                                has_streamers=True,
                            )
                        return True
                    if raw.startswith("S1,"):
                        shots_seen += 1
                        if shots_seen > max_shot_probe:
                            if database is not None and project_name.strip() and file_path:
                                database.save_postplot_4d_file_cache(
                                    project_name.strip(),
                                    file_path,
                                    path.name,
                                    file_mtime,
                                    file_size,
                                    receiver_feathers_cached=True,
                                    has_streamers=False,
                                )
                            return False
                    continue
                head = raw[:1].upper()
                # Fixed-width P190 receiver records start with ``R`` (never a
                # comma in the first field); a P111-style ``R1,`` is handled
                # above so this only matches genuine P190 receiver rows.
                if head == "R" and "," not in raw[:4] and len(raw.rstrip()) >= 23:
                    return True
                if head == "S" and "," not in raw[:4]:
                    shots_seen += 1
                    if shots_seen > max_shot_probe:
                        if database is not None and project_name.strip() and file_path:
                            database.save_postplot_4d_file_cache(
                                project_name.strip(),
                                file_path,
                                path.name,
                                file_mtime,
                                file_size,
                                receiver_feathers_cached=True,
                                has_streamers=False,
                            )
                        return False
    except OSError:
        return False
    if database is not None and project_name.strip() and file_path:
        database.save_postplot_4d_file_cache(
            project_name.strip(),
            file_path,
            path.name,
            file_mtime,
            file_size,
            receiver_feathers_cached=True,
            has_streamers=False,
        )
    return False


def _receiver_feathers_for_path(
    path: Path | None,
    *,
    line_name: str = "",
    sequence_group: str = "",
    subline: str = "",
    database=None,
    project_name: str = "",
) -> dict[int, float]:
    if path is None:
        return {}
    # Network-free fast path: serve the persisted feather index by file name so
    # recalc reads the DB instead of re-parsing the source over the network.
    if database is not None and project_name.strip() and path.name:
        cached, cache_rows = database.load_postplot_4d_receiver_feather_rows_by_name(
            project_name.strip(),
            path.name,
        )
        if cached:
            records = _receiver_records_from_cache_rows(cache_rows)
            records = _filter_receiver_feather_records(
                path,
                records,
                line_name=line_name,
                sequence_group=sequence_group,
                subline=subline,
            )
            return average_receiver_feathers_by_shotpoint(records)
    if not path.is_file():
        return {}
    file_path, file_mtime, file_size = _file_fingerprint(path)
    if database is not None and project_name.strip() and file_path:
        cached, cache_rows = database.load_postplot_4d_receiver_feather_rows(
            project_name.strip(),
            file_path,
            file_mtime,
            file_size,
        )
        if cached:
            records = _receiver_records_from_cache_rows(cache_rows)
            records = _filter_receiver_feather_records(
                path,
                records,
                line_name=line_name,
                sequence_group=sequence_group,
                subline=subline,
            )
            return average_receiver_feathers_by_shotpoint(records)
    try:
        records = _parse_receiver_feathers(path)
    except OSError:
        return {}
    if database is not None and project_name.strip() and file_path:
        database.save_postplot_4d_receiver_feathers(
            project_name.strip(),
            file_path,
            path.name,
            file_mtime,
            file_size,
            _receiver_cache_rows(records),
        )
    records = _filter_receiver_feather_records(
        path,
        records,
        line_name=line_name,
        sequence_group=sequence_group,
        subline=subline,
    )
    return average_receiver_feathers_by_shotpoint(records)


def _map_geographic_lat_lon(xs: list[float], ys: list[float], map_epsg: str) -> tuple[list[str], list[str]]:
    try:
        geo_epsg = geographic_epsg_from_map(map_epsg)
        lons, lats = transform_coordinates(xs, ys, map_epsg, geo_epsg)
    except Exception:  # noqa: BLE001
        return [], []
    if len(lons) != len(xs) or len(lats) != len(ys):
        return [], []
    return (
        [f"{float(lat):.8f}" for lat in lats],
        [f"{float(lon):.8f}" for lon in lons],
    )


def _sync_baseline_geographic(
    baseline: dict[BaselineKey, BaselineShotpoint],
    map_epsg: str,
) -> dict[BaselineKey, BaselineShotpoint]:
    """Set baseline lat/long strings from projected EN in the map CRS geodetic datum."""
    code = normalize_epsg(map_epsg)
    if not code or not baseline:
        return baseline
    keys = list(baseline)
    lats, lons = _map_geographic_lat_lon(
        [baseline[key].x for key in keys],
        [baseline[key].y for key in keys],
        code,
    )
    if len(lats) != len(keys):
        return baseline
    return {
        key: BaselineShotpoint(
            shotpoint=baseline[key].shotpoint,
            x=baseline[key].x,
            y=baseline[key].y,
            latitude=lats[index],
            longitude=lons[index],
            source_id=baseline[key].source_id,
            source_index=baseline[key].source_index,
        )
        for index, key in enumerate(keys)
    }


def _sync_source_geographic(
    sources: dict[int, PositionRecord],
    map_epsg: str,
) -> dict[int, PositionRecord]:
    """Set firing-source lat/long strings from projected EN in the map CRS geodetic datum."""
    code = normalize_epsg(map_epsg)
    if not code or not sources:
        return sources
    shotpoints = sorted(sources)
    lats, lons = _map_geographic_lat_lon(
        [sources[sp].x for sp in shotpoints],
        [sources[sp].y for sp in shotpoints],
        code,
    )
    if len(lats) != len(shotpoints):
        return sources
    return {
        sp: replace(
            sources[sp],
            latitude=lats[index],
            longitude=lons[index],
        )
        for index, sp in enumerate(shotpoints)
    }


def _reproject_baseline(
    baseline: dict[BaselineKey, BaselineShotpoint],
    src_epsg: str,
    dst_epsg: str,
) -> dict[BaselineKey, BaselineShotpoint]:
    """Reproject baseline shotpoints into the common map CRS (no-op if equal)."""
    src = normalize_epsg(src_epsg)
    dst = normalize_epsg(dst_epsg)
    if not src or not dst or src == dst or not baseline:
        return baseline
    keys = list(baseline)
    new_x, new_y = transform_coordinates(
        [baseline[k].x for k in keys],
        [baseline[k].y for k in keys],
        src,
        dst,
    )
    if len(new_x) != len(keys) or len(new_y) != len(keys):
        return baseline  # refuse to corrupt on a partial transform
    lats, lons = _map_geographic_lat_lon(new_x, new_y, dst)
    result: dict[BaselineKey, BaselineShotpoint] = {}
    for index, key in enumerate(keys):
        point = baseline[key]
        result[key] = BaselineShotpoint(
            shotpoint=point.shotpoint,
            x=new_x[index],
            y=new_y[index],
            latitude=lats[index] if lats else point.latitude,
            longitude=lons[index] if lons else point.longitude,
            source_id=point.source_id,
            source_index=point.source_index,
        )
    return result


def _reproject_sources(
    sources: dict[int, PositionRecord],
    settings: ProjectSettings | None,
    dst_epsg: str,
    *,
    database=None,
    project_name: str = "",
) -> dict[int, PositionRecord]:
    """Reproject firing-source shotpoints into the common map CRS (no-op if equal)."""
    dst = normalize_epsg(dst_epsg)
    if not dst or not sources:
        return sources
    by_file: dict[str, list[int]] = defaultdict(list)
    for shotpoint, record in sources.items():
        by_file[record.file_name].append(shotpoint)
    result: dict[int, PositionRecord] = {}
    epsg_cache: dict[str, str] = {}
    for file_name, shotpoints in by_file.items():
        if file_name not in epsg_cache:
            epsg_cache[file_name] = normalize_epsg(
                _source_file_epsg(
                    settings,
                    file_name,
                    database=database,
                    project_name=project_name,
                )
            )
        src = epsg_cache[file_name]
        if not src or src == dst:
            for shotpoint in shotpoints:
                result[shotpoint] = sources[shotpoint]
            continue
        new_x, new_y = transform_coordinates(
            [sources[sp].x for sp in shotpoints],
            [sources[sp].y for sp in shotpoints],
            src,
            dst,
        )
        if len(new_x) != len(shotpoints) or len(new_y) != len(shotpoints):
            for shotpoint in shotpoints:
                result[shotpoint] = sources[shotpoint]
            continue
        lats, lons = _map_geographic_lat_lon(new_x, new_y, dst)
        for index, shotpoint in enumerate(shotpoints):
            record = sources[shotpoint]
            result[shotpoint] = replace(
                record,
                x=new_x[index],
                y=new_y[index],
                latitude=lats[index] if lats else record.latitude,
                longitude=lons[index] if lons else record.longitude,
            )
    return result


def _offset_components(
    delta_e: float,
    delta_n: float,
    azimuth_deg: float,
) -> tuple[float, float, float]:
    theta = math.radians(azimuth_deg)
    inline = delta_e * math.sin(theta) + delta_n * math.cos(theta)
    crossline = delta_e * math.cos(theta) - delta_n * math.sin(theta)
    radial = math.hypot(inline, crossline)
    return inline, crossline, radial


def compute_postplot_4d_diff_rows(
    baseline: dict[BaselineKey, BaselineShotpoint],
    sources: dict[int, PositionRecord],
    line_direction: str,
    *,
    baseline_path: Path | None = None,
    navplan_feathers: dict[int, float] | None = None,
    line_feathers: dict[int, float] | None = None,
    vessel_ids: dict[int, str] | None = None,
) -> list[Postplot4DDiffRow]:
    if not baseline or not sources:
        return []

    azimuth = resolve_line_azimuth_degrees(line_direction, baseline, baseline_path)
    source_count = _baseline_source_count(baseline)
    reverse_sources = _source_lookup_reversed(baseline, azimuth)

    rows: list[Postplot4DDiffRow] = []
    for shotpoint in sorted(sources):
        source = sources[shotpoint]
        source_key = _source_key(source.source_id)
        lookup_key = _remap_source_key_for_direction(source_key, source_count, reverse_sources)
        base = baseline.get((shotpoint, lookup_key))
        if base is None and lookup_key != source_key:
            base = baseline.get((shotpoint, source_key))
        if base is None:
            base = baseline.get(shotpoint)
        if base is None:
            continue
        delta_e = source.x - base.x
        delta_n = source.y - base.y
        inline, crossline, radial = _offset_components(delta_e, delta_n, azimuth)
        vessel_id = source.vessel_id
        if not vessel_id and vessel_ids:
            vessel_id = vessel_ids.get(shotpoint, "")
        firing_source_id = source.source_id
        rows.append(
            Postplot4DDiffRow(
                shotpoint=shotpoint,
                baseline_x=base.x,
                baseline_y=base.y,
                baseline_latitude=base.latitude,
                baseline_longitude=base.longitude,
                source_x=source.x,
                source_y=source.y,
                source_latitude=source.latitude,
                source_longitude=source.longitude,
                crossline_m=crossline,
                inline_m=inline,
                radial_m=radial,
                navplan_feather_deg=(
                    navplan_feathers.get(shotpoint) if navplan_feathers else None
                ),
                line_feather_deg=(
                    line_feathers.get(shotpoint) if line_feathers else None
                ),
                vessel_id=vessel_id,
                firing_source_id=firing_source_id,
            )
        )
    return rows


def assess_diff_crs_consistency(
    map_data: MapData | None,
    settings: ProjectSettings | None,
    positions: list[PositionRecord],
    match_row: Postplot4DMatchRow,
    *,
    database=None,
    project_name: str = "",
) -> DiffCrsAssessment:
    """Validate that baseline + firing-source coordinates resolve to ONE CRS.

    Returns an assessment describing whether the Diff Stat can be safely
    computed. The contract is intentionally strict (zero tolerance): every
    participating file must declare a resolvable EPSG, and any differences must
    be reconcilable to a single map CRS via an available transform.
    """
    map_epsg = normalize_epsg(resolve_diff_map_epsg(map_data, settings))
    baseline_path = _resolve_baseline_path(
        settings,
        match_row.baseline_kind,
        match_row.baseline_file_name,
    )
    baseline_kind = "Navplan" if match_row.baseline_kind == "navplan" else "Preplot"
    if baseline_path is None:
        return DiffCrsAssessment(
            False,
            f"{baseline_kind} baseline file not found for "
            f"{match_row.baseline_file_name or match_row.baseline_name}",
            map_epsg,
            "",
            (),
        )
    baseline_epsg = _baseline_file_epsg(
        settings,
        match_row.baseline_kind,
        match_row.baseline_file_name,
        baseline_path,
        database=database,
        project_name=project_name,
    )

    sources = source_shotpoints_for_match(positions, match_row)
    source_files = sorted({record.file_name for record in sources.values() if record.file_name})
    source_epsgs = tuple(
        normalize_epsg(
            _source_file_epsg(
                settings,
                file_name,
                database=database,
                project_name=project_name,
            )
        )
        for file_name in source_files
    )

    if not baseline_epsg:
        return DiffCrsAssessment(
            False,
            f"{baseline_kind} CRS could not be determined from {baseline_path.name} "
            "(missing/unrecognised datum + projection header)",
            map_epsg,
            baseline_epsg,
            source_epsgs,
        )
    if not source_files:
        return DiffCrsAssessment(
            False,
            "No firing-source (P111/P190) shotpoints found for this line",
            map_epsg,
            baseline_epsg,
            source_epsgs,
        )
    unknown_sources = [
        Path(file_name).name
        for file_name, epsg in zip(source_files, source_epsgs)
        if not epsg
    ]
    if unknown_sources:
        return DiffCrsAssessment(
            False,
            "Firing-source CRS could not be determined from "
            + ", ".join(unknown_sources[:3])
            + (" …" if len(unknown_sources) > 3 else ""),
            map_epsg,
            baseline_epsg,
            source_epsgs,
        )

    distinct = {baseline_epsg, *source_epsgs}
    if map_epsg:
        distinct.add(map_epsg)
    if len(distinct) <= 1:
        return DiffCrsAssessment(
            True,
            f"All inputs share EPSG:{baseline_epsg}",
            map_epsg or baseline_epsg,
            baseline_epsg,
            source_epsgs,
        )
    # Differing CRS: a single map target plus an available transform is required
    # so baseline and sources can be projected into one grid before differencing.
    if not map_epsg:
        return DiffCrsAssessment(
            False,
            "Baseline and firing-source CRS differ ("
            + ", ".join(sorted(distinct))
            + ") and no map CRS is set to reconcile them",
            map_epsg,
            baseline_epsg,
            source_epsgs,
        )
    if not pyproj_available():
        return DiffCrsAssessment(
            False,
            "Inputs use different CRS ("
            + ", ".join(sorted(distinct))
            + ") and pyproj is unavailable to reproject them",
            map_epsg,
            baseline_epsg,
            source_epsgs,
        )
    return DiffCrsAssessment(
        True,
        "Inputs reprojected to EPSG:" + map_epsg,
        map_epsg,
        baseline_epsg,
        source_epsgs,
    )


def calculate_match_diff_rows(
    map_data: MapData | None,
    settings: ProjectSettings | None,
    positions: list[PositionRecord],
    match_row: Postplot4DMatchRow,
    *,
    database=None,
    project_name: str = "",
) -> list[Postplot4DDiffRow]:
    assessment = assess_diff_crs_consistency(
        map_data,
        settings,
        positions,
        match_row,
        database=database,
        project_name=project_name,
    )
    if not assessment.ok:
        raise CrsMismatchError(assessment.reason)
    map_epsg = resolve_diff_map_epsg(map_data, settings)
    baseline_path = _resolve_baseline_path(
        settings,
        match_row.baseline_kind,
        match_row.baseline_file_name,
    )
    baseline = load_baseline_shotpoints(
        map_data,
        settings,
        match_row.baseline_kind,
        match_row.baseline_name,
        match_row.baseline_file_name,
        database=database,
        project_name=project_name,
        map_epsg=map_epsg,
    )
    # Ensure baseline and firing sources share one projected CRS (datum +
    # projection) before differencing. No-op when files already match map_epsg.
    baseline = _reproject_baseline(
        baseline,
        _baseline_file_epsg(
            settings,
            match_row.baseline_kind,
            match_row.baseline_file_name,
            baseline_path,
            database=database,
            project_name=project_name,
        ),
        map_epsg,
    )
    sources = source_shotpoints_for_match(positions, match_row)
    sources = _reproject_sources(
        sources,
        settings,
        map_epsg,
        database=database,
        project_name=project_name,
    )
    navplan_feathers: dict[int, float] | None = None
    if match_row.baseline_kind == "navplan":
        navplan_feathers = _receiver_feathers_for_path(
            baseline_path,
            line_name=match_row.baseline_name,
            subline=match_row.subline,
            database=database,
            project_name=project_name,
        )
    # Line feather is the firing-source streamer feather and is independent of
    # the baseline kind: it is meaningful for a preplot baseline too, whenever
    # the P111/P190 source carries streamers. It stays empty (column hidden)
    # for firing-source-only files that have no receiver records.
    source_file_names = {
        record.file_name for record in sources.values() if record.file_name
    }
    source_paths = {
        _resolve_source_path(settings, file_name) for file_name in source_file_names
    }
    source_paths.discard(None)
    line_feathers: dict[int, float] = {}
    target_group = sequence_group_id(match_row.sequence_id)
    for source_path in source_paths:
        # Gate the expensive receiver-feather parse behind a cheap streamer
        # probe: firing-source-only files (e.g. 4030/7027 P111V) have no
        # streamers, so a full multi-pass parse here would only burn time
        # (~33 ms/file) producing nothing. The probe bails in ~0.5 ms.
        if not source_has_streamers(
            source_path,
            database=database,
            project_name=project_name,
        ):
            continue
        line_feathers.update(
            _receiver_feathers_for_path(
                source_path,
                sequence_group=target_group,
                subline=match_row.subline,
                database=database,
                project_name=project_name,
            )
        )
    baseline = _sync_baseline_geographic(baseline, map_epsg)
    sources = _sync_source_geographic(sources, map_epsg)
    vessel_ids = vessel_shotpoints_for_match(positions, match_row)
    return compute_postplot_4d_diff_rows(
        baseline,
        sources,
        match_row.line_direction,
        baseline_path=baseline_path,
        navplan_feathers=navplan_feathers,
        line_feathers=line_feathers,
        vessel_ids=vessel_ids,
    )


_MAX_FEATHER_WARM_WORKERS = 8


def warm_postplot_4d_parse_caches(
    map_data: MapData | None,
    settings: ProjectSettings,
    database,
    project_name: str,
    *,
    include_receiver_feathers: bool = True,
    db_path=None,
    progress_callback=None,
    cancelled=None,
) -> tuple[int, int]:
    """Populate parse-derived Diff Stat inputs in the DB, never diff results.

    This is intended for background import/save work. It precomputes dense
    preplot baseline shotpoints for every imported preplot line and caches
    receiver/streamer feather metadata for P111/P190/navplan files. The math is
    the same as the on-demand Diff Stat path; this only moves the work earlier.
    """
    if map_data is None or database is None or not project_name.strip():
        return 0, 0

    def is_cancelled() -> bool:
        return bool(cancelled and cancelled())

    map_epsg = resolve_diff_map_epsg(map_data, settings)
    preplot_segments = [
        segment
        for segment in map_data.preplot_segments
        if segment.file_name and segment.line_name
    ]
    feather_paths: list[Path] = []
    if include_receiver_feathers:
        seen_paths: set[str] = set()
        for raw in [
            *settings.nav_files,
            *settings.navplan_files,
            *(entry.file_path for entry in settings.navplan_catalog),
        ]:
            if not raw:
                continue
            path = Path(raw)
            key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            feather_paths.append(path)

    total = len(preplot_segments) + len(feather_paths)
    completed = 0
    preplot_lines = 0
    feather_files = 0

    for segment in preplot_segments:
        if is_cancelled():
            break
        path = _resolve_baseline_path(settings, "preplot", segment.file_name)
        generated = _generated_preplot_baseline_from_segment(
            segment,
            segment.line_name,
            path,
            database=database,
            project_name=project_name,
            map_epsg=map_epsg,
        )
        if generated:
            preplot_lines += 1
        completed += 1
        if progress_callback:
            progress_callback(
                completed,
                total,
                f"Cached preplot line {segment.line_name}",
            )

    def _warm_one(path: Path, warm_db) -> bool:
        # Network feather files are I/O bound, so reading several at once hides
        # SMB latency. EPSG + streamer probe + feather index are cached per file.
        _file_epsg(path, database=warm_db, project_name=project_name)
        if source_has_streamers(path, database=warm_db, project_name=project_name):
            _receiver_feathers_for_path(
                path,
                database=warm_db,
                project_name=project_name,
            )
            return True
        return False

    warm_workers = (
        min(len(feather_paths), _MAX_FEATHER_WARM_WORKERS)
        if db_path is not None
        else 1
    )

    if warm_workers <= 1:
        for path in feather_paths:
            if is_cancelled():
                break
            if _warm_one(path, database):
                feather_files += 1
            completed += 1
            if progress_callback:
                progress_callback(
                    completed,
                    total,
                    f"Cached feather data for {path.name}",
                )
        return preplot_lines, feather_files

    # Parallel across files: each worker thread gets its own DB connection
    # (sqlite connections are single-thread) with a busy timeout so concurrent
    # writers queue instead of raising "database is locked".
    import threading
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    from xpostmaps.core.database import Database

    thread_local = threading.local()
    opened_dbs: list[Database] = []
    opened_lock = threading.Lock()

    def _worker_db() -> Database:
        db = getattr(thread_local, "db", None)
        if db is None:
            db = Database(db_path)
            try:
                db._conn.execute("PRAGMA busy_timeout=30000")
            except Exception:  # noqa: BLE001
                pass
            thread_local.db = db
            with opened_lock:
                opened_dbs.append(db)
        return db

    def _task(path: Path) -> bool:
        return _warm_one(path, _worker_db())

    executor = ThreadPoolExecutor(max_workers=warm_workers)
    try:
        pending_iter = iter(feather_paths)
        futures: dict = {}

        def _submit_next() -> None:
            while not is_cancelled() and len(futures) < warm_workers:
                try:
                    nxt = next(pending_iter)
                except StopIteration:
                    return
                futures[executor.submit(_task, nxt)] = nxt

        _submit_next()
        while futures and not is_cancelled():
            done, _ = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                path = futures.pop(future)
                try:
                    if future.result():
                        feather_files += 1
                except Exception:  # noqa: BLE001
                    pass
                completed += 1
                if progress_callback:
                    progress_callback(
                        completed,
                        total,
                        f"Cached feather data for {path.name}",
                    )
            _submit_next()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        with opened_lock:
            for db in opened_dbs:
                db.close()
            opened_dbs.clear()

    return preplot_lines, feather_files


def diff_row_to_dict(row: Postplot4DDiffRow) -> dict:
    return {
        "shotpoint": row.shotpoint,
        "baseline_x": row.baseline_x,
        "baseline_y": row.baseline_y,
        "baseline_latitude": row.baseline_latitude,
        "baseline_longitude": row.baseline_longitude,
        "source_x": row.source_x,
        "source_y": row.source_y,
        "source_latitude": row.source_latitude,
        "source_longitude": row.source_longitude,
        "crossline_m": row.crossline_m,
        "inline_m": row.inline_m,
        "radial_m": row.radial_m,
        "navplan_feather_deg": row.navplan_feather_deg,
        "line_feather_deg": row.line_feather_deg,
        "vessel_id": row.vessel_id,
        "firing_source_id": row.firing_source_id,
    }


def _optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def diff_row_from_dict(data: dict) -> Postplot4DDiffRow:
    return Postplot4DDiffRow(
        shotpoint=int(data.get("shotpoint", 0)),
        baseline_x=float(data.get("baseline_x", 0.0)),
        baseline_y=float(data.get("baseline_y", 0.0)),
        baseline_latitude=str(data.get("baseline_latitude", "")),
        baseline_longitude=str(data.get("baseline_longitude", "")),
        source_x=float(data.get("source_x", 0.0)),
        source_y=float(data.get("source_y", 0.0)),
        source_latitude=str(data.get("source_latitude", "")),
        source_longitude=str(data.get("source_longitude", "")),
        crossline_m=float(data.get("crossline_m", 0.0)),
        inline_m=float(data.get("inline_m", 0.0)),
        radial_m=float(data.get("radial_m", 0.0)),
        navplan_feather_deg=_optional_float(data.get("navplan_feather_deg")),
        line_feather_deg=_optional_float(data.get("line_feather_deg")),
        vessel_id=str(data.get("vessel_id", "")),
        firing_source_id=str(data.get("firing_source_id", "")),
    )
