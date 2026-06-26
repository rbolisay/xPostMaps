"""Postplot 4D diff-stat calculations and persistence helpers."""

from __future__ import annotations

import math
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
from xpostmaps.parsers.preplot_parser import parse_navplan_source_file, parse_preplot_file
from xpostmaps.core.crs_utils import (
    WGS84_EPSG,
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

    segments = (
        map_data.navplan_segments if baseline_kind == "navplan" else map_data.preplot_segments
    )
    target_name = Path(baseline_file_name).name if baseline_file_name else ""
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
    if path is None or not path.is_file():
        return "", 0.0, 0
    stat = path.stat()
    return str(path.resolve()), float(stat.st_mtime), int(stat.st_size)


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
        lons, lats = transform_coordinates(
            [point.x for point in ordered],
            [point.y for point in ordered],
            code,
            WGS84_EPSG,
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


def _file_epsg(path: Path | None) -> str:
    """Resolve the EPSG (datum + projection) declared in a nav/preplot file."""
    if path is None or not path.is_file():
        return ""
    try:
        metadata = parse_file_metadata(path)
    except OSError:
        return ""
    return normalize_epsg(metadata.get("epsg code", ""))


def _source_file_epsg(settings: ProjectSettings | None, file_name: str) -> str:
    if settings is None or not file_name:
        return ""
    target = Path(file_name).name
    for raw in settings.nav_files:
        path = Path(raw)
        if path.name == target and path.is_file():
            return _file_epsg(path)
    folder = getattr(settings, "p111_p190_dir", "") or ""
    if folder:
        candidate = Path(folder) / target
        if candidate.is_file():
            return _file_epsg(candidate)
    return ""


def _wgs84_lat_lon(xs: list[float], ys: list[float], map_epsg: str) -> tuple[list[str], list[str]]:
    try:
        lons, lats = transform_coordinates(xs, ys, map_epsg, WGS84_EPSG)
    except Exception:  # noqa: BLE001
        return [], []
    if len(lons) != len(xs) or len(lats) != len(ys):
        return [], []
    return (
        [f"{float(lat):.8f}" for lat in lats],
        [f"{float(lon):.8f}" for lon in lons],
    )


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
    lats, lons = _wgs84_lat_lon(new_x, new_y, dst)
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
            epsg_cache[file_name] = normalize_epsg(_source_file_epsg(settings, file_name))
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
        lats, lons = _wgs84_lat_lon(new_x, new_y, dst)
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
            )
        )
    return rows


def assess_diff_crs_consistency(
    map_data: MapData | None,
    settings: ProjectSettings | None,
    positions: list[PositionRecord],
    match_row: Postplot4DMatchRow,
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
    baseline_epsg = _file_epsg(baseline_path)

    sources = source_shotpoints_for_match(positions, match_row)
    source_files = sorted({record.file_name for record in sources.values() if record.file_name})
    source_epsgs = tuple(
        normalize_epsg(_source_file_epsg(settings, file_name)) for file_name in source_files
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
    assessment = assess_diff_crs_consistency(map_data, settings, positions, match_row)
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
    baseline = _reproject_baseline(baseline, _file_epsg(baseline_path), map_epsg)
    sources = source_shotpoints_for_match(positions, match_row)
    sources = _reproject_sources(sources, settings, map_epsg)
    return compute_postplot_4d_diff_rows(
        baseline,
        sources,
        match_row.line_direction,
        baseline_path=baseline_path,
    )


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
    }


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
    )
