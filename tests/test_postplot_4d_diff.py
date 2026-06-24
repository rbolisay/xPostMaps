from pathlib import Path
import math

from xpostmaps.core.coord_format import (
    dms_compact_to_decimal,
    format_dd_mm,
    format_geo_display,
)
from xpostmaps.core.models import PositionRecord, RecordType
from xpostmaps.core.postplot_4d_diff import (
    BaselineShotpoint,
    _generate_preplot_shotpoints,
    _read_preplot_header_info,
    compute_postplot_4d_diff_rows,
    parse_shotpoint_interval_m,
    resolve_line_azimuth_degrees,
    source_shotpoints_for_match,
)
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.parsers.preplot_parser import parse_preplot_file


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


def test_shotpoint_interval_parser_handles_sample_header_styles() -> None:
    assert parse_shotpoint_interval_m(
        "CC,1,0,0,SHOT POINT INTERVAL       16.667 m"
    ) == 16.667
    assert parse_shotpoint_interval_m("H2600SHOT POINT INTERVAL       25.0 m") == 25.0
    assert parse_shotpoint_interval_m("H2600SHOT INTERVAL ...........: 25.0000") == 25.0
    assert parse_shotpoint_interval_m("H2600 SHOT POINT INTERVAL.....: 25.000000") == 25.0
    assert parse_shotpoint_interval_m("H2600STREAMER SEPARATION       112.50 m") is None
    assert parse_shotpoint_interval_m("H2600SHOT INCREMENT ..........: 1") is None


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
