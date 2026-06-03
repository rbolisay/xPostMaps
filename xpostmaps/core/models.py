"""Data models for xPostMaps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class DisplayMode(str, Enum):
    LINES = "lines"
    DOTS = "dots"


class LineStyle(str, Enum):
    SOLID = "solid"
    DOTTED = "dotted"  # circles / points along the line
    DASH = "dash"      # dashed line segments


class AreaCoordinateMode(str, Enum):
    SURVEY_PERIMETER = "survey_perimeter"
    IMPORTED = "imported"
    CUSTOM = "custom"


@dataclass
class PolygonPoint:
    x: float = 0.0
    y: float = 0.0
    latitude: str = ""
    longitude: str = ""


@dataclass
class SurveyPerimeter:
    file_name: str = ""
    name: str = ""
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)
    latitudes: list[str] = field(default_factory=list)
    longitudes: list[str] = field(default_factory=list)


@dataclass
class AreaLegendEntry:
    name: str = ""
    border_style: LineStyle = LineStyle.SOLID
    color: str = "#60a5fa"
    opacity: float = 1.0
    border_width: float = 2.0
    hidden: bool = False
    coordinate_mode: AreaCoordinateMode = AreaCoordinateMode.SURVEY_PERIMETER
    survey_perimeter_index: int = 0
    imported_polygon_index: int = 0
    custom_points: list[PolygonPoint] = field(default_factory=list)
    source_file: str = ""
    source_epsg: str = ""
    import_polygon_number: int = 0


class NavDataType(str, Enum):
    VESSEL = "vessel"
    SOURCE = "source"


@dataclass
class PreplotCatalogEntry:
    preplot_number: int = 0
    file_path: str = ""
    crs_code: str = ""
    total_lines: int = 0


@dataclass
class NavplanCatalogEntry:
    navplan_number: int = 0
    navplan_name: str = ""
    file_path: str = ""
    crs_code: str = ""
    fsp: int = 0
    lsp: int = 0
    total_points: int = 0


@dataclass
class PreplotLegendEntry:
    name: str = ""
    preplot_source_index: int = 0
    line_style: LineStyle = LineStyle.SOLID
    color: str = "#f59e0b"
    opacity: float = 1.0
    line_width: float = 0.9
    dot_radius: float = 3.0
    hidden: bool = False


@dataclass
class NavplanLegendEntry:
    name: str = ""
    line_style: LineStyle = LineStyle.SOLID
    color: str = "#22c55e"
    opacity: float = 1.0
    line_width: float = 0.9
    dot_radius: float = 3.0
    hidden: bool = False
    navplan_source_indices: list[int] = field(default_factory=list)
    navplan_filter_active: bool = False


@dataclass
class PostplotLegendEntry:
    name: str = ""
    line_style: LineStyle = LineStyle.SOLID
    color: str = "#ef4444"
    opacity: float = 1.0
    line_width: float = 1.2
    dot_radius: float = 3.0
    hidden: bool = False
    data_type: NavDataType = NavDataType.SOURCE
    sequence_ids: list[str] = field(default_factory=list)
    sequence_filter_active: bool = False


@dataclass
class LegendConfig:
    areas: list[AreaLegendEntry] = field(default_factory=list)
    preplot_lines: list[PreplotLegendEntry] = field(default_factory=list)
    navplan_lines: list[NavplanLegendEntry] = field(default_factory=list)
    postplot_lines: list[PostplotLegendEntry] = field(default_factory=list)

    @staticmethod
    def default() -> LegendConfig:
        # Area rows are not auto-populated; the user adds them explicitly.
        # Imported polygons, preplots and survey perimeters are never added
        # to the Area table automatically.
        return LegendConfig(
            areas=[],
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
    nav_files_explicit: bool = False
    preplot_files: list[str] = field(default_factory=list)
    preplot_files_explicit: bool = False
    preplots_dir: str = ""
    preplot_catalog: list[PreplotCatalogEntry] = field(default_factory=list)
    navplan_files: list[str] = field(default_factory=list)
    navplan_files_explicit: bool = False
    navplans_dir: str = ""
    navplan_catalog: list[NavplanCatalogEntry] = field(default_factory=list)
    overlay_dir: str = ""  # legacy; migrated to preplot_files
    display_mode: DisplayMode = DisplayMode.LINES
    show_source: bool = True
    show_vessel: bool = True
    show_overlay: bool = True
    show_preplots: bool = True
    logo_path: str = ""
    legend_config: LegendConfig = field(default_factory=LegendConfig.default)
    minimap_view: dict[str, float] = field(default_factory=dict)


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
    date: str = field(default_factory=lambda: date.today().isoformat())
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
    navplan_segments: list[LineSegment] = field(default_factory=list)
    sequences: list[LineSequence] = field(default_factory=list)
    positions: list[PositionRecord] = field(default_factory=list)
    bounds: SurveyBounds = field(default_factory=SurveyBounds)
    geo_bounds: GeoBounds = field(default_factory=GeoBounds)
    postmap_info: PostmapInfo = field(default_factory=PostmapInfo)
    source_files: list[str] = field(default_factory=list)
    nav_file_cache: dict[str, tuple[float, int, str]] = field(default_factory=dict)
    survey_perimeters: list[SurveyPerimeter] = field(default_factory=list)
    preplot_file_order: list[str] = field(default_factory=list)
    navplan_file_order: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    # Transient flag: positions already exist in the DB and have not been
    # re-parsed/modified in memory. When True and ``positions`` is empty, the
    # heavy positions table must NOT be rewritten or cleared on save.
    positions_persisted: bool = False
