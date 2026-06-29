from pathlib import Path

from xpostmaps.core.models import (
    LineSegment,
    LineSequence,
    MapData,
    NavplanCatalogEntry,
    PreplotCatalogEntry,
    ProjectSettings,
    RecordType,
)
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
from xpostmaps.parsers.preplot_parser import parse_preplot_files


ROOT = Path(__file__).resolve().parents[1]


def _sequence(line_name: str, sequence_no: str = "1") -> LineSequence:
    return LineSequence(
        seq_id=f"post.p190|{sequence_no}|{line_name}",
        file_name="post.p190",
        sequence_no=sequence_no,
        line_name=line_name,
        subline="A",
        line_direction="Up",
        first_sp=100,
        last_sp=200,
        record_type=RecordType.SOURCE,
    )


def test_navplan_matching_uses_noisy_header_name_tokens() -> None:
    settings = ProjectSettings(
        navplan_catalog=[
            NavplanCatalogEntry(
                navplan_number=1,
                navplan_name="H2600PREPLOT LINE NUMBER......: 0103643A extra text",
                file_path=r"C:\sample\0103643A.navplan",
            )
        ]
    )
    map_data = MapData(
        sequences=[_sequence("0103643A")],
        navplan_segments=[
            LineSegment(
                line_name="unrelated segment name",
                record_type=RecordType.NAVPLAN,
                file_name="0103643A.navplan",
            )
        ],
    )

    rows = build_postplot_4d_rows(map_data, settings, "navplan")

    assert len(rows) == 1
    assert rows[0].has_match
    assert rows[0].line_name == "0103643A"


def test_preplot_matching_handles_p111_and_p190_line_names() -> None:
    settings = ProjectSettings(
        preplot_catalog=[PreplotCatalogEntry(preplot_number=1, file_path=r"C:\sample\preplot.p111")]
    )
    map_data = MapData(
        sequences=[_sequence("1018"), _sequence("51892")],
        preplot_segments=[
            LineSegment(
                line_name="N1 preplot line 1018",
                record_type=RecordType.PREPLOT,
                file_name="preplot.p111",
            ),
            LineSegment(
                line_name="51892",
                record_type=RecordType.PREPLOT,
                file_name="preplot.p190",
            ),
        ],
    )

    rows = build_postplot_4d_rows(map_data, settings, "preplot")
    matched = {(row.baseline_name, row.line_name) for row in rows if row.has_match}

    assert ("N1 preplot line 1018", "1018") in matched
    assert ("51892", "51892") in matched


def test_preplot_matching_does_not_use_project_or_sequence_number_tokens() -> None:
    map_data = MapData(
        sequences=[
            LineSequence(
                seq_id="15762317027.p190|7027|15762317027",
                file_name="15762317027_7027.p190",
                sequence_no="7027",
                line_name="15762317027",
                subline="a7027",
                line_direction="305.0",
                first_sp=54409,
                last_sp=54899,
                record_type=RecordType.SOURCE,
            )
        ],
        preplot_segments=[
            LineSegment(
                line_name="51892",
                record_type=RecordType.PREPLOT,
                file_name="7027_S_TRINAV_v2.p190",
            )
        ],
    )

    rows = build_postplot_4d_rows(map_data, ProjectSettings(), "preplot")

    assert len(rows) == 1
    assert not rows[0].has_match
    assert rows[0].baseline_name == "51892"


def test_preplot_matching_handles_trinav_embedded_line_ids() -> None:
    map_data = MapData(
        sequences=[
            LineSequence(
                seq_id="3001.51892113001.a3001.GFUNREG.p111|3001|51892113001",
                file_name="3001.51892113001.a3001.GFUNREG.p111",
                sequence_no="3001",
                line_name="51892113001",
                subline="a3001",
                line_direction="305.0",
                first_sp=100,
                last_sp=200,
                record_type=RecordType.SOURCE,
            ),
            LineSequence(
                seq_id="3002.51980113002.a3002.GFUNREG.p111|3002|51980113002",
                file_name="3002.51980113002.a3002.GFUNREG.p111",
                sequence_no="3002",
                line_name="51980113002",
                subline="a3002",
                line_direction="305.0",
                first_sp=100,
                last_sp=200,
                record_type=RecordType.SOURCE,
            ),
        ],
        preplot_segments=[
            LineSegment(
                line_name="51892",
                record_type=RecordType.PREPLOT,
                file_name="7027_S_TRINAV_v2.p190",
            ),
            LineSegment(
                line_name="51980",
                record_type=RecordType.PREPLOT,
                file_name="7027_S_TRINAV_v2.p190",
            ),
            LineSegment(
                line_name="51900",
                record_type=RecordType.PREPLOT,
                file_name="7027_S_TRINAV_v2.p190",
            ),
        ],
    )

    rows = build_postplot_4d_rows(map_data, ProjectSettings(), "preplot")
    matched = {(row.baseline_name, row.line_name, row.sequence_no) for row in rows if row.has_match}

    assert matched == {
        ("51892", "51892113001", "3001"),
        ("51980", "51980113002", "3002"),
    }
    assert ("51900", "", "") not in matched


def test_preplot_matching_handles_trinav_l_suffix_line_ids() -> None:
    map_data = MapData(
        sequences=[
            LineSequence(
                seq_id="3224.531401L0224.a3224.GFUNREG.p111|3224|531401L0224",
                file_name="3224.531401L0224.a3224.GFUNREG.p111",
                sequence_no="3224",
                line_name="531401L0224",
                subline="a3224",
                line_direction="305.0",
                first_sp=100,
                last_sp=200,
                record_type=RecordType.SOURCE,
            ),
            LineSequence(
                seq_id="3227.531242L0227.a3227.GFUNREG.p111|3227|531242L0227",
                file_name="3227.531242L0227.a3227.GFUNREG.p111",
                sequence_no="3227",
                line_name="531242L0227",
                subline="a3227",
                line_direction="305.0",
                first_sp=100,
                last_sp=200,
                record_type=RecordType.SOURCE,
            ),
        ],
        preplot_segments=[
            LineSegment(
                line_name="53140",
                record_type=RecordType.PREPLOT,
                file_name="7027_S_TRINAV_v2.p190",
            ),
            LineSegment(
                line_name="53124",
                record_type=RecordType.PREPLOT,
                file_name="7027_S_TRINAV_v2.p190",
            ),
        ],
    )

    rows = build_postplot_4d_rows(map_data, ProjectSettings(), "preplot")
    matched = {(row.baseline_name, row.line_name) for row in rows if row.has_match}

    assert matched == {
        ("53140", "531401L0224"),
        ("53124", "531242L0227"),
    }


def test_preplot_prefix_matching_prefers_longest_preplot_id() -> None:
    map_data = MapData(
        sequences=[
            LineSequence(
                seq_id="3004.51988113004.a3004.GFUNREG.p111|3004|51988113004",
                file_name="3004.51988113004.a3004.GFUNREG.p111",
                sequence_no="3004",
                line_name="51988113004",
                subline="a3004",
                line_direction="305.0",
                first_sp=100,
                last_sp=200,
                record_type=RecordType.SOURCE,
            )
        ],
        preplot_segments=[
            LineSegment(
                line_name="51980",
                record_type=RecordType.PREPLOT,
                file_name="7027_S_TRINAV_v2.p190",
            ),
            LineSegment(
                line_name="51988",
                record_type=RecordType.PREPLOT,
                file_name="7027_S_TRINAV_v2.p190",
            ),
        ],
    )

    rows = build_postplot_4d_rows(map_data, ProjectSettings(), "preplot")
    matched = [row for row in rows if row.has_match]

    assert len(matched) == 1
    assert matched[0].baseline_name == "51988"
    assert matched[0].line_name == "51988113004"


def test_single_preplot_baseline_creates_extra_rows_for_multiple_matches() -> None:
    map_data = MapData(
        sequences=[
            _sequence("1486A177", sequence_no="177"),
            _sequence("1486A178", sequence_no="178"),
        ],
        preplot_segments=[
            LineSegment(
                line_name="1486",
                record_type=RecordType.PREPLOT,
                file_name="3190_TTUD1_Main_v2.WGS84.p190",
            )
        ],
    )

    rows = build_postplot_4d_rows(map_data, ProjectSettings(), "preplot")
    matched = [(row.baseline_name, row.line_name, row.sequence_no) for row in rows if row.has_match]

    assert matched == [
        ("1486", "1486A177", "177"),
        ("1486", "1486A178", "178"),
    ]


def test_navplan_matching_ignores_file_format_tokens() -> None:
    settings = ProjectSettings(
        navplan_catalog=[
            NavplanCatalogEntry(
                navplan_number=1,
                navplan_name="1005P1",
                file_path=r"C:\sample\1005P1.p190",
            ),
            NavplanCatalogEntry(
                navplan_number=2,
                navplan_name="1065P1",
                file_path=r"C:\sample\1065P1.p190",
            ),
        ]
    )
    map_data = MapData(
        sequences=[_sequence("1065P1A-070", sequence_no="70")],
        navplan_segments=[
            LineSegment(
                line_name="1005P1",
                record_type=RecordType.NAVPLAN,
                file_name="1005P1.p190",
            ),
            LineSegment(
                line_name="1065P1",
                record_type=RecordType.NAVPLAN,
                file_name="1065P1.p190",
            ),
        ],
    )

    rows = build_postplot_4d_rows(map_data, settings, "navplan")
    matched = [(row.baseline_name, row.line_name) for row in rows if row.has_match]
    unmatched = [row.baseline_name for row in rows if not row.has_match]

    assert matched == [("1065P1", "1065P1A-070")]
    assert unmatched == ["1005P1"]


def test_baseline_parent_name_matches_contained_imported_line_name() -> None:
    settings = ProjectSettings(
        navplan_catalog=[
            NavplanCatalogEntry(
                navplan_number=1,
                navplan_name="1065P",
                file_path=r"C:\sample\1065P.p190",
            )
        ]
    )
    map_data = MapData(
        sequences=[
            LineSequence(
                seq_id="70.1065P1A-070.a070.p190|70|1065P1A-070",
                file_name="70.1065P1A-070.a070.p190",
                sequence_no="70",
                line_name="1065P1A-070",
                subline="a070",
                line_direction="179.97",
                first_sp=1300,
                last_sp=1600,
                record_type=RecordType.SOURCE,
            )
        ],
        navplan_segments=[
            LineSegment(
                line_name="1065P",
                record_type=RecordType.NAVPLAN,
                file_name="1065P.p190",
            )
        ],
    )

    rows = build_postplot_4d_rows(map_data, settings, "navplan")

    assert len(rows) == 1
    assert rows[0].has_match
    assert rows[0].baseline_name == "1065P"
    assert rows[0].line_name == "1065P1A-070"
    assert rows[0].sequence_no == "70"


def test_4030_prefixed_imported_line_maps_to_zero_prefixed_baseline() -> None:
    settings = ProjectSettings(
        navplan_catalog=[
            NavplanCatalogEntry(
                navplan_number=1,
                navplan_name="0114451U",
                file_path=r"C:\sample\0114451U.navplan",
            ),
            NavplanCatalogEntry(
                navplan_number=2,
                navplan_name="0116269V",
                file_path=r"C:\sample\0116269V.navplan",
            ),
        ]
    )
    map_data = MapData(
        sequences=[
            _sequence("8114451U-032", sequence_no="32"),
            _sequence("8116269V-031", sequence_no="31"),
        ],
        navplan_segments=[
            LineSegment(
                line_name="0114451U",
                record_type=RecordType.NAVPLAN,
                file_name="0114451U.navplan",
            ),
            LineSegment(
                line_name="0116269V",
                record_type=RecordType.NAVPLAN,
                file_name="0116269V.navplan",
            ),
        ],
    )

    rows = build_postplot_4d_rows(map_data, settings, "navplan")
    matched = {(row.baseline_name, row.line_name, row.sequence_no) for row in rows if row.has_match}

    assert matched == {
        ("0114451U", "8114451U-032", "32"),
        ("0116269V", "8116269V-031", "31"),
    }


def test_4030_single_digit_prefix_line_maps_to_zero_prefixed_baseline() -> None:
    settings = ProjectSettings(
        navplan_catalog=[
            NavplanCatalogEntry(
                navplan_number=1,
                navplan_name="0116875A",
                file_path=r"C:\sample\0116875A.navplan",
            )
        ]
    )
    map_data = MapData(
        sequences=[_sequence("1116875A-038", sequence_no="38")],
        navplan_segments=[
            LineSegment(
                line_name="0116875A",
                record_type=RecordType.NAVPLAN,
                file_name="0116875A.navplan",
            )
        ],
    )

    rows = build_postplot_4d_rows(map_data, settings, "navplan")

    assert len(rows) == 1
    assert rows[0].has_match
    assert rows[0].baseline_name == "0116875A"
    assert rows[0].line_name == "1116875A-038"


def test_3190_preplot_name_matches_acquired_header_prefix() -> None:
    map_data = MapData(
        sequences=[_sequence("1486A177", sequence_no="0177")],
        preplot_segments=[
            LineSegment(
                line_name="1486",
                record_type=RecordType.PREPLOT,
                file_name="3190_TTUD1_Main_v2.WGS84.p190",
            )
        ],
    )

    rows = build_postplot_4d_rows(map_data, ProjectSettings(), "preplot")

    assert len(rows) == 1
    assert rows[0].has_match
    assert rows[0].baseline_name == "1486"
    assert rows[0].line_name == "1486A177"


def test_3190_preplot_name_matches_acquired_filename_fallback() -> None:
    map_data = MapData(
        sequences=[
            LineSequence(
                seq_id="0003.T26A.1018A003.c0003.GFUNREG.VES.p111|0003|UNNAMED",
                file_name="0003.T26A.1018A003.c0003.GFUNREG.VES.p111",
                sequence_no="0003",
                line_name="UNNAMED",
                subline="",
                line_direction="",
                first_sp=100,
                last_sp=200,
                record_type=RecordType.SOURCE,
            )
        ],
        preplot_segments=[
            LineSegment(
                line_name="1018",
                record_type=RecordType.PREPLOT,
                file_name="3190_TTUD1_Main_v2.WGS84.p190",
            )
        ],
    )

    rows = build_postplot_4d_rows(map_data, ProjectSettings(), "preplot")

    assert len(rows) == 1
    assert rows[0].has_match
    assert rows[0].baseline_name == "1018"
    assert rows[0].line_name == "UNNAMED"


def test_3190_real_preplot_lines_match_header_and_filename_cases() -> None:
    preplot = ROOT / "Sample Preplots" / "3190_TTUD1_Main_v2.WGS84.p190"
    segments, _meta, _stats = parse_preplot_files([preplot])
    selected = [segment for segment in segments if segment.line_name in {"1018", "1486"}]
    map_data = MapData(
        sequences=[
            _sequence("1486A177", sequence_no="0177"),
            LineSequence(
                seq_id="0003.T26A.1018A003.c0003.GFUNREG.VES.p111|0003|UNNAMED",
                file_name="0003.T26A.1018A003.c0003.GFUNREG.VES.p111",
                sequence_no="0003",
                line_name="UNNAMED",
                subline="",
                line_direction="",
                first_sp=100,
                last_sp=200,
                record_type=RecordType.SOURCE,
            ),
        ],
        preplot_segments=selected,
    )

    rows = build_postplot_4d_rows(map_data, ProjectSettings(), "preplot")
    matched = {(row.baseline_name, row.line_name) for row in rows if row.has_match}

    assert matched == {
        ("1018", "UNNAMED"),
        ("1486", "1486A177"),
    }


def test_find_match_by_sequence_no_and_sort_key() -> None:
    from xpostmaps.core.postplot_4d_matching import (
        Postplot4DMatchRow,
        find_match_by_sequence_no,
        sequence_sort_key,
    )

    def _row(sequence_no: str) -> Postplot4DMatchRow:
        return Postplot4DMatchRow(
            baseline_name="B",
            baseline_kind="preplot",
            line_name="L",
            subline=f"c{sequence_no}",
            sequence_no=sequence_no,
            first_sp=1,
            last_sp=10,
            line_direction="Up",
            sequence_id=f"file|{sequence_no}|L",
        )

    rows = [_row("0020"), _row("0003")]

    assert find_match_by_sequence_no(rows, "3") is rows[1]
    assert find_match_by_sequence_no(rows, "0020") is rows[0]
    assert find_match_by_sequence_no(rows, "999") is None
    assert find_match_by_sequence_no(rows, "") is None
    assert [r.sequence_no for r in sorted(rows, key=sequence_sort_key)] == [
        "0003",
        "0020",
    ]
