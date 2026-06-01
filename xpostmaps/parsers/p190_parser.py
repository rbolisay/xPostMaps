"""P190 (UKOOA P1/90) fixed-width navigation file parser."""

from __future__ import annotations

from pathlib import Path

from xpostmaps.core.models import PositionRecord, RecordType


def _slice_field(line: str, start: int, end: int) -> str:
    if len(line) < start:
        return ""
    return line[start - 1 : end].strip()


def _parse_float(value: str) -> float:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return float("nan")


def _parse_int(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        return 0


def parse_p190_line(line: str, file_name: str) -> PositionRecord | None:
    """Parse a single P190 position record.

    Source positions use the firing-source ``S`` record only.
    Vessel positions use the ``V`` record. All other record types are ignored.
    """
    if len(line) < 64:
        return None

    record_id = line[0].upper()
    if record_id == "S":
        record_type = RecordType.SOURCE
    elif record_id == "V":
        record_type = RecordType.VESSEL
    else:
        return None

    x = _parse_float(_slice_field(line, 47, 55))
    y = _parse_float(_slice_field(line, 56, 64))
    if not (x == x and y == y):  # NaN check
        return None

    depth_str = _slice_field(line, 65, 70)
    depth = _parse_float(depth_str) if depth_str else None

    return PositionRecord(
        file_name=file_name,
        record_type=record_type,
        line_name=_slice_field(line, 2, 13),
        vessel_id=_slice_field(line, 17, 17),
        source_id=_slice_field(line, 18, 18),
        point_num=_parse_int(_slice_field(line, 20, 25)),
        x=x,
        y=y,
        depth=depth if depth == depth else None,
        latitude=_slice_field(line, 26, 35),
        longitude=_slice_field(line, 36, 46),
    )


def parse_p190_file(path: Path) -> list[PositionRecord]:
    """Parse P190 navigation records, keeping one firing-source S record per shotpoint."""
    records: list[PositionRecord] = []
    file_name = path.name
    firing_by_shot: dict[tuple[str, int], PositionRecord] = {}

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            rec = parse_p190_line(line.rstrip("\n\r"), file_name)
            if rec is None:
                continue
            if rec.record_type == RecordType.SOURCE:
                key = (rec.line_name.strip() or "UNNAMED", rec.point_num)
                firing_by_shot[key] = rec
                continue
            records.append(rec)

    records.extend(firing_by_shot.values())
    return records


def parse_p190_header(path: Path) -> dict[str, str]:
    """Extract metadata from H records in a P190 file."""
    info: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("H"):
                if line.startswith(("S", "V", "E", "R")):
                    break
                continue
            text = line[1:].strip()
            if ":" in text:
                key, _, value = text.partition(":")
                info[key.strip().lower()] = value.strip()
            elif len(text) > 10:
                info[f"header_{len(info)}"] = text
    return info
