"""Parse polygon geometry from KML, CSV, and shapefile sources."""

from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from xpostmaps.core.crs_utils import WGS84_EPSG, epsg_from_prj_path, normalize_epsg

POLYGON_EXTENSIONS = frozenset({".kml", ".csv", ".shp"})


@dataclass
class ImportedPolygon:
    name: str
    source_file: str
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)
    source_epsg: str = ""
    is_geographic: bool = False


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


_COORD_TOL = 1e-7


def _points_close(
    a: tuple[float, float],
    b: tuple[float, float],
    tol: float = _COORD_TOL,
) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _parse_coord_text(text: str) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for token in re.split(r"[\s]+", text.strip()):
        if not token:
            continue
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            continue
        if x == x and y == y:
            xs.append(x)
            ys.append(y)
    return xs, ys


def _placemark_name(placemark: ET.Element) -> str:
    for child in placemark:
        if _local_tag(child.tag) == "name" and child.text:
            return child.text.strip()
    return ""


def _element_name(elem: ET.Element) -> str:
    for child in elem:
        if _local_tag(child.tag) == "name" and child.text:
            return child.text.strip()
    return ""


def _child_placemarks(container: ET.Element) -> list[ET.Element]:
    return [child for child in container if _local_tag(child.tag) == "Placemark"]


def _ring_coords(elem: ET.Element) -> tuple[list[float], list[float]]:
    for child in elem.iter():
        if _local_tag(child.tag) == "coordinates" and child.text:
            return _parse_coord_text(child.text)
    return [], []


def _placemark_polygons(placemark: ET.Element) -> list[tuple[list[float], list[float]]]:
    rings: list[tuple[list[float], list[float]]] = []
    for elem in placemark.iter():
        if _local_tag(elem.tag) != "Polygon":
            continue
        xs, ys = _ring_coords(elem)
        if len(xs) >= 3:
            rings.append((xs, ys))
    return rings


def _placemark_linestring_segments(
    placemark: ET.Element,
) -> list[tuple[list[float], list[float]]]:
    segments: list[tuple[list[float], list[float]]] = []
    for elem in placemark.iter():
        if _local_tag(elem.tag) != "LineString":
            continue
        xs, ys = _ring_coords(elem)
        if len(xs) >= 2:
            segments.append((xs, ys))
    return segments


def _closed_linestring_ring(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]] | None:
    if len(xs) < 3:
        return None
    ring_x = list(xs)
    ring_y = list(ys)
    if not _points_close((ring_x[0], ring_y[0]), (ring_x[-1], ring_y[-1])):
        ring_x.append(ring_x[0])
        ring_y.append(ring_y[0])
    if _points_close((ring_x[0], ring_y[0]), (ring_x[-1], ring_y[-1])):
        if len(ring_x) >= 4:
            ring_x = ring_x[:-1]
            ring_y = ring_y[:-1]
        if len(ring_x) >= 3:
            return ring_x, ring_y
    return None


def _stitch_line_segments(
    segments: list[tuple[list[float], list[float]]],
) -> tuple[list[float], list[float]]:
    """Chain line segments sharing endpoints into one closed ring."""
    edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for xs, ys in segments:
        for index in range(len(xs) - 1):
            edges.append(((xs[index], ys[index]), (xs[index + 1], ys[index + 1])))

    if len(edges) < 3:
        return [], []

    used = [False] * len(edges)
    start = edges[0][0]
    current = edges[0][1]
    chain_x = [start[0], current[0]]
    chain_y = [start[1], current[1]]
    used[0] = True
    added = 1

    while added < len(edges):
        found = False
        for index, (point_a, point_b) in enumerate(edges):
            if used[index]:
                continue
            if _points_close(current, point_a):
                current = point_b
            elif _points_close(current, point_b):
                current = point_a
            else:
                continue
            chain_x.append(current[0])
            chain_y.append(current[1])
            used[index] = True
            added += 1
            found = True
            break
        if not found:
            return [], []

    if not _points_close((chain_x[0], chain_y[0]), (chain_x[-1], chain_y[-1])):
        return [], []

    if len(chain_x) >= 4:
        chain_x = chain_x[:-1]
        chain_y = chain_y[:-1]
    if len(chain_x) >= 3:
        return chain_x, chain_y
    return [], []


def _append_polygon(
    results: list[ImportedPolygon],
    path: Path,
    name: str,
    xs: list[float],
    ys: list[float],
) -> None:
    results.append(
        ImportedPolygon(
            name=name,
            source_file=path.name,
            xs=xs,
            ys=ys,
            source_epsg=WGS84_EPSG,
            is_geographic=True,
        )
    )


def parse_kml(path: Path) -> list[ImportedPolygon]:
    """Parse polygon rings from a KML file (WGS84 geographic)."""
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []

    root = tree.getroot()
    results: list[ImportedPolygon] = []

    for elem in root.iter():
        if _local_tag(elem.tag) != "Placemark":
            continue
        base_name = _placemark_name(elem) or path.stem
        rings = _placemark_polygons(elem)
        if rings:
            for index, (xs, ys) in enumerate(rings):
                name = base_name if len(rings) == 1 else f"{base_name} ({index + 1})"
                _append_polygon(results, path, name, xs, ys)
            continue

        line_rings: list[tuple[list[float], list[float]]] = []
        for segment_xs, segment_ys in _placemark_linestring_segments(elem):
            ring = _closed_linestring_ring(segment_xs, segment_ys)
            if ring is not None:
                line_rings.append(ring)
        for index, (xs, ys) in enumerate(line_rings):
            name = base_name if len(line_rings) == 1 else f"{base_name} ({index + 1})"
            _append_polygon(results, path, name, xs, ys)

    for elem in root.iter():
        if _local_tag(elem.tag) != "Folder":
            continue
        placemarks = _child_placemarks(elem)
        if not placemarks:
            continue
        if any(_placemark_polygons(placemark) for placemark in placemarks):
            continue

        segments: list[tuple[list[float], list[float]]] = []
        for placemark in placemarks:
            segments.extend(_placemark_linestring_segments(placemark))
        xs, ys = _stitch_line_segments(segments)
        if len(xs) >= 3:
            _append_polygon(results, path, _element_name(elem) or path.stem, xs, ys)

    return results


def _shapefile_name(reader, index: int, fallback: str) -> str:
    try:
        record = reader.record(index)
    except Exception:
        return fallback
    for value in record:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def parse_shp(path: Path) -> list[ImportedPolygon]:
    """Parse polygon shapes from an ESRI shapefile."""
    try:
        import shapefile
    except ImportError:
        return []

    prj_epsg = epsg_from_prj_path(path.with_suffix(".prj"))
    is_geographic = prj_epsg == WGS84_EPSG or not prj_epsg

    try:
        reader = shapefile.Reader(str(path))
    except Exception:
        return []

    polygon_types = {
        shapefile.POLYGON,
        shapefile.POLYGONZ,
        shapefile.POLYGONM,
    }
    results: list[ImportedPolygon] = []
    for index, shape in enumerate(reader.shapes()):
        if shape.shapeType not in polygon_types:
            continue
        parts = list(shape.parts) + [len(shape.points)]
        for part_idx in range(len(shape.parts)):
            start = shape.parts[part_idx]
            end = parts[part_idx + 1]
            ring = shape.points[start:end]
            xs = [float(p[0]) for p in ring]
            ys = [float(p[1]) for p in ring]
            if len(xs) < 3:
                continue
            base_name = _shapefile_name(reader, index, path.stem)
            part_count = len(shape.parts)
            name = base_name if part_count == 1 else f"{base_name} ({part_idx + 1})"
            results.append(
                ImportedPolygon(
                    name=name,
                    source_file=path.name,
                    xs=xs,
                    ys=ys,
                    source_epsg=prj_epsg,
                    is_geographic=is_geographic,
                )
            )
    return results


_EASTING_KEYS = frozenset({"easting", "east", "e", "x", "lon", "longitude", "long"})
_NORTHING_KEYS = frozenset({"northing", "north", "n", "y", "lat", "latitude"})
_NAME_KEYS = frozenset({"name", "area", "polygon", "label", "description"})


def _header_index(headers: list[str], keys: frozenset[str]) -> int | None:
    for index, header in enumerate(headers):
        if header.strip().lower() in keys:
            return index
    return None


def _looks_geographic(xs: list[float], ys: list[float]) -> bool:
    if not xs or not ys:
        return False
    max_abs_x = max(abs(v) for v in xs)
    max_abs_y = max(abs(v) for v in ys)
    return max_abs_x <= 180.0 and max_abs_y <= 90.0


def parse_csv(path: Path) -> list[ImportedPolygon]:
    """Parse polygon vertices from CSV (column layout auto-detected)."""
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().has_header(sample)
            except csv.Error:
                dialect = False
            reader = csv.reader(handle)
            rows = [row for row in reader if any(cell.strip() for cell in row)]
    except OSError:
        return []

    if not rows:
        return []

    headers: list[str] = []
    data_rows = rows
    if dialect:
        headers = [cell.strip().lower() for cell in rows[0]]
        data_rows = rows[1:]

    x_idx: int | None = None
    y_idx: int | None = None
    name_idx: int | None = None
    if headers:
        east_idx = _header_index(headers, _EASTING_KEYS)
        north_idx = _header_index(headers, _NORTHING_KEYS)
        if east_idx is not None and north_idx is not None:
            x_idx, y_idx = east_idx, north_idx
        name_idx = _header_index(headers, _NAME_KEYS)

    grouped: dict[str, tuple[list[float], list[float]]] = {}
    default_key = path.stem

    for row in data_rows:
        if not row:
            continue
        try:
            if x_idx is not None and y_idx is not None and max(x_idx, y_idx) < len(row):
                x = float(str(row[x_idx]).replace(",", "").strip())
                y = float(str(row[y_idx]).replace(",", "").strip())
            elif len(row) >= 2:
                x = float(str(row[0]).replace(",", "").strip())
                y = float(str(row[1]).replace(",", "").strip())
            else:
                continue
        except ValueError:
            continue
        if x != x or y != y:
            continue

        group_name = default_key
        if name_idx is not None and name_idx < len(row) and row[name_idx].strip():
            group_name = row[name_idx].strip()
        bucket = grouped.setdefault(group_name, ([], []))
        bucket[0].append(x)
        bucket[1].append(y)

    if not grouped:
        return []

    geographic = _looks_geographic(
        [x for xs, _ in grouped.values() for x in xs],
        [y for _, ys in grouped.values() for y in ys],
    )
    results: list[ImportedPolygon] = []
    for name, (xs, ys) in grouped.items():
        if len(xs) < 3:
            continue
        results.append(
            ImportedPolygon(
                name=name,
                source_file=path.name,
                xs=xs,
                ys=ys,
                source_epsg="",
                is_geographic=geographic,
            )
        )
    return results


def parse_polygon_file(path: Path) -> list[ImportedPolygon]:
    suffix = path.suffix.lower()
    if suffix == ".kml":
        return parse_kml(path)
    if suffix == ".shp":
        return parse_shp(path)
    if suffix == ".csv":
        return parse_csv(path)
    return []


def collect_polygon_paths(paths: list[Path]) -> list[Path]:
    """Expand directories and filter to supported polygon files."""
    collected: list[Path] = []
    for path in paths:
        if path.is_dir():
            for candidate in sorted(path.rglob("*")):
                if candidate.is_file() and candidate.suffix.lower() in POLYGON_EXTENSIONS:
                    collected.append(candidate)
        elif path.is_file() and path.suffix.lower() in POLYGON_EXTENSIONS:
            collected.append(path)
    unique: dict[str, Path] = {}
    for path in collected:
        unique[str(path.resolve())] = path
    return sorted(unique.values(), key=lambda p: p.name.lower())


def parse_polygon_paths(paths: list[Path]) -> list[ImportedPolygon]:
    polygons: list[ImportedPolygon] = []
    for path in collect_polygon_paths(paths):
        polygons.extend(parse_polygon_file(path))
    return polygons
