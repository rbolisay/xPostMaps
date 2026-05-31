"""P111 (IOGP P1/11) CSV navigation file parser."""

from __future__ import annotations

import re
from pathlib import Path

from xpostmaps.core.models import PositionRecord, RecordType

# CC header card prefixes (from xp111.py)
CC_SEQUENCE_PREFIX = "CC,1,0,0,LINE SEQUENCE NUMBER ="
CC_LINENAME_PREFIX = "CC,1,0,0,LINENAME/SUBLINE ="
CC_LINE_DIRECTION_PREFIX = "CC,1,0,0,LINE-DIRECTION ="

# P1 record field indices (0-based after split)
P_REC_SPN_IDX = 4
P_REC_PREPLOT_IDX = 5
P_REC_DEVICE_ID_IDX = 9
P_REC_EASTING_IDX = 12
P_REC_NORTHING_IDX = 13
P_REC_LATITUDE_IDX = 15
P_REC_LONGITUDE_IDX = 16

# S1 record field indices
S1_REC_SPN_IDX = 4
S1_REC_PREPLOT_IDX = 5
S1_REC_SOURCE_FIRED_IDX = 9
S1_REC_EASTING_IDX = 12
S1_REC_NORTHING_IDX = 13
S1_REC_LATITUDE_IDX = 15
S1_REC_LONGITUDE_IDX = 16

# Legacy V1/S1 short-form indices (fallback when CC context is absent)
LEGACY_LINE_IDX = 1
LEGACY_POINT_IDX = 3
LEGACY_X_IDX = 11
LEGACY_Y_IDX = 12
LEGACY_LAT_IDX = 14
LEGACY_LON_IDX = 15

P111_RECORD_MAP: dict[str, RecordType] = {
    "S1": RecordType.SOURCE,
    "S2": RecordType.SOURCE,
    "V1": RecordType.VESSEL,
    "V2": RecordType.VESSEL,
}


def _parse_float(value: str) -> float:
    try:
        return float(value.replace(",", "").strip())
    except ValueError:
        return float("nan")


def _parse_int(value: str) -> int:
    try:
        return int(float(value.strip()))
    except ValueError:
        return 0


def _field(parts: list[str], index: int) -> str:
    if index < 0 or index >= len(parts):
        return ""
    return parts[index].strip()


def _format_line_direction(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.1f}°"


def scan_vessel_id(path: Path, scan_limit: int = 2000) -> str | None:
    """Scan P111 header for vessel device ID (matches xp111.py logic)."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for i, line in enumerate(handle):
                if i >= scan_limit:
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith(("P1,", "S1,", "R1,")):
                    break
                if not line.startswith("HC,2,"):
                    continue
                fields = line.split(",")
                if len(fields) <= 8:
                    continue
                device_id = _field(fields, 6)
                if not device_id:
                    continue
                device_type = _field(fields, 8).lower()
                description = _field(fields, 15) if len(fields) > 15 else ""
                is_vessel = device_type == "vessel" or description == "Vessel Reference Point"
                if is_vessel:
                    return device_id
    except OSError:
        return None
    return None


def _parse_legacy_line(
    line: str,
    file_name: str,
    record_type: RecordType,
) -> PositionRecord | None:
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 14:
        return None
    x = _parse_float(_field(parts, LEGACY_X_IDX))
    y = _parse_float(_field(parts, LEGACY_Y_IDX))
    if not (x == x and y == y):
        return None
    depth_val = _parse_float(_field(parts, 25)) if len(parts) > 25 else float("nan")
    return PositionRecord(
        file_name=file_name,
        record_type=record_type,
        line_name=_field(parts, LEGACY_LINE_IDX),
        vessel_id=_field(parts, 5),
        source_id=_field(parts, 8),
        point_num=_parse_int(_field(parts, LEGACY_POINT_IDX)),
        x=x,
        y=y,
        depth=depth_val if depth_val == depth_val else None,
        latitude=_field(parts, LEGACY_LAT_IDX),
        longitude=_field(parts, LEGACY_LON_IDX),
    )


def parse_p111_file(path: Path, vessel_id: str | None = None) -> list[PositionRecord]:
    """Parse vessel (P1) and source (S1) positions per shotpoint with sequence context."""
    records: list[PositionRecord] = []
    file_name = path.name

    if vessel_id is None:
        vessel_id = scan_vessel_id(path)

    current_sequence = "N/A"
    current_line_name = "N/A"
    current_subline = ""
    current_line_direction: float | None = None
    has_cc_headers = False

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith(CC_SEQUENCE_PREFIX):
                has_cc_headers = True
                try:
                    current_sequence = line.split("=", 1)[1].strip() or "N/A"
                except IndexError:
                    pass
                continue

            if line.startswith(CC_LINENAME_PREFIX):
                has_cc_headers = True
                try:
                    parts = line.split("=", 1)[1].strip()
                    name_parts = [p for p in parts.split("/") if p]
                    current_line_name = name_parts[0] if name_parts else "N/A"
                    current_subline = name_parts[1] if len(name_parts) > 1 else ""
                except (IndexError, ValueError):
                    pass
                continue

            if line.startswith(CC_LINE_DIRECTION_PREFIX):
                has_cc_headers = True
                try:
                    current_line_direction = float(line.split("=", 1)[1].strip())
                except (IndexError, ValueError, TypeError):
                    current_line_direction = None
                continue

            if line.startswith("S1,"):
                fields = line.split(",")
                min_fields = max(
                    S1_REC_SPN_IDX,
                    S1_REC_EASTING_IDX,
                    S1_REC_NORTHING_IDX,
                    S1_REC_LATITUDE_IDX,
                    S1_REC_LONGITUDE_IDX,
                ) + 1
                if len(fields) < min_fields:
                    continue
                x = _parse_float(_field(fields, S1_REC_EASTING_IDX))
                y = _parse_float(_field(fields, S1_REC_NORTHING_IDX))
                if not (x == x and y == y):
                    continue
                line_name = current_line_name if has_cc_headers else _field(fields, LEGACY_LINE_IDX)
                records.append(
                    PositionRecord(
                        file_name=file_name,
                        record_type=RecordType.SOURCE,
                        line_name=line_name or "UNNAMED",
                        vessel_id="",
                        source_id=_field(fields, S1_REC_SOURCE_FIRED_IDX),
                        point_num=_parse_int(_field(fields, S1_REC_SPN_IDX)),
                        x=x,
                        y=y,
                        latitude=_field(fields, S1_REC_LATITUDE_IDX),
                        longitude=_field(fields, S1_REC_LONGITUDE_IDX),
                        sequence_no=current_sequence,
                        line_direction=_format_line_direction(current_line_direction),
                        subline=current_subline,
                    )
                )
                continue

            if line.startswith("P1,") and vessel_id:
                fields = line.split(",")
                if len(fields) <= max(P_REC_SPN_IDX, P_REC_DEVICE_ID_IDX):
                    continue
                device_id = _field(fields, P_REC_DEVICE_ID_IDX)
                if device_id != vessel_id:
                    continue
                if len(fields) <= max(P_REC_EASTING_IDX, P_REC_NORTHING_IDX):
                    continue
                x = _parse_float(_field(fields, P_REC_EASTING_IDX))
                y = _parse_float(_field(fields, P_REC_NORTHING_IDX))
                if not (x == x and y == y):
                    continue
                records.append(
                    PositionRecord(
                        file_name=file_name,
                        record_type=RecordType.VESSEL,
                        line_name=current_line_name or "UNNAMED",
                        vessel_id=device_id,
                        source_id="",
                        point_num=_parse_int(_field(fields, P_REC_SPN_IDX)),
                        x=x,
                        y=y,
                        depth=None,
                        latitude=_field(fields, P_REC_LATITUDE_IDX),
                        longitude=_field(fields, P_REC_LONGITUDE_IDX),
                        sequence_no=current_sequence,
                        line_direction=_format_line_direction(current_line_direction),
                        subline=current_subline,
                    )
                )
                continue

            record_id = line.split(",", 1)[0].upper()
            record_type: RecordType | None = P111_RECORD_MAP.get(record_id)
            if record_type is None:
                if record_id.startswith("S"):
                    record_type = RecordType.SOURCE
                elif record_id.startswith("V"):
                    record_type = RecordType.VESSEL
                else:
                    continue
            legacy = _parse_legacy_line(line, file_name, record_type)
            if legacy is not None:
                if has_cc_headers:
                    legacy.sequence_no = current_sequence
                    legacy.line_direction = _format_line_direction(current_line_direction)
                    legacy.subline = current_subline
                    if current_line_name != "N/A":
                        legacy.line_name = current_line_name
                records.append(legacy)

    return records


def parse_p111_header(path: Path) -> dict[str, str]:
    info: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped.startswith("H"):
                if re.match(r"^[SVEFRP]", stripped):
                    break
                continue
            text = stripped[1:].lstrip(",").strip()
            if "," in text:
                parts = [p.strip() for p in text.split(",")]
                if len(parts) >= 2:
                    info[parts[0].lower()] = parts[1]
            elif ":" in text:
                key, _, value = text.partition(":")
                info[key.strip().lower()] = value.strip()
    return info
