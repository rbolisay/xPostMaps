"""Legend config serialization helpers."""

from __future__ import annotations

from xpostmaps.core.models import (
    AreaCoordinateMode,
    AreaLegendEntry,
    LegendConfig,
    LineStyle,
    NavDataType,
    PolygonPoint,
    PostplotLegendEntry,
)


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
                "coordinate_mode": a.coordinate_mode.value,
                "survey_perimeter_index": a.survey_perimeter_index,
                "custom_points": [_polygon_point_to_dict(p) for p in a.custom_points],
            }
            for a in config.areas
        ],
        "postplot_lines": [
            {
                "name": p.name,
                "line_style": p.line_style.value,
                "color": p.color,
                "opacity": p.opacity,
                "data_type": p.data_type.value,
                "sequence_ids": list(p.sequence_ids),
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
                coordinate_mode=coordinate_mode,
                survey_perimeter_index=int(item.get("survey_perimeter_index", 0)),
                custom_points=[
                    _polygon_point_from_dict(point)
                    for point in item.get("custom_points", [])
                ],
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
                data_type=data_type,
                sequence_ids=list(item.get("sequence_ids", [])),
            )
        )
    if not areas and not lines:
        return LegendConfig.default()
    return LegendConfig(
        areas=areas or LegendConfig.default().areas,
        postplot_lines=lines or LegendConfig.default().postplot_lines,
    )
