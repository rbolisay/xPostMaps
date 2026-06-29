from pathlib import Path
import math
from unittest.mock import patch

from xpostmaps.core.coord_format import (
    dms_compact_to_decimal,
    format_dd_mm,
    format_geo_display,
    GeoDisplayFormatter,
)
from xpostmaps.core.crs_utils import geographic_epsg_from_map, transform_coordinates
from xpostmaps.core.legend_utils import legend_from_dict, legend_to_dict
from xpostmaps.core.database import Database
from xpostmaps.core.models import (
    ConditionalColorRule,
    LegendConfig,
    MapData,
    PositionRecord,
    PostplotLegendEntry,
    ProjectSettings,
    RecordType,
)
from xpostmaps.core.postplot_4d_diff import (
    BaselineShotpoint,
    Postplot4DDiffRow,
    _generate_preplot_shotpoints,
    _read_preplot_generation_info,
    _read_preplot_header_info,
    compute_postplot_4d_diff_rows,
    parse_number_of_sources,
    parse_p111_gun_array_offset_m,
    parse_p190_source_offset_m,
    parse_shotpoint_interval_m,
    parse_source_separation_m,
    resolve_line_azimuth_degrees,
    source_shotpoints_for_match,
)
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.parsers.p111_parser import (
    average_receiver_feathers_by_shotpoint,
    parse_p111_receiver_feathers,
    parse_p111_file,
    scan_projected_axis_order,
)
from xpostmaps.parsers.p190_parser import parse_p190_file
from xpostmaps.parsers.preplot_parser import parse_preplot_file
from xpostmaps.ui.main_window import MainWindow


def test_decimal_lat_lon_formats_to_dd_mm() -> None:
    assert format_dd_mm(59.60086832, is_latitude=True) == "59 36.05 N"
    assert format_dd_mm(1.1701019, is_latitude=False) == "1 10.21 E"


def test_dms_compact_parses_navplan_style_values() -> None:
    lat = dms_compact_to_decimal("593603.13N")
    lon = dms_compact_to_decimal("011012.37E")
    assert lat is not None and abs(lat - 59.600869) < 0.001
    assert lon is not None and abs(lon - 1.170103) < 0.001
    assert format_dd_mm(lat, is_latitude=True) == "59 36.05 N"
    assert format_dd_mm(lon, is_latitude=False) == "1 10.21 E"


def test_format_geo_display_uses_decimal_strings() -> None:
    assert format_geo_display("59.60086832", 0.0, is_latitude=True) == "59 36.05 N"
    assert format_geo_display("1.1701019", 0.0, is_latitude=False) == "1 10.21 E"


def test_format_geo_from_projected_round_trips_projected() -> None:
    from xpostmaps.core.coord_format import format_geo_from_projected

    fmt = GeoDisplayFormatter("2193")
    assert fmt.geographic_epsg == "4167"
    x, y = 1623841.7, 5606835.5
    lat = format_geo_from_projected(x, y, is_latitude=True, formatter=fmt)
    lon = format_geo_from_projected(x, y, is_latitude=False, formatter=fmt)
    assert lat == "39 41.28 S"
    assert lon == "173 16.68 E"
    geo_epsg = geographic_epsg_from_map("2193")
    lons, lats = transform_coordinates([x], [y], "2193", geo_epsg)
    xs, ys = transform_coordinates(lons, lats, geo_epsg, "2193")
    assert abs(xs[0] - x) < 0.001
    assert abs(ys[0] - y) < 0.001


def test_geographic_epsg_from_map_pairs_projected_crs() -> None:
    assert geographic_epsg_from_map("2193") == "4167"
    assert geographic_epsg_from_map("23031") == "4230"
    assert geographic_epsg_from_map("4326") == "4326"


def test_shotpoint_interval_parser_handles_sample_header_styles() -> None:
    assert parse_shotpoint_interval_m(
        "CC,1,0,0,SHOT POINT INTERVAL       16.667 m"
    ) == 16.667
    assert parse_shotpoint_interval_m("H2600SHOT POINT INTERVAL       25.0 m") == 25.0
    assert parse_shotpoint_interval_m("H2600SHOT INTERVAL ...........: 25.0000") == 25.0
    assert parse_shotpoint_interval_m("H2600 SHOT POINT INTERVAL.....: 25.000000") == 25.0
    assert parse_shotpoint_interval_m("H2600STREAMER SEPARATION       112.50 m") is None
    assert parse_shotpoint_interval_m("H2600SHOT INCREMENT ..........: 1") is None


def test_preplot_source_header_parsers_handle_sample_styles() -> None:
    assert parse_number_of_sources("H2600NUMBER OF SOURCES......: 3") == 3
    assert parse_number_of_sources("CC,1,0,0,NUMBER OF SOURCES      2") == 2
    assert parse_source_separation_m("H2600SOURCE SEPARATION       50.00 m") == 50.0
    assert parse_source_separation_m("CC,1,0,0,SOURCE SEPARATION      37.50 m") == 37.5
    assert parse_p190_source_offset_m(
        "H0900 OFFSET REF. TO SOURCE 1      1   1    37.5       0"
    ) == (1, 37.5)
    assert parse_p190_source_offset_m(
        "H0900 OFFSET REF. TO SOURCE 3      1   3   -37.5       0"
    ) == (3, -37.5)
    assert parse_p190_source_offset_m(
        "H0900 OFFSET REF TO SOURCE G03      1   3   -3.75E+01       +0.0"
    ) == (3, -37.5)
    assert parse_p190_source_offset_m(
        "H0900 OFFSET REF. TO STREAMER 1      1   1   618.75       0"
    ) is None
    assert parse_p111_gun_array_offset_m(
        "HC,2,3,0,Gun Array 1,101,G1,4,Air Gun Array,,,100,37.5,0,0,COS,0,0,0"
    ) == (1, 37.5)
    assert parse_p111_gun_array_offset_m(
        "HC,2,3,0,Gun Array 3,103,G3,4,Air Gun Array,,,100,-37.5,0,0,COS,0,0,0"
    ) == (3, -37.5)
    assert parse_p111_gun_array_offset_m(
        "HC,2,3,0,Gun Array G1,11,G01,4,Air-Gun Array,,,1,0,-519,-7,Centre of Source,3,,"
    ) == (1, 0.0)
    assert parse_p111_gun_array_offset_m(
        "HC,2,3,0,Streamer 1,104,S1,2,Streamer,,,100,618.75,0,0,CNG,0,0,0"
    ) is None


def test_3190_sample_p190_header_reads_explicit_source_offsets() -> None:
    info = _read_preplot_generation_info(
        Path("Sample Preplots/3190_TTUD1_Main_v2.WGS84.p190")
    )

    assert info.number_of_sources == 3
    assert info.source_separation_m == 37.5
    assert info.source_offsets_m == (37.5, 0.0, -37.5)


def test_3190_sample_p111_header_reads_explicit_source_offsets_and_azimuth() -> None:
    info = _read_preplot_generation_info(
        Path("Sample Preplots/3190_TTUD1_Main_v2.WGS84.p111")
    )

    assert info.shotpoint_interval_m == 16.67
    assert info.line_direction == "67.33°"
    assert info.number_of_sources == 3
    assert info.source_offsets_m == (37.5, 0.0, -37.5)


def test_sample_preplot_headers_parse_interval_and_heading() -> None:
    interval, heading = _read_preplot_header_info(
        Path("Sample Preplots/7027_S_TRINAV_v2.p190")
    )
    assert interval == 25.0
    assert heading == "125.00°"


def test_4030_preplot_header_parses_shot_interval_and_rotation() -> None:
    interval, heading = _read_preplot_header_info(
        Path("4D/4030/Preplot/4030_Mariner4D_Preplots_v2.190")
    )
    assert interval == 25.0
    assert heading == "123.10°"


def test_generated_preplot_shotpoints_interpolate_each_integer_shotpoint() -> None:
    controls = [
        PositionRecord(
            file_name="preplot.p190",
            record_type=RecordType.PREPLOT,
            line_name="LINE01",
            vessel_id="",
            source_id="",
            point_num=100,
            x=0.0,
            y=0.0,
        ),
        PositionRecord(
            file_name="preplot.p190",
            record_type=RecordType.PREPLOT,
            line_name="LINE01",
            vessel_id="",
            source_id="",
            point_num=104,
            x=40.0,
            y=0.0,
        ),
    ]
    generated = _generate_preplot_shotpoints(controls, "")
    assert sorted(generated) == [100, 101, 102, 103, 104]
    assert generated[102].x == 20.0
    assert generated[102].y == 0.0


def test_generated_preplot_shotpoints_offsets_multiple_sources_crossline() -> None:
    controls = [
        PositionRecord(
            file_name="preplot.p190",
            record_type=RecordType.PREPLOT,
            line_name="LINE01",
            vessel_id="",
            source_id="",
            point_num=100,
            x=0.0,
            y=0.0,
        ),
        PositionRecord(
            file_name="preplot.p190",
            record_type=RecordType.PREPLOT,
            line_name="LINE01",
            vessel_id="",
            source_id="",
            point_num=101,
            x=0.0,
            y=25.0,
        ),
    ]
    generated = _generate_preplot_shotpoints(
        controls,
        "",
        source_count=2,
        source_separation_m=50.0,
        line_azimuth_deg=0.0,
    )
    source_1 = generated[(100, "1")]
    source_2 = generated[(100, "2")]
    assert source_1.source_id == "G01"
    assert source_2.source_id == "G02"
    assert abs(source_1.x - 25.0) < 1e-6
    assert abs(source_1.y - 0.0) < 1e-6
    assert abs(source_2.x + 25.0) < 1e-6
    assert abs(source_2.y - 0.0) < 1e-6


def test_generated_preplot_shotpoints_uses_explicit_source_offsets() -> None:
    controls = [
        PositionRecord(
            file_name="preplot.p190",
            record_type=RecordType.PREPLOT,
            line_name="LINE01",
            vessel_id="",
            source_id="",
            point_num=100,
            x=0.0,
            y=0.0,
        ),
        PositionRecord(
            file_name="preplot.p190",
            record_type=RecordType.PREPLOT,
            line_name="LINE01",
            vessel_id="",
            source_id="",
            point_num=101,
            x=0.0,
            y=25.0,
        ),
    ]
    generated = _generate_preplot_shotpoints(
        controls,
        "",
        source_count=3,
        source_separation_m=37.5,
        line_azimuth_deg=0.0,
        source_offsets_m=(40.0, 5.0, -20.0),
    )

    assert abs(generated[(100, "1")].x - 40.0) < 1e-6
    assert abs(generated[(100, "2")].x - 5.0) < 1e-6
    assert abs(generated[(100, "3")].x + 20.0) < 1e-6


def test_diff_rows_compare_firing_source_to_matching_preplot_source_position() -> None:
    baseline = {
        (100, "1"): BaselineShotpoint(
            shotpoint=100,
            x=25.0,
            y=0.0,
            source_id="G01",
            source_index=1,
        ),
        (100, "2"): BaselineShotpoint(
            shotpoint=100,
            x=-25.0,
            y=0.0,
            source_id="G02",
            source_index=2,
        ),
    }
    sources = {
        100: PositionRecord(
            file_name="line.p111",
            record_type=RecordType.SOURCE,
            line_name="LINE01",
            vessel_id="",
            source_id="G02",
            point_num=100,
            x=-20.0,
            y=0.0,
        )
    }
    rows = compute_postplot_4d_diff_rows(baseline, sources, "0.0")
    assert len(rows) == 1
    assert rows[0].baseline_x == -25.0
    assert abs(rows[0].crossline_m - 5.0) < 1e-6
    assert rows[0].firing_source_id == "G02"


def test_diff_rows_include_vessel_and_firing_source_ids() -> None:
    baseline = {
        100: BaselineShotpoint(shotpoint=100, x=0.0, y=0.0),
    }
    sources = {
        100: PositionRecord(
            file_name="line.p111",
            record_type=RecordType.SOURCE,
            line_name="LINE01",
            vessel_id="AMU",
            source_id="G01",
            point_num=100,
            x=1.0,
            y=2.0,
        )
    }
    rows = compute_postplot_4d_diff_rows(
        baseline,
        sources,
        "0.0",
        vessel_ids={100: "AMU"},
    )
    assert len(rows) == 1
    assert rows[0].vessel_id == "AMU"
    assert rows[0].firing_source_id == "G01"


def test_enrich_diff_rows_fills_vessel_id_from_vessel_positions() -> None:
    from xpostmaps.core.postplot_4d_diff import enrich_diff_rows_from_positions
    from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow

    match_row = Postplot4DMatchRow(
        baseline_name="1065P1A-070",
        baseline_kind="navplan",
        line_name="1065P1A-070",
        subline="a070",
        sequence_no="70",
        first_sp=1489,
        last_sp=1508,
        line_direction="179.97°",
        sequence_id="70.1065P1A-070.a070.p111|70|1065P1A-070|source",
    )
    rows = [
        Postplot4DDiffRow(
            shotpoint=1600,
            baseline_x=0.0,
            baseline_y=0.0,
            baseline_latitude="",
            baseline_longitude="",
            source_x=1.0,
            source_y=2.0,
            source_latitude="",
            source_longitude="",
            crossline_m=0.0,
            inline_m=0.0,
            radial_m=0.0,
            firing_source_id="G02",
        )
    ]
    positions = [
        PositionRecord(
            file_name="70.1065P1A-070.a070.p111",
            record_type=RecordType.SOURCE,
            line_name="1065P1A-070",
            vessel_id="",
            source_id="G02",
            point_num=1600,
            x=1.0,
            y=2.0,
            sequence_no="70",
        ),
        PositionRecord(
            file_name="70.1065P1A-070.a070.p111",
            record_type=RecordType.VESSEL,
            line_name="1065P1A-070",
            vessel_id="AWA",
            source_id="",
            point_num=1600,
            x=1.0,
            y=2.0,
            sequence_no="70",
        ),
    ]
    enriched = enrich_diff_rows_from_positions(rows, positions, match_row)
    assert enriched[0].vessel_id == "AWA"
    assert enriched[0].firing_source_id == "G02"


def test_diff_rows_remap_preplot_source_side_for_reverse_acquisition() -> None:
    controls = [
        PositionRecord(
            file_name="3190_preplot.p111",
            record_type=RecordType.PREPLOT,
            line_name="1018",
            vessel_id="",
            source_id="",
            point_num=100,
            x=0.0,
            y=0.0,
        ),
        PositionRecord(
            file_name="3190_preplot.p111",
            record_type=RecordType.PREPLOT,
            line_name="1018",
            vessel_id="",
            source_id="",
            point_num=101,
            x=25.0 * math.sin(math.radians(67.3)),
            y=25.0 * math.cos(math.radians(67.3)),
        ),
    ]
    baseline = _generate_preplot_shotpoints(
        controls,
        "",
        source_count=3,
        source_separation_m=37.5,
        line_azimuth_deg=67.3,
    )
    # The preplot file geometry is 67.3 degrees, but this acquired line was
    # shot in the reciprocal direction. For the firing direction, source 1 is
    # on the side cached as preplot source 3.
    physical_source_1 = baseline[(100, "3")]
    physical_source_3 = baseline[(100, "1")]
    sources = {
        100: PositionRecord(
            file_name="line.p111",
            record_type=RecordType.SOURCE,
            line_name="1018A003",
            vessel_id="",
            source_id="G01",
            point_num=100,
            x=physical_source_1.x,
            y=physical_source_1.y,
        ),
        101: PositionRecord(
            file_name="line.p111",
            record_type=RecordType.SOURCE,
            line_name="1018A003",
            vessel_id="",
            source_id="G03",
            point_num=101,
            x=physical_source_3.x + 25.0 * math.sin(math.radians(67.3)),
            y=physical_source_3.y + 25.0 * math.cos(math.radians(67.3)),
        ),
    }

    rows = compute_postplot_4d_diff_rows(baseline, sources, "247.3")

    assert len(rows) == 2
    assert rows[0].baseline_x == physical_source_1.x
    assert rows[1].baseline_x == physical_source_3.x + 25.0 * math.sin(math.radians(67.3))
    assert abs(rows[0].crossline_m) < 1e-6
    assert abs(rows[1].crossline_m) < 1e-6


def test_diff_rows_keep_preplot_source_side_for_same_direction_acquisition() -> None:
    controls = [
        PositionRecord(
            file_name="3190_preplot.p111",
            record_type=RecordType.PREPLOT,
            line_name="1702",
            vessel_id="",
            source_id="",
            point_num=100,
            x=0.0,
            y=0.0,
        ),
        PositionRecord(
            file_name="3190_preplot.p111",
            record_type=RecordType.PREPLOT,
            line_name="1702",
            vessel_id="",
            source_id="",
            point_num=101,
            x=25.0 * math.sin(math.radians(67.3)),
            y=25.0 * math.cos(math.radians(67.3)),
        ),
    ]
    baseline = _generate_preplot_shotpoints(
        controls,
        "",
        source_count=3,
        source_separation_m=37.5,
        line_azimuth_deg=67.3,
    )
    physical_source_1 = baseline[(100, "1")]
    sources = {
        100: PositionRecord(
            file_name="line.p111",
            record_type=RecordType.SOURCE,
            line_name="1702A002",
            vessel_id="",
            source_id="G01",
            point_num=100,
            x=physical_source_1.x,
            y=physical_source_1.y,
        )
    }

    rows = compute_postplot_4d_diff_rows(baseline, sources, "67.3")

    assert len(rows) == 1
    assert rows[0].baseline_x == physical_source_1.x
    assert abs(rows[0].crossline_m) < 1e-6


def test_p111_preplot_parser_uses_actual_control_shotpoints() -> None:
    result = parse_preplot_file(Path("Sample Preplots/TTUD-13D.DL2_3.WGS84.p111"))
    controls = [
        record
        for record in result.records
        if record.line_name == "6018"
    ]
    assert [record.point_num for record in controls] == [1974, 4500, 7529]
    first, middle = controls[0], controls[1]
    distance = math.hypot(middle.x - first.x, middle.y - first.y)
    assert abs(distance / (middle.point_num - first.point_num) - 16.667) < 1e-3


def test_10221_p111_firing_source_axis_order_matches_p190_sample() -> None:
    p111 = Path("Sample P111-P190/10221/002.1815M1A-002.nrt.p111")
    p190 = Path("Sample P111-P190/10221/002.1815M1A-002.nrt.p190")
    if not p111.is_file() or not p190.is_file():
        return

    assert scan_projected_axis_order(p111) == ("northing", "easting")
    p111_sources = {
        record.point_num: record
        for record in parse_p111_file(p111)
        if record.record_type == RecordType.SOURCE
    }
    p190_sources = {
        record.point_num: record
        for record in parse_p190_file(p190)
        if record.record_type == RecordType.SOURCE
    }
    common = sorted(set(p111_sources).intersection(p190_sources))[:20]

    assert common
    for shotpoint in common:
        p111_source = p111_sources[shotpoint]
        p190_source = p190_sources[shotpoint]
        assert abs(p111_source.x - p190_source.x) < 0.1
        assert abs(p111_source.y - p190_source.y) < 0.1
        assert p111_source.source_id[-1] == p190_source.source_id


def test_10221_p111_receiver_feathers_average_all_streamers() -> None:
    p111 = Path("Sample P111-P190/10221/70.1065P1A-070.a070.p111")
    if not p111.is_file():
        return

    feathers = parse_p111_receiver_feathers(p111)
    by_sp = average_receiver_feathers_by_shotpoint(feathers)
    sp1600 = [record for record in feathers if record.shotpoint == 1600]

    assert len(sp1600) == 8
    assert set(record.streamer_id for record in sp1600) == {
        "S01",
        "S02",
        "S03",
        "S04",
        "S05",
        "S06",
        "S07",
        "S08",
    }
    assert 0.0 < by_sp[1600] < 10.0


def test_diff_rows_include_optional_feather_values() -> None:
    baseline = {100: BaselineShotpoint(shotpoint=100, x=0.0, y=0.0)}
    sources = {
        100: PositionRecord(
            file_name="line.p111",
            record_type=RecordType.SOURCE,
            line_name="0103643A",
            vessel_id="",
            source_id="G01",
            point_num=100,
            x=0.0,
            y=0.0,
        )
    }

    rows = compute_postplot_4d_diff_rows(
        baseline,
        sources,
        "0.0",
        navplan_feathers={100: 1.25},
        line_feathers={100: -2.5},
    )

    assert rows[0].navplan_feather_deg == 1.25
    assert rows[0].line_feather_deg == -2.5


def test_feather_diff_is_line_minus_navplan() -> None:
    from xpostmaps.core.postplot_4d_diff import feather_diff_deg

    assert feather_diff_deg(line_feather_deg=-2.5, navplan_feather_deg=1.25) == -3.75
    assert feather_diff_deg(line_feather_deg=None, navplan_feather_deg=1.25) is None
    assert feather_diff_deg(line_feather_deg=-2.5, navplan_feather_deg=None) is None


def test_4030_generated_preplot_position_matches_interval_and_rotation() -> None:
    preplot = Path("4D/4030/Preplot/4030_Mariner4D_Preplots_v2.190")
    result = parse_preplot_file(preplot)
    controls = [
        record
        for record in result.records
        if record.line_name == "0103643A"
    ]
    generated = _generate_preplot_shotpoints(controls, "")
    sp = 1536
    start = controls[0]
    expected_x = start.x + (sp - start.point_num) * 25.0 * math.sin(math.radians(123.1))
    expected_y = start.y + (sp - start.point_num) * 25.0 * math.cos(math.radians(123.1))
    assert abs(generated[sp].x - expected_x) < 0.02
    assert abs(generated[sp].y - expected_y) < 0.02


def test_offset_components_use_line_heading_for_4030_sp1536() -> None:
    baseline = {1536: BaselineShotpoint(shotpoint=1536, x=396709.1, y=6608538.9)}
    sources = {
        1536: PositionRecord(
            file_name="069.0103643A-069.nrt.GFUNREG.p111",
            record_type=RecordType.SOURCE,
            line_name="0103643A-069",
            vessel_id="",
            source_id="G01",
            point_num=1536,
            x=396709.0,
            y=6608538.64,
            latitude="59.60086832",
            longitude="1.1701019",
        )
    }
    azimuth = resolve_line_azimuth_degrees("123.1", baseline, baseline_path=None)
    assert abs(azimuth - 123.1) < 0.01
    rows = compute_postplot_4d_diff_rows(baseline, sources, "123.1")
    row = rows[0]
    assert abs(row.inline_m - 0.058) < 0.01
    assert abs(row.crossline_m - 0.272) < 0.01
    assert abs(row.radial_m - 0.279) < 0.01


def test_offset_components_use_line_azimuth() -> None:
    baseline = {
        100: BaselineShotpoint(shotpoint=100, x=0.0, y=0.0),
    }
    sources = {
        100: PositionRecord(
            file_name="line.p190",
            record_type=RecordType.SOURCE,
            line_name="0103643A",
            vessel_id="",
            source_id="G01",
            point_num=100,
            x=10.0,
            y=5.0,
        )
    }
    rows = compute_postplot_4d_diff_rows(baseline, sources, "0.0")
    assert len(rows) == 1
    row = rows[0]
    assert abs(row.inline_m - 5.0) < 1e-6
    assert abs(row.crossline_m - 10.0) < 1e-6
    assert abs(row.radial_m - (125.0**0.5)) < 1e-6


def test_7027_multisource_diff_compares_each_gun_to_its_own_offset_source() -> None:
    """Real flip-flop dual-source: G01/G02 must diff vs their own +/-25 m
    baseline source, not the line centre (which would leave a ~25 m bias)."""
    import math

    from xpostmaps.core.models import MapData, ProjectSettings, RecordType
    from xpostmaps.core.postplot_4d_diff import (
        _read_preplot_generation_info,
        calculate_match_diff_rows,
        load_baseline_shotpoints,
    )
    from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
    from xpostmaps.parsers.p111_parser import parse_p111_file
    from xpostmaps.parsers.preplot_parser import parse_preplot_files
    from xpostmaps.parsers.sequence_builder import build_display_sequences

    preplot = Path("4D/7027/Preplot/7027_S_TRINAV_v2.p190")
    p111 = Path("4D/7027/P111V_S/3237.53196213237.a3237.GFUNREG.p111")
    if not preplot.is_file() or not p111.is_file():
        return  # dataset not present in this checkout

    info = _read_preplot_generation_info(preplot)
    assert info.number_of_sources == 2
    assert info.source_separation_m == 50.0

    segments, _meta, _stats = parse_preplot_files([preplot])
    src = [r for r in parse_p111_file(p111) if r.record_type == RecordType.SOURCE]
    map_data = MapData()
    map_data.preplot_segments = segments
    map_data.positions = src
    map_data.sequences = build_display_sequences(src)
    settings = ProjectSettings(
        preplot_files=[str(preplot.resolve())],
        nav_files=[str(p111.resolve())],
        postplot_4d_baseline="preplot",
    )
    rows = build_postplot_4d_rows(map_data, settings, "preplot")
    match_row = next(r for r in rows if r.has_match)

    # baseline places two sources exactly 50 m apart per shotpoint
    baseline = load_baseline_shotpoints(
        map_data, settings, "preplot", match_row.baseline_name,
        match_row.baseline_file_name, map_epsg="32621",
    )
    sp_both = [k[0] for k in baseline
               if isinstance(k, tuple) and (k[0], "1") in baseline and (k[0], "2") in baseline]
    sample = sp_both[len(sp_both) // 2]
    d = math.hypot(
        baseline[(sample, "1")].x - baseline[(sample, "2")].x,
        baseline[(sample, "1")].y - baseline[(sample, "2")].y,
    )
    assert abs(d - 50.0) < 1e-3

    diff_rows = calculate_match_diff_rows(map_data, settings, src, match_row)
    src_by_sp = {r.point_num: r for r in src}
    g01 = [r.crossline_m for r in diff_rows if src_by_sp.get(r.shotpoint, src[0]).source_id == "G01"]
    g02 = [r.crossline_m for r in diff_rows if src_by_sp.get(r.shotpoint, src[0]).source_id == "G02"]
    assert g01 and g02
    # Correct separation + side -> small residual bias (NOT ~25 m).
    assert abs(sum(g01) / len(g01)) < 5.0
    assert abs(sum(g02) / len(g02)) < 5.0


def test_p111_compound_crs_row_does_not_clobber_projected_epsg() -> None:
    from xpostmaps.parsers.metadata_parser import parse_p111_metadata

    path = Path("4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111")
    metadata = parse_p111_metadata(path)
    # The file lists a compound CRS ("ED50 / UTM zone 31N / Instantaneous Water
    # Level depth") with an empty EPSG field. That row must NOT overwrite the
    # real projected horizontal CRS, ED50 / UTM zone 31N == EPSG:23031.
    assert metadata.get("epsg code") == "23031"


def test_10221_preplot_infers_nztm_from_tm_grid_parameters() -> None:
    path = Path("4D/10221/Preplot/10221_AWA_Maui4D_v2.190")
    if not path.is_file():
        return

    from xpostmaps.parsers.metadata_parser import parse_p190_metadata
    from xpostmaps.core.preplot_catalog_utils import build_preplot_catalog

    metadata = parse_p190_metadata(path)
    assert metadata.get("epsg code") == "2193"
    assert metadata.get("projection", "").upper().find("TRANSVERSE MERCATOR") >= 0
    assert metadata.get("projection zone", "").strip() == ""

    catalog = build_preplot_catalog([path])
    assert len(catalog) == 1
    assert catalog[0].crs_code == "2193"


def test_10221_p190_receiver_feathers_parse_all_streamers() -> None:
    from xpostmaps.parsers.p111_parser import (
        average_receiver_feathers_by_shotpoint,
        parse_p190_receiver_feathers,
    )

    source = Path("4D/10221/P1/70.1065P1A-070.a070.p190")
    navplan = Path("4D/10221/Navplan/1065P1.p190")
    if not source.is_file() or not navplan.is_file():
        return

    source_records = parse_p190_receiver_feathers(source)
    assert source_records, "expected per-streamer feather records from P190 source"
    # 8-streamer survey: each shotpoint should yield 8 streamer feathers.
    from collections import Counter

    per_shot = Counter(record.shotpoint for record in source_records)
    assert max(per_shot.values()) == 8
    source_avg = average_receiver_feathers_by_shotpoint(source_records)
    assert 1300 in source_avg
    assert -45.0 < source_avg[1300] < 45.0

    navplan_avg = average_receiver_feathers_by_shotpoint(
        parse_p190_receiver_feathers(navplan)
    )
    assert navplan_avg, "expected navplan feather records from P190 navplan"
    assert 1300 in navplan_avg


def test_receiver_endpoint_targets_from_real_headers() -> None:
    from xpostmaps.parsers.p111_parser import (
        scan_p111_receiver_endpoint_targets,
        scan_p190_receiver_endpoint_targets,
    )

    p111 = Path("4D/0085.T26A.6054B085.a0085.SSFILTREG.p111")
    if p111.is_file():
        targets = scan_p111_receiver_endpoint_targets(p111)
        assert targets.get("S01") == (1, 3203)
        assert targets.get("S12") == (1, 3203)

    p111v = Path("4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111")
    if p111v.is_file():
        assert scan_p111_receiver_endpoint_targets(p111v) == {}

    p190 = Path("4D/10221/P1/70.1065P1A-070.a070.p190")
    if p190.is_file():
        targets = scan_p190_receiver_endpoint_targets(p190)
        assert targets.get("1") == (1, 240)
        assert targets.get("P") == (1, 240)


def test_p111_multirow_streamer_feather_is_head_to_tail() -> None:
    """Shearwater P111 splits one streamer across several R1 rows.

    The parser must accumulate all rows and emit ONE feather per
    (shotpoint, streamer), computed from the global first/last receiver.
    """
    from collections import Counter

    from xpostmaps.parsers.p111_parser import parse_p111_receiver_feathers

    path = Path("4D/0145.SUR633D2024.1736P2-145.a0145.SSFILTUNREG.v19.p111")
    if not path.is_file():
        return
    records = parse_p111_receiver_feathers(path)
    assert records
    # Exactly one feather record per (shotpoint, streamer) despite 4 R1 rows.
    per_key = Counter((r.shotpoint, r.streamer_id) for r in records)
    assert per_key, "expected feather records"
    assert max(per_key.values()) == 1
    # 7-streamer survey.
    streamers = {r.streamer_id for r in records}
    assert streamers == {f"S0{i}" for i in range(1, 8)}


def test_p111_feather_falls_back_to_track_when_header_is_wrong() -> None:
    """A bad LINE-DIRECTION header must not produce an absurd feather.

    File 0085 has header 247.33 deg but an actual source track of ~300 deg;
    the feather must use the data-derived track (~-5 deg), not the header
    (which would give ~-57 deg).
    """
    from xpostmaps.parsers.p111_parser import (
        average_receiver_feathers_by_shotpoint,
        parse_p111_receiver_feathers,
        scan_p111_source_track_deg,
        scan_projected_axis_order,
    )

    path = Path("4D/0085.T26A.6054B085.a0085.SSFILTREG.p111")
    if not path.is_file():
        return
    axis = scan_projected_axis_order(path)
    track = scan_p111_source_track_deg(path, axis)
    assert track is not None
    assert 290.0 < track < 310.0  # real sail line, not the 247.33 header

    avg = average_receiver_feathers_by_shotpoint(parse_p111_receiver_feathers(path))
    assert avg
    # Every shotpoint feather must be physically plausible (well under the
    # absurd ~-57 deg the bad header would yield).
    assert all(abs(v) < 15.0 for v in avg.values())


def test_p111_track_resolver_prefers_validated_header() -> None:
    from xpostmaps.parsers.p111_parser import _resolve_feather_line_direction

    # Header within tolerance of track -> keep header (validated).
    assert _resolve_feather_line_direction(179.97, 179.66) == 179.97
    # Header grossly disagrees with track -> use track.
    assert _resolve_feather_line_direction(247.33, 299.6) == 299.6
    # Missing pieces fall back gracefully.
    assert _resolve_feather_line_direction(None, 300.0) == 300.0
    assert _resolve_feather_line_direction(120.0, None) == 120.0


def test_p190_header_preserves_full_precision_line_direction() -> None:
    """The feather angle must use the unrounded line direction.

    ``parse_p190_header`` exposes a display string rounded to 2 dp
    ("179.97 deg"); a separate full-precision value must be available so the
    streamer feather is not biased by ~0.004 deg.
    """
    from xpostmaps.parsers.p190_parser import parse_p190_header

    source = Path("4D/10221/P1/70.1065P1A-070.a070.p190")
    if not source.is_file():
        return
    info = parse_p190_header(source)
    assert info.get("line direction value") == "179.9740"
    # The display form remains rounded for the UI.
    assert info.get("line direction", "").startswith("179.97")


def test_p190_feather_matches_independent_calculation() -> None:
    """Brutal check: parser feather equals a hand calculation from raw groups."""
    import math

    from xpostmaps.parsers.p111_parser import parse_p190_receiver_feathers

    source = Path("4D/10221/P1/70.1065P1A-070.a070.p190")
    if not source.is_file():
        return

    # Independent feather: streamer 1 at SP 1600 from raw min/max groups.
    sp, target_streamer = 1600, "1"
    groups: dict[int, tuple[float, float]] = {}
    current = 0
    with source.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\n\r")
            if not line:
                continue
            if line[0] == "S":
                current = int(line[19:25])
            elif line[0] == "R" and current == sp:
                if len(line) <= 79 or line[79].strip() != target_streamer:
                    continue
                pos = 1
                while pos + 22 <= len(line):
                    g = line[pos : pos + 4].strip()
                    e = line[pos + 4 : pos + 13].strip()
                    n = line[pos + 13 : pos + 22].strip()
                    if not (g and e and n):
                        break
                    groups[int(g)] = (float(e), float(n))
                    pos += 26
    assert groups
    first, last = groups[min(groups)], groups[max(groups)]
    dx, dy = last[0] - first[0], last[1] - first[1]
    az = math.degrees(math.atan2(dx, dy)) % 360.0
    expected = ((179.9740 + 180.0) - az + 180.0) % 360.0 - 180.0

    parsed = {
        (r.shotpoint, r.streamer_id): r.feather_deg
        for r in parse_p190_receiver_feathers(source)
    }
    assert abs(parsed[(sp, target_streamer)] - expected) < 1e-9


def test_p190_orient_track_to_streamers_resolves_reciprocal() -> None:
    """P190 shotpoints can number opposite to travel, so the raw track bearing
    is direction-ambiguous. Streamer trailing geometry must flip it to a true
    heading (the bearing pointing *into* the heading, away from the streamers)."""
    from xpostmaps.parsers.p111_parser import _orient_track_to_streamers

    # Vessel heads ~180 deg (south); streamers trail north (~355 deg head->tail).
    # A shotpoint-ordered bearing of 359.66 (reciprocal) must flip to ~179.66.
    assert abs(_orient_track_to_streamers(359.66, 355.4) - 179.66) < 1e-6
    # A bearing already aligned with the heading is kept unchanged.
    assert abs(_orient_track_to_streamers(179.66, 355.4) - 179.66) < 1e-6
    # Missing inputs degrade gracefully.
    assert _orient_track_to_streamers(None, 355.4) is None
    assert _orient_track_to_streamers(179.66, None) == 179.66


def test_p190_feather_uses_header_when_track_agrees_on_real_file() -> None:
    """On a correctly-headed real P190 the oriented track must agree with the
    header (within tolerance) so the exact header feather is preserved."""
    from xpostmaps.parsers.p111_parser import (
        _orient_track_to_streamers,
        _track_bearing_from_source_positions,
        parse_p190_receiver_feathers,
        scan_p190_source_track_deg,
    )

    source = Path("4D/10221/P1/70.1065P1A-070.a070.p190")
    if not source.is_file():
        return
    feathers = {
        (r.shotpoint, r.streamer_id): r.feather_deg
        for r in parse_p190_receiver_feathers(source)
    }
    # Header 179.9740 is kept -> the independently verified +4.599 deg stands.
    assert abs(feathers[(1600, "1")] - 4.599) < 0.01


def test_p190_feather_falls_back_to_oriented_track_without_header(monkeypatch) -> None:
    """A missing P190 LINE-DIRECTION must not drop the feather: the oriented,
    data-derived track stands in and yields the same plausible feather."""
    import xpostmaps.parsers.p190_parser as p190
    from xpostmaps.parsers.p111_parser import parse_p190_receiver_feathers

    source = Path("4D/10221/P1/70.1065P1A-070.a070.p190")
    if not source.is_file():
        return

    with_header = {
        (r.shotpoint, r.streamer_id): r.feather_deg
        for r in parse_p190_receiver_feathers(source)
    }

    real_header = p190.parse_p190_header

    def _strip_direction(path):
        info = dict(real_header(path))
        info.pop("line direction value", None)
        info.pop("line direction", None)
        return info

    # parse_p190_receiver_feathers imports parse_p190_header from p190_parser at
    # call time, so patch it at the source module.
    monkeypatch.setattr(p190, "parse_p190_header", _strip_direction)
    without_header = {
        (r.shotpoint, r.streamer_id): r.feather_deg
        for r in parse_p190_receiver_feathers(source)
    }
    assert without_header, "missing header must not drop the feather"
    # Oriented track (~179.66) vs header (179.974) differ by ~0.3 deg only.
    assert abs(without_header[(1600, "1")] - with_header[(1600, "1")]) < 1.0


def test_p190_feather_dispatch_returns_values_with_sequence_fallback() -> None:
    from xpostmaps.core.postplot_4d_diff import _receiver_feathers_for_path

    source = Path("4D/10221/P1/70.1065P1A-070.a070.p190")
    if not source.is_file():
        return
    # A non-matching sequence group must not wipe out single-line P190 feathers.
    feathers = _receiver_feathers_for_path(
        source, sequence_group="does|not|match", subline=""
    )
    assert feathers
    assert 1300 in feathers


def test_navplan_feather_survives_subline_mismatch() -> None:
    from xpostmaps.core.postplot_4d_diff import _receiver_feathers_for_path

    navplan = Path("4D/10221/Navplan/1065P1.p190")
    if not navplan.is_file():
        return
    # The navplan carries its own subline ("1"); the acquired line's subline
    # ("a070") must not empty the navplan feather column.
    feathers = _receiver_feathers_for_path(
        navplan, line_name="1065P1A-070", subline="a070"
    )
    assert feathers
    assert 1300 in feathers


def test_4030_preplot_crs_resolves_to_ed50_utm31n() -> None:
    path = Path("4D/4030/Preplot/4030_Mariner4D_Preplots_v2.190")
    if not path.is_file():
        return
    from xpostmaps.core.preplot_catalog_utils import build_preplot_catalog
    from xpostmaps.parsers.metadata_parser import parse_p190_metadata

    metadata = parse_p190_metadata(path)
    assert metadata.get("epsg code") == "23031"
    catalog = build_preplot_catalog([path])
    assert catalog and catalog[0].crs_code == "23031"


def test_7027_preplot_crs_resolves_to_wgs84_utm21n() -> None:
    path = Path("4D/7027/Preplot/7027_S_TRINAV_v2.p190")
    if not path.is_file():
        return
    from xpostmaps.core.preplot_catalog_utils import build_preplot_catalog
    from xpostmaps.parsers.metadata_parser import (
        _p190_grid_parameters,
        parse_p190_metadata,
    )

    metadata = parse_p190_metadata(path)
    assert metadata.get("epsg code") == "32621"
    # Packed-DMS central meridian (0570000.000W) must parse to -57.0 degrees.
    central_meridian, _, _, _ = _p190_grid_parameters(metadata)
    assert central_meridian is not None
    assert abs(central_meridian - (-57.0)) < 1e-6
    catalog = build_preplot_catalog([path])
    assert catalog and catalog[0].crs_code == "32621"


def test_parse_central_meridian_accepts_dms_and_packed_formats() -> None:
    from xpostmaps.parsers.metadata_parser import _parse_p190_central_meridian_deg

    assert _parse_p190_central_meridian_deg("173 0 0.000E") == 173.0
    assert _parse_p190_central_meridian_deg("  3 0 0.000E") == 3.0
    assert _parse_p190_central_meridian_deg("0570000.000W") == -57.0
    assert _parse_p190_central_meridian_deg("57.0W") == -57.0
    assert _parse_p190_central_meridian_deg("-57.0") == -57.0
    assert _parse_p190_central_meridian_deg("") is None


def test_grid_parameter_resolver_handles_common_tm_grids() -> None:
    from xpostmaps.core.crs_utils import epsg_from_grid_parameters, pyproj_available

    if not pyproj_available():
        return
    # British National Grid (OSGB36 / TM).
    assert (
        epsg_from_grid_parameters("OSGB36", -2.0, 400000.0, -100000.0, 0.9996012717, 49.0)
        == "27700"
    )
    # GDA94 / MGA zone 55.
    assert (
        epsg_from_grid_parameters("GDA94", 147.0, 500000.0, 10000000.0, 0.9996)
        == "28355"
    )


def test_navplan_header_infers_epsg_from_datum_projection_zone() -> None:
    from xpostmaps.parsers.metadata_parser import parse_file_metadata

    path = Path("4D/4030/Navplans/Priority1/0111421A.navplan")
    metadata = parse_file_metadata(path)
    assert metadata.get("geographic datum", "").startswith("ED50")
    assert metadata.get("projection") == "001 U.T.M. NORTHERN HEMISPHERE"
    assert metadata.get("projection zone") == "31N"
    assert metadata.get("epsg code") == "23031"


def test_navplan_header_line_direction_from_h2600() -> None:
    from xpostmaps.core.navplan_catalog_utils import build_navplan_catalog
    from xpostmaps.parsers.metadata_parser import parse_file_metadata

    path = Path("4D/4030/Navplans/Priority1/0103643A.navplan")
    if not path.is_file():
        return

    metadata = parse_file_metadata(path)
    assert metadata.get("line direction") == "123.10°"

    catalog = build_navplan_catalog([path])
    assert len(catalog) == 1
    assert catalog[0].line_direction == "123.10°"

    reverse_path = Path("4D/4030/Navplans/Priority2/0122936A.navplan")
    if reverse_path.is_file():
        reverse_catalog = build_navplan_catalog([reverse_path])
        assert reverse_catalog[0].line_direction == "303.10°"


def test_infer_epsg_from_header_known_utm_families_without_pyproj() -> None:
    """Header-only inference must resolve common UTM datum families even when
    pyproj is unavailable. These EPSG codes are authoritative and fixed."""
    from xpostmaps.core.crs_utils import infer_epsg_from_header

    # ED50 / UTM North (zones 28-38 == EPSG 23028-23038).
    assert infer_epsg_from_header("ED50", "U.T.M. NORTHERN HEMISPHERE", "31N") == "23031"
    assert infer_epsg_from_header("ED-50", "UTM", "28N") == "23028"
    assert infer_epsg_from_header("ED50", "UTM", "38N") == "23038"
    # WGS 84 / UTM, both hemispheres (326xx north, 327xx south).
    assert infer_epsg_from_header("WGS84", "UTM zone 21N", "21N") == "32621"
    assert infer_epsg_from_header("WGS 84", "UTM SOUTHERN HEMISPHERE", "55S") == "32755"
    # ETRS89 and NAD families.
    assert infer_epsg_from_header("ETRS89", "UTM", "32N") == "25832"
    assert infer_epsg_from_header("NAD83", "UTM", "15N") == "26915"
    assert infer_epsg_from_header("NAD27", "UTM", "15N") == "26715"
    # Out-of-family zone numbers must NOT produce a false EPSG.
    assert infer_epsg_from_header("ED50", "UTM", "60N") == ""
    # Missing zone must not borrow digits from the projection code (e.g. "001").
    assert infer_epsg_from_header("ED50", "001 U.T.M. NORTHERN HEMISPHERE", "") == ""


def _build_4030_navplan_match_row(p111: Path):
    """Construct a navplan match row wired to the real 4030 P111 source records."""
    from xpostmaps.core.models import make_sequence_group_id
    from xpostmaps.parsers.p111_parser import parse_p111_file

    src = [
        r
        for r in parse_p111_file(p111)
        if r.record_type == RecordType.SOURCE and r.point_num > 0
    ]
    rec = src[0]
    seq_id = make_sequence_group_id(rec.file_name, rec.sequence_no, rec.line_name) + "|source"
    match_row = Postplot4DMatchRow(
        baseline_name="0103643A",
        baseline_kind="navplan",
        line_name=rec.line_name,
        subline=rec.subline,
        sequence_no=rec.sequence_no,
        first_sp=min(r.point_num for r in src),
        last_sp=max(r.point_num for r in src),
        line_direction="123.1",
        sequence_id=seq_id,
        baseline_file_name="0103643A.navplan",
    )
    return src, match_row


def test_diff_crs_gate_passes_on_real_4030_navplan_vs_p111() -> None:
    from xpostmaps.core.postplot_4d_diff import (
        assess_diff_crs_consistency,
        calculate_match_diff_rows,
    )

    navplan = Path("4D/4030/Navplans/Priority1/0103643A.navplan")
    p111 = Path("4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111")
    if not navplan.is_file() or not p111.is_file():
        return  # dataset not present in this checkout

    src, match_row = _build_4030_navplan_match_row(p111)
    map_data = MapData()
    map_data.postmap_info.epsg_code = "23031"
    settings = ProjectSettings(
        nav_files=[str(p111.resolve())],
        navplan_files=[str(navplan.resolve())],
        postplot_4d_baseline="navplan",
    )

    assessment = assess_diff_crs_consistency(map_data, settings, src, match_row)
    assert assessment.ok, assessment.reason
    assert assessment.baseline_epsg == "23031"
    assert set(assessment.source_epsgs) == {"23031"}

    diff_rows = calculate_match_diff_rows(map_data, settings, src, match_row)
    assert diff_rows  # FSP/LSP positions populated only when CRS is verified


def test_diff_crs_gate_blocks_when_source_crs_unknown() -> None:
    from xpostmaps.core.postplot_4d_diff import (
        CrsMismatchError,
        assess_diff_crs_consistency,
        calculate_match_diff_rows,
    )

    navplan = Path("4D/4030/Navplans/Priority1/0103643A.navplan")
    p111 = Path("4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111")
    if not navplan.is_file() or not p111.is_file():
        return

    src, match_row = _build_4030_navplan_match_row(p111)
    map_data = MapData()
    map_data.postmap_info.epsg_code = "23031"
    # No nav_files / p111 dir -> the firing-source CRS cannot be resolved.
    settings = ProjectSettings(
        navplan_files=[str(navplan.resolve())],
        postplot_4d_baseline="navplan",
    )

    assessment = assess_diff_crs_consistency(map_data, settings, src, match_row)
    assert not assessment.ok
    assert "source" in assessment.reason.lower()

    import pytest

    with pytest.raises(CrsMismatchError):
        calculate_match_diff_rows(map_data, settings, src, match_row)


def test_diff_crs_gate_blocks_when_no_sources() -> None:
    from xpostmaps.core.postplot_4d_diff import (
        CrsMismatchError,
        assess_diff_crs_consistency,
        calculate_match_diff_rows,
    )

    navplan = Path("4D/4030/Navplans/Priority1/0103643A.navplan")
    if not navplan.is_file():
        return

    match_row = Postplot4DMatchRow(
        baseline_name="0103643A",
        baseline_kind="navplan",
        line_name="0103643A",
        subline="",
        sequence_no="1",
        first_sp=0,
        last_sp=0,
        line_direction="123.1",
        sequence_id="missing.p111|1|0103643A|source",
        baseline_file_name="0103643A.navplan",
    )
    map_data = MapData()
    map_data.postmap_info.epsg_code = "23031"
    settings = ProjectSettings(
        navplan_files=[str(navplan.resolve())],
        postplot_4d_baseline="navplan",
    )

    assessment = assess_diff_crs_consistency(map_data, settings, [], match_row)
    assert not assessment.ok

    import pytest

    with pytest.raises(CrsMismatchError):
        calculate_match_diff_rows(map_data, settings, [], match_row)


def test_source_shotpoints_filter_by_sequence_group() -> None:
    match_row = Postplot4DMatchRow(
        baseline_name="0103643A",
        baseline_kind="navplan",
        line_name="0103643A",
        subline="A",
        sequence_no="1",
        first_sp=100,
        last_sp=200,
        line_direction="90.0",
        sequence_id="line.p190|1|0103643A|source",
        baseline_file_name="0103643A.navplan",
    )
    positions = [
        PositionRecord(
            file_name="line.p190",
            record_type=RecordType.SOURCE,
            line_name="0103643A",
            vessel_id="",
            source_id="G01",
            point_num=100,
            x=1.0,
            y=2.0,
            subline="A",
            sequence_no="1",
        ),
        PositionRecord(
            file_name="other.p190",
            record_type=RecordType.SOURCE,
            line_name="0103643A",
            vessel_id="",
            source_id="G01",
            point_num=100,
            x=9.0,
            y=9.0,
            subline="A",
            sequence_no="1",
        ),
    ]
    sources = source_shotpoints_for_match(positions, match_row)
    assert list(sources) == [100]
    assert sources[100].x == 1.0


def test_conditional_color_range_matching_uses_absolute_values() -> None:
    assert MainWindow._conditional_range_matches(-3.0, "<=3")
    assert MainWindow._conditional_range_matches(3.0, "0-3")
    assert not MainWindow._conditional_range_matches(-3.01, "<=3")
    assert MainWindow._conditional_range_matches(-3.01, ">3")
    assert MainWindow._conditional_range_matches(3.0, ">=3")
    assert MainWindow._conditional_range_matches(3.0, "=>3")
    assert not MainWindow._conditional_range_matches(2.99, ">=3")
    assert MainWindow._conditional_range_matches(5.0, "<=5")
    assert MainWindow._conditional_range_matches(5.0, "=<5")
    assert not MainWindow._conditional_range_matches(5.01, "<=5")


def test_postplot_conditional_colors_round_trip_in_legend_config() -> None:
    config = LegendConfig(
        postplot_lines=[
            PostplotLegendEntry(
                name="Acceptance",
                conditional_colors=[
                    ConditionalColorRule(
                        diff_stat="radial",
                        range_value="0-3",
                        color="#22c55e",
                        opacity=0.75,
                    )
                ],
            )
        ]
    )
    restored = legend_from_dict(legend_to_dict(config))
    rule = restored.postplot_lines[0].conditional_colors[0]
    assert rule.diff_stat == "radial"
    assert rule.range_value == "0-3"
    assert rule.color == "#22c55e"
    assert rule.opacity == 0.75


def test_conditional_points_signature_uses_diff_stat_field() -> None:
    settings = ProjectSettings(
        legend_config=LegendConfig(
            postplot_lines=[
                PostplotLegendEntry(
                    name="Acceptance",
                    sequence_ids=["0103643A"],
                    conditional_colors=[
                        ConditionalColorRule(
                            diff_stat="radial",
                            range_value="0-3",
                            color="#22c55e",
                            opacity=0.75,
                        )
                    ],
                )
            ]
        )
    )

    signature = MainWindow._conditional_points_signature(settings, 7, (42, "2026-01-01T00:00:00Z"))

    assert signature[0] == 7
    assert signature[1] == (42, "2026-01-01T00:00:00Z")
    assert signature[2][0][3][0][0] == "radial"


def test_conditional_refresh_reruns_when_saved_diff_rows_appear(tmp_path) -> None:
    db = Database(tmp_path / "project.db")
    settings = ProjectSettings(
        name="4030",
        postplot_4d_baseline="navplan",
        legend_config=LegendConfig(
            postplot_lines=[
                PostplotLegendEntry(
                    name="Acceptance",
                    sequence_ids=["file.p190|1"],
                    sequence_filter_active=True,
                    conditional_colors=[
                        ConditionalColorRule(
                            diff_stat="radial",
                            range_value="0-3",
                            color="#22c55e",
                            opacity=0.75,
                        )
                    ],
                )
            ]
        ),
    )
    db.save_project(settings, MapData())
    window = MainWindow.__new__(MainWindow)
    window._settings = settings
    window._map_data = MapData()
    window._db = db
    window._match_diff_cache = {}
    window._match_diff_cache_version = -1
    window._conditional_data_version = 0
    window._conditional_points_signature_cache = None
    window._map = type(
        "MapStub",
        (),
        {
            "set_conditional_postplot_points": lambda self, points: setattr(
                self, "points", list(points)
            ),
        },
    )()
    window._map.points = []
    # The saved-diff rerun is what this test verifies; the background diff fill
    # is exercised separately, so keep it from spawning a real worker thread.
    window._ensure_conditional_diffs_async = lambda *_a, **_k: None
    match_row = Postplot4DMatchRow(
        baseline_name="baseline",
        baseline_kind="navplan",
        line_name="0103643A",
        subline="",
        sequence_no="1",
        first_sp=101,
        last_sp=101,
        line_direction="",
        sequence_id="file.p190|1",
        baseline_file_name="baseline.navplan",
    )

    with patch(
        "xpostmaps.ui.main_window.build_postplot_4d_rows",
        return_value=[match_row],
    ):
        MainWindow._refresh_conditional_postplot_points(window)

    assert window._map.points == []
    cached_after_empty = window._conditional_points_signature_cache
    assert cached_after_empty is not None

    saved = [
        Postplot4DDiffRow(
            shotpoint=101,
            baseline_x=1.0,
            baseline_y=2.0,
            baseline_latitude="",
            baseline_longitude="",
            source_x=4.0,
            source_y=6.0,
            source_latitude="",
            source_longitude="",
            crossline_m=1.5,
            inline_m=2.5,
            radial_m=2.0,
        )
    ]
    db.save_postplot_4d_diffs("4030", "navplan", "baseline", "file.p190|1", saved)

    with patch(
        "xpostmaps.ui.main_window.build_postplot_4d_rows",
        return_value=[match_row],
    ):
        MainWindow._refresh_conditional_postplot_points(window)

    assert len(window._map.points) == 1
    assert window._map.points[0][2] == "#22c55e"
    assert window._conditional_points_signature_cache != cached_after_empty
    db.close()


class _FakeSignal:
    def __init__(self) -> None:
        self.slots = []

    def connect(self, slot, *_a, **_k) -> None:
        self.slots.append(slot)


class _FakeDiffWorker:
    instances: list["_FakeDiffWorker"] = []

    def __init__(self, *_args, match_rows=None, **_kwargs) -> None:
        self.match_rows = list(match_rows or [])
        self.finished_batch = _FakeSignal()
        self.finished = _FakeSignal()
        self.started = False
        _FakeDiffWorker.instances.append(self)

    def isRunning(self) -> bool:  # noqa: N802
        return self.started

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.started = False


def _fill_stub_window(db) -> "MainWindow":
    window = MainWindow.__new__(MainWindow)
    window._settings = ProjectSettings(name="proj")
    window._map_data = MapData()
    window._db = db
    window._parsing = False
    window._loading_project = False
    window._conditional_data_version = 0
    window._conditional_diff_fill_worker = None
    window._conditional_diff_fill_attempted = set()
    window._conditional_diff_fill_attempted_version = -1
    return window


def _fill_match_row(sequence_id: str) -> Postplot4DMatchRow:
    return Postplot4DMatchRow(
        baseline_name="baseline",
        baseline_kind="navplan",
        line_name="L",
        subline="",
        sequence_no="1",
        first_sp=1,
        last_sp=1,
        line_direction="",
        sequence_id=sequence_id,
        baseline_file_name="baseline.navplan",
    )


def test_conditional_diff_fill_launches_worker_for_missing_rows(tmp_path) -> None:
    db = Database(tmp_path / "p.db")
    db.save_project(ProjectSettings(name="proj"), MapData())
    window = _fill_stub_window(db)
    rows = [_fill_match_row("a|1"), _fill_match_row("b|1")]

    _FakeDiffWorker.instances = []
    with patch("xpostmaps.ui.main_window.DiffStatRecalcWorker", _FakeDiffWorker):
        MainWindow._ensure_conditional_diffs_async(window, rows)
        # Re-invoking with the same already-attempted rows must not relaunch.
        MainWindow._ensure_conditional_diffs_async(window, rows)

    assert len(_FakeDiffWorker.instances) == 1
    assert {r.sequence_id for r in _FakeDiffWorker.instances[0].match_rows} == {"a|1", "b|1"}
    assert window._conditional_diff_fill_attempted == {"a|1", "b|1"}
    db.close()


def test_conditional_diff_fill_skips_when_no_missing_rows(tmp_path) -> None:
    db = Database(tmp_path / "p.db")
    db.save_project(ProjectSettings(name="proj"), MapData())
    window = _fill_stub_window(db)

    _FakeDiffWorker.instances = []
    with patch("xpostmaps.ui.main_window.DiffStatRecalcWorker", _FakeDiffWorker):
        MainWindow._ensure_conditional_diffs_async(window, [])

    assert _FakeDiffWorker.instances == []
    db.close()


def test_conditional_diff_cache_reads_saved_database_rows(tmp_path) -> None:
    db = Database(tmp_path / "project.db")
    settings = ProjectSettings(name="proj")
    db.save_project(settings, MapData())
    saved = [
        Postplot4DDiffRow(
            shotpoint=101,
            baseline_x=1.0,
            baseline_y=2.0,
            baseline_latitude="",
            baseline_longitude="",
            source_x=4.0,
            source_y=6.0,
            source_latitude="",
            source_longitude="",
            crossline_m=1.5,
            inline_m=2.5,
            radial_m=3.0,
        )
    ]
    db.save_postplot_4d_diffs("proj", "navplan", "baseline", "file.p190|1", saved)
    window = MainWindow.__new__(MainWindow)
    window._settings = settings
    window._map_data = MapData()
    window._db = db
    window._match_diff_cache = {}
    window._match_diff_cache_version = -1
    window._conditional_data_version = 0
    match_row = Postplot4DMatchRow(
        baseline_name="baseline",
        baseline_kind="navplan",
        line_name="0100001A",
        subline="",
        sequence_no="1",
        first_sp=101,
        last_sp=101,
        line_direction="",
        sequence_id="file.p190|1",
        baseline_file_name="baseline.navplan",
    )

    rows = MainWindow._cached_match_diff_rows(window, match_row, [])

    assert rows == saved
    assert db.postplot_4d_diffs_updated_at("proj", "navplan", "file.p190|1")
    grouped = db.load_all_postplot_4d_diffs("proj", "navplan")
    assert grouped == {"file.p190|1": saved}
    db.close()


def test_source_has_streamers_probe_distinguishes_real_files() -> None:
    """Streamer detection must be robust on real P111/P190 sources.

    Streamer surveys (0085 12-streamer P111, 10221 8-streamer P190) carry
    receiver records; firing-source-only exports (4030 P111V) do not. The probe
    must also see past the very large (~15k line) 10221 P190 header block.
    """
    from xpostmaps.core.postplot_4d_diff import source_has_streamers

    cases = [
        (Path("4D/0085.T26A.6054B085.a0085.SSFILTREG.p111"), True),
        (Path("4D/10221/P1/70.1065P1A-070.a070.p190"), True),
        (Path("4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111"), False),
    ]
    for path, expected in cases:
        if not path.is_file():
            continue
        assert source_has_streamers(path) is expected, path


def test_preplot_baseline_carries_line_feather_when_streamers_present() -> None:
    """Line Feather must populate for a PREPLOT baseline when the firing-source
    P111/P190 carries streamers (real 10221 8-streamer survey)."""
    from xpostmaps.core.models import MapData, ProjectSettings, RecordType
    from xpostmaps.core.postplot_4d_diff import calculate_match_diff_rows
    from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
    from xpostmaps.parsers.p190_parser import parse_p190_file
    from xpostmaps.parsers.preplot_parser import parse_preplot_files
    from xpostmaps.parsers.sequence_builder import build_display_sequences

    preplot = Path("4D/10221/Preplot/10221_AWA_Maui4D_v2.190")
    source = Path("4D/10221/P1/70.1065P1A-070.a070.p190")
    if not preplot.is_file() or not source.is_file():
        return  # dataset not present in this checkout

    segments, _meta, _stats = parse_preplot_files([preplot])
    src = [r for r in parse_p190_file(source) if r.record_type == RecordType.SOURCE]
    map_data = MapData()
    map_data.preplot_segments = segments
    map_data.positions = src
    map_data.sequences = build_display_sequences(src)
    map_data.postmap_info.epsg_code = "2193"
    settings = ProjectSettings(
        preplot_files=[str(preplot.resolve())],
        nav_files=[str(source.resolve())],
        postplot_4d_baseline="preplot",
    )
    rows = build_postplot_4d_rows(map_data, settings, "preplot")
    match_row = next(r for r in rows if r.has_match)

    diff_rows = calculate_match_diff_rows(map_data, settings, src, match_row)
    feathers = [r.line_feather_deg for r in diff_rows if r.line_feather_deg is not None]
    assert feathers, "preplot baseline must expose Line Feather when streamers exist"
    # 8-streamer averaged feather stays physically plausible.
    assert all(abs(v) < 45.0 for v in feathers)


def test_preplot_baseline_has_no_line_feather_for_firing_source_only() -> None:
    """Firing-source-only P111 (no receiver records) must leave Line Feather
    empty so the column stays hidden for a PREPLOT baseline (real 4030)."""
    from xpostmaps.core.models import MapData, ProjectSettings, RecordType
    from xpostmaps.core.postplot_4d_diff import calculate_match_diff_rows
    from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
    from xpostmaps.parsers.p111_parser import parse_p111_file
    from xpostmaps.parsers.preplot_parser import parse_preplot_files
    from xpostmaps.parsers.sequence_builder import build_display_sequences

    preplot = Path("4D/4030/Preplot/4030_Mariner4D_Preplots_v2.190")
    source = Path("4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111")
    if not preplot.is_file() or not source.is_file():
        return  # dataset not present in this checkout

    segments, _meta, _stats = parse_preplot_files([preplot])
    src = [r for r in parse_p111_file(source) if r.record_type == RecordType.SOURCE]
    map_data = MapData()
    map_data.preplot_segments = segments
    map_data.positions = src
    map_data.sequences = build_display_sequences(src)
    map_data.postmap_info.epsg_code = "23031"
    settings = ProjectSettings(
        preplot_files=[str(preplot.resolve())],
        nav_files=[str(source.resolve())],
        postplot_4d_baseline="preplot",
    )
    rows = build_postplot_4d_rows(map_data, settings, "preplot")
    match_row = next(r for r in rows if r.has_match)

    diff_rows = calculate_match_diff_rows(map_data, settings, src, match_row)
    assert diff_rows
    assert all(r.line_feather_deg is None for r in diff_rows)
