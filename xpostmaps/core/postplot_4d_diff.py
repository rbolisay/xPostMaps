"""Postplot 4D diff-stat calculations and persistence helpers."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
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
from xpostmaps.parsers.p190_parser import parse_p190_header
from xpostmaps.parsers.preplot_parser import parse_navplan_source_file, parse_preplot_file
from xpostmaps.core.crs_utils import normalize_epsg

_AZIMUTH_RE = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class BaselineShotpoint:
    shotpoint: int
    x: float
    y: float
    latitude: str = ""
    longitude: str = ""


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


def load_baseline_shotpoints(
    map_data: MapData | None,
    settings: ProjectSettings | None,
    baseline_kind: BaselineKind,
    baseline_name: str,
    baseline_file_name: str,
) -> dict[int, BaselineShotpoint]:
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
            by_records = _baseline_from_records(parsed.records, baseline_name, record_type)
            if by_records:
                return by_records
        except OSError:
            pass

    segments = (
        map_data.navplan_segments if baseline_kind == "navplan" else map_data.preplot_segments
    )
    target_name = Path(baseline_file_name).name if baseline_file_name else ""
    merged: dict[int, BaselineShotpoint] = {}
    for segment in segments:
        if target_name and segment.file_name and Path(segment.file_name).name != target_name:
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
    baseline: dict[int, BaselineShotpoint],
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
    baseline: dict[int, BaselineShotpoint],
    sources: dict[int, PositionRecord],
    line_direction: str,
    *,
    baseline_path: Path | None = None,
) -> list[Postplot4DDiffRow]:
    if not baseline or not sources:
        return []

    azimuth = resolve_line_azimuth_degrees(line_direction, baseline, baseline_path)

    rows: list[Postplot4DDiffRow] = []
    for shotpoint in sorted(set(baseline) & set(sources)):
        base = baseline[shotpoint]
        source = sources[shotpoint]
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


def calculate_match_diff_rows(
    map_data: MapData | None,
    settings: ProjectSettings | None,
    positions: list[PositionRecord],
    match_row: Postplot4DMatchRow,
) -> list[Postplot4DDiffRow]:
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
    )
    sources = source_shotpoints_for_match(positions, match_row)
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
