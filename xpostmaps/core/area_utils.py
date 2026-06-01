"""Resolve legend area polygons for map rendering."""

from __future__ import annotations

from xpostmaps.core.models import (
    AreaCoordinateMode,
    AreaLegendEntry,
    MapData,
    PolygonPoint,
    SurveyPerimeter,
)


def coordinate_dropdown_labels(perimeter_count: int) -> list[str]:
    """Build Coordinates column options for the legend area table."""
    if perimeter_count >= 2:
        labels = [f"Survey Perimeter {index}" for index in range(1, perimeter_count + 1)]
    else:
        labels = ["Survey Perimeter"]
    labels.append("Custom")
    return labels


def custom_coordinate_index(perimeter_count: int) -> int:
    return len(coordinate_dropdown_labels(perimeter_count)) - 1


def coord_selection_from_index(
    index: int, perimeter_count: int
) -> tuple[AreaCoordinateMode, int]:
    if index >= custom_coordinate_index(perimeter_count):
        return AreaCoordinateMode.CUSTOM, 0
    return AreaCoordinateMode.SURVEY_PERIMETER, index


def coord_index_from_selection(
    mode: AreaCoordinateMode,
    perimeter_index: int,
    perimeter_count: int,
) -> int:
    if mode == AreaCoordinateMode.CUSTOM:
        return custom_coordinate_index(perimeter_count)
    if perimeter_count >= 2:
        return min(max(perimeter_index, 0), perimeter_count - 1)
    return 0


def _normalize_name(value: str) -> str:
    return (
        value.lower()
        .replace(" area", "")
        .replace(" boundary", "")
        .replace(" polygon", "")
        .strip()
    )


def perimeter_matches_area(area_name: str, perimeter: SurveyPerimeter) -> bool:
    area_key = _normalize_name(area_name)
    perimeter_key = _normalize_name(perimeter.name)
    if not area_key or not perimeter_key:
        return False
    return area_key in perimeter_key or perimeter_key in area_key


def find_survey_perimeter(area_name: str, map_data: MapData | None) -> SurveyPerimeter | None:
    if map_data is None or not map_data.survey_perimeters:
        return None
    for perimeter in map_data.survey_perimeters:
        if perimeter_matches_area(area_name, perimeter):
            return perimeter
    return map_data.survey_perimeters[0]


def survey_perimeter_by_index(
    map_data: MapData | None,
    perimeter_index: int,
) -> SurveyPerimeter | None:
    if map_data is None or not map_data.survey_perimeters:
        return None
    if 0 <= perimeter_index < len(map_data.survey_perimeters):
        return map_data.survey_perimeters[perimeter_index]
    return None


def custom_polygon_xy(points: list[PolygonPoint]) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for point in points:
        if point.x == point.x and point.y == point.y and (point.x != 0.0 or point.y != 0.0):
            xs.append(point.x)
            ys.append(point.y)
    if len(xs) >= 3 and (xs[0] != xs[-1] or ys[0] != ys[-1]):
        xs.append(xs[0])
        ys.append(ys[0])
    return xs, ys


def resolve_area_polygon(
    entry: AreaLegendEntry,
    map_data: MapData | None,
) -> tuple[list[float], list[float]]:
    if entry.coordinate_mode == AreaCoordinateMode.CUSTOM:
        return custom_polygon_xy(entry.custom_points)

    perimeter = survey_perimeter_by_index(map_data, entry.survey_perimeter_index)
    if perimeter is None and map_data is not None and len(map_data.survey_perimeters) == 1:
        perimeter = map_data.survey_perimeters[0]
    if perimeter is None:
        perimeter = find_survey_perimeter(entry.name, map_data)
    if perimeter is None:
        return [], []
    return list(perimeter.xs), list(perimeter.ys)
