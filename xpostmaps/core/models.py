"""Data models for xPostMaps."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DisplayMode(str, Enum):
    LINES = "lines"
    DOTS = "dots"


class LineStyle(str, Enum):
    SOLID = "solid"
    DOTTED = "dotted"  # circles / points along the line
    DASH = "dash"      # dashed line segments


class NavDataType(str, Enum):
    VESSEL = "vessel"
    SOURCE = "source"


@dataclass
class AreaLegendEntry:
    name: str = ""
    color: str = "#60a5fa"
    opacity: float = 1.0


@dataclass
class PostplotLegendEntry:
    name: str = ""
    line_style: LineStyle = LineStyle.SOLID
    color: str = "#ef4444"
    opacity: float = 1.0
    data_type: NavDataType = NavDataType.SOURCE
    sequence_ids: list[str] = field(default_factory=list)


@dataclass
class LegendConfig:
    areas: list[AreaLegendEntry] = field(default_factory=list)
    postplot_lines: list[PostplotLegendEntry] = field(default_factory=list)

    @staticmethod
    def default() -> LegendConfig:
        return LegendConfig(
            areas=[
                AreaLegendEntry(name="Full Fold Area", color="#22c55e"),
            ],
            postplot_lines=[
                PostplotLegendEntry(name="Up Line", line_style=LineStyle.SOLID, color="#ef4444"),
                PostplotLegendEntry(name="Down Line", line_style=LineStyle.SOLID, color="#3b82f6"),
            ],
        )


class RecordType(str, Enum):
    SOURCE = "source"
    VESSEL = "vessel"
    EVENT = "event"
    OVERLAY = "overlay"
    PREPLOT = "preplot"
    NAVPLAN = "navplan"


@dataclass
class PositionRecord:
    file_name: str
    record_type: RecordType
    line_name: str
    vessel_id: str
    source_id: str
    point_num: int
    x: float
    y: float
    depth: float | None = None
    latitude: str = ""
    longitude: str = ""
    sequence_no: str = ""
    line_direction: str = ""
    subline: str = ""


def make_sequence_id(
    file_name: str,
    sequence_no: str,
    line_name: str,
    record_type: RecordType,
) -> str:
    return f"{file_name}|{sequence_no}|{line_name}|{record_type.value}"


def make_sequence_group_id(
    file_name: str,
    sequence_no: str,
    line_name: str,
) -> str:
    """Group id shared by vessel and source records for the same sequence."""
    return f"{file_name}|{sequence_no}|{line_name}"


def sequence_group_id(seq_id: str) -> str:
    if seq_id.count("|") >= 3:
        return seq_id.rsplit("|", 1)[0]
    return seq_id


def sequence_id_matches(segment_seq_id: str, assigned_ids: set[str] | list[str]) -> bool:
    if not segment_seq_id or not assigned_ids:
        return False
    group = sequence_group_id(segment_seq_id)
    for seq_id in assigned_ids:
        if segment_seq_id == seq_id or group == seq_id or group == sequence_group_id(seq_id):
            return True
    return False


@dataclass
class LineSequence:
    seq_id: str
    file_name: str
    sequence_no: str
    line_name: str
    line_direction: str
    first_sp: int
    last_sp: int
    record_type: RecordType


@dataclass
class LineSegment:
    line_name: str
    record_type: RecordType
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)
    direction: int = 1  # 1 = up, -1 = down
    sequence_id: str = ""
    file_name: str = ""
    sequence_no: str = ""
    line_direction: str = ""


@dataclass
class ProjectSettings:
    name: str = ""
    p111_p190_dir: str = ""
    nav_files: list[str] = field(default_factory=list)
    preplot_files: list[str] = field(default_factory=list)
    preplots_dir: str = ""
    overlay_dir: str = ""  # legacy; migrated to preplot_files
    display_mode: DisplayMode = DisplayMode.LINES
    show_source: bool = True
    show_vessel: bool = True
    show_overlay: bool = True
    show_preplots: bool = True
    logo_path: str = ""
    legend_config: LegendConfig = field(default_factory=LegendConfig.default)


@dataclass
class PostmapInfo:
    company_name: str = "Shearwater Positioning"
    title: str = ""
    job_number: str = ""
    client: str = ""
    area: str = ""
    project: str = ""
    client_ref: str = ""
    file_name: str = ""
    user_name: str = ""
    date: str = ""
    crs_name: str = ""
    projection: str = ""
    epsg_code: str = ""
    geographic_datum: str = ""
    spheroid: str = ""
    semi_major_axis: str = ""
    inverse_flattening: str = ""
    eccentricity: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class GeoBounds:
    lat_min: float = 0.0
    lat_max: float = 0.0
    lon_min: float = 0.0
    lon_max: float = 0.0

    @property
    def is_valid(self) -> bool:
        return self.lat_max > self.lat_min and self.lon_max > self.lon_min


@dataclass
class SurveyBounds:
    xmin: float = 0.0
    xmax: float = 0.0
    ymin: float = 0.0
    ymax: float = 0.0

    @property
    def is_valid(self) -> bool:
        return self.xmax > self.xmin and self.ymax > self.ymin


@dataclass
class MapData:
    segments: list[LineSegment] = field(default_factory=list)
    overlay_segments: list[LineSegment] = field(default_factory=list)
    preplot_segments: list[LineSegment] = field(default_factory=list)
    sequences: list[LineSequence] = field(default_factory=list)
    positions: list[PositionRecord] = field(default_factory=list)
    bounds: SurveyBounds = field(default_factory=SurveyBounds)
    geo_bounds: GeoBounds = field(default_factory=GeoBounds)
    postmap_info: PostmapInfo = field(default_factory=PostmapInfo)
    source_files: list[str] = field(default_factory=list)
    nav_file_cache: dict[str, tuple[float, int]] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
