"""Export Layer Styles rows to shapefiles (map CRS), KML (WGS84), and DXF (map CRS).

Each Layer Styles row becomes one output file. Line layers (preplot, navplan,
postplot) are written as polylines and area layers as polygons. The dotted
on-screen style is a cartographic choice only; the underlying survey data is a
line of shots, so it is exported as line geometry (one feature per segment)
rather than one point feature per shot. That keeps the files compact and fast.
"""

from __future__ import annotations

import re
import xml.sax.saxutils
from dataclasses import dataclass, field
from pathlib import Path

from xpostmaps.core.area_utils import resolve_area_polygon
from xpostmaps.core.crs_utils import WGS84_EPSG, normalize_epsg
from xpostmaps.core.models import (
    LegendConfig,
    LineSegment,
    MapData,
    NavDataType,
    PostplotLegendEntry,
    RecordType,
    sequence_id_matches,
)
from xpostmaps.core.navplan_catalog_utils import (
    resolve_navplan_file_order,
    segments_for_navplan_source,
)
from xpostmaps.core.pdf_export import LegendLayerSpec, iter_legend_layer_specs, legend_with_only_layer
from xpostmaps.core.polygon_import_service import non_imported_polygon_entries
from xpostmaps.core.preplot_catalog_utils import (
    resolve_preplot_file_order,
    segments_for_preplot_source,
)

_INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


@dataclass
class LayerGeometry:
    polylines: list[tuple[list[float], list[float]]] = field(default_factory=list)
    polygons: list[tuple[list[float], list[float]]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.polylines and not self.polygons


def sanitize_export_stem(text: str, *, fallback: str = "layer") -> str:
    cleaned = _INVALID_PATH_CHARS.sub("_", text.strip())
    cleaned = cleaned.strip(" .")
    return cleaned or fallback


def layer_export_filename(spec: LegendLayerSpec) -> str:
    section = sanitize_export_stem(spec.section.title(), fallback="Layer")
    name = sanitize_export_stem(spec.name, fallback="Unnamed")
    return f"{section}_{name}"


def resolve_map_epsg(map_data: MapData | None) -> str:
    if map_data is None:
        return ""
    return normalize_epsg(map_data.postmap_info.epsg_code)


def _record_type_for_data_type(data_type: NavDataType) -> RecordType:
    return RecordType.VESSEL if data_type == NavDataType.VESSEL else RecordType.SOURCE


def _segment_matches_postplot_entry(
    segment: LineSegment,
    entry: PostplotLegendEntry,
) -> bool:
    if entry.hidden:
        return False
    if segment.record_type in (RecordType.OVERLAY, RecordType.PREPLOT, RecordType.NAVPLAN):
        return False
    required = _record_type_for_data_type(entry.data_type)
    if segment.record_type in (RecordType.SOURCE, RecordType.VESSEL) and segment.record_type != required:
        return False
    if not entry.sequence_filter_active or not entry.sequence_ids:
        return False
    if not segment.sequence_id:
        return False
    return sequence_id_matches(segment.sequence_id, entry.sequence_ids)


def _append_segment_geometry(geometry: LayerGeometry, segment: LineSegment) -> None:
    if not segment.xs or len(segment.xs) != len(segment.ys):
        return
    coords = [
        (float(x), float(y))
        for x, y in zip(segment.xs, segment.ys)
        if x == x and y == y
    ]
    if len(coords) < 2:
        return
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    geometry.polylines.append((xs, ys))


def _close_ring(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    if len(xs) < 3:
        return xs, ys
    if xs[0] != xs[-1] or ys[0] != ys[-1]:
        return xs + [xs[0]], ys + [ys[0]]
    return xs, ys


def collect_layer_geometry(
    spec: LegendLayerSpec,
    legend: LegendConfig,
    map_data: MapData | None,
) -> LayerGeometry:
    """Collect map geometry for one Layer Styles row."""
    if map_data is None:
        return LayerGeometry()

    cfg = legend_with_only_layer(legend, spec)
    geometry = LayerGeometry()

    if spec.section == "area":
        areas = non_imported_polygon_entries(cfg.areas)
        if spec.index < 0 or spec.index >= len(areas):
            return geometry
        entry = areas[spec.index]
        xs, ys = resolve_area_polygon(entry, map_data, cfg.areas)
        if len(xs) >= 3:
            ring_x, ring_y = _close_ring(list(xs), list(ys))
            geometry.polygons.append((ring_x, ring_y))
        return geometry

    if spec.section == "preplot":
        if spec.index < 0 or spec.index >= len(cfg.preplot_lines):
            return geometry
        entry = cfg.preplot_lines[spec.index]
        segments = segments_for_preplot_source(
            map_data.preplot_segments,
            resolve_preplot_file_order(map_data),
            entry.preplot_source_index,
        )
        for segment in segments:
            _append_segment_geometry(geometry, segment)
        return geometry

    if spec.section == "navplan":
        if spec.index < 0 or spec.index >= len(cfg.navplan_lines):
            return geometry
        entry = cfg.navplan_lines[spec.index]
        file_paths = resolve_navplan_file_order(map_data)
        segments: list[LineSegment] = []
        for source_index in entry.navplan_source_indices:
            segments.extend(
                segments_for_navplan_source(
                    map_data.navplan_segments,
                    file_paths,
                    source_index,
                )
            )
        for segment in segments:
            _append_segment_geometry(geometry, segment)
        return geometry

    if spec.section == "postplot":
        if spec.index < 0 or spec.index >= len(cfg.postplot_lines):
            return geometry
        entry = cfg.postplot_lines[spec.index]
        for segment in map_data.segments:
            if _segment_matches_postplot_entry(segment, entry):
                _append_segment_geometry(geometry, segment)
        return geometry

    return geometry


def _write_prj(path: Path, epsg: str) -> None:
    code = normalize_epsg(epsg)
    if not code:
        return
    from pyproj import CRS

    prj_path = path.with_suffix(".prj")
    prj_path.write_text(CRS.from_epsg(int(code)).to_wkt(), encoding="utf-8")


def _write_shapefile(
    path: Path,
    geometry: LayerGeometry,
    *,
    layer_name: str,
    section: str,
    epsg: str,
) -> None:
    import shapefile

    writer = shapefile.Writer(str(path))
    writer.autoBalance = 1
    writer.field("name", "C", 120)
    writer.field("section", "C", 40)

    for xs, ys in geometry.polylines:
        writer.line([list(zip(xs, ys))])
        writer.record(layer_name, section)

    for xs, ys in geometry.polygons:
        writer.poly([list(zip(xs, ys))])
        writer.record(layer_name, section)

    writer.close()
    _write_prj(path, epsg)


def _make_transformer(source_epsg: str, target_epsg: str):
    src = normalize_epsg(source_epsg)
    dst = normalize_epsg(target_epsg)
    if not src or not dst or src == dst:
        return None
    from pyproj import Transformer

    return Transformer.from_crs(f"EPSG:{src}", f"EPSG:{dst}", always_xy=True)


def _coords_to_kml(xs: list[float], ys: list[float], transformer) -> str:
    if transformer is not None:
        tx, ty = transformer.transform(xs, ys)
    else:
        tx, ty = xs, ys
    return " ".join(f"{lon:.8f},{lat:.8f},0" for lon, lat in zip(tx, ty))


def _write_kml(
    path: Path,
    geometry: LayerGeometry,
    *,
    layer_name: str,
    section: str,
    source_epsg: str,
) -> None:
    transformer = _make_transformer(source_epsg, WGS84_EPSG)
    placemarks: list[str] = []
    title = xml.sax.saxutils.escape(layer_name)
    section_text = xml.sax.saxutils.escape(section)

    for xs, ys in geometry.polylines:
        coords = _coords_to_kml(xs, ys, transformer)
        if not coords:
            continue
        placemarks.append(
            "<Placemark>"
            f"<name>{title}</name>"
            f"<description>{section_text} line</description>"
            "<LineString><tessellate>1</tessellate>"
            f"<coordinates>{coords}</coordinates>"
            "</LineString></Placemark>"
        )

    for xs, ys in geometry.polygons:
        coords = _coords_to_kml(xs, ys, transformer)
        if not coords:
            continue
        placemarks.append(
            "<Placemark>"
            f"<name>{title}</name>"
            f"<description>{section_text} polygon</description>"
            "<Polygon><outerBoundaryIs><LinearRing>"
            f"<coordinates>{coords}</coordinates>"
            "</LinearRing></outerBoundaryIs></Polygon></Placemark>"
        )

    body = "\n".join(placemarks)
    kml_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "<Document>\n"
        f"<name>{title}</name>\n"
        f"{body}\n"
        "</Document>\n"
        "</kml>\n"
    )
    path.write_text(kml_text, encoding="utf-8")


def _write_dxf(
    path: Path,
    geometry: LayerGeometry,
    *,
    layer_name: str,
) -> None:
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    dxf_layer = sanitize_export_stem(layer_name, fallback="Layer")[:255]
    if dxf_layer not in doc.layers:
        doc.layers.add(dxf_layer)

    for xs, ys in geometry.polylines:
        msp.add_lwpolyline(
            list(zip(xs, ys)),
            dxfattribs={"layer": dxf_layer},
        )

    for xs, ys in geometry.polygons:
        msp.add_lwpolyline(
            list(zip(xs, ys)),
            close=True,
            dxfattribs={"layer": dxf_layer},
        )

    doc.saveas(str(path))


def export_layers(
    output_dir: Path,
    pdf_stem: str,
    legend: LegendConfig,
    map_data: MapData | None,
    *,
    shapefiles: bool = False,
    kml: bool = False,
    dxf: bool = False,
    progress_callback=None,
) -> dict[str, list[Path]]:
    """Export every Layer Styles row to the requested formats in a single pass.

    Geometry is collected once per layer and written to all requested formats,
    so enabling multiple formats does not multiply the per-layer cost.
    """
    formats = [name for name, on in (("shp", shapefiles), ("kml", kml), ("dxf", dxf)) if on]
    if not formats:
        return {}

    map_epsg = resolve_map_epsg(map_data)
    if not map_epsg:
        raise ValueError("Map CRS (EPSG) is not set — set the map EPSG before exporting layers.")

    dirs: dict[str, Path] = {}
    stem = sanitize_export_stem(pdf_stem)
    if shapefiles:
        dirs["shp"] = output_dir / f"{stem}_Shapefiles"
    if kml:
        dirs["kml"] = output_dir / f"{stem}_KML"
    if dxf:
        dirs["dxf"] = output_dir / f"{stem}_DXF"
    for target in dirs.values():
        target.mkdir(parents=True, exist_ok=True)

    written: dict[str, list[Path]] = {name: [] for name in formats}
    specs = iter_legend_layer_specs(legend)
    total = len(specs)
    for index, spec in enumerate(specs, start=1):
        if progress_callback is not None:
            progress_callback(index, total, spec.display_name)
        geometry = collect_layer_geometry(spec, legend, map_data)
        if geometry.is_empty:
            continue
        base_name = layer_export_filename(spec)

        if shapefiles:
            out_path = dirs["shp"] / f"{base_name}.shp"
            _write_shapefile(
                out_path,
                geometry,
                layer_name=spec.name,
                section=spec.section,
                epsg=map_epsg,
            )
            written["shp"].append(out_path)

        if kml:
            out_path = dirs["kml"] / f"{base_name}.kml"
            _write_kml(
                out_path,
                geometry,
                layer_name=spec.name,
                section=spec.section,
                source_epsg=map_epsg,
            )
            written["kml"].append(out_path)

        if dxf:
            out_path = dirs["dxf"] / f"{base_name}.dxf"
            _write_dxf(out_path, geometry, layer_name=spec.name)
            written["dxf"].append(out_path)

    return written


def export_layers_to_shapefiles(
    output_dir: Path,
    pdf_stem: str,
    legend: LegendConfig,
    map_data: MapData | None,
    *,
    progress_callback=None,
) -> list[Path]:
    """Write one shapefile per Layer Styles row under ``output_dir``."""
    return export_layers(
        output_dir,
        pdf_stem,
        legend,
        map_data,
        shapefiles=True,
        progress_callback=progress_callback,
    ).get("shp", [])


def export_layers_to_kml(
    output_dir: Path,
    pdf_stem: str,
    legend: LegendConfig,
    map_data: MapData | None,
    *,
    progress_callback=None,
) -> list[Path]:
    """Write one KML file per Layer Styles row under ``output_dir``."""
    return export_layers(
        output_dir,
        pdf_stem,
        legend,
        map_data,
        kml=True,
        progress_callback=progress_callback,
    ).get("kml", [])


def export_layers_to_dxf(
    output_dir: Path,
    pdf_stem: str,
    legend: LegendConfig,
    map_data: MapData | None,
    *,
    progress_callback=None,
) -> list[Path]:
    """Write one DXF file per Layer Styles row under ``output_dir``."""
    return export_layers(
        output_dir,
        pdf_stem,
        legend,
        map_data,
        dxf=True,
        progress_callback=progress_callback,
    ).get("dxf", [])
