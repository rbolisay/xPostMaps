"""Tests for Layer Styles shapefile/KML export."""

from __future__ import annotations

from pathlib import Path

import pytest

from xpostmaps.core.layer_file_export import (
    collect_layer_geometry,
    export_layers,
    export_layers_to_dxf,
    export_layers_to_kml,
    export_layers_to_shapefiles,
    layer_export_filename,
    sanitize_export_stem,
)
from xpostmaps.core.models import (
    LegendConfig,
    LineSegment,
    LineStyle,
    MapData,
    PostmapInfo,
    PreplotLegendEntry,
    RecordType,
)
from xpostmaps.core.pdf_export import LegendLayerSpec


def test_sanitize_export_stem() -> None:
    assert sanitize_export_stem('bad/name*') == "bad_name_"
    assert sanitize_export_stem("  ") == "layer"


def test_layer_export_filename() -> None:
    spec = LegendLayerSpec(section="preplot", index=0, name="Main", hidden=False)
    assert layer_export_filename(spec) == "Preplot_Main"


def test_collect_preplot_geometry(tmp_path: Path) -> None:
    legend = LegendConfig.default()
    legend.preplot_lines = [
        PreplotLegendEntry(name="Main", preplot_source_index=0, line_style=LineStyle.SOLID)
    ]
    map_data = MapData(
        preplot_segments=[
            LineSegment(
                line_name="1001",
                record_type=RecordType.PREPLOT,
                xs=[0.0, 100.0, 200.0],
                ys=[0.0, 50.0, 100.0],
                file_name="test.p111",
            )
        ],
        preplot_file_order=["test.p111"],
        postmap_info=PostmapInfo(epsg_code="2193"),
    )
    spec = LegendLayerSpec(section="preplot", index=0, name="Main", hidden=False)
    geometry = collect_layer_geometry(spec, legend, map_data)
    assert len(geometry.polylines) == 1
    assert geometry.polylines[0][0] == [0.0, 100.0, 200.0]


def test_export_shapefiles_and_kml(tmp_path: Path) -> None:
    legend = LegendConfig.default()
    legend.preplot_lines = [
        PreplotLegendEntry(name="Main", preplot_source_index=0, line_style=LineStyle.SOLID)
    ]
    map_data = MapData(
        preplot_segments=[
            LineSegment(
                line_name="1001",
                record_type=RecordType.PREPLOT,
                xs=[500000.0, 500100.0],
                ys=[5900000.0, 5900100.0],
                file_name="test.p111",
            )
        ],
        preplot_file_order=["test.p111"],
        postmap_info=PostmapInfo(epsg_code="2193"),
    )

    shp_paths = export_layers_to_shapefiles(
        tmp_path,
        "postmap",
        legend,
        map_data,
    )
    assert len(shp_paths) == 1
    assert shp_paths[0].exists()
    assert shp_paths[0].with_suffix(".shp").exists()
    assert shp_paths[0].with_suffix(".prj").exists()

    kml_paths = export_layers_to_kml(
        tmp_path,
        "postmap",
        legend,
        map_data,
    )
    assert len(kml_paths) == 1
    text = kml_paths[0].read_text(encoding="utf-8")
    assert "<LineString>" in text
    assert "coordinates" in text

    dxf_paths = export_layers_to_dxf(
        tmp_path,
        "postmap",
        legend,
        map_data,
    )
    assert len(dxf_paths) == 1
    assert dxf_paths[0].exists()
    assert dxf_paths[0].suffix == ".dxf"


def test_export_layers_single_pass_all_formats(tmp_path: Path) -> None:
    legend = LegendConfig.default()
    legend.preplot_lines = [
        PreplotLegendEntry(name="Main", preplot_source_index=0, line_style=LineStyle.SOLID)
    ]
    map_data = MapData(
        preplot_segments=[
            LineSegment(
                line_name="1001",
                record_type=RecordType.PREPLOT,
                xs=[500000.0, 500100.0],
                ys=[5900000.0, 5900100.0],
                file_name="test.p111",
            )
        ],
        preplot_file_order=["test.p111"],
        postmap_info=PostmapInfo(epsg_code="2193"),
    )
    written = export_layers(
        tmp_path,
        "postmap",
        legend,
        map_data,
        shapefiles=True,
        kml=True,
        dxf=True,
    )
    assert len(written["shp"]) == 1
    assert len(written["kml"]) == 1
    assert len(written["dxf"]) == 1


def test_dotted_postplot_exports_as_polyline(tmp_path: Path) -> None:
    from xpostmaps.core.models import NavDataType, PostplotLegendEntry
    from xpostmaps.core.models import make_sequence_id

    seq_id = make_sequence_id("nav.p190", "1001", "1001", RecordType.SOURCE)
    legend = LegendConfig.default()
    legend.postplot_lines = [
        PostplotLegendEntry(
            name="Up Line",
            line_style=LineStyle.DOTTED,
            data_type=NavDataType.SOURCE,
            sequence_ids=[seq_id],
            sequence_filter_active=True,
        )
    ]
    map_data = MapData(
        segments=[
            LineSegment(
                line_name="1001",
                record_type=RecordType.SOURCE,
                xs=[500000.0, 500050.0, 500100.0],
                ys=[5900000.0, 5900050.0, 5900100.0],
                file_name="nav.p190",
                sequence_id=seq_id,
            )
        ],
        postmap_info=PostmapInfo(epsg_code="2193"),
    )
    spec = LegendLayerSpec(section="postplot", index=0, name="Up Line", hidden=False)
    geometry = collect_layer_geometry(spec, legend, map_data)
    assert len(geometry.polylines) == 1
    assert len(geometry.polylines[0][0]) == 3


def test_export_shapefiles_requires_epsg(tmp_path: Path) -> None:
    legend = LegendConfig.default()
    map_data = MapData()
    with pytest.raises(ValueError, match="EPSG"):
        export_layers_to_shapefiles(tmp_path, "postmap", legend, map_data)
