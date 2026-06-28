"""Per-shotpoint vessel ID parsing for P111 (including multi-vessel lines)."""

from __future__ import annotations

from pathlib import Path

from xpostmaps.core.models import RecordType
from xpostmaps.parsers.p111_parser import parse_p111_file


def _hc_vessel(name: str, device_id: str) -> str:
    return (
        f"HC,2,3,0,{name:<48},1,{device_id},1,Vessel,,,,,,,"
        f"Vessel Reference Point,,,"
    )


def _hc_gun(name: str, device_id: str) -> str:
    return f"HC,2,3,0,{name:<48},1,{device_id},1,air gun array,,,,,,,,,,"


def _s1(line: str, shotpoint: int, gun: str, x: float, y: float) -> str:
    return (
        f"S1,0,{line},{line},{shotpoint},{shotpoint},1,1000000000.000,11,{gun},1,,"
        f"{x:.2f},{y:.2f},,0.0,0.0,,0.0,0.0,,0.0,0.0,0.0,,,"
    )


def _p1_vessel(line: str, shotpoint: int, vessel: str, x: float, y: float) -> str:
    return (
        f"P1,0,{line},{line},{shotpoint},{shotpoint},1,1000000000.000,1,{vessel},2,,"
        f"{x:.2f},{y:.2f},,0.0,0.0,,0.0,0.0,,0.0,0.0,0.0,,,"
    )


def _write_multi_vessel_p111(path: Path, body_lines: list[str]) -> None:
    header = [
        "CC,1,0,0,LINE SEQUENCE NUMBER =1",
        "CC,1,0,0,LINENAME/SUBLINE =MULTIV/L001",
        _hc_vessel("Vessel Alpha", "VES1"),
        _hc_vessel("Vessel Bravo", "VES2"),
        _hc_gun("Gun 01", "G01"),
        _hc_gun("Gun 02", "G02"),
    ]
    path.write_text("\n".join(header + body_lines) + "\n", encoding="utf-8")


def test_p111_multi_vessel_vessel_id_is_per_shotpoint(tmp_path: Path) -> None:
    path = tmp_path / "multi.p111"
    _write_multi_vessel_p111(
        path,
        [
            _s1("MULTIV", 100, "G01", 100.0, 200.0),
            _p1_vessel("MULTIV", 100, "VES1", 100.0, 200.0),
            _s1("MULTIV", 101, "G02", 125.0, 200.0),
            _p1_vessel("MULTIV", 101, "VES2", 125.0, 200.0),
            _s1("MULTIV", 102, "G01", 150.0, 200.0),
            _p1_vessel("MULTIV", 102, "VES1", 150.0, 200.0),
        ],
    )

    sources = {
        record.point_num: record
        for record in parse_p111_file(path)
        if record.record_type == RecordType.SOURCE
    }

    assert sources[100].vessel_id == "VES1"
    assert sources[100].source_id == "G01"
    assert sources[101].vessel_id == "VES2"
    assert sources[101].source_id == "G02"
    assert sources[102].vessel_id == "VES1"
    assert sources[102].source_id == "G01"


def test_p111_vessel_id_backfilled_when_p1_follows_later_s1(tmp_path: Path) -> None:
    """S1 for SP+1 can flush SP before its P1 row appears in the file."""
    path = tmp_path / "late_p1.p111"
    _write_multi_vessel_p111(
        path,
        [
            _s1("MULTIV", 100, "G01", 100.0, 200.0),
            _s1("MULTIV", 101, "G02", 125.0, 200.0),
            _p1_vessel("MULTIV", 100, "VES1", 100.0, 200.0),
            _p1_vessel("MULTIV", 101, "VES2", 125.0, 200.0),
        ],
    )

    sources = {
        record.point_num: record
        for record in parse_p111_file(path)
        if record.record_type == RecordType.SOURCE
    }

    assert sources[100].vessel_id == "VES1"
    assert sources[101].vessel_id == "VES2"


def test_p111_real_single_vessel_file_still_resolves_vessel_id() -> None:
    path = Path("4D/4030/P111V/003.0106067A-003.nrt.GFUNREG.p111")
    if not path.is_file():
        return

    sources = [
        record
        for record in parse_p111_file(path)
        if record.record_type == RecordType.SOURCE
    ]
    assert sources
    assert all(record.vessel_id == "AMU" for record in sources[:20])
    assert all(record.source_id for record in sources[:20])
