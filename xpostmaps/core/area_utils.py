"""Resolve legend area polygons for map rendering."""

from __future__ import annotations

from xpostmaps.core.models import (
    AreaCoordinateMode,
    AreaLegendEntry,
    MapData,
    PolygonPoint,
    SurveyPerimeter,
)


def perimeter_label_count(perimeter_count: int) -> int:
    if perimeter_count >= 2:
        return perimeter_count
    if perimeter_count == 1:
        return 1
    return 0


def polygon_source_dropdown_labels(
    perimeter_count: int,
    imported_count: int,
) -> list[str]:
    """Build Polygon Source column options for the legend area table."""
    labels: list[str] = []
    if perimeter_count >= 2:
        labels.extend(
            f"Survey Perimeter {index}" for index in range(1, perimeter_count + 1)
        )
    elif perimeter_count == 1:
        labels.append("Survey Perimeter")

    for index in range(1, imported_count + 1):
        labels.append(f"Imported Polygon {index}")

    labels.append("Custom")
    return labels


def custom_source_index(perimeter_count: int, imported_count: int) -> int:
    return len(polygon_source_dropdown_labels(perimeter_count, imported_count)) - 1


def polygon_source_from_index(
    index: int,
    perimeter_count: int,
    imported_count: int,
) -> tuple[AreaCoordinateMode, int, int]:
    """Map dropdown index to coordinate mode and perimeter/import indices."""
    if index >= custom_source_index(perimeter_count, imported_count):
        return AreaCoordinateMode.CUSTOM, 0, 0

    perimeter_labels = perimeter_label_count(perimeter_count)
    if index < perimeter_labels:
        if perimeter_count >= 2:
            return AreaCoordinateMode.SURVEY_PERIMETER, index, 0
        return AreaCoordinateMode.SURVEY_PERIMETER, 0, 0

    imported_index = index - perimeter_labels
    if imported_index < imported_count:
        return AreaCoordinateMode.IMPORTED, 0, imported_index

    return AreaCoordinateMode.CUSTOM, 0, 0


def polygon_source_index_from_selection(
    mode: AreaCoordinateMode,
    perimeter_index: int,
    imported_index: int,
    perimeter_count: int,
    imported_count: int,
) -> int:
    if mode == AreaCoordinateMode.CUSTOM:
        return custom_source_index(perimeter_count, imported_count)
    if mode == AreaCoordinateMode.IMPORTED:
        return perimeter_label_count(perimeter_count) + imported_index
    if perimeter_count >= 2:
        return min(max(perimeter_index, 0), perimeter_count - 1)
    return 0


# Legacy aliases used during migration
coordinate_dropdown_labels = polygon_source_dropdown_labels
custom_coordinate_index = custom_source_index
coord_selection_from_index = polygon_source_from_index
coord_index_from_selection = polygon_source_index_from_selection


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


def imported_polygon_by_index(
    legend_areas: list[AreaLegendEntry] | None,
    imported_index: int,
) -> AreaLegendEntry | None:
    if legend_areas is None:
        return None
    from xpostmaps.core.polygon_import_service import imported_polygon_entries

    imported = imported_polygon_entries(legend_areas)
    if 0 <= imported_index < len(imported):
        return imported[imported_index]
    return None


def resolve_area_polygon(
    entry: AreaLegendEntry,
    map_data: MapData | None,
    legend_areas: list[AreaLegendEntry] | None = None,
) -> tuple[list[float], list[float]]:
    if entry.coordinate_mode == AreaCoordinateMode.CUSTOM:
        return custom_polygon_xy(entry.custom_points)

    if entry.coordinate_mode == AreaCoordinateMode.IMPORTED:
        imported = imported_polygon_by_index(legend_areas, entry.imported_polygon_index)
        if imported is None:
            return [], []
        return custom_polygon_xy(imported.custom_points)

    perimeter = survey_perimeter_by_index(map_data, entry.survey_perimeter_index)
    if perimeter is None and map_data is not None and len(map_data.survey_perimeters) == 1:
        perimeter = map_data.survey_perimeters[0]
    if perimeter is None:
        perimeter = find_survey_perimeter(entry.name, map_data)
    if perimeter is None:
        return [], []
    return list(perimeter.xs), list(perimeter.ys)
