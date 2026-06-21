"""Legend config serialization helpers."""

from __future__ import annotations

from xpostmaps.core.models import (
    AreaCoordinateMode,
    AreaLegendEntry,
    LegendConfig,
    LineStyle,
    NavplanLegendEntry,
    NavDataType,
    PolygonPoint,
    PostplotLegendEntry,
    PreplotLegendEntry,
)
from xpostmaps.utils.symbology_units import migrate_dot_radius_mm, migrate_line_width_mm


def _polygon_point_to_dict(point: PolygonPoint) -> dict:
    return {
        "x": point.x,
        "y": point.y,
        "latitude": point.latitude,
        "longitude": point.longitude,
    }


def _polygon_point_from_dict(data: dict) -> PolygonPoint:
    return PolygonPoint(
        x=float(data.get("x", 0.0)),
        y=float(data.get("y", 0.0)),
        latitude=str(data.get("latitude", "")),
        longitude=str(data.get("longitude", "")),
    )


def legend_to_dict(config: LegendConfig) -> dict:
    return {
        "areas": [
            {
                "name": a.name,
                "border_style": a.border_style.value,
                "color": a.color,
                "opacity": a.opacity,
                "border_width": a.border_width,
                "hidden": a.hidden,
                "coordinate_mode": a.coordinate_mode.value,
                "survey_perimeter_index": a.survey_perimeter_index,
                "imported_polygon_index": a.imported_polygon_index,
                "custom_points": [_polygon_point_to_dict(p) for p in a.custom_points],
                "source_file": a.source_file,
                "source_epsg": a.source_epsg,
                "import_polygon_number": a.import_polygon_number,
            }
            for a in config.areas
        ],
        "preplot_lines": [
            {
                "name": p.name,
                "preplot_source_index": p.preplot_source_index,
                "line_style": p.line_style.value,
                "color": p.color,
                "opacity": p.opacity,
                "line_width": p.line_width,
                "dot_radius": p.dot_radius,
                "hidden": p.hidden,
            }
            for p in config.preplot_lines
        ],
        "navplan_lines": [
            {
                "name": n.name,
                "line_style": n.line_style.value,
                "color": n.color,
                "opacity": n.opacity,
                "line_width": n.line_width,
                "dot_radius": n.dot_radius,
                "hidden": n.hidden,
                "navplan_source_indices": list(n.navplan_source_indices),
                "navplan_filter_active": n.navplan_filter_active,
            }
            for n in config.navplan_lines
        ],
        "postplot_lines": [
            {
                "name": p.name,
                "line_style": p.line_style.value,
                "color": p.color,
                "opacity": p.opacity,
                "line_width": p.line_width,
                "dot_radius": p.dot_radius,
                "hidden": p.hidden,
                "data_type": p.data_type.value,
                "sequence_ids": list(p.sequence_ids),
                "sequence_filter_active": p.sequence_filter_active,
            }
            for p in config.postplot_lines
        ],
    }


def _parse_border_style(raw: str) -> LineStyle:
    try:
        style = LineStyle(raw)
    except ValueError:
        return LineStyle.SOLID
    if style not in (LineStyle.SOLID, LineStyle.DASH):
        return LineStyle.SOLID
    return style


def legend_from_dict(data: dict | None) -> LegendConfig:
    if not data:
        return LegendConfig.default()
    areas = []
    for item in data.get("areas", []):
        raw_mode = item.get("coordinate_mode", "survey_perimeter")
        try:
            coordinate_mode = AreaCoordinateMode(raw_mode)
        except ValueError:
            coordinate_mode = AreaCoordinateMode.SURVEY_PERIMETER
        areas.append(
            AreaLegendEntry(
                name=item.get("name", ""),
                border_style=_parse_border_style(item.get("border_style", "solid")),
                color=item.get("color", "#60a5fa"),
                opacity=float(item.get("opacity", 1.0)),
                border_width=float(item.get("border_width", 2.0)),
                hidden=bool(item.get("hidden", False)),
                coordinate_mode=coordinate_mode,
                survey_perimeter_index=int(item.get("survey_perimeter_index", 0)),
                imported_polygon_index=int(item.get("imported_polygon_index", 0)),
                custom_points=[
                    _polygon_point_from_dict(point)
                    for point in item.get("custom_points", [])
                ],
                source_file=str(item.get("source_file", "")),
                source_epsg=str(item.get("source_epsg", "")),
                import_polygon_number=int(item.get("import_polygon_number", 0)),
            )
        )
    imported_counter = 0
    for area in areas:
        if area.source_file and area.custom_points and area.import_polygon_number <= 0:
            imported_counter += 1
            area.import_polygon_number = imported_counter
    preplot_lines = []
    for item in data.get("preplot_lines", []):
        raw_style = item.get("line_style", "solid")
        try:
            line_style = LineStyle(raw_style)
        except ValueError:
            line_style = LineStyle.SOLID
        preplot_lines.append(
            PreplotLegendEntry(
                name=item.get("name", ""),
                preplot_source_index=int(item.get("preplot_source_index", 0)),
                line_style=line_style,
                color=item.get("color", "#f59e0b"),
                opacity=float(item.get("opacity", 1.0)),
                line_width=migrate_line_width_mm(float(item.get("line_width", 0.9))),
                dot_radius=migrate_dot_radius_mm(float(item.get("dot_radius", 3.0))),
                hidden=bool(item.get("hidden", False)),
            )
        )
    navplan_lines = []
    for item in data.get("navplan_lines", []):
        raw_style = item.get("line_style", "solid")
        try:
            line_style = LineStyle(raw_style)
        except ValueError:
            line_style = LineStyle.SOLID
        navplan_lines.append(
            NavplanLegendEntry(
                name=item.get("name", ""),
                line_style=line_style,
                color=item.get("color", "#22c55e"),
                opacity=float(item.get("opacity", 1.0)),
                line_width=migrate_line_width_mm(float(item.get("line_width", 0.9))),
                dot_radius=migrate_dot_radius_mm(float(item.get("dot_radius", 3.0))),
                hidden=bool(item.get("hidden", False)),
                navplan_source_indices=[
                    int(index) for index in item.get("navplan_source_indices", [])
                ],
                navplan_filter_active=bool(
                    item.get(
                        "navplan_filter_active",
                        bool(item.get("navplan_source_indices")),
                    )
                ),
            )
        )
    lines = []
    for item in data.get("postplot_lines", []):
        raw_style = item.get("line_style", "solid")
        try:
            line_style = LineStyle(raw_style)
        except ValueError:
            line_style = LineStyle.SOLID
        raw_data_type = item.get("data_type", "source")
        try:
            data_type = NavDataType(raw_data_type)
        except ValueError:
            data_type = NavDataType.SOURCE
        lines.append(
            PostplotLegendEntry(
                name=item.get("name", ""),
                line_style=line_style,
                color=item.get("color", "#ef4444"),
                opacity=float(item.get("opacity", 1.0)),
                line_width=migrate_line_width_mm(float(item.get("line_width", 1.2))),
                dot_radius=migrate_dot_radius_mm(float(item.get("dot_radius", 3.0))),
                hidden=bool(item.get("hidden", False)),
                data_type=data_type,
                sequence_ids=list(item.get("sequence_ids", [])),
                sequence_filter_active=bool(
                    item.get(
                        "sequence_filter_active",
                        bool(item.get("sequence_ids")),
                    )
                ),
            )
        )
    if not areas and not preplot_lines and not navplan_lines and not lines:
        return LegendConfig.default()
    return LegendConfig(
        areas=areas,
        preplot_lines=preplot_lines,
        navplan_lines=navplan_lines,
        postplot_lines=lines or LegendConfig.default().postplot_lines,
    )
