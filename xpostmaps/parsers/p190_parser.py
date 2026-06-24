"""P190 (UKOOA P1/90) fixed-width navigation file parser."""

from __future__ import annotations

import re
from pathlib import Path

from xpostmaps.core.models import PositionRecord, RecordType


_NUMERIC_VALUE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_LINE_SUBLINE_FILENAME_RE = re.compile(
    r"(?:^|[._\-\s])(?P<line>[A-Za-z0-9]+[A-Za-z0-9_-]*-\d+)[._\-\s]+(?P<subline>[A-Za-z]\w*)$",
    re.IGNORECASE,
)


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


def _canonical_header_key(key: str) -> str:
    """Normalize P190 H-record labels across dotted, spaced, and numbered forms."""
    key = key.strip().lower()
    key = re.sub(r"^\d+", "", key)
    return re.sub(r"[^a-z0-9/]+", "", key)


def _parse_header_value(line: str) -> tuple[str, str] | None:
    text = line[1:].strip()
    separator = ":" if ":" in text else "=" if "=" in text else ""
    if not separator:
        return None
    key, _, value = text.partition(separator)
    return _canonical_header_key(key), value.strip()


def _parse_linename_subline(value: str) -> tuple[str, str]:
    """Parse headers like ``/1065P1A-070/a070`` into line name and subline."""
    parts = [
        part.strip(" \t\r\n.:")
        for part in re.split(r"[/\\]+", value.strip())
        if part.strip(" \t\r\n.:")
    ]
    if not parts:
        return "", ""
    line_name = parts[0]
    subline = parts[1] if len(parts) > 1 else ""
    return line_name, subline


def _parse_linename_subline_from_filename(path: Path) -> tuple[str, str]:
    """Best-effort fallback for names like ``70.1065P1A-070.a070.p190``."""
    stem = path.stem.strip()
    match = _LINE_SUBLINE_FILENAME_RE.search(stem)
    if match:
        return match.group("line"), match.group("subline")
    parts = [part.strip() for part in re.split(r"[._\s]+", stem) if part.strip()]
    for index, part in enumerate(parts):
        if "-" not in part:
            continue
        if index + 1 < len(parts) and re.fullmatch(r"[A-Za-z]\w*", parts[index + 1]):
            return part, parts[index + 1]
    return "", ""


def _format_line_direction(value: str) -> str:
    match = _NUMERIC_VALUE_RE.search(value.replace(",", ""))
    if not match:
        return ""
    try:
        return f"{float(match.group(0)):.2f}°"
    except ValueError:
        return ""


def _is_linename_subline_key(key: str) -> bool:
    return "line" in key and "name" in key and "subline" in key


def _is_line_direction_key(key: str) -> bool:
    if not any(term in key for term in ("direction", "heading", "bearing", "azimuth")):
        return False
    # Prefer line-specific direction metadata; accept bare heading/bearing/azimuth
    # labels but avoid unrelated projection/origin definitions.
    if "line" in key:
        return True
    return key in {"heading", "bearing", "azimuth"}


def _is_sequence_key(key: str) -> bool:
    return "line" in key and "sequence" in key and "number" in key


def _apply_p190_header(
    line: str,
    state: dict[str, str],
    info: dict[str, str] | None = None,
) -> None:
    parsed = _parse_header_value(line)
    if parsed is None:
        return
    key, value = parsed
    if info is not None:
        info[key] = value
    if _is_linename_subline_key(key):
        line_name, subline = _parse_linename_subline(value)
        if line_name:
            state["line_name"] = line_name
        state["subline"] = subline
        if info is not None:
            info["linename/subline"] = value
            info["line name"] = line_name
            info["subline"] = subline
        return
    if _is_line_direction_key(key):
        formatted = _format_line_direction(value)
        if formatted:
            state["line_direction"] = formatted
            if info is not None:
                info["line direction"] = formatted
        return
    if _is_sequence_key(key):
        sequence_no = value.strip()
        if sequence_no:
            state["sequence_no"] = sequence_no
            if info is not None:
                info["line sequence number"] = sequence_no


def parse_p190_line(
    line: str,
    file_name: str,
    *,
    line_name_override: str = "",
    subline: str = "",
    line_direction: str = "",
    sequence_no: str = "",
) -> PositionRecord | None:
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
        line_name=line_name_override or _slice_field(line, 2, 13),
        vessel_id=_slice_field(line, 17, 17),
        source_id=_slice_field(line, 18, 18),
        point_num=_parse_int(_slice_field(line, 20, 25)),
        x=x,
        y=y,
        depth=depth if depth == depth else None,
        latitude=_slice_field(line, 26, 35),
        longitude=_slice_field(line, 36, 46),
        sequence_no=sequence_no,
        line_direction=line_direction,
        subline=subline,
    )


def parse_p190_file(path: Path) -> list[PositionRecord]:
    """Parse P190 navigation records, keeping one firing-source S record per shotpoint."""
    records: list[PositionRecord] = []
    file_name = path.name
    firing_by_shot: dict[tuple[str, int], PositionRecord] = {}
    fallback_line_name, fallback_subline = _parse_linename_subline_from_filename(path)
    header_state = {
        "line_name": fallback_line_name,
        "subline": fallback_subline,
        "line_direction": "",
        "sequence_no": "",
    }

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n\r")
            if line.startswith("H"):
                _apply_p190_header(line, header_state)
                continue
            rec = parse_p190_line(
                line,
                file_name,
                line_name_override=header_state["line_name"],
                subline=header_state["subline"],
                line_direction=header_state["line_direction"],
                sequence_no=header_state["sequence_no"],
            )
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
    fallback_line_name, fallback_subline = _parse_linename_subline_from_filename(path)
    state = {
        "line_name": fallback_line_name,
        "subline": fallback_subline,
        "line_direction": "",
        "sequence_no": "",
    }
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("H"):
                if line.startswith(("S", "V", "E", "R")):
                    break
                continue
            text = line[1:].strip()
            _apply_p190_header(line.rstrip("\n\r"), state, info)
            if ":" not in text and "=" not in text and len(text) > 10:
                info[f"header_{len(info)}"] = text
    if state["line_name"]:
        info.setdefault("line name", state["line_name"])
    if state["subline"]:
        info.setdefault("subline", state["subline"])
    return info
