from pathlib import Path

from xpostmaps.parsers.p190_parser import parse_p190_file, parse_p190_header


def _p190_record(
    record_id: str,
    *,
    line_name: str = "OLDLINE",
    point_num: int = 1300,
    x: float = 6378137.0,
    y: float = 2982572.0,
) -> str:
    chars = [" "] * 80
    chars[0] = record_id

    def put(start: int, end: int, value: str) -> None:
        text = value[: end - start + 1].ljust(end - start + 1)
        chars[start - 1 : end] = list(text)

    put(2, 13, line_name)
    put(17, 17, "1")
    put(18, 18, "1")
    put(20, 25, str(point_num))
    put(47, 55, f"{x:9.1f}")
    put(56, 64, f"{y:9.1f}")
    return "".join(chars)


def test_p190_header_line_subline_and_direction_are_applied(tmp_path: Path) -> None:
    path = tmp_path / "sample.p190"
    path.write_text(
        "\n".join(
            [
                "H2600LINENAME/SUBLINE.........: /1065P1A-070/a070",
                "H2600LINE-DIRECTION...........: 179.9740",
                "H2600LINE SEQUENCE NUMBER.....: 270",
                _p190_record("S", point_num=1300),
                _p190_record("S", point_num=1600),
            ]
        ),
        encoding="utf-8",
    )

    records = parse_p190_file(path)

    assert len(records) == 2
    assert {record.line_name for record in records} == {"1065P1A-070"}
    assert {record.subline for record in records} == {"a070"}
    assert {record.line_direction for record in records} == {"179.97°"}
    assert {record.sequence_no for record in records} == {"270"}


def test_p190_header_exposes_canonical_metadata(tmp_path: Path) -> None:
    path = tmp_path / "sample.p190"
    path.write_text(
        "\n".join(
            [
                "H2600LINENAME/SUBLINE.........: /1065P1A-070/a070",
                "H2600LINE-DIRECTION...........: 179.9740",
                _p190_record("S"),
            ]
        ),
        encoding="utf-8",
    )

    metadata = parse_p190_header(path)

    assert metadata["line name"] == "1065P1A-070"
    assert metadata["subline"] == "a070"
    assert metadata["line direction"] == "179.97°"


def test_p190_filename_fallback_detects_subline_when_header_missing(tmp_path: Path) -> None:
    path = tmp_path / "70.1065P1A-070.a070.p190"
    path.write_text(_p190_record("S", line_name="1065P1A-070"), encoding="utf-8")

    records = parse_p190_file(path)
    metadata = parse_p190_header(path)

    assert len(records) == 1
    assert records[0].line_name == "1065P1A-070"
    assert records[0].subline == "a070"
    assert metadata["line name"] == "1065P1A-070"
    assert metadata["subline"] == "a070"


def test_p190_real_seq_070_sample_detects_subline() -> None:
    path = Path(r"c:\xPostMaps\Sample P111-P190\10221\70.1065P1A-070.a070.p190")
    if not path.exists():
        return

    records = parse_p190_file(path)

    assert records
    assert {record.line_name for record in records} == {"1065P1A-070"}
    assert {record.subline for record in records} == {"a070"}
    assert {record.line_direction for record in records} == {"179.97°"}
