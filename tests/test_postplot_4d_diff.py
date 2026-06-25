from pathlib import Path
import math

from xpostmaps.core.coord_format import (
    dms_compact_to_decimal,
    format_dd_mm,
    format_geo_display,
)
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
    _read_preplot_header_info,
    compute_postplot_4d_diff_rows,
    parse_number_of_sources,
    parse_shotpoint_interval_m,
    parse_source_separation_m,
    resolve_line_azimuth_degrees,
    source_shotpoints_for_match,
)
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
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

    signature = MainWindow._conditional_points_signature(settings, 7)

    assert signature[0] == 7
    assert signature[1][0][3][0][0] == "radial"


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
    db.close()
